from hotpost.studio_store import StudioStore
from hotpost.studio_timing import summarize


def timings(store, task):
    with store.connect() as db:
        return [dict(row) for row in db.execute('SELECT * FROM events WHERE task_id=? ORDER BY id', (task['id'],))]


def test_service_wait_and_reclaim_do_not_become_failure_or_duplicate_completion(tmp_path):
    store = StudioStore(tmp_path)
    task, _ = store.create('timing', 'timing')
    first = store.claim()
    store.defer(first, 'capacity wait', 0, waiting=True, waiting_status='source_wait')
    current = store.claim()
    assert store.finish(first, {}, lambda *a: None) is False
    store.finish(current, {}, lambda *a: None)
    report = summarize(timings(store, task))
    assert [r['outcome'] for r in report['attempts']] == ['claimed', 'deferred', 'claimed', 'done']
    assert report['attempts'][1]['wait_kind'] == 'source_wait'
    assert current['checkpoint'].get('auto_retries', 0) == 0
    assert not report['internal_waits_separately_measured']


def test_recovery_reports_unknown_interruption_without_inventing_run_duration(tmp_path):
    store = StudioStore(tmp_path)
    task, _ = store.create('recovery', 'recovery')
    old = store.claim()
    store.recover()
    assert store.fail(old, 'late') is False
    report = summarize(timings(store, task))
    assert report['attempts'][-1]['outcome'] == 'interrupted_unknown_end'
    assert report['claim_wall_union_seconds'] == 0


def test_parallel_source_and_voice_stages_use_interval_union_not_sum():
    events = [{'kind':'job_timing', 'detail':{
        'kind':kind, 'started_at':start, 'observed_at':end,
        'claim_wall_seconds':end-start, 'outcome':'done'}}
        for kind,start,end in [('collect_sources',10,40),('voice',20,30),('edit',50,60)]]
    report = summarize(events)
    assert report['claim_wall_union_seconds'] == 40
    assert sum(report['stage_wall_seconds'].values()) == 50
