import json
import sys

import pytest

from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.studio_pause import StudioPaused, bind_progress, check_paused, pause_scope, active_cancel
from hotpost.source_browser_worker import run_bounded


def test_running_collection_pause_preserves_files_and_no_failure_charge(tmp_path, monkeypatch):
    studio = Studio(Settings(data_dir=tmp_path), workers=False)
    task, _ = studio.store.create('watchdog', 'product', {'active': True, 'protocol': 2})
    with studio.store.transaction() as db:
        db.execute("update jobs set status='done'")
        studio.store.enqueue(db, task['id'], 'collect_sources', {}, 'watchdog-collect')
    job = studio.store.claim('sources')
    assert job['kind'] == 'collect_sources'
    received = tmp_path / 'received.mp4'
    calls = []

    def collect(*args, **kwargs):
        progress = args[2]
        received.write_bytes(b'previously received evidence')
        progress('first candidate received', 50)
        calls.append('first')
        studio.action(task['id'], 'pause-auto', {})
        progress('next request must be prevented', 51)
        calls.append('second')

    monkeypatch.setattr('hotpost.source_finder.find_sources', collect)
    monkeypatch.setattr(studio, '_review_deferred_downloads', lambda *a: None)
    with pytest.raises(StudioPaused) as stopped:
        studio._collect_sources(studio.store.get(task['id']), job)
    studio.store.defer(job, str(stopped.value), 0, waiting=True)
    state = studio.store.get(task['id'])
    assert state['status'] == 'paused'
    assert state['automation']['paused_by_user'] and not state['automation']['active']
    assert calls == ['first'] and received.read_bytes() == b'previously received evidence'
    assert studio.store.jobs(task['id'])[0]['status'] == 'paused'
    assert not job['checkpoint'].get('auto_retries')
    assert not state.get('daily_quality', {}).get('repair_round')


@pytest.mark.parametrize('transfer_without_progress', [False, True])
def test_browser_poll_stops_owned_child_even_when_message_never_changes(tmp_path, transfer_without_progress):
    checkpoint = tmp_path / 'checkpoint.json'
    checkpoint.write_text(json.dumps({'message': 'same unchanged checkpoint',
                                     'candidates': [{'url': 'saved candidate'}]}), 'utf-8')
    received = tmp_path / 'partial.bin'
    received.write_bytes(b'keep partial transfer')
    ticks = []

    def check():
        ticks.append(1)
        if len(ticks) == 3:
            raise StudioPaused('watchdog requested stop')

    def progress(_):
        pass

    progress.check_cancel = check
    with pytest.raises(StudioPaused), pause_scope(progress):
        run_bounded([sys.executable, '-c', 'import sys,time; sys.stdin.read(); time.sleep(60)'],
                    {}, checkpoint, 30, None if transfer_without_progress else progress)
    assert len(ticks) == 3
    assert received.read_bytes() == b'keep partial transfer'
    assert json.loads(checkpoint.read_text('utf-8'))['candidates'] == [{'url': 'saved candidate'}]
    assert active_cancel() is None


def test_nested_progress_keeps_pause_check(tmp_path):
    studio = Studio(Settings(data_dir=tmp_path), workers=False)
    task, _ = studio.store.create('stop-nested', 'product', {'active': True, 'protocol': 2})
    def original(*args):
        pass
    original.check_cancel = lambda: check_paused(studio.store, {'task_id': task['id']})
    nested = bind_progress(lambda _: None, original)
    studio.action(task['id'], 'pause-auto', {})
    with pytest.raises(StudioPaused):
        nested.check_cancel()
