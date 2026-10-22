import copy
import hashlib
import io
import json
import pytest
from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.video_agents import VideoAgentManager,get_agent
from hotpost.video_agent_context import semantic_fingerprint
from hotpost.video_agent_actions import execute
from hotpost.video_agent_recovery import OVERLAY_FAILURE,retained_candidates
from hotpost.video_agent_memory import history,recall


def app(tmp_path):return Studio(Settings(data_dir=tmp_path),workers=False)


def stage_observation(kind,repair='r1',*,job='job',fingerprint='input',epoch=1,status=None,**result):
    action={'kind':kind,'_agent_epoch':epoch}
    if kind=='propose_patch':action['patch']={'binding':{'job_id':job}}
    else:action['repair_id']=repair
    return {'fingerprint':fingerprint,'action':action,'result':{
        'status':status or ('tests_passed' if kind=='test_patch' else 'completed'),
        'repair_id':repair,**result}}


def test_partial_drafts_and_repeated_test_cycles_do_not_reset_recovery_stage():
    from hotpost.video_agent_memory import repair_stage_progress
    rows=[stage_observation('propose_patch'),stage_observation('test_patch')]
    for i in range(20):
        rows.extend([stage_observation('inspect_code'),stage_observation('propose_patch',f'r{i+2}',code_changed=True),
                     stage_observation('test_patch',f'r{i+2}')])
    track=repair_stage_progress(rows)[0]
    assert track['phase']==2 and track['stagnant_decisions']==60
    rows.append(stage_observation('review_patch','r21',review_id='signed-review'))
    assert repair_stage_progress(rows)[0]['stagnant_decisions']==0
    rows.append(stage_observation('review_patch','r21',status='error'))
    assert repair_stage_progress(rows)[0]['stagnant_decisions']==1
    rows.append(stage_observation('apply_patch','r21',status='loaded'))
    assert repair_stage_progress(rows)[0]['phase']==4
    rows.append(stage_observation('continue_repaired','r21',status='queued'))
    assert repair_stage_progress(rows)[0]['phase']==5
    # New task input, owner epoch and repair target remain independent.
    for index,kw in enumerate([{'fingerprint':'new-input'},{'epoch':2},{'job':'other-job'}]):
        rows.append(stage_observation('propose_patch',f'new{index}',**kw))
    tracks=repair_stage_progress(rows)
    assert len(tracks)==4 and all(row['phase']==1 and row['stagnant_decisions']==0 for row in tracks[1:])


def test_malformed_old_decisions_cannot_break_stage_history():
    from hotpost.video_agent_memory import repair_stage_progress
    malformed=[{'action':None},{'action':{'kind':[]}},
        {'action':{'kind':'test_patch','repair_id':[]},'result':{'status':'error'}},
        {'action':{'kind':'propose_patch','patch':[]},'result':{'status':'completed','repair_id':'bad'}}]
    assert repair_stage_progress(malformed)==[]


def test_verified_dependency_wait_does_not_inflate_stage_stall_after_recovery():
    from hotpost.video_agent_memory import repair_stage_progress
    rows=[stage_observation('propose_patch'),stage_observation('test_patch')]
    for _ in range(20):
        waiting=stage_observation('wait',status='waiting');waiting['dependency_wait']=True
        rows.append(waiting)
    rows.append(stage_observation('apply_patch',status='waiting',retry_same_decision=True))
    rows.append(stage_observation('inspect_code'))
    assert repair_stage_progress(rows)[0]['stagnant_decisions']==1
    rows.append(stage_observation('wait',status='waiting'))  # No host evidence.
    assert repair_stage_progress(rows)[0]['stagnant_decisions']==2


@pytest.mark.parametrize('kind,invalid_id',[('test_patch',[]),('propose_patch',['bad'])])
def test_invalid_repair_id_in_saved_history_does_not_stop_next_plan(tmp_path,kind,invalid_id):
    from types import SimpleNamespace
    s=app(tmp_path);state,job=preparation(s,tmp_path);m=VideoAgentManager(s)
    s.video_repair_pipeline=SimpleNamespace(
        repair_material=lambda *a:pytest.fail('Malformed ID must not reach pipeline'),
        inspect_code=lambda repo,path:{'content':'# retained exact code','base_sha256':'hash'},roots={})
    m._save(state['id'],1,{'idle_decisions':16}, {'fingerprint':semantic_fingerprint(state),
        'action':{'kind':kind,'repair_id':invalid_id,'_agent_epoch':1,'patch':{'binding':{'job_id':job['id']}}},
        'result':{'status':'error'}},'malformed-saved')
    m.pool.shutdown(wait=True)
    m=VideoAgentManager(s);m.jobs=Writer([])
    try:
        m.step(state['id'])
        assert len(m.jobs.payloads)==1 and get_agent(s.store,state['id'])['pending']
        assert m.jobs.payloads[0]['evidence']['repair_packet']
        assert all(row.get('source')!='staged_repair' for row in m.jobs.payloads[0]['evidence']['repair_packet'])
    finally:m.pool.shutdown(wait=True)


@pytest.mark.parametrize('kind',['propose_patch','test_patch'])
def test_less_stalled_target_cannot_renew_shared_repair_read_budget(tmp_path,monkeypatch,kind):
    s=app(tmp_path);state,job=preparation(s,tmp_path);fp=semantic_fingerprint(state)
    with s.store.transaction() as db:
        other=s.store.enqueue(db,state['id'],'edit',{},'second-failed-target')
        db.execute("UPDATE jobs SET status='failed',error='second failure' WHERE id=?",(other,))
    m=VideoAgentManager(s);rows=[]
    for jid,rid,count in [(job['id'],'draft-a',30),(other,'draft-b',18)]:
        rows.extend([stage_observation('propose_patch',rid,job=jid,fingerprint=fp),
                     stage_observation('test_patch',rid,fingerprint=fp)])
        rows.extend(stage_observation('inspect_code',rid,fingerprint=fp) for _ in range(count))
    for i,row in enumerate(rows):m._save(state['id'],1,{},row,f'prior-{i}')
    m._save(state['id'],1,{'idle_decisions':0,'repair_evidence_used':['used-read']})
    action={'kind':kind,'repair_id':'draft-b','hypothesis':'Partial second target change'}
    if kind=='propose_patch':action['patch']={'binding':{'job_id':other}}
    m.jobs=Writer([action]);monkeypatch.setattr(m,'execute',lambda *a:{'status':
        'tests_passed' if kind=='test_patch' else 'completed','repair_id':'new-b','code_changed':True})
    try:
        m.step(state['id'])
        assert m.jobs.payloads[0]['evidence']['repair_stage_watch']['job_id']==job['id']
        m.step(state['id'])
        assert get_agent(s.store,state['id'])['repair_evidence_used']==['used-read']
        assert all(j['status']=='failed' for j in s.store.jobs(state['id']))
    finally:m.pool.shutdown(wait=True)


@pytest.mark.parametrize('current',[True,False])
def test_stage_watch_survives_partial_patch_idle_reset_and_restart(tmp_path,monkeypatch,current):
    s=app(tmp_path);state,job=preparation(s,tmp_path);fp=semantic_fingerprint(state)
    m=VideoAgentManager(s)
    rows=[stage_observation('propose_patch',job=job['id'],fingerprint=fp),
          stage_observation('test_patch',fingerprint=fp)]
    rows.extend(stage_observation('inspect_code',fingerprint=fp) for _ in range(18))
    rows.append(stage_observation('propose_patch','new-draft',job=job['id'],fingerprint=fp,code_changed=True))
    try:
        for i,row in enumerate(rows):
            if not current:row['action']['_agent_epoch']=0
            m._save(state['id'],1,{},row,f'past-{i}')
        m._save(state['id'],1,{'idle_decisions':0,'repair_evidence_used':['already-read']})
    finally:m.pool.shutdown(wait=True)
    m=VideoAgentManager(s)
    action={'kind':'propose_patch','patch':{'binding':{'job_id':job['id']}},'hypothesis':'Add another partial change'}
    m.jobs=Writer([action]);monkeypatch.setattr(m,'execute',lambda *a:{'status':'completed','repair_id':'next','code_changed':True})
    try:
        m.step(state['id'])
        evidence=m.jobs.payloads[0]['evidence']
        assert bool(evidence.get('allowed_actions')) is current
        if current:assert evidence['repair_stage_watch']['stagnant_decisions']==19
        m.step(state['id'])
        assert get_agent(s.store,state['id'])['repair_evidence_used']==(['already-read'] if current else [])
        assert s.store.jobs(state['id'])[0]['status']=='failed'
    finally:m.pool.shutdown(wait=True)


class Writer:
    def __init__(self,actions):self.actions=actions;self.payloads=[]
    def create(self,kind,payload,key):
        self.payloads.append(copy.deepcopy(payload));return {'id':str(len(self.payloads)-1)}
    def start(self):pass
    def get(self,identifier,**kwargs):return {'state':'completed','result':{'value':{'action':self.actions[int(identifier)]}}}


@pytest.mark.parametrize('changed',[False,True])
def test_identical_restage_does_not_buy_another_diagnosis_budget(tmp_path,monkeypatch,changed):
    s=app(tmp_path);state,_=s.store.create('restage','Restage',{'active':True},prepare=False)
    m=VideoAgentManager(s);m.jobs=Writer([{'kind':'propose_patch','hypothesis':'Retain exact draft on current dependencies.'}])
    clock=[1000];monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    monkeypatch.setattr(m,'execute',lambda *a:{'status':'completed','repair_id':'new-id','code_changed':changed})
    try:
        m._save(state['id'],1,{'idle_decisions':20,'repair_evidence_used':['six-already-used']})
        m.step(state['id']);clock[0]+=3;m.step(state['id'])
        owner=get_agent(s.store,state['id'])
        assert owner['idle_decisions']==(0 if changed else 21)
        assert owner['repair_evidence_used']==([] if changed else ['six-already-used'])
    finally:m.pool.shutdown(wait=True)


def test_replacement_parser_upgrade_reopens_failed_action_once(tmp_path,monkeypatch):
    from hotpost import video_agent_repairs as repairs
    s=app(tmp_path);state,_=s.store.create('eol-contract','EOL',{'active':True},prepare=False)
    action={'kind':'propose_patch','hypothesis':'Use exact saved context.',
        'patch':{'files':[{'replacements':[{'old':'a\nb','new':'a\nc'}]}]}}
    m=VideoAgentManager(s);m.jobs=Writer([action]*4);calls=[];clock=[1000]
    monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    monkeypatch.setattr(repairs,'SOURCE_REPLACEMENT_CONTRACT','legacy-exact-bytes')
    def execute(*args):
        calls.append(repairs.SOURCE_REPLACEMENT_CONTRACT)
        if repairs.SOURCE_REPLACEMENT_CONTRACT=='legacy-exact-bytes':raise ValueError('Each replacement must match exactly once.')
        assert repairs._replace_exact_source('a\r\nb','a\nb','a\nc')=='a\r\nc'
        return {'status':'completed','repair_id':'fresh','code_changed':True}
    monkeypatch.setattr(m,'execute',execute)
    def decision():
        for _ in range(2):m.step(state['id']);clock[0]+=1000
    try:
        decision();decision();assert len(calls)==1
        monkeypatch.setattr(repairs,'SOURCE_REPLACEMENT_CONTRACT','eol-equivalent-unique-v1')
        decision();assert len(calls)==2 and get_agent(s.store,state['id'])['last_result']['status']=='completed'
        decision();assert len(calls)==2
    finally:m.pool.shutdown(wait=True)


@pytest.mark.parametrize('only_new',[True,False])
def test_http_automatic_protocol_visible_to_worker_at_first_commit(tmp_path,only_new):
    from hotpost.studio_http import StudioHTTP
    from types import SimpleNamespace
    real=app(tmp_path);seen=[]
    def create(code,automation=None,with_created=False):
        s,new=real.store.create(code,'Sink',automation)
        claimed=real.store.claim(task_id=s['id'])
        seen.append(real.store.get(s['id'])['automation'])
        assert claimed and seen[-1]['protocol']==2 and seen[-1]['active']
        return (s,new)
    fake=SimpleNamespace(create=create,action=lambda *a:pytest.fail('New auto task must not need a second command'))
    body=json.dumps({'shortcodes':['sink'],'automatic':True,'only_new':only_new}).encode()
    handler=StudioHTTP();handler.path='/api/studio';handler.headers={'Content-Length':str(len(body))};handler.rfile=io.BytesIO(body)
    handler._json=lambda value,status:None
    assert handler.studio_post(fake) and len(seen)==1


def test_successful_read_can_be_repeated_after_history_eviction_and_restart(tmp_path,monkeypatch):
    s=app(tmp_path);state,_=s.store.create('memory','Memory',{'active':True},prepare=False)
    file=s.folder(state['id'])/'cause.json';file.write_text('{"cause":"keep this evidence"}')
    action={'kind':'inspect_artifact','path':str(file),'hypothesis':'Read exact evidence'}
    m=VideoAgentManager(s)
    for i in range(20):
        m._save(state['id'],1,{}, {'action':action if i==0 else {'kind':'inspect_code','path':str(i)},'result':{'status':'completed','content':str(i)}},str(i))
    assert history(s.store,state['id'])['memory_index'][0]['decision_id']=='0'
    assert 'cause.json' in recall(s.store,state['id'],{'decision_id':'0'})['content']
    writer=Writer([action,action]);m.jobs=writer
    clock=[1000];monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    try:
        for _ in range(4):m.step(state['id']);clock[0]+=1000
        assert get_agent(s.store,state['id'])['last_result']['status']=='completed'
        fresh=VideoAgentManager(s)
        try:assert history(fresh.store,state['id'])['total_decisions']==22
        finally:fresh.pool.shutdown(wait=True)
    finally:m.pool.shutdown(wait=True)


def test_old_frozen_owner_enters_independent_recovery(tmp_path):
    s=app(tmp_path);state,_=s.store.create('frozen','Frozen',{'active':True},prepare=False)
    m=VideoAgentManager(s);m.jobs=Writer([])
    try:
        m._save(state['id'],1,{'blocked_observation':semantic_fingerprint(state),'status':'attention'})
        m.step(state['id'])
        assert get_agent(s.store,state['id'])['status']=='recovering'
        assert 'independent recovery engineer' in m.jobs.payloads[0]['instruction']
    finally:m.pool.shutdown(wait=True)


@pytest.mark.parametrize('invalid',[None,[],['bad'],'bad',12,True,{}, {'kind':[]}, {'kind':{}}, {'kind':None}])
def test_invalid_action_records_incident_and_continues_recovery(tmp_path,monkeypatch,invalid):
    s=app(tmp_path);state,_=s.store.create('malformed','Malformed',{'active':True},prepare=False)
    m=VideoAgentManager(s);m.jobs=Writer([invalid]*6)
    clock=[1000];monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    try:
        for _ in range(12):m.step(state['id']);clock[0]+=1000
        owner=get_agent(s.store,state['id']);assert owner['recovery_mode']
        assert owner['invalid_decisions']==6 and not owner.get('blocked_observation')
    finally:m.pool.shutdown(wait=True)


def preparation(s,tmp_path):
    state,_=s.store.create('sink','Sink',{'protocol':2,'active':True})
    reference=tmp_path/'ref.mp4';reference.write_bytes(b'reference')
    transcript=tmp_path/'transcript.json';transcript.write_text('{}')
    s.store.change(state['id'],lambda st,db:st.update(reference_video=str(reference),transcript_path=str(transcript)))
    job=s.store.claim(task_id=state['id']);s.store.fail(job,ValueError(OVERLAY_FAILURE))
    from hotpost.studio_runtime.generation import LOADED_SOURCE_SHA256
    from hotpost.video_agent_recovery import PREPARATION_CONTRACT
    failed_job=s.store.jobs(state['id'])[0]
    receipt={'contract':PREPARATION_CONTRACT,'generation_sha256':LOADED_SOURCE_SHA256,'incidents':[{
        'task_id':state['id'],'job_id':job['id'],'failed_at':failed_job['updated'],'error':OVERLAY_FAILURE,
        'cause':'worker-claimed-before-automatic-protocol','reproduced':True,
        'evidence':[{'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (reference,transcript)]}]}
    (s.store.root/'preparation-recovery.json').write_text(json.dumps(receipt),'utf8')
    return s.store.get(state['id']),job


def recovery(s,state,job,decision='recover'):
    return execute(s,state['id'],{'kind':'recover_preparation','job_id':job['id'],'hypothesis':'Current automatic protocol replaces obsolete manual admission','_agent_epoch':1},decision,semantic_fingerprint(state))


def test_preparation_recovery_requeues_exact_job_preserving_incident(tmp_path):
    s=app(tmp_path);state,job=preparation(s,tmp_path)
    result=recovery(s,state,job)
    assert result['status']=='queued' and result['job_ids']==[job['id']]
    assert s.store.get(state['id'])['sources']==[]
    with s.store.connect() as db:cp=json.loads(db.execute('select checkpoint from jobs where id=?',(job['id'],)).fetchone()[0])
    assert cp['failure_trace']['message']==OVERLAY_FAILURE and cp['video_agent_recoveries'][0]['old_error']==OVERLAY_FAILURE
    # Same contract cannot buy another execution merely by issuing a new decision.
    with s.store.transaction() as db:db.execute("update jobs set status='failed',error=? where id=?",(OVERLAY_FAILURE,job['id']))
    assert recovery(s,s.store.get(state['id']),job,'again')['status']=='held'


@pytest.mark.parametrize('change',[{'automation':{'protocol':2,'active':True,'paused_by_user':True}},
    {'source_acquisition':{'hold':{'reason':'captcha'}}},
    {'source_acquisition':{'waiting':{'searches':[{'status':'login_required'}]}}},
    {'scripts':[{'id':'approved'}]}, {'voices':[{'id':'approved'}]}, {'edits':[{'id':'done'}]}])
def test_recovery_preserves_auth_user_and_narration_boundaries(tmp_path,change):
    s=app(tmp_path);state,job=preparation(s,tmp_path)
    s.store.change(state['id'],lambda st,db:st.update(change));state=s.store.get(state['id'])
    assert recovery(s,state,job)['status']=='held'
    assert s.store.jobs(state['id'])[0]['status']=='failed'


def test_retained_unreviewed_download_is_not_granted_editing_permission(tmp_path):
    from hotpost.source_quality import editing_ready
    s=app(tmp_path);root=s.settings.source_dir/'sink-123';root.mkdir(parents=True)
    clip=root/'source.mp4';clip.write_bytes(b'downloaded footage')
    manifest=root/'manifest.json';manifest.write_text(json.dumps({'candidates':[{'selected_for_zip':True,'downloaded_file':clip.name,
        'file_sha256':hashlib.sha256(clip.read_bytes()).hexdigest(),'source_quality':'edited-with-text','blur_required':True,'relevance_review_required':True}]}))
    state={'recovery_source_manifest_path':str(manifest),'recovery_source_manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}
    rows=retained_candidates(s,state)
    assert len(rows)==1 and not editing_ready(rows[0])
    clip.write_bytes(b'changed');assert retained_candidates(s,state)==[]
    manifest.write_text('{}')
    with pytest.raises(ValueError,match='changed'):retained_candidates(s,state)


def test_recall_cannot_cross_video_ownership(tmp_path):
    s=app(tmp_path);a,_=s.store.create('a','a',prepare=False);b,_=s.store.create('b','b',prepare=False)
    m=VideoAgentManager(s)
    try:
        m._save(a['id'],1,{}, {'secret':'other video'},'private')
        with pytest.raises(ValueError):recall(s.store,b['id'],{'decision_id':'private'})
    finally:m.pool.shutdown(wait=True)


def test_recall_search_discovers_old_versions_beyond_context_window(tmp_path):
    s=app(tmp_path);state,_=s.store.create('old-memory','History',prepare=False)
    m=VideoAgentManager(s)
    try:
        for i in range(170):
            m._save(state['id'],1,{}, {'action':{'kind':'inspect_code','path':'same.py'},'result':{'status':'completed','content':'revision '+str(i)}},str(i))
        page=recall(s.store,state['id'],{'query':'same.py','limit':10})
        assert page['entries'][0]['decision_id']=='0' and page['next_offset']==10
        assert 'revision 0' in recall(s.store,state['id'],{'decision_id':'0'})['content']
        assert recall(s.store,state['id'],{'query':'same.py','offset':160})['next_offset'] is None
    finally:m.pool.shutdown(wait=True)


def test_preparation_recovery_does_not_skip_service_cooldown(tmp_path):
    import time
    s=app(tmp_path);state,job=preparation(s,tmp_path);future=time.time()+300
    with s.store.transaction() as db:db.execute('update jobs set checkpoint=? where id=?',(json.dumps({'not_before':future}),job['id']))
    assert recovery(s,state,job)['status']=='held'
    with s.store.connect() as db:assert json.loads(db.execute('select checkpoint from jobs where id=?',(job['id'],)).fetchone()[0])['not_before']==future


def test_intake_accepts_review_required_bytes_but_final_editor_still_rejects(tmp_path):
    from hotpost.source_intake import downloaded_candidates
    from hotpost.editing_adapter import selected_source_videos
    file=tmp_path/'candidate.mp4';file.write_bytes(b'candidate')
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'candidates':[{'selected_for_zip':True,'downloaded_file':file.name,
        'file_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'source_quality':'edited-with-text','blur_required':True}]}))
    assert downloaded_candidates(manifest)==[file]
    with pytest.raises(ValueError,match='CapCut'):selected_source_videos(manifest)
    file.write_bytes(b'changed')
    with pytest.raises(ValueError,match='SHA'):downloaded_candidates(manifest)


def test_preparation_does_not_adopt_unbound_latest_manifest(tmp_path):
    s=app(tmp_path);state,job=preparation(s,tmp_path)
    for name in ['sink-1','sink-2']:
        p=s.settings.source_dir/name/'manifest.json';p.parent.mkdir(parents=True);p.write_text('{}')
    assert recovery(s,state,job)['status']=='queued'
    assert not s.store.get(state['id']).get('recovery_source_manifest_path')


def test_intake_rejects_out_of_job_paths(tmp_path):
    from hotpost.source_intake import downloaded_candidates
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps({'candidates':[{'selected_for_zip':True,'downloaded_file':'../other.mp4'}]}))
    with pytest.raises(ValueError,match='leaves'):downloaded_candidates(manifest)


@pytest.mark.parametrize('invalid',[None,'other_task','unsettled_worker','other_manifest'])
def test_recovery_import_requires_exact_settled_source_receipt(tmp_path,invalid):
    from hotpost.source_pause_receipts import binding
    s=app(tmp_path);state,job=preparation(s,tmp_path)
    manifest=s.settings.source_dir/'sink-123'/'manifest.json';manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({'shortcode':'sink','job_id':manifest.parent.name,'candidates':[]}))
    descriptor={**binding(state,job),'manifest_path':str(manifest),'workers':[]}
    if invalid=='other_task':descriptor['task_id']='another-owner'
    if invalid=='unsettled_worker':descriptor['workers']=[{'settled':False}]
    if invalid=='other_manifest':manifest.write_text(json.dumps({'shortcode':'other','job_id':manifest.parent.name}))
    with s.store.transaction() as db:
        cp=json.loads(db.execute('select checkpoint from jobs where id=?',(job['id'],)).fetchone()[0])
        cp['source_attempts']=[descriptor]
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),job['id']))
    assert recovery(s,state,job)['status']=='queued'
    updated=s.store.get(state['id'])
    assert bool(updated.get('recovery_source_manifest_path'))==(invalid is None)
    if invalid is None:assert updated['recovery_source_manifest_sha256']==hashlib.sha256(manifest.read_bytes()).hexdigest()


def test_repeated_wait_is_escalated_not_treated_as_production_progress(tmp_path,monkeypatch):
    s=app(tmp_path);state,_=s.store.create('waiting-loop','Wait',{'active':True},prepare=False)
    m=VideoAgentManager(s);m.jobs=Writer([{'kind':'wait','hypothesis':'service','reason':'service','seconds':30}]*9)
    clock=[1000];monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    try:
        for _ in range(18):m.step(state['id']);clock[0]+=1000
        assert get_agent(s.store,state['id'])['recovery_mode']
        assert 'independent recovery engineer' in m.jobs.payloads[8]['instruction']
    finally:m.pool.shutdown(wait=True)


@pytest.mark.parametrize('result',[[],['bad'],{'error_reason':'model_capacity','retry_at':'bad'},
    {'error_reason':'model_capacity','retry_at':float('nan')},{'error_reason':'model_capacity','retry_at':float('inf')}])
def test_failed_model_bad_receipt_releases_pending_for_recovery(tmp_path,result):
    s=app(tmp_path);state,_=s.store.create('bad-result','Bad result',{'active':True},prepare=False)
    m=VideoAgentManager(s);m.jobs=Writer([])
    m.jobs.get=lambda *args,**kw:{'state':'failed','result':result,'error':'invalid response'}
    try:
        m.step(state['id']);m.step(state['id'])
        owner=get_agent(s.store,state['id'])
        assert owner['pending'] is None and owner['recovery_mode']
    finally:m.pool.shutdown(wait=True)


def test_stale_future_cannot_poison_new_owner_after_user_command(tmp_path):
    from concurrent.futures import Future
    from hotpost.video_agents import enroll
    s=app(tmp_path);state,_=s.store.create('future-epoch','Epoch',{'active':True},prepare=False)
    m=VideoAgentManager(s);bad=Future();bad.set_exception(RuntimeError('old failure'))
    m.futures[state['id']]=bad;m.future_epochs[state['id']]=1
    with s.store.transaction() as db:
        state['automation']['active']=False
        enroll(db,state,'user_command',renew=True);enroll(db,state,'user_command')
    try:
        before=get_agent(s.store,state['id']);m.tick();after=get_agent(s.store,state['id'])
        assert after==before and not after.get('runtime_error')
    finally:m.pool.shutdown(wait=True)


@pytest.mark.parametrize('defect',['missing','code_sha','job_id','failed_at','evidence'])
def test_preparation_recovery_requires_tested_code_and_exact_incident(tmp_path,defect):
    s=app(tmp_path);state,job=preparation(s,tmp_path);p=s.store.root/'preparation-recovery.json'
    receipt=json.loads(p.read_text())
    if defect=='missing':p.unlink()
    else:
        if defect=='code_sha':receipt['generation_sha256']='wrong'
        else:receipt['incidents'][0][defect]='wrong'
        p.write_text(json.dumps(receipt))
    assert recovery(s,state,job)['status']=='held'


@pytest.mark.parametrize('error',[KeyError('missing'),RuntimeError('temporary storage failure')])
def test_missing_model_job_eventually_releases_pending(tmp_path,monkeypatch,error):
    s=app(tmp_path);state,_=s.store.create('missing-model','Missing',{'active':True},prepare=False)
    m=VideoAgentManager(s);m.jobs=Writer([]);clock=[1000]
    monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    def unavailable(*args,**kw):raise error
    m.jobs.get=unavailable
    try:
        m.step(state['id'])
        for _ in range(3):
            clock[0]+=1000;m.step(state['id'])
            if get_agent(s.store,state['id'])['pending'] is None:break
        assert get_agent(s.store,state['id'])['pending'] is None
        assert get_agent(s.store,state['id'])['recovery_mode']
    finally:m.pool.shutdown(wait=True)


def test_local_draft_syntax_rejection_corrects_without_production_backoff(tmp_path,monkeypatch):
    from hotpost.video_agent_runtime import configure
    s=app(tmp_path);state,job=preparation(s,tmp_path)
    m=VideoAgentManager(s);configure(s,m)
    draft={'kind':'propose_patch','patch':{'binding':{'job_id':job['id']},'reason':'Observed local draft syntax',
        'files':[{'repo':'main','path':'tests/test_local_syntax.py','base_sha256':None,'content':'def broken(:\n'}]},
        'hypothesis':'Correct a local staged syntax failure'}
    m.jobs=Writer([draft,draft]);clock=[1000];monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    try:
        m._save(state['id'],1,{'idle_decisions':40})
        m.step(state['id']);m.step(state['id'])
        owner=get_agent(s.store,state['id'])
        assert owner['last_result']['type']=='RepairRejected'
        assert owner['next_at']==1002 and owner['idle_decisions']==41 and owner['consecutive_failures']==1
        assert s.store.jobs(state['id'])[0]['status']=='failed'
        clock[0]=1002;m.step(state['id']);m.step(state['id'])
        owner=get_agent(s.store,state['id'])
        assert owner['last_result']['type']=='ValueError' and '같은 행동' in owner['last_result']['error']
        assert owner['next_at']==1302 and owner['idle_decisions']==42
    finally:m.pool.shutdown(wait=True)


@pytest.mark.parametrize('outcome',['tests_failed','tests_passed'])
def test_repair_test_result_does_not_enable_identical_test_loop(tmp_path,monkeypatch,outcome):
    s=app(tmp_path);state,job=preparation(s,tmp_path)
    action={'kind':'test_patch','repair_id':'immutable-draft','hypothesis':'Test preserved failure'}
    m=VideoAgentManager(s);m.jobs=Writer([action,action]);clock=[1000]
    monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    calls=[]
    def run_test(*args):
        calls.append(args)
        return {'status':outcome,'repair_id':'immutable-draft','tests':[{'passed':outcome=='tests_passed','log_path':'isolated.log'}]}
    monkeypatch.setattr(m,'execute',run_test)
    try:
        m._save(state['id'],1,{'idle_decisions':17,'recovery_mode':True,'repair_evidence_used':['earlier-read']})
        m.step(state['id']);m.step(state['id'])
        first=get_agent(s.store,state['id'])
        if outcome=='tests_failed':
            assert first['idle_decisions']==18 and first['recovery_mode']
            assert first['repair_evidence_used']==['earlier-read']
            assert first['consecutive_failures']==1 and first['next_at']==1002
        else:
            assert first['idle_decisions']==0
        clock[0]=first['next_at'];m.step(state['id']);m.step(state['id'])
        second=get_agent(s.store,state['id'])
        assert len(calls)==1 and '같은 행동' in second['last_result']['error']
        assert second['idle_decisions']==first['idle_decisions']+1
        assert s.store.jobs(state['id'])[0]['status']=='failed'
    finally:m.pool.shutdown(wait=True)


def test_repair_notes_survive_restart_without_resetting_idle_or_changing_method(tmp_path,monkeypatch):
    s=app(tmp_path);state,job=preparation(s,tmp_path)
    action={'kind':'test_patch','repair_id':'draft','hypothesis':'Test same failure'}
    clock=[1000];monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    m=VideoAgentManager(s);m.jobs=Writer([action])
    m.jobs.get=lambda *a,**kw:{'state':'completed','result':{'value':{'action':action,'working_notes':'Observed causal field; next fix exact staged regression.'}}}
    monkeypatch.setattr(m,'execute',lambda *a:{'status':'tests_failed'})
    try:
        m._save(state['id'],1,{'idle_decisions':17})
        m.step(state['id']);m.step(state['id'])
        owner=get_agent(s.store,state['id']);notes=owner['working_notes']
        assert owner['idle_decisions']==18
        assert notes['historical_evidence'] and notes['input_fingerprint']==semantic_fingerprint(s.store.get(state['id']))
    finally:m.pool.shutdown(wait=True)
    clock[0]=1002;other=VideoAgentManager(s);other.jobs=Writer([action])
    other.jobs.get=lambda *a,**kw:{'state':'completed','result':{'value':{'action':action,'working_notes':'Changed wording does not authorize the repeated method.'}}}
    monkeypatch.setattr(other,'execute',lambda *a:pytest.fail('Notes cannot bypass duplicate guard'))
    try:
        other.step(state['id'])
        assert other.jobs.payloads[0]['evidence']['working_notes']==notes
        other.step(state['id'])
        assert '같은 행동' in get_agent(s.store,state['id'])['last_result']['error']
        assert s.store.jobs(state['id'])[0]['status']=='failed'
        from hotpost.video_agents import enroll
        with s.store.transaction() as db:enroll(db,s.store.get(state['id'],db),'user_command',renew=True)
        assert get_agent(s.store,state['id'])['working_notes'] is None
    finally:other.pool.shutdown(wait=True)


@pytest.mark.parametrize('notes',[None,{},'x'*12001,'   '])
def test_invalid_repair_notes_do_not_replace_previous_memory(tmp_path,monkeypatch,notes):
    s=app(tmp_path);state,_=preparation(s,tmp_path)
    m=VideoAgentManager(s);m.jobs=Writer([])
    m.jobs.get=lambda *a,**kw:{'state':'completed','result':{'value':{'action':{'kind':'wait','reason':'service','seconds':2},'working_notes':notes}}}
    previous={'text':'retain observed dependency','historical_evidence':True}
    try:
        m._save(state['id'],1,{'working_notes':previous})
        m.step(state['id']);m.step(state['id'])
        assert get_agent(s.store,state['id'])['working_notes']==previous
    finally:m.pool.shutdown(wait=True)


def test_diagnosis_budget_switches_to_repair_and_requeues_real_job(tmp_path,monkeypatch):
    from hotpost.video_agent_memory import REPAIR_TOOLS,REPAIR_EVIDENCE_TOOLS
    s=app(tmp_path);state,job=preparation(s,tmp_path)
    read={'kind':'inspect_artifact','path':state['reference_video'],'hypothesis':'Inspect retained evidence'}
    m=VideoAgentManager(s);m.jobs=Writer([read]*16+[{'kind':'recover_preparation','job_id':job['id'],'hypothesis':'Apply audited preparation contract'}])
    clock=[1000];monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    try:
        for _ in range(34):m.step(state['id']);clock[0]+=1000
        payload=m.jobs.payloads[-1]
        assert set(payload['evidence']['allowed_actions'])==REPAIR_TOOLS|REPAIR_EVIDENCE_TOOLS
        assert 'repair executor' in payload['instruction']
        assert get_agent(s.store,state['id'])['last_result']['status']=='queued'
        assert s.store.jobs(state['id'])[0]['status']=='queued'
    finally:m.pool.shutdown(wait=True)


def test_repair_executor_cannot_spend_more_calls_reading(tmp_path,monkeypatch):
    s=app(tmp_path);state,_=preparation(s,tmp_path)
    m=VideoAgentManager(s);m.jobs=Writer([{'kind':'inspect_code','repo':'main','path':'invented.py','hypothesis':'read again'}])
    try:
        m._save(state['id'],1,{'idle_decisions':16})
        m.step(state['id']);m.step(state['id'])
        owner=get_agent(s.store,state['id'])
        assert '진단 예산' in owner['last_result']['error'] and owner['pending'] is None
    finally:m.pool.shutdown(wait=True)


@pytest.mark.parametrize('bad',[[],{},None,123])
def test_invalid_model_state_does_not_keep_pending(tmp_path,bad):
    s=app(tmp_path);state,_=s.store.create('bad-state','State',{'active':True},prepare=False)
    m=VideoAgentManager(s);m.jobs=Writer([]);m.jobs.get=lambda *a,**k:{'state':bad}
    try:
        m.step(state['id']);m.step(state['id'])
        assert get_agent(s.store,state['id'])['pending'] is None
    finally:m.pool.shutdown(wait=True)


def test_no_failed_job_does_not_enter_impossible_repair_only_mode(tmp_path):
    s=app(tmp_path);state,_=s.store.create('idle-new','New',{'active':True},prepare=False)
    m=VideoAgentManager(s);m.jobs=Writer([])
    try:
        m._save(state['id'],1,{'idle_decisions':20})
        m.step(state['id'])
        assert not m.jobs.payloads[0]['evidence'].get('allowed_actions')
        assert not get_agent(s.store,state['id'])['pending']['repair_execution']
    finally:m.pool.shutdown(wait=True)


def test_new_epoch_resets_diagnosis_budget_but_preserves_evidence(tmp_path):
    from hotpost.video_agents import enroll
    s=app(tmp_path);state,_=s.store.create('new-epoch','New',{'active':True},prepare=False)
    m=VideoAgentManager(s)
    try:
        m._save(state['id'],1,{'idle_decisions':20,'recovery_mode':True,'consecutive_failures':10}, {'status':'old failure'},'old')
        with s.store.transaction() as db:enroll(db,state,'user_command',renew=True)
        current=get_agent(s.store,state['id'])
        assert current['idle_decisions']==0 and not current['recovery_mode'] and current['consecutive_failures']==0
        assert 'old failure' in recall(s.store,state['id'],{'decision_id':'old'})['content']
    finally:m.pool.shutdown(wait=True)


@pytest.mark.parametrize('checkpoint',[{'not_before':99999999999},{'failure_classification':{'category':'access_blocked'}}])
def test_authentication_and_service_cooldown_are_not_forced_code_repairs(tmp_path,checkpoint):
    s=app(tmp_path);state,job=preparation(s,tmp_path)
    with s.store.transaction() as db:db.execute('update jobs set checkpoint=? where id=?',(json.dumps(checkpoint),job['id']))
    m=VideoAgentManager(s);m.jobs=Writer([])
    try:
        m._save(state['id'],1,{'idle_decisions':20});m.step(state['id'])
        assert not get_agent(s.store,state['id'])['pending']['repair_execution']
    finally:m.pool.shutdown(wait=True)


def test_internal_evidence_wait_is_repaired_without_removing_worker_cooldown(tmp_path):
    s=app(tmp_path);state,job=preparation(s,tmp_path)
    checkpoint={'not_before':99999999999,'internal_evidence_wait':True}
    with s.store.transaction() as db:db.execute('update jobs set checkpoint=? where id=?',(json.dumps(checkpoint),job['id']))
    m=VideoAgentManager(s);m.jobs=Writer([])
    try:
        m._save(state['id'],1,{'idle_decisions':20});m.step(state['id'])
        assert get_agent(s.store,state['id'])['pending']['repair_execution']
        with s.store.connect() as db:
            saved=json.loads(db.execute('select checkpoint from jobs where id=?',(job['id'],)).fetchone()[0])
        assert saved['not_before']==99999999999
    finally:m.pool.shutdown(wait=True)


def test_internal_wait_repair_proposal_uses_same_grace_as_planner(tmp_path,monkeypatch):
    from types import SimpleNamespace
    s=app(tmp_path);state,job=preparation(s,tmp_path)
    checkpoint={'not_before':99999999999,'internal_evidence_wait':True}
    with s.store.transaction() as db:db.execute("update jobs set status='queued',checkpoint=? where id=?",(json.dumps(checkpoint),job['id']))
    monkeypatch.setattr('hotpost.video_agents.time.time',lambda:1000)
    proposals=[];s.video_repair_pipeline=SimpleNamespace(propose_patch=lambda p:proposals.append(p) or 'repair-test',
        repair_material=lambda *a:{'content_fingerprint':'new-content'})
    m=VideoAgentManager(s)
    try:
        m._save(state['id'],1,{'queue_observation':{'since':960}})
        result=m.execute(state['id'],{'kind':'propose_patch','_agent_epoch':1,'patch':{'binding':{'job_id':job['id']},'incident':{'forged':True},'incident_fixture':{'forged':True}}},'decision',semantic_fingerprint(state))
        assert result['repair_id']=='repair-test' and proposals[0]['job_id']==job['id']
        incident=proposals[0]['incident']
        assert 'forged' not in incident and incident['task']['id']==state['id'] and incident['job']['id']==job['id']
        assert incident['job']['checkpoint']['internal_evidence_wait'] is True
        fixture=proposals[0]['incident_fixture']
        assert fixture['task']==state and fixture['job']['id']==job['id']
        assert fixture['job']['task_id']==state['id']
        assert isinstance(fixture['job']['checkpoint'],dict)
    finally:m.pool.shutdown(wait=True)


def test_current_done_qa_enters_repair_execution_and_captures_unchanged_incident(tmp_path):
    s=app(tmp_path);state,_=s.store.create('qa','QA',{'active':True},prepare=False)
    feedback=[{'kind':'cover','reason':'Face exposed'}]
    def setup(state,db):
        state.update(status='source_wait',run_id='run-qa',script_id='script-qa',voice_id='voice-qa',edit_id='edit-qa',
            daily_quality={'status':'needs_attention','pending':'scene_wait','feedback':feedback,'reviewed_edit_id':'edit-qa',
                'reviews':[{'edit_id':'edit-qa','passed':False,'issues':feedback}]})
        jid=s.store.enqueue(db,state['id'],'quality_review',{k:state[k] for k in ('script_id','voice_id','edit_id')},'qa')
        db.execute("UPDATE jobs SET status='done' WHERE id=?",(jid,))
    s.store.change(state['id'],setup);state=s.store.get(state['id']);job=s.store.jobs(state['id'])[0]
    m=VideoAgentManager(s);m.jobs=Writer([])
    from hotpost.video_agent_runtime import configure
    configure(s,m)
    try:
        m._save(state['id'],1,{'idle_decisions':20});m.step(state['id'])
        assert get_agent(s.store,state['id'])['pending']['repair_execution']
        assert 'continue_repaired' in m.jobs.payloads[0]['evidence']['allowed_actions']
        assert m.jobs.payloads[0]['evidence']['repair_packet'][0]['path']=='hotpost/daily_quality_routing.py'
        proposals=[]
        s.video_repair_pipeline.propose_patch=lambda p:proposals.append(p) or 'repair-qa'
        s.video_repair_pipeline.repair_material=lambda *a:{'content_fingerprint':'new-content'}
        result=m.execute(state['id'],{'kind':'propose_patch','_agent_epoch':1,'patch':{'binding':{'job_id':job['id']}}},'propose',semantic_fingerprint(state))
        assert result['repair_id']=='repair-qa'
        assert proposals[0]['incident_fixture']['job']['status']=='done'
        assert proposals[0]['incident_fixture']['task']['daily_quality']==state['daily_quality']
        assert s.store.jobs(state['id'])[0]['status']=='done'
    finally:m.pool.shutdown(wait=True)


def test_done_source_strategy_hold_is_repair_context_not_completed_production(tmp_path):
    s=app(tmp_path);state,_=s.store.create('source-context','Source',{'active':True},prepare=False)
    def setup(state,db):
        state.update(status='source_wait',run_id='run-source',source_goal={'ready':False},source_search_manifest_path='registered-manifest.json')
        jid=s.store.enqueue(db,state['id'],'collect_sources',{'round':6,'run_id':'run-source'},'last-source')
        db.execute("UPDATE jobs SET status='done',checkpoint=? WHERE id=?",(json.dumps({'manifest':'registered-manifest.json'}),jid))
        state['source_acquisition']={'hold':{'reason':'strategy_exhausted'},'rounds':[{'job_id':jid,'round':6,'run_id':'run-source','manifest_path':'registered-manifest.json'}]}
    s.store.change(state['id'],setup);state=s.store.get(state['id']);job=s.store.jobs(state['id'])[0]
    m=VideoAgentManager(s);m.jobs=Writer([])
    from hotpost.video_agent_runtime import configure
    configure(s,m)
    try:
        m._save(state['id'],1,{'idle_decisions':20});m.step(state['id'])
        assert get_agent(s.store,state['id'])['pending']['repair_execution']
        assert m.jobs.payloads[0]['evidence']['source_recovery']['job_ids']==[job['id']]
        proposals=[];s.video_repair_pipeline.propose_patch=lambda p:proposals.append(p) or 'repair-source'
        s.video_repair_pipeline.repair_material=lambda *a:{'content_fingerprint':'new-content'}
        result=m.execute(state['id'],{'kind':'propose_patch','_agent_epoch':1,'patch':{'binding':{'job_id':job['id']}}},'propose',semantic_fingerprint(state))
        assert result['repair_id']=='repair-source'
        assert proposals[0]['incident_fixture']['task']['source_acquisition']==state['source_acquisition']
        assert s.store.jobs(state['id'])[0]['status']=='done'
    finally:m.pool.shutdown(wait=True)


def test_working_evidence_retains_read_tails_and_only_latest_file_version():
    from hotpost.video_agent_memory import working_evidence
    def read(path,sha,offset,text):
        return {'action':{'kind':'inspect_code','repo':'main','path':path,'offset':offset},
            'result':{'content':text,'base_sha256':sha,'offset':offset,'next_offset':offset+len(text)}}
    obs=[read('a.py','old',0,'obsolete'),read('a.py','new',0,'a'*7000+'needed-tail'),
        read('b.py','b',0,'b'*12000),read('a.py','new',8000,'second range')]
    rows=[{'decision_id':str(i)} for i in range(len(obs))]
    result=working_evidence(rows,obs)
    assert [r['decision_id'] for r in result]==['1','2','3']
    assert result[0]['result']['content'].endswith('needed-tail')
    assert result[-1]['result']['offset']==8000
    assert all(r['historical_evidence'] is True for r in result)
    shorter=obs+[read('a.py','new',0,'a'*1000)]
    retained=working_evidence(rows+[{'decision_id':'short'}],shorter)
    assert any(r['result']['content'].endswith('needed-tail') for r in retained)
    assert retained[-1]['decision_id']=='short'
    empty_new=obs+[read('a.py','newer',8000,'')]
    retained=working_evidence(rows+[{'decision_id':'empty-new'}],empty_new)
    assert all(r['action']['path']!='a.py' for r in retained)
    large=[read(str(i)+'.py',str(i),0,'x'*24000) for i in range(20)]
    result=working_evidence([{'decision_id':str(i)} for i in range(20)],large)
    assert sum(len(r['result']['content']) for r in result)<=144000
    assert result[-1]['decision_id']=='19' and len(result)==6
    assert working_evidence([{'decision_id':'bad'}],[{'action':None,'result':None}])==[]


@pytest.mark.parametrize('use_line',[False,True])
def test_repair_packet_preserves_observed_tail_after_history_eviction(tmp_path,use_line):
    from types import SimpleNamespace
    from hotpost.video_agent_memory import repair_packet
    s=app(tmp_path);state,_=preparation(s,tmp_path);m=VideoAgentManager(s)
    content=('header\n'*20000)+'causal_tail\n'+('remaining\n'*9000)
    sha=hashlib.sha256(content.encode()).hexdigest();offset=len('header\n'*20000)
    action={'kind':'inspect_code','repo':'main','path':'hotpost/large.py','limit':24000}
    action.update({'line':20001} if use_line else {'offset':offset})
    try:
        m._save(state['id'],1,{}, {'action':action,'result':{'status':'completed','base_sha256':sha,'offset':offset,'content':content[offset:offset+24000]}},'tail')
        for i in range(16):
            m._save(state['id'],1,{}, {'action':{'kind':'inspect_code','repo':'main','path':f'other{i}.py'},'result':{'status':'completed','base_sha256':str(i),'content':'other'}},str(i))
        evidence=history(s.store,state['id'])
        assert not any(row['decision_id']=='tail' for row in evidence['working_evidence'])
        entry=next(row for row in evidence['memory_index'] if row['decision_id']=='tail')
        assert entry['offset']==offset and entry['line']==(20001 if use_line else None)
        def inspect(repo,path):
            if path!='hotpost/large.py':raise ValueError('not a current dependency')
            return {'content':content,'base_sha256':sha}
        pipeline=SimpleNamespace(inspect_code=inspect)
        packet=repair_packet(SimpleNamespace(video_repair_pipeline=pipeline),evidence)
        assert packet[0]['offset']==offset and packet[0]['content'].startswith('causal_tail\n')
        assert len(packet[0]['content'])==48000 and packet[0]['next_offset']==offset+48000
        # Changed file bytes invalidate historical line/offset placement.
        entry['sha256']='older-source'
        packet=repair_packet(SimpleNamespace(video_repair_pipeline=pipeline),evidence)
        assert packet[0]['offset']==0 and packet[0]['content'].startswith('header\n')
    finally:m.pool.shutdown(wait=True)


def test_memory_index_caps_latest_reference_use_not_first_insertion(tmp_path):
    from types import SimpleNamespace
    from hotpost.video_agent_memory import repair_packet
    s=app(tmp_path);state,_=preparation(s,tmp_path);m=VideoAgentManager(s)
    content='header\n'*12000+'NEEDED CURRENT CODE\n'+'tail\n'*20000
    sha=hashlib.sha256(content.encode()).hexdigest();offset=len('header\n'*12000)
    action={'kind':'inspect_code','repo':'main','path':'hotpost/important.py','offset':offset}
    try:
        m._save(state['id'],1,{}, {'action':action,'result':{'status':'completed','content':'old','base_sha256':'old'}},'first-use')
        for i in range(170):
            m._save(state['id'],1,{}, {'action':{'kind':'inspect_code','repo':'main','path':f'other{i}.py'},'result':{'status':'completed','content':'other'}},f'other-{i}')
        m._save(state['id'],1,{}, {'action':action,'result':{'status':'completed','content':content[offset:offset+24000],'base_sha256':sha,'offset':offset}},'current-use')
        evidence=history(s.store,state['id']);index=evidence['memory_index']
        assert len(index)==160 and index[-1]['decision_id']=='current-use'
        assert index[-1]['sha256']==sha and index[-1]['offset']==offset
        assert not any(row['decision_id']=='first-use' for row in index)
        def inspect(repo,path):
            if path!='hotpost/important.py':raise ValueError('unrelated')
            return {'content':content,'base_sha256':sha}
        packet=repair_packet(SimpleNamespace(video_repair_pipeline=SimpleNamespace(inspect_code=inspect)),evidence)
        assert packet[0]['path']=='hotpost/important.py' and packet[0]['offset']==offset
        assert packet[0]['content'].startswith('NEEDED CURRENT CODE')
    finally:m.pool.shutdown(wait=True)


def test_memory_preserves_repair_target_and_rejections_per_repair(tmp_path):
    s=app(tmp_path);state,_=s.store.create('memory-binding','Memory',{'active':True},prepare=False)
    m=VideoAgentManager(s)
    try:
        for n in (1,2):
            m._save(state['id'],1,{}, {'action':{'kind':'propose_patch','hypothesis':'Incident '+str(n),
                'patch':{'binding':{'job_id':'job-'+str(n)}}},'fingerprint':'input-'+str(n),
                'result':{'status':'completed','repair_id':'repair-'+str(n)}},'proposal-'+str(n))
            m._save(state['id'],1,{}, {'action':{'kind':'review_patch','repair_id':'repair-'+str(n)},
                'result':{'status':'error','error':'Rejected '+str(n)},'fingerprint':'input-'+str(n)},'review-'+str(n))
        index=history(s.store,state['id'])['memory_index']
        assert len(index)==4
        assert index[0]['job_id']=='job-1' and index[2]['job_id']=='job-2'
        assert index[0]['input_fingerprint']=='input-1' and index[2]['input_fingerprint']=='input-2'
        assert index[1]['repair_id']=='repair-1' and index[3]['repair_id']=='repair-2'
        assert all(r['historical_evidence'] for r in index)
    finally:m.pool.shutdown(wait=True)


def test_next_decision_receives_full_last_inspection_before_next_offset(tmp_path):
    s=app(tmp_path);state,_=s.store.create('read-body','Read',{'active':True},prepare=False)
    m=VideoAgentManager(s);m.jobs=Writer([])
    content='x'*15000+'actual failure line'+'y'*8990
    try:
        m._save(state['id'],1,{}, {'action':{'kind':'inspect_code','path':'hotpost/source.py'},
            'result':{'status':'completed','content':content,'next_offset':len(content)}},'read')
        m.step(state['id'])
        result=m.jobs.payloads[-1]['evidence']['previous_steps'][-1]['result']
        assert result['content']==content and result['next_offset']==len(content)
    finally:m.pool.shutdown(wait=True)


@pytest.mark.parametrize('blocked',[None,'user_pause','changed_epoch','missing_park','cooldown','execution_error'])
def test_fresh_loaded_repair_finishes_same_guarded_job_without_another_model(tmp_path,monkeypatch,blocked):
    from types import SimpleNamespace
    from hotpost.video_agent_runtime import resume_loaded_repairs
    from hotpost import video_agent_actions,video_agent_repairs
    s=app(tmp_path);state,_=s.store.create('resume-load','Resume',{'active':True},prepare=False)
    fp=semantic_fingerprint(state)
    from hotpost.video_agent_context import job_method_fingerprint
    signature=job_method_fingerprint({'kind':'collect_sources','payload':{},'checkpoint':{}})
    with s.store.transaction() as db:
        jid=s.store.enqueue(db,state['id'],'collect_sources',{},'original-job')
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps({'video_agent_input_fingerprint':fp,'video_agent_job_fingerprint':signature}),jid))
    receipt={'repair_id':'repair-loaded','binding':{'task_id':state['id'],'job_id':jid,'input_fingerprint':fp,'job_fingerprint':signature,'agent_epoch':1},
        'files':[{'repo':'main','path':'hotpost/source.py','sha256':'verified'}]}
    s.video_repair_pipeline=SimpleNamespace(ready_to_apply=lambda _:receipt)
    parked=video_agent_actions.execute(s,state['id'],{'kind':'park_for_repair','repair_id':'repair-loaded',
        'job_id':jid,'_agent_epoch':1,'hypothesis':'Test actual host parking'},'park',fp)
    assert parked['parked']
    s.loaded_code_receipts={'repair-loaded':receipt}
    monkeypatch.setattr(video_agent_repairs,'verified_repair',lambda *args:receipt)
    if blocked=='user_pause':s.store.change(state['id'],lambda x,db:x['automation'].update(paused_by_user=True))
    with s.store.transaction() as db:
        if blocked=='changed_epoch':db.execute('update video_agents set epoch=2 where task_id=?',(state['id'],))
        cp=json.loads(db.execute('select checkpoint from jobs where id=?',(jid,)).fetchone()[0])
        if blocked=='missing_park':cp.pop('video_agent_park_receipt')
        if blocked=='cooldown':cp['not_before']=99999999999
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),jid))
    m=VideoAgentManager(s)
    try:
        if blocked=='execution_error':
            def broken(*args):raise TypeError('Malformed legacy source record')
            monkeypatch.setattr(video_agent_actions,'execute',broken)
        resume_loaded_repairs(s,m);resume_loaded_repairs(s,m)
        jobs=s.store.jobs(state['id'])
        assert len(jobs)==1 and jobs[0]['id']==jid
        assert jobs[0]['status']==('queued' if blocked is None else 'paused')
        if blocked is None:assert get_agent(s.store,state['id'])['last_action']=='retry_repaired'
        if blocked=='execution_error':
            owner=get_agent(s.store,state['id'])
            assert owner['status']=='recovering' and owner['last_result']['failure_type']=='TypeError'
            assert 'Malformed legacy source record' in owner['last_result']['failure_trace']
    finally:m.pool.shutdown(wait=True)


def test_missing_incident_receipt_does_not_advertise_or_force_recovery(tmp_path):
    s=app(tmp_path);state,_=preparation(s,tmp_path)
    (s.store.root/'preparation-recovery.json').unlink()
    m=VideoAgentManager(s);m.jobs=Writer([])
    try:
        m._save(state['id'],1,{'idle_decisions':20});m.step(state['id'])
        evidence=m.jobs.payloads[-1]['evidence']
        assert 'recover_preparation' not in evidence['production_tools_available']
        assert not evidence.get('allowed_actions')
    finally:m.pool.shutdown(wait=True)


def test_unexecuted_cooldown_hold_can_execute_after_time_changes(tmp_path,monkeypatch):
    s=app(tmp_path);state,job=preparation(s,tmp_path);clock=[1000]
    with s.store.transaction() as db:db.execute('update jobs set checkpoint=? where id=?',(json.dumps({'not_before':1200}),job['id']))
    m=VideoAgentManager(s);action={'kind':'recover_preparation','job_id':job['id'],'hypothesis':'Use verified repair after service cooldown'}
    m.jobs=Writer([action,action]);monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    try:
        m.step(state['id']);m.step(state['id'])
        assert get_agent(s.store,state['id'])['last_result']['status']=='held'
        clock[0]=1500;m.step(state['id']);m.step(state['id'])
        assert get_agent(s.store,state['id'])['last_result']['status']=='queued'
    finally:m.pool.shutdown(wait=True)


def test_repair_executor_can_fetch_missing_code_once_without_read_loop(tmp_path,monkeypatch):
    s=app(tmp_path);state,_=preparation(s,tmp_path)
    read={'kind':'inspect_code','repo':'main','path':'hotpost/studio_runtime/generation.py','hypothesis':'Missing cause',
        'needed_for_repair':'Need the exact preparation branch before constructing the patch'}
    m=VideoAgentManager(s);m.jobs=Writer([read,read]);executed=[];clock=[1000]
    monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    m.execute=lambda *a:(executed.append(a) or {'status':'completed','content':'actual code'})
    try:
        m._save(state['id'],1,{'idle_decisions':16})
        for _ in range(4):m.step(state['id']);clock[0]+=1000
        assert len(executed)==1
        assert '진단 예산' in get_agent(s.store,state['id'])['last_result']['error']
    finally:m.pool.shutdown(wait=True)


def test_spent_budget_can_read_new_source_but_not_aliases_or_overlaps_after_restart(tmp_path,monkeypatch):
    s=app(tmp_path);state,job=preparation(s,tmp_path)
    repo=tmp_path/'repo';(repo/'hotpost').mkdir(parents=True)
    source=repo/'hotpost/readiness.py';source.write_text('# exact contract\n'+'x'*12000,'utf8')
    from hotpost.video_agent_repairs import VideoRepairPipeline
    s.video_repair_pipeline=VideoRepairPipeline(repo,repo,tmp_path/'receipts',interpreters={},regression_tests={})
    before=s.store.jobs(state['id']);clock=[1000]
    monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    base={'kind':'inspect_code','repo':'main','path':'hotpost/readiness.py','limit':4096,
          'hypothesis':'Implement saved readiness recovery',
          'needed_for_repair':'Read the missing technical readiness contract before implementing recovery'}
    m=VideoAgentManager(s);m.jobs=Writer([base])
    try:
        m._save(state['id'],1,{'idle_decisions':30,'repair_evidence_used':['used']*6})
        m.step(state['id']);m.step(state['id'])
        assert 'inspect_code' in m.jobs.payloads[-1]['evidence']['allowed_actions']
        assert get_agent(s.store,state['id'])['last_result']['status']=='completed'
        assert history(s.store,state['id'])['working_evidence'][-1]['result']['content']==source.read_bytes().decode('utf8')[:4096]
        assert get_agent(s.store,state['id'])['idle_decisions']>30
    finally:m.pool.shutdown(wait=True)
    # Durable receipts, not an in-memory budget, reject alternate spellings and
    # mostly overlapping reads. A genuinely missing range still gets through.
    m=VideoAgentManager(s);m.jobs=Writer([
        {**base,'path':'hotpost/./readiness.py','hypothesis':'Different wording'},
        {**base,'offset':1},{**base,'offset':4096},
        {**base,'offset':11000,'limit':1},
        {**base,'query':'readiness'},{**base,'path':'../outside.py'}])
    try:
        results=[]
        for _ in range(6):
            clock[0]+=1000;m.step(state['id']);m.step(state['id'])
            results.append(get_agent(s.store,state['id'])['last_result'])
        assert [r['status'] for r in results]==['error','error','completed','completed','error','error']
        assert results[3]['offset']==11000 and results[3]['total_characters']==len(source.read_bytes().decode('utf8'))
        assert s.store.jobs(state['id'])==before
        assert get_agent(s.store,state['id'])['repair_evidence_used']==['used']*6
        # A real source revision is new evidence, while original patch/review
        # guards remain responsible for accepting changes to production.
        source.write_text('# revised contract\n'+'y'*12000,'utf8')
        m.jobs=Writer([base]);clock[0]+=1000;m.step(state['id']);m.step(state['id'])
        assert get_agent(s.store,state['id'])['last_result']['status']=='completed'
    finally:m.pool.shutdown(wait=True)


def test_novel_contract_union_and_empty_tail_cannot_buy_information_progress(tmp_path):
    from hotpost.video_agent_memory import novel_code_contract
    s=app(tmp_path);state,_=preparation(s,tmp_path);m=VideoAgentManager(s)
    try:
        for i in range(2):
            m._save(state['id'],1,{}, {'action':{'kind':'inspect_code','repo':'main','path':'hotpost/a.py'},
                'result':{'status':'completed','base_sha256':'sha','offset':i*3000,'content':'a'*3000}},f'read-{i}')
        result={'repo':'main','path':'hotpost/a.py','base_sha256':'sha','content':'a'*6000,'offset':0,'total_characters':6500}
        assert not novel_code_contract(s.store,state['id'],1,result)
        assert not novel_code_contract(s.store,state['id'],1,{**result,'content':'a'*6500})
        assert novel_code_contract(s.store,state['id'],1,{**result,'offset':6000,'content':'a'*500})
        assert not novel_code_contract(s.store,state['id'],1,{**result,'offset':6500,'content':''})
    finally:m.pool.shutdown(wait=True)


def test_old_ephemeral_read_is_restored_once_per_attested_owner_conversation(tmp_path,monkeypatch):
    from hotpost.video_agent_repairs import VideoRepairPipeline
    from hotpost.writing.owner_session import value_digest
    s=app(tmp_path);state,_=preparation(s,tmp_path)
    repo=tmp_path/'repo';(repo/'hotpost').mkdir(parents=True)
    text='# previously read but lost contract\n';source=repo/'hotpost/readiness.py';source.write_bytes(text.encode())
    s.video_repair_pipeline=VideoRepairPipeline(repo,repo,tmp_path/'receipts',interpreters={},regression_tests={})
    action={'kind':'inspect_code','repo':'main','path':'hotpost/readiness.py',
            'needed_for_repair':'Restore exact missing readiness contract from the old ephemeral context'}
    context=['00000000-0000-0000-0000-000000000001'];clock=[1000]
    monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    def writer():
        w=Writer([copy.deepcopy(action)]*4);original=w.get
        def get(*args,**kwargs):
            result=original(*args,**kwargs)
            value=result['result']['value']
            result['result']['inference']={'calls':[{'status':'completed','exit_code':0,
                'decoded_value_sha256':value_digest(value),'owner_conversation':{
                    'binding':{'task_id':state['id'],'run_id':state.get('run_id'),'epoch':1},
                    'thread_id':context[0]}}]}
            return result
        w.get=get;return w
    m=VideoAgentManager(s);m.jobs=writer()
    try:
        old=m.execute(state['id'],action,'old',semantic_fingerprint(state))
        m._save(state['id'],1,{'idle_decisions':30,'repair_evidence_used':['used']*6},
                {'action':action,'result':old},'ephemeral-old')
        m.step(state['id']);m.step(state['id'])
        assert get_agent(s.store,state['id'])['last_result']['status']=='completed'
        assert history(s.store,state['id'])['working_evidence'][-1]['result']['content']==text
    finally:m.pool.shutdown(wait=True)
    m=VideoAgentManager(s);m.jobs=writer()
    try:
        clock[0]+=1000;m.step(state['id']);m.step(state['id'])
        assert get_agent(s.store,state['id'])['last_result']['status']=='error'
        context[0]='00000000-0000-0000-0000-000000000002'
        clock[0]+=1000;m.step(state['id']);m.step(state['id'])
        assert get_agent(s.store,state['id'])['last_result']['status']=='completed'
        clock[0]+=1000;m.step(state['id']);m.step(state['id'])
        assert get_agent(s.store,state['id'])['last_result']['status']=='error'
    finally:m.pool.shutdown(wait=True)


@pytest.mark.parametrize('defect',['foreign_binding','wrong_digest','failed','malformed_uuid','model_claim','conflicting_calls'])
def test_model_cannot_reset_code_delivery_context_by_claiming_a_thread(defect):
    from hotpost.video_agent_memory import model_context_id
    from hotpost.writing.owner_session import value_digest
    binding={'task_id':'work-1','run_id':'run-1','epoch':1};value={'action':{'kind':'inspect_code'}}
    call={'status':'completed','exit_code':0,'decoded_value_sha256':value_digest(value),
          'owner_conversation':{'binding':binding.copy(),'thread_id':'00000000-0000-0000-0000-000000000001'}}
    result={'value':value,'inference':{'calls':[call]}}
    assert model_context_id(result,binding)==call['owner_conversation']['thread_id']
    if defect=='foreign_binding':call['owner_conversation']['binding']['task_id']='work-other'
    elif defect=='wrong_digest':call['decoded_value_sha256']='bad'
    elif defect=='failed':call['status']='failed'
    elif defect=='malformed_uuid':call['owner_conversation']['thread_id']='invented'
    elif defect=='model_claim':result={'value':{'owner_conversation':call['owner_conversation']}}
    else:
        second=copy.deepcopy(call);second['owner_conversation']['thread_id']='00000000-0000-0000-0000-000000000002'
        result['inference']['calls'].append(second)
    assert model_context_id(result,binding) is None


@pytest.mark.parametrize('seconds',['bad',None,float('nan'),float('inf')])
def test_bad_tool_delay_never_loses_executed_receipt(tmp_path,seconds):
    s=app(tmp_path);state,_=s.store.create('delay','Delay',{'active':True},prepare=False)
    m=VideoAgentManager(s);m.jobs=Writer([{'kind':'test_patch','repair_id':'test','hypothesis':'Verify repair'}])
    m.execute=lambda *a:{'status':'completed','seconds':seconds,'test_receipt':'preserve'}
    try:
        m.step(state['id']);m.step(state['id'])
        owner=get_agent(s.store,state['id'])
        assert owner['pending'] is None and owner['last_result']['test_receipt']=='preserve'
        assert 'preserve' in history(s.store,state['id'])['previous_steps'][-1]['result']['test_receipt']
    finally:m.pool.shutdown(wait=True)


def test_large_failure_file_is_excerpted_at_actual_trace_location(tmp_path):
    from types import SimpleNamespace
    from hotpost.video_agent_memory import repair_packet
    text=('unrelated line padding\n'*10000)+'EXACT FAILURE HERE\n'+('tail\n'*40000)
    pipeline=SimpleNamespace(roots={'main':tmp_path},inspect_code=lambda *a:{'content':text,'base_sha256':'whole-file-sha'})
    evidence={'jobs':[{'checkpoint':{'failure_trace':{'frames':[{'path':str(tmp_path/'large.py'),'line':10001}]}}}]}
    packet=repair_packet(SimpleNamespace(video_repair_pipeline=pipeline),evidence)
    assert len(packet)==1 and 'EXACT FAILURE HERE' in packet[0]['content']
    assert packet[0]['offset']>0 and packet[0]['base_sha256']=='whole-file-sha' and len(packet[0]['content'])<=48000


@pytest.mark.parametrize('kind',['test_patch','review_patch','apply_patch'])
def test_owner_cannot_mutate_another_videos_repair(tmp_path,kind):
    from types import SimpleNamespace
    s=app(tmp_path);state,_=s.store.create('owner','Owner',{'active':True},prepare=False)
    calls=[]
    def authorize(rid,task,epoch,store):
        assert task==state['id'] and epoch==1
        calls.append('authorization');raise ValueError('Repair task differs from caller')
    s.video_repair_pipeline=SimpleNamespace(authorize=authorize,
        test_patch=lambda *a:pytest.fail('cross-task test ran'),review_patch=lambda *a:pytest.fail('cross-task review ran'),
        apply_patch=lambda *a,**k:pytest.fail('cross-task apply ran'))
    m=VideoAgentManager(s)
    try:
        with pytest.raises(ValueError,match='caller'):
            m.execute(state['id'],{'kind':kind,'repair_id':'foreign','_agent_epoch':1},'test',semantic_fingerprint(state))
        assert calls==['authorization']
    finally:m.pool.shutdown(wait=True)


@pytest.mark.parametrize('outcome',['drained','timeout','revoked','shutdown'])
def test_reviewed_apply_keeps_admission_closed_until_drain(tmp_path,monkeypatch,outcome):
    from types import SimpleNamespace
    import hotpost.video_agents as owners
    s=app(tmp_path);state,_=s.store.create('drain','Drain',{'active':True},prepare=False)
    m=VideoAgentManager(s);calls=[];ticks=[0.0]
    monkeypatch.setattr(owners.time,'monotonic',lambda:ticks[0])
    def apply(*args,**kwargs):
        assert m.maintenance.is_set()
        calls.append('attempt')
        if len(calls)==1:raise ValueError('All production, collection and model queues must be idle before apply.')
        if outcome=='revoked':raise ValueError('Agent ownership changed')
        return {'repair_id':'own','status':'applied'}
    def wait(seconds):
        assert m.maintenance.is_set()
        # No peer may be admitted while the already-running queues settle.
        m.tick();assert not m.futures
        ticks[0]+=61 if outcome=='timeout' else seconds
        if outcome=='shutdown':m.stop.set()
    if outcome=='timeout':
        def apply(*args,**kwargs):
            assert m.maintenance.is_set();calls.append('attempt')
            raise ValueError('All production, collection and model queues must be idle before apply.')
    monkeypatch.setattr(m.stop,'wait',wait)
    s.video_repair_pipeline=SimpleNamespace(authorize=lambda *a:None,apply_patch=apply)
    m.request_restart=lambda receipt:m.restart_requested.set()
    action={'kind':'apply_patch','repair_id':'own','review_id':'review','_agent_epoch':1}
    try:
        if outcome=='revoked':
            with pytest.raises(ValueError,match='ownership'):m.execute(state['id'],action,'decision',semantic_fingerprint(state))
        else:
            result=m.execute(state['id'],action,'decision',semantic_fingerprint(state))
            assert result['status']==('applied' if outcome=='drained' else 'waiting')
        assert m.restart_requested.is_set()==(outcome=='drained')
        assert m.maintenance.is_set()==(outcome=='drained')
        assert len(calls)==(1 if outcome=='shutdown' else 2)
    finally:m.pool.shutdown(wait=True)



def test_rejected_mutation_reopens_only_after_host_prerequisite_changes(tmp_path,monkeypatch):
    from types import SimpleNamespace
    s=app(tmp_path);state,job=preparation(s,tmp_path)
    record={'binding':{'task_id':state['id'],'job_id':job['id']},'status':'staged'}
    s.video_repair_pipeline=SimpleNamespace(_read=lambda rid:record)
    action={'kind':'apply_patch','repair_id':'own','review_id':'review','hypothesis':'Apply exact repair'}
    m=VideoAgentManager(s);m.jobs=Writer([action]*4);calls=[]
    def execute(*args):
        calls.append(record['status'])
        if record['status']!='reviewed':raise ValueError('Missing signed independent review')
        return {'status':'error','error':'New dependency mismatch; restage required'}
    m.execute=execute
    clock=[1000];monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    def decision():
        for _ in range(2):m.step(state['id']);clock[0]+=1000
    try:
        decision();decision()
        assert len(calls)==1 and '같은 행동' in get_agent(s.store,state['id'])['last_result']['error']
        record.update(status='reviewed',review={'signature':'host-signed'})
        decision();assert calls==['staged','reviewed']
        decision();assert len(calls)==2
    finally:m.pool.shutdown(wait=True)


def test_forced_repair_can_read_a_distinct_missing_owned_artifact(tmp_path,monkeypatch):
    s=app(tmp_path);state,_=preparation(s,tmp_path)
    file=s.folder(state['id'])/'diagnosis.json';file.write_text('{"evidence":"registered local receipt"}')
    action={'kind':'inspect_artifact','path':str(file),'needed_for_repair':'Read actual binding receipt before designing correction','hypothesis':'Missing exact receipt'}
    m=VideoAgentManager(s);m.jobs=Writer([action,action])
    clock=[1000];monkeypatch.setattr('hotpost.video_agents.time.time',lambda:clock[0])
    try:
        m._save(state['id'],1,{'idle_decisions':16})
        for _ in range(2):m.step(state['id']);clock[0]+=1000
        assert get_agent(s.store,state['id'])['last_result']['status']=='completed'
        for _ in range(2):m.step(state['id']);clock[0]+=1000
        assert '진단 예산' in get_agent(s.store,state['id'])['last_result']['error']
        assert len(get_agent(s.store,state['id'])['repair_evidence_used'])==1
    finally:m.pool.shutdown(wait=True)



def test_historical_ledgers_do_not_overflow_repair_review_or_owner_memory(tmp_path):
    from hotpost.video_agent_context import compact_incident
    incident={'task':{'source_acquisition':{'round':202,'no_progress_rounds':201,'waiting':{'reason':'must retain'},'rounds':[{'evidence':'x'*12000} for _ in range(150)],'interrupted_attempts':[{'id':i,'evidence':'y'*12000} for i in range(20)]}},'job':{'checkpoint':{'source_attempts':[{'product':''}]}},'expected_source_attempt_binding':{'product':'current'}}
    raw=json.dumps(incident);projected=compact_incident(incident)
    assert json.dumps(incident)==raw and len(json.dumps(projected))<15000
    assert projected['job']==incident['job'] and projected['expected_source_attempt_binding']==incident['expected_source_attempt_binding']
    ac=projected['task']['source_acquisition'];assert ac['round']==202 and ac['waiting']=={'reason':'must retain'}
    assert ac['rounds']['count']==150 and len(ac['rounds']['sha256'])==64
    assert compact_incident(projected)==projected
    s=app(tmp_path);state,_=s.store.create('bounded','Bounded',{'active':True},prepare=False);m=VideoAgentManager(s)
    try:
        m._save(state['id'],1,{}, {'action':{'kind':'inspect_repair'},'result':{'status':'completed','diagnostics':{'incident':incident}}},'old-oversized')
        bounded=history(s.store,state['id']);assert len(json.dumps(bounded))<18000
        with s.store.connect() as db:
            original=json.loads(db.execute('select observation from video_agent_steps where decision_id=?',('old-oversized',)).fetchone()[0])
        assert original['result']['diagnostics']['incident']==incident
    finally:m.pool.shutdown(wait=True)
