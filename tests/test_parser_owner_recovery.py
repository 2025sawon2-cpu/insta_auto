"""Local route failures reach the owner without granting platform access."""
import copy
import json
import pytest

from hotpost.config import Settings
from hotpost.source_access_preflight import check_access, observe_routes, SourceAccessWaiting
from hotpost.source_search.readiness import record_unresolved
from hotpost.video_agent_actions import parser_repair_context, _gate, ActionHeld
from hotpost.video_agent_context import recovery_target, job_method_fingerprint


def saved_failure(tmp_path, monkeypatch):
    settings=Settings(data_dir=tmp_path, source_browser_search=True)
    (tmp_path/'search_cooldowns').mkdir()
    (tmp_path/'search_cooldowns/tiktok.json').write_text(json.dumps({
        'reason':'captcha','until':0,'requires_verification':False,
        'last_captcha_check':{'status':'clear'}}))
    record_unresolved(tmp_path,'tiktok','product query')
    monkeypatch.setattr('hotpost.browser_search.BROWSER_COOLDOWNS',{})
    return settings


def test_cleared_captcha_never_labels_local_failure_as_captcha(tmp_path,monkeypatch):
    from hotpost import tiktok_download as td
    from hotpost.source_attempts import candidate_execution
    settings=saved_failure(tmp_path,monkeypatch)
    before=(tmp_path/'search_cooldowns/tiktok.json').read_bytes()
    monkeypatch.setattr(td,'endpoint',lambda _: 'http://existing')
    monkeypatch.setattr(td,'attach_browser',lambda *a:pytest.fail('No browser request permitted'))
    diagnostics={}
    with pytest.raises(RuntimeError):
        td.download(settings,'https://www.tiktok.com/@fixture/video/123456789',tmp_path/'out.mp4',1024,diagnostics=diagnostics)
    receipt=candidate_execution({'download_diagnostics':diagnostics,'download_attempted':False})
    assert receipt['access_status']=='readiness_blocked'
    assert receipt['waiting'] and not receipt['observed'] and not receipt['attempted']
    assert (tmp_path/'search_cooldowns/tiktok.json').read_bytes()==before
    assert not (tmp_path/'out.mp4').exists()


def blocked_job(tmp_path,monkeypatch):
    settings=saved_failure(tmp_path,monkeypatch)
    state={'id':'task','run_id':'run','automation':{'active':True},'source_acquisition':{
        'no_progress_rounds':21,'waiting':{'at':1,'searches':[
            {'provider':'tiktok','status':'captcha','observed':False,'basis':'saved_gate'},
            {'provider':'youtube','status':'login_required','observed':False}]}}}
    rows=observe_routes(settings,['tiktok'])
    rows.append({'provider':'yandex-images','status':'ready','reason':'current_existing_page_observed','observed_at':1})
    job={'id':'job','kind':'collect_sources','status':'queued','payload':{'run_id':'run'},'checkpoint':{}}
    with pytest.raises(SourceAccessWaiting):
        check_access(settings,state,job,observe=lambda *_:rows)
    return state,job


def test_repeated_round_enters_owner_diagnosis_without_clearing_any_gate(tmp_path,monkeypatch):
    state,job=blocked_job(tmp_path,monkeypatch);before=copy.deepcopy(state)
    job['checkpoint'].update(not_before=10**12,deferred_wait=True)
    assert parser_repair_context(state,job)
    _gate(state,'park_for_repair',job)
    _gate(state,'retry_repaired',job)
    with pytest.raises(ActionHeld):_gate(state,'advance',job)
    with pytest.raises(ActionHeld):_gate(state,'collect_sources',job)
    row={**job,'checkpoint':json.dumps(job['checkpoint'])}
    assert recovery_target(state,[row])=='job'
    fingerprint=job_method_fingerprint(row)
    for key in ['source_access_preflight','parser_repair_context']:
        job['checkpoint'][key]['at']=999
        for obs in job['checkpoint'][key]['observations']:obs['observed_at']=999
    assert job_method_fingerprint(job)==fingerprint
    assert state==before


@pytest.mark.parametrize('damage',['manual','wrong_run','wrong_task','receipt','access','missing_preflight','paused','hold'])
def test_repair_scope_preserves_real_access_and_owner_boundaries(tmp_path,monkeypatch,damage):
    state,job=blocked_job(tmp_path,monkeypatch)
    cp=job['checkpoint']
    if damage=='manual':cp['parser_repair_context']['observations'][0]['manual_gate_active']=True
    if damage=='wrong_run':job['payload']['run_id']='other'
    if damage=='wrong_task':cp['parser_repair_context']['task_id']='other'
    if damage=='receipt':state['source_acquisition']['receipt_wait']={'pending':True}
    if damage=='access':cp['failure_classification']={'category':'access_blocked'}
    if damage=='missing_preflight':cp['source_access_preflight']['observations']=[]
    if damage=='paused':state['automation']['paused_by_user']=True
    if damage=='hold':state['source_acquisition']['hold']={'reason':'strategy_exhausted'}
    row={**job,'checkpoint':json.dumps(cp)}
    assert recovery_target(state,[row]) is None


def test_active_captcha_and_normal_first_round_are_not_technical_repair(tmp_path,monkeypatch):
    settings=saved_failure(tmp_path,monkeypatch)
    gate=tmp_path/'search_cooldowns/tiktok.json'
    gate.write_text(json.dumps({'reason':'captcha','until':0,'requires_verification':True}))
    rows=observe_routes(settings,['tiktok'])
    assert rows[0]['manual_gate_active'] is True
    state={'id':'task','run_id':'run','source_acquisition':{'no_progress_rounds':21}}
    job={'checkpoint':{}}
    with pytest.raises(SourceAccessWaiting):check_access(settings,state,job,observe=lambda *_:rows)
    assert 'parser_repair_context' not in job['checkpoint']
    state['source_acquisition']['no_progress_rounds']=0
    rows[0]['manual_gate_active']=False
    with pytest.raises(SourceAccessWaiting):check_access(settings,state,job,observe=lambda *_:rows)
    assert 'parser_repair_context' not in job['checkpoint']


def test_claimed_worker_defers_same_job_and_owner_reserves_it(tmp_path,monkeypatch):
    from hotpost.studio import Studio
    from hotpost.video_agents import VideoAgentManager, get_agent
    settings=saved_failure(tmp_path,monkeypatch)
    studio=Studio(settings,workers=False)
    state,_=studio.store.create('local-parser','Local parser',{'protocol':2,'active':True},prepare=False)
    task=state['id'];clock=[1000]
    monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    studio.store.change(task,lambda s,db:s.update(run_id='run',source_acquisition={
        'no_progress_rounds':21,'waiting':{'at':1,'searches':[{'provider':'tiktok','status':'captcha','basis':'saved_gate'}]}}))
    with studio.store.transaction() as db:
        jid=studio.store.enqueue(db,task,'collect_sources',{'run_id':'run'},'local-parser')
    job=studio.store.claim(task_id=task)
    with pytest.raises(SourceAccessWaiting) as caught:
        check_access(settings,studio.store.get(task),job,observe=lambda *_:observe_routes(settings,['tiktok']))
    studio.handle_source_error(job,caught.value)
    class Writer:
        def __init__(self):self.payloads=[]
        def create(self,kind,payload,key):self.payloads.append(payload);return {'id':'model'}
        def start(self):pass
        def get(self,*a,**kw):return {'state':'queued'}
    manager=VideoAgentManager(studio);manager.jobs=Writer()
    studio.store.video_agents=manager;manager.ready.set();manager.pulse=clock[0]
    try:
        manager.step(task);clock[0]+=31;manager.pulse=clock[0];manager.step(task)
        assert get_agent(studio.store,task)['recovery_job_id']==jid
        assert len(manager.jobs.payloads)==1
        assert studio.store.claim(task_id=task) is None
        with studio.store.connect() as db:
            assert db.execute('select count(*) from jobs where task_id=?',(task,)).fetchone()[0]==1
        assert studio.store.get(task)['source_acquisition']['waiting']['searches'][0]['status']=='captcha'
        assert not studio.store.get(task).get('edits')
    finally:manager.pool.shutdown(wait=True)


def test_causal_local_error_survives_large_historical_ledger(tmp_path,monkeypatch):
    from hotpost.video_agent_context import parser_failure_evidence
    state,job=blocked_job(tmp_path,monkeypatch)
    failure={'provider':'tiktok','query':'product query','run_id':'run',
        'parser_revision':job['checkpoint']['parser_repair_context']['observations'][0]['readiness']['parser_revision'],
        'status':'page_unresolved','stage':'locate_search_input','error':'PermissionError',
        'error_detail':'[WinError 5] checkpoint.tmp -> search-checkpoint.json',
        'execution':{'query_submitted':False,'query_url_matched':False}}
    state['source_acquisition']['queries']=[{'old':'x'*20000},copy.deepcopy(failure),
        {**failure,'query':'different'},{**failure,'run_id':'other'}]
    original=copy.deepcopy(state)
    assert parser_failure_evidence(state,[job])==[failure]
    assert state==original
