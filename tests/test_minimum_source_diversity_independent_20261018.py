"""Independent counterexamples for minimum-five actual body parents.

Pure synthetic plans establish accounting/guard behavior, not source relevance,
actual search execution, media decoding, or visual quality. No live state is used.
"""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from hotpost.source_diversity import (
    SourceDiversityRequired,
    body_usage_report,
    parent_identity,
    policy_for_state,
    require_body_minimum,
)


POLICY = {'version': 'minimum-five-sources-v1', 'minimum_parent_sources': 5}


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def plan(count=5):
    sources = [{'id': f'source-{i}', 'sha256': sha(f'parent-{i}'),
                'path': f'isolated-parent-{i}.mp4'} for i in range(count)]
    shots = [{'id': f'shot-{i}', 'source_id': s['id'], 'sha256': s['sha256'],
              'start': 0., 'end': 10.} for i, s in enumerate(sources)]
    beats = [{'id': f'beat-{i}', 'text': f'related product/context {i}',
              'start': i + 1/30, 'end': i + 1 + 1/30,
              'selected_shot_id': shot['id'], 'source_start': 1., 'source_end': 2.,
              'options': [{'shot_id': row['id'], 'relation': 'context'} for row in shots]}
             for i, shot in enumerate(shots)]
    return {'fps': 30, 'duration': count + 1/30, 'sources': sources, 'shots': shots,
            'beats': beats, 'source_diversity_policy': copy.deepcopy(POLICY),
            'cover_spec': {'source': {'source_sha256': sha('cover-only')}}}


def assert_shortfall(document, used):
    before = copy.deepcopy(document)
    report = body_usage_report(document)
    assert report['enforced'] and report['minimum_parent_sources'] == 5
    assert report['used_parent_sources'] == used and report['shortfall'] == 5-used
    with pytest.raises(SourceDiversityRequired) as failure:
        require_body_minimum(document)
    assert failure.value.diagnostics['used_parent_sources'] == used
    assert failure.value.diagnostics['shortfall'] == 5-used
    assert document == before


def test_five_distinct_selected_body_parents_meet_the_new_contract_without_mutation():
    document = plan()
    before = copy.deepcopy(document)
    report = require_body_minimum(document)
    assert report['enforced'] and report['used_parent_sources'] == 5
    assert report['minimum_parent_sources'] == 5 and report['shortfall'] == 0
    assert set(report['parent_sha256s']) == {s['sha256'] for s in document['sources']}
    assert document == before


def test_five_eligible_inventory_sources_and_options_do_not_make_one_parent_edit_complete():
    document = plan()
    for beat in document['beats']:
        beat['selected_shot_id'] = 'shot-0'
    document['footage_diversity'] = {'parent_files': 5, 'used_files': 5}
    document['source_ids'] = [s['id'] for s in document['sources']]
    assert_shortfall(document, 1)


@pytest.mark.parametrize('same_parent', ['original_sha256', 'sha256'])
def test_five_derivatives_or_file_ids_of_one_parent_are_only_one_source(same_parent):
    document = plan()
    for source in document['sources']:
        source[same_parent] = sha('one-actual-parent')
    assert_shortfall(document, 1)


def test_parent_identity_uses_original_hash_before_derivative_hash_not_file_name():
    source = {'id': 'new-id', 'path': 'another-name.mp4', 'sha256': sha('derivative'),
              'original_sha256': sha('actual-parent')}
    assert parent_identity(source) == sha('actual-parent')
    assert parent_identity({'sha256': sha('full-parent')}) == sha('full-parent')
    assert not parent_identity({'id': 'invented-id', 'path': 'five-sources.mp4'})


def test_cover_only_fifth_parent_does_not_contribute_to_body_usage():
    document = plan()
    document['beats'] = document['beats'][:4]
    document['cover_spec']['source']['source_sha256'] = document['sources'][4]['sha256']
    assert_shortfall(document, 4)


def test_first_one_frame_cover_beat_cannot_supply_a_fifth_body_parent():
    document = plan()
    document['beats'][4].update(start=0., end=1/30)
    assert_shortfall(document, 4)


@pytest.mark.parametrize('invalid', ['output_zero', 'output_negative', 'source_zero', 'source_negative', 'no_output_frame'])
def test_non_exposed_or_non_positive_selected_windows_do_not_fill_the_fifth_source(invalid):
    document = plan()
    beat = document['beats'][4]
    if invalid == 'output_zero':
        beat.update(start=4., end=4.)
    elif invalid == 'output_negative':
        beat.update(start=4., end=3.)
    elif invalid == 'source_zero':
        beat.update(source_start=2., source_end=2.)
    elif invalid == 'source_negative':
        beat.update(source_start=2., source_end=1.)
    else:
        # Both global output positions round to tick 120: no actual 30fps frame.
        beat.update(start=4.001, end=4.002)
    assert_shortfall(document, 4)


def test_missing_hash_source_is_not_replaced_by_its_path_or_shot_id():
    document = plan()
    document['sources'][4].pop('sha256')
    assert_shortfall(document, 4)


def test_related_reaction_or_context_can_be_a_real_fifth_parent():
    document = plan()
    document['sources'][4]['source_role'] = 'context_only'
    document['shots'][4]['shot_presentation'] = {'product_visible': False, 'product_role': 'general_context'}
    assert require_body_minimum(document)['used_parent_sources'] == 5


def test_legacy_plan_is_not_retroactively_required_to_have_five_parents():
    document = plan(1)
    document.pop('source_diversity_policy')
    before = copy.deepcopy(document)
    report = require_body_minimum(document)
    assert not report['enforced'] and report['shortfall'] == 0
    assert document == before


def test_saved_legacy_run_does_not_inherit_a_new_state_level_source_policy():
    state = {'run_id': 'old-run', 'runs': [{'id': 'old-run', 'status': 'completed',
             'source_policy': {'version': 4}}],
             'source_policy': {'version': 5, 'source_diversity_policy': copy.deepcopy(POLICY)}}
    before = copy.deepcopy(state)
    assert not policy_for_state(state)
    assert state == before


def test_current_run_frozen_policy_wins_over_state_and_other_runs():
    frozen = copy.deepcopy(POLICY)
    state = {'run_id': 'selected', 'runs': [
        {'id': 'selected', 'source_policy': {'source_diversity_policy': frozen}},
        {'id': 'other', 'source_policy': {'source_diversity_policy': {**POLICY, 'minimum_parent_sources': 7}}}],
        'source_policy': {'source_diversity_policy': {**POLICY, 'minimum_parent_sources': 6}}}
    before = copy.deepcopy(state)
    assert policy_for_state(state) == frozen
    assert state == before


def test_state_policy_is_used_before_any_run_exists():
    state = {'source_policy': {'source_diversity_policy': copy.deepcopy(POLICY)}}
    assert policy_for_state(state) == POLICY


@pytest.mark.parametrize('invalid', [None, [], 'not-a-policy', {}, {'version': POLICY['version']},
    {'version': 'unknown-source-rule', 'minimum_parent_sources': 5},
    *[{'version': POLICY['version'], 'minimum_parent_sources': n} for n in (None, 0, 4, True, 5.0)]])
def test_explicit_invalid_policy_cannot_silently_opt_out_of_five_sources(invalid):
    document = plan(1)
    document['source_diversity_policy'] = invalid
    with pytest.raises(ValueError):
        require_body_minimum(document)


def test_same_actual_file_hash_with_conflicting_claimed_parent_hashes_is_not_five_sources():
    document = plan()
    for i, source in enumerate(document['sources']):
        source.update(sha256=sha('identical-actual-file'), original_sha256=sha(f'claimed-parent-{i}'))
    for shot in document['shots']:
        shot['sha256'] = sha('identical-actual-file')
    assert_shortfall(document, 1)


def test_expected_current_policy_cannot_be_removed_from_a_plan_to_bypass_completion():
    document = plan(1)
    document.pop('source_diversity_policy')
    with pytest.raises(SourceDiversityRequired) as failure:
        require_body_minimum(document, expected_policy=POLICY)
    assert failure.value.diagnostics['reason'] == 'policy_mismatch'


def quality_case(tmp_path, *, count=1, legacy=False, omit_plan_policy=False):
    from hotpost import daily_quality
    document = plan(count)
    if legacy or omit_plan_policy:
        document.pop('source_diversity_policy')
    video = tmp_path/'fixture-media-not-decoded.mp4'
    video.write_bytes(b'acceptance guard fixture; never a fabricated valid MP4')
    plan_path = tmp_path/'plan.json'
    plan_path.write_text(json.dumps(document), encoding='utf-8')
    edit = {'id': 'edit', 'preview_path': str(video), 'export_path': str(video),
            'plan_path': str(plan_path), 'quality_verified': True, 'export_verified': True}
    receipt = {'edit_id': 'edit', 'passed': True, 'issues': [], 'review_path': 'controlled-model-pass.json',
               'render_sha256': hashlib.sha256(video.read_bytes()).hexdigest(),
               'plan_sha256': hashlib.sha256(plan_path.read_bytes()).hexdigest()}
    policy = {'version': 4} if legacy else {'version': 5, 'source_diversity_policy': copy.deepcopy(POLICY)}
    state = {'id': 'isolated-minimum-five', 'run_id': 'run', 'runs': [
        {'id': 'run', 'source_policy': copy.deepcopy(policy)}], 'source_policy': policy,
        'edits': [edit], 'edit_id': 'edit', 'daily_quality': {'policy': daily_quality.POLICY,
            'status': 'passed', 'reviewed_edit_id': 'edit', 'reviews': [receipt]}}

    class Reviewer(daily_quality.DailyQualityMixin):
        def folder(self, task):
            return tmp_path
    return Reviewer(), state, edit, receipt


@pytest.mark.parametrize('omit_plan_policy', [False, True])
def test_quality_worker_rejects_body_shortfall_or_missing_policy_before_decode_and_model(tmp_path, monkeypatch, omit_plan_policy):
    from hotpost import daily_quality
    reviewer, state, edit, _ = quality_case(tmp_path, omit_plan_policy=omit_plan_policy)
    before = copy.deepcopy(state)
    monkeypatch.setattr(daily_quality.subprocess, 'run', lambda *a, **k: pytest.fail('Minimum gate must run before media decode'))
    monkeypatch.setattr('hotpost.script_rewriter._generate', lambda *a, **k: pytest.fail('No model may waive the body minimum'))
    with pytest.raises(SourceDiversityRequired):
        reviewer._quality_review(state, {'id': 'qa', 'payload': {'edit_id': edit['id']}})
    assert state == before


@pytest.mark.parametrize('omit_plan_policy', [False, True])
def test_a_model_pass_cannot_be_accepted_when_actual_selected_body_has_one_parent(tmp_path, omit_plan_policy):
    reviewer, state, _, controlled_pass = quality_case(tmp_path, omit_plan_policy=omit_plan_policy)
    before = copy.deepcopy(state)
    with pytest.raises(SourceDiversityRequired):
        reviewer.accept_daily_quality(state, {'id': 'qa', 'payload': {}}, controlled_pass, None)
    assert state == before


@pytest.mark.parametrize('quality_enabled', [False, True])
def test_export_completion_gate_is_independent_of_model_quality_enablement(tmp_path, quality_enabled):
    from hotpost.daily_quality import verified_quality_export
    _, state, edit, _ = quality_case(tmp_path)
    if not quality_enabled:
        state['daily_quality']['policy'] = 'quality-disabled'
    assert not verified_quality_export(state, edit)


def test_old_completed_single_parent_receipt_is_still_available_inside_new_state(tmp_path):
    from hotpost.daily_quality import verified_quality_export
    _, state, edit, _ = quality_case(tmp_path, legacy=True)
    state['source_policy'] = {'version': 5, 'source_diversity_policy': copy.deepcopy(POLICY)}
    before = copy.deepcopy(state)
    assert verified_quality_export(state, edit, historical=True)
    assert state == before


def test_new_five_parent_completion_is_not_blanket_rejected(tmp_path):
    from hotpost.daily_quality import verified_quality_export
    _, state, edit, _ = quality_case(tmp_path, count=5)
    assert verified_quality_export(state, edit)


def test_unmocked_new_store_default_freezes_real_v6_search_and_body_requirements(tmp_path):
    from hotpost.studio_store import StudioStore
    store = StudioStore(tmp_path/'genuine-v5-store')
    # Protocol 2 is the production entry point that actually calls init_run;
    # prepare=False only prevents a queued prepare job, not this run creation.
    state, created = store.create('minimum-five-default', 'related product',
                                  {'protocol': 2, 'active': False}, prepare=False)
    assert created and state['source_policy']['version'] == 6
    assert state['source_policy']['minimum_total'] == 5
    assert state['source_policy']['search_minimums'] == {'en': 5, 'zh': 5}
    assert state['source_policy']['source_diversity_policy'] == {**POLICY,'core_product_priority_version':'core-product-first-v1'}
    assert state['runs'][0]['source_policy'] == state['source_policy']
    assert policy_for_state(state) == {**POLICY,'core_product_priority_version':'core-product-first-v1'}


def test_explicit_null_on_a_frozen_new_run_is_invalid_not_a_legacy_opt_out():
    state = {'run_id': 'new-run', 'runs': [{'id': 'new-run', 'source_policy': {
        'version': 5, 'source_diversity_policy': None}}]}
    with pytest.raises(ValueError):
        policy_for_state(state)


def test_five_visual_cuts_can_supply_five_parents_inside_one_unchanged_narration_beat():
    document = plan()
    cuts = copy.deepcopy(document['beats'])
    parent = {**copy.deepcopy(cuts[0]), 'id': 'one-original-narration-beat',
              'end': document['duration'], 'source_end': 6., 'text': 'one unchanged sentence'}
    document['beats'] = [parent]
    document['visual_cuts'] = [{**cut, 'id': f'visual-cut-{i}',
                               'parent_beat_id': parent['id']} for i, cut in enumerate(cuts)]
    before = copy.deepcopy(document)
    report = require_body_minimum(document)
    assert report['used_parent_sources'] == 5 and report['shortfall'] == 0
    assert sum(report['source_frames'].values()) == 150
    assert document == before


def test_actual_visual_cut_usage_wins_over_five_parent_caption_beat_labels():
    document = plan()
    document['visual_cuts'] = [{**document['beats'][0], 'id': 'only-real-visual-cut',
                               'end': document['duration'], 'source_end': 6.,
                               'parent_beat_id': document['beats'][0]['id']}]
    assert_shortfall(document, 1)


def nested_plan():
    document = plan()
    cuts = copy.deepcopy(document['beats'])
    parent = {**copy.deepcopy(cuts[0]), 'id': 'parent-narration',
              'end': document['duration'], 'source_end': 6.}
    document['beats'] = [parent]
    document['visual_cuts'] = [{**cut, 'id': f'cut-{i}', 'parent_beat_id': parent['id']}
                               for i, cut in enumerate(cuts)]
    return document


def test_child_visual_cut_cannot_restore_a_withdrawn_source_interval(tmp_path):
    from types import SimpleNamespace
    from hotpost.source_review_withdrawals import validate_plan
    document = nested_plan()
    fifth = document['sources'][4]
    fifth['reviewed_intervals'] = [{'source_start': 0., 'source_end': 10.}]
    folder = tmp_path/'source_review_withdrawals'
    folder.mkdir()
    (folder/(fifth['sha256']+'.json')).write_text(json.dumps({
        'source_sha256': fifth['sha256'], 'intervals': [{'source_start': 1., 'source_end': 2.,
            'reason': 'actual output evidence withdrew this range', 'evidence': ['preserved-native-frame']}]}), encoding='utf-8')
    before = copy.deepcopy(document)
    with pytest.raises(ValueError, match='제외'):
        validate_plan(SimpleNamespace(data_dir=tmp_path), document)
    assert document == before


@pytest.mark.parametrize('explicit_user_crop', [False, True])
def test_each_child_visual_cut_keeps_its_own_reviewed_crop_unless_explicitly_overridden(monkeypatch, explicit_user_crop):
    from hotpost import source_presentation
    document = nested_plan()
    source = document['sources'][4]
    source['presentation_review'] = {'usable': True}
    document['shots'][4]['path'] = source['path']
    child = document['visual_cuts'][4]
    child['emphasis'] = 2
    if explicit_user_crop:
        child['presentation_crop_override'] = True
    # This is the existing receipt-validity port; no new model review is faked.
    monkeypatch.setattr(source_presentation, 'valid_review', lambda source: True)
    source_presentation.protect_automatic_crop(document)
    assert child['emphasis'] == 2  # Original caption/SFX emphasis is preserved.
    assert child.get('visual_emphasis', child['emphasis']) == (2 if explicit_user_crop else 0)


def native_cut_case(tmp_path):
    from test_scene_requirement_proof_modes_independent import scenario, response, review
    state, document = scenario(tmp_path)
    review(tmp_path, state, response(state))
    parent = document['beats'][0]
    document['visual_cuts'] = [
        {**copy.deepcopy(parent), 'id': 'support-without-required-frame', 'parent_beat_id': parent['id'],
         'start': 0., 'end': .473, 'source_start': 2., 'source_end': 2.473},
        {**copy.deepcopy(parent), 'id': 'actual-witness', 'parent_beat_id': parent['id'],
         'start': .473, 'end': .946, 'source_start': 1., 'source_end': 1.473},
    ]
    return state, document


def test_native_requirement_can_be_witnessed_by_second_actual_cut_without_requiring_every_support_cut(tmp_path):
    from hotpost.scene_requirements import anchor_selected_scenes, validate_selected_scenes
    state, document = native_cut_case(tmp_path)
    before = copy.deepcopy(document['beats'])
    validate_selected_scenes(state, document)
    anchor_selected_scenes(state, document)
    validate_selected_scenes(state, document)
    cuts = document['visual_cuts']
    assert cuts[1]['required_scene_anchor']['supporting_frame_ids'] == ['0']
    assert 'required_scene_anchor' not in cuts[0]
    assert (cuts[0]['source_start'], cuts[0]['source_end']) == (2., 2.473)
    assert [(b['id'], b['text'], b['start'], b['end']) for b in document['beats']] == [
        (b['id'], b['text'], b['start'], b['end']) for b in before]


def test_native_requirement_cannot_be_satisfied_by_unused_parent_selection_when_actual_cuts_lose_proof(tmp_path):
    from hotpost.daily_quality import QualitySceneGap
    from hotpost.scene_requirements import anchor_selected_scenes, validate_selected_scenes
    state, document = native_cut_case(tmp_path)
    document['visual_cuts'][1].update(source_start=2.5, source_end=2.973)
    # The parent's mirrored selection still includes support frame 0 at 1s;
    # only the actual output cuts decide whether it remains visible.
    assert document['beats'][0]['source_start'] == 1.
    before = copy.deepcopy(document)
    with pytest.raises(QualitySceneGap):
        validate_selected_scenes(state, document)
    # Anchoring may move a reviewed short cut to retain the actual proof.
    anchor_selected_scenes(state, document)
    validate_selected_scenes(state, document)
    assert document['visual_cuts'] != before['visual_cuts']


def test_recovery_signature_ignores_reworded_review_and_review_time_on_same_actual_footage(tmp_path):
    from hotpost.source_diversity import inventory_signature
    from test_source_diversity_acquisition_v5 import source
    state = {'sources': [source(tmp_path, 0, core=True)]}
    before = inventory_signature(state)
    changed = copy.deepcopy(state)
    changed['sources'][0]['functional_review'].update(reason='Same approved evidence, reworded', reviewed_at=1234.)
    assert inventory_signature(changed) == before


def test_recovery_signature_changes_for_new_actual_reviewed_window(tmp_path):
    from hotpost.source_diversity import inventory_signature
    from test_source_diversity_acquisition_v5 import source
    state = {'sources': [source(tmp_path, 0, core=True)]}
    state['sources'][0]['video_meta']['duration'] = 4.
    before = inventory_signature(state)
    state['sources'][0]['reviewed_intervals'][0]['source_end'] = 3.
    assert inventory_signature(state) != before


def test_same_actual_recovery_inventory_cannot_clear_gap_or_increment_new_edit_generation(tmp_path):
    from hotpost.source_diversity import inventory_signature
    from hotpost.studio_sources import resolve_diversity_recovery
    from test_source_diversity_acquisition_v5 import source
    state = {'sources': [source(tmp_path, 0, core=True)], 'source_diversity_generation': 2}
    state['source_diversity_gap'] = {'inventory_signature': inventory_signature(state)}
    before = copy.deepcopy(state)
    assert not resolve_diversity_recovery(state)
    assert state == before


def test_voice_only_fast_reuse_does_not_collapse_old_visual_cuts_to_first_mirrored_parent(tmp_path, monkeypatch):
    from hotpost import daily_quality
    from hotpost.studio_reviewed_scenes import approved_voice_scenes
    old = nested_plan()
    old['script_text'] = 'the same approved narration'
    path = tmp_path/'old-cut-layout.json'
    path.write_text(json.dumps(old), encoding='utf-8')
    state = {'run_id': 'new', 'voice_id': 'new-voice', 'runs': [
        {'id': 'old-run', 'artifacts': {'edit_id': 'old-edit'}},
        {'id': 'new', 'parent_id': 'old-run', 'inputs': {}}],
        'edits': [{'id': 'old-edit', 'voice_id': 'old-voice', 'plan_path': str(path)}]}
    fresh = copy.deepcopy(old)
    fresh.pop('visual_cuts')
    fresh['beats'][0]['end'] = .5
    # Approval validity is an existing independent boundary. This unit tests
    # only whether an approved multi-cut layout enters the one-shot fast path.
    monkeypatch.setattr(daily_quality, 'verified_quality_export', lambda *a, **k: True)
    before = copy.deepcopy(fresh)
    assert approved_voice_scenes(state, fresh) is None
    assert fresh == before
