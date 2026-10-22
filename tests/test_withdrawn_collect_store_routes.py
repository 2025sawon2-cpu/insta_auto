import copy
import json
from pathlib import Path

import pytest

from test_withdrawn_pending_integration import withdrawn


class RouteReached(Exception):
    pass


@pytest.mark.parametrize('change', [None, 'file', 'receipt_missing', 'receipt_identity', 'eligible', 'manual', 'restored'])
def test_actual_collect_selector_uses_current_withdrawal_inputs(tmp_path, monkeypatch, change):
    from hotpost import source_finder
    h, state, job, source, receipt = withdrawn(tmp_path)
    if change == 'file':
        Path(source['path']).write_bytes(b'changed footage')
    elif change == 'receipt_missing':
        receipt.unlink()
    elif change == 'receipt_identity':
        value = json.loads(receipt.read_text('utf8'))
        value['source_sha256'] = '0' * 64
        receipt.write_text(json.dumps(value), encoding='utf8')
    elif change == 'eligible':
        source['editing_eligible'] = True
    elif change == 'manual':
        source['manual_usage_review']['editing_eligible'] = True
    elif change == 'restored':
        source['reviewed_intervals'] = [{'source_start': 3, 'source_end': 4}]
    manifest = tmp_path / 'collect-route-manifest.json'
    manifest.write_text(json.dumps({'candidates': [], 'search_audit': []}), encoding='utf8')
    state['source_search_manifest_path'] = str(manifest)
    state['manifest_path'] = str(manifest)
    h.store.state = copy.deepcopy(state)
    before = copy.deepcopy(h.store.state)
    h._restore_source_attempt_history = lambda state, job: state
    h._review_deferred_downloads = lambda *args: None
    h._recover_local_source_intervals = lambda *args, **kwargs: None
    routes = []
    def find(*args, **kwargs):
        routes.append('fresh_search')
        raise RouteReached
    def records(files, path):
        assert files == []
        assert Path(path) == manifest
        routes.append('saved_local_review')
        raise RouteReached
    monkeypatch.setattr(source_finder, 'find_sources', find)
    h._source_records = records
    with pytest.raises(RouteReached):
        h._collect_source_attempt(state, job)
    assert routes == (['fresh_search'] if change is None else ['saved_local_review'])
    assert h.store.state['sources'] == before['sources']
    if change is None:
        assert h.store.state['sources'][0]['editing_eligible'] is False
        assert h.store.state['sources'][0]['manual_usage_review']['editing_eligible'] is False
