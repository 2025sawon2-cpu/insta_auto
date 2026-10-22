import copy
import json
from pathlib import Path

import pytest

from test_source_pause_history import setup
from hotpost import source_coverage
from hotpost.source_pause_receipts import binding, SourceReceiptWaiting


@pytest.mark.parametrize('foreign_manifest', [False, True])
def test_exception_preserves_current_scope_without_accepting_foreign_run(tmp_path, monkeypatch, foreign_manifest):
    h, initial, job, manifest, progress = setup(tmp_path)
    initial['test_scope'] = 'old'
    h.store.state['test_scope'] = 'current'
    monkeypatch.setattr(source_coverage, 'diversity_required', lambda policy: True)
    monkeypatch.setattr(source_coverage, 'search_scope_for_state',
                        lambda state: {'product': state['test_scope']})
    before = copy.deepcopy(h.store.state)
    class AcquisitionStopped(Exception):
        pass
    def attempt(state, active_job):
        current = h.store.get(state['id'])
        active_job['checkpoint']['source_attempts'] = []
        callback = lambda *args: None
        h._bind_source_attempt_progress(current, active_job, callback)
        scope = binding(current, active_job)
        data = {'job_id': manifest.parent.name, 'shortcode': current['shortcode'],
                'run_id': 'foreign' if foreign_manifest else scope['run_id'],
                'search_context': scope['search_context'],
                'execution_audit_available': True, 'search_audit': [], 'candidates': []}
        manifest.write_text(json.dumps(data), encoding='utf-8')
        callback.source_attempt_created(manifest)
        raise AcquisitionStopped('original acquisition error')
    monkeypatch.setattr(h, '_collect_source_attempt', attempt)
    expected = SourceReceiptWaiting if foreign_manifest else AcquisitionStopped
    with pytest.raises(expected):
        h._collect_sources(initial, job)
    descriptor = job['checkpoint']['source_attempts'][0]
    assert descriptor['search_context'] == {'product': 'current'}
    assert h.store.state['sources'] == before['sources']
    assert h.store.state['scripts'] == before['scripts']
    assert h.store.state['voices'] == before['voices']
    assert h.store.state['source_acquisition']['queries'] == before['source_acquisition']['queries']
    data = json.loads(manifest.read_text(encoding='utf-8'))
    assert data['run_id'] == ('foreign' if foreign_manifest else initial['run_id'])
    if foreign_manifest:
        assert 'receipt_path' not in descriptor
        assert h.store.state['source_acquisition']['receipt_wait']['status'] == 'receipt_wait'
    else:
        assert descriptor.get('receipt_path')
        receipt = json.loads(Path(descriptor['receipt_path']).read_text(encoding='utf-8'))
        assert receipt['search_context'] == {'product': 'current'}
        assert receipt['run_id'] == initial['run_id']
