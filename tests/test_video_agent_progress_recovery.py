"""Regression for production queue churn and reviewed-repair input races."""
import copy
import json
import pytest
from types import SimpleNamespace

from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.video_agents import VideoAgentManager, get_agent
from hotpost.video_agent_context import semantic_fingerprint, queue_progress_fingerprint, recovery_target, job_method_fingerprint
from hotpost.video_agent_actions import execute


class Writer:
    def __init__(self): self.payloads=[]
    def create(self,kind,payload,key):
        self.payloads.append(copy.deepcopy(payload));return {'id':'model'}
    def start(self): pass
    def get(self,*args,**kwargs): return {'state':'queued'}


def test_replacement_jobs_and_running_transitions_do_not_reset_progress(tmp_path,monkeypatch):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('churn','Churn',{'protocol':2,'active':True},prepare=False)
    task=state['id'];clock=[1000]
    monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    manager=VideoAgentManager(studio);manager.jobs=Writer()
    studio.store.video_agents=manager;manager.ready.set();manager.pulse=1000
    try:
        for i in range(11):
            with studio.store.transaction() as db:
                db.execute("update jobs set status='done' where task_id=?",(task,))
                jid=studio.store.enqueue(db,task,'collect_sources',{'round':i},'round-'+str(i))
                db.execute('update jobs set checkpoint=? where id=?',(json.dumps({'auto_retries':i,'_claim_token':str(i),'not_before':clock[0]}),jid))
                st=studio.store.get(task,db)
                st['source_acquisition']={'round':i,'rounds':[{'job_id':jid}]*i,'no_progress_rounds':i,'execution_seconds':i*30}
                st['sources']=[{'id':'preserved-source','sha256':'same','editing_eligible':False,
                    'review_outcome':{'stage':'overlay','status':'unconfirmed','reason':'outside bound interval','source_sha256':'same','checked_at':clock[0]},
                    'review_error_history':[{'stage':'overlay','error':'outside bound interval','source_sha256':'same','resolved_at':1000+j*30} for j in range(i+1)]}]
                studio.store.save(db,st)
            manager.pulse=clock[0];manager.step(task)
            if i<10:assert not manager.jobs.payloads
            clock[0]+=30
        owner=get_agent(studio.store,task)
        assert owner['queue_observation']['since']==1000
        assert owner['recovery_job_id']==jid
        assert len(manager.jobs.payloads)==1
        assert studio.store.claim(task_id=task) is None
        assert len(studio.store.get(task)['sources'][0]['review_error_history'])==11
        # An externally superseded queued job cannot leave a dead reservation.
        with studio.store.transaction() as db:
            db.execute("update jobs set status='done' where id=?",(jid,))
            replacement=studio.store.enqueue(db,task,'collect_sources',{},'replacement')
            db.execute('update jobs set checkpoint=? where id=?',(json.dumps({'auto_retries':999}),replacement))
        manager.step(task)
        assert get_agent(studio.store,task)['queue_observation']['since']==1000
        assert get_agent(studio.store,task)['recovery_job_id']==replacement
        assert studio.store.claim(task_id=task) is None
        # A different video remains queued until the current video's final QA.
        other,_=studio.store.create('other','Other',{'active':True})
        manager.pulse=clock[0]
        assert studio.store.claim(task_id=other['id']) is None
        studio.store.change(task,lambda st,db:st['source_acquisition'].update(no_progress_rounds=0))
        manager.step(task)
        assert not get_agent(studio.store,task).get('recovery_job_id')
    finally:manager.pool.shutdown(wait=True)


def test_progress_watch_excludes_status_churn_and_reserves_only_stalled_lane():
    state={'id':'task','automation':{'active':True},'status':'preparing','error':'',
           'source_acquisition':{'no_progress_rounds':133},'sources':[{'sha256':'same'}]}
    rows=[{'id':'a-normal','kind':'voice','status':'queued','checkpoint':'{}'},
          {'id':'z-stalled','kind':'collect_sources','status':'queued','checkpoint':'{}'}]
    first=queue_progress_fingerprint(state,rows)
    state.update(status='retry_wait',error='another worker attempt')
    assert queue_progress_fingerprint(state,rows)==first
    assert recovery_target(state,rows)=='z-stalled'
    state['source_acquisition']['waiting']={'searches':[{'status':'login_required'}]}
    assert recovery_target(state,rows) is None


@pytest.mark.parametrize('change',['status','source_sha256','scope','reason','new_error','access'])
def test_review_watch_retains_actual_evidence_and_access_changes(change):
    state={'id':'task','automation':{'active':True},'sources':[{'sha256':'same',
        'review_outcome':{'status':'unconfirmed','source_sha256':'same','scope':{'start':1},'reason':'bad frame','checked_at':1},
        'review_error_history':[{'stage':'overlay','error':'bad frame','resolved_at':1}]}],
        'source_acquisition':{'no_progress_rounds':3}}
    row={'id':'job','kind':'collect_sources','payload':{},'checkpoint':{},'status':'queued'}
    before=copy.deepcopy(state);signature=queue_progress_fingerprint(state,[row]);exact=semantic_fingerprint(state)
    state['sources'][0]['review_outcome']['checked_at']=2
    state['sources'][0]['review_error_history'].append({'stage':'overlay','error':'bad frame','resolved_at':2})
    assert queue_progress_fingerprint(state,[row])==signature
    assert semantic_fingerprint(state)!=exact  # Repair/input binding still retains the exact record.
    if change=='new_error':state['sources'][0]['review_error_history'].append({'error':'different defect'})
    elif change=='access':state['source_acquisition']['waiting']={'searches':[{'status':'login_required'}]}
    else:state['sources'][0]['review_outcome'][change]={'new':'evidence'} if change=='scope' else 'changed'
    assert queue_progress_fingerprint(state,[row])!=signature
    assert before['sources'][0]['review_outcome']['checked_at']==1


def test_changed_search_method_gets_new_observation(tmp_path,monkeypatch):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('methods','Methods',{'active':True},prepare=False)
    task=state['id'];clock=[1000];manager=VideoAgentManager(studio);manager.jobs=Writer()
    monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    studio.store.change(task,lambda st,db:st.update(source_acquisition={'no_progress_rounds':5}))
    try:
        with studio.store.transaction() as db:
            jid=studio.store.enqueue(db,task,'collect_sources',{'search':'old'},'old')
        manager.step(task)
        # Independent queue churn does not reset the stalled source method.
        for i in range(1,4):
            clock[0]+=90
            with studio.store.transaction() as db:
                db.execute("update jobs set status='done' where kind='voice'")
                studio.store.enqueue(db,task,'voice',{'variant':i},str(i))
            manager.step(task)
            assert get_agent(studio.store,task)['queue_observation']['since']==1000
            studio.store.change(task,lambda st,db:st.setdefault('voices',[]).append({'id':'unselected-'+str(i),'sha256':str(i)}))
        with studio.store.transaction() as db:db.execute("update jobs set status='done' where id=?",(jid,))
        manager.step(task)  # Only the independent voice lane is observable.
        with studio.store.transaction() as db:db.execute("update jobs set status='queued' where id=?",(jid,))
        manager.step(task)
        assert get_agent(studio.store,task)['queue_observation']['since']==1000
        clock[0]=1400
        with studio.store.transaction() as db:db.execute('update jobs set payload=? where id=?',(json.dumps({'search':'new'}),jid))
        manager.step(task)
        assert get_agent(studio.store,task)['queue_observation']['since']==1400
        assert not manager.jobs.payloads
        clock[0]=1410
        with studio.store.transaction() as db:db.execute('update jobs set payload=? where id=?',(json.dumps({'search':'old'}),jid))
        manager.step(task)
        assert get_agent(studio.store,task)['queue_observation']['since']==1000
    finally:manager.pool.shutdown(wait=True)


def test_queued_source_is_diagnosed_while_other_lane_runs(tmp_path,monkeypatch):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('parallel','Parallel',{'active':True},prepare=False)
    task=state['id'];clock=[1000];manager=VideoAgentManager(studio);manager.jobs=Writer()
    monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    studio.store.change(task,lambda st,db:st.update(source_acquisition={'no_progress_rounds':5}))
    try:
        with studio.store.transaction() as db:
            jid=studio.store.enqueue(db,task,'collect_sources',{},'source')
            voice=studio.store.enqueue(db,task,'voice',{},'voice')
            db.execute("update jobs set status='running' where id=?",(voice,))
        manager.step(task);clock[0]=1301;manager.step(task)
        assert get_agent(studio.store,task)['recovery_job_id']==jid
        assert len(manager.jobs.payloads)==1
        with studio.store.connect() as db:assert db.execute('select status from jobs where id=?',(voice,)).fetchone()[0]=='running'
    finally:manager.pool.shutdown(wait=True)


@pytest.mark.parametrize('hold',[{'daily_quality':{'pending':'exhausted'}},
    {'daily_quality':{'pending':'scene_wait'}},{'daily_quality':{'narration_context_hold':True}},
    {'editorial_content_hold':{'reason':'review'}},{'automation':{'active':True,'paused_by_user':True}}])
def test_unavailable_repair_gate_never_reserves_worker(hold):
    state={'id':'task','automation':{'active':True},**hold}
    rows=[{'id':'job','kind':'collect_sources','status':'queued','checkpoint':json.dumps({'internal_evidence_wait':True})}]
    assert recovery_target(state,rows) is None


def test_neighbour_internal_error_cannot_shorten_normal_method_grace(tmp_path,monkeypatch):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('grace','Grace',{'active':True},prepare=False)
    task=state['id'];clock=[1000];manager=VideoAgentManager(studio);manager.jobs=Writer()
    monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    studio.store.change(task,lambda st,db:st.update(source_acquisition={'no_progress_rounds':2}))
    try:
        with studio.store.transaction() as db:
            normal=studio.store.enqueue(db,task,'collect_sources',{},'normal')
            error=studio.store.enqueue(db,task,'voice',{},'error')
            # Deterministically focus the normal, lexically first source job.
            db.execute("update jobs set id='a-normal' where id=?",(normal,))
            db.execute("update jobs set id='z-error',checkpoint=? where id=?",(json.dumps({'internal_evidence_wait':True}),error))
        manager.step(task);clock[0]=1031;manager.step(task)
        manager.step(task)
        assert get_agent(studio.store,task).get('recovery_job_id')=='z-error'
        assert len(manager.jobs.payloads)==1
    finally:manager.pool.shutdown(wait=True)


def test_worker_bookkeeping_does_not_change_input_but_real_changes_do():
    s={'id':'task','automation':{'active':True},'source_search':{'status':'running'},
       'source_acquisition':{'round':1,'no_progress_rounds':1,'receipt_wait':{'at':1,'status':'receipt_wait'}},
       'sources':[{'id':'source','sha256':'original'}],'script_id':'script','run_id':'run'}
    baseline=semantic_fingerprint(s)
    new=copy.deepcopy(s);new['source_search']={'status':'queued','error':'retry'}
    new.update(status='retry_wait',error='worker display error')
    new['automation']['stage']='voice'
    new['source_acquisition'].update(round=150,no_progress_rounds=149,execution_seconds=4000,rounds=[{'job_id':'new'}])
    new['source_acquisition']['receipt_wait']['at']=900
    assert semantic_fingerprint(new)==baseline
    for key,value in [('sources',[{'id':'source','sha256':'changed'}]),('script_id','new'),('run_id','new'),('automation',{'active':False})]:
        changed=copy.deepcopy(new);changed[key]=value
        assert semantic_fingerprint(changed)!=baseline
    changed=copy.deepcopy(new);changed['source_acquisition']['hold']={'reason':'captcha'}
    assert semantic_fingerprint(changed)!=baseline


@pytest.mark.parametrize('blocked',[None,'external_receipt','captcha','job_access','input_changed','job_changed','user_pause'])
def test_real_repair_parking_survives_retry_bookkeeping_transaction(tmp_path,blocked):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('repair-race','Repair',{'protocol':2,'active':True},prepare=False)
    task=state['id']
    studio.store.change(task,lambda st,db:st.update(source_acquisition={'receipt_wait':{'at':1,'status':'receipt_wait'}}))
    state=studio.store.get(task);fingerprint=semantic_fingerprint(state)
    with studio.store.transaction() as db:
        jid=studio.store.enqueue(db,task,'collect_sources',{},'stalled')
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps({'video_agent_input_fingerprint':fingerprint,'internal_evidence_wait':True}),jid))
    receipt={'repair_id':'reviewed','binding':{'task_id':task,'job_id':jid,'input_fingerprint':fingerprint,'agent_epoch':1},'files':[]}
    with studio.store.transaction() as db:
        row=db.execute('select kind,payload,checkpoint from jobs where id=?',(jid,)).fetchone()
        signature=job_method_fingerprint(row);cp=json.loads(row['checkpoint']);cp['video_agent_job_fingerprint']=signature
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),jid))
        receipt['binding']['job_fingerprint']=signature
    studio.video_repair_pipeline=SimpleNamespace(ready_to_apply=lambda repair:receipt)
    studio.store.change(task,lambda st,db:st['source_acquisition']['receipt_wait'].update(at=9999))
    studio.store.change(task,lambda st,db:st.update(status='retry_wait',error='new worker error display'))
    if blocked=='external_receipt':
        with studio.store.transaction() as db:
            db.execute('update jobs set checkpoint=? where id=?',(json.dumps({'video_agent_input_fingerprint':fingerprint}),jid))
    elif blocked=='captcha':
        studio.store.change(task,lambda st,db:st['source_acquisition'].update(waiting={'searches':[{'status':'captcha'}]}))
        fingerprint=semantic_fingerprint(studio.store.get(task))
    elif blocked=='input_changed':studio.store.change(task,lambda st,db:st.update(script_id='new-script'))
    elif blocked=='job_access':
        with studio.store.transaction() as db:
            cp=json.loads(db.execute('select checkpoint from jobs where id=?',(jid,)).fetchone()[0])
            cp['failure_classification']={'category':'access_blocked'}
            db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),jid))
    elif blocked=='job_changed':
        with studio.store.transaction() as db:db.execute('update jobs set payload=? where id=?',(json.dumps({'search':'different-method'}),jid))
    elif blocked=='user_pause':studio.store.change(task,lambda st,db:st['automation'].update(paused_by_user=True))
    result=execute(studio,task,{'kind':'park_for_repair','job_id':jid,'repair_id':'reviewed','_agent_epoch':1,'hypothesis':'Apply signed repair','evidence':[]},'park',fingerprint)
    if blocked:
        assert result['status']=='held'
        assert studio.store.jobs(task)[0]['status']=='queued'
        return
    assert result['parked'] is True
    assert studio.store.jobs(task)[0]['status']=='paused'


def test_old_reserved_job_is_present_in_owner_evidence(tmp_path):
    from hotpost.video_agent_context import snapshot
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('old-job','Old job',{'active':True},prepare=False)
    task=state['id'];manager=VideoAgentManager(studio)
    try:
        with studio.store.transaction() as db:
            target=studio.store.enqueue(db,task,'collect_sources',{'search':'exact-target'},'old')
            for i in range(15):
                jid=studio.store.enqueue(db,task,'voice',{},str(i))
                db.execute("update jobs set status='done' where id=?",(jid,))
        manager._save(task,1,{'recovery_job_id':target})
        evidence=snapshot(studio,task)
        assert evidence['recovery_job_id']==target
        row=next(r for r in evidence['jobs'] if r['id']==target)
        assert row['payload']=={'search':'exact-target'} and row['status']=='queued'
    finally:manager.pool.shutdown(wait=True)


@pytest.mark.parametrize('mode',['service','unknown_cooldown','internal','collection_pacing'])
def test_cooldown_is_distinguished_from_internal_retry_and_collection_pacing(monkeypatch,mode):
    monkeypatch.setattr('hotpost.video_agent_context.time.time',lambda:1000)
    state={'id':'t','automation':{'active':True},'source_acquisition':{'no_progress_rounds':100}}
    checkpoint={'not_before':2000}
    if mode=='service':checkpoint['deferred_wait']=True
    if mode=='internal':checkpoint['internal_evidence_wait']=True
    if mode=='collection_pacing':state['source_acquisition']['next_attempt_at']=2000
    rows=[{'id':'j','kind':'collect_sources','status':'queued','checkpoint':json.dumps(checkpoint)}]
    assert bool(recovery_target(state,rows))==(mode in {'internal','collection_pacing'})


def test_old_due_method_is_not_starved_by_new_lexically_earlier_method(monkeypatch):
    monkeypatch.setattr('hotpost.video_agent_context.time.time',lambda:2000)
    state={'id':'t','automation':{'active':True},'source_acquisition':{'no_progress_rounds':100}}
    rows=[{'id':i,'kind':'collect_sources','status':'queued','checkpoint':'{}'} for i in ['a-new','z-old']]
    assert recovery_target(state,rows,{'a-new':1999,'z-old':1000})=='z-old'


def test_source_updates_do_not_reset_voice_method_observation():
    state={'id':'t','automation':{'active':True},'script_id':'s','scripts':[{'id':'s','text':'narration'}],
           'sources':[],'source_acquisition':{'queries':[]}}
    row={'kind':'voice','checkpoint':'{}','payload':json.dumps({'script_id':'s'})}
    baseline=queue_progress_fingerprint(state,[row])
    state['sources'].append({'id':'new-source','sha256':'real-new-source'})
    state['source_acquisition']['queries'].append({'query':'new-search','status':'results'})
    assert queue_progress_fingerprint(state,[row])==baseline
    state['scripts'][0]['text']='new selected narration'
    assert queue_progress_fingerprint(state,[row])!=baseline


def test_edit_method_observes_real_source_and_review_changes():
    state={'id':'t','automation':{'active':True},'sources':[{'id':'s','sha256':'old'}],'daily_quality':{}}
    row={'kind':'quality_reedit','checkpoint':'{}','payload':'{}'}
    baseline=queue_progress_fingerprint(state,[row])
    state['sources'][0]['sha256']='new'
    changed=queue_progress_fingerprint(state,[row]);assert changed!=baseline
    state['daily_quality']={'reviews':[{'sha256':'actual-review','issues':['visible-logo']}]}
    assert queue_progress_fingerprint(state,[row])!=changed


@pytest.mark.parametrize('kind',['collect_sources','voice','edit'])
@pytest.mark.parametrize('collection,field',[('scripts','script_id'),('voices','voice_id')])
def test_approved_asset_changes_reset_method_even_when_selection_differs(kind,collection,field):
    state={'id':'t','automation':{'active':True},field:'selected','approved_'+field:'approved',
           collection:[{'id':'selected','sha256':'a'},{'id':'approved','sha256':'b'}]}
    row={'kind':kind,'checkpoint':'{}','payload':'{}'}
    before=queue_progress_fingerprint(state,[row])
    state[collection][1]['sha256']='changed-approved-bytes'
    assert queue_progress_fingerprint(state,[row])!=before


def test_proposal_cannot_bind_changed_job_payload_to_old_decision(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('proposal','Proposal',{'active':True},prepare=False)
    task=state['id'];manager=VideoAgentManager(studio)
    studio.video_repair_pipeline=SimpleNamespace(propose_patch=lambda p:pytest.fail('Stale proposal reached staging'))
    try:
        with studio.store.transaction() as db:
            jid=studio.store.enqueue(db,task,'collect_sources',{'search':'old'},'method')
            db.execute("update jobs set status='failed' where id=?",(jid,))
            row=db.execute('select kind,payload,checkpoint from jobs where id=?',(jid,)).fetchone()
            signature=job_method_fingerprint(row)
            db.execute('update jobs set payload=? where id=?',(json.dumps({'search':'changed'}),jid))
        with pytest.raises(ValueError,match='method changed'):
            manager.execute(task,{'kind':'propose_patch','_agent_epoch':1,'_expected_job_signature':signature,
                'patch':{'binding':{'job_id':jid}}},'decision',semantic_fingerprint(state))
    finally:manager.pool.shutdown(wait=True)


def test_pending_diagnosis_is_consumed_despite_unselected_voice_churn(tmp_path,monkeypatch):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('pending-churn','Pending',{'active':True},prepare=False)
    task=state['id'];manager=VideoAgentManager(studio);manager.jobs=Writer();clock=[1000];executed=[]
    monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    manager.jobs.get=lambda *a,**kw:{'state':'completed','result':{'value':{'action':{'kind':'inspect_code','repo':'main','path':'hotpost/studio_sources.py'}}}}
    monkeypatch.setattr(manager,'execute',lambda *a:executed.append(a) or {'status':'completed'})
    try:
        with studio.store.transaction() as db:studio.store.enqueue(db,task,'collect_sources',{},'stalled')
        studio.store.change(task,lambda st,db:st.update(source_acquisition={'no_progress_rounds':8}))
        manager.step(task);clock[0]=1301;manager.step(task)
        assert get_agent(studio.store,task)['pending']
        studio.store.change(task,lambda st,db:st['voices'].extend([{'id':'unused1','sha256':'a'},{'id':'unused2','sha256':'b'}]))
        manager.step(task)
        assert len(executed)==1 and get_agent(studio.store,task)['last_action']=='inspect_code'
    finally:manager.pool.shutdown(wait=True)


def test_same_kind_neighbour_does_not_erase_absent_method_history(tmp_path,monkeypatch):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('same-lane','Same lane',{'active':True},prepare=False)
    task=state['id'];manager=VideoAgentManager(studio);manager.jobs=Writer();clock=[1000]
    monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    try:
        with studio.store.transaction() as db:
            a=studio.store.enqueue(db,task,'collect_sources',{'method':'A'},'A')
            studio.store.enqueue(db,task,'collect_sources',{'method':'B'},'B')
            row=db.execute('select * from jobs where id=?',(a,)).fetchone()
            signature=queue_progress_fingerprint(studio.store.get(task,db),[row])
        manager.step(task);clock[0]=1100
        with studio.store.transaction() as db:db.execute("update jobs set status='done' where id=?",(a,))
        manager.step(task)
        assert get_agent(studio.store,task)['queue_observations'][signature]['since']==1000
        with studio.store.transaction() as db:studio.store.enqueue(db,task,'collect_sources',{'method':'A'},'A-replacement')
        clock[0]=1200;manager.step(task)
        assert get_agent(studio.store,task)['queue_observations'][signature]['since']==1000
    finally:manager.pool.shutdown(wait=True)


@pytest.mark.parametrize('damage',[None,'old_observation','blocked_route','access_error','wrong_run','no_observation','generic_validation','no_trace',
    'missing_time','null_time','string_time','bool_time','nan_time','bad_wait_time'])
def test_internal_route_repair_never_releases_blocked_platform(damage):
    from hotpost.video_agent_actions import repair_has_available_route
    state={'id':'t','run_id':'run','automation':{'active':True},'source_acquisition':{'waiting':{'at':10,'searches':[{'provider':'youtube','status':'login_required'}]}}}
    cp={'failure_classification':{'category':'input_validation'},'source_access_preflight':{'ready_routes':['tiktok'],
        'observations':[{'provider':'tiktok','status':'ready','reason':'current_existing_page_observed','observed_at':20}]}}
    row={'kind':'collect_sources','payload':{'run_id':'run'},'checkpoint':cp}
    cp['failure_classification']['signature_material']={'exception_type':'hotpost.source_visual_queries.VisualQueryRejection','stage':'collect_sources'}
    cp['failure_trace']={'type':'VisualQueryRejection','stage':'collect_sources','frames':[{'function':'cached_visual_queries'}]}
    if damage=='old_observation':cp['source_access_preflight']['observations'][0]['observed_at']=5
    if damage=='blocked_route':state['source_acquisition']['waiting']['searches'].append({'provider':'tiktok','status':'captcha'})
    if damage=='access_error':cp['failure_classification']['category']='access_blocked'
    if damage=='wrong_run':row['payload']['run_id']='other'
    if damage=='no_observation':cp['source_access_preflight']['observations']=[]
    if damage=='generic_validation':cp['failure_classification']['signature_material']['exception_type']='ValueError'
    if damage=='no_trace':cp.pop('failure_trace')
    if damage in {'missing_time','null_time','string_time','bool_time','nan_time'}:
        state['source_acquisition']['waiting']['at']=0
        observation=cp['source_access_preflight']['observations'][0]
        observation.pop('observed_at')
        if damage!='missing_time':observation['observed_at']={'null_time':None,'string_time':'20','bool_time':True,'nan_time':float('nan')}[damage]
    if damage=='bad_wait_time':state['source_acquisition']['waiting']['at']=float('inf')
    before=copy.deepcopy(state)
    assert repair_has_available_route(state,row)==(damage is None)
    assert state==before


def test_running_queue_is_observed_but_not_claimed_by_recovery(tmp_path,monkeypatch):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('running','Running',{'active':True})
    task=state['id'];job=studio.store.claim(task_id=task)
    manager=VideoAgentManager(studio);manager.jobs=Writer();clock=[1000]
    monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    try:
        manager.step(task);clock[0]=2000;manager.step(task)
        assert get_agent(studio.store,task)['queue_observation']['since']==1000
        assert not get_agent(studio.store,task).get('recovery_job_id')
        assert studio.store.jobs(task)[0]['status']=='running'
        assert not manager.jobs.payloads
    finally:manager.pool.shutdown(wait=True)


@pytest.mark.parametrize('blocked',[None,'access','old_preflight','external_receipt'])
def test_available_internal_route_enters_repair_execution_without_clearing_access_wait(tmp_path,blocked):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('route-executor','Route',{'active':True},prepare=False)
    waiting={'at':10,'searches':[{'provider':'youtube','status':'login_required'}]}
    def setup(s,db):
        s.update(run_id='run',source_acquisition={'waiting':waiting})
        if blocked=='external_receipt':s['source_acquisition']['receipt_wait']={'reason':'pending approval'}
        cp={'failure_classification':{'category':'input_validation','signature_material':{'exception_type':'hotpost.source_visual_queries.VisualQueryRejection','stage':'collect_sources'}},'failure_trace':{'type':'VisualQueryRejection','stage':'collect_sources','frames':[{'function':'cached_visual_queries'}]},'source_access_preflight':{'ready_routes':['tiktok'],'observations':[{'provider':'tiktok','status':'ready','reason':'current_existing_page_observed','observed_at':20}]}}
        if blocked=='access':cp['failure_classification']['category']='access_blocked'
        if blocked=='old_preflight':cp['source_access_preflight']['observations'][0]['observed_at']=5
        job=studio.store.enqueue(db,s['id'],'collect_sources',{'run_id':'run'},'source')
        db.execute("update jobs set status='failed',checkpoint=? where id=?",(json.dumps(cp),job))
    studio.store.change(state['id'],setup)
    before=studio.store.get(state['id'])
    studio.video_repair_pipeline=SimpleNamespace(roots={'main':tmp_path},inspect_code=lambda *a:{'content':'def cause(): return None','base_sha256':'current'})
    manager=VideoAgentManager(studio);manager.jobs=Writer()
    try:
        manager._save(state['id'],1,{'idle_decisions':20,'recovery_mode':True})
        manager.step(state['id'])
        evidence=manager.jobs.payloads[0]['evidence']
        assert bool(evidence.get('allowed_actions'))==(blocked is None)
        assert studio.store.get(state['id'])==before
    finally:manager.pool.shutdown(wait=True)
