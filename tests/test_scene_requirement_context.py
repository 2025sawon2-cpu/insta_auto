import hashlib
import json

import pytest

from hotpost.scene_requirement_context import (
    POLICY, SCENE_CONTEXT_INSTRUCTION, build_scene_requirement_context,
)


def fixture(tmp_path):
    texts = ['저녁 준비하다', '깨가 싱크대 밑으로', '굴러가면 꺼내기 번거롭잖아요',
             '이 매트는 L자로 꺾인', '끝을 틈새에 끼워', '그 길을 가려줘요',
             '위에 묻은 소스는 물티슈로 닦으면 되고']
    script = ' '.join(texts[:3]) + '. ' + ' '.join(texts[3:6]) + '. ' + texts[6] + '.'
    plan = {'script_text': script,
        'narration_priority': {'script_id': 'script-current',
                              'script_sha256': hashlib.sha256(script.encode()).hexdigest()},
        'beats': [{'id': f'beat-{i+4}', 'text': text, 'start': i, 'end': i+1,
                   'selected_shot_id': 'old-failed-shot', 'source_start': 9+i,
                   'source_end': 10+i} for i, text in enumerate(texts)],
        'shots': [{'id': 'old-failed-shot', 'source_id': 'old-source', 'sha256': 'old-sha'}]}
    plan_path = tmp_path / 'timeline.json'
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
    reference = tmp_path / 'reference.mp4'
    reference.write_bytes(b'reference-evidence-test')
    state = {'script_id': 'script-current', 'approved_script_id': 'script-current',
        'scripts': [{'id': 'script-current', 'text': script},
                    {'id': 'script-old', 'text': '별도 차단재를 설치해요.'}],
        'edit_id': 'edit-current', 'edits': [{'id': 'edit-current', 'script_id': 'script-current',
                                             'plan_path': str(plan_path)}],
        'product': '주방 매트', 'title': '주방매트',
        'original_text': '이 매트 끝부분이 엘자로 꺾여 틈새로 들어가요.',
        'reference_video': str(reference),
        'sources': [{'id': 'separate-strip', 'sha256': 'strip-sha', 'source_role': 'context',
            'functional_review': {'reviewed': True, 'source_sha256': 'strip-sha',
                'same_core_function': True, 'context_usable': True,
                'differences': ['넓은 매트 옆에 별도 좁은 투명 차단재'],
                'observed_actions': ['별도 차단재 설치'],
                'context_usage_limits': ['매트 자체의 끝이라고 주장하지 않음'],
                'matched_reference_features': ['싱크대 틈새 차단']},
            'usage_limits': ['설치 맥락 보조만 사용']}],
    }
    requirement = {'kind': 'scene_gap', 'beat_id': 'beat-8', 'reason': '끝을 끼우는 실제 장면'}
    return state, plan, plan_path, requirement


def write_plan(path, plan):
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')


def test_approved_actual_narration_neighbors_preserve_product_ownership_and_limits(tmp_path):
    state, plan, path, requirement = fixture(tmp_path)
    result = build_scene_requirement_context(state, [requirement])
    assert result['verified'] and result['policy'] == POLICY
    assert result['selected_narration']['text'] == state['scripts'][0]['text']
    assert result['selected_edit']['plan_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    context = result['requirement_contexts'][0]
    assert context['narration'] == '끝을 틈새에 끼워'
    assert '이 매트는 L자로 꺾인' in context['context_text']
    assert '그 길을 가려줘요' in context['context_text']
    assert context['target'][0]['selected_source_id'] == 'old-source'
    assert result['selected_edit']['existing_selection_role'] == 'failed_context_not_candidate_approval'
    original = result['original_product_evidence']
    assert original['text'] == state['original_text']
    assert original['reference_video_sha256'] == hashlib.sha256(b'reference-evidence-test').hexdigest()
    limits = result['source_function_limits'][0]
    assert limits['review_hash_bound'] and limits['same_core_function'] is True
    assert limits['differences'] == ['넓은 매트 옆에 별도 좁은 투명 차단재']
    assert limits['context_usage_limits'] == ['매트 자체의 끝이라고 주장하지 않음']
    assert limits['source_usage_limits'] == ['설치 맥락 보조만 사용']
    assert 'separate accessory' in SCENE_CONTEXT_INSTRUCTION
    assert 'minor color/material/design variations' in SCENE_CONTEXT_INSTRUCTION


@pytest.mark.parametrize('mutation,hold', [
    ('approval', 'selected_script_not_approved'),
    ('script-hash', 'selected_script_hash_mismatch'),
    ('edit-script', 'selected_plan_narration_mismatch'),
    ('plan-text', 'selected_plan_narration_mismatch'),
    ('priority-id', 'selected_plan_script_id_mismatch'),
    ('priority-hash', 'selected_plan_script_hash_mismatch'),
    ('voice-id', 'selected_plan_voice_script_mismatch'),
    ('plan-hash', 'selected_plan_hash_mismatch'),
    ('beat-text', 'selected_plan_beat_narration_mismatch'),
])
def test_stale_or_unapproved_selected_context_holds(tmp_path, mutation, hold):
    state, plan, path, requirement = fixture(tmp_path)
    if mutation == 'approval': state['approved_script_id'] = 'script-old'
    if mutation == 'script-hash': state['scripts'][0]['sha256'] = 'incorrect'
    if mutation == 'edit-script': state['edits'][0]['script_id'] = 'script-old'
    if mutation == 'plan-text': plan['script_text'] = '별도 차단재를 설치해요.'
    if mutation == 'priority-id': plan['narration_priority']['script_id'] = 'script-old'
    if mutation == 'priority-hash': plan['narration_priority']['script_sha256'] = 'incorrect'
    if mutation == 'voice-id': plan['voice'] = {'script_id': 'script-old'}
    if mutation == 'plan-hash': state['edits'][0]['plan_sha256'] = 'incorrect'
    if mutation == 'beat-text': plan['beats'][3]['text'] = '별도 차단재의 끝을'
    write_plan(path, plan)
    result = build_scene_requirement_context(state, [requirement])
    assert not result['verified'] and hold in result['holds']
    assert not result['selected_edit']['script_binding_verified']


def test_missing_actual_beat_holds_instead_of_using_issue_text_as_narration(tmp_path):
    state, _, _, requirement = fixture(tmp_path)
    requirement.update(beat_id='beat-absent', reason='대본처럼 보이는 과거 메모')
    result = build_scene_requirement_context(state, [requirement])
    assert not result['verified']
    assert 'required_beat_not_in_selected_plan:beat-absent' in result['holds']
    assert result['requirement_contexts'][0]['narration'] == ''
    assert result['requirement_contexts'][0]['target'] == []


def test_context_signature_tracks_actual_plan_script_original_and_function_limits(tmp_path):
    state, plan, path, requirement = fixture(tmp_path)
    original = build_scene_requirement_context(state, [requirement])
    assert original['signature'] == build_scene_requirement_context(state, [requirement])['signature']
    state['sources'][0]['functional_review']['differences'].append('미세한 색상 차이')
    changed = build_scene_requirement_context(state, [requirement])
    assert changed['verified'] and changed['signature'] != original['signature']
    state['original_text'] += ' 쿠션감도 있어요.'
    changed_original = build_scene_requirement_context(state, [requirement])
    assert changed_original['signature'] != changed['signature']
    plan['beats'][4]['source_start'] += 0.1
    write_plan(path, plan)
    changed_plan = build_scene_requirement_context(state, [requirement])
    assert changed_plan['verified'] and changed_plan['signature'] != changed_original['signature']


def test_invalid_beat_text_returns_hold_without_crashing_or_inventing_context(tmp_path):
    state, plan, path, requirement = fixture(tmp_path)
    plan['beats'][4]['text'] = None
    write_plan(path, plan)
    result = build_scene_requirement_context(state, [requirement])
    assert not result['verified'] and 'selected_plan_beat_narration_missing' in result['holds']
    assert result['requirement_contexts'][0]['narration'] == ''


def test_global_requirement_uses_whole_actual_approved_narration(tmp_path):
    state, plan, _, _ = fixture(tmp_path)
    result = build_scene_requirement_context(state, [{'kind': 'source_fit', 'reason': '제품 구조 전체'}])
    assert result['verified']
    context = result['requirement_contexts'][0]
    assert len(context['target']) == len(plan['beats'])
    assert '이 매트는 L자로 꺾인 끝을 틈새에 끼워' in context['narration']
    assert context['before'] == [] and context['after'] == []


def test_generic_plan_script_text_binding_does_not_require_optional_voice_script_id(tmp_path):
    state, plan, path, requirement = fixture(tmp_path)
    plan.pop('narration_priority')
    plan['voice'] = {'id': 'voice-current'}
    write_plan(path, plan)
    result = build_scene_requirement_context(state, [requirement])
    assert result['verified'] and result['selected_edit']['script_binding_verified']


def test_final_plan_cannot_rewrite_neighbor_while_required_target_and_script_text_stay_same(tmp_path):
    from pathlib import Path
    from hotpost.config import Settings
    from hotpost.daily_quality import QualitySceneGap
    from hotpost.scene_requirements import assess, validate_selected_scenes
    from test_scene_requirement_intervals import approved, coverage

    state = approved(tmp_path)
    state['daily_quality']['scene_requirements'] = assess(Settings(data_dir=tmp_path), state,
        generate=lambda *args, **kwargs: coverage(state['sources'][0]))
    source = state['sources'][0]
    path = state['edits'][0]['plan_path']
    actual_beats = json.loads(Path(path).read_text(encoding='utf-8'))['beats']
    plan = {'script_text': state['scripts'][0]['text'], 'beats': actual_beats,
        'shots': [{'id': 'shot', 'source_id': source['id'], 'sha256': source['sha256'],
                   'path': source['path'], 'start': 1, 'end': 3}]}
    target = next(row for row in plan['beats'] if row['id'] == 'b1')
    target.update(source_start=1.5, source_end=2.1, selected_shot_id='shot')
    plan['beats'][0]['text'] = 'The separate transparent strip is installed.'
    assert plan['script_text'] == state['scripts'][0]['text']
    assert next(b for b in plan['beats'] if b['id'] == 'b1')['text'] == 'Observed action.'
    with pytest.raises(QualitySceneGap):
        validate_selected_scenes(state, plan)
