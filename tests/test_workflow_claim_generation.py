"""External worker replay/recovery conditions, using real durable transactions."""
import copy
import pytest
import sqlite3
from hotpost.studio_store import StudioStore, StaleClaim, change_claimed


def claimed(tmp_path):
    store = StudioStore(tmp_path)
    task, _ = store.create('replay', 'replay')
    return store, task, store.claim()


def test_read_connection_context_releases_database_handle_immediately(tmp_path):
    store = StudioStore(tmp_path)
    with store.connect() as db:
        assert db.execute('SELECT 1').fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute('SELECT 1')


def test_duplicate_completion_failure_and_deferral_cannot_rewind_completed_state(tmp_path):
    store, task, job = claimed(tmp_path)
    assert store.finish(job, {}, lambda s, db, r: s.update(status='completed'))
    before = copy.deepcopy(store.get(task['id']))
    events = store.events(task['id'])
    assert store.finish(job, {}, lambda s, db, r: s.update(status='preparing')) is False
    assert store.fail(job, 'late failure') is False
    assert store.defer(job, 'late wait', 0, waiting=True) is False
    with pytest.raises(StaleClaim):
        change_claimed(store, job, lambda s, db: s.update(status='editing'))
    assert store.get(task['id']) == before and store.events(task['id']) == events


def test_recovered_same_id_old_worker_cannot_complete_or_erase_new_checkpoint(tmp_path):
    store, task, old = claimed(tmp_path)
    store.checkpoint(old, {**old['checkpoint'], 'request_id': 718})
    store.recover()
    current = store.claim()
    assert current['id'] == old['id'] and current['claim_token'] != old['claim_token']
    assert current['checkpoint']['request_id'] == 718
    assert store.finish(old, {}, lambda s, db, r: s.update(status='completed')) is False
    assert store.fail(old, 'late error') is False
    assert store.defer(old, 'old wait', 0) is False
    with pytest.raises(StaleClaim):
        store.checkpoint(old, {'request_id': 1})
    with pytest.raises(StaleClaim):
        change_claimed(store, old, lambda s, db: s.update(script_id='old'))
    assert store.finish(current, {}, lambda s, db, r: s.update(status='completed'))
    assert store.get(task['id'])['status'] == 'completed'


def test_service_deferral_reclaim_preserves_id_and_only_current_completion_is_accepted(tmp_path):
    store, task, old = claimed(tmp_path)
    store.defer(old, 'service busy', 0, waiting=True, waiting_status='retry_wait')
    current = store.claim()
    assert current['checkpoint'].get('auto_retries', 0) == 0
    assert store.finish(old, {}, lambda s, db, r: s.update(status='attention')) is False
    assert store.finish(current, {}, lambda s, db, r: s.update(status='completed'))
