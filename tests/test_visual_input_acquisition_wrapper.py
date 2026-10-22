import json
from types import SimpleNamespace

import pytest

from hotpost import source_finder


def test_real_find_sources_preserves_input_hook_and_rejection(tmp_path, monkeypatch):
    owner = {'task_id': 'task-one', 'job_id': 'job-one', 'run_id': 'run-one'}
    checkpoints = []
    manifests = []
    failure = ValueError('independent identity rejection')

    def progress(message, pct):
        pass

    def capture(input_sha):
        checkpoints.append({**owner, 'input_sha256': input_sha})
        return owner

    progress.visual_query_input = capture
    progress.source_attempt_created = manifests.append
    cancel = lambda: None
    progress.check_cancel = cancel

    def acquisition(settings, shortcode, wrapped, **kwargs):
        assert wrapped is not progress
        assert wrapped.visual_query_input is capture
        assert wrapped.check_cancel is cancel
        assert wrapped.visual_query_input('actual-input-sha') == owner
        raise failure

    monkeypatch.setattr(source_finder, '_find_sources', acquisition)
    monkeypatch.setattr('hotpost.source_outcomes.platform_outcomes', lambda *args: {})
    settings = SimpleNamespace(source_dir=tmp_path)
    context = {'run_id': 'run-one', 'source_policy': {
        'minimum_total': 5, 'platform_minimums': {}}}
    with pytest.raises(ValueError) as caught:
        source_finder.find_sources(settings, 'Example123', progress, search_context=context)
    assert caught.value is failure
    assert checkpoints == [{**owner, 'input_sha256': 'actual-input-sha'}]
    assert len(manifests) == 1
    receipt = json.loads(manifests[0].read_text(encoding='utf-8'))
    assert receipt['status'] == 'failed'
    assert receipt['failure']['type'] == 'ValueError'
    assert receipt['run_id'] == 'run-one'
    assert receipt['candidates'] == []


def test_real_find_sources_does_not_invent_input_hook(tmp_path, monkeypatch):
    def acquisition(settings, shortcode, wrapped, **kwargs):
        assert wrapped.visual_query_input is None
        return {'status': 'stubbed'}

    monkeypatch.setattr(source_finder, '_find_sources', acquisition)
    monkeypatch.setattr('hotpost.source_outcomes.platform_outcomes', lambda *args: {})
    context = {'source_policy': {'minimum_total': 5, 'platform_minimums': {}}}
    result = source_finder.find_sources(
        SimpleNamespace(source_dir=tmp_path), 'Example123', search_context=context)
    assert result == {'status': 'stubbed'}
