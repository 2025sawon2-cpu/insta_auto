import base64
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from hotpost import source_finder as finder, source_topic_queries as topic
from hotpost import source_topic_replanning as recovery
from hotpost import source_preparation as prep
from hotpost.source_visual_queries import digest, VisualQueryRejection



import copy
import json
from pathlib import Path
import pytest
from test_source_topic_queries import topic_case
from test_topic_replanning_provenance import saved_failure, invoke
from hotpost.source_topic_replanning import acquire_topic_queries
from hotpost import source_topic_queries as topic
from hotpost.source_visual_queries import digest
from test_topic_replanning_preparation_incident import (
    incident_case, test_preserved_incident_reaches_real_preparation_stage,
    test_preparation_rejects_changed_binding_or_media)


def test_windows_replanning_path_is_flat_and_keeps_original_receipts(topic_case,monkeypatch):
    c=topic_case
    evidence,bad,review,original=saved_failure(c)
    before={p.name:p.read_bytes() for p in original.iterdir()}
    real_mkdir=Path.mkdir
    def windows_mkdir(path,*args,**kwargs):
        if 'provenance-replanning' in path.parts:
            raise FileNotFoundError(2,'Preserved Windows nested cache path exceeds limit',str(path))
        return real_mkdir(path,*args,**kwargs)
    monkeypatch.setattr(Path,'mkdir',windows_mkdir)
    fresh=copy.deepcopy(bad)
    fresh['subject_identity']['required_terms'][0].update(source='caption',quote='디올 향수')
    calls=[]
    def external(settings,instruction,data,**kwargs):
        assert settings.data_dir==c.tmp_path
        calls.append(data)
        if 'proposal_sha256' not in data:return copy.deepcopy(fresh)
        return {**review,'proposal_sha256':data['proposal_sha256']}
    receipt=invoke(c,acquire_topic_queries,external)
    assert len(topic.verify(receipt))==10 and len(calls)==2
    assert all((original/name).read_bytes()==raw for name,raw in before.items())
    caches=list((c.tmp_path/'source-topic-query-receipts').iterdir())
    assert len(caches)==2 and all(len(p.name)==64 for p in caches)
    assert all(p.parent==original.parent for p in caches)
    assert receipt['replanning_key']==digest(calls[0]['planning_feedback'])
    assert invoke(c,acquire_topic_queries,lambda *a,**k:pytest.fail('cached response must be reused'))==receipt
    saved=next(p/'receipt.json' for p in caches if (p/'receipt.json').is_file())
    value=json.loads(saved.read_text('utf8'));value['replanning_key']='0'*64
    saved.write_text(json.dumps(value),encoding='utf8')
    with pytest.raises(ValueError,match='cache differs'):
        invoke(c,acquire_topic_queries,lambda *a,**k:pytest.fail('must reject altered binding'))


def test_explicit_retry_command_preserves_current_failed_incident(incident_case,tmp_path):
    from hotpost.config import Settings
    from hotpost.studio import Studio
    c=incident_case
    state=copy.deepcopy(c.original['task']);job=copy.deepcopy(c.original['job'])
    assert job['status']=='failed' and job['kind']=='collect_sources'
    assert job['checkpoint']['failure_classification']['category']=='storage'
    assert 'provenance-replanning' in job['error']
    before=copy.deepcopy(job['checkpoint']);waiting=copy.deepcopy(state['source_acquisition'].get('waiting'))
    service=Studio(Settings(data_dir=tmp_path/'command'),workers=False)
    # Public URL serialization of production artifact paths is outside this command test.
    service.public=lambda value:value
    try:
        with service.store.transaction() as db:
            db.execute('INSERT INTO tasks(id,shortcode,revision,state,updated) VALUES(?,?,?,?,?)',
                (state['id'],state['shortcode'],state['revision'],json.dumps(state),1))
            columns=['id','task_id','kind','status','payload','key','checkpoint','created','updated','error']
            values=[json.dumps(job[k]) if isinstance(job[k],(dict,list)) else job[k] for k in columns]
            db.execute('INSERT INTO jobs('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',values)
        service.action(state['id'],'retry',{'revision':state['revision'],'job_id':job['id']})
        after=service.store.get(state['id'])
        with service.store.connect() as db:
            saved=db.execute('SELECT * FROM jobs WHERE id=?',(job['id'],)).fetchone()
            assert saved['status']=='queued'
            cp=json.loads(saved['checkpoint'])
            assert cp['failure_classification']==before['failure_classification']
            assert cp['failure_trace']==before['failure_trace']
            assert json.loads(saved['payload'])==job['payload']
            assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==1
        assert after['run_id']==state['run_id']
        assert after['source_acquisition'].get('waiting')==waiting
        assert after['scripts']==state['scripts'] and after['voices']==state['voices']
    finally:service.close()

def test_explicit_command_claim_to_persisted_preparation(incident_case,tmp_path,monkeypatch):
    import time
    from pathlib import PureWindowsPath
    from hotpost.config import Settings
    from hotpost.studio_store import StudioStore
    from hotpost.studio_sources import SourceAcquisitionMixin
    c=incident_case
    state=copy.deepcopy(c.original['task']);job=copy.deepcopy(c.original['job'])
    original_failure=copy.deepcopy(job['checkpoint']['failure_trace'])
    original_wait=copy.deepcopy(state['source_acquisition']['waiting'])
    old_sha=c.original['task']['source_acquisition']['visual_query_rejection']['reference_sha256']
    paths={c.original['task']['reference_video']:str(c.reference.resolve())}
    for original,temporary in zip(c.original['task']['source_acquisition']['visual_query_rejection']['evidence']['frames'],c.frames):
        paths[original['path']]=str(temporary.resolve())
    for row in c.original['artifacts']:
        p=PureWindowsPath(row['path'])
        if 'source_jobs' in p.parts:
            index=p.parts.index('source_jobs')
            paths.setdefault(row['path'],str(tmp_path.joinpath(*p.parts[index:]).resolve()))
    def remap(value):
        if isinstance(value,dict):return {k:remap(v) for k,v in value.items()}
        if isinstance(value,list):return [remap(v) for v in value]
        if isinstance(value,str):
            if value==old_sha:return prep.digest(c.reference)
            if value in paths:return paths[value]
            parts=PureWindowsPath(value).parts
            if 'source_jobs' in parts:
                return str(tmp_path.joinpath(*parts[parts.index('source_jobs'):]).resolve())
            if PureWindowsPath(value).is_absolute():
                return str((tmp_path/'other'/hashlib.sha256(value.encode()).hexdigest()).resolve())
        return value
    state=remap(state);job=remap(job)
    state['reference_video']=str(c.reference.resolve())
    # Captured manifests and receipts remain bound to their original task/job/run.
    # Only paths and hashes of remapped isolated bytes change. No search is added.
    for original in c.original['task']['source_acquisition']['interrupted_attempts']:
        descriptor=next(d for d in state['source_acquisition']['interrupted_attempts'] if d['studio_job_id']==original['studio_job_id'])
        manifest=remap(c.artifact(original['manifest_path']))
        manifest_path=Path(descriptor['manifest_path']);manifest_path.parent.mkdir(parents=True,exist_ok=True)
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf8')
        captured_receipt=next((r for r in c.original['artifacts'] if r['path']==original['receipt_path']),None)
        if captured_receipt is None:
            # Registered round0 receipt inspected at decision 1301926373063b48d464595d0d316627304007481adbde2941b18edc6dd15120:
            # every JSON field equals this preserved descriptor projection.
            # This is isolated historical input, never a production receipt.
            assert original['studio_job_id']=='job-85d6c467a47e4a03'
            assert original['receipt_sha256']=='304c32bb78fe2e1be4e7e51b70874f3e48e8270ab98a468f381215fecf9cff05'
            assert original['worker_checkpoints']==[] and original['candidates']==[]
            assert [r['status'] for r in original['searches']]==['not_attempted','connection_failed']
            historical={k:copy.deepcopy(v) for k,v in original.items() if k not in {'receipt_path','receipt_sha256'}}
        else:
            assert not captured_receipt['truncated']
            historical=json.loads(captured_receipt['content'])
        receipt=remap(historical)
        receipt['manifest_sha256']=prep.digest(manifest_path)
        receipt_path=Path(descriptor['receipt_path'])
        receipt_path.write_text(json.dumps(receipt,ensure_ascii=False),encoding='utf8')
        descriptor.update(manifest_sha256=prep.digest(manifest_path),receipt_sha256=prep.digest(receipt_path))
        for attempt in job['checkpoint']['source_attempts']:
            if attempt['studio_job_id']==descriptor['studio_job_id']:
                attempt.update(receipt_sha256=descriptor['receipt_sha256'])
    settings=Settings(data_dir=tmp_path,source_browser_search=True,source_transcribe_reference=False,source_query_model_enabled=True)
    store=StudioStore(tmp_path/'worker-store')
    from hotpost.studio import Studio
    service=Studio(settings,workers=False)
    service.public=lambda value:value
    store=service.store
    with store.transaction() as db:
        db.execute('INSERT INTO tasks VALUES(?,?,?,?,?)',(state['id'],state['shortcode'],state['revision'],json.dumps(state,ensure_ascii=False),time.time()))
        db.execute('INSERT INTO jobs(id,task_id,kind,key,payload,status,checkpoint,created,updated,error) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (job['id'],job['task_id'],job['kind'],job['id'],json.dumps(job['payload']),job['status'],json.dumps(job['checkpoint']),time.time(),time.time(),job['error']))
    assert job['status']=='failed' and job['checkpoint']['failure_classification']['category']=='storage'
    service.action(state['id'],'retry',{'revision':state['revision'],'job_id':job['id']})
    job=store.claim(lane='sources')
    assert job and job['id']==c.original['job']['id'] and job['payload']['run_id']==state['run_id']
    assert job['checkpoint']['failure_classification']['category']=='storage'
    owner=SourceAcquisitionMixin();owner.settings=settings;owner.store=store
    plan,frames=prep.preflight_preparation(settings,state,job)
    assert plan is None and frames
    def progress(*args):pass
    with monkeypatch.context() as old:
        old.setattr(recovery,'acquire_topic_queries',topic.cached_topic_queries)
        with pytest.raises(VisualQueryRejection,match='시각 고정 조건'):
            owner._prepare_source_queries(store.get(state['id']),job,progress)
    assert c.calls==[] and 'planning_preparation' not in job['checkpoint']
    current=owner._prepare_source_queries(store.get(state['id']),job,progress)
    with store.connect() as db:
        saved=db.execute('SELECT checkpoint FROM jobs WHERE id=? AND task_id=?',(job['id'],state['id'])).fetchone()
    checkpoint=json.loads(saved[0])
    selected=checkpoint['planning_preparation']
    assert {k:selected[k] for k in ('task_id','job_id','run_id')}==c.owner
    assert checkpoint['failure_trace']==remap(original_failure)
    assert current['source_acquisition']['waiting']==remap(original_wait)
    plan,frames=prep.preflight_preparation(settings,current,{**job,'checkpoint':checkpoint})
    assert plan is not None and frames and len(topic.plan_queries(plan))==10
    assert c.calls==['proposal','review']
    assert not current['sources'] and not current['edits']
    assert current['script_id']==c.original['task']['script_id']
    assert current['voice_id']==c.original['task']['voice_id']
    assert all((c.cache/name).read_bytes()==raw for name,raw in c.before.items())
    # Continue the same production worker through real access validation.
    # Only the external browser transport and existing-page responses are doubled.
    from contextlib import nullcontext
    import playwright.sync_api as api
    from hotpost import source_browser_runtime as runtime
    from hotpost.source_access_preflight import SourceAccessWaiting
    from hotpost.editing_adapter import _atomic_json
    from hotpost.studio_pause import StudioPaused
    settings.source_browser_profile_dir.mkdir(parents=True,exist_ok=True)
    (settings.source_browser_profile_dir/'hotpost-live-session-v1').write_text('isolated')
    class Page:
        url='https://www.tiktok.com/search?q=new+balance'
        reads=0
        def locator(self,selector):
            assert selector=='body'
            def text(**kwargs):
                self.reads+=1
                return 'Search videos'
            return SimpleNamespace(inner_text=text)
    page=Page();context=SimpleNamespace(pages=[page])
    browser=SimpleNamespace(contexts=[context])
    pw=SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=lambda *a,**k:browser))
    monkeypatch.setattr(api,'sync_playwright',lambda:nullcontext(pw))
    monkeypatch.setattr(runtime,'endpoint',lambda settings:'http://isolated.invalid')
    def existing(context,settings,provider):
        if provider=='tiktok':return page
        raise LookupError('isolated missing tab')
    monkeypatch.setattr(runtime,'existing_page',existing)
    ready=owner._source_access_gate(store.get(state['id']),job)
    assert 'tiktok' in ready and page.reads>0
    with store.connect() as db:
        persisted=json.loads(db.execute('SELECT checkpoint FROM jobs WHERE id=? AND task_id=?',(job['id'],state['id'])).fetchone()[0])
    observed=next(r for r in persisted['source_access_preflight']['observations'] if r['provider']=='tiktok')
    assert observed['status']=='ready' and observed['reason']=='current_existing_page_observed'
    assert persisted['planning_preparation']==selected
    assert persisted['failure_trace']==remap(original_failure)
    assert store.get(state['id'])['source_acquisition']['waiting']==remap(original_wait)
    target=tmp_path/'search_cooldowns'/'tiktok.json'
    for block in ({'reason':'rate_limited','until':time.time()+120,'server_retry_after':True},
                  {'reason':'login_required','requires_verification':True,'until':0}):
        _atomic_json(target,block);original_bytes=target.read_bytes()
        with pytest.raises(SourceAccessWaiting):
            owner._source_access_gate(store.get(state['id']),job)
        assert target.read_bytes()==original_bytes
        assert 'tiktok' not in job['checkpoint']['source_access_preflight']['ready_routes']
        assert store.get(state['id'])['source_acquisition']['waiting']==remap(original_wait)
    store.change(state['id'],lambda s,db:s.setdefault('automation',{}).update(paused_by_user=True))
    before_reads=page.reads
    with pytest.raises(StudioPaused):
        owner._source_access_gate(store.get(state['id']),job)
    assert page.reads==before_reads
    assert store.get(state['id'])['automation']['paused_by_user'] is True
    assert not store.get(state['id'])['sources'] and not store.get(state['id'])['edits']
