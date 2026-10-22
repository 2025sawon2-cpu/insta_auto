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


@pytest.fixture
def incident_case(tmp_path, monkeypatch):
    original=json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    fixture=copy.deepcopy(original)
    state,job=fixture['task'],fixture['job']
    assert job['task_id']==state['id'] and job['payload']['run_id']==state['run_id']
    assert job['status']=='failed' and job['kind']=='collect_sources'
    assert 'planning_preparation' not in job['checkpoint']
    rejected=state['source_acquisition']['visual_query_rejection']
    evidence=copy.deepcopy(rejected['evidence'])
    owner=copy.deepcopy(rejected['binding'])
    assert job['checkpoint']['visual_query_input']=={**owner,'input_sha256':digest(evidence)}
    def artifact(path):
        row=next(r for r in fixture['artifacts'] if r['path']==path)
        assert not row['truncated']
        return json.loads(row['content'])
    bad=artifact(rejected['files'][0]['path'])['proposal']
    old_review=artifact(rejected['files'][1]['path'])
    assert old_review['proposal_sha256']==digest(bad)
    assert bad['subject_identity']['required_terms'][0]['source']=='visual'
    media=tmp_path/'media';media.mkdir()
    reference=media/'reference.mp4';reference.write_bytes(b'isolated reference stand-in')
    captured={r['path']:r for r in fixture['preparation_frame_evidence'][0]['frames']}
    frames=[]
    for index,row in enumerate(evidence['frames']):
        captured_row=captured[row['path']]
        data=base64.b64decode(captured_row['data_base64'])
        assert hashlib.sha256(data).hexdigest()==row['sha256']==captured_row['sha256']
        path=media/('frame_%02d.jpg'%index);path.write_bytes(data);frames.append(path)
        row['path']=str(path.resolve())
    evidence.update(reference_path=str(reference.resolve()),reference_sha256=prep.digest(reference))
    caption=evidence['text']['caption'];transcript={**evidence['text'],'reference_kind':'speech'}
    policy=copy.deepcopy(job['payload']['source_policy'])
    settings=SimpleNamespace(data_dir=tmp_path,source_transcribe_reference=False,source_query_model_enabled=True)
    sheet=media/'sheet.jpg';sheet.write_bytes(frames[0].read_bytes())
    bundle=prep.acquisition_bundle_path(settings,state['shortcode'],caption,transcript,policy,state['product'])
    prep.save_bundle(bundle,caption,transcript,reference,frames,sheet,query_policy='media-only',transcript=transcript,query_plan={})
    cache=tmp_path/'source-topic-query-receipts'/digest({'evidence':evidence,'owner':owner})
    cache.mkdir(parents=True)
    old_review['input_sha256']=digest(evidence)
    for name,value in [('proposal.json',{'input_sha256':digest(evidence),'proposal':bad}),('review.json',old_review)]:
        (cache/name).write_text(json.dumps(value),encoding='utf8')
    before={name:(cache/name).read_bytes() for name in ('proposal.json','review.json')}
    monkeypatch.setattr(finder,'_post',lambda *a:SimpleNamespace(is_video=True,caption=caption))
    monkeypatch.setattr(finder,'_transcript_evidence',lambda *a:copy.deepcopy(transcript))
    monkeypatch.setattr(finder,'OpenClipVerifier',lambda *a:SimpleNamespace(error='',product_evidence=[],subject_reference_indices=[]))
    from hotpost import text_overlay,script_rewriter
    monkeypatch.setattr(text_overlay,'TextOverlayDetector',lambda *a:SimpleNamespace(note=''))
    fresh=copy.deepcopy(bad)
    fresh['subject_identity']['required_terms'][0].update(source='caption',quote='뉴발란스')
    calls=[]
    def external(settings,instruction,data,**kwargs):
        if 'proposal_sha256' in data:
            calls.append('review')
            result=copy.deepcopy(old_review)
            result.update(input_sha256=data['input_sha256'],proposal_sha256=data['proposal_sha256'],identity_reason='Isolated fresh review: brand is grounded by literal caption 뉴발란스; model remains unknown.')
            assert result['proposal_sha256']==digest(fresh)!=digest(bad)
            return result
        if data.get('policy')=='natural-topic-search-v1':
            calls.append('proposal')
            assert data['planning_feedback']['rejected_proposal']==bad
            assert data['owner']==owner
            return copy.deepcopy(fresh)
        return {'subject_kind':'product','primary_subject':{'name':'뉴발란스','source':'caption','quote':'뉴발란스'},'queries':[],'tiktok_queries':[]}
    monkeypatch.setattr(script_rewriter,'_generate',external)
    scope=copy.deepcopy(job['checkpoint']['source_attempts'][0]['search_context'])
    scope['reference_sha256']=prep.digest(reference)
    context={**owner,'source_policy':policy,'search_context':scope,'preparation_only':True,'expected_reference_sha256':prep.digest(reference)}
    def progress(message,pct):pass
    def capture(key):
        assert key==digest(evidence)
        return copy.deepcopy(owner)
    progress.visual_query_input=capture
    return SimpleNamespace(**locals())


def test_preserved_incident_reaches_real_preparation_stage(incident_case,tmp_path,monkeypatch):
    c=incident_case
    old=tmp_path/'old'/c.job['id'];old.mkdir(parents=True)
    (old/'manifest.json').write_text('{}',encoding='utf8')
    with monkeypatch.context() as prior:
        prior.setattr(recovery,'acquire_topic_queries',topic.cached_topic_queries)
        with pytest.raises(VisualQueryRejection,match='시각 고정 조건'):
            finder._find_sources(c.settings,c.state['shortcode'],c.progress,search_request='',search_round=c.job['payload']['round'],previous_searches=[],exclude_urls=[],root=old,policy=c.policy,search_context=c.context)
    assert c.calls==[]
    root=tmp_path/'repaired'/c.job['id'];root.mkdir(parents=True)
    (root/'manifest.json').write_text('{}',encoding='utf8')
    result=finder._find_sources(c.settings,c.state['shortcode'],c.progress,search_request='',search_round=c.job['payload']['round'],previous_searches=[],exclude_urls=[],root=root,policy=c.policy,search_context=c.context)
    assert result['preparation_only'] is True
    assert result['run_id']==c.job['payload']['run_id']
    plan=result['query_plan']
    assert plan['query_owner']==c.owner and len(topic.plan_queries(plan))==10
    assert prep.reusable_query_contract(plan,c.policy,c.state['product'],c.context)
    assert json.loads((root/'manifest.json').read_text('utf8'))['audit_checkpoint']=='preparation_complete'
    assert c.calls==['proposal','review']
    assert all((c.cache/name).read_bytes()==data for name,data in c.before.items())
    assert c.fixture['task']==c.original['task'] and c.fixture['job']==c.original['job']


@pytest.mark.parametrize('fault',['owner','reference','frame'])
def test_preparation_rejects_changed_binding_or_media(incident_case,tmp_path,fault):
    c=incident_case;context=copy.deepcopy(c.context)
    if fault=='owner':context['job_id']='foreign-job'
    elif fault=='reference':context['expected_reference_sha256']='0'*64
    else:c.frames[0].write_bytes(b'changed')
    root=tmp_path/'invalid'/c.job['id'];root.mkdir(parents=True)
    (root/'manifest.json').write_text('{}',encoding='utf8')
    with pytest.raises((ValueError,AssertionError)):
        finder._find_sources(c.settings,c.state['shortcode'],c.progress,search_request='',search_round=1,previous_searches=[],exclude_urls=[],root=root,policy=c.policy,search_context=context)
    assert c.calls==[]
    assert not (c.cache/'receipt.json').exists()


def test_preserved_checkpoint_through_production_preparation(incident_case,tmp_path,monkeypatch):
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
    # Real failed-state admission uses the same isolated causal bytes.
    from hotpost.video_agent_actions import local_topic_repair_context, _gate, ActionHeld
    admission_state=copy.deepcopy(state);admission_job=copy.deepcopy(job)
    # Trace filenames are routing data, never paths opened by this test.
    admission_job['checkpoint']['failure_trace']=copy.deepcopy(c.original['job']['checkpoint']['failure_trace'])
    rejected=admission_state['source_acquisition']['visual_query_rejection']
    rejected['evidence']=copy.deepcopy(c.evidence)
    rejected['input_sha256']=digest(c.evidence)
    rejected['reference_sha256']=prep.digest(c.reference)
    rejected['files']=[{'path':str((c.cache/name).resolve()),'sha256':prep.digest(c.cache/name)}
        for name in ('proposal.json','review.json')]
    admission_job['checkpoint']['visual_query_input']={**c.owner,'input_sha256':digest(c.evidence)}
    assert admission_job['status']=='failed'
    assert local_topic_repair_context(admission_state,admission_job)
    assert _gate(admission_state,'retry_repaired',admission_job) is None
    assert c.calls==[]
    with pytest.raises(ActionHeld):_gate(admission_state,'collect_sources',admission_job)
    for fault in ('owner','input','login','captcha','rate','pause','receipt'):
        denied_state=copy.deepcopy(admission_state);denied_job=copy.deepcopy(admission_job)
        if fault=='owner':denied_job['task_id']='foreign'
        elif fault=='input':denied_job['checkpoint']['visual_query_input']['input_sha256']='0'*64
        elif fault=='pause':denied_state['automation']['paused_by_user']=True
        elif fault=='receipt':denied_state['source_acquisition']['receipt_wait']={'reason':'unsettled'}
        else:denied_state['source_acquisition']['waiting']['searches'][0]['status']={'login':'login_required','captcha':'captcha_required','rate':'rate_limited'}[fault]
        with pytest.raises(ActionHeld):_gate(denied_state,'retry_repaired',denied_job)
    assert admission_state['source_acquisition']['waiting']==remap(original_wait)
    assert all((c.cache/name).read_bytes()==raw for name,raw in c.before.items())
    # Host pinned contracts cover signed apply/load/retry. This same-job
    # production sub-entry represents the subsequent worker claim boundary.
    job['status']='running';job['claim_token']=job['checkpoint']['_claim_token']
    with store.transaction() as db:
        db.execute('INSERT INTO tasks VALUES(?,?,?,?,?)',(state['id'],state['shortcode'],state['revision'],json.dumps(state,ensure_ascii=False),time.time()))
        db.execute('INSERT INTO jobs(id,task_id,kind,key,payload,status,checkpoint,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
            (job['id'],job['task_id'],job['kind'],job['id'],json.dumps(job['payload']),job['status'],json.dumps(job['checkpoint']),time.time(),time.time()))
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
