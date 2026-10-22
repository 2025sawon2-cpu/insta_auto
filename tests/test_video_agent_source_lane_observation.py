"""A busy shared source worker is distinct from a failed queued task."""
import json
import pytest
from types import SimpleNamespace
from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.video_agent_context import source_lane_observation,snapshot


def test_other_task_collection_is_visible_without_its_content_or_authority(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    a,_=studio.store.create('waiting','Waiting',{},prepare=False)
    b,_=studio.store.create('busy','Private title',{},prepare=False)
    studio._threads=[SimpleNamespace(name='studio-sources',is_alive=lambda:True),
                     SimpleNamespace(name='studio-scripts',is_alive=lambda:True)]
    try:
        with studio.store.transaction() as db:
            queued=studio.store.enqueue(db,a['id'],'collect_sources',{},'waiting')
            active=studio.store.enqueue(db,b['id'],'collect_sources',{'secret':'not exposed'},'busy')
            db.execute("update jobs set status='running',checkpoint=? where id=?",
                       (json.dumps({'_claim_started_at':123,'secret':'not exposed'}),active))
            db.execute('update jobs set checkpoint=? where id=?',(json.dumps({'not_before':100}),queued))
        before=studio.store.get(a['id'])
        facts=snapshot(studio,a['id'])['source_lane_observation']
        assert facts['live_source_worker_count']==1 and facts['running_source_job_count']==1
        assert facts['running_source_jobs'][0]['id']==active
        assert facts['running_source_jobs'][0]['claim_started_at']==123
        assert facts['this_task_queued_source_jobs']==[{'id':queued,'kind':'collect_sources','not_before':100}]
        assert 'Private title' not in json.dumps(facts) and 'secret' not in json.dumps(facts)
        assert studio.store.get(a['id'])==before
        with studio.store.connect() as db:
            assert db.execute('select status from jobs where id=?',(queued,)).fetchone()[0]=='queued'
    finally:
        studio._threads=[];studio.close()


def test_missing_worker_or_stale_running_row_is_observation_not_health_verdict(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    a,_=studio.store.create('fixture','Fixture',{},prepare=False)
    try:
        with studio.store.transaction() as db:
            for n in range(10):
                job=studio.store.enqueue(db,a['id'],'refresh_sources',{},str(n))
                db.execute("update jobs set status='running' where id=?",(job,))
        with studio.store.connect() as db:facts=source_lane_observation(studio,db,a['id'])
        assert facts['live_source_worker_count']==0
        assert facts['running_source_job_count']==10 and len(facts['running_source_jobs'])==8
        assert facts['running_source_jobs_truncated'] is True
        assert facts['this_task_queued_source_jobs']==[]
        assert set(facts)=={'observed_at','live_source_worker_count','running_source_job_count',
            'running_source_jobs','running_source_jobs_truncated','this_task_queued_source_jobs','scope'}
    finally:studio.close()


def test_real_proposal_captures_shared_lane_in_incident_and_fixture_over_model_spoof(tmp_path):
    from test_preparation_query_diagnostics import captured
    from hotpost.video_agents import VideoAgentManager
    from hotpost.video_agent_context import semantic_fingerprint
    studio,state,*_=captured(tmp_path)
    foreign,_=studio.store.create('foreign','Private contents',{},prepare=False)
    studio._threads=[SimpleNamespace(name='studio-sources',is_alive=lambda:True)]
    with studio.store.transaction() as db:
        target=studio.store.enqueue(db,state['id'],'collect_sources',{'run_id':state['run_id']},'failure')
        active=studio.store.enqueue(db,foreign['id'],'collect_sources',{'private':'not copied'},'busy')
        db.execute("update jobs set status='failed' where id=?",(target,))
        db.execute("update jobs set status='running',checkpoint=? where id=?",(json.dumps({'_claim_started_at':321}),active))
    received=[]
    studio.video_repair_pipeline=SimpleNamespace(propose_patch=lambda patch:received.append(patch) or 'repair',
        repair_material=lambda *args:{'content_fingerprint':'new-code'})
    manager=VideoAgentManager(studio)
    try:
        result=manager.execute(state['id'],{'kind':'propose_patch','_agent_epoch':1,
            'patch':{'binding':{'job_id':target},'incident_fixture':{'source_lane_observation':'spoof'}}},
            'lane-observation',semantic_fingerprint(state))
        assert result['status']=='completed'
        patch=received[0];facts=patch['incident']['source_lane_observation']
        assert patch['incident_fixture']['source_lane_observation']==facts
        assert facts['live_source_worker_count']==1 and facts['running_source_jobs'][0]['id']==active
        assert facts['running_source_jobs'][0]['claim_started_at']==321
        assert 'spoof' not in json.dumps(facts) and 'private' not in json.dumps(facts)
        with studio.store.connect() as db:
            assert db.execute('select status from jobs where id=?',(active,)).fetchone()[0]=='running'
            assert db.execute('select status from jobs where id=?',(target,)).fetchone()[0]=='failed'
    finally:
        manager.pool.shutdown(wait=True);studio._threads=[];studio.close()


@pytest.mark.parametrize('variant',['occupied','missing_worker','missing_claim','two_running','media_job','no_running'])
def test_actual_owner_does_not_force_repair_for_proven_other_task_source_dependency(tmp_path,monkeypatch,variant):
    import time
    from hotpost.video_agents import VideoAgentManager,get_agent
    from hotpost.video_agent_context import queue_progress_fingerprint
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    current,_=studio.store.create('waiting','Waiting',{'active':True},prepare=False)
    foreign,_=studio.store.create('busy','Busy',{},prepare=False)
    studio._threads=[] if variant=='missing_worker' else [SimpleNamespace(name='studio-sources',is_alive=lambda:True)]
    manager=VideoAgentManager(studio);sent=[]
    manager.jobs=SimpleNamespace(create=lambda kind,payload,key:sent.append(payload) or {'id':'owner-model'},start=lambda:None)
    monkeypatch.setattr('hotpost.video_agents.repair_packet',lambda *a,**kw:[{'source':'current_code'}])
    try:
        with studio.store.transaction() as db:
            queued=studio.store.enqueue(db,current['id'],'collect_sources',{},'waiting')
            if variant!='no_running':
                active=studio.store.enqueue(db,foreign['id'],'collect_sources',{},'busy')
                cp={} if variant=='missing_claim' else {'_claim_started_at':time.time()-600}
                db.execute("update jobs set status='running',checkpoint=? where id=?",(json.dumps(cp),active))
                if variant=='two_running':
                    another=studio.store.enqueue(db,foreign['id'],'refresh_sources',{},'other')
                    db.execute("update jobs set status='running',checkpoint=? where id=?",(json.dumps(cp),another))
            if variant=='media_job':studio.store.enqueue(db,current['id'],'voice',{},'media')
            row=db.execute('select * from jobs where id=?',(queued,)).fetchone()
        signature=queue_progress_fingerprint(studio.store.get(current['id']),[row]);since=time.time()-600
        manager._save(current['id'],1,{'idle_decisions':16,'queue_observation':{'signature':signature,'since':since},
            'queue_observations':{signature:{'since':since}}})
        manager.step(current['id'])
        if variant!='no_running':
            assert not sent
            owner=get_agent(studio.store,current['id'])
            assert owner['status']=='waiting_turn' and owner['waiting_for_video']==foreign['id']
            return  # Another video's live work is never a license to diagnose this one in parallel.
        assert len(sent)==1
        occupied=variant=='occupied';evidence=sent[0]['evidence']
        assert evidence['source_lane_dependency_wait'] is occupied
        pending=get_agent(studio.store,current['id'])['pending']
        assert pending['dependency_wait'] is occupied
        assert pending['repair_execution'] is (not occupied)
        assert ('allowed_actions' in evidence) is (not occupied)
        with studio.store.connect() as db:
            assert db.execute('select status from jobs where id=?',(queued,)).fetchone()[0]=='queued'
    finally:
        manager.pool.shutdown(wait=True);studio._threads=[];studio.close()


@pytest.mark.parametrize('checkpoint',['{bad json',json.dumps({'_claim_started_at':{'secret':'x'*10000}}),
    json.dumps({'_claim_started_at':'secret'*10000}),'{"_claim_started_at":1e999}',
    '{"_claim_started_at":true}','{"_claim_started_at":-1}'],
    ids=['malformed','object','string','infinite','boolean','negative'])
def test_foreign_bad_checkpoint_cannot_break_snapshot_or_disclose_content(tmp_path,checkpoint):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    a,_=studio.store.create('local','Local',{},prepare=False)
    b,_=studio.store.create('foreign','Foreign',{},prepare=False)
    try:
        with studio.store.transaction() as db:
            job=studio.store.enqueue(db,b['id'],'collect_sources',{},'foreign')
            db.execute("update jobs set status='running',checkpoint=? where id=?",(checkpoint,job))
        facts=snapshot(studio,a['id'])['source_lane_observation']
        assert facts['running_source_jobs'][0]['claim_started_at'] is None
        assert 'secret' not in json.dumps(facts) and len(json.dumps(facts))<2000
    finally:studio.close()
