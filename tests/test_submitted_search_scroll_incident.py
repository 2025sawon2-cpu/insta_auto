"""Current submitted-query checkpoint recovery, without modifying prior regressions.
Full captured task/job/run/readiness/history remain; only test media paths and
hashes are rebound by the existing isolation helper. External CDP behavior is
mocked, never internal validators. Host pinned tests cover signed retry/load.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
import pytest
from hotpost.editing_adapter import _atomic_json
from hotpost.studio_sources import SourceAcquisitionMixin
from hotpost.source_access_preflight import SourceAccessWaiting
from hotpost.source_search.readiness import readiness_record


def helpers():
    path=Path(__file__).with_name('test_source_parser_response_incident.py')
    spec=importlib.util.spec_from_file_location('preserved_parser_test_helpers',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def setup_incident(tmp_path,monkeypatch):
    h=helpers()
    fixture=json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    state=copy.deepcopy(fixture['task']);job=copy.deepcopy(fixture['job'])
    assert job['id']=='job-2861e0826f2f4395'
    assert job['task_id']==state['id'] and job['payload']['run_id']==state['run_id']
    failed=copy.deepcopy(job['checkpoint']['parser_repair_context']['observations'][0]['readiness'])
    assert failed['query']=='concave flower vent silicone pot lid'
    assert job['checkpoint']['parser_response_recovery']['status']=='unavailable'
    def remap(v):
        if isinstance(v,dict):return {k:remap(x) for k,x in v.items()}
        if isinstance(v,list):return [remap(x) for x in v]
        if isinstance(v,str) and (PureWindowsPath(v).is_absolute() or v.startswith('/')):
            return str(tmp_path/hashlib.sha256(v.encode()).hexdigest())
        return v
    state,job=remap(state),remap(job)
    reference=tmp_path/'reference.mp4';reference.write_bytes(b'isolated reference')
    state['reference_video']=str(reference)
    settings,page=h.browser_fixture(monkeypatch,tmp_path,failed['query'])
    bundle,caption,transcript=h.install_registered_bundle(fixture,state,job,settings,tmp_path)
    from hotpost import source_finder
    monkeypatch.setattr(source_finder,'_post',lambda *a,**k:SimpleNamespace(caption=caption))
    monkeypatch.setattr(source_finder,'_transcript_evidence',lambda *a,**k:copy.deepcopy(transcript))
    _atomic_json(tmp_path/'search_readiness'/'tiktok.json',failed)
    store=h.transactional_store(state,job,tmp_path)
    owner=SourceAcquisitionMixin();owner.settings=settings;owner.store=store
    page.scrolls=[];page.scrolled=False;page.enable_scroll=False
    def wheel(x,y):
        assert (x,y)==(0,900)
        page.scrolls.append((x,y))
        if page.enable_scroll:page.scrolled=True
    page.mouse=SimpleNamespace(wheel=wheel)
    emit=page.wait_for_timeout
    def wait(milliseconds):
        assert milliseconds==250
        if page.scrolled:emit(milliseconds)
    page.wait_for_timeout=wait
    return fixture,state,job,failed,settings,page,store,owner,bundle


def isolated_retry_contract(tmp_path,state,job,store):
    import time
    import hmac
    from hotpost.video_agent_repairs import VideoRepairPipeline, _json
    from hotpost.video_agent_context import semantic_fingerprint, job_method_fingerprint
    # These are isolated future service proofs, not production approvals.
    fingerprint=semantic_fingerprint(state)
    job['checkpoint']['video_agent_input_fingerprint']=fingerprint
    job['checkpoint']['video_agent_job_fingerprint']=job_method_fingerprint(job)
    store.checkpoint(job,job['checkpoint'])
    pipeline=VideoRepairPipeline(tmp_path/'proof-main',tmp_path/'proof-renderer',
        tmp_path/'proof-records',interpreters={},regression_tests={})
    rid='repair-'+'1'*32
    source=Path(__file__).resolve().parents[1]/'hotpost/source_parser_recovery.py'
    target=pipeline.roots['main']/'hotpost/source_parser_recovery.py'
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes())
    sha=hashlib.sha256(target.read_bytes()).hexdigest()
    folder=pipeline._folder(rid);stage=folder/'stage/main/hotpost'
    stage.mkdir(parents=True,exist_ok=True)
    (stage/'source_parser_recovery.py').write_bytes(target.read_bytes())
    log=folder/'isolated-prior-test.log'
    log.write_text('Isolated prior-service proof fixture; not an executed production test.',encoding='utf8')
    binding={'task_id':state['id'],'job_id':job['id'],'agent_epoch':1,
        'input_fingerprint':fingerprint,'job_fingerprint':job_method_fingerprint(job)}
    files=[{'repo':'main','path':'hotpost/source_parser_recovery.py','sha256':sha}]
    record={'repair_id':rid,'status':'applied','applied_at':time.time()-1,
        'binding':binding,'files':files,'pinned_tests':[],'new_tests':[],
        'snapshot_hashes':{},'tests':[{'passed':True,'log_path':str(log),
        'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}]}
    pipeline._save(record)
    request=pipeline.review_request(rid)
    signed={'binding_sha256':request['binding_sha256'],'approved':True,
        'preserves_quality_guards':True,'recovers_current_incident':True,
        'regression_meaningful':True,'scope':'isolated external review fixture'}
    signed['signature']=hmac.new(pipeline._key,_json(signed).encode(),hashlib.sha256).hexdigest()
    record['review']=signed;pipeline._save(record)
    loaded={'repair_id':rid,'process_id':os.getpid(),'loaded_at':time.time(),'files':files}
    studio=SimpleNamespace(store=store,settings=SimpleNamespace(data_dir=tmp_path),
        video_repair_pipeline=pipeline,loaded_code_receipt=loaded)
    # Minimal projection of the exact hold visible in the host snapshot.
    hold={'job_id':job['id'],'phase':'held',
        'diagnosis_id':'codex0a5ad36d2b2f504df51e4875e5fc7339',
        'reason':'진전 관측 자료 부족 · AI 원인 검토 저장, 같은 입력의 재실행 보류',
        'waiting':False}
    with store.transaction() as db:
        db.execute('CREATE TABLE video_agents(task_id TEXT PRIMARY KEY,epoch INTEGER,record TEXT,updated REAL)')
        db.execute('INSERT INTO video_agents VALUES(?,?,?,?)',(state['id'],1,'{}',time.time()))
        db.execute('CREATE TABLE supervision_jobs(job_id TEXT PRIMARY KEY,task_id TEXT,claim TEXT,phase TEXT,record TEXT)')
        db.execute('INSERT INTO supervision_jobs VALUES(?,?,?,?,?)',(job['id'],state['id'],
            job['checkpoint']['_claim_token'],'held',json.dumps(hold)))
    action={'kind':'retry_repaired','hypothesis':'Isolated current incident recovery',
        'job_id':job['id'],'held_job_id':job['id'],'repair_id':rid,'evidence':[],'_agent_epoch':1}
    return studio,action,fingerprint,hold


def test_explicit_retry_claim_reaches_preserved_gate(tmp_path,monkeypatch):
    from hotpost.video_agent_actions import execute
    fixture,state,job,failed,settings,page,store,owner,bundle=setup_incident(tmp_path,monkeypatch)
    assert job['status']=='paused' and not job['checkpoint'].get('video_agent_park_receipt')
    studio,action,fingerprint,hold=isolated_retry_contract(tmp_path,state,job,store)
    assert store.claim('sources',task_id=state['id'],job_id=job['id']) is None
    result=execute(studio,state['id'],action,'isolated-explicit-retry',fingerprint)
    assert result['status']=='queued' and result['job_ids']==[fixture['job']['id']]
    with store.connect() as db:
        saved=json.loads(db.execute('SELECT record FROM supervision_jobs WHERE job_id=?',(job['id'],)).fetchone()[0])
    assert saved['phase']=='method_changed' and saved['diagnosis_id']==hold['diagnosis_id']
    assert 'released_at' not in saved
    claimed=store.claim('sources',task_id=state['id'],job_id=job['id'])
    assert claimed and claimed['id']==job['id'] and claimed['task_id']==state['id']
    assert claimed['payload']['run_id']==state['run_id']
    assert claimed['checkpoint']['parser_response_recovery']['status']=='unavailable'
    with pytest.raises(SourceAccessWaiting):owner._source_access_gate(store.get(state['id']),claimed)
    assert store.reload(claimed)['parser_response_recovery']['status']=='unavailable'
    assert readiness_record(tmp_path,'tiktok')==failed
    page.scrolls.clear();page.enable_scroll=True
    assert 'tiktok' in owner._source_access_gate(store.get(state['id']),claimed)
    receipt=store.reload(claimed)['parser_response_recovery']
    assert receipt['status']=='response_validated' and receipt['job_id']==fixture['job']['id']
    assert receipt['run_id']==state['run_id'] and receipt['grants_media_approval'] is False
    assert page.scrolls==[(0,900)] and not store.get(state['id'])['sources']


@pytest.mark.parametrize('damage',['missing_hold','unrelated_hold','epoch','signature','process','evidence','user_pause'])
def test_current_retry_admission_rejects_invalid_proof(tmp_path,monkeypatch,damage):
    from hotpost.video_agent_actions import execute
    _,state,job,failed,settings,page,store,owner,bundle=setup_incident(tmp_path,monkeypatch)
    studio,action,fingerprint,hold=isolated_retry_contract(tmp_path,state,job,store)
    if damage in ('missing_hold','unrelated_hold'):
        with store.transaction() as db:
            if damage=='missing_hold':db.execute('DELETE FROM supervision_jobs')
            else:db.execute('UPDATE supervision_jobs SET job_id=?',('unrelated-job',))
    elif damage=='epoch':action['_agent_epoch']=2
    elif damage=='process':studio.loaded_code_receipt['process_id']=-1
    elif damage=='signature':
        pipeline=studio.video_repair_pipeline;record=pipeline._read(action['repair_id'])
        record['review']['signature']='invalid';pipeline._save(record)
    elif damage=='evidence':action['evidence']=[{'path':state['reference_video'],'sha256':'0'*64}]
    else:store.change(state['id'],lambda s,db:s['automation'].update(paused_by_user=True))
    result=execute(studio,state['id'],action,'isolated-invalid-'+damage,fingerprint)
    assert result['status']=='held'
    assert store.jobs(state['id'])[0]['status']=='paused'
    assert page.emitted==0 and page.scrolls==[]
    assert readiness_record(tmp_path,'tiktok')==failed


def test_current_submitted_incident_reaches_normal_gate(tmp_path,monkeypatch):
    fixture,state,job,failed,settings,page,store,owner,bundle=setup_incident(tmp_path,monkeypatch)
    # No future response while passively waiting: old causal route fails.
    with pytest.raises(SourceAccessWaiting):owner._source_access_gate(state,job)
    assert page.emitted==0 and page.listeners==[]
    assert store.reload(job)['parser_response_recovery']['status']=='unavailable'
    assert readiness_record(tmp_path,'tiktok')==failed
    # The same existing page now supplies a fresh native response upon scroll.
    page.scrolls.clear();page.enable_scroll=True
    ready=owner._source_access_gate(store.get(state['id']),job)
    assert page.scrolls==[(0,900)] and page.emitted==1 and page.listeners==[]
    assert 'tiktok' in ready
    receipt=store.reload(job)['parser_response_recovery']
    assert receipt['status']=='response_validated'
    assert receipt['task_id']==fixture['task']['id']
    assert receipt['job_id']==fixture['job']['id'] and receipt['run_id']==state['run_id']
    assert receipt['query_submitted'] is False and receipt['grants_media_approval'] is False
    current=store.get(state['id'])
    assert 'tiktok' in current['source_acquisition']['core_search_plan']['routes']
    assert not current['source_acquisition'].get('core_fallback')
    assert not current['sources'] and not current['edits']
    assert readiness_record(tmp_path,'tiktok')['previous_failure']==failed


@pytest.mark.parametrize('condition',['login','cooldown','wrong_query','corrupt_preparation'])
def test_scroll_never_bypasses_failed_prerequisite(tmp_path,monkeypatch,condition):
    _,state,job,failed,settings,page,store,owner,bundle=setup_incident(tmp_path,monkeypatch)
    page.enable_scroll=True
    if condition=='login':page.body='Log in to search'
    elif condition=='cooldown':
        import time
        _atomic_json(tmp_path/'search_cooldowns'/'tiktok.json',{'reason':'rate_limited','until':time.time()+120})
    elif condition=='wrong_query':page.url='https://www.tiktok.com/search?q=unrelated'
    else:Path(bundle['frames'][0]).write_bytes(b'corrupt')
    if condition=='cooldown':
        cooldown_path=tmp_path/'search_cooldowns'/'tiktok.json'
        original_cooldown=cooldown_path.read_bytes()
        previous_receipt=copy.deepcopy(job['checkpoint']['parser_response_recovery'])
        ready=owner._source_access_gate(state,job)
        assert 'tiktok' not in ready
        rows=job['checkpoint']['source_access_preflight']['observations']
        blocked=next(row for row in rows if row['provider']=='tiktok')
        assert blocked['status']=='cooldown' and blocked['reason']=='rate_limited'
        assert cooldown_path.read_bytes()==original_cooldown
        assert job['checkpoint']['parser_response_recovery']==previous_receipt
    else:
        with pytest.raises(SourceAccessWaiting):owner._source_access_gate(state,job)
    assert page.scrolls==[] and page.emitted==0 and page.listeners==[]
    assert readiness_record(tmp_path,'tiktok')==failed
    assert not store.get(state['id'])['sources']
