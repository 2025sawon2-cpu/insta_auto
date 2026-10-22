"""Recover the preserved gate, with real preparation/access/response validators.

The full fixture retains task/job/run, failed readiness and history. Only paths
and stand-in media are isolated. The registered bundle and saved finite plan
are retained with consistently rebound nested media hashes. Existing
host pinned tests cover signed parking/retry/load; this tests its missing gate
connection, not production completion. The old diagnostics draft is unapproved
and remains untouched; preparation corruption, pause and ownership/access
rejection coverage are retained here for the replacement recovery method.
"""
import copy
import hashlib
import json
import os
import time
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from urllib.parse import urlencode
import pytest
from hotpost.studio_sources import SourceAcquisitionMixin
from hotpost.source_access_preflight import SourceAccessWaiting
from hotpost.editing_adapter import _atomic_json
from hotpost.source_search.readiness import readiness_blocked, readiness_record


class DiskStore:
    def __init__(self,state,root):self.state=state;self.path=root/'checkpoint.json'
    def get(self,task_id):
        assert task_id==self.state['id']
        return copy.deepcopy(self.state)
    def checkpoint(self,job,checkpoint):
        _atomic_json(self.path,{'id':job['id'],'checkpoint':checkpoint})
    def reload(self,job):
        value=json.loads(self.path.read_text('utf8'))
        assert value['id']==job['id']
        job['checkpoint']=value['checkpoint']
        return value['checkpoint']


def incident():
    value=json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    return value,copy.deepcopy(value['task']),copy.deepcopy(value['job'])


def response(query):
    now=time.time()
    return {'page_url':'https://www.tiktok.com/search?'+urlencode({'q':query}),
        'response_url':'https://www.tiktok.com/api/search/item/full/?'+urlencode({'keyword':query}),
        'http_status':200,'observation_started_at':now,'received_at':now,
        'body':{'status_code':0,'item_list':[{'id':'1234567890123456789',
            'author':{'uniqueId':'isolated_fixture'},'video':{'duration':10}}]}}


def browser_fixture(monkeypatch,root,query):
    from contextlib import nullcontext
    from hotpost import source_browser_runtime as runtime, browser_search
    import playwright.sync_api as api
    settings=SimpleNamespace(data_dir=root,source_browser_search=True,
        source_browser_existing_window_only=True,source_min_usable=5,
        source_browser_profile_dir=root/'profile',source_browser_search_interval=30,
        source_browser_block_cooldown=60)
    settings.source_browser_profile_dir.mkdir(parents=True,exist_ok=True)
    (settings.source_browser_profile_dir/'hotpost-live-session-v1').write_text('isolated')
    monkeypatch.setattr(browser_search,'BROWSER_COOLDOWNS',{})
    class Page:
        def __init__(self,url):
            self.url=url;self.body='Search videos';self.listeners=[]
            self.emitted=0;self.reads=0;self.status=200;self.attach_error=False
        def locator(self,selector):
            assert selector=='body'
            def text(**kwargs):
                self.reads+=1
                return self.body
            return SimpleNamespace(inner_text=text)
        def on(self,event,callback):
            assert event=='response';self.listeners.append(callback)
        def remove_listener(self,event,callback):
            assert event=='response';self.listeners.remove(callback)
        def wait_for_timeout(self,milliseconds):
            assert milliseconds==250 and self.listeners
            payload=response(query)
            item=SimpleNamespace(status=self.status,url=payload['response_url'],
                headers={'retry-after':'120'},json=lambda:copy.deepcopy(payload['body']))
            self.emitted+=1
            for callback in list(self.listeners):callback(item)
    page=Page(response(query)['page_url'])
    yandex=Page('https://yandex.com/images/search')
    youtube=Page('https://www.youtube.com/')
    context=SimpleNamespace(pages=[page,yandex,youtube])
    browser=SimpleNamespace(contexts=[context])
    pw=SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=lambda *a,**k:browser))
    monkeypatch.setattr(api,'sync_playwright',lambda:nullcontext(pw))
    monkeypatch.setattr(runtime,'endpoint',lambda settings:'http://isolated.invalid')
    monkeypatch.setattr(runtime,'browser_lease',lambda settings:nullcontext())
    def attach(*args):
        if page.attach_error:raise LookupError('isolated unavailable tab')
        return context
    monkeypatch.setattr(runtime,'attach_browser',attach)
    def existing(context,settings,provider):
        if provider=='tiktok':return page
        if provider=='yandex-images':return yandex
        if provider=='youtube':return youtube
        raise LookupError('tab_missing')
    monkeypatch.setattr(runtime,'existing_page',existing)
    _atomic_json(root/'search_cooldowns'/'youtube.json',
        {'reason':'login_required','requires_verification':True,'until':0})
    return settings,page


def install_registered_bundle(fixture,state,job,settings,root):
    from PIL import Image
    from hotpost import source_preparation as preparation
    from hotpost.source_visual_queries import digest, plan_queries
    from hotpost.source_core_priority import context
    from hotpost.source_diversity import acquisition_policy
    from hotpost.source_policy import run_policy
    documents=[]
    for artifact in fixture['artifacts']:
        try: value=json.loads(artifact['content'])
        except (KeyError,TypeError,ValueError): continue
        if isinstance(value,dict) and value.get('policy')=='source-preparation-sha-v1' and isinstance(value.get('query_plan'),dict):
            documents.append(value)
    assert documents, 'Registered preparation bundle must be captured, never replaced with a legacy-only fixture'
    original=next(v for v in documents if v['query_plan'].get('run_id')==state['run_id'])
    bundle=copy.deepcopy(original)
    original_receipt=copy.deepcopy(bundle['query_plan']['visual_query_evidence'])
    substitutions={}
    reference_bytes=Path(state['reference_video']).read_bytes()
    reference_sha=hashlib.sha256(reference_bytes).hexdigest()
    substitutions[original_receipt['evidence']['reference_sha256']]=reference_sha
    media=[bundle['reference'],*bundle['frames'],bundle['sheet'],
           original_receipt['evidence']['reference_path'],
           *[r['path'] for r in original_receipt['evidence']['frames']]]
    reference_names={bundle['reference'],original_receipt['evidence']['reference_path']}
    for index,raw in enumerate(dict.fromkeys(media)):
        target=(root/'bundle-media'/hashlib.sha256(raw.encode()).hexdigest()).resolve()
        target.parent.mkdir(parents=True,exist_ok=True)
        if raw in reference_names: target.write_bytes(reference_bytes)
        else:
            picture=Image.new('RGB',(32,32))
            picture.putdata([((x*17+index*31)%256,(x*7+index*53)%256,(x*29+index*11)%256) for x in range(1024)])
            picture.save(target,format='PNG')
        substitutions[raw]=str(target)
    for row in bundle['files']:
        if row['path'] in substitutions:
            substitutions[row['sha256']]=hashlib.sha256(Path(substitutions[row['path']]).read_bytes()).hexdigest()
    for row in original_receipt['evidence']['frames']:
        substitutions[row['sha256']]=hashlib.sha256(Path(substitutions[row['path']]).read_bytes()).hexdigest()
    def rewrite(value):
        if isinstance(value,dict): return {k:rewrite(v) for k,v in value.items()}
        if isinstance(value,list): return [rewrite(v) for v in value]
        if isinstance(value,str): return substitutions.get(value,value)
        return value
    bundle=rewrite(bundle)
    # Rebind evidence only: never alter proposal observations or verdict flags.
    receipt=bundle['query_plan']['visual_query_evidence']
    receipt['proposal']=copy.deepcopy(original_receipt['proposal'])
    receipt['review']=copy.deepcopy(original_receipt['review'])
    receipt['input_sha256']=digest(receipt['evidence'])
    receipt['review']['input_sha256']=receipt['input_sha256']
    assert receipt['review']['proposal_sha256']==digest(receipt['proposal'])
    substitutions[original_receipt['input_sha256']]=receipt['input_sha256']
    rewritten_state=rewrite(state);state.clear();state.update(rewritten_state)
    rewritten_job=rewrite(job);job.clear();job.update(rewritten_job)
    plan=bundle['query_plan']
    plan['query_reference_sha256']=reference_sha
    from hotpost.source_coverage import search_scope_for_state
    plan['search_context']=search_scope_for_state(state)
    assert plan_queries(plan)==original_receipt['queries']
    transcript=bundle['transcript'];caption=receipt['evidence']['text']['caption']
    policy=acquisition_policy(state,run_policy(state))
    destination=preparation.acquisition_bundle_path(settings,state['shortcode'],caption,transcript,policy,state['product'])
    assert destination is not None and destination.resolve().is_relative_to(root.resolve())
    assert caption==original_receipt['evidence']['text']['caption']
    assert all(transcript.get(k,'')==original_receipt['evidence']['text'].get(k,'')
               for k in ('speech','screen_text'))
    # Relocated fixture metadata uses the exact external text supplied below.
    # Preserve original text and verdicts; recompute only its derived binding.
    bundle['evidence_key']=preparation.evidence_key(caption,transcript)
    bundle['payload_sha256']=preparation.payload_key(bundle)
    _atomic_json(destination,bundle)
    saved=state['source_acquisition']['core_search_plan']
    assert saved['queries'] and saved['identity']==plan['search_identity']
    saved['context']=context(state)
    saved['frame_sha256']=[hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in bundle['frames']]
    saved['sha256']=digest({k:v for k,v in saved.items() if k not in {'sha256','excluded_routes'}})
    return bundle,caption,transcript


def transactional_store(state,job,root):
    from hotpost.studio_store import StudioStore
    class IncidentStore(StudioStore):
        def reload(self,job):
            with self.connect() as db:
                row=db.execute('SELECT checkpoint FROM jobs WHERE id=? AND task_id=?',(job['id'],job['task_id'])).fetchone()
            assert row is not None
            job['checkpoint']=json.loads(row[0])
            return job['checkpoint']
    store=IncidentStore(root/'transactional-store')
    with store.transaction() as db:
        db.execute('INSERT INTO tasks VALUES(?,?,?,?,?)',(state['id'],state['shortcode'],state['revision'],json.dumps(state,ensure_ascii=False),time.time()))
        db.execute('INSERT INTO jobs(id,task_id,kind,key,payload,status,checkpoint,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
            (job['id'],job['task_id'],job['kind'],job['id'],json.dumps(job['payload']),job['status'],json.dumps(job['checkpoint']),time.time(),time.time()))
    return store


def test_same_incident_gate_recovers_after_disk_reload(tmp_path,monkeypatch):
    from hotpost import source_parser_recovery as recovery, source_access_preflight as access, source_finder
    fixture,state,job=incident()
    assert job['id']=='job-b720a8b55d0f4bb1'
    assert state['run_id']==job['payload']['run_id']
    failed=copy.deepcopy(job['checkpoint']['parser_repair_context']['observations'][0]['readiness'])
    assert failed['query']=='手持 喷花器 圆柱形喷头'
    def remap(v):
        if isinstance(v,dict):return {k:remap(x) for k,x in v.items()}
        if isinstance(v,list):return [remap(x) for x in v]
        if isinstance(v,str) and (PureWindowsPath(v).is_absolute() or v.startswith('/')):
            return str(tmp_path/hashlib.sha256(v.encode()).hexdigest())
        return v
    state,job=remap(state),remap(job)
    reference=tmp_path/'authoritative-reference.mp4';reference.write_bytes(b'isolated reference')
    state['reference_video']=str(reference)
    manifest=json.loads(fixture['artifacts'][0]['content'])
    assert manifest['shortcode']==state['shortcode'] and manifest['run_id']==state['run_id']
    path=Path(state['source_acquisition']['rounds'][0]['manifest_path'])
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf8')
    legacy=path.parent/'reference.mp4';legacy.write_bytes(reference.read_bytes())
    (path.parent/'reference_contact_sheet.jpg').write_bytes(b'isolated sheet')
    frames=[]
    for i,relative in enumerate(manifest['reference_frames']):
        p=(path.parent/relative).resolve();assert p.is_relative_to(tmp_path.resolve())
        p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(str(i).encode());frames.append(p)
    monkeypatch.setattr(source_finder,'_post',lambda *a,**k:SimpleNamespace(caption=manifest['caption']))
    monkeypatch.setattr(source_finder,'_transcript_evidence',lambda *a,**k:copy.deepcopy(manifest['product_evidence']['query_evidence']))
    _atomic_json(tmp_path/'search_readiness'/'tiktok.json',failed)
    settings,page=browser_fixture(monkeypatch,tmp_path,failed['query'])
    observed=access.current_routes(settings,['tiktok','yandex-images','youtube'])
    assert [r['status'] for r in observed]==['readiness_blocked','ready','login_required']
    bundle,caption,transcript=install_registered_bundle(fixture,state,job,settings,tmp_path)
    monkeypatch.setattr(source_finder,'_post',lambda *a,**k:SimpleNamespace(caption=caption))
    monkeypatch.setattr(source_finder,'_transcript_evidence',lambda *a,**k:copy.deepcopy(transcript))
    frames=[Path(p) for p in bundle['frames']]
    store=transactional_store(state,job,tmp_path);owner=SourceAcquisitionMixin();owner.settings=settings;owner.store=store
    from hotpost.source_preparation import preflight_preparation
    plan,actual_frames=preflight_preparation(settings,state,job)
    assert plan is not None and plan==bundle['query_plan']
    assert [p.resolve() for p in actual_frames]==frames
    original_finite=copy.deepcopy(state['source_acquisition']['core_search_plan'])
    assert owner._prepare_source_queries(state,job,lambda *a:None)==state
    # Unchanged old causal path fails even when an external response is available.
    with pytest.raises(SourceAccessWaiting):access.check_access(settings,state,job,plan=plan,frames=frames)
    assert page.emitted==0
    assert 'parser_response_recovery' not in job['checkpoint']
    page.attach_error=True
    with pytest.raises(SourceAccessWaiting):owner._source_access_gate(state,job)
    saved=store.reload(job)
    assert saved['parser_response_recovery']['status']=='unavailable'
    assert saved['parser_response_recovery']['error_type']=='LookupError'
    assert readiness_record(tmp_path,'tiktok')==failed
    # Corrupt evidence still rejects before external I/O.
    page.attach_error=False
    before_reads=page.reads
    protected_frame=frames[0];original_bytes=protected_frame.read_bytes()
    protected_frame.write_bytes(b'corrupt')
    with pytest.raises(SourceAccessWaiting,match='소스 준비 근거 보존 대기'):owner._source_access_gate(state,job)
    assert page.reads==before_reads and page.emitted==0
    protected_frame.write_bytes(original_bytes)
    ready=owner._source_access_gate(store.get(state['id']),job)
    assert page.emitted==1 and page.listeners==[]
    rows=job['checkpoint']['source_access_preflight']['observations']
    actual=next(r for r in rows if r['provider']=='tiktok')
    assert actual['status']=='ready' and actual['reason']=='current_existing_page_observed'
    assert next(r for r in rows if r['provider']=='youtube')['status']=='login_required'
    assert 'tiktok' in ready
    saved=store.reload(job);receipt=saved['parser_response_recovery']
    current=store.get(state['id'])
    finite=current['source_acquisition']['core_search_plan']
    assert finite['queries']==original_finite['queries']
    assert finite['identity']==original_finite['identity']
    assert set(finite['routes'])==set(original_finite['routes'])|{'tiktok'}
    assert not current['source_acquisition'].get('core_fallback')
    assert not current['sources'] and not current['edits']
    assert current['id']==fixture['task']['id'] and current['run_id']==fixture['task']['run_id']
    assert store.jobs(state['id'])[0]['id']==fixture['job']['id']
    assert receipt['status']=='response_validated'
    assert receipt['job_id']==job['id'] and receipt['run_id']==state['run_id']
    assert receipt['task_id']==state['id']
    assert receipt['query_submitted'] is False and receipt['grants_media_approval'] is False
    assert readiness_record(tmp_path,'tiktok')['previous_failure']==failed
    assert not readiness_blocked(tmp_path,'tiktok')
    assert not state['sources'] and not state['edits']


@pytest.mark.parametrize('condition',['visible_login','rate_limit','persisted_cooldown','saved_login','saved_captcha'])
def test_real_response_reader_preserves_access_blocks(tmp_path,monkeypatch,condition):
    from hotpost import source_parser_recovery as recovery
    from hotpost.source_access_preflight import current_routes
    from hotpost.search_access import access_record,manual_required
    _,state,job=incident()
    failed=copy.deepcopy(job['checkpoint']['parser_repair_context']['observations'][0]['readiness'])
    settings,page=browser_fixture(monkeypatch,tmp_path,failed['query'])
    _atomic_json(tmp_path/'search_readiness'/'tiktok.json',failed)
    target=tmp_path/'search_cooldowns'/'tiktok.json'
    if condition=='visible_login':page.body='Log in to search'
    elif condition=='rate_limit':page.status=429
    else:
        record=({'reason':'rate_limited','until':time.time()+120,'server_retry_after':True}
            if condition=='persisted_cooldown' else
            {'reason':'captcha' if condition=='saved_captcha' else 'login_required',
             'requires_verification':True,'until':0})
        _atomic_json(target,record)
        original=target.read_bytes()
    assert recovery.recover_response(settings,DiskStore(state,tmp_path),state,job) is False
    assert readiness_record(tmp_path,'tiktok')==failed
    assert job['checkpoint']['parser_response_recovery']['status']=='unavailable'
    saved=access_record(tmp_path,'tiktok')
    if condition=='rate_limit':
        assert page.emitted==1 and page.listeners==[]
        assert saved['reason']=='rate_limited' and saved['server_retry_after'] is True
        assert saved['until']-saved['blocked_at']==pytest.approx(120)
    elif condition=='visible_login':
        assert page.emitted==0 and manual_required(saved)
        assert saved['reason']=='login_required'
    else:
        assert page.emitted==0 and target.read_bytes()==original
    if condition!='saved_captcha':
        rows=current_routes(settings,['tiktok'])
        assert rows[0]['status']!='ready'
    assert not state['sources'] and not state['edits']


@pytest.mark.parametrize('invalid',['payload_run','context_task','manual_gate','receipt_wait','access_blocked'])
def test_invalid_incident_never_observes_or_changes_readiness(tmp_path,monkeypatch,invalid):
    from hotpost import source_parser_recovery as recovery
    _,state,job=incident()
    if invalid=='payload_run':job['payload']['run_id']='other'
    elif invalid=='context_task':job['checkpoint']['parser_repair_context']['task_id']='other'
    elif invalid=='manual_gate':
        for row in job['checkpoint']['source_access_preflight']['observations']:
            if row['provider']=='tiktok':row['manual_gate_active']=True
        job['checkpoint']['parser_repair_context']['observations'][0]['manual_gate_active']=True
    elif invalid=='receipt_wait':state.setdefault('source_acquisition',{})['receipt_wait']={'status':'receipt_wait'}
    else:job['checkpoint']['failure_classification']={'category':'access_blocked'}
    before=copy.deepcopy(job['checkpoint']);seen=[]
    monkeypatch.setattr(recovery,'read_response',lambda *a:seen.append(a))
    assert recovery.recover_response(SimpleNamespace(),DiskStore(state,tmp_path),state,job) is False
    assert seen==[] and job['checkpoint']==before
    assert not (tmp_path/'search_readiness').exists()


def test_pause_rejects_before_observation(tmp_path,monkeypatch):
    from hotpost import source_parser_recovery as recovery
    from hotpost.studio_pause import StudioPaused
    _,state,job=incident();state['automation']['paused_by_user']=True
    seen=[];monkeypatch.setattr(recovery,'read_response',lambda *a:seen.append(a))
    with pytest.raises(StudioPaused):recovery.recover_response(SimpleNamespace(),DiskStore(state,tmp_path),state,job)
    assert seen==[] and not (tmp_path/'checkpoint.json').exists()
