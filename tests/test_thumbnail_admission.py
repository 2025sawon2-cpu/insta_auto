"""Two independent publication processes must not duplicate media work."""
import multiprocessing
from types import SimpleNamespace
from unittest.mock import patch

import psutil
import pytest

from hotpost.post_preparation import DraftConflict, PostPreparation
from hotpost import post_thumbnail as thumbnails


def contender(root, code, barrier, release, results):
    service = PostPreparation(SimpleNamespace(data_dir=root))
    service.get = lambda _: {'revision': 0, 'draft': {
        'thumbnail_options': {'hook': 'New title'}, 'selected_thumbnail': 'hook'}}

    def source(_):
        barrier.wait(timeout=15)
        return {'thumbnail_ready': True}

    service.source = source
    try:
        # Keep a genuinely live owner but do not render or launch a service.
        with patch.object(thumbnails.threading.Thread, 'start'):
            result = service.start_thumbnail(code, {'revision': 0})
        results.put(('accepted', result))
    except DraftConflict as exc:
        results.put(('conflict', str(exc)))
    except Exception as exc:
        results.put(('error', repr(exc)))
    finally:
        release.wait(timeout=20)


@pytest.mark.parametrize('second_code', ['same', 'other'])
def test_database_serializes_separate_server_processes(tmp_path, second_code):
    service = PostPreparation(SimpleNamespace(data_dir=tmp_path))
    ctx = multiprocessing.get_context('spawn')
    barrier, release, results = ctx.Barrier(2), ctx.Event(), ctx.Queue()
    processes = [ctx.Process(target=contender, args=(tmp_path, code, barrier, release, results))
                 for code in ('same', second_code)]
    try:
        for process in processes:
            process.start()
        answers = [results.get(timeout=20) for _ in processes]
        assert not any(kind == 'error' for kind, _ in answers), answers
        with service.connect() as db:
            assert db.execute('SELECT count(*) FROM thumbnail_jobs').fetchone()[0] == 1
        if second_code == 'same':
            assert [kind for kind, _ in answers] == ['accepted', 'accepted']
            assert answers[0][1]['id'] == answers[1][1]['id']
        else:
            assert sorted(kind for kind, _ in answers) == ['accepted', 'conflict']
    finally:
        release.set()
        for process in processes:
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()


@pytest.fixture
def service(tmp_path):
    service = PostPreparation(SimpleNamespace(data_dir=tmp_path))
    service.get = lambda _: {'revision': 0, 'draft': {
        'thumbnail_options': {'hook': 'New title'}, 'selected_thumbnail': 'hook'}}
    service.source = lambda _: {'thumbnail_ready': True}
    return service


def test_thread_start_failure_does_not_leave_a_permanent_active_job(service):
    with patch.object(thumbnails.threading.Thread, 'start', side_effect=RuntimeError('thread unavailable')):
        with pytest.raises(RuntimeError, match='thread unavailable'):
            service.start_thumbnail('post', {'revision': 0})
    assert thumbnails.job_status(service, 'post')['status'] == 'failed'


def test_revision_changed_during_source_read_cannot_render_old_text(service):
    def changed(_):
        with service.connect() as db:
            db.execute('INSERT INTO drafts VALUES (?,?,?,?)', ('post', 1, '{}', 0))
        return {'thumbnail_ready': True}
    service.source = changed
    with pytest.raises(DraftConflict):
        service.start_thumbnail('post', {'revision': 0})
    with service.connect() as db:
        assert db.execute('SELECT count(*) FROM thumbnail_jobs').fetchone()[0] == 0


def test_unreadable_owner_is_not_treated_as_dead(service):
    with service.connect() as db:
        db.execute('INSERT INTO thumbnail_jobs VALUES (?,?,?,?,?,?,?,?,?)',
                   ('job', 'post', 'running', 'working', 'text', 0, 0, 123, 1))
    with patch.object(thumbnails.psutil, 'Process', side_effect=psutil.AccessDenied(123)):
        assert thumbnails.job_status(service, 'post')['status'] == 'running'
    with patch.object(thumbnails.psutil, 'Process', side_effect=psutil.NoSuchProcess(123)):
        assert thumbnails.job_status(service, 'post')['status'] == 'failed'


def test_late_dead_owner_observation_cannot_overwrite_completion(service):
    with service.connect() as db:
        db.execute('INSERT INTO thumbnail_jobs VALUES (?,?,?,?,?,?,?,?,?)',
                   ('job', 'post', 'running', 'working', 'text', 0, 0, 123, 1))
        stale = db.execute('SELECT * FROM thumbnail_jobs').fetchone()
        db.execute("UPDATE thumbnail_jobs SET status='completed'")
        with patch.object(thumbnails.psutil, 'Process', side_effect=psutil.NoSuchProcess(123)):
            assert thumbnails._job_status(db, stale)['status'] == 'completed'
