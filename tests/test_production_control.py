"""Actual store/owner/action boundaries; only external model execution is replaced."""
import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.studio_store import StudioStore
from hotpost.production_control import admit, hold, park
from hotpost.video_agents import VideoAgentManager, enroll, get_agent
from hotpost.video_agent_context import semantic_fingerprint
from test_video_agent_integration import ScriptedWriter, _finished_state
from test_video_agent_actions import setup, action, failed, bind_failure_input, modify, execute
from test_daily_quality import ready, finish, passed


def test_real_budget_refusal_parks_queued_method_and_survives_ticks_and_reconstruction(tmp_path,monkeypatch):
    from hotpost import video_agents
    app=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=app.store.create('same-method','Same method',{'active':True},prepare=False)
    tool={'kind':'inspect_code','repo':'main','path':'hotpost/studio_sources.py',
          'needed_for_repair':'Verify the original failure boundary before patching'}
    writer=ScriptedWriter([tool]);manager=VideoAgentManager(app);manager.jobs=writer
    clock=[1000.0];monkeypatch.setattr(video_agents.time,'time',lambda:clock[0])
    fp=semantic_fingerprint(state)
    manager._save(state['id'],1,{'pending':{'decision_id':'actual-refusal','model_job_id':'0',
        'fingerprint':fp,'repair_execution':True},'repair_evidence_used':[
            json.dumps({k:v for k,v in tool.items() if k not in {'hypothesis','needed_for_repair','_agent_epoch'}},sort_keys=True)]})
    # A queued source method is frozen atomically alongside its owner's hold.
    with app.store.transaction() as db:
        jid=app.store.enqueue(db,state['id'],'collect_sources',{},'source-method')
    try:
        # Prime the exact unchanged queue observation without a real five-minute wait.
        from hotpost.video_agent_context import queue_progress_fingerprint
        with app.store.connect() as db:
            rows=db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchall()
        signature=queue_progress_fingerprint(state,rows)
        manager._save(state['id'],1,{'queue_observation':{'signature':signature,'since':0},
            'queue_observations':{signature:{'since':0}},'pending':{
                'decision_id':'actual-refusal','model_job_id':'0','fingerprint':fp,
                'repair_execution':True,'queue_signature':signature}})
        manager.step(state['id'])
        owner=get_agent(app.store,state['id'])
        assert owner['status']=='held' and '진단 예산 소진' in owner['no_progress_hold']['reason']
        assert app.store.jobs(state['id'])[0]['status']=='paused'
        for _ in range(12):
            clock[0]+=1000;manager.step(state['id']);manager.tick()
        assert writer.payloads==[] and app.store.claim() is None
        restarted=StudioStore(app.store.root)
        with restarted.transaction() as db:
            enroll(db,restarted.get(state['id'],db),'startup-sync')
        assert get_agent(restarted,state['id'])['no_progress_hold']==owner['no_progress_hold']
        assert restarted.claim() is None
        assert list((restarted.root/'production-records').rglob('hold-*.md'))
    finally:manager.pool.shutdown(wait=True)


def test_concurrent_lanes_and_restart_retain_one_video_until_current_qa(tmp_path):
    app=Studio(Settings(data_dir=tmp_path),workers=False)
    first,_=app.store.create('first','First',{'active':True},initial={'source_policy':{}},prepare=False)
    second,_=app.store.create('second','Second',{'active':True},prepare=False)
    with app.store.transaction() as db:
        for tid in (first['id'],second['id']):
            app.store.enqueue(db,tid,'prepare',{},'prepare:'+tid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims=list(pool.map(lambda _:app.store.claim(),range(2)))
    live=[j for j in claims if j]
    assert len(live)==1 and live[0]['task_id']==first['id']
    app.store.finish(live[0],{},lambda *_:None)
    restarted=StudioStore(app.store.root)
    assert restarted.claim(task_id=second['id']) is None
    # Actual final bytes and real QA hash validators, under a saved legacy policy.
    final=_finished_state(tmp_path)
    def accept_final(s,db):
        s.update({k:v for k,v in final.items() if k!='id'})
    restarted.change(first['id'],accept_final)
    assert restarted.claim(task_id=second['id'])['task_id']==second['id']


@pytest.mark.parametrize('damage',['draft_only','changed_render','changed_plan','wrong_script','wrong_voice','paused'])
def test_slot_never_advances_for_unfinished_or_stale_qa(tmp_path,damage):
    app=Studio(Settings(data_dir=tmp_path),workers=False)
    first,_=app.store.create('current','Current',{'active':True},initial={'source_policy':{}},prepare=False)
    other,_=app.store.create('next','Next',{'active':True},prepare=False)
    with app.store.transaction() as db:assert admit(db,first['id'])
    final=_finished_state(tmp_path)
    if damage=='draft_only':final['daily_quality']['status']='pending'
    elif damage=='changed_render':(tmp_path/'final.mp4').write_bytes(b'not reviewed')
    elif damage=='changed_plan':(tmp_path/'plan.json').write_text('{}')
    elif damage=='wrong_script':final['approved_script_id']='different'
    elif damage=='wrong_voice':final['approved_voice_id']='different'
    elif damage=='paused':
        final['daily_quality']['status']='pending'
        final['automation']={'active':False,'paused_by_user':True}
    app.store.change(first['id'],lambda s,db:s.update({k:v for k,v in final.items() if k!='id'}))
    with app.store.transaction() as db:assert not admit(db,other['id'])


def test_guarded_changed_media_resume_reuses_exact_job_and_preserves_other_pauses(setup):
    app,state,root=setup
    jid=failed(app,kind='collect_sources');bind_failure_input(app,jid)
    incident=park(app.store,state['id'],1,'Saved source method has no new evidence',{},'refusal')
    assert incident and app.store.claim() is None
    # Timestamps, a hypothesis, or resume-auto cannot clear a technical hold.
    value=action('retry',job_id=jid,hold_id=incident['id'])
    assert execute(app,value)['status']=='held'
    path=root/'actual-new-source.mp4';path.write_bytes(b'new source media')
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    modify(app,sources=[{'id':'new','path':str(path),'sha256':sha}])
    value['evidence']=[{'path':str(path),'sha256':sha}]
    result=execute(app,value,decision='new-material')
    assert result['status']=='queued' and result['job_ids']==[jid]
    owner=get_agent(app.store,state['id'])
    assert not owner.get('no_progress_hold') and owner['hold_history'][-1]['id']==incident['id']
    claimed=app.store.claim('sources')
    assert claimed['id']==jid
    app.store.finish(claimed,{},lambda s,db,r:s.update(message='same video source stage accepted'))
    assert app.store.get(state['id'])['message']=='same video source stage accepted'
    assert app.store.jobs(state['id'])[0]['status']=='done'


def test_user_stop_and_access_gate_survive_attempt_resolution(setup):
    app,state,root=setup;jid=failed(app,kind='collect_sources');bind_failure_input(app,jid)
    incident=park(app.store,state['id'],1,'Source failure',{},'stop')
    path=root/'new.mp4';path.write_bytes(b'new')
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    modify(app,sources=[{'id':'new','path':str(path),'sha256':sha}],
           source_acquisition={'waiting':{'searches':[{'status':'captcha'}]}})
    value=action('retry',job_id=jid,hold_id=incident['id'],evidence=[{'path':str(path),'sha256':sha}])
    assert execute(app,value)['status']=='held'
    modify(app,automation={'active':False,'paused_by_user':True})
    assert execute(app,value,decision='paused')['status']=='held'
    assert get_agent(app.store,state['id'])['no_progress_hold']['id']==incident['id']


def test_normal_model_queue_wait_does_not_park_or_create_another_call(tmp_path):
    app=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=app.store.create('wait','Wait',{'active':True},prepare=False)
    class QueuedWriter(ScriptedWriter):
        def get(self,*args,**kwargs):return {'state':'queued'}
    writer=QueuedWriter([]);manager=VideoAgentManager(app);manager.jobs=writer
    try:
        for _ in range(15):manager.step(state['id'])
        assert len(writer.payloads)==1
        assert get_agent(app.store,state['id'])['pending']
        assert not get_agent(app.store,state['id']).get('no_progress_hold')
    finally:manager.pool.shutdown(wait=True)


def test_resolved_attempt_accepts_current_final_qa_before_next_video(ready):
    """Real reserve/retry/claim/QA acceptance; no validator is replaced."""
    from hotpost.retry_budget import reserve
    from hotpost.video_agent_actions import execute as run_action
    from hotpost.video_agent_context import completion
    app,tid=ready
    job=app.store.claim(task_id=tid)
    classification={'category':'no_progress','retryable':False,'reason':'requires_new_evidence'}
    job['checkpoint']['failure_classification']=classification
    assert not reserve(app.store,job,classification,app.store.get(tid))
    app.store.fail(job,ValueError('saved unresolved source evidence'))
    with app.store.transaction() as db:
        follow_up=app.store.enqueue(db,tid,'register',{'edit_id':'old-edit'},'untouched-follow-up')
    before=copy.deepcopy(app.store.get(tid))
    incident=park(app.store,tid,1,'Same evidence method is exhausted',{},'held-qa')
    other,_=app.store.create('after-current','Next',{'active':True})
    assert app.store.claim(task_id=other['id']) is None
    path=app.folder(tid)/'new-reviewed-source.mp4';path.write_bytes(b'new verified evidence')
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    source=copy.deepcopy(before['sources'][0])
    source.update(id='additional',path=str(path),sha256=sha)
    source['functional_review']['source_sha256']=sha
    app.store.change(tid,lambda s,db:s['sources'].append(source))
    current=app.store.get(tid)
    result=run_action(app,tid,{'kind':'retry','job_id':job['id'],'hold_id':incident['id'],
        'hypothesis':'Use newly reviewed source evidence retained for the same video',
        '_agent_epoch':1,'evidence':[{'path':str(path),'sha256':sha}]},
        'current-qa-resume',semantic_fingerprint(current))
    assert result['status']=='queued' and result['job_ids']==[job['id']]
    assert result['restored_job_ids']==[follow_up]
    assert app.store.claim(task_id=other['id']) is None
    follow=app.store.claim(job_id=follow_up)
    assert follow and follow['id']==follow_up
    app.store.finish(follow,{'registration_deferred':True,'registration_note':'fixture editor busy'},
                     lambda s,db,r:app._accept(s,follow,r,db))
    assert finish(app,tid,passed('old-edit'))['id']==job['id']
    current=app.store.get(tid)
    assert current['status']=='completed' and completion(current)
    assert current['scripts']==before['scripts'] and current['voices']==before['voices']
    assert current['run_id']==before['run_id']
    assert app.store.claim(task_id=other['id'])['task_id']==other['id']


def test_resuming_one_method_never_revives_preexisting_failed_or_paused_methods(setup):
    app,state,root=setup;jid=failed(app,kind='collect_sources');bind_failure_input(app,jid)
    with app.store.transaction() as db:
        old=app.store.enqueue(db,state['id'],'voice',{},'previously-failed')
        paused=app.store.enqueue(db,state['id'],'edit',{},'previously-paused')
        db.execute("UPDATE jobs SET status='failed' WHERE id=?",(old,))
        db.execute("UPDATE jobs SET status='paused' WHERE id=?",(paused,))
    incident=park(app.store,state['id'],1,'Exhausted source method',{},'multi-held')
    path=root/'actual-fresh.mp4';path.write_bytes(b'fresh');sha=hashlib.sha256(path.read_bytes()).hexdigest()
    modify(app,sources=[{'id':'new','path':str(path),'sha256':sha}])
    result=execute(app,action('retry',job_id=jid,hold_id=incident['id'],
        evidence=[{'path':str(path),'sha256':sha}]),decision='resume-source')
    assert result['status']=='queued' and not result.get('restored_job_ids')
    owner=get_agent(app.store,state['id'])
    assert set(owner['held_method_incidents'])=={old,paused}
    statuses={j['id']:j['status'] for j in app.store.jobs(state['id'])}
    assert statuses[old]=='failed' and statuses[paused]=='paused'


def test_claim_retains_user_stop_but_accepts_exact_manual_source_permission(tmp_path):
    app=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=app.store.create('stopped','Stopped',{'active':True},prepare=False)
    with app.store.transaction() as db:assert admit(db,state['id'])
    app.store.change(state['id'],lambda s,db:s['automation'].update(active=False,paused_by_user=True,paused_at=123))
    with app.store.transaction() as db:
        app.store.enqueue(db,state['id'],'prepare',{},'forbidden-prepare')
        source=app.store.enqueue(db,state['id'],'refresh_sources',
            {'manual_source_request':True,'pause_token':123},'explicit-source')
    assert app.store.claim('media') is None
    assert app.store.claim('sources')['id']==source
