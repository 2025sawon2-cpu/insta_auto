import copy
import sqlite3
from types import SimpleNamespace

import pytest

from hotpost.daily_quality import DailyQualityMixin, QualitySceneGap, POLICY
from hotpost.quality_progress import observe, record_preparation_failure
from hotpost.scene_requirements import (
    anchor_selected_scenes, constrain_plan, coverage_current,
    input_signature, requirements_key, validate_selected_scenes,
)
from hotpost.scene_requirement_context import build_scene_requirement_context
from test_scene_requirement_proof_modes import fixture


def failed_render_state():
    return {'id': 'task', 'edit_id': 'old', 'scripts': [{'id': 's', 'text': 'approved'}],
            'voices': [{'id': 'v', 'sha256': 'approved'}], 'edits': [{'id': 'old'}],
            'automation': {'active': True}, 'run_id': 'run', 'script_id': 's', 'voice_id': 'v',
            'daily_quality': {'policy': POLICY, 'status': 'repair', 'pending': 'reediting',
                'repair_round': 2, 'render_accounting': [{'repair_charge': 1}],
                'reviews': [], 'feedback': [{'kind': 'repetition', 'beat_id': 'b', 'reason': 'actual repeat'}],
                'progress_policy': {'policy': 'quality-progress-20261013-v1',
                    'defects': {'repeat': {'status': 'unresolved'}},
                    'reviews': [{'identity': 'actual', 'defect_ids': ['repeat'], 'output': {}}],
                    'best': {'edit_id': 'old'}, 'attempts': [
                        {'key': 'render', 'stage': 'render', 'status': 'failed'},
                        {'key': 'method', 'stage': 'reedit', 'status': 'running', 'job_id': 'job'}],
                    'decisions': []}}}


def job():
    return {'id': 'job', 'payload': {'quality_method': {'key': 'method'}}, 'checkpoint': {'stage': 'selection'}}


def test_pre_render_report_never_resolves_or_imports_render_defects():
    state = failed_render_state()
    before = copy.deepcopy(state)
    assert observe(state, {'pre_render_scene_gap': True, 'edit_id': 'old',
        'passed': False, 'issues': [{'kind': 'scene_gap'}]})['preparation_failure']
    assert state == before


def test_claim_finished_preparation_failure_preserves_actual_output_and_usage():
    state = failed_render_state(); before = copy.deepcopy(state)
    mixin = DailyQualityMixin()
    mixin.store = SimpleNamespace(finish=lambda j, result, callback: callback(state, None, result))
    error = QualitySceneGap([{'kind': 'scene_gap', 'beat_id': 'b', 'reason': 'no linked window'}])
    mixin.handle_daily_scene_gap(job(), error)
    mixin.handle_daily_scene_gap(job(), error)
    q = state['daily_quality']; old = before['daily_quality']
    for key in ('reviews', 'feedback', 'repair_round', 'render_accounting'):
        assert q[key] == old[key]
    for key in ('defects', 'reviews', 'best'):
        assert q['progress_policy'][key] == old['progress_policy'][key]
    for key in ('scripts', 'voices', 'edits', 'edit_id'):
        assert state[key] == before[key]
    assert len(q['preparation_failures']) == 1
    assert q['progress_policy']['attempts'][1]['status'] == 'preparation_failed'
    assert q['pending'] == 'scene_wait'


def test_direct_pre_render_accept_also_preserves_feedback():
    state = failed_render_state(); before = copy.deepcopy(state['daily_quality']['feedback'])
    DailyQualityMixin().accept_daily_quality(state, job(), {'pre_render_scene_gap': True,
        'issues': [{'kind': 'scene_gap'}]}, None)
    assert state['daily_quality']['feedback'] == before


def test_terminal_collection_key_holds_without_new_queue_or_counter():
    state = failed_render_state(); state['daily_quality']['pending'] = 'recollect'
    state['daily_quality']['feedback'][0]['search_query'] = 'product'
    db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE jobs(id TEXT,status TEXT,key TEXT)')
    db.execute('INSERT INTO jobs VALUES(?,?,?)', ('done-source', 'done',
        'quality:run:2:collection:0:refresh_sources:old'))
    mixin = DailyQualityMixin()
    mixin.store = SimpleNamespace(enqueue=lambda *a: pytest.fail('terminal key cannot enqueue'))
    assert mixin.advance_daily_quality(state, db, None, None, None)
    assert state['daily_quality']['pending'] == 'scene_wait'
    assert state['daily_quality']['repair_round'] == 2
    assert 'collection_attempt' not in state['daily_quality']
    assert db.execute('SELECT count(*) FROM jobs').fetchone()[0] == 1
    db.close()


def repetition_fixture(tmp_path, duration=.946667):
    state, plan, _ = fixture(tmp_path, support=('1',))
    q = state['daily_quality']; q['feedback'][0]['kind'] = 'repetition'
    r = q['scene_requirements']; r['requirements'][0]['kind'] = 'repetition'
    r['signature'] = input_signature(state); r['requirements_key'] = requirements_key(state)
    r['context_signature'] = build_scene_requirement_context(state, q['feedback'])['signature']
    plan['beats'][0]['end'] = duration; plan['beats'][0]['source_end'] = duration
    return state, plan


def test_missing_semantic_option_links_only_exact_accepted_window(tmp_path):
    state, plan = repetition_fixture(tmp_path)
    base = plan['shots'][0]; base['end'] = 4
    base.update(observation='old unrelated semantic statement', selection_exclusion='old shot annotation')
    plan['beats'][0].update(options=[], selected_shot_id=None)
    assert coverage_current(state)
    constrain_plan(state, plan)
    option = plan['beats'][0]['options'][0]
    shot = next(s for s in plan['shots'] if s['id'] == option['shot_id'])
    assert (shot['start'], shot['end']) == pytest.approx((0, 1+1/30))
    assert option['relation'] == 'context' and option['action_match'] == 'not_established'
    assert 'observation' not in shot and 'selection_exclusion' not in shot
    plan['beats'][0].update(selected_shot_id=shot['id'], source_start=0, source_end=.946667)
    anchor_selected_scenes(state, plan); validate_selected_scenes(state, plan)
    assert plan['beats'][0]['source_end'] >= 1+1/30-1e-6


def test_repetition_native_frame_outside_short_cut_is_rejected(tmp_path):
    state, plan = repetition_fixture(tmp_path)
    with pytest.raises(QualitySceneGap): validate_selected_scenes(state, plan)
    before = copy.deepcopy(plan); plan['beats'][0]['end'] = 1.18; plan['beats'][0]['source_end'] = 1.18
    snapshot = copy.deepcopy(plan)
    with pytest.raises(QualitySceneGap, match='제품 매력') as caught:
        anchor_selected_scenes(state, plan)
    assert caught.value.issues[0]['failure_reason']
    assert caught.value.issues[0]['kind'] == 'repetition'
    assert plan == snapshot and before['script_text'] == plan['script_text']


@pytest.mark.parametrize('tamper', ['source', 'frame'])
def test_accepted_option_injection_cannot_use_changed_evidence(tmp_path, tamper):
    state, plan = repetition_fixture(tmp_path)
    plan['beats'][0].update(options=[], selected_shot_id=None)
    from pathlib import Path
    source = state['sources'][0]
    path = source['path'] if tamper == 'source' else source['mask_review']['evidence_frames'][1]['path']
    Path(path).write_bytes(b'changed')
    assert not coverage_current(state)
    constrain_plan(state, plan)
    assert plan['beats'][0]['options'] == []


def corrected_legacy_observation(tmp_path):
    from test_quality_progress_independent import fixture as actual_fixture
    state, document, review = actual_fixture(tmp_path)
    ledger = state['daily_quality']['progress_policy']
    raw = copy.deepcopy(ledger['reviews'][0])
    raw.update(identity='old-no-render-observation', defect_ids=['synthetic-gap'])
    ledger['reviews'].append(raw)
    ledger['defects']['synthetic-gap'] = {'id': 'synthetic-gap', 'kind': 'scene_gap',
        'status': 'preparation_only', 'target': 'body', 'history': []}
    ledger['observation_corrections'] = [{'review_identity': raw['identity'],
        'classification': 'preparation_only', 'previous': copy.deepcopy(raw)}]
    return state, document, raw


def test_corrected_observation_is_preserved_but_not_actual_comparison_baseline(tmp_path):
    from hotpost.quality_progress import actual_review_rows
    state, _, raw = corrected_legacy_observation(tmp_path)
    ledger = state['daily_quality']['progress_policy']; before = copy.deepcopy(ledger)
    assert [r['identity'] for r in actual_review_rows(ledger)] == [ledger['reviews'][0]['identity']]
    assert ledger == before and ledger['reviews'][-1] == raw


def test_same_actual_output_cannot_pass_after_legacy_preparation_correction(tmp_path):
    from test_quality_progress_independent import store_plan
    state, document, raw = corrected_legacy_observation(tmp_path)
    result = store_plan(tmp_path, state, document, 'unchanged-output')
    result.update(passed=True, issues=[])
    actual = observe(state, result)
    assert actual['conflict'] and not actual['passed'] and actual['resolved'] == []
    assert state['daily_quality']['progress_policy']['reviews'][-2] == raw


def test_changed_review_compares_original_defect_without_synthetic_regression(tmp_path):
    from test_quality_progress_independent import store_plan, plan as new_plan
    state, _, raw = corrected_legacy_observation(tmp_path)
    ledger = state['daily_quality']['progress_policy']; original = ledger['reviews'][0]['defect_ids']
    result = store_plan(tmp_path, state, new_plan('actual-new-source'), 'new-output')
    result.update(passed=True, issues=[])
    actual = observe(state, result)
    assert actual['passed'] and actual['resolved'] == original and actual['introduced'] == []
    assert 'synthetic-gap' not in actual['resolved']
    assert ledger['reviews'][-2] == raw
    assert ledger['observation_corrections'][0]['previous'] == raw


def test_initial_pre_render_scene_gap_resumes_deferred_sources_and_updates_frozen_run_inputs():
    from hotpost.quality_progress import resume_assessment
    from hotpost.studio_runtime.lifecycle import LifecycleMixin
    state = {
        'id': 'task', 'title': '몽벨 패딩', 'product': '몽벨 패딩', 'edit_id': None, 'edits': [],
        'script_id': 's1', 'voice_id': 'v1', 'run_id': 'run-1',
        'scripts': [{'id': 's1', 'text': 'approved'}],
        'voices': [{'id': 'v1', 'sha256': 'vsha'}],
        'runs': [{'id': 'run-1', 'inputs': {'source_ids': ['s-old']}}],
        'sources': [{'id': 's-old', 'sha256': 'sha-old', 'source_quality': 'clean-source',
                     'editing_eligible': True, 'video_meta': {'duration': 12.0},
                     'functional_review': {'reviewed': True, 'source_sha256': 'sha-old', 'same_core_function': True}}],
        'source_acquisition': {'rounds': [{'review_completion': {
            'reason': 'quota_met', 'deferred_sources': 2,
            'reviewed_source_sha256': ['sha-old'],
            'deferred_source_sha256': ['sha-new']}}]},
        'automation': {'active': False, 'protocol': 2},
        'daily_quality': {
            'policy': POLICY, 'status': 'waiting_for_sources', 'pending': 'scene_wait',
            'preparation_failures': [{'failure_reason': [
                {'kind': 'scene_gap', 'scope': 'cover', 'search_query': '몽벨 패딩 제품 단독'}]}],
        },
    }
    assert resume_assessment(state) is True
    assert state['daily_quality']['pending'] == 'recollect'
    enqueued = []
    mixin = DailyQualityMixin()
    mixin.store = SimpleNamespace(enqueue=lambda db, tid, stage, payload, key: enqueued.append((stage, payload, key)))
    assert mixin.advance_daily_quality(state, None, None, None, None) is True
    assert enqueued and enqueued[0][0] == 'refresh_sources'
    assert enqueued[0][1]['request'] == '몽벨 패딩 제품 단독'
    assert state['daily_quality']['pending'] == 'recollecting'

    class AcceptHarness(LifecycleMixin):
        settings = SimpleNamespace(source_min_usable=10.0)
        advanced = False
        def advance_workflow(self, s, db):
            self.advanced = True

    harness = AcceptHarness()
    new_source = {'id': 's-new', 'sha256': 'sha-new', 'source_quality': 'clean-source',
                  'editing_eligible': True, 'video_meta': {'duration': 10.0},
                  'functional_review': {'reviewed': True, 'source_sha256': 'sha-new', 'same_core_function': True}}
    harness._accept(state, {'id': 'job-refresh', 'kind': 'refresh_sources', 'payload': {'daily_quality_repair': True}}, {
        'sources': [new_source], 'source_search_manifest_path': 'manifest.json',
        'searches': [], 'attempted_urls': [], 'local_deferred_review': True,
        'review_completion': {'reviewed_source_sha256': ['sha-new']},
    }, None)
    assert harness.advanced is True
    assert state['runs'][0]['inputs']['source_ids'] == ['s-old', 's-new']
    assert 'pending' not in state['daily_quality']
    assert state['daily_quality']['status'] == 'pending'
    assert state['daily_quality']['resume_retry_count'] == 1
