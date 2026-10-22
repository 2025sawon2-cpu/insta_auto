import copy
import json
import os
from pathlib import Path

import pytest

from hotpost.studio_store import StudioStore
from hotpost.video_agent_actions import _hash
from hotpost.video_agent_context import semantic_fingerprint,job_method_fingerprint


def install(tmp_path, incident=None):
    store=StudioStore(tmp_path/'studio')
    if incident:
        task=copy.deepcopy(incident['task']);state=json.loads(task['state'])
        parent,child=copy.deepcopy(incident['jobs']);owner=copy.deepcopy(incident['owner']);receipt=copy.deepcopy(incident['receipt'])
    else:
        state={'id':'work-test','shortcode':'test','status':'source_wait','run_id':'run-test','revision':0,'script_id':None,
            'automation':{'active':True,'protocol':2},'source_policy':{'version':6},
            'source_goal':{'ready':False},'source_search_manifest_path':'preserved.json',
            'source_acquisition':{'round':7,'hold':{'reason':'strategy_exhausted'},
                'rounds':[{'job_id':'job-parent','round':6,'run_id':'run-test','manifest_path':'preserved.json'}]}}
        task={'id':state['id'],'shortcode':'test','revision':0,'state':json.dumps(state),'updated':1}
        parent={'id':'job-parent','task_id':state['id'],'kind':'collect_sources','key':'old',
            'payload':json.dumps({'round':6,'run_id':'run-test'}),'status':'done',
            'checkpoint':json.dumps({'manifest':'preserved.json'}),'error':'','created':1,'updated':2}
        child={**parent,'id':'job-child','key':'source-plan-recovery:run-test:job-parent',
            'payload':json.dumps({'round':7,'run_id':'run-test','source_policy':state['source_policy'],
                'planning_recovery_from':'job-parent'}),'checkpoint':'{}','status':'paused','created':3,'updated':3}
        owner={'task_id':state['id'],'epoch':1,'record':'{}','updated':3}
        binding={'task_id':state['id'],'job_id':parent['id'],'agent_epoch':1,
            'input_fingerprint':semantic_fingerprint(state),'job_fingerprint':job_method_fingerprint(parent)}
        files=[{'repo':'main','path':'hotpost/source_finder.py','sha256':'reviewed-source-sha'}]
        key=_hash({'kind':'continue_repaired','binding':binding,'files':files})
        result={'status':'queued','job_ids':[child['id']],'method_key':key,
            'evidence':[{'repair':{'binding':binding,'files':files,'review_binding_sha256':'review-binding'}}]}
        receipt={'task_id':state['id'],'decision_id':'continue','action_sha':'host-action','method_key':key,
                 'result':json.dumps(result),'created':3}
    with store.transaction() as db:
        db.execute('CREATE TABLE video_agents(task_id TEXT PRIMARY KEY,epoch INTEGER,record TEXT,updated REAL)')
        db.execute('CREATE TABLE video_agent_action_receipts(task_id TEXT,decision_id TEXT,action_sha TEXT,method_key TEXT,result TEXT,created REAL)')
        for table,rows in [('tasks',[task]),('jobs',[parent,child]),('video_agents',[owner]),('video_agent_action_receipts',[receipt])]:
            for row in rows:
                db.execute('INSERT INTO '+table+'('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
    return store,state,parent,child


def test_verified_recovery_survives_hold_pause_and_reclaims_same_never_started_child(tmp_path):
    store,state,parent,child=install(tmp_path)
    claim=store.claim(task_id=state['id'],lane='sources')
    assert claim and claim['id']==child['id'] and claim['claim_token']
    assert store.get(state['id'])['source_acquisition']==state['source_acquisition']
    with store.connect() as db:assert dict(db.execute('select * from jobs where id=?',(parent['id'],)).fetchone())==parent
    assert store.claim(task_id=state['id'],lane='sources') is None
    store.defer(claim,'Local preparation service still starting',1,waiting=True)
    assert store.claim(task_id=state['id'],lane='sources') is None
    with store.transaction() as db:
        cp=dict(claim['checkpoint']);cp['not_before']=0
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),child['id']))
    resumed=store.claim(task_id=state['id'],lane='sources')
    assert resumed and resumed['id']==child['id'] and resumed['claim_token']!=claim['claim_token']
    with store.connect() as db:assert not store.owns(db,claim)


def test_unclassified_first_failure_cannot_reuse_original_continuation(tmp_path):
    store,state,parent,child=install(tmp_path)
    claim=store.claim(task_id=state['id'],lane='sources')
    assert claim and 'failure_classification' not in claim['checkpoint']
    assert store.fail(claim,RuntimeError('first failure without classifier'))
    with store.transaction() as db:
        cp=json.loads(db.execute('select checkpoint from jobs where id=?',(child['id'],)).fetchone()[0])
        assert 'failure_trace' in cp and 'failure_classification' not in cp
        store.enqueue(db,state['id'],'collect_sources',json.loads(child['payload']),child['key'])
    assert store.claim(task_id=state['id'],lane='sources') is None


@pytest.mark.parametrize('defect',['no_receipt','wrong_method','foreign_child','epoch','semantic','parent_checkpoint',
    'user_pause','consumed','inactive','completed','captcha','login_wait','receipt_wait','wrong_run','wrong_round',
    'wrong_policy','wrong_parent','prior_claim','explicit_pause','prior_failure','supervisor_hold'])
def test_planning_claim_cannot_resurrect_unowned_or_user_access_held_work(tmp_path,defect):
    store,state,parent,child=install(tmp_path)
    with store.transaction() as db:
        if defect=='no_receipt':db.execute('delete from video_agent_action_receipts')
        elif defect=='wrong_method':db.execute("update video_agent_action_receipts set method_key='wrong'")
        elif defect=='foreign_child':
            row=db.execute('select result from video_agent_action_receipts').fetchone();r=json.loads(row['result']);r['job_ids']=['foreign']
            db.execute('update video_agent_action_receipts set result=?',(json.dumps(r),))
        elif defect=='epoch':db.execute('update video_agents set epoch=2')
        elif defect=='parent_checkpoint':db.execute("update jobs set checkpoint='{}' where id=?",(parent['id'],))
        elif defect in {'wrong_run','wrong_round','wrong_policy','wrong_parent'}:
            payload=json.loads(child['payload']);field={'wrong_run':'run_id','wrong_round':'round','wrong_policy':'source_policy','wrong_parent':'planning_recovery_from'}[defect]
            payload[field]='wrong';db.execute('update jobs set payload=? where id=?',(json.dumps(payload),child['id']))
        elif defect=='prior_claim':db.execute('update jobs set checkpoint=? where id=?',(json.dumps({'_claim_token':'prior'}),child['id']))
        elif defect=='explicit_pause':db.execute('update jobs set updated=4 where id=?',(child['id'],))
        elif defect=='prior_failure':db.execute("update jobs set error='prior failure' where id=?",(child['id'],))
        elif defect=='supervisor_hold':
            db.execute('create table supervision_runtime(id integer)')
        else:
            if defect=='semantic':state['original_text']='changed'
            elif defect=='user_pause':state['automation']['paused_by_user']=True
            elif defect=='consumed':state['automation']['consumed_by_daily_policy']=True
            elif defect=='inactive':state['automation']['active']=False
            elif defect=='completed':state['status']='completed'
            elif defect=='captcha':state['source_acquisition']['hold']={'reason':'captcha'}
            elif defect=='login_wait':state['source_acquisition']['waiting']={'reason':'login_required'}
            elif defect=='receipt_wait':state['source_acquisition']['receipt_wait']={'reason':'unsettled'}
            db.execute('update tasks set state=?',(json.dumps(state),))
    assert store.claim(task_id=state['id'],lane='sources') is None
    with store.connect() as db:assert db.execute('select status from jobs where id=?',(child['id'],)).fetchone()[0]=='paused'


def test_captured_perfume_paused_child_enters_real_claim_without_rewriting_hold(tmp_path,monkeypatch):
    path=os.environ.get('HOTPOST_PLANNING_CLAIM_INCIDENT')
    if not path:pytest.skip('Optional local preserved incident')
    incident=json.loads(Path(path).read_text('utf8'))
    store,state,parent,child=install(tmp_path,incident)
    assert child['status']=='paused' and child['checkpoint']=='{}' and child['created']==child['updated']
    # Reproduce the deployed pre-fix queue path with its unconditional hold pause.
    with monkeypatch.context() as old:
        old.setattr('hotpost.video_agent_planning_claim.admitted_planning_children',lambda db:set())
        assert store.claim(task_id=state['id'],lane='sources') is None
    claim=store.claim(task_id=state['id'],lane='sources')
    assert claim and claim['id']==child['id']
    assert store.get(state['id'])['source_acquisition']==state['source_acquisition']
    with store.connect() as db:
        assert dict(db.execute('select * from jobs where id=?',(parent['id'],)).fetchone())==parent
        assert dict(db.execute('select * from video_agent_action_receipts').fetchone())==incident['receipt']


@pytest.mark.parametrize('captured',[False,True])
def test_failure_inside_planning_recovery_requires_fresh_repair_then_same_child_claim(tmp_path,monkeypatch,captured):
    from types import SimpleNamespace
    from hotpost import video_agent_actions as actions
    incident=None
    if captured:
        path=os.environ.get('HOTPOST_PLANNING_CHILD_FAILURE')
        if not path:pytest.skip('Optional local failed planning-child incident')
        incident=json.loads(Path(path).read_text('utf8'))
    store,state,parent,child=install(tmp_path,incident)
    if not captured:
        state['source_acquisition']['interrupted_attempts']=[{'error':'new storage failure','job_id':child['id']}]
        with store.transaction() as db:
            db.execute('update tasks set state=?',(json.dumps(state),))
            db.execute("update jobs set status='failed',checkpoint=?,error='storage failure' where id=?",
                (json.dumps({'failure_classification':{'category':'storage','retryable':False}}),child['id']))
    with store.connect() as db:failed=dict(db.execute('select * from jobs where id=?',(child['id'],)).fetchone())
    assert failed['status']=='failed'
    fingerprint=semantic_fingerprint(state)
    with pytest.raises(actions.ActionHeld):actions._gate(state,'retry',failed)
    actions._gate(state,'retry_repaired',failed)
    studio=SimpleNamespace(store=store,settings=SimpleNamespace(data_dir=tmp_path))
    available=actions.capabilities(studio,state)
    assert 'retry_repaired' in available and 'retry' not in available
    action={'kind':'retry_repaired','job_id':child['id'],'repair_id':'repair-fresh','_agent_epoch':1,
            'hypothesis':'Repair the new storage failure without clearing the original planning hold','evidence':[]}
    monkeypatch.setattr('hotpost.video_agent_repairs.verified_repair',lambda *args:None)
    assert actions.execute(studio,state['id'],action,'unverified',fingerprint)['status']=='held'
    # Isolate the already-covered signed/loaded repair verifier. Exercise the
    # actual executor, durable recovery receipt, broad pause gate and claim.
    verified={'repair_id':'repair-fresh','binding':{'task_id':state['id'],'job_id':child['id'],
        'agent_epoch':1,'input_fingerprint':fingerprint,'job_fingerprint':job_method_fingerprint(failed)},
        'files':[{'repo':'main','path':'hotpost/source_visual_queries.py','sha256':'new-reviewed-sha'}],
        'review_binding_sha256':'new-reviewed-binding'}
    monkeypatch.setattr('hotpost.video_agent_repairs.verified_repair',lambda *args:verified)
    result=actions.execute(studio,state['id'],action,'verified-retry',fingerprint)
    assert result['status']=='queued' and result['job_ids']==[child['id']]
    claim=store.claim(task_id=state['id'],lane='sources')
    assert claim and claim['id']==child['id']
    assert store.get(state['id'])['source_acquisition']==state['source_acquisition']
    with store.connect() as db:assert dict(db.execute('select * from jobs where id=?',(parent['id'],)).fetchone())==parent


    # Service waits preserve this attempt's admission, but another actual
    # failure consumes it even if the semantic input has not changed.
    store.defer(claim,'Prepare service wait',0,waiting=True)
    resumed=store.claim(task_id=state['id'],lane='sources')
    assert resumed and resumed['id']==child['id']
    assert store.fail(resumed,FileNotFoundError('same storage defect remains'))
    with store.transaction() as db:
        assert 'video_agent_retry_admission' not in json.loads(db.execute('select checkpoint from jobs where id=?',(child['id'],)).fetchone()[0])
        store.enqueue(db,state['id'],'collect_sources',json.loads(child['payload']),child['key'])
    assert store.claim(task_id=state['id'],lane='sources') is None


@pytest.mark.parametrize('damage',['no_current_repair','checkpoint_only','foreign_epoch','old_input','different_child','mismatched_evidence'])
def test_old_continuation_does_not_authorize_a_new_failed_child_attempt(tmp_path,damage):
    store,state,parent,child=install(tmp_path)
    state['source_acquisition']['interrupted_attempts']=[{'job_id':child['id'],'error':'storage'}]
    binding={'task_id':state['id'],'job_id':child['id'],'agent_epoch':1,'input_fingerprint':semantic_fingerprint(state)}
    evidence=[{'repair':{'binding':binding,'files':[{'path':'new.py'}],'review_binding_sha256':'review'}}]
    cp={'failure_classification':{'category':'storage'},'video_agent_recoveries':[{
        'decision_id':'new-repair','method_key':'retry-key','changed_input':True,'evidence':copy.deepcopy(evidence)}]}
    cp['video_agent_retry_admission']={'decision_id':'new-repair','method_key':'retry-key'}
    if damage=='no_current_repair':cp.pop('video_agent_recoveries')
    if damage=='foreign_epoch':binding['agent_epoch']=2
    if damage=='old_input':binding['input_fingerprint']='old'
    result={'status':'queued','job_ids':[child['id']],'method_key':'retry-key','evidence':evidence}
    if damage=='different_child':result['job_ids']=['other-child']
    if damage!='mismatched_evidence' and cp.get('video_agent_recoveries'):
        cp['video_agent_recoveries'][0]['evidence']=copy.deepcopy(evidence)
    if damage=='mismatched_evidence':result['evidence']=[]
    with store.transaction() as db:
        db.execute('update tasks set state=?',(json.dumps(state),))
        db.execute("update jobs set status='queued',checkpoint=? where id=?",(json.dumps(cp),child['id']))
        if damage!='checkpoint_only':db.execute('insert into video_agent_action_receipts values(?,?,?,?,?,?)',
            (state['id'],'new-repair','action','retry-key',json.dumps(result),4))
    assert store.claim(task_id=state['id'],lane='sources') is None


import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from hotpost import video_agent_actions as actions
from hotpost.video_agent_context import semantic_fingerprint,job_method_fingerprint
from hotpost.video_agent_planning_claim import internal_wait_parking_proof


def waiting(tmp_path,captured=False):
    incident=None
    if captured:
        path=os.environ.get('HOTPOST_PAUSED_PLANNING_CHILD')
        if not path:pytest.skip('Optional captured current internal-wait child')
        incident=json.loads(Path(path).read_text('utf8'))
    store,state,parent,child=install(tmp_path,incident)
    if captured:
        with store.transaction() as db:
            for event in incident['events']:
                db.execute('insert into events(id,task_id,kind,detail,created) values(?,?,?,?,?)',
                    (event['id'],event['task_id'],event['kind'],event['detail'],event['created']))
    else:
        job=store.claim(task_id=state['id'],lane='sources');assert job
        job['checkpoint'].update(internal_evidence_wait=True,
            failure_trace={'type':'PreparationEvidenceWaiting','stage':'collect_sources','message':'insufficient approved plan'})
        state['source_acquisition']['internal_error']='insufficient independently reviewed plan'
        with store.transaction() as db:db.execute('update tasks set state=?',(json.dumps(state),))
        store.defer(job,'insufficient approved plan',0,waiting=False)
        with store.transaction() as db:store.pause_queued(db)
    with store.connect() as db:
        child=dict(db.execute('select * from jobs where id=?',(child['id'],)).fetchone())
        assert child['status']=='paused'
        assert internal_wait_parking_proof(db,state,child)
    return store,state,parent,child


@pytest.mark.parametrize('captured',[False,True])
def test_internal_wait_uses_fresh_reviewed_parking_and_verified_retry_of_same_child(tmp_path,monkeypatch,captured):
    store,state,parent,child=waiting(tmp_path,captured)
    before=copy.deepcopy(state['source_acquisition'])
    fingerprint=semantic_fingerprint(state);signature=job_method_fingerprint(child)
    cp=json.loads(child['checkpoint']);cp.update(video_agent_input_fingerprint=fingerprint,video_agent_job_fingerprint=signature)
    with store.transaction() as db:db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),child['id']))
    receipt={'repair_id':'repair-new-wait','binding':{'task_id':state['id'],'job_id':child['id'],
        'agent_epoch':1,'input_fingerprint':fingerprint,'job_fingerprint':signature},
        'files':[{'repo':'main','path':'hotpost/source_visual_queries.py','sha256':'fresh-tested-source'}],
        'review_binding_sha256':'fresh-independent-review'}
    studio=SimpleNamespace(store=store,settings=SimpleNamespace(data_dir=tmp_path),
        video_repair_pipeline=SimpleNamespace(ready_to_apply=lambda rid:copy.deepcopy(receipt)))
    action={'kind':'park_for_repair','job_id':child['id'],'repair_id':receipt['repair_id'],
        '_agent_epoch':1,'hypothesis':'Repair original internal preparation wait','evidence':[]}
    with monkeypatch.context() as old:
        old.setattr('hotpost.video_agent_planning_claim.internal_wait_parking_proof',lambda *a:None)
        assert actions.execute(studio,state['id'],action,'old-entry',fingerprint)['status']=='held'
    studio.video_repair_pipeline.ready_to_apply=lambda rid:False
    assert actions.execute(studio,state['id'],action,'no-review',fingerprint)['status']=='held'
    studio.video_repair_pipeline.ready_to_apply=lambda rid:copy.deepcopy(receipt)
    result=actions.execute(studio,state['id'],action,'fresh-park',fingerprint)
    assert result['parked'] is True and result['job_ids']==[child['id']]
    assert store.claim(task_id=state['id'],lane='sources') is None
    retry={**action,'kind':'retry_repaired'}
    monkeypatch.setattr('hotpost.video_agent_repairs.verified_repair',lambda *a:None)
    assert actions.execute(studio,state['id'],retry,'no-loaded-proof',fingerprint)['status']=='held'
    # Real signed/load verifier is covered by pipeline tests; here exercise the
    # normal executor, action receipt, retained hold and atomic same-child claim.
    monkeypatch.setattr('hotpost.video_agent_repairs.verified_repair',lambda *a:copy.deepcopy(receipt))
    result=actions.execute(studio,state['id'],retry,'fresh-retry',fingerprint)
    assert result['status']=='queued' and result['job_ids']==[child['id']]
    claim=store.claim(task_id=state['id'],lane='sources')
    assert claim and claim['id']==child['id'] and claim['claim_token']!=cp['_claim_token']
    assert store.get(state['id'])['source_acquisition']==before
    with store.connect() as db:
        assert dict(db.execute('select * from jobs where id=?',(parent['id'],)).fetchone())==parent
        assert db.execute('select count(*) from jobs').fetchone()[0]==2


@pytest.mark.parametrize('fault',['user_pause','inactive','captcha','login','qa','wrong_run','missing_trace',
    'other_failure','service_wait','not_internal','future_wait','different_updated','different_claim',
    'different_start','different_due','explicit_pause','paused_timing','missing_timing','infinite_time'])
def test_ambiguous_or_explicit_pauses_never_get_internal_parking_proof(tmp_path,fault):
    store,state,parent,child=waiting(tmp_path)
    cp=json.loads(child['checkpoint'])
    with store.transaction() as db:
        if fault=='user_pause':state['automation']['paused_by_user']=True
        elif fault=='inactive':state['automation']['active']=False
        elif fault=='captcha':state['source_acquisition']['hold']={'reason':'captcha'}
        elif fault=='login':state['source_acquisition']['waiting']={'searches':[{'provider':'tiktok','reason':'login_required'}]}
        elif fault=='qa':state['daily_quality']={'pending':'scene_wait'}
        elif fault=='wrong_run':state['run_id']='different'
        elif fault=='missing_trace':cp.pop('failure_trace')
        elif fault=='other_failure':cp['failure_trace']['type']='RuntimeError'
        elif fault=='service_wait':cp['deferred_wait']=True
        elif fault=='not_internal':cp['internal_evidence_wait']=False
        elif fault=='future_wait':cp['not_before']=99999999999
        elif fault=='different_updated':child['updated']+=1
        elif fault=='different_claim':cp['_claim_token']='other'
        elif fault=='different_start':cp['_claim_started_at']+=1
        elif fault=='different_due':cp['not_before']-=1
        elif fault=='infinite_time':cp['_claim_started_at']=float('inf')
        elif fault=='explicit_pause':store.event(db,state['id'],'job_paused',{'job_id':child['id']})
        elif fault=='paused_timing':store.event(db,state['id'],'job_timing',{'job_id':child['id'],'outcome':'paused'})
        elif fault=='missing_timing':db.execute("delete from events where kind='job_timing'")
        child['checkpoint']=json.dumps(cp)
        assert internal_wait_parking_proof(db,state,child) is None
    with store.connect() as db:
        assert db.execute('select status from jobs where id=?',(child['id'],)).fetchone()[0]=='paused'


def test_defer_timestamp_uses_exact_persisted_timing_even_with_distinct_clock_calls(tmp_path,monkeypatch):
    store,state,parent,child=install(tmp_path)
    job=store.claim(task_id=state['id'],lane='sources')
    clock=iter(range(10000,10100));monkeypatch.setattr('hotpost.studio_store.time.time',lambda:next(clock))
    store.defer(job,'internal wait',0,waiting=False)
    with store.connect() as db:
        row=db.execute('select updated from jobs where id=?',(child['id'],)).fetchone()
        timing=json.loads(db.execute("select detail from events where kind='job_timing' order by id desc limit 1").fetchone()[0])
        assert row['updated']==timing['observed_at']
