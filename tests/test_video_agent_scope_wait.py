import copy,json
from pathlib import Path
import pytest
from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.video_agents import VideoAgentManager,get_agent
from hotpost.video_agent_context import job_method_fingerprint,queue_progress_fingerprint,recovery_target,scope_repair_context


def incident():
    state={'id':'task','run_id':'run','automation':{'active':True},
           'source_acquisition':{'no_progress_rounds':1}}
    rows=[{'provider':'tiktok','status':'query_exhausted','reason':'no_unused_supported_scope',
           'attempted':False,'query':'','observed_at':1000},
          {'provider':'youtube','status':'login_required','reason':'saved_manual_gate_requires_explicit_recheck',
           'attempted':False,'query':'','observed_at':1000}]
    job={'id':'job','task_id':'task','kind':'collect_sources','status':'queued','payload':{'run_id':'run'},
         'checkpoint':{'deferred_wait':True,'not_before':1030,'source_access_preflight':{
             'at':1001,'observations':rows,'ready_routes':[]}}}
    return state,job


def test_repeated_preflight_timestamps_are_not_new_method_or_progress():
    state,job=incident();before=copy.deepcopy(job)
    signature=queue_progress_fingerprint(state,[job]);method=job_method_fingerprint(job)
    cp=job['checkpoint'];cp['not_before']=1060;cp['_claim_token']='new-claim'
    cp['source_access_preflight']['at']=1031
    for row in cp['source_access_preflight']['observations']:row['observed_at']=1030
    assert job_method_fingerprint(job)==method
    assert queue_progress_fingerprint(state,[job])==signature
    assert before['checkpoint']['source_access_preflight']['at']==1001
    cp['source_access_preflight']['observations'][0]['status']='captcha'
    assert queue_progress_fingerprint(state,[job])!=signature


def test_internal_scope_wait_can_be_diagnosed_without_authorizing_search(monkeypatch):
    state,job=incident();monkeypatch.setattr('hotpost.video_agent_context.time.time',lambda:1010)
    row={**job,'checkpoint':json.dumps(job['checkpoint']),'payload':json.dumps(job['payload'])}
    before=copy.deepcopy(state)
    assert recovery_target(state,[row],{'job':700})=='job'
    assert state==before


@pytest.mark.parametrize('change',['status','reason','query','retry_at','ready_routes','scope','source','review'])
def test_real_evidence_changes_still_advance_progress(change):
    state,job=incident();signature=queue_progress_fingerprint(state,[job])
    pre=job['checkpoint']['source_access_preflight'];row=pre['observations'][0]
    if change=='ready_routes':pre['ready_routes']=['tiktok']
    elif change=='source':state['sources']=[{'sha256':'new-received-video'}]
    elif change=='review':state['sources']=[{'sha256':'same','review_outcome':{'status':'accepted'}}]
    else:row[change]={'status':'captcha','reason':'visible_login_wall','query':'new product query',
                     'retry_at':2000,'scope':{'cursor':'page-2'}}[change]
    assert queue_progress_fingerprint(state,[job])!=signature


@pytest.mark.parametrize('damage',['wrong_run','wrong_task','receipt','hold','user_pause','real_wait',
    'access_failure','ready_route','no_exhausted','attempted','wrong_reason','future_retry','malformed_time',
    'not_deferred','cooldown','first_round','missing_task','future_observation'])
def test_scope_diagnosis_preserves_real_access_and_ownership_gates(monkeypatch,damage):
    state,job=incident();monkeypatch.setattr('hotpost.video_agent_context.time.time',lambda:1010)
    cp=job['checkpoint'];pre=cp['source_access_preflight'];a=state['source_acquisition']
    if damage=='wrong_run':job['payload']['run_id']='other'
    elif damage=='wrong_task':job['task_id']='other'
    elif damage=='receipt':a['receipt_wait']={'pending':True}
    elif damage=='hold':a['hold']={'reason':'strategy_exhausted'}
    elif damage=='user_pause':state['automation']['paused_by_user']=True
    elif damage=='real_wait':a['waiting']={'searches':[{'provider':'tiktok','status':'captcha'}]}
    elif damage=='access_failure':cp['failure_classification']={'category':'access_blocked'}
    elif damage=='ready_route':pre['ready_routes']=['tiktok']
    elif damage=='no_exhausted':pre['observations'][0]['status']='login_required'
    elif damage=='attempted':pre['observations'][0]['attempted']=True
    elif damage=='wrong_reason':pre['observations'][0]['reason']='rate_limited'
    elif damage=='future_retry':pre['observations'][0]['retry_at']=2000
    elif damage=='malformed_time':pre['at']=float('nan')
    elif damage=='not_deferred':cp['deferred_wait']=False
    elif damage=='cooldown':pre['observations'][1]['status']='cooldown'
    elif damage=='first_round':a['no_progress_rounds']=0
    elif damage=='missing_task':job.pop('task_id')
    elif damage=='future_observation':pre['observations'][0]['observed_at']=2000
    row={**job,'checkpoint':json.dumps(cp),'payload':json.dumps(job['payload'])}
    assert recovery_target(state,[row],{'job':700}) is None


def test_captured_scope_wait_has_stable_evidence_without_touching_operational_data():
    path=Path(__file__).resolve().parents[1]/'data/agent-progress-repair-20261019/captured-scope-preflight-wait.json'
    if not path.is_file():pytest.skip('Optional local incident capture is unavailable')
    captured=json.loads(path.read_text('utf8'));state=captured['state'];job=captured['job']
    before=copy.deepcopy(captured);signature=queue_progress_fingerprint(state,[job])
    assert scope_repair_context(state,job,now=captured['at'])
    cp=json.loads(job['checkpoint']);cp['source_access_preflight']['at']+=30
    for row in cp['source_access_preflight']['observations']:row['observed_at']+=30
    job['checkpoint']=json.dumps(cp)
    assert queue_progress_fingerprint(state,[job])==signature
    assert json.loads(path.read_text('utf8'))==before


def test_repeated_claim_preflight_defers_then_reserves_same_job(tmp_path,monkeypatch):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('scope','Scope',{'protocol':2,'active':True},prepare=False)
    task=state['id'];clock=[1000]
    monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    studio.store.change(task,lambda s,db:s.update(run_id='run',source_acquisition={'no_progress_rounds':1}))
    with studio.store.transaction() as db:jid=studio.store.enqueue(db,task,'collect_sources',{'run_id':'run'},'scope')
    class Writer:
        def __init__(self):self.payloads=[]
        def create(self,kind,payload,key):self.payloads.append(payload);return {'id':'model'}
        def start(self):pass
        def get(self,*a,**kw):return {'state':'queued'}
    manager=VideoAgentManager(studio);manager.jobs=Writer();studio.store.video_agents=manager
    manager.ready.set();manager.pulse=clock[0]
    try:
        for n in range(11):
            manager.pulse=clock[0]
            job=studio.store.claim(task_id=task);assert job is not None, (n,get_agent(studio.store,task))
            _,sample=incident();cp=sample['checkpoint']
            cp['source_access_preflight']['at']=clock[0]
            for r in cp['source_access_preflight']['observations']:r['observed_at']=clock[0]
            job['checkpoint'].update(cp)
            studio.store.defer(job,'same exhausted scopes',30,waiting=True)
            manager.pulse=clock[0];manager.step(task)
            clock[0]+=31
        assert get_agent(studio.store,task)['recovery_job_id']==jid
        assert len(manager.jobs.payloads)==1
        assert manager.jobs.payloads[0]['evidence']['recovery_job_id']==jid
        assert studio.store.claim(task_id=task) is None
        with studio.store.connect() as db:
            assert db.execute('select count(*) from jobs where task_id=?',(task,)).fetchone()[0]==1
        assert not studio.store.get(task).get('edits')
        other,_=studio.store.create('other','Other',{'active':True})
        manager.pulse=clock[0]
        assert studio.store.claim(task_id=other['id']) is None  # Current video has not passed final QA.
    finally:manager.pool.shutdown(wait=True)
