"""Exercise the queue against the historical fingerprint/accepted retry incident."""
import copy
import json
from pathlib import Path

import pytest

from test_video_agent_planning_claim import install
from hotpost.video_agent_actions import _hash
from hotpost.video_agent_context import job_method_fingerprint, _job_method_fingerprint, semantic_fingerprint


def accepted(tmp_path):
    store,state,parent,child=install(tmp_path)
    cp=json.loads(parent['checkpoint'])
    cp['source_access_preflight']={'at':10,'observations':[{'observed_at':9,'status':'exhausted','scope':'original'}]}
    parent['checkpoint']=json.dumps(cp)
    legacy=_job_method_fingerprint(parent,normalize_preflight=False)
    assert legacy!=job_method_fingerprint(parent)
    binding={'task_id':state['id'],'job_id':child['id'],'agent_epoch':1,
        'input_fingerprint':semantic_fingerprint(state)}
    evidence=[{'repair':{'binding':binding,'files':[{'path':'reviewed.py','sha256':'sha'}],
        'review_binding_sha256':'review'}}]
    recovery={'decision_id':'retry','method_key':'retry-key','changed_input':True,'evidence':evidence,'at':20}
    child.update(checkpoint=json.dumps({'_claim_token':'old-claim','_claim_started_at':15,
        'failure_trace':{'type':'PreparationEvidenceWaiting'},'video_agent_recoveries':[recovery],
        'video_agent_retry_admission':{'decision_id':'retry','method_key':'retry-key'}}),updated=21)
    receipt={'status':'queued','job_ids':[child['id']],'method_key':'retry-key','evidence':evidence}
    with store.transaction() as db:
        db.execute('update jobs set checkpoint=? where id=?',(parent['checkpoint'],parent['id']))
        saved=json.loads(db.execute("select result from video_agent_action_receipts where decision_id='continue'").fetchone()[0])
        repair=saved['evidence'][0]['repair'];repair['binding']['job_fingerprint']=legacy
        key=_hash({'kind':'continue_repaired','binding':repair['binding'],'files':repair['files']})
        saved['method_key']=key
        db.execute('update video_agent_action_receipts set result=?,method_key=? where decision_id=?',
            (json.dumps(saved),key,'continue'))
        db.execute('update jobs set checkpoint=?,updated=? where id=?',(child['checkpoint'],child['updated'],child['id']))
        db.execute('insert into video_agent_action_receipts values(?,?,?,?,?,?)',
            (state['id'],'retry','action','retry-key',json.dumps(receipt),22))
        db.execute('insert into events values(?,?,?,?,?)',
            (10,state['id'],'video_agent_action',json.dumps({'decision_id':'retry','kind':'retry_repaired',**receipt}),23))
    return store,state,parent,child


def test_legacy_parent_and_accepted_unclaimed_retry_enter_same_child_without_history_changes(tmp_path):
    store,state,parent,child=accepted(tmp_path)
    with store.connect() as db:
        receipts=[dict(r) for r in db.execute('select * from video_agent_action_receipts')]
    claim=store.claim(task_id=state['id'],lane='sources')
    assert claim and claim['id']==child['id'] and claim['claim_token']!='old-claim'
    assert store.get(state['id'])['source_acquisition']==state['source_acquisition']
    with store.connect() as db:
        assert dict(db.execute('select * from jobs where id=?',(parent['id'],)).fetchone())==parent
        assert [dict(r) for r in db.execute('select * from video_agent_action_receipts')]==receipts
        assert db.execute('select count(*) from jobs').fetchone()[0]==2


@pytest.mark.parametrize('damage',['parent_content','receipt_method','epoch','input','run','user_pause','login',
    'receipt_wait','new_claim_same_clock','new_claim_back_clock','deferred','explicit_pause','failed','finished',
    'stopped','supervision','updated_after_receipt','missing_action','wrong_action','wrong_evidence','old_claim',
    'infinite_time','error','wrong_admission','new_park_same_clock','new_park_back_clock'])
def test_compatibility_never_restores_an_ambiguous_or_new_attempt(tmp_path,damage):
    store,state,parent,child=accepted(tmp_path)
    cp=json.loads(child['checkpoint'])
    with store.transaction() as db:
        if damage=='parent_content':
            original=json.loads(parent['checkpoint']);original['source_access_preflight']['observations'][0]['scope']='different'
            db.execute('update jobs set checkpoint=? where id=?',(json.dumps(original),parent['id']))
        elif damage=='receipt_method':db.execute("update video_agent_action_receipts set method_key='tampered' where decision_id='continue'")
        elif damage=='epoch':db.execute('update video_agents set epoch=2')
        elif damage in {'input','run','user_pause','login','receipt_wait'}:
            if damage=='input':state['original_text']='different'
            if damage=='run':state['run_id']='new-run'
            if damage=='user_pause':state['automation']['paused_by_user']=True
            if damage=='login':state['source_acquisition']['waiting']={'reason':'login_required'}
            if damage=='receipt_wait':state['source_acquisition']['receipt_wait']={'reason':'unsettled'}
            db.execute('update tasks set state=?',(json.dumps(state),))
        elif damage in {'new_claim_same_clock','new_claim_back_clock','deferred','explicit_pause','failed','finished','stopped',
                'new_park_same_clock','new_park_back_clock'}:
            kind={'explicit_pause':'job_paused','failed':'failed','finished':'collect_sources_finished',
                'stopped':'source_collection_stopped'}.get(damage,'job_timing')
            detail={'job_id':child['id'],'outcome':'claimed' if damage.startswith('new_claim') else 'deferred'}
            if damage.startswith('new_park'):
                kind='video_agent_action';detail={'kind':'park_for_repair','parked':True,'status':'paused','job_ids':[child['id']]}
            db.execute('insert into events values(?,?,?,?,?)',(11,state['id'],kind,json.dumps(detail),1 if damage.endswith('back_clock') else 23))
        elif damage=='supervision':
            db.execute('create table supervision_jobs(job_id text,task_id text,phase text)')
            db.execute('insert into supervision_jobs values(?,?,?)',('other-job',state['id'],'held'))
        elif damage=='updated_after_receipt':db.execute('update jobs set updated=24 where id=?',(child['id'],))
        elif damage=='missing_action':db.execute('delete from events')
        elif damage in {'wrong_action','wrong_evidence'}:
            event=json.loads(db.execute('select detail from events').fetchone()[0])
            if damage=='wrong_action':event['kind']='retry'
            else:event['evidence']=[]
            db.execute('update events set detail=?',(json.dumps(event),))
        elif damage=='old_claim':cp['_claim_started_at']=20
        elif damage=='infinite_time':cp['_claim_started_at']=float('inf')
        elif damage=='error':db.execute("update jobs set error='new failure' where id=?",(child['id'],))
        elif damage=='wrong_admission':cp['video_agent_retry_admission']['decision_id']='foreign'
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),child['id']))
    assert store.claim(task_id=state['id'],lane='sources') is None
    with store.connect() as db:
        assert db.execute('select status from jobs where id=?',(child['id'],)).fetchone()[0]=='paused'


def test_parser_legacy_uses_its_original_time_normalization(tmp_path):
    _,_,parent,_=accepted(tmp_path)
    cp=json.loads(parent['checkpoint']);cp['parser_repair_context']={'at':30,'observations':[{'observed_at':29}]}
    parent['checkpoint']=json.dumps(cp)
    assert _job_method_fingerprint(parent,normalize_preflight=False)==job_method_fingerprint(parent)


def test_actual_captured_perfume_retry_claims_without_rewriting_preserved_receipts(tmp_path):
    path=Path(__file__).resolve().parents[1]/'data/agent-progress-repair-20261020/captured-perfume-retry-admission.json'
    if not path.exists():pytest.skip('Optional preserved local incident')
    incident=json.loads(path.read_text('utf8'));seed=copy.deepcopy(incident)
    seed['receipt']=seed['receipts'][0]
    store,state,parent,child=install(tmp_path,seed)
    with store.transaction() as db:
        db.execute('delete from video_agent_action_receipts')
        for table in ('video_agent_action_receipts','events'):
            for row in incident['receipts' if table=='video_agent_action_receipts' else 'events']:
                db.execute('insert into '+table+'('+','.join(row)+') values('+','.join('?' for _ in row)+')',tuple(row.values()))
    claim=store.claim(task_id=state['id'],lane='sources')
    assert claim and claim['id']==child['id']
    assert claim['claim_token']!=json.loads(child['checkpoint'])['_claim_token']
    assert store.get(state['id'])['source_acquisition']==state['source_acquisition']
    with store.connect() as db:
        assert dict(db.execute('select * from jobs where id=?',(parent['id'],)).fetchone())==parent
        actual={r['decision_id']:dict(r) for r in db.execute('select * from video_agent_action_receipts')}
        assert actual=={r['decision_id']:r for r in incident['receipts']}
