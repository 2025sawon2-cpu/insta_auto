import copy
import json
import threading
from types import SimpleNamespace

import pytest

from hotpost.studio_store import StudioStore
from hotpost.studio_runtime.lifecycle import LifecycleMixin
from hotpost.source_access_preflight import SourceAccessWaiting
from hotpost.source_pause_receipts import SourceReceiptWaiting
from hotpost.source_preparation import PreparationEvidenceWaiting


@pytest.mark.parametrize('error_type,internal', [(SourceReceiptWaiting, True), (PreparationEvidenceWaiting, True), (SourceAccessWaiting, False)])
def test_real_worker_persists_wait_and_respects_due_time_and_claim_ownership(tmp_path, monkeypatch, error_type, internal):
    clock = [2000000000.0]
    monkeypatch.setattr('time.time', lambda: clock[0])
    store = StudioStore(tmp_path)
    state, _ = store.create('integration-source-wait', 'source wait', prepare=False, initial={'status': 'source_wait', 'automation': {'active': False}, 'sources': [], 'daily_quality': {'repair_round': 0, 'max_repairs': 3}})
    before = copy.deepcopy(store.get(state['id']))
    with store.transaction() as db:
        db.execute("INSERT INTO jobs(id,task_id,kind,key,payload,status,checkpoint,created,updated) VALUES(?,?,?,?,?,'queued','{}',?,?)", ('integration-job', state['id'], 'collect_sources', 'integration-key', '{}', clock[0], clock[0]))
    worker = LifecycleMixin()
    worker.store = store
    worker.stop = threading.Event()
    worker.settings = SimpleNamespace(studio_daily_quality_max_repairs=3)
    seen = []
    error = error_type('immutable binding mismatch' if internal else 'external access dependency')
    error.retry_at = clock[0] + 40
    def collect(actual, job):
        seen.append(copy.deepcopy(job))
        worker.stop.set()
        raise error
    worker._collect_sources = collect
    worker._worker('sources')
    assert len(seen) == 1
    with store.connect() as db:
        row = db.execute('SELECT * FROM jobs WHERE id=?', ('integration-job',)).fetchone()
        checkpoint = json.loads(row['checkpoint'])
        assert row['status'] == 'queued'
        assert checkpoint['not_before'] == clock[0] + 40
        assert bool(checkpoint.get('retry_requested')) is internal
        assert checkpoint.get('auto_retries', 0) == (1 if internal else 0)
        if internal:
            assert checkpoint['internal_evidence_wait'] is True
            assert checkpoint['failure_trace']['type'] == error_type.__name__
            assert checkpoint['failure_trace']['message'] == str(error)
    after = store.get(state['id'])
    assert after['sources'] == before['sources']
    assert after['daily_quality'] == before['daily_quality']
    assert after['automation'] == before['automation']
    assert after['source_search']['error'] == (str(error) if internal else '')
    assert store.claim('sources') is None
    clock[0] += 39
    assert store.claim('sources') is None
    clock[0] += 1
    reclaimed = store.claim('sources')
    assert reclaimed['id'] == 'integration-job'
    assert reclaimed['claim_token'] != seen[0]['claim_token']
    assert store.defer(seen[0], 'stale overwrite', 0) is False
    with store.connect() as db:
        row = db.execute('SELECT status,checkpoint FROM jobs WHERE id=?', ('integration-job',)).fetchone()
        assert row['status'] == 'running'
        assert json.loads(row['checkpoint'])['_claim_token'] == reclaimed['claim_token']
    store.change(state['id'], lambda current, db: current['automation'].update(paused_by_user=True))
    store.defer(reclaimed, 'preserve user pause', 40, waiting=not internal, waiting_status='source_wait')
    assert store.get(state['id'])['automation']['paused_by_user'] is True
    assert store.get(state['id'])['status'] == 'paused'
    clock[0] += 41
    assert store.claim('sources') is None
