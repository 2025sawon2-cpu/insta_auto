"""Real preserved normal defer -> broad hold -> original child claim recovery.

The temporary database owns all mutations. Only the external artifact location
is bound to the preserved, read-only incident; internal validators remain real.
"""
import copy
import json
from pathlib import Path

import pytest

from test_video_agent_planning_claim import install
from hotpost import video_agent_source_wait as waits

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def preserved(tmp_path,monkeypatch):
    path=ROOT/'data/agent-progress-repair-20261020/captured-perfume-claimed-source-wait.json'
    if not path.exists():pytest.skip('Optional preserved local claimed-source-wait incident')
    incident=json.loads(path.read_text('utf8'));seed=copy.deepcopy(incident);seed['receipt']=seed['receipts'][0]
    store,state,parent,child=install(tmp_path,seed)
    with store.transaction() as db:
        db.execute('delete from video_agent_action_receipts')
        for table,key in [('video_agent_action_receipts','receipts'),('events','events')]:
            for row in incident[key]:
                db.execute('insert into '+table+'('+','.join(row)+') values('+','.join('?' for _ in row)+')',tuple(row.values()))
    monkeypatch.setattr(waits,'_evidence_root',lambda db:ROOT/'data')
    # Freeze the actual captured external recovery, so subsequent live searches
    # cannot change the preserved scenario while its temporary DB is tested.
    actual=waits._Files.read
    def saved_recovery(self,path,limit=4*1024*1024):
        if Path(path)==ROOT/'data/search_readiness/tiktok.json':
            path=ROOT/'data/agent-progress-repair-20261020/captured-parser-recovery-readiness.json'
        return actual(self,path,limit)
    monkeypatch.setattr(waits._Files,'read',saved_recovery)
    return store,state,parent,child,incident


def test_actual_normal_defer_reclaims_same_child_without_replaying_old_retry(preserved,monkeypatch):
    store,state,parent,child,incident=preserved
    with monkeypatch.context() as old:
        old.setattr(waits,'resolved_claimed_wait',lambda *args:None)
        assert store.claim(task_id=state['id'],lane='sources') is None
    before_state=copy.deepcopy(store.get(state['id']))
    with store.connect() as db:before=[dict(r) for r in db.execute('select * from video_agent_action_receipts')]
    claim=store.claim(task_id=state['id'],lane='sources')
    assert claim and claim['id']==child['id'] and claim['claim_token']!=json.loads(child['checkpoint'])['_claim_token']
    assert store.get(state['id'])['source_acquisition']==before_state['source_acquisition']
    with store.connect() as db:
        assert dict(db.execute('select * from jobs where id=?',(parent['id'],)).fetchone())==parent
        assert [dict(r) for r in db.execute('select * from video_agent_action_receipts')]==before
        assert db.execute('select count(*) from jobs').fetchone()[0]==2
    # A new actual failure consumes admission; enqueue cannot resurrect it.
    assert store.fail(claim,RuntimeError('new actual failure'))
    with store.transaction() as db:store.enqueue(db,state['id'],child['kind'],json.loads(child['payload']),child['key'])
    assert store.claim(task_id=state['id'],lane='sources') is None


@pytest.mark.parametrize('damage',['epoch','input','run','policy','voice','old_audit','old_plan','core_plan',
    'selected_owner','selected_sha','selected_policy','selected_scope','token','started','updated','cooldown',
    'deferred','error','receipt_method','receipt_evidence','recovery','missing_claim','wrong_wait',
    'new_claim','new_failure','new_pause','new_park','new_stop','supervision','user_pause','access','receipt_wait'])
def test_normal_wait_proof_cannot_authorize_changed_failed_or_ambiguous_work(preserved,damage):
    store,state,parent,child,incident=preserved;cp=json.loads(child['checkpoint'])
    with store.transaction() as db:
        if damage=='epoch':db.execute('update video_agents set epoch=2')
        elif damage in {'input','run','policy','voice','old_audit','old_plan','core_plan','user_pause','access','receipt_wait'}:
            if damage=='input':state['original_text']='different'
            if damage=='run':state['run_id']='foreign'
            if damage=='policy':state['source_policy']['version']=5
            if damage=='voice':state['approved_voice_id']='foreign'
            if damage=='old_audit':state['source_acquisition']['interrupted_attempts'][0]['foreign']=True
            if damage=='old_plan':state['source_acquisition']['core_search_plan']['context']['run_id']='foreign'
            if damage=='core_plan':state['source_acquisition']['core_search_plan']['queries']=['unverified']
            if damage=='user_pause':state['automation']['paused_by_user']=True
            if damage=='access':state['source_acquisition']['waiting']={'reason':'login_required'}
            if damage=='receipt_wait':state['source_acquisition']['receipt_wait']={'reason':'unsettled'}
            db.execute('update tasks set state=?',(json.dumps(state),))
        elif damage.startswith('selected_'):
            key={'selected_owner':'job_id','selected_sha':'sha256','selected_policy':'source_policy','selected_scope':'search_context'}[damage]
            cp['planning_preparation'][key]='foreign'
        elif damage=='token':cp['_claim_token']='foreign'
        elif damage=='started':cp['_claim_started_at']+=1
        elif damage=='updated':db.execute('update jobs set updated=updated+1 where id=?',(child['id'],))
        elif damage=='cooldown':cp['not_before']=10**20
        elif damage=='deferred':cp['deferred_wait']=False
        elif damage=='error':db.execute("update jobs set error='new failure' where id=?",(child['id'],))
        elif damage=='receipt_method':db.execute("update video_agent_action_receipts set method_key='foreign' where decision_id=?",(cp['video_agent_retry_admission']['decision_id'],))
        elif damage=='receipt_evidence':
            saved=json.loads(db.execute('select result from video_agent_action_receipts where decision_id=?',(cp['video_agent_retry_admission']['decision_id'],)).fetchone()[0]);saved['evidence']=[]
            db.execute('update video_agent_action_receipts set result=? where decision_id=?',(json.dumps(saved),cp['video_agent_retry_admission']['decision_id']))
        elif damage=='recovery':cp['video_agent_recoveries'][-1]['changed_input']=False
        elif damage=='missing_claim':db.execute("delete from events where kind='job_timing' and json_extract(detail,'$.outcome')='claimed'")
        elif damage=='wrong_wait':db.execute("update events set detail=json_set(detail,'$.wait_kind','retry_wait') where kind='job_timing' and json_extract(detail,'$.outcome')='deferred'")
        elif damage.startswith('new_'):
            kind={'new_claim':'job_timing','new_failure':'failed','new_pause':'job_paused','new_park':'video_agent_action','new_stop':'source_collection_stopped'}[damage]
            detail={'job_id':child['id'],'outcome':'claimed'}
            if damage=='new_park':detail={'kind':'park_for_repair','job_ids':[child['id']]}
            # Event IDs, not a conveniently old/repeated clock, are decisive.
            db.execute('insert into events(task_id,kind,detail,created) values(?,?,?,1)',(state['id'],kind,json.dumps(detail)))
        elif damage=='supervision':
            db.execute('create table supervision_jobs(job_id text,task_id text,phase text)')
            db.execute('insert into supervision_jobs values(?,?,?)',('other',state['id'],'held'))
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),child['id']))
    assert store.claim(task_id=state['id'],lane='sources') is None
    with store.connect() as db:assert db.execute('select status from jobs where id=?',(child['id'],)).fetchone()[0]=='paused'


@pytest.mark.parametrize('which',['fixture','bundle','reference','frame','receipt','manifest','readiness'])
def test_corrupted_external_evidence_is_rejected_by_real_byte_validators(preserved,monkeypatch,which):
    store,state,parent,child,incident=preserved;cp=json.loads(child['checkpoint'])
    tail=state['source_acquisition']['interrupted_attempts'][-1]
    bundle=json.loads(Path(cp['planning_preparation']['path']).read_text('utf8'))
    target={'bundle':Path(cp['planning_preparation']['path']),'reference':Path(state['reference_video']),
        'frame':Path(bundle['frames'][0]),'receipt':Path(tail['receipt_path']),
        'manifest':Path(tail['manifest_path']),'readiness':ROOT/'data/search_readiness/tiktok.json'}.get(which)
    actual=waits._Files.read
    def transport(self,path,limit=4*1024*1024):
        raw=actual(self,path,limit)
        if (which=='fixture' and str(path).replace('\\','/').endswith('/.repair-evidence/incident.json')) or Path(path)==target:
            return b'{}'
        return raw
    monkeypatch.setattr(waits._Files,'read',transport)
    assert store.claim(task_id=state['id'],lane='sources') is None


def test_file_budget_is_enforced_before_read_and_module_is_protected(tmp_path):
    from hotpost.video_agent_repairs import _PROTECTED
    assert 'video_agent_source_wait.py' in _PROTECTED
    oversized=tmp_path/'oversized.json'
    with oversized.open('wb') as stream:stream.truncate(4*1024*1024+1)
    with pytest.raises(ValueError,match='budget'):waits._Files(tmp_path).read(oversized)
    with pytest.raises(ValueError,match='foreign'):waits._Files(tmp_path).read(tmp_path.parent/'foreign')


def test_evidence_stamp_change_is_detected(tmp_path):
    p=tmp_path/'evidence.json';p.write_bytes(b'{}')
    files=waits._Files(tmp_path);files.read(p);p.write_bytes(b'{"changed":true}')
    assert not files.unchanged()


def test_wait_proof_never_enters_unbounded_media_hash_helpers(preserved,monkeypatch):
    from hotpost import source_quality
    store,state,parent,child,incident=preserved
    monkeypatch.setattr(source_quality,'sha256_file',lambda *a:pytest.fail('Unbounded nested media hash'))
    monkeypatch.setattr(Path,'read_bytes',lambda *a:pytest.fail('Unbounded nested read_bytes'))
    with store.connect() as db:
        row=db.execute('select * from jobs where id=?',(child['id'],)).fetchone()
        assert waits.resolved_claimed_wait(db,row,state,1) is not None


def test_coherently_changed_bundle_media_cannot_inherit_original_pixel_receipt(preserved,monkeypatch):
    import hashlib
    from hotpost.source_preparation import payload_key
    from hotpost.source_visual_queries import digest
    store,state,parent,child,incident=preserved;cp=json.loads(child['checkpoint'])
    path=Path(cp['planning_preparation']['path']);bundle=json.loads(path.read_text('utf8'))
    frame=Path(bundle['frames'][0]);new_pixels=b'changed pixel bytes'
    for row in bundle['files']:
        if Path(row['path'])==frame:row['sha256']=hashlib.sha256(new_pixels).hexdigest()
    bundle['payload_sha256']=payload_key(bundle)
    new_bundle=json.dumps(bundle,ensure_ascii=False).encode()
    cp['planning_preparation']['sha256']=hashlib.sha256(new_bundle).hexdigest()
    finite=state['source_acquisition']['core_search_plan']
    for i,name in enumerate(bundle['frames']):
        if Path(name)==frame:finite['frame_sha256'][i]=hashlib.sha256(new_pixels).hexdigest()
    finite['sha256']=digest({k:v for k,v in finite.items() if k not in {'sha256','excluded_routes'}})
    with store.transaction() as db:
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),child['id']))
        db.execute('update tasks set state=?',(json.dumps(state),))
    actual=waits._Files.read
    def transport(self,p,limit=4*1024*1024):
        raw=actual(self,p,limit)
        return new_bundle if Path(p)==path else new_pixels if Path(p)==frame else raw
    monkeypatch.setattr(waits._Files,'read',transport)
    assert store.claim(task_id=state['id'],lane='sources') is None


@pytest.mark.parametrize('damage',['previous','revision','status','time','submitted','media_approval'])
def test_saved_recovery_is_only_a_resolved_same_incident_wait(preserved,monkeypatch,damage):
    store,state,parent,child,incident=preserved
    actual=waits._Files.read
    def transport(self,path,limit=4*1024*1024):
        raw=actual(self,path,limit)
        if Path(path)==ROOT/'data/search_readiness/tiktok.json':
            value=json.loads(raw)
            if damage=='previous':value['previous_failure']={'foreign':True}
            if damage=='revision':value['parser_revision']='foreign'
            if damage=='status':value['recovery']['status']='unavailable'
            if damage=='time':value['recovery']['at']=1
            if damage=='submitted':value['recovery']['query_submitted']=True
            if damage=='media_approval':value['recovery']['grants_media_approval']=True
            return json.dumps(value).encode()
        return raw
    monkeypatch.setattr(waits._Files,'read',transport)
    assert store.claim(task_id=state['id'],lane='sources') is None
