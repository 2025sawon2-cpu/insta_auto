import copy
import json
from types import SimpleNamespace

import pytest

from hotpost.studio import Studio
from hotpost.config import Settings
from hotpost.video_agents import VideoAgentManager,get_agent
from hotpost.video_agent_context import semantic_fingerprint,job_method_fingerprint
from hotpost.video_agent_runtime import resume_loaded_repairs
from hotpost import video_agent_actions as actions,video_agent_repairs as repairs


def parked(tmp_path,monkeypatch):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('loaded','Loaded',{'active':True},prepare=False)
    fp=semantic_fingerprint(state)
    signature=job_method_fingerprint({'kind':'collect_sources','payload':{},'checkpoint':{}})
    with studio.store.transaction() as db:
        jid=studio.store.enqueue(db,state['id'],'collect_sources',{},'original-job')
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps({
            'video_agent_input_fingerprint':fp,'video_agent_job_fingerprint':signature}),jid))
    receipt={'repair_id':'repair-loaded','binding':{'task_id':state['id'],'job_id':jid,
        'input_fingerprint':fp,'job_fingerprint':signature,'agent_epoch':1},
        'files':[{'repo':'main','path':'hotpost/source.py','sha256':'verified'}]}
    studio.video_repair_pipeline=SimpleNamespace(ready_to_apply=lambda _:receipt)
    assert actions.execute(studio,state['id'],{'kind':'park_for_repair','repair_id':receipt['repair_id'],
        'job_id':jid,'_agent_epoch':1,'hypothesis':'Park current job for the reviewed code'},'park',fp)['parked']
    studio.loaded_code_receipts={receipt['repair_id']:receipt}
    monkeypatch.setattr(repairs,'verified_repair',lambda *args:receipt)
    return studio,state['id'],jid,VideoAgentManager(studio)


def rows(store):
    with store.connect() as db:
        return {name:[tuple(row) for row in db.execute('select * from '+name)]
                for name in ('tasks','jobs','video_agents','video_agent_steps','video_agent_action_receipts')}


def test_loaded_resume_does_not_replay_old_success_after_same_job_pauses_again(tmp_path,monkeypatch):
    studio,task,jid,manager=parked(tmp_path,monkeypatch)
    try:
        resume_loaded_repairs(studio,manager)
        job=studio.store.claim(task_id=task);assert job and job['id']==jid
        assert studio.store.pause_claimed(job,'New independently diagnosed preparation failure')
        manager._save(task,1,{'pending':{'model_job_id':'new-diagnosis'},'last_action':'test_patch',
            'status':'recovering','last_result':{'status':'tests_failed'},'idle_decisions':13})
        before=copy.deepcopy(rows(studio.store))
        monkeypatch.setattr(actions,'execute',lambda *args:pytest.fail('Accepted continuation cannot execute again'))
        resume_loaded_repairs(studio,manager);resume_loaded_repairs(studio,manager)
        assert rows(studio.store)==before
        assert get_agent(studio.store,task)['pending']['model_job_id']=='new-diagnosis'
    finally:manager.pool.shutdown(wait=True)


@pytest.mark.parametrize('blocked',['cooldown','error'])
def test_unsuccessful_continuation_remains_eligible_after_the_cause_is_fixed(tmp_path,monkeypatch,blocked):
    studio,task,jid,manager=parked(tmp_path,monkeypatch)
    original=actions.execute
    try:
        if blocked=='cooldown':
            with studio.store.transaction() as db:
                cp=json.loads(db.execute('select checkpoint from jobs where id=?',(jid,)).fetchone()[0])
                cp['not_before']=10**12
                db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),jid))
        else:
            def fail(*args):raise TypeError('Transient malformed legacy dependency')
            monkeypatch.setattr(actions,'execute',fail)
        resume_loaded_repairs(studio,manager)
        with studio.store.connect() as db:
            assert not db.execute("select 1 from video_agent_action_receipts where decision_id like 'loaded-repair-resume:%'").fetchone()
            assert db.execute('select status from jobs where id=?',(jid,)).fetchone()[0]=='paused'
        monkeypatch.setattr(actions,'execute',original)
        with studio.store.transaction() as db:
            cp=json.loads(db.execute('select checkpoint from jobs where id=?',(jid,)).fetchone()[0]);cp.pop('not_before',None)
            db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),jid))
        resume_loaded_repairs(studio,manager)
        with studio.store.connect() as db:assert db.execute('select status from jobs where id=?',(jid,)).fetchone()[0]=='queued'
    finally:manager.pool.shutdown(wait=True)
