import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hotpost import stage_gate
from hotpost.final_qa import digest

ID = {'video_id': 'post', 'task_id': 'task', 'run_id': 'run'}
SCRIPT = '같은 방인데, 침대 위에만 바람이 덜 닿아요! 댓글에 나도 남겨주세요.'


def test_proceed_review_cannot_hide_explicitly_banned_emotion(tmp_path):
    script = tmp_path / 'selected.txt'
    script.write_text('쉬는 시간이 괜히 반가워요.', 'utf-8')
    with pytest.raises(ValueError, match='사용자 금지 표현'):
        stage_gate._editorial_review({'review_kind': 'audience_hook_v2'},
                                    {'review': {'decision': 'proceed'}},
                                    {'selected_script': [{'path': str(script), 'sha256': digest(script)}]})


@pytest.fixture
def root(tmp_path, monkeypatch):
    """Isolated copy of the contract with stub rule files, so real doc edits never matter."""
    root = tmp_path / 'repo'
    contract = json.loads(stage_gate.CONTRACT.read_text('utf-8'))
    for rule in stage_gate.required_rules(contract):
        target = root / rule.relative_to(stage_gate.ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f'rule {target.name}', 'utf-8')
    (root / 'docs').mkdir(exist_ok=True)
    shutil.copy(stage_gate.CONTRACT, root / 'docs' / 'stage_contracts.json')
    monkeypatch.setattr(stage_gate, 'ROOT', root)
    monkeypatch.setattr(stage_gate, 'CONTRACT', root / 'docs' / 'stage_contracts.json')
    return root


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    elif isinstance(data, str):
        path.write_text(data, 'utf-8')
    else:
        path.write_text(json.dumps(data, ensure_ascii=False), 'utf-8')
    return path


@pytest.mark.parametrize('model', [None, 'previous-explicit-model'])
def test_official_writing_calls_do_not_require_a_dedicated_model(model):
    call = {'provider': 'codex', 'status': 'completed', 'fallback': False}
    if model:
        call['requested_model'] = model
    stage_gate._check_calls({'calls': [call], 'fallback': False}, 'Writing result')


@pytest.mark.parametrize('change', [
    {'provider': 'unofficial'}, {'status': 'failed'}, {'fallback': True}])
def test_removing_model_pin_preserves_official_call_evidence(change):
    call = {'provider': 'codex', 'status': 'completed', 'fallback': False, **change}
    with pytest.raises(ValueError, match='completed official Codex'):
        stage_gate._check_calls({'calls': [call]}, 'Writing result')


@pytest.fixture
def work(tmp_path):
    w = tmp_path / 'work'
    calls = [{'provider': 'codex', 'status': 'completed', 'model_selection': 'codex_cli_default', 'fallback': False}]
    files = {
        'source': write(w / 'BB01.mp4', b'source clip'),
        'writing': write(w / 'writing-result.json', {
            'type': 'scripts', 'scripts': [{'text': SCRIPT}, {'text': '둘째 안'}, {'text': '셋째 안'}],
            'generation_inference': {'calls': calls, 'fallback': False}}),
        'script': write(w / 'selected-script.txt', SCRIPT),
        'wav': write(w / 'narration.wav', b'voice'),
    }
    files['voice'] = write(w / 'voice-result.json', {
        'status': 'succeeded', 'style_verified': True,
        'provider':'google-ai-studio-browser','model':'gemini-3.8-flash-tts','voice_name':'Arlo',
        'style':__import__('hotpost.ai_studio_adapter',fromlist=['STYLE']).STYLE,
        'audio_sha256':digest(files['wav']),
        'text_sha256': hashlib.sha256(SCRIPT.encode()).hexdigest(),
        'seed_supported':False, 'seed':None, 'quality_mode':'google-ai-studio', 'segment_count': 1,
        'voice_profile_id': None, 'output_path': str(files['wav'])})
    files['plan'] = write(w / 'timeline.json', {
        'script_text': SCRIPT,
        'sources': [{'id': 'source-1', 'path': str(files['source']), 'sha256': digest(files['source'])}],
        'caption_semantic_contract': {'review': {'script_sha256': hashlib.sha256(SCRIPT.encode()).hexdigest()}},
        'narration_policy': {'profile': 'short_pauses_breath_v1'},
        'voice_source': {'sha256': digest(files['wav'])},
        'cover_text': '자리찾기\n더쉽게',
        'footage_selection_policy': 'diverse-sequential-v1',
        'source_diversity_policy': {'version': 'minimum-five-sources-v1', 'minimum_parent_sources': 5},
        'duration': 1.0,
        'shots': [{'id': 'shot-1', 'source_id': 'source-1', 'path': str(files['source']),
                   'sha256': digest(files['source']), 'start': 0.0, 'end': 4.0}],
        'beats': [{'id': 'beat-1', 'start': 0.0, 'end': 1.0, 'selected_shot_id': 'shot-1',
                   'source_start': 0.0, 'source_end': 1.0}],
        'rendered_clips': [{'beat_id': 'beat-1', 'selected_shot_id': 'shot-1', 'start': 0.0,
                            'source_sha256': digest(files['source']), 'duration': 1.0,
                            'selected_source_window': [0.0, 1.0]}]})
    video, cover = write(w / 'video.mp4', b'final'), write(w / 'cover.png', b'cover')
    files['video'] = video
    files['delivery'] = write(w / 'delivery-receipt.json', {
        'video': str(video), 'cover': str(cover), 'video_sha256': digest(video),
        'cover_sha256': digest(cover), 'full_decode': True, 'faststart': True})
    return files


def answers(stage, files=None):
    contract = json.loads(stage_gate.CONTRACT.read_text('utf-8'))
    result = {c['id']: {'answer': '확인함', 'evidence': ['frame 00:01']}
              for c in contract['stages'][stage]['checks']}
    if stage == 'script' and files:
        from hotpost.writing.hook_policy import first_sentence
        result['script_hook']['review'] = {
            'decision': 'proceed', 'script_sha256': digest(files['script']),
            'opening_quote': first_sentence(files['script'].read_text('utf-8').strip()),
            'target_audience': '3040 여성 중 이 생활 상황에 관심 있는 시청자',
            'viewer_interest': '작은 방의 생활 공간을 편하게 쓰고 싶은 관심',
            'why_keep_watching': '어떻게 침대 위 환경이 달라지는지 확인하고 싶음',
            'weakness_considered': '방향만 바뀌는 장면 해설과 실제 생활 이득을 구분',
            'thumbnail_lines': ['자리찾기', '더쉽게'],
            'thumbnail_interest': '제한된 공간을 다르게 쓰는 기대',
            'thumbnail_promise': '본문의 제품 쓰임으로 기대를 충족',
            'thumbnail_weakness_considered': '이미지 묘사만으로 끝나지 않는지 검토',
            'empathy_review': {'natural': True, 'quote': files['script'].read_text('utf-8').strip(),
                               'reason': '실제 사용에서 달라진 행동과 감정의 입말 연결을 검토'},
            'thumbnail_context_review': {'pre_view_relevant': True, 'core_appeal': '공간 활용',
                                         'expected_topic': '좁은 공간을 다르게 쓰는 방법',
                                         'reason': '대본을 모르고 대표 이미지와 문구만 보아도 같은 쓰임을 기대'}}
    if stage == 'edit' and files:
        try:
            usage = stage_gate.montage_usage(json.loads(files['plan'].read_text('utf-8')))
        except ValueError:
            usage = {}  # Invalid-source fixtures must reach the actual source-stage check.
        result['edit_scenes']['review'] = {
            'decision': 'proceed', 'plan_sha256': digest(files['plan']),
            'usage': usage,
            'sequence_assessment': '전체 화면의 장면 전개를 확인',
            'repetition_assessment': '사용 시간과 고유 구간을 비교해 반복을 판단',
            'script_visual_relation': '자막 시간과 독립적인 주제 중심 장면',
            'weakness_considered': '원본 개수만으로 시각적 다양성을 대신하지 않음'}
    return result


def outputs(files, stage):
    return {'source': {'sources': [str(files['source'])]},
            'script': {'writing_result': str(files['writing']), 'selected_script': str(files['script'])},
            'voice': {'voice_result': str(files['voice'])},
            'edit': {'plan': str(files['plan'])},
            'deliver': {'delivery_receipt': str(files['delivery'])}}[stage]


def run(gates, files, stage):
    stage_gate.begin(gates, stage, **ID)
    return stage_gate.end(gates, stage, answers=answers(stage, files), outputs=outputs(files, stage))


def test_contract_checks_cite_their_own_stage_rules_and_files_exist():
    contract = stage_gate.load_contract()
    for rule in stage_gate.required_rules(contract):
        assert rule.is_file(), rule


def test_full_chain_records_rules_and_outputs(root, work, tmp_path):
    gates = tmp_path / 'gates'
    started = stage_gate.begin(gates, 'source', **ID)
    assert any(r['path'].endswith('SOURCE_WORKFLOW.md') for r in started['rules'])
    stage_gate.end(gates, 'source', answers=answers('source'), outputs=outputs(work, 'source'))
    for stage in ('script', 'voice', 'edit', 'deliver'):
        run(gates, work, stage)
    stage_gate.require_complete(gates, ID)
    assert set(stage_gate.status(gates).values()) == {'ended'}


def test_stage_cannot_begin_before_its_inputs_end(root, work, tmp_path):
    with pytest.raises(ValueError, match='script stage has not ended'):
        stage_gate.begin(tmp_path / 'gates', 'voice', **ID)


def test_restarted_script_invalidates_downstream_but_same_bytes_do_not(root, work, tmp_path):
    gates = tmp_path / 'gates'
    for stage in ('source', 'script', 'voice', 'edit', 'deliver'):
        run(gates, work, stage)
    stage_gate.begin(gates, 'script', restart=True, **ID)
    stage_gate.end(gates, 'script', answers=answers('script', work), outputs=outputs(work, 'script'))
    stage_gate.require_complete(gates, ID)  # New review timestamp alone changes no inputs.
    stage_gate.begin(gates, 'script', restart=True, **ID)
    revised = SCRIPT.replace('덜 닿아요', '안 닿아요')
    work['script'].write_text(revised, 'utf-8')
    writing = json.loads(work['writing'].read_text('utf-8'))
    writing['scripts'][0]['text'] = revised
    write(work['writing'], writing)
    stage_gate.end(gates, 'script', answers=answers('script', work), outputs=outputs(work, 'script'))
    with pytest.raises(ValueError, match='stale script'):
        stage_gate.require_complete(gates, ID)
    assert stage_gate.status(gates)['voice'] == 'stale'
    assert stage_gate.status(gates)['deliver'] == 'stale'


def test_predecessor_changed_during_stage_cannot_end(root, work, tmp_path):
    gates = tmp_path / 'gates'
    run(gates, work, 'script')
    stage_gate.begin(gates, 'voice', **ID)
    stage_gate.begin(gates, 'script', restart=True, **ID)
    work['writing'].write_text(work['writing'].read_text('utf-8') + ' ', 'utf-8')
    stage_gate.end(gates, 'script', answers=answers('script', work), outputs=outputs(work, 'script'))
    with pytest.raises(ValueError, match='predecessor inputs changed'):
        stage_gate.end(gates, 'voice', answers=answers('voice'), outputs=outputs(work, 'voice'))


def test_voice_gate_rejects_other_script_even_with_same_style(root, work, tmp_path):
    gates = tmp_path / 'gates'
    run(gates, work, 'script')
    voice = json.loads(work['voice'].read_text('utf-8'))
    write(work['voice'], {**voice, 'text_sha256': '0' * 64})
    stage_gate.begin(gates, 'voice', **ID)
    with pytest.raises(ValueError, match='Voice request text'):
        stage_gate.end(gates, 'voice', answers=answers('voice'), outputs=outputs(work, 'voice'))


def test_edit_requires_existing_renderer_parent_protection(root, work, tmp_path):
    gates = tmp_path / 'gates'
    for stage in ('source', 'script', 'voice'):
        run(gates, work, stage)
    plan = json.loads(work['plan'].read_text('utf-8'))
    plan.pop('source_diversity_policy')
    write(work['plan'], plan)
    stage_gate.begin(gates, 'edit', **ID)
    with pytest.raises(ValueError, match='source diversity'):
        stage_gate.end(gates, 'edit', answers=answers('edit', work), outputs=outputs(work, 'edit'))


def test_end_needs_every_answer_with_evidence(root, work, tmp_path):
    gates = tmp_path / 'gates'
    stage_gate.begin(gates, 'script', **ID)
    partial = answers('script', work)
    partial['script_hook']['evidence'] = []
    with pytest.raises(ValueError, match='script_hook.*첫 문장'):
        stage_gate.end(gates, 'script', answers=partial, outputs=outputs(work, 'script'))


def test_rule_changed_after_begin_requires_reading_it_again(root, work, tmp_path):
    gates = tmp_path / 'gates'
    stage_gate.begin(gates, 'script', **ID)
    (root / 'hotpost' / 'writing' / 'RULES.md').write_text('updated rule', 'utf-8')
    with pytest.raises(ValueError, match='run begin again'):
        stage_gate.end(gates, 'script', answers=answers('script', work), outputs=outputs(work, 'script'))
    stage_gate.begin(gates, 'script', **ID)
    stage_gate.end(gates, 'script', answers=answers('script', work), outputs=outputs(work, 'script'))


def test_unofficial_outputs_are_rejected(root, work, tmp_path):
    gates = tmp_path / 'gates'
    stage_gate.begin(gates, 'script', **ID)
    work['script'].write_text('제작자가 임의로 고친 원고', 'utf-8')
    with pytest.raises(ValueError, match='not one of the variants'):
        stage_gate.end(gates, 'script', answers=answers('script', work), outputs=outputs(work, 'script'))
    work['script'].write_text(SCRIPT, 'utf-8')
    run(gates, work, 'script')

    voice = json.loads(work['voice'].read_text('utf-8'))
    write(work['voice'], {**voice, 'style_verified': False})
    stage_gate.begin(gates, 'voice', **ID)
    with pytest.raises(ValueError, match='verified style'):
        stage_gate.end(gates, 'voice', answers=answers('voice'), outputs=outputs(work, 'voice'))
    write(work['voice'], voice)
    run(gates, work, 'voice')
    run(gates, work, 'source')

    plan = json.loads(work['plan'].read_text('utf-8'))
    write(work['plan'], {**plan, 'voice_source': {'sha256': '0' * 64}})
    stage_gate.begin(gates, 'edit', **ID)
    with pytest.raises(ValueError, match='voice stage output'):
        stage_gate.end(gates, 'edit', answers=answers('edit', work), outputs=outputs(work, 'edit'))


def test_refined_script_is_accepted_only_with_official_selection_record(root, work, tmp_path):
    gates = tmp_path / 'gates'
    refined = SCRIPT.replace('덜 닿아요', '안 닿아요')
    work['script'].write_text(refined, 'utf-8')
    selection = write(tmp_path / 'selection.json', {
        'text': refined, 'before': SCRIPT, 'calls': [{'provider': 'codex', 'status': 'completed', 'fallback': False}]})
    stage_gate.begin(gates, 'script', **ID)
    stage_gate.end(gates, 'script', answers=answers('script', work),
                   outputs={**outputs(work, 'script'), 'selection': str(selection)})


def test_finished_stage_output_change_blocks_next_stage_and_restart_keeps_history(root, work, tmp_path):
    gates = tmp_path / 'gates'
    run(gates, work, 'script')
    work['writing'].write_text(work['writing'].read_text('utf-8') + ' ', 'utf-8')
    with pytest.raises(ValueError, match='changed after it was recorded'):
        stage_gate.begin(gates, 'voice', **ID)
    with pytest.raises(ValueError, match='already ended'):
        stage_gate.begin(gates, 'script', **ID)
    stage_gate.begin(gates, 'script', restart=True, **ID)
    assert len(list((gates / 'history').glob('*script*'))) == 2


def test_new_completion_requires_stage_gates(root, work, tmp_path, monkeypatch):
    from hotpost.reference_registry import load, mark
    gates = tmp_path / 'gates'
    for stage in ('source', 'script', 'voice', 'edit', 'deliver'):
        run(gates, work, stage)
    monkeypatch.setattr(stage_gate, 'REQUIRED_SINCE', datetime(2000, 1, 1, tzinfo=timezone.utc))
    registry = load(tmp_path / 'registry.json')
    registry['posts']['post'] = {'video_id': 'post', 'reference': {}, 'production': {'state': 'unknown'}}
    mark(registry, 'post', 'in_progress', 'Bound workers', expected='unknown',
         task_id='task', run_id='run', owner='producer', monitor='monitor')
    current = registry['posts']['post']['production']
    with pytest.raises(ValueError, match='stage-gates'):
        stage_gate_check(current, None, work)
    stage_gate_check(current, gates, work)


def stage_gate_check(current, gates, work):
    from hotpost.reference_registry import _require_stage_gates
    _require_stage_gates(current, 'post', gates, digest(work['video']))


@pytest.mark.parametrize('started_at', [
    '2026-10-28T00:00:00+09:00',
    '2026-10-28T07:29:34+09:00',
    '2026-10-27T22:29:34+00:00',
])
def test_korean_rollout_day_morning_requires_gates(started_at):
    from hotpost.reference_registry import _require_stage_gates
    current = {'task_id': 'task', 'run_id': 'run',
               'history': [{'to': 'in_progress', 'at': started_at}]}
    with pytest.raises(ValueError, match='stage-gates'):
        _require_stage_gates(current, 'post', None, '0' * 64)


def test_pre_rollout_video_keeps_original_path_after_later_resume():
    from hotpost.reference_registry import _require_stage_gates
    current = {'task_id': 'task', 'run_id': 'run', 'history': [
        {'to': 'in_progress', 'at': '2026-10-27T23:59:59+09:00'},
        {'to': 'in_progress', 'at': '2026-10-28T15:00:00+09:00'},
    ]}
    _require_stage_gates(current, 'post', None, '0' * 64)


@pytest.mark.parametrize('changed', ['derivative', 'hash', 'missing'])
def test_edit_requires_the_actual_sources_reviewed_at_source_stage(root, work, tmp_path, changed):
    gates = tmp_path / 'gates'
    for stage in ('source', 'script', 'voice'):
        run(gates, work, stage)
    plan = json.loads(work['plan'].read_text('utf-8'))
    if changed == 'derivative':
        derivative = write(tmp_path / 'source-with-new-label.mp4', b'different labeled pixels')
        plan['sources'] = [{'path': str(derivative), 'sha256': digest(derivative)}]
    elif changed == 'hash':
        plan['sources'][0]['sha256'] = '0' * 64
    else:
        del plan['sources']
    write(work['plan'], plan)
    stage_gate.begin(gates, 'edit', **ID)
    with pytest.raises(ValueError, match='source stage'):
        stage_gate.end(gates, 'edit', answers=answers('edit', work), outputs=outputs(work, 'edit'))
    assert not (gates / 'edit.end.json').exists()


def test_script_hook_cannot_end_with_generic_confirmation_only(root, work, tmp_path):
    gates = tmp_path / 'gates'
    stage_gate.begin(gates, 'script', **ID)
    generic = answers('script')
    with pytest.raises(ValueError, match='audience|hook|review'):
        stage_gate.end(gates, 'script', answers=generic, outputs=outputs(work, 'script'))


@pytest.mark.parametrize('missing', ['empathy_review', 'thumbnail_context_review'])
def test_script_cannot_skip_naturalness_or_pre_view_review(root, work, tmp_path, missing):
    gates = tmp_path / 'gates'
    stage_gate.begin(gates, 'script', **ID)
    checked = answers('script', work)
    del checked['script_hook']['review'][missing]
    with pytest.raises(ValueError, match='Audience review needs'):
        stage_gate.end(gates, 'script', answers=checked, outputs=outputs(work, 'script'))


@pytest.mark.parametrize('failed', ['empathy_review', 'thumbnail_context_review'])
def test_proceed_does_not_override_an_editorial_failure(root, work, tmp_path, failed):
    gates = tmp_path / 'gates'
    stage_gate.begin(gates, 'script', **ID)
    checked = answers('script', work)
    review = checked['script_hook']['review']
    review['thumbnail_lines'] = ['커피까지 마셔야', '제대로 쉬는 기분이잖아요']
    key = 'natural' if failed == 'empathy_review' else 'pre_view_relevant'
    review[failed][key] = False
    review[failed]['reason'] = '감정 항목을 채운 어색한 말 또는 영상을 본 뒤에야 이어지는 먼 보상'
    with pytest.raises(ValueError, match='Audience review needs'):
        stage_gate.end(gates, 'script', answers=checked, outputs=outputs(work, 'script'))
    assert not (gates / 'script.end.json').exists()


@pytest.mark.parametrize('field,value', [('opening_quote','없는 첫 문장!'),('script_sha256','0'*64),('viewer_interest','')])
def test_hook_review_must_describe_current_selected_script(root, work, tmp_path, field, value):
    gates = tmp_path / 'gates'
    stage_gate.begin(gates, 'script', **ID)
    reviewed = answers('script', work)
    reviewed['script_hook']['review'][field] = value
    with pytest.raises(ValueError, match='Audience|audience'):
        stage_gate.end(gates, 'script', answers=reviewed, outputs=outputs(work, 'script'))


def test_thumbnail_change_cannot_reuse_another_hook_review(root, work, tmp_path):
    gates = tmp_path / 'gates'
    for stage in ('source','script','voice'):
        run(gates, work, stage)
    plan = json.loads(work['plan'].read_text('utf-8'))
    plan['cover_text'] = '바뀐 문구\n재검토 필요'
    write(work['plan'],plan)
    stage_gate.begin(gates, 'edit', **ID)
    with pytest.raises(ValueError,match='thumbnail'):
        stage_gate.end(gates,'edit',answers=answers('edit',work),outputs=outputs(work,'edit'))


@pytest.mark.parametrize('field,value',[('plan_sha256','0'*64),('usage',{}),('repetition_assessment','')])
def test_montage_review_is_bound_to_actual_plan_and_usage(root, work, tmp_path, field, value):
    gates = tmp_path / 'gates'
    for stage in ('source','script','voice'):
        run(gates, work, stage)
    stage_gate.begin(gates,'edit',**ID)
    reviewed=answers('edit',work)
    reviewed['edit_scenes']['review'][field]=value
    with pytest.raises(ValueError,match='Montage|montage'):
        stage_gate.end(gates,'edit',answers=reviewed,outputs=outputs(work,'edit'))


def test_montage_usage_merges_original_windows_across_derivatives():
    parent='a'*64
    sources=[{'id':name,'sha256':name,'path':name+'.mp4','original_sha256':parent,
              'original_interval':{'start':offset}}
             for name,offset in [('first',10),('second',11)]]
    plan={'sources':sources,'duration':6,'footage_selection_policy':'diverse-sequential-v1',
          'shots':[{'id':s['id'],'source_id':s['id'],'path':s['path'],'sha256':s['sha256'],
                    'start':0,'end':2} for s in sources], 'beats':[], 'rendered_clips':[]}
    for index,name in enumerate(('first','second','first')):
        beat_id=f'beat-{index}'
        plan['beats'].append({'id':beat_id,'start':index*2,'end':index*2+2,
                              'selected_shot_id':name,'source_start':0,'source_end':2})
        plan['rendered_clips'].append({'beat_id':beat_id,'selected_shot_id':name,'start':index*2,
                                      'source_sha256':name,'duration':2,'selected_source_window':[0,2]})
    usage=stage_gate.montage_usage(plan)
    assert usage=={'timeline_seconds':6,'body_seconds':6,'parents':[{'parent_sha256':parent,'duration':6,
                   'uses':3,'unique_seconds':3,'replay_seconds':3}]}
    # A repeated sequence needs a real editorial judgment, not an arbitrary numeric veto.
    assert len(usage['parents'])==1


def test_current_selection_cannot_reuse_stale_rendered_clips(root, work, tmp_path):
    gates = tmp_path / 'gates'
    for stage in ('source', 'script', 'voice'):
        run(gates, work, stage)
    plan = json.loads(work['plan'].read_text('utf-8'))
    new_source = write(tmp_path / 'unreviewed.mp4', b'unreviewed pixels')
    plan['shots'].append({**plan['shots'][0], 'id': 'new-shot',
                          'path': str(new_source), 'sha256': digest(new_source)})
    plan['beats'][0]['selected_shot_id'] = 'new-shot'
    write(work['plan'], plan)
    stage_gate.begin(gates, 'edit', **ID)
    with pytest.raises(ValueError, match='[Mm]ontage|[Rr]endered|[Ss]elected'):
        stage_gate.end(gates, 'edit', answers=answers('edit', work), outputs=outputs(work, 'edit'))
    assert not (gates / 'edit.end.json').exists()


def test_montage_counts_only_the_rendered_part_of_a_long_selected_window(work):
    plan = json.loads(work['plan'].read_text('utf-8'))
    plan['duration'] = 2.0
    plan['beats'][0]['source_end'] = 4.0
    plan['beats'].append({**plan['beats'][0], 'id': 'beat-2', 'start': 1.0, 'end': 2.0})
    plan['rendered_clips'][0]['selected_source_window'] = [0.0, 4.0]
    plan['rendered_clips'].append({**plan['rendered_clips'][0], 'beat_id': 'beat-2', 'start': 1.0})
    usage = stage_gate.montage_usage(plan)
    assert usage['parents'][0]['unique_seconds'] == 1.0
    assert usage['parents'][0]['replay_seconds'] == 1.0


@pytest.mark.parametrize('changed', ['shot_path', 'shot_sha', 'source_id', 'clip_shot', 'clip_source',
                                   'window', 'start', 'duration', 'timeline', 'missing_clip'])
def test_montage_rejects_mismatched_current_selection_chain(work, changed):
    plan = json.loads(work['plan'].read_text('utf-8'))
    shot, clip, beat = plan['shots'][0], plan['rendered_clips'][0], plan['beats'][0]
    if changed == 'shot_path':
        shot['path'] = str(work['source'].with_name('unreviewed.mp4'))
    elif changed == 'shot_sha':
        shot['sha256'] = '0' * 64
        clip['source_sha256'] = shot['sha256']
    elif changed == 'source_id':
        shot['source_id'] = 'unrecorded-source'
    elif changed == 'clip_shot':
        clip['selected_shot_id'] = 'old-shot'
    elif changed == 'clip_source':
        clip['source_sha256'] = '0' * 64
    elif changed == 'window':
        clip['selected_source_window'] = [1.0, 2.0]
    elif changed == 'start':
        clip['start'] = 1 / 30
    elif changed == 'duration':
        clip['duration'] = 0.5
    elif changed == 'timeline':
        beat['end'] = 2.0
    else:
        plan['rendered_clips'] = []
    with pytest.raises(ValueError, match='Montage|Rendered'):
        stage_gate.montage_usage(plan)


def test_visual_cut_sequence_uses_picture_rows_and_ignores_unused_shots(work):
    plan = json.loads(work['plan'].read_text('utf-8'))
    # Many caption fragments can share two picture cuts in a single subject beat.
    plan['cues'] = [{'id': f'cue-{i}'} for i in range(10)]
    plan['shots'].append({'id': 'unused', 'path': 'missing-unused.mp4', 'sha256': 'unread'})
    plan['visual_cuts'] = []
    plan['rendered_clips'] = []
    for index in range(2):
        cut = {**plan['beats'][0], 'id': f'cut-{index}', 'parent_beat_id': 'beat-1',
               'start': index / 2, 'end': (index + 1) / 2,
               'source_start': index / 2, 'source_end': (index + 1) / 2}
        plan['visual_cuts'].append(cut)
        plan['rendered_clips'].append({'beat_id': cut['id'], 'parent_beat_id': 'beat-1',
            'selected_shot_id': 'shot-1', 'start': index / 2, 'duration': 0.5,
            'source_sha256': plan['sources'][0]['sha256'],
            'selected_source_window': [index / 2, (index + 1) / 2]})
    assert stage_gate.montage_usage(plan)['parents'][0]['unique_seconds'] == 1.0
    plan['rendered_clips'].reverse()
    with pytest.raises(ValueError, match='Rendered clip differs'):
        stage_gate.montage_usage(plan)
    plan['rendered_clips'].reverse()
    plan['beats'][0]['start'] = 0.5
    with pytest.raises(ValueError, match='parent beat timing'):
        stage_gate.montage_usage(plan)


@pytest.mark.parametrize('mode,body', [(None, 1.0), ('other', 1.0), ('replace_first_frame', 29 / 30)])
def test_montage_excludes_only_the_replaced_cover_frame(work, mode, body):
    plan = json.loads(work['plan'].read_text('utf-8'))
    plan['cover_mode'] = mode
    usage = stage_gate.montage_usage(plan)
    assert usage['timeline_seconds'] == 1.0
    assert usage['body_seconds'] == round(body, 6)
    assert usage['parents'][0]['duration'] == round(body, 6)
    assert usage['parents'][0]['unique_seconds'] == round(body, 6)
    assert usage['parents'][0]['replay_seconds'] == 0


def test_cover_only_source_has_no_body_exposure(work):
    plan = json.loads(work['plan'].read_text('utf-8'))
    plan['cover_mode'] = 'replace_first_frame'
    plan['duration'] = plan['beats'][0]['end'] = plan['rendered_clips'][0]['duration'] = 1 / 30
    assert stage_gate.montage_usage(plan) == {
        'timeline_seconds': round(1 / 30, 6), 'body_seconds': 0, 'parents': []}


def test_montage_keeps_native_final_ceil_and_legacy_shot_window_mapping(work):
    plan = json.loads(work['plan'].read_text('utf-8'))
    plan['duration'] = plan['beats'][0]['end'] = 1.01
    plan['beats'][0]['source_end'] = 2.0
    plan['rendered_clips'][0].update(duration=31 / 30, selected_source_window=[0.0, 2.0])
    usage = stage_gate.montage_usage(plan)
    assert usage['timeline_seconds'] == round(31 / 30, 6)
    assert usage['parents'][0]['unique_seconds'] == round(31 / 30, 6)
    del plan['footage_selection_policy']
    plan['rendered_clips'][0]['selected_source_window'] = [0.0, 4.0]  # native legacy render_window
    assert stage_gate.montage_usage(plan) == usage
