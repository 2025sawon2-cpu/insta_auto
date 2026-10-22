import copy
import json
from pathlib import Path

import pytest

from hotpost.source_review_withdrawals import apply_withdrawals, validate_plan
from test_source_rejected_local_pending import rejected, harness


def withdrawn(tmp_path):
    source = rejected(tmp_path)
    source['reviewed_intervals'] = [{'source_start': 0, 'source_end': 2}]
    h, state, job = harness(tmp_path, [source])
    folder = tmp_path / 'source_review_withdrawals'
    folder.mkdir()
    receipt = folder / (source['sha256'] + '.json')
    receipt.write_text(json.dumps({'source_sha256': source['sha256'], 'intervals': [
        {'source_start': 0, 'source_end': 2, 'reason': 'observed defect',
         'evidence': ['actual-review-frame.png']}]}), encoding='utf8')
    source = apply_withdrawals(h.settings, source)
    state['sources'] = [source]
    return h, state, job, source, receipt


def test_actual_withdrawal_ends_local_loop_and_stays_excluded(tmp_path):
    h, state, job, source, receipt = withdrawn(tmp_path)
    assert 'functional_review' not in source
    assert source['presentation_review_required'] is True
    assert source['manual_usage_review']['editing_eligible'] is False
    before = copy.deepcopy(state)
    h._review_source_records = lambda *args: pytest.fail('withdrawn footage requeued')
    for _ in range(3):
        assert h._review_pending_local_sources(state, job, lambda *args: None) is None
    assert state == before
    plan = {'sources': [source], 'shots': [{'id': 'shot', 'source_id': source['id'],
            'start': 0, 'end': 1}], 'beats': [{'id': 'beat', 'selected_shot_id': 'shot'}]}
    with pytest.raises(ValueError):
        validate_plan(h.settings, plan)


@pytest.mark.parametrize('change', ['file', 'receipt_missing', 'receipt_identity', 'eligible', 'manual', 'restored'])
def test_unverified_or_changed_withdrawal_cannot_skip_pending(tmp_path, change):
    h, state, job, source, receipt = withdrawn(tmp_path)
    if change == 'file': Path(source['path']).write_bytes(b'changed footage')
    if change == 'receipt_missing': receipt.unlink()
    if change == 'receipt_identity':
        value = json.loads(receipt.read_text('utf8'))
        value['source_sha256'] = '0' * 64
        receipt.write_text(json.dumps(value), encoding='utf8')
    if change == 'eligible': source['editing_eligible'] = True
    if change == 'manual': source['manual_usage_review']['editing_eligible'] = True
    if change == 'restored': source['reviewed_intervals'] = [{'source_start': 3, 'source_end': 4}]
    called = []
    def review(state, job, rows, progress):
        called.extend(rows)
        return rows, None
    h._review_source_records = review
    before = copy.deepcopy(state)
    assert h._review_pending_local_sources(state, job, lambda *args: None)['visual_review_only']
    assert len(called) == 1
    assert state == before
