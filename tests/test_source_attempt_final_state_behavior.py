import copy
import json

import pytest

from test_source_rejected_local_pending import harness
from hotpost import source_finder, source_coverage, studio_sources
from hotpost.source_pause_receipts import binding, snapshot, SourceReceiptWaiting


def test_collect_callback_uses_refreshed_scope_and_rejects_foreign_evidence(tmp_path, monkeypatch):
    h, state, job = harness(tmp_path, [])
    state['run_id'] = 'run-current'
    state['test_scope'] = 'old-product'
    h.store.state = copy.deepcopy(state)
    old_state = copy.deepcopy(state)
    # Isolate scope derivation; receipt creation and validation remain real.
    monkeypatch.setattr(source_coverage, 'diversity_required', lambda policy: True)
    monkeypatch.setattr(source_coverage, 'search_scope_for_state',
                        lambda s: {'product': s['test_scope']})
    monkeypatch.setattr(studio_sources, 'search_scope_for_state',
                        lambda s: {'product': s['test_scope']})
    monkeypatch.setattr(studio_sources, 'source_goal', lambda *a, **k: {'ready': False})
    h._review_deferred_downloads = lambda *a: None
    def refresh(*args, **kwargs):
        h.store.state['test_scope'] = 'final-product'
        return None
    h._recover_local_source_intervals = refresh
    root = h.settings.source_dir / 'apple-123'
    root.mkdir(parents=True)
    manifest = root / 'manifest.json'
    observed = []
    class DiscoveryObserved(Exception):
        pass
    def discover(settings, shortcode, progress, **kwargs):
        current = h.store.get(state['id'])
        scope = binding(current, job)
        assert scope['search_context'] == {'product': 'final-product'}
        data = {'job_id': root.name, 'shortcode': shortcode,
                'run_id': scope['run_id'], 'search_context': scope['search_context'],
                'search_audit': [], 'candidates': [], 'execution_audit_available': True}
        manifest.write_text(json.dumps(data), encoding='utf-8')
        progress.source_attempt_created(manifest)
        descriptor = job['checkpoint']['source_attempts'][-1]
        receipt = snapshot(settings.source_dir, descriptor, current, job)
        assert descriptor['search_context'] == scope['search_context']
        assert receipt['search_context'] == scope['search_context']
        assert h.store.checkpoints[-1]['source_attempts'][-1] == descriptor
        with pytest.raises(SourceReceiptWaiting):
            snapshot(settings.source_dir, descriptor, old_state, job)
        foreign_job = copy.deepcopy(job)
        foreign_job['id'] = 'other-collect-job'
        with pytest.raises(SourceReceiptWaiting):
            snapshot(settings.source_dir, descriptor, current, foreign_job)
        data['run_id'] = 'foreign-run'
        manifest.write_text(json.dumps(data), encoding='utf-8')
        with pytest.raises(SourceReceiptWaiting):
            snapshot(settings.source_dir, descriptor, current, job)
        observed.append(receipt)
        raise DiscoveryObserved()
    monkeypatch.setattr(source_finder, 'find_sources', discover)
    with pytest.raises(DiscoveryObserved):
        h._collect_source_attempt(state, job)
    assert len(observed) == 1
    assert h.store.state['sources'] == []
    assert h.store.state['source_acquisition']['queries'] == old_state['source_acquisition']['queries']
