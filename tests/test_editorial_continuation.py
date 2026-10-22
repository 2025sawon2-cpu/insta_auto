import copy
from types import SimpleNamespace

import pytest

from hotpost.editorial_continuation import extension_scope, review_extension
from hotpost.source_quality import sha256_file


def source(tmp_path):
    path = tmp_path / 'original.mp4'
    path.write_bytes(b'unchanged original')
    return {'id': 'source', 'path': str(path), 'sha256': sha256_file(path),
            'video_meta': {'duration': 10.},
            'reviewed_intervals': [{'source_start': 2., 'source_end': 3.}],
            'mask_review': {'source_sha256': sha256_file(path)}}


def test_short_extension_is_real_adjacent_original_not_minimum_recovery_window(tmp_path):
    s = source(tmp_path)
    scope = extension_scope(s, {'start': 2., 'end': 3.}, 1.45)
    assert scope['start'] == 2.
    assert 3.45 <= scope['end'] < 3.51
    assert scope['intervals'] == [[2., scope['end']]]
    assert s['reviewed_intervals'] == [{'source_start': 2., 'source_end': 3.}]


def test_exact_file_end_is_usable_without_unnecessary_spare_frame(tmp_path):
    s = source(tmp_path)
    s['video_meta']['duration'] = 2.
    s['reviewed_intervals'] = [{'source_start': 1., 'source_end': 2.}]
    assert extension_scope(s, {'start': 1., 'end': 2.}, 2.)['intervals'] == [[0., 2.]]
    assert extension_scope(s, {'start': 1., 'end': 2.}, 2.1) is None


def test_continuation_cannot_resurrect_actually_withdrawn_frames(tmp_path):
    s = source(tmp_path)
    s['source_interval_withdrawal'] = {'intervals': [{'source_start': 3., 'source_end': 4.}]}
    assert extension_scope(s, {'start': 2., 'end': 3.}, 1.45) is None


def test_review_cannot_discard_old_approved_scope_or_auto_retry_same_rejection(tmp_path, monkeypatch):
    s = source(tmp_path)
    before = copy.deepcopy(s)
    scope = extension_scope(s, {'start': 2., 'end': 3.}, 1.45)
    calls = []
    def overlay(*args, **kwargs):
        calls.append(kwargs['intervals'])
        return {**s, 'reviewed_intervals': [{'source_start': 3., 'source_end': 3.5}]}
    monkeypatch.setattr('hotpost.source_overlay_review.review_source_overlays', overlay)
    review = lambda value: pytest.fail('lost prior scope must not reach functional approval')
    assert review_extension(SimpleNamespace(), s, scope, tmp_path / 'receipts', review) is None
    assert review_extension(SimpleNamespace(), s, scope, tmp_path / 'receipts', review) is None
    assert len(calls) == 1
    assert s == before


def test_service_wait_preserves_retry_semantics_instead_of_content_failure(tmp_path, monkeypatch):
    from hotpost.model_service import ModelServiceUnavailable
    s = source(tmp_path)
    scope = extension_scope(s, {'start': 2., 'end': 3.}, 1.45)
    def overlay(*args, **kwargs):
        raise ModelServiceUnavailable('capacity', retry_at=0)
    monkeypatch.setattr('hotpost.source_overlay_review.review_source_overlays', overlay)
    with pytest.raises(ModelServiceUnavailable):
        review_extension(SimpleNamespace(), s, scope, tmp_path / 'receipts', lambda value: value)
    import json
    saved = json.loads(next((tmp_path / 'receipts').glob('extension-*.json')).read_text('utf8'))
    assert saved['status'] == 'service_wait'
