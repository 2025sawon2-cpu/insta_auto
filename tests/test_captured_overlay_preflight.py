import copy
import json
import os
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost import source_finder, source_access_preflight
from hotpost.scene_requirements import clear_cached_review_errors
from hotpost.source_overlay_review import POLICY
from hotpost.source_preparation import preflight_preparation
from test_source_pause_history import Harness, MemoryStore


def test_captured_failure_preserves_denial_through_real_preflight(tmp_path, monkeypatch):
    captured = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    state = copy.deepcopy(captured['task'])
    job = copy.deepcopy(captured['job'])
    assert job['task_id'] == state['id']
    assert job['payload']['run_id'] == state['run_id']
    failures = [s for s in state['sources'] if s.get('overlay_review_error')
        and s.get('overlay_review_attempted_policy') == POLICY
        and s.get('overlay_review_attempted_sha256') == s.get('sha256')
        and s.get('reviewed_intervals') and s.get('mask_review')]
    assert failures, 'Captured input must retain the causal settled failure'
    before = copy.deepcopy(failures)
    for source in failures:
        assert source['editing_eligible'] is False
        clear_cached_review_errors(source)
    assert failures == before
    paths = {}
    def isolate(value):
        if isinstance(value, dict):
            return {isolate(k):isolate(v) for k,v in value.items()}
        if isinstance(value, list):
            return [isolate(v) for v in value]
        if isinstance(value, str) and PureWindowsPath(value).is_absolute():
            if value not in paths:
                paths[value] = str(tmp_path / ('unavailable-%d' % len(paths)))
            return paths[value]
        return value
    # Historical paths remain unavailable inside this isolated copy. This
    # tests the no-existing-bundle preparation branch, not history recovery.
    state, job = isolate(state), isolate(job)
    reference = tmp_path / 'reference.mp4'
    reference.write_bytes(b'isolated authoritative reference')
    state['reference_video'] = str(reference)
    settings = Settings(data_dir=tmp_path)
    settings.source_browser_search = True
    monkeypatch.setattr(source_finder, '_post', lambda *a: SimpleNamespace(caption='captured reference'))
    monkeypatch.setattr(source_finder, '_transcript_evidence', lambda *a: {'speech':'', 'screen_text':''})
    assert preflight_preparation(settings, state, job) == (None, [])
    h = Harness()
    h.settings = settings
    h.store = MemoryStore(state)
    observations = [{'provider':'tiktok','status':'ready','reason':'isolated browser observation'},
        {'provider':'youtube','status':'login_required','reason':'isolated login wall'}]
    monkeypatch.setattr(source_access_preflight, 'current_routes', lambda *a: copy.deepcopy(observations))
    ready = h._source_access_gate(state, job)
    assert ready == ['tiktok']
    checkpoint = job['checkpoint']['source_access_preflight']
    assert checkpoint['ready_routes'] == ['tiktok']
    assert any(r['status'] == 'login_required' for r in checkpoint['observations'])
    assert h.store.state['sources'] == state['sources']
    assert (state['id'],job['id'],state['run_id']) == (captured['task']['id'],captured['job']['id'],captured['task']['run_id'])
    monkeypatch.setattr(source_access_preflight, 'current_routes', lambda *a: [dict(r,status='login_required') for r in observations])
    with pytest.raises(source_access_preflight.SourceAccessWaiting):
        h._source_access_gate(state, job)
    reference.unlink()
    with pytest.raises(source_access_preflight.SourceAccessWaiting):
        h._source_access_gate(state, job)
    assert captured == json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
