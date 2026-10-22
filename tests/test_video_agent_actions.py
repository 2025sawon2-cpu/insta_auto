import hashlib
import json
from types import SimpleNamespace
import time

import pytest

from hotpost import video_agent_actions as actions
from hotpost.studio_store import StudioStore


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store=StudioStore(tmp_path/'studio')
    state={'id':'work-one','shortcode':'one','title':'duck','revision':0,'status':'editing',
           'updated':time.time(),'automation':{'active':True},'sources':[],'scripts':[],
           'voices':[],'edits':[],'semantic':'input-a','daily_quality':{}}
    with store.transaction() as db:
        db.execute('INSERT INTO tasks VALUES(?,?,?,?,?)',('work-one','one',0,json.dumps(state),time.time()))
        db.execute('CREATE TABLE video_agents(task_id TEXT PRIMARY KEY,epoch INTEGER,record TEXT,updated REAL)')
        db.execute('INSERT INTO video_agents VALUES(?,?,?,?)',('work-one',1,'{}',time.time()))
    monkeypatch.setattr(actions,'_fingerprint',lambda s:s['semantic'])
    studio=SimpleNamespace(store=store,settings=SimpleNamespace(data_dir=tmp_path))
    studio._advance_auto=lambda s,db:store.enqueue(db,s['id'],'edit',{},'new-edit')
    studio.ensure_source_collection=lambda s,db:store.enqueue(db,s['id'],'collect_sources',{},'new-collection')
    studio.advance_daily_quality=lambda s,db,*args:store.enqueue(db,s['id'],'refresh_sources',{'daily_quality_repair':True},'repair-scenes')
    return studio,state,tmp_path


def action(kind='advance',**values):
    return {'kind':kind,'hypothesis':'Use validated current evidence','evidence':[], '_agent_epoch':1,**values}


def execute(studio,value,decision='decision-one',fingerprint='input-a'):
    return actions.execute(studio,'work-one',value,decision,fingerprint)


def modify(studio,**values):
    studio.store.change('work-one',lambda s,db:s.update(values))


def failed(studio,kind='edit',classification=None,status='failed',checkpoint=None):
    with studio.store.transaction() as db:
        jid=studio.store.enqueue(db,'work-one',kind,{},'old-method')
        cp=checkpoint or {}
        if classification:cp['failure_classification']=classification
        db.execute('UPDATE jobs SET status=?,checkpoint=?,error=? WHERE id=?',(status,json.dumps(cp),'saved failure',jid))
    return jid


def transient():
    return {'category':'transport','retryable':True,'reason':'typed_connection_failure',
            'signature_material':{'exception_type':'requests.exceptions.ConnectionError'}}


def supervisor_hold(studio,jid):
    with studio.store.transaction() as db:
        db.execute('CREATE TABLE supervision_jobs(job_id TEXT PRIMARY KEY,task_id TEXT,claim TEXT,phase TEXT,record TEXT)')
        db.execute('INSERT INTO supervision_jobs VALUES(?,?,?,?,?)',(jid,'work-one','claim-old','held',json.dumps({'phase':'held','incident':'keep-original'})))


def test_advance_enqueues_actual_production_once(setup):
    studio,_,_=setup
    first=execute(studio,action())
    assert first['status']=='queued' and len(first['job_ids'])==1
    assert execute(studio,action())==first
    assert len(studio.store.jobs('work-one'))==1


@pytest.mark.parametrize('changes',[{'automation':{'active':True,'paused_by_user':True}},
    {'automation':{'active':False}}, {'automation':{'active':True,'pause_reason':'save-script'}},
    {'source_acquisition':{'hold':{'reason':'captcha'}}},
    {'source_acquisition':{'waiting':{'searches':[{'status':'login_required'}]}}},
    {'daily_quality':{'pending':'exhausted'}}, {'editorial_content_hold':{'reason':'unresolved'}}])
def test_user_access_and_quality_holds_cannot_be_cleared(setup,changes):
    studio,_,_=setup;modify(studio,**changes)
    result=execute(studio,action())
    assert result['status']=='held' and studio.store.jobs('work-one')==[]
    assert all(studio.store.get('work-one')[k]==v for k,v in changes.items())


def test_epoch_and_semantic_input_are_checked_in_action_transaction(setup):
    studio,_,_=setup
    assert execute(studio,action(_agent_epoch=0))['status']=='held'
    assert execute(studio,action(),fingerprint='old-input')['status']=='held'
    assert not studio.store.jobs('work-one')


def test_existing_worker_and_implicit_failed_resurrection_are_blocked(setup):
    studio,_,_=setup
    jid=failed(studio)
    studio._advance_auto=lambda s,db:studio.store.enqueue(db,s['id'],'edit',{},'old-method')
    assert execute(studio,action())['status']=='held'
    assert studio.store.jobs('work-one')[0]['status']=='failed'
    with studio.store.transaction() as db:db.execute("UPDATE jobs SET status='running' WHERE id=?",(jid,))
    assert execute(studio,action('collect_sources'))['status']=='held'


def test_collection_and_scene_repair_use_normal_queue_contracts(setup):
    studio,_,_=setup
    assert execute(studio,action('repair_scenes'))['status']=='held'
    modify(studio,daily_quality={'pending':'recollect','feedback':[{'kind':'scene_gap','search_query':'approved product'}]})
    result=execute(studio,action('repair_scenes'))
    assert result['status']=='queued'
    saved=studio.store.jobs('work-one')[0]
    with studio.store.connect() as db:
        payload=json.loads(db.execute('SELECT payload FROM jobs WHERE id=?',(saved['id'],)).fetchone()[0])
    assert saved['kind']=='refresh_sources' and payload['daily_quality_repair'] is True


def test_collection_cannot_leave_a_new_job_behind_unchanged_supervision_hold(setup):
    studio,_,_=setup;jid=failed(studio,status='paused');supervisor_hold(studio,jid)
    assert execute(studio,action('collect_sources',held_job_id=jid))['status']=='held'
    assert len(studio.store.jobs('work-one'))==1
    with studio.store.connect() as db:
        assert db.execute('SELECT phase FROM supervision_jobs').fetchone()[0]=='held'


def test_typed_retry_uses_shared_budget_and_never_resets_it(setup):
    studio,_,_=setup;jid=failed(studio,classification=transient())
    value=action('retry',job_id=jid)
    assert execute(studio,value)['status']=='queued'
    for index in (2,3):
        with studio.store.transaction() as db:db.execute("UPDATE jobs SET status='failed' WHERE id=?",(jid,))
        result=execute(studio,value,'decision-'+str(index))
        assert result['status']==('queued' if index==2 else 'held')
    with studio.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM retry_budget_attempts WHERE reserved=1').fetchone()[0]==2


def test_typed_retry_does_not_release_exact_supervision_hold(setup):
    studio,_,_=setup;jid=failed(studio,classification=transient());supervisor_hold(studio,jid)
    assert execute(studio,action('retry',job_id=jid))['status']=='held'
    with studio.store.connect() as db:
        assert db.execute('SELECT phase FROM supervision_jobs').fetchone()[0]=='held'


def test_no_progress_error_text_and_claim_id_never_authorize_retry(setup):
    studio,_,_=setup;jid=failed(studio,classification={'category':'no_progress','retryable':False})
    assert execute(studio,action('retry',job_id=jid,hypothesis='connection timeout fixed'))['status']=='held'


def test_verified_repair_releases_only_exact_hold_preserving_incident(setup,monkeypatch):
    studio,_,_=setup;jid=failed(studio,status='paused');supervisor_hold(studio,jid)
    from hotpost import video_agent_repairs
    receipt={'repair_id':'repair-one','files':[{'sha256':'tested-code'}]}
    monkeypatch.setattr(video_agent_repairs,'verified_repair',lambda *args:receipt)
    result=execute(studio,action('retry_repaired',job_id=jid,repair_id='repair-one'))
    assert result['status']=='queued'
    with studio.store.connect() as db:
        row=db.execute('SELECT phase,record FROM supervision_jobs').fetchone()
        assert row['phase']=='method_changed'
        record=json.loads(row['record'])
        assert record['incident']=='keep-original' and 'released_at' not in record
        assert record['method_change']['evidence']==[{'repair':receipt}]


def test_false_or_unrelated_repair_cannot_unpause_a_job(setup,monkeypatch):
    studio,_,_=setup;jid=failed(studio,status='paused');supervisor_hold(studio,jid)
    from hotpost import video_agent_repairs
    monkeypatch.setattr(video_agent_repairs,'verified_repair',lambda *args:False)
    assert execute(studio,action('retry_repaired',job_id=jid,repair_id='invented'))['status']=='held'


def test_new_repair_receipt_id_cannot_repeat_same_applied_method(setup,monkeypatch):
    studio,_,_=setup;jid=failed(studio,status='paused');supervisor_hold(studio,jid)
    from hotpost import video_agent_repairs
    monkeypatch.setattr(video_agent_repairs,'verified_repair',lambda studio,state,a,old:
        {'repair_id':a['repair_id'],'files':[{'repo':'insta_auto','path':'hotpost/worker.py','sha256':'same-code'}]})
    assert execute(studio,action('retry_repaired',job_id=jid,repair_id='repair-first'))['status']=='queued'
    with studio.store.transaction() as db:
        db.execute("UPDATE jobs SET status='failed' WHERE id=?",(jid,))
    assert execute(studio,action('retry_repaired',job_id=jid,repair_id='new-id'),decision='decision-two')['status']=='held'


def test_quality_review_binds_latest_actual_video_and_plan_bytes(setup):
    studio,_,root=setup
    video=root/'preview.mp4';video.write_bytes(b'video')
    plan=root/'plan.json';plan.write_text('{}')
    modify(studio,script_id='script-one',approved_script_id='script-one',voice_id='voice-one',approved_voice_id='voice-one',edit_id='edit-one',
           scripts=[{'id':'script-one','text':'approved'}],voices=[{'id':'voice-one','script_id':'script-one'}],
           edits=[{'id':'edit-one','script_id':'script-one','voice_id':'voice-one','preview_path':str(video),'plan_path':str(plan)}])
    value=action('quality_review',edit_id='edit-one',render_sha256=hashlib.sha256(b'video').hexdigest(),plan_sha256=hashlib.sha256(b'{}').hexdigest())
    assert execute(studio,{**value,'render_sha256':'incorrect'})['status']=='held'
    result=execute(studio,value)
    assert result['status']=='queued'
    with studio.store.connect() as db:
        payload=json.loads(db.execute('SELECT payload FROM jobs WHERE id=?',(result['job_ids'][0],)).fetchone()[0])
    assert payload['edit_id']=='edit-one' and payload['render_sha256']==value['render_sha256']
    assert payload['agent_bound_review'] is True and not payload.get('explicit_policy_recheck')


@pytest.mark.parametrize('pending',['rewrite','reedit','recollect','recheck','stop_method'])
def test_review_does_not_discard_existing_quality_repair(setup,pending):
    studio,_,_=setup
    modify(studio,daily_quality={'pending':pending,'feedback':[{'kind':'scene_gap'}]})
    assert execute(studio,action('quality_review'))['status']=='held'
    assert studio.store.get('work-one')['daily_quality']['pending']==pending


def test_self_shot_cannot_be_sent_to_external_collection(setup):
    studio,_,_=setup;modify(studio,creation_mode='self_shot')
    assert execute(studio,action('collect_sources'))['status']=='held'
    assert not studio.store.jobs('work-one')


def bind_failure_input(studio,jid):
    from hotpost.retry_budget import reserve
    with studio.store.connect() as db:
        old=dict(db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
    old['payload']=json.loads(old['payload']);old['checkpoint']=json.loads(old['checkpoint'])
    classify={'category':'no_progress','retryable':False,'reason':'requires_new_evidence'}
    old['checkpoint']['failure_classification']=classify
    assert not reserve(studio.store,old,classify,studio.store.get('work-one'))
    with studio.store.transaction() as db:
        db.execute('UPDATE jobs SET checkpoint=? WHERE id=?',(json.dumps(old['checkpoint']),jid))


def test_verified_new_media_releases_exact_hold_for_unused_collection(setup):
    studio,_,root=setup;jid=failed(studio,status='paused');supervisor_hold(studio,jid)
    bind_failure_input(studio,jid)
    video=root/'new-source.mp4';video.write_bytes(b'new source actual bytes')
    sha=hashlib.sha256(video.read_bytes()).hexdigest()
    modify(studio,sources=[{'id':'new-source','path':str(video),'sha256':sha}])
    value=action('collect_sources',held_job_id=jid,evidence=[{'path':str(video),'sha256':sha}])
    result=execute(studio,value)
    assert result['status']=='queued'
    with studio.store.connect() as db:
        assert db.execute('SELECT phase FROM supervision_jobs WHERE job_id=?',(jid,)).fetchone()[0]=='method_changed'
        assert db.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()[0]=='paused'


def test_same_bytes_new_filename_and_hypothesis_are_not_changed_input(setup):
    studio,_,root=setup
    video=root/'old.mp4';video.write_bytes(b'same bytes');sha=hashlib.sha256(video.read_bytes()).hexdigest()
    modify(studio,sources=[{'id':'source-old','path':str(video),'sha256':sha}])
    jid=failed(studio,status='paused');supervisor_hold(studio,jid);bind_failure_input(studio,jid)
    copied=root/'new-name.mp4';copied.write_bytes(video.read_bytes())
    modify(studio,sources=[{'id':'source-new','path':str(copied),'sha256':sha}])
    value=action('retry',job_id=jid,hypothesis='A different method name',evidence=[{'path':str(copied),'sha256':sha}])
    assert execute(studio,value)['status']=='held'
    with studio.store.connect() as db:
        assert db.execute('SELECT phase FROM supervision_jobs').fetchone()[0]=='held'


@pytest.mark.parametrize('kind',['collect_sources','repair_scenes'])
def test_new_media_cannot_release_authentication_hold(setup,kind):
    studio,_,root=setup;jid=failed(studio,status='paused');supervisor_hold(studio,jid)
    bind_failure_input(studio,jid)
    with studio.store.transaction() as db:
        cp=json.loads(db.execute('select checkpoint from jobs where id=?',(jid,)).fetchone()[0])
        cp['failure_classification']={'category':'access_blocked'}
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),jid))
    video=root/'new-source.mp4';video.write_bytes(b'new source actual bytes')
    sha=hashlib.sha256(video.read_bytes()).hexdigest()
    modify(studio,sources=[{'id':'new-source','path':str(video),'sha256':sha}])
    result=execute(studio,action(kind,held_job_id=jid,evidence=[{'path':str(video),'sha256':sha}]))
    assert result['status']=='held' and 'session recovery' in result['reason']
    with studio.store.connect() as db:
        assert db.execute('select phase from supervision_jobs where job_id=?',(jid,)).fetchone()[0]=='held'
        assert db.execute('select count(*) from jobs').fetchone()[0]==1


def approved_park(studio,status='queued',**binding_changes):
    checkpoint={'video_agent_input_fingerprint':'input-a','not_before':time.time()+600,'saved':'keep'}
    jid=failed(studio,status=status,checkpoint=checkpoint)
    from hotpost.video_agent_context import job_method_fingerprint
    signature=job_method_fingerprint({'kind':'edit','payload':{},'checkpoint':checkpoint})
    checkpoint['video_agent_job_fingerprint']=signature
    with studio.store.transaction() as db:db.execute('update jobs set checkpoint=? where id=?',(json.dumps(checkpoint),jid))
    receipt={'repair_id':'approved-repair','binding':{'task_id':'work-one','job_id':jid,
        'input_fingerprint':'input-a','job_fingerprint':signature,'agent_epoch':1,**binding_changes},
        'files':[{'repo':'insta_auto','path':'hotpost/worker.py','sha256':'tested'}],
        'review_binding_sha256':'signed-review'}
    studio.video_repair_pipeline=SimpleNamespace(ready_to_apply=lambda rid:receipt if rid=='approved-repair' else False)
    return jid,checkpoint,receipt


def test_park_exact_queued_approved_repair_preserves_cooldown_and_receipt(setup):
    studio,_,_=setup;jid,checkpoint,receipt=approved_park(studio)
    value=action('park_for_repair',job_id=jid,repair_id='approved-repair')
    result=execute(studio,value)
    assert result['status']=='completed' and result['parked']
    assert execute(studio,value)==result
    with studio.store.connect() as db:
        row=db.execute('SELECT status,checkpoint,error FROM jobs WHERE id=?',(jid,)).fetchone()
    saved=json.loads(row['checkpoint'])
    assert row['status']=='paused' and row['error']=='saved failure'
    assert all(saved[k]==v for k,v in checkpoint.items())
    assert saved['video_agent_parked_repair']=='approved-repair'
    assert saved['video_agent_park_receipt']['repair']==receipt


@pytest.mark.parametrize('changes',[{'task_id':'other'},{'job_id':'other'},
    {'input_fingerprint':'stale'},{'agent_epoch':2}])
def test_park_requires_every_signed_binding_field(setup,changes):
    studio,_,_=setup;jid,_,_=approved_park(studio,**changes)
    assert execute(studio,action('park_for_repair',job_id=jid,repair_id='approved-repair'))['status']=='held'
    assert studio.store.jobs('work-one')[0]['status']=='queued'


def test_park_rejects_approval_bound_to_old_task_input(setup):
    studio,_,_=setup;jid,_,_=approved_park(studio)
    modify(studio,semantic='input-new')
    result=execute(studio,action('park_for_repair',job_id=jid,repair_id='approved-repair'),fingerprint='input-new')
    assert result['status']=='held' and studio.store.jobs('work-one')[0]['status']=='queued'


@pytest.mark.parametrize('status',['running','paused','failed'])
def test_park_never_changes_running_or_nonqueued_job(setup,status):
    studio,_,_=setup;jid,_,_=approved_park(studio,status=status)
    assert execute(studio,action('park_for_repair',job_id=jid,repair_id='approved-repair'))['status']=='held'
    assert studio.store.jobs('work-one')[0]['status']==status


def test_unsigned_repair_or_access_hold_cannot_park(setup):
    studio,_,_=setup;jid,_,_=approved_park(studio)
    assert execute(studio,action('park_for_repair',job_id=jid,repair_id='unreviewed'))['status']=='held'
    modify(studio,source_acquisition={'hold':{'reason':'captcha_review_pending'}})
    assert execute(studio,action('park_for_repair',job_id=jid,repair_id='approved-repair'))['status']=='held'
    assert studio.store.jobs('work-one')[0]['status']=='queued'


def test_parked_job_resumes_only_with_matching_verified_loaded_repair(setup,monkeypatch):
    studio,_,_=setup;jid,_,receipt=approved_park(studio)
    assert execute(studio,action('park_for_repair',job_id=jid,repair_id='approved-repair'))['parked']
    from hotpost import video_agent_repairs
    monkeypatch.setattr(video_agent_repairs,'verified_repair',lambda *args:receipt)
    value=action('retry_repaired',job_id=jid,repair_id='approved-repair')
    assert execute(studio,value,decision='retry-before-cooldown')['status']=='held'
    with studio.store.transaction() as db:
        checkpoint=json.loads(db.execute('SELECT checkpoint FROM jobs WHERE id=?',(jid,)).fetchone()[0])
        checkpoint['not_before']=0
        db.execute('UPDATE jobs SET checkpoint=? WHERE id=?',(json.dumps(checkpoint),jid))
    assert execute(studio,{**value,'repair_id':'wrong-repair'},decision='retry-wrong')['status']=='held'
    assert execute(studio,value,decision='retry-valid')['status']=='queued'


@pytest.mark.parametrize('damage',[None,'binding','parking_receipt','user_pause'])
def test_new_loaded_repair_can_resume_original_host_park_only_for_same_inputs(setup,monkeypatch,damage):
    studio,_,_=setup;jid,_,receipt=approved_park(studio)
    assert execute(studio,action('park_for_repair',job_id=jid,repair_id='approved-repair'))['parked']
    from hotpost import video_agent_repairs
    replacement={**receipt,'repair_id':'new-repair','binding':dict(receipt['binding'])}
    if damage=='binding':replacement['binding']['agent_epoch']=2
    monkeypatch.setattr(video_agent_repairs,'verified_repair',lambda *args:replacement)
    with studio.store.transaction() as db:
        checkpoint=json.loads(db.execute('select checkpoint from jobs where id=?',(jid,)).fetchone()[0])
        checkpoint['not_before']=0
        if damage=='parking_receipt':checkpoint['video_agent_park_receipt']['decision_id']='invented'
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(checkpoint),jid))
    if damage=='user_pause':modify(studio,automation={'active':False,'paused_by_user':True})
    result=execute(studio,action('retry_repaired',job_id=jid,repair_id='new-repair'),decision='new-retry')
    assert result['status']==('queued' if damage is None else 'held')
