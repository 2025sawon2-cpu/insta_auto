import sqlite3
from types import SimpleNamespace

import pytest

from hotpost.studio_runtime.lifecycle import LifecycleMixin


class Stop:
    def __init__(self):
        self.stopped = False
        self.waits = []

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        self.waits.append(seconds)


@pytest.mark.parametrize('code,message', [
    (sqlite3.SQLITE_BUSY, 'database is locked'),
    (sqlite3.SQLITE_LOCKED, 'database table is locked'),
    (sqlite3.SQLITE_BUSY | (2 << 8), 'database is locked'),
    (sqlite3.SQLITE_LOCKED | (1 << 8), 'database table is locked'),
    (None, 'database is locked'),
    (None, 'database table is locked'),
])
def test_worker_retries_normal_claim_after_transient_lock(code, message, caplog):
    stop = Stop()
    calls = []
    error = sqlite3.OperationalError(message)
    if code is not None:
        error.sqlite_errorcode = code

    def claim(lane):
        calls.append(lane)
        if len(calls) == 1:
            raise error
        stop.stopped = True
        return None

    worker = SimpleNamespace(stop=stop, store=SimpleNamespace(claim=claim))
    LifecycleMixin._worker(worker, 'sources')
    assert calls == ['sources', 'sources']
    assert stop.waits == [.6, .6]
    assert 'Studio claim temporarily locked: sources' in caplog.text


@pytest.mark.parametrize('code,message', [
    (None, 'admission failed'),
    (sqlite3.SQLITE_ERROR, 'admission failed'),
    (sqlite3.SQLITE_CORRUPT, 'admission failed'),
    (sqlite3.SQLITE_ERROR, 'database is locked'),
    (None, 'database is locked unexpectedly'),
])
def test_worker_does_not_hide_other_admission_errors(code, message):
    stop = Stop()
    error = sqlite3.OperationalError(message)
    if code is not None:
        error.sqlite_errorcode = code

    def claim(lane):
        raise error

    worker = SimpleNamespace(stop=stop, store=SimpleNamespace(claim=claim))
    with pytest.raises(sqlite3.OperationalError) as caught:
        LifecycleMixin._worker(worker, 'sources')
    assert caught.value is error
    assert stop.waits == []


def test_stop_during_lock_backoff_prevents_another_claim():
    stop = Stop()
    calls = []

    def wait(seconds):
        stop.waits.append(seconds)
        stop.stopped = True

    stop.wait = wait

    def claim(lane):
        calls.append(lane)
        raise sqlite3.OperationalError('database is locked')

    worker = SimpleNamespace(stop=stop, store=SimpleNamespace(claim=claim))
    LifecycleMixin._worker(worker, 'sources')
    assert calls == ['sources']
    assert stop.waits == [.6]
