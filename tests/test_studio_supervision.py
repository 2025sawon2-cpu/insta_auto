import json
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.studio_supervision import StudioSupervisor, SupervisionHold


class Writer:
    def __init__(self):
        self.calls = []
        self.state = 'queued'
    def create(self, kind, payload, identity):
        self.calls.append((kind, payload, identity))
        return {'id': 'codexdiagnosis'}
    def start(self): pass
    def get(self, jid, **kwargs):
        return {'state': self.state, 'result': {'value': {'category': 'unknown', 'reason': 'continue anyway'}}}


def setup(tmp_path):
    studio = Studio(Settings(data_dir=tmp_path), workers=False)
    now = [1000.]
    evidence = {'progress': {'bytes': 123}, 'waits': [], 'references': [], 'unknown': False}
    writer = Writer()
    monitor = StudioSupervisor(studio, clock=lambda: now[0], collector=lambda *_: evidence, writer=writer)
    monitor.suspect_after = 10
    monitor.diagnosis_grace = 5
    studio.supervisor = studio.store.supervisor = monitor
    task = studio.store.create('test', 'test', prepare=False)[0]
    with studio.store.transaction() as db:
        jid = studio.store.enqueue(db, task['id'], 'edit', {}, 'one')
    return studio, monitor, now, evidence, writer, task, jid


def tick(monitor, now, seconds=5):
    now[0] += seconds
    monitor.tick()
    monitor.pulse()


def test_no_admission_before_monitor_is_ready_and_durable_claim_receipt(tmp_path):
    studio, monitor, *_ = setup(tmp_path)
    assert studio.store.claim() is None
    monitor.pulse()
    job = studio.store.claim()
    monitor.check(job)
    with studio.store.connect() as db:
        row = db.execute('SELECT claim FROM supervision_jobs WHERE job_id=?', (job['id'],)).fetchone()
    assert row[0] == job['claim_token']


def test_stale_monitor_blocks_new_work_and_running_boundaries(tmp_path):
    studio, monitor, now, *_ = setup(tmp_path)
    monitor.pulse(); job = studio.store.claim()
    now[0] += monitor.stale_after+1
    assert studio.store.claim() is None
    with pytest.raises(SupervisionHold): monitor.check(job)


def test_stagnation_calls_ai_once_then_holds_without_repeating_work(tmp_path):
    studio, monitor, now, evidence, writer, task, _ = setup(tmp_path)
    monitor.pulse(); job = studio.store.claim()
    tick(monitor, now)  # existing files are only the baseline
    tick(monitor, now); tick(monitor, now)
    assert len(writer.calls) == 1
    tick(monitor, now)
    with pytest.raises(SupervisionHold): monitor.check(job)
    assert monitor.summary(task['id'])['jobs'][0]['phase'] == 'held'
    studio.store.pause_claimed(job, 'held')
    with studio.store.transaction() as db:
        studio.store.enqueue(db, task['id'], 'voice', {}, 'other')
    assert studio.store.claim() is None  # another stage cannot evade a held method
    assert len(writer.calls) == 1


def test_actual_progress_continues_long_work_and_wait_does_not_count_as_progress(tmp_path):
    studio, monitor, now, evidence, writer, *_ = setup(tmp_path)
    monitor.pulse(); job = studio.store.claim(); tick(monitor, now)
    for _ in range(20):
        evidence['progress']['bytes'] += 1
        tick(monitor, now)
    assert not writer.calls
    last = monitor.summary()['jobs'][0]['last_progress_at']
    evidence['waits'] = [{'kind': 'model_queue', 'reference': 'bound-job'}]
    for _ in range(20): tick(monitor, now)
    assert not writer.calls
    assert monitor.summary()['jobs'][0]['last_progress_at'] == last
    monitor.check(job)


def test_administrative_changes_cannot_reset_stall_or_model_advice_approve(tmp_path):
    studio, monitor, now, evidence, writer, *_ = setup(tmp_path)
    monitor.pulse(); job = studio.store.claim(); tick(monitor, now)
    for n in range(2):
        evidence['message'] = f'alive{n}'
        evidence['references'] = [{'path': f'renamed-{n}.log'}]
        tick(monitor, now)
    writer.state = 'completed'
    tick(monitor, now, 1)
    with pytest.raises(SupervisionHold): monitor.check(job)


def test_restart_preserves_high_water_and_hold_requires_explicit_release(tmp_path):
    studio, monitor, now, evidence, writer, task, jid = setup(tmp_path)
    monitor.pulse(); job = studio.store.claim(); tick(monitor, now)
    monitor.hold(job, 'no progress')
    other = StudioSupervisor(studio, clock=lambda: now[0], collector=lambda *_: evidence, writer=writer)
    studio.supervisor = studio.store.supervisor = other
    other.pulse(); studio.store.recover()
    assert studio.store.jobs(task['id'])[0]['status'] == 'paused'
    assert studio.store.claim() is None
    with studio.store.transaction() as db:
        other.release(db, task['id'])
        db.execute("UPDATE jobs SET status='queued' WHERE id=?", (jid,))
    new = studio.store.claim()
    assert new['claim_token'] != job['claim_token']
    with pytest.raises(SupervisionHold): other.check(job)
    other.check(new)
    with studio.store.connect() as db:
        saved = json.loads(db.execute('SELECT record FROM supervision_jobs WHERE job_id=?', (jid,)).fetchone()[0])
    assert saved['high_water'] == {'bytes': 123}


def test_late_diagnosis_cannot_write_over_new_claim(tmp_path):
    studio, monitor, now, evidence, writer, task, jid = setup(tmp_path)
    monitor.pulse(); job = studio.store.claim(); tick(monitor, now)
    with studio.store.connect() as db:
        old = json.loads(db.execute('SELECT record FROM supervision_jobs WHERE job_id=?', (jid,)).fetchone()[0])
    studio.store.recover(); new = studio.store.claim()
    old.update(phase='held', reason='late old response')
    assert monitor._save(job, old) is False
    monitor.check(new)


def test_writer_failure_holds_without_generic_retry(tmp_path):
    studio, monitor, now, _, writer, *_ = setup(tmp_path)
    def broken(*args): raise OSError('unavailable')
    writer.create = broken
    monitor.pulse(); job = studio.store.claim(); tick(monitor, now)
    tick(monitor, now); tick(monitor, now)
    with pytest.raises(SupervisionHold): monitor.check(job)


def test_real_studio_starts_monitor_before_workers_and_keeps_single_owner(tmp_path):
    settings = Settings(data_dir=tmp_path, studio_auto_top_enabled=False)
    studio = Studio(settings)
    try:
        assert studio.supervisor.healthy()
        assert studio._threads[0].name == 'studio-supervision'
        second = Studio(settings)
        try:
            assert second.supervisor is None
            assert not second._threads
        finally: second.close()
    finally: studio.close()


def test_observation_failure_blocks_admission_and_loop_can_recover(tmp_path):
    studio, monitor, now, *_ = setup(tmp_path)
    monitor.pulse(); studio.store.claim()
    monitor.error = 'database unavailable'
    assert studio.store.claim() is None
    monitor.tick(); monitor.pulse()
    assert monitor.healthy()


def test_supervision_health_route_is_not_consumed_as_the_full_task_list():
    from hotpost.studio_http import StudioHTTP
    route = StudioHTTP()
    route.path = '/api/studio-supervision'
    assert route.studio_get(None) is False
    assert route.studio_post(None) is False
