import json
from pathlib import Path
import sqlite3
import time

import pytest

from tools import sync_completed_exports as exports


@pytest.fixture
def installed(tmp_path):
    root, destination = tmp_path / 'data', tmp_path / 'destination'
    (root / 'studio').mkdir(parents=True)
    destination.mkdir()
    (root / 'video.mp4').write_bytes(b'completed-video')
    (root / 'cover.png').write_bytes(b'selected-cover')
    now = time.time()
    state = {'title': '수납선반', 'latest_completed_run_id': 'run',
             'runs': [{'id': 'run', 'status': 'completed', 'completed': now,
                       'artifacts': {'edit_id': 'edit'}}],
             'edits': [{'id': 'edit', 'export_verified': True,
                        'export_path': str(root / 'video.mp4'), 'cover_path': str(root / 'cover.png')}]}
    with sqlite3.connect(root / 'studio/studio.sqlite3') as db:
        db.execute('CREATE TABLE tasks(shortcode TEXT, state TEXT)')
        db.execute('INSERT INTO tasks VALUES (?,?)', ('abc', json.dumps(state)))
    config = root / 'local-services/completed-export.json'
    exports.save_json(config, {'data_dir': str(root), 'destination': str(destination), 'enabled_after': now-1})
    return root, destination, config, state


def update(root, state):
    with sqlite3.connect(root / 'studio/studio.sqlite3') as db:
        db.execute('UPDATE tasks SET state=?', (json.dumps(state),))


def test_pair_has_korean_date_topic_names_and_is_idempotent(installed):
    root, destination, config, state = installed
    before = (root / 'studio/studio.sqlite3').read_bytes()
    assert exports.sync(config)['copied_pairs'] == 1
    day = exports.datetime.fromtimestamp(state['runs'][0]['completed'], exports.KST).strftime('%Y-%m-%d')
    assert (destination / day / (day+'_수납선반.mp4')).read_bytes() == b'completed-video'
    assert (destination / day / (day+'_수납선반_썸네일.png')).read_bytes() == b'selected-cover'
    assert exports.sync(config)['copied_pairs'] == 0
    assert before == (root / 'studio/studio.sqlite3').read_bytes()


@pytest.mark.parametrize('mode', ['unfinished', 'unverified', 'missing-cover', 'outside-data', 'old'])
def test_only_new_complete_verified_pairs_are_saved(installed, mode):
    root, destination, config, state = installed
    if mode == 'unfinished':
        state['runs'][0]['status'] = 'running'
    elif mode == 'unverified':
        state['edits'][0]['export_verified'] = False
    elif mode == 'missing-cover':
        (root / 'cover.png').unlink()
    elif mode == 'outside-data':
        outside = root.parent / 'outside.png'
        outside.write_bytes(b'not-allowed')
        state['edits'][0]['cover_path'] = str(outside)
    else:
        state['runs'][0]['completed'] -= 100
    update(root, state)
    assert exports.sync(config)['eligible_pairs'] == 0
    assert not list(destination.rglob('*.mp4'))


def test_current_applied_thumbnail_and_video_export_together_and_keep_prior(installed):
    root, destination, config, state = installed
    assert exports.sync(config)['copied_pairs'] == 1
    (root / 'new.mp4').write_bytes(b'new-video-with-thumbnail')
    (root / 'new.png').write_bytes(b'new-selected-thumbnail')
    active = {'source_edit_id': 'edit', 'version': 'selected-v2', 'updated': time.time(),
              'final': str(root / 'new.mp4'), 'cover': str(root / 'new.png')}
    exports.save_json(root / 'post-preparations/abc/active.json', active)
    assert exports.sync(config)['copied_pairs'] == 1
    videos = sorted(destination.rglob('*.mp4'))
    assert len(videos) == 2
    revised = next(p for p in videos if p.stem.endswith('_02'))
    assert revised.read_bytes() == b'new-video-with-thumbnail'
    assert revised.with_name(revised.stem+'_썸네일.png').read_bytes() == b'new-selected-thumbnail'


def test_offline_destination_is_retried_and_existing_files_preserved(installed):
    root, destination, config, state = installed
    destination.rmdir()
    assert exports.sync(config)['errors']
    assert not destination.exists()
    destination.mkdir()
    day = exports.datetime.fromtimestamp(state['runs'][0]['completed'], exports.KST).strftime('%Y-%m-%d')
    (destination / day).mkdir()
    existing = destination / day / (day+'_수납선반.mp4')
    existing.write_bytes(b'user-file')
    assert exports.sync(config)['copied_pairs'] == 1
    assert existing.read_bytes() == b'user-file'
    assert any(p.stem.endswith('_02') for p in destination.rglob('*.mp4'))


def test_revision_changed_during_copy_does_not_publish_stale_pair(installed, monkeypatch):
    root, destination, config, state = installed
    original = exports.shutil.copyfile
    def changing(source, target):
        result = original(source, target)
        exports.save_json(root / 'post-preparations/abc/active.json', {'version': 'changed'})
        return result
    monkeypatch.setattr(exports.shutil, 'copyfile', changing)
    assert exports.sync(config)['errors']
    assert not list(destination.rglob('*.mp4'))
    assert not list(destination.rglob('*.partial'))


def test_interrupted_pair_publication_resumes_without_duplicate(installed, monkeypatch):
    root, destination, config, state = installed
    method = 'rename' if exports.os.name == 'nt' else 'link'
    original = getattr(exports.os, method)
    calls = []
    def interrupted(source, target):
        calls.append(target)
        if len(calls) == 2:
            raise OSError('drive disconnected')
        return original(source, target)
    monkeypatch.setattr(exports.os, method, interrupted)
    assert exports.sync(config)['errors']
    assert len(list(destination.rglob('*.mp4'))) == 1
    monkeypatch.setattr(exports.os, method, original)
    assert exports.sync(config)['copied_pairs'] == 1
    assert len(list(destination.rglob('*.mp4'))) == 1
    assert len(list(destination.rglob('*.png'))) == 1
