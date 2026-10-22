"""Worker claim lock recovery without changing admission controls."""
import sqlite3
import pytest
from hotpost.config import Settings
from hotpost.studio import Studio


@pytest.mark.parametrize('failure', ['database is locked', 'database table is locked'])
def test_worker_retries_locked_claim_through_real_store(tmp_path, monkeypatch, failure):
    app = Studio(Settings(data_dir=tmp_path), workers=False)
    state, _ = app.store.create('claim-lock', 'Claim lock')
    original = app.store.claim
    attempts = []
    waits = []
    def claim(lane):
        attempts.append(lane)
        if len(attempts) == 1:
            raise sqlite3.OperationalError(failure)
        assert app.store.jobs(state['id'])[0]['status'] == 'queued'
        return original(lane)
    def prepare(current, job):
        assert job['claim_token']
        app.stop.set()
        return {}
    monkeypatch.setattr(app.store, 'claim', claim)
    monkeypatch.setattr(app.stop, 'wait', lambda seconds: waits.append(seconds))
    monkeypatch.setattr(app, '_prepare', prepare)
    monkeypatch.setattr(app, '_accept', lambda *args: None)
    app._worker('media')
    assert attempts == ['media', 'media']
    assert waits == [.6]
    assert app.store.jobs(state['id'])[0]['status'] == 'done'


def test_worker_does_not_retry_non_lock_claim_error(tmp_path, monkeypatch):
    app = Studio(Settings(data_dir=tmp_path), workers=False)
    state, _ = app.store.create('claim-corrupt', 'Claim error')
    def claim(lane):
        raise sqlite3.OperationalError('no such table: jobs')
    monkeypatch.setattr(app.store, 'claim', claim)
    with pytest.raises(sqlite3.OperationalError, match='no such table'):
        app._worker('media')
    assert app.store.jobs(state['id'])[0]['status'] == 'queued'
