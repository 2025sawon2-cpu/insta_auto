import copy
import hashlib
import json
from types import SimpleNamespace

import pytest
from hotpost import studio_sources
from hotpost.source_pause_receipts import SourceReceiptWaiting


def fixture_state(tmp_path):
    root = tmp_path / 'clip-123'
    root.mkdir()
    video = root / 'video.mp4'
    video.write_bytes(b'received media bytes')
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    manifest = root / 'manifest.json'
    manifest.write_text(json.dumps({'shortcode': 'clip', 'candidates': [{
        'file_sha256': digest, 'downloaded_file': 'video.mp4',
        'video_meta': {'duration': 5}, 'preview_file': 'preview.jpg'
    }]}), encoding='utf-8')
    state = {'id': 'task', 'shortcode': 'clip', 'run_id': 'run',
             'sources': [{'sha256': digest}], 'runs': [],
             'source_acquisition': {'interrupted_attempts': [{
                 'task_id': 'obsolete-task', 'studio_job_id': 'old-job',
                 'run_id': 'run', 'manifest_path': str(manifest),
                 'worker_checkpoints': []
             }]}}
    def unexpected_review(*args, **kwargs):
        pytest.fail('Unverified or already registered media reached local review')
    owner = SimpleNamespace(settings=SimpleNamespace(source_dir=tmp_path),
                            _source_records=unexpected_review)
    classes = [value for value in vars(studio_sources).values()
               if isinstance(value, type) and '_deferred_download_records' in value.__dict__]
    assert len(classes) == 1
    method = classes[0]._deferred_download_records
    return owner, state, method, video


def test_registered_candidates_do_not_require_obsolete_receipt_or_enter_review(tmp_path):
    owner, state, method, video = fixture_state(tmp_path)
    before = copy.deepcopy(state)
    records, origins = method(owner, state)
    assert records == []
    assert len(origins) == 1
    assert state == before
    assert video.read_bytes() == b'received media bytes'


def test_new_candidate_still_requires_real_receipt_binding(tmp_path):
    owner, state, method, _ = fixture_state(tmp_path)
    state['sources'] = []
    before = copy.deepcopy(state)
    with pytest.raises(SourceReceiptWaiting, match='결속'):
        method(owner, state)
    assert state == before


def test_new_candidate_with_changed_bytes_is_blocked(tmp_path):
    owner, state, method, video = fixture_state(tmp_path)
    state['sources'] = []
    video.write_bytes(b'changed bytes')
    before = copy.deepcopy(state)
    with pytest.raises(SourceReceiptWaiting, match='SHA'):
        method(owner, state)
    assert state == before
