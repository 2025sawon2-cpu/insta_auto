import json
import time
from hotpost.studio_store import StudioStore


def test_reservation_hides_job_from_old_worker_but_respects_real_backoff(tmp_path):
    store=StudioStore(tmp_path)
    task,_=store.create('selected','Selected',prepare=False)
    with store.transaction() as db:
        job=store.enqueue(db,task['id'],'collect_sources',{},'reserved')
        cp={'not_before':time.time()+3600,'batch_reservation':'batch',
            'batch_original_not_before':time.time()+60}
        db.execute('UPDATE jobs SET checkpoint=? WHERE id=?',(json.dumps(cp),job))
    assert store.claim('sources') is None
    assert store.claim('sources',reservation='other') is None
    assert store.claim('sources',reservation='batch') is None
    cp['batch_original_not_before']=0
    store.checkpoint(job,cp)
    claimed=store.claim('sources',task_id=task['id'],reservation='batch')
    assert claimed['id']==job
    assert store.claim('sources',reservation='batch') is None

def test_specific_job_claim_does_not_take_an_older_independent_source_job(tmp_path):
    store=StudioStore(tmp_path);task,_=store.create('selected','Selected',prepare=False)
    with store.transaction() as db:
        source=store.enqueue(db,task['id'],'collect_sources',{},'sources')
        render=store.enqueue(db,task['id'],'quality_reedit',{},'render')
    claimed=store.claim(task_id=task['id'],job_id=render)
    assert claimed['id']==render
    assert store.claim('sources')['id']==source
