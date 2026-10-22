"""Independent production entry/authority tests using the real task store."""
import copy
import json
import pytest

def test_code_search_is_literal_bounded_and_never_reads_runtime_data(tmp_path):
    from types import SimpleNamespace
    from hotpost.video_agent_context import search_code
    (tmp_path/'hotpost').mkdir();(tmp_path/'data').mkdir()
    (tmp_path/'hotpost'/'source.py').write_text('raise ValueError("checkpoint SHA wait")','utf-8')
    (tmp_path/'data'/'private.py').write_text('checkpoint SHA wait private','utf-8')
    result=search_code(SimpleNamespace(roots={'main':tmp_path}),'main','checkpoint SHA')
    assert [r['path'] for r in result['matches']]==['hotpost/source.py']
    assert search_code(SimpleNamespace(roots={'main':tmp_path}),'main','.*')['matches']==[]

def test_same_decision_service_wait_is_replaced_by_actual_tool_outcome(tmp_path):
    from hotpost.video_agents import VideoAgentManager
    app=studio(tmp_path);state,_=app.store.create('receipt-final','Receipt',{'active':True},prepare=False)
    manager=VideoAgentManager(app)
    try:
        manager._save(state['id'],1,{}, {'status':'waiting'},'decision')
        manager._save(state['id'],1,{}, {'status':'applied'},'decision')
        with app.store.connect() as db:
            rows=db.execute('SELECT observation FROM video_agent_steps WHERE task_id=?',(state['id'],)).fetchall()
        assert len(rows)==1 and json.loads(rows[0][0])['status']=='applied'
    finally:manager.pool.shutdown(wait=True)

from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.video_agents import enroll, get_agent
from hotpost.video_agent_context import semantic_fingerprint


def studio(tmp_path):
    return Studio(Settings(data_dir=tmp_path), workers=False)


@pytest.mark.parametrize('mode', ['automatic','manual','self_shot'])
def test_all_creation_paths_enroll_once_before_prepare_queue(tmp_path,mode):
    app=studio(tmp_path)
    auto={'protocol':2,'active':mode=='automatic','selection_mode':mode}
    initial={'creation_mode':'self_shot','self_shot':{'started':False}} if mode=='self_shot' else {}
    first,created=app.store.create('same-'+mode,'Task',auto,initial=initial)
    owner=get_agent(app.store,first['id'])
    assert created and owner and owner['epoch']==1
    second,created=app.store.create('same-'+mode,'Different',{'active':True})
    assert not created and first['id']==second['id']
    assert get_agent(app.store,first['id'])['epoch']==1
    assert app.store.get(first['id'])==first
    assert len(app.store.jobs(first['id']))==1


def test_user_command_revokes_epoch_before_action_without_changing_task_revision(tmp_path,monkeypatch):
    app=studio(tmp_path)
    state,_=app.store.create('authority','Authority',{'protocol':2,'active':True},prepare=False)
    before=copy.deepcopy(state);epoch=get_agent(app.store,state['id'])['epoch']
    seen=[]
    def command(task_id,action,data):
        seen.append(get_agent(app.store,task_id)['epoch'])
        assert get_agent(app.store,task_id)['status']=='user_command'
        assert app.store.get(task_id)['revision']==before['revision']
        def pause(s,db):
            s['automation'].update(active=False,paused_by_user=True,paused_at=123)
        app.store.change(task_id,pause,data['revision'])
        return {'ok':True}
    monkeypatch.setattr(app,'_action',command)
    assert app.action(state['id'],'pause-auto',{'revision':state['revision']})=={'ok':True}
    assert seen==[epoch+1] and get_agent(app.store,state['id'])['epoch']==epoch+1
    saved=app.store.get(state['id'])
    assert saved['automation']['paused_by_user'] and not saved['automation']['active']


def test_failed_user_command_revokes_old_decision_but_cannot_activate_task(tmp_path,monkeypatch):
    app=studio(tmp_path)
    state,_=app.store.create('rejected','Rejected',{'protocol':2,'active':False,'paused_by_user':True},prepare=False)
    before=copy.deepcopy(state);epoch=get_agent(app.store,state['id'])['epoch']
    def rejected(*args):raise ValueError('Invalid input')
    monkeypatch.setattr(app,'_action',rejected)
    with pytest.raises(ValueError,match='Invalid input'):app.action(state['id'],'resume-auto',{})
    assert app.store.get(state['id'])==before
    assert get_agent(app.store,state['id'])['epoch']==epoch+1


def test_command_does_not_hold_write_transaction_during_slow_work(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    app=studio(tmp_path);state,_=app.store.create('concurrent-agent','Concurrent',prepare=False)
    def command(*args):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(app.store.change,state['id'],lambda s,db:s.update(progress=47)).result(timeout=2)
        return {}
    monkeypatch.setattr(app,'_action',command)
    app.action(state['id'],'check-script',{})
    assert app.store.get(state['id'])['progress']==47


def test_user_pause_changes_semantic_authority_even_with_same_selected_assets(tmp_path):
    app=studio(tmp_path);state,_=app.store.create('fingerprint-agent','Authority',
        {'protocol':2,'active':True,'paused_by_user':False},prepare=False)
    old=semantic_fingerprint(state)
    paused=copy.deepcopy(state);paused['automation'].update(active=False,paused_by_user=True,paused_at=99)
    assert semantic_fingerprint(paused)!=old
    paused['automation'].update(active=False,paused_by_user=False,pause_reason='save-script')
    assert semantic_fingerprint(paused)!=old


def test_owner_actions_reject_stale_epoch_even_after_pause_resume_aba(tmp_path):
    from hotpost.video_agent_actions import execute
    app=studio(tmp_path);state,_=app.store.create('epoch-agent','Epoch',
        {'protocol':2,'active':True},prepare=False)
    old=get_agent(app.store,state['id'])['epoch']
    fingerprint=semantic_fingerprint(state)
    with app.store.transaction() as db:
        enroll(db,state,'user_command',renew=True)
        enroll(db,state,'user_command')
    result=execute(app,state['id'],{'kind':'advance','hypothesis':'Complete this task','_agent_epoch':old},
                   'stale-epoch',fingerprint)
    assert result['status']=='held' and not app.store.jobs(state['id'])


def _finished_state(tmp_path):
    import hashlib
    from hotpost.daily_quality import POLICY
    video=tmp_path/'final.mp4';video.write_bytes(b'actual reviewed render')
    plan=tmp_path/'plan.json';plan.write_text('{"reviewed":true}')
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    edit={'id':'e','script_id':'s','voice_id':'v','export_path':str(video),
          'plan_path':str(plan),'quality_verified':True,'export_verified':True}
    return {'id':'complete','status':'completed','edit_id':'e','edits':[edit],
        'script_id':'s','approved_script_id':'s','scripts':[{'id':'s','text':'approved'}],
        'voice_id':'v','approved_voice_id':'v','voices':[{'id':'v','script_id':'s'}],
        'daily_quality':{'policy':POLICY,'status':'passed','reviewed_edit_id':'e',
            'reviews':[{'edit_id':'e','passed':True,'render_sha256':digest(video),'plan_sha256':digest(plan)}]}}


def test_owner_completion_requires_actual_qa_bytes_and_current_approved_inputs(tmp_path):
    from hotpost.video_agent_context import completion
    state=_finished_state(tmp_path)
    assert completion(state)['completion_verified']
    changed=copy.deepcopy(state);changed['approved_script_id']='new-script'
    assert completion(changed) is None
    changed=copy.deepcopy(state);changed['approved_voice_id']='new-voice'
    assert completion(changed) is None
    from pathlib import Path
    Path(state['edits'][0]['export_path']).write_bytes(b'different unreviewed bytes')
    assert completion(state) is None


def test_repeated_failed_model_is_held_with_resolution_record_without_repeated_calls(tmp_path,monkeypatch):
    from hotpost import video_agents
    app=studio(tmp_path);state,_=app.store.create('failed-model-agent','Failed model',
        {'protocol':2,'active':True},prepare=False)
    manager=video_agents.VideoAgentManager(app)
    class Writer:
        def __init__(self):self.created=[]
        def create(self,*args):
            self.created.append(args);return {'id':'model-'+str(len(self.created))}
        def start(self):pass
        def get(self,*args,**kwargs):return {'state':'failed','result':{},'error':'Same deterministic model failure'}
    writer=Writer();manager.jobs=writer
    clock=[1000.0];monkeypatch.setattr(video_agents.time,'time',lambda:clock[0])
    try:
        for _ in range(10):
            manager.step(state['id']);clock[0]+=1000
        assert len(writer.created)==3
        owner=get_agent(app.store,state['id'])
        assert not owner.get('blocked_observation')
        assert owner['status']=='held' and owner['no_progress_hold']['next_action']
        assert owner['no_progress_hold']['responsible_owner']==state['id']
        assert owner['pending'] is None
    finally:manager.pool.shutdown(wait=True)


def test_normal_production_and_model_queue_waits_preserve_owner_health(tmp_path):
    from hotpost import video_agents
    app=studio(tmp_path);busy,_=app.store.create('busy-owner','Busy',{'active':True})
    idle,_=app.store.create('model-wait-owner','Model wait',{'active':True},prepare=False)
    manager=video_agents.VideoAgentManager(app);manager.ready.set();manager.pulse=video_agents.time.time()
    class QueuedWriter(ScriptedWriter):
        def get(self,*args,**kwargs):return {'state':'queued'}
    writer=QueuedWriter([]);manager.jobs=writer
    try:
        for _ in range(3):manager.step(busy['id'])
        assert not writer.payloads and manager.healthy()
        for _ in range(4):manager.step(idle['id'])
        assert not writer.payloads and manager.healthy()
        assert get_agent(app.store,idle['id'])['status']=='waiting_turn'
        assert get_agent(app.store,idle['id'])['waiting_for_video']==busy['id']
    finally:manager.pool.shutdown(wait=True)


def test_dispatcher_failure_closes_admission_without_claiming_queued_work(tmp_path,monkeypatch):
    from hotpost import video_agents
    app=studio(tmp_path);state,_=app.store.create('unhealthy-owner','Unhealthy',{'active':True})
    manager=video_agents.VideoAgentManager(app);app.store.video_agents=manager
    def failed_tick():raise RuntimeError('Injected dispatcher failure')
    monkeypatch.setattr(manager,'tick',failed_tick)
    monkeypatch.setattr(manager.stop,'wait',lambda seconds:manager.stop.set())
    manager.run()
    manager.stop.clear()  # The fault itself, not just shutdown, must close admission.
    assert manager.dispatch_error and not manager.healthy()
    assert app.store.claim() is None
    assert app.store.jobs(state['id'])[0]['status']=='queued'


def test_queue_observation_distinguishes_pacing_from_meaningful_receipt_change(tmp_path,monkeypatch):
    from hotpost import video_agents
    app=studio(tmp_path);state,_=app.store.create('queued-evidence','Queued evidence',{'active':True})
    manager=video_agents.VideoAgentManager(app);clock=[1000.0]
    monkeypatch.setattr(video_agents.time,'time',lambda:clock[0])
    class QueuedWriter(ScriptedWriter):
        def get(self,*args,**kwargs):return {'state':'queued'}
    writer=QueuedWriter([]);manager.jobs=writer
    job=app.store.jobs(state['id'])[0]
    def checkpoint(value):
        with app.store.transaction() as db:
            db.execute('UPDATE jobs SET checkpoint=? WHERE id=?',(json.dumps(value),job['id']))
    try:
        manager.step(state['id'])
        clock[0]=1299;checkpoint({'not_before':9000,'_claim_token':'transient'})
        manager.step(state['id']);assert not writer.payloads
        assert get_agent(app.store,state['id'])['queue_observation']['since']==1000
        clock[0]=1301;manager.step(state['id']);assert len(writer.payloads)==1
        model_evidence=writer.payloads[-1]['evidence']
        assert model_evidence['jobs'][0]['checkpoint']['not_before']==9000
        clock[0]=1302;checkpoint({'not_before':9000,'verified_receipt':'new-search-result'})
        manager.step(state['id'])
        assert get_agent(app.store,state['id'])['queue_observation']['since']==1302
        assert get_agent(app.store,state['id'])['pending'] is None
        with app.store.connect() as db:
            observed=json.loads(db.execute('SELECT observation FROM video_agent_steps WHERE task_id=? ORDER BY id DESC LIMIT 1',
                                           (state['id'],)).fetchone()[0])
        assert observed['status']=='stale_queue_evidence'
        clock[0]=1601;manager.step(state['id']);assert len(writer.payloads)==1
    finally:manager.pool.shutdown(wait=True)


class ScriptedWriter:
    def __init__(self,actions):self.actions=actions;self.payloads=[]
    def create(self,kind,payload,key):
        self.payloads.append(copy.deepcopy(payload));return {'id':str(len(self.payloads)-1)}
    def start(self):pass
    def get(self,job_id,**kwargs):
        return {'id':job_id,'state':'completed','result':{'value':{'action':self.actions[int(job_id)]}}}


def test_owner_observes_tool_failure_then_uses_different_method_until_verified_completion(tmp_path,monkeypatch):
    from hotpost import video_agents, video_agent_actions
    # Minimal historical QA fixture; v6 body diversity is covered by its policy suite.
    app=studio(tmp_path);state,_=app.store.create('tool-loop','Tool loop',{'active':True},
        initial={'source_policy':{}},prepare=False)
    artifact=app.folder(state['id'])/'diagnostic.json'
    artifact.parent.mkdir(parents=True,exist_ok=True);artifact.write_text('{"cause":"missing reviewed interval"}')
    writer=ScriptedWriter([
        {'kind':'inspect_artifact','path':str(artifact)},
        {'kind':'repair_scenes','hypothesis':'Inspect the currently reviewed alternate interval'},
        {'kind':'collect_sources','hypothesis':'Actual interval receipt confirms existing source cannot repair this scene'},
    ])
    manager=video_agents.VideoAgentManager(app);manager.jobs=writer
    called=[];clock=[1000.0];monkeypatch.setattr(video_agents.time,'time',lambda:clock[0])
    def production(studio,task,action,decision,fingerprint):
        called.append(action['kind'])
        if action['kind']=='repair_scenes':return {'status':'held','error':'No clean independently reviewed interval'}
        finished=_finished_state(tmp_path)
        studio.store.change(task,lambda s,db:s.update({k:v for k,v in finished.items() if k!='id'}))
        return {'status':'completed','job_id':'real-receipt-fixture'}
    monkeypatch.setattr(video_agent_actions,'execute',production)
    try:
        for _ in range(7):manager.step(state['id']);clock[0]+=1000
        assert called==['repair_scenes','collect_sources']
        previous=writer.payloads[1]['evidence']['previous_steps']
        assert 'missing reviewed interval' in previous[-1]['result']['content']
        previous=writer.payloads[2]['evidence']['previous_steps']
        assert previous[-1]['result']['status']=='held'
        assert 'No clean' in previous[-1]['result']['error']
        owner=get_agent(app.store,state['id'])
        assert owner['status']=='completed' and owner['completion']['completion_verified']
        assert len(writer.payloads)==3
    finally:manager.pool.shutdown(wait=True)


def test_model_response_arriving_after_user_command_cannot_execute(tmp_path,monkeypatch):
    from hotpost import video_agents
    app=studio(tmp_path);state,_=app.store.create('stale-model','Stale model',{'active':True},prepare=False)
    manager=video_agents.VideoAgentManager(app)
    writer=ScriptedWriter([{'kind':'advance'}]);manager.jobs=writer
    invoked=[];monkeypatch.setattr(manager,'execute',lambda *args:invoked.append(args))
    def response_after_command(*args,**kwargs):
        with app.store.transaction() as db:
            enroll(db,state,'user_command',renew=True)
            enroll(db,state,'user_command')
        return {'state':'completed','result':{'value':{'action':{'kind':'advance'}}}}
    try:
        manager.step(state['id'])
        monkeypatch.setattr(writer,'get',response_after_command)
        manager.step(state['id'])
        assert not invoked
        owner=get_agent(app.store,state['id'])
        assert owner['epoch']==2 and owner['pending'] is None
    finally:manager.pool.shutdown(wait=True)


def test_restart_marker_blocks_new_claims_and_next_process_verifies_loaded_hashes(tmp_path,monkeypatch):
    import hashlib
    from pathlib import Path
    from hotpost import video_agents, video_agent_runtime
    from hotpost.video_agent_repairs import VideoRepairPipeline, RepairRejected
    app=studio(tmp_path);state,_=app.store.create('restart','Restart',{'active':True})
    manager=video_agents.VideoAgentManager(app);app.store.video_agents=manager
    manager.ready.set();manager.pulse=video_agents.time.time()
    source=Path(video_agent_runtime.__file__)
    receipt={'repair_id':'tested-reviewed','applied_at':1,'files':[{'repo':'main','path':'hotpost/video_agent_runtime.py',
             'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}]}
    try:
        manager.request_restart(receipt)
        assert app.store.claim() is None
        manager.tick();assert not manager.futures
        assert json.loads((app.store.root/'agent-restart.json').read_text('utf-8'))==receipt
        with pytest.raises((RepairRejected,FileNotFoundError)):
            video_agent_runtime.configure(app,manager)
        assert not (app.store.root/'agent-loaded.json').exists()
        # The repair suite tests real signatures; isolate this module's load boundary.
        def authenticated(pipeline,repair_id):
            assert repair_id==receipt['repair_id']
            return copy.deepcopy(receipt)
        monkeypatch.setattr(VideoRepairPipeline,'applied_receipt',authenticated)
        video_agent_runtime.configure(app,manager)
        loaded=json.loads((app.store.root/'agent-loaded.json').read_text('utf-8'))
        assert loaded['repair_id']==receipt['repair_id'] and loaded['process_id']>0
        receipt['files'][0]['sha256']='0'*64
        (app.store.root/'agent-restart.json').write_text(json.dumps(receipt),'utf-8')
        with pytest.raises(RuntimeError,match='SHA'):
            video_agent_runtime.configure(app,manager)
    finally:manager.pool.shutdown(wait=True)


def test_failed_owner_future_does_not_automatically_skip_to_another_video(tmp_path,monkeypatch):
    from concurrent.futures import Future
    from hotpost import video_agents
    app=studio(tmp_path);failed,_=app.store.create('owner-fault','Fault',{'active':True})
    other,_=app.store.create('owner-other','Other',{'active':True})
    manager=video_agents.VideoAgentManager(app);app.store.video_agents=manager
    monkeypatch.setattr(video_agents.time,'time',lambda:1000.0)
    manager.ready.set();manager.pulse=1000.0
    bad=Future();bad.set_exception(RuntimeError('Snapshot unavailable'))
    manager.futures[failed['id']]=bad
    manager.future_epochs[failed['id']]=get_agent(app.store,failed['id'])['epoch']
    # Keep the independent owner in flight, without scheduling any real work.
    manager.futures[other['id']]=Future()
    try:
        manager.tick()
        owner=get_agent(app.store,failed['id'])
        assert owner['runtime_error']=='Snapshot unavailable' and owner['next_at']==1030
        assert failed['id'] not in manager.futures
        assert app.store.claim(task_id=failed['id']) is None
        assert app.store.claim(task_id=other['id']) is None
    finally:manager.pool.shutdown(wait=True)


def test_queued_diagnosis_cannot_execute_after_that_queue_becomes_failed(tmp_path,monkeypatch):
    from hotpost import video_agents
    app=studio(tmp_path);state,_=app.store.create('queue-transition','Queue transition',{'active':True})
    manager=video_agents.VideoAgentManager(app);clock=[1000.0]
    monkeypatch.setattr(video_agents.time,'time',lambda:clock[0])
    manager.jobs=ScriptedWriter([{'kind':'advance'}]);invoked=[]
    monkeypatch.setattr(manager,'execute',lambda *args:invoked.append(args) or {'status':'completed'})
    try:
        manager.step(state['id']);clock[0]=1301;manager.step(state['id'])
        assert get_agent(app.store,state['id'])['pending']
        with app.store.transaction() as db:
            db.execute("UPDATE jobs SET status='failed',error='new failure' WHERE task_id=?",(state['id'],))
        manager.step(state['id'])
        assert not invoked
        assert get_agent(app.store,state['id'])['pending'] is None
    finally:manager.pool.shutdown(wait=True)


@pytest.mark.parametrize('newline',['\n','\r\n'])
def test_search_positions_open_exact_unicode_function_body(tmp_path,newline):
    from types import SimpleNamespace
    from hotpost.video_agent_context import search_code
    from hotpost.video_agents import VideoAgentManager
    import hashlib
    root=tmp_path/'repo';(root/'hotpost').mkdir(parents=True)
    source=(newline.join(['# 한글 설명 '+str(i) for i in range(3000)])+newline+'def exact_function():'+newline+'    return "정확한 본문"'+newline)
    path=root/'hotpost'/'sample.py';path.write_bytes(source.encode('utf8'))
    pipeline=SimpleNamespace(roots={'main':root},inspect_code=lambda repo,p:{'content':source,'base_sha256':hashlib.sha256(source.encode()).hexdigest()})
    found=search_code(pipeline,'main','def exact_function')['matches'][0]
    assert found['offset']==source.index('def exact_function') and found['line']==3001
    app=studio(tmp_path/'app');state,_=app.store.create('nav','Navigation',{'active':True},prepare=False)
    app.video_repair_pipeline=pipeline;manager=VideoAgentManager(app)
    try:
        response=manager.execute(state['id'],{'kind':'inspect_code','repo':'main','path':found['path'],'line':found['line']},'read',semantic_fingerprint(state))
        assert response['content'].startswith('def exact_function():') and '정확한 본문' in response['content']
        assert response['offset']==found['offset'] and response['base_sha256']==found['base_sha256']
        for invalid in [1.5,True,0,-1,99999]:
            with pytest.raises(ValueError,match='line number'):
                manager.execute(state['id'],{'kind':'inspect_code','repo':'main','path':found['path'],'line':invalid},'read-bad',semantic_fingerprint(state))
    finally:manager.pool.shutdown(wait=True)
