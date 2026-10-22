"""Independent regressions for cancellation ownership and hidden model retries."""
from types import SimpleNamespace
import runpy
import threading
import time

import pytest

from hotpost.studio_adapter import StudioAdapter
from hotpost.studio_store import StudioStore


class Writer:
    def __init__(self, initial=None):
        self.updates = []
        self.created = []
        self.initial = initial

    def update(self, identifier, **values):
        self.updates.append((identifier, values))

    def active_children(self, identifier):
        return []

    def create(self, kind, payload, *args):
        self.created.append((kind, payload, args))
        return self.initial

    def start(self):
        pass


def test_model_id_only_cancellation_cannot_cancel_new_claim_owner(tmp_path):
    store = StudioStore(tmp_path/'studio')
    task, _ = store.create('ownership', 'ownership')
    old = store.claim()
    old['checkpoint']['supervision_model_job_id'] = 'codexshared'
    store.checkpoint(old, old['checkpoint'])
    store.recover()
    current = store.claim()
    assert current['claim_token'] != old['claim_token']
    adapter = StudioAdapter(SimpleNamespace(data_dir=tmp_path))
    writer = Writer()
    adapter._jobs = writer
    # Old adapter's model ID has no proof that it still owns this new claim.
    adapter._cancel_exclusive('codexshared')
    assert writer.updates == []


@pytest.mark.parametrize('error_reason', ['no_progress', 'validation', 'invalid_response'])
def test_editorial_does_not_blindly_rerun_a_saved_nontransport_failure(tmp_path, error_reason):
    adapter = StudioAdapter(SimpleNamespace(data_dir=tmp_path))
    writer = Writer({'id': 'codexsaved', 'state': 'failed', 'error': 'saved failure',
                     'result': {'error_reason': error_reason}})
    adapter._jobs = writer
    def wait(job):
        raise RuntimeError('saved failure requires diagnosis')
    adapter._wait = wait
    with pytest.raises(RuntimeError):
        adapter.editorial('review', {'purpose': 'scene_review'})
    assert len(writer.created) == 1


def test_claim_bound_cancellation_rejects_stale_and_shared_consumers(tmp_path):
    from test_studio_supervision import setup
    studio, monitor, _, _, _, task, _ = setup(tmp_path)
    monitor.pulse()
    old = studio.store.claim()
    old['checkpoint']['supervision_model_job_id'] = 'codexshared'
    studio.store.checkpoint(old, old['checkpoint'])
    studio.store.recover()
    current = studio.store.claim()
    writer = Writer()
    assert not monitor.cancel_model(old, 'codexshared', writer)
    assert not monitor.cancel_model(current, 'codexdifferent', writer)
    # A second current consumer can be on the independent source lane.
    with studio.store.transaction() as db:
        source_id = studio.store.enqueue(db, task['id'], 'collect_sources', {}, 'source')
    source = studio.store.claim('sources', job_id=source_id)
    source['checkpoint']['supervision_model_job_id'] = 'codexshared'
    studio.store.checkpoint(source, source['checkpoint'])
    assert not monitor.cancel_model(current, 'codexshared', writer)
    assert writer.updates == []
    studio.store.fail(source, RuntimeError('done'))
    assert monitor.cancel_model(current, 'codexshared', writer)
    assert writer.updates == [('codexshared', {'cancel': 1})]


def test_close_keeps_supervisor_healthy_until_production_threads_drain(tmp_path):
    from test_studio_supervision import setup
    studio, monitor, now, *_ = setup(tmp_path)
    monitor.interval = .005
    finished = threading.Event()
    studio._start_owned_thread(monitor.run, (), 'studio-supervision')
    assert monitor.ready.wait(1)
    studio._start_owned_thread(lambda: finished.wait(2), (), 'studio-production')
    closing = threading.Thread(target=studio.close)
    closing.start()
    try:
        assert studio.stop.wait(1)
        assert not monitor.stop.is_set()
        now[0] += monitor.stale_after + 1
        until = time.monotonic() + 1
        while monitor.last_tick < now[0] and time.monotonic() < until:
            time.sleep(.005)
        assert monitor.healthy()
        assert closing.is_alive()  # Still draining the accepted work.
    finally:
        finished.set()
        closing.join(2)
        monitor.stop.set()
    assert not closing.is_alive()
    assert all(not thread.is_alive() for thread in studio._threads)


def test_recovery_helper_fails_before_settings_or_studio_state_is_opened(monkeypatch, capsys):
    import hotpost.config
    import hotpost.studio
    def forbidden(*a, **kw):
        pytest.fail('unmonitored recovery must not touch settings or production state')
    monkeypatch.setattr(hotpost.config, 'load_settings', forbidden)
    monkeypatch.setattr(hotpost.studio, 'Studio', forbidden)
    monkeypatch.setattr('sys.argv', ['run_reserved_recovery_job', '--code', 'x', '--kind', 'edit'])
    with pytest.raises(SystemExit) as caught:
        runpy.run_module('tools.run_reserved_recovery_job', run_name='__main__')
    assert caught.value.code == 2
    assert 'API' in capsys.readouterr().err


def test_deployed_database_cannot_be_claimed_through_unattached_store(tmp_path):
    from test_studio_supervision import setup
    studio, monitor, *_ = setup(tmp_path)
    monitor.pulse()
    detached = StudioStore(studio.store.root)
    assert detached.claim() is None
    assert studio.store.claim() is not None


def test_writer_no_progress_requests_claim_bound_cancellation_before_parent_pauses(tmp_path, monkeypatch):
    from hotpost.operation_progress import NoProgressTimeout
    from hotpost.studio_pause import pause_scope
    class StalledWatch:
        def __init__(self, *a, **kw): pass
        def observe(self, *a): pass
        def check(self): raise NoProgressTimeout('actual output stopped')
    monkeypatch.setattr('hotpost.operation_progress.ProgressWatch', StalledWatch)
    adapter = StudioAdapter(SimpleNamespace(data_dir=tmp_path, studio_timeout=1))
    adapter.get = lambda identifier, **kw: {'id': identifier, 'state': 'running', 'progress': 0}
    writer = Writer()
    writer.observe_progress = lambda *a: None
    adapter._jobs = writer
    cancelled = []
    def progress(*a): pass
    progress.check_cancel = lambda: None
    progress.supervision_cancel = lambda identifier, owner: cancelled.append((identifier, owner)) or True
    with pause_scope(progress):
        with pytest.raises(NoProgressTimeout):
            adapter._wait({'id': 'codexstalled'})
    assert cancelled == [('codexstalled', writer)]
