import copy
import inspect
import json
import textwrap
from pathlib import Path

import pytest

from hotpost import scene_requirements as requirements
from hotpost import source_finder
from hotpost.source_overlay_review import POLICY
from test_source_rejected_local_pending import rejected, harness


def incident(tmp_path):
    source = rejected(tmp_path)
    source.pop('functional_review')
    source.update(overlay_review_error='Accepted function frame is outside its bound interval',
        overlay_review_policy=POLICY, overlay_review_attempted_policy=POLICY,
        overlay_review_attempted_sha256=source['sha256'],
        mask_review={'source_sha256':source['sha256']},
        reviewed_intervals=[{'source_start':0.0,'source_end':4.0}])
    h, state, job = harness(tmp_path, [source])
    manifest = Path(state['manifest_path'])
    assert manifest.is_relative_to(tmp_path)
    manifest.write_text(json.dumps({'candidates': []}), encoding='utf8')
    return h, state, job


def test_same_failed_receipt_reaches_search_through_production_entry(tmp_path, monkeypatch):
    h, state, job = incident(tmp_path)
    before = copy.deepcopy(state)
    current = requirements.clear_cached_review_errors
    source = textwrap.dedent(inspect.getsource(current))
    old_source = source.replace('not settled_overlay_failure and ', '')
    assert old_source != source
    namespace = dict(vars(requirements))
    exec(compile(old_source, 'old-cached-error-route', 'exec'), namespace)
    monkeypatch.setattr(requirements, 'clear_cached_review_errors', namespace['clear_cached_review_errors'])
    # Old initialization clears the failure and enters local visual review,
    # which requests the absent reference rather than reaching fresh search.
    with pytest.raises(KeyError, match='reference_video'):
        h._collect_source_attempt(state, job)
    h, state, job = incident(tmp_path)
    monkeypatch.setattr(requirements, 'clear_cached_review_errors', current)
    reached = []
    class SearchReached(Exception):
        pass
    def search(*args, **kwargs):
        reached.append(kwargs)
        raise SearchReached
    monkeypatch.setattr(source_finder, 'find_sources', search)
    with pytest.raises(SearchReached):
        h._collect_source_attempt(state, job)
    assert len(reached) == 1
    assert job['id'] == 'new' and job['task_id'] == state['id'] == 'task'
    assert h.store.state['sources'] == before['sources']
    assert h.store.state['sources'][0]['editing_eligible'] is False
    assert h.store.state['sources'][0]['overlay_review_error'] == before['sources'][0]['overlay_review_error']


def test_persisted_failure_is_stable_and_changed_attempt_is_distinct(tmp_path):
    h, state, job = incident(tmp_path)
    source = state['sources'][0]
    before = copy.deepcopy(source)
    assert requirements.clear_cached_review_errors(source) is False
    assert requirements.clear_cached_review_errors(source) is False
    assert source == before
    source['overlay_review_attempted_sha256'] = 'old-file'
    assert requirements.clear_cached_review_errors(source) is True
    assert 'overlay_review_error' not in source
    assert source['editing_eligible'] is False
