"""The isolated search worker must retain the controller's browser restrictions."""
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost import source_browser_runtime, source_browser_worker


@pytest.mark.parametrize('enabled', [False, True])
def test_isolated_search_preserves_same_window_flags(tmp_path, monkeypatch, enabled):
    settings = Settings(data_dir=tmp_path,
                        source_browser_allow_same_window_tabs=enabled,
                        source_browser_existing_window_only=enabled)
    monkeypatch.setattr(source_browser_runtime, 'endpoint', lambda _: 'http://127.0.0.1:2211')
    captured = {}

    def capture(command, payload, checkpoint, timeout, progress=None):
        captured.update(payload)
        return {'candidates': [], 'terms': [], 'notes': [], 'searches': []}

    monkeypatch.setattr(source_browser_worker, 'run_bounded', capture)
    source_browser_worker.isolated_search(settings, [], ['steam cleaner'], 1, tmp_path / 'debug')
    child_values = dict(captured['settings'])
    assert child_values['source_browser_allow_same_window_tabs'] is enabled
    assert child_values['source_browser_existing_window_only'] is enabled
    child_values['data_dir'] = Path(child_values['data_dir'])
    child = Settings(**child_values)
    assert child.source_browser_allow_same_window_tabs is enabled
    assert child.source_browser_existing_window_only is enabled
