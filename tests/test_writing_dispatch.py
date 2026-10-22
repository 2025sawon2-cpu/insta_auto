import threading
import time

from hotpost.writing.jobs import Jobs


def owner(jobs,index,identity=''):
    return jobs.create('video_agent',{'owner_conversation':{
        'task_id':f'work-{index:016x}','run_id':f'run-{index:016x}','epoch':1}},identity)


def eventually(predicate):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(.01)
    assert predicate()


def test_three_distinct_owners_run_without_duplicate_dispatch_and_bound_is_three(tmp_path,monkeypatch):
    jobs=Jobs(tmp_path)
    rows=[owner(jobs,i) for i in range(1,5)]
    releases={row['id']:threading.Event() for row in rows}
    started=[];lock=threading.Lock();inflight=set();maximum=[0]
    def execute(job):
        assert jobs.get(job['id'],include_payload=False)['state']=='running'
        with lock:
            assert job['id'] not in started
            started.append(job['id']);inflight.add(job['id']);maximum[0]=max(maximum[0],len(inflight))
        assert releases[job['id']].wait(10)
        jobs.update(job['id'],state='completed',result={'value':'settled'})
        with lock:inflight.remove(job['id'])
    monkeypatch.setattr(jobs,'execute',execute)
    worker=threading.Thread(target=jobs.work);worker.start()
    try:
        eventually(lambda:len(started)==3)
        # Another Jobs instance cannot become a second consumer or mark live
        # calls interrupted while the dispatcher owns the OS lease.
        competitor=Jobs(tmp_path)
        monkeypatch.setattr(competitor,'execute',lambda job:(_ for _ in ()).throw(AssertionError('duplicate')))
        competitor.work()
        assert len(started)==3
        assert jobs.get(rows[3]['id'])['state']=='queued'
        releases[rows[0]['id']].set()
        eventually(lambda:len(started)==4)
        assert maximum[0]==3
    finally:
        for event in releases.values():event.set()
        worker.join(10)
    assert not worker.is_alive()
    assert all(jobs.get(row['id'])['state']=='completed' for row in rows)


def test_same_video_and_ordinary_production_remain_serial_but_new_other_owner_can_start(tmp_path,monkeypatch):
    jobs=Jobs(tmp_path)
    first=owner(jobs,1,'first');same=owner(jobs,1,'next-owner-decision')
    production=jobs.create('editorial',{'instruction':'first'})
    next_production=jobs.create('editorial',{'instruction':'second'})
    started=[];ended=[];release=threading.Event();lock=threading.Lock()
    blocking={first['id'],production['id']}
    def execute(job):
        with lock:
            if job['id']==same['id']:assert first['id'] in ended
            if job['id']==next_production['id']:assert production['id'] in ended
            started.append(job['id'])
        if job['id'] in blocking:assert release.wait(10)
        with lock:ended.append(job['id'])
        jobs.update(job['id'],state='completed',result={'value':True})
    monkeypatch.setattr(jobs,'execute',execute)
    worker=threading.Thread(target=jobs.work);worker.start()
    try:
        eventually(lambda:first['id'] in started and production['id'] in started)
        assert same['id'] not in started and next_production['id'] not in started
        new=owner(jobs,2)
        eventually(lambda:new['id'] in started)
        assert not release.is_set()
    finally:
        release.set();worker.join(10)
    assert not worker.is_alive()
    assert len(started)==len(set(started))==5
    assert all(jobs.get(jid)['state']=='completed' for jid in started)


def test_owner_lane_spans_run_and_epoch_and_malformed_binding_stays_serial():
    first={'kind':'video_agent','payload':{'owner_conversation':{'task_id':'work-'+'a'*16,'run_id':'old','epoch':1}}}
    next_run={'kind':'video_agent','payload':{'owner_conversation':{'task_id':'work-'+'a'*16,'run_id':'new','epoch':2}}}
    assert Jobs._execution_lane(first)==Jobs._execution_lane(next_run)
    for payload in [None,[],{}, {'owner_conversation':[]},{'owner_conversation':{'task_id':'foreign'}}]:
        assert Jobs._execution_lane({'kind':'video_agent','payload':payload})=='production'


def test_independent_owner_after_sixty_four_blocked_lane_jobs_is_not_hidden(tmp_path,monkeypatch):
    jobs=Jobs(tmp_path);first=owner(jobs,1,'first')
    for index in range(64):owner(jobs,1,'blocked-'+str(index))
    independent=owner(jobs,2)
    release=threading.Event();started=[]
    def execute(job):
        started.append(job['id'])
        if job['id']==first['id']:assert release.wait(10)
        jobs.update(job['id'],state='completed',result={'value':True})
    monkeypatch.setattr(jobs,'execute',execute)
    worker=threading.Thread(target=jobs.work);worker.start()
    try:
        eventually(lambda:independent['id'] in started)
        assert started==[first['id'],independent['id']]
        assert not release.is_set()
    finally:
        release.set();worker.join(10)
    assert not worker.is_alive() and len(started)==66


def test_blocked_daemon_call_does_not_hold_process_exit_and_running_row_is_recovered(tmp_path,monkeypatch):
    import subprocess
    import sys
    from pathlib import Path
    script='''import sys,threading
from hotpost.writing.jobs import Jobs
jobs=Jobs(sys.argv[1]);started=threading.Event()
jobs.create('video_agent',{'owner_conversation':{'task_id':'work-1111111111111111','run_id':None,'epoch':1}})
def blocked(job):
 started.set();threading.Event().wait()
jobs.execute=blocked
jobs.start()
assert started.wait(5)
'''
    proc=subprocess.Popen([sys.executable,'-c',script,str(tmp_path)],cwd=Path(__file__).resolve().parents[1],
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        stdout,stderr=proc.communicate(timeout=10)
        assert proc.returncode==0,(stdout,stderr)
    finally:
        if proc.poll() is None:proc.kill();proc.wait(timeout=5)
    jobs=Jobs(tmp_path)
    with jobs.db() as db:old=db.execute("select id from jobs where state='running'").fetchone()['id']
    new=owner(jobs,2)
    monkeypatch.setattr(jobs,'execute',lambda job:jobs.update(job['id'],state='completed',result={'value':True}))
    jobs.work()
    assert jobs.get(old)['state']=='interrupted'
    assert jobs.get(new['id'])['state']=='completed'


def test_cancelled_admission_keeps_existing_execution_cancel_check(tmp_path,monkeypatch):
    from hotpost.writing import codex_writer
    jobs=Jobs(tmp_path);row=owner(jobs,1);jobs.update(row['id'],cancel=1)
    monkeypatch.setattr(codex_writer,'chat',lambda *a,**k:(_ for _ in ()).throw(AssertionError('cancelled model called')))
    jobs.work()
    assert jobs.get(row['id'])['state']=='cancelled'


def test_thread_start_failure_preserves_claim_for_existing_orphan_recovery(tmp_path,monkeypatch):
    import pytest
    jobs=Jobs(tmp_path);first=owner(jobs,1);next_job=owner(jobs,2)
    original=threading.Thread.start
    def reject_model(thread):
        if thread.name=='codex-model':raise RuntimeError('planned thread start failure')
        return original(thread)
    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread,'start',reject_model)
        with pytest.raises(RuntimeError,match='planned thread start failure'):jobs.work()
    assert jobs.get(first['id'])['state']=='running'
    assert jobs.get(next_job['id'])['state']=='queued'
    monkeypatch.setattr(jobs,'execute',lambda job:jobs.update(job['id'],state='completed',result={'value':True}))
    jobs.work()
    assert jobs.get(first['id'])['state']=='interrupted'
    assert jobs.get(next_job['id'])['state']=='completed'
