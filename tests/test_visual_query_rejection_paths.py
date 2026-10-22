import json
from types import SimpleNamespace

import pytest

from hotpost import source_visual_queries as visual


def test_rejection_paths(tmp_path, monkeypatch):
    # Keep real atomic writes within ordinary isolated Windows paths.
    original_digest = visual.digest
    monkeypatch.setattr(visual, 'digest', lambda value: original_digest(value)[:8])
    reference = tmp_path / 'reference.mp4'
    frame = tmp_path / 'frame.jpg'
    reference.write_bytes(b'reference')
    frame.write_bytes(b'frame')
    settings = SimpleNamespace(data_dir=tmp_path)
    monkeypatch.setattr('hotpost.visual_media.frame_inline_data',
                        lambda *args, **kwargs: {'mimeType': 'image/jpeg', 'data': 'AA=='})
    calls = []
    proposal = {'observations': [], 'queries': []}
    review = {'subject_identity_supported': False, 'core_identity_complete': False}

    def generate(settings, prompt, data, **kwargs):
        calls.append(data)
        return review if 'proposal_sha256' in data else proposal

    def reject(*args):
        raise ValueError('independent identity rejection')

    monkeypatch.setattr(visual, 'validate', reject)
    evidence = visual.binding(reference, [frame], 'caption', {},
                              search_minimums={'en': 5, 'zh': 5})
    root = tmp_path / 'source-visual-queries' / visual.digest(evidence)
    saved = None
    for attempt in range(2):
        with pytest.raises(ValueError) as caught:
            visual.cached_visual_queries(settings, reference, [frame], 'caption', {},
                                         generate, search_minimums={'en': 5, 'zh': 5})
        message = str(caught.value)
        assert 'independent identity rejection' in message
        assert str((root / 'proposal.json').resolve()) in message
        assert str((root / 'review.json').resolve()) in message
        assert isinstance(caught.value.__cause__, ValueError)
        assert not (root / 'receipt.json').exists()
        current = {name: (root / name).read_bytes()
                   for name in ('proposal.json', 'review.json')}
        if saved is not None:
            assert current == saved
        saved = current
    assert len(calls) == 2
    assert json.loads(saved['proposal.json'])['proposal'] == proposal
    assert json.loads(saved['review.json']) == review
