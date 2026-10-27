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


@pytest.fixture
def work(tmp_path):
    w = tmp_path / 'work'
    calls = [{'requested_model': 'gpt-6-sol', 'fallback': False}]
    files = {
        'source': write(w / 'BB01.mp4', b'source clip'),
        'writing': write(w / 'writing-result.json', {
            'type': 'scripts', 'scripts': [{'text': SCRIPT}, {'text': '둘째 안'}, {'text': '셋째 안'}],
            'generation_inference': {'calls': calls, 'fallback': False}}),
        'script': write(w / 'selected-script.txt', SCRIPT),
        'wav': write(w / 'narration.wav', b'voice'),
    }
    files['voice'] = write(w / 'voice-result.json', {
        'status': 'succeeded', 'style_verified': True, 'requested_style_id': 'reels_bright_v1',
        'voice_profile_id': None, 'output_path': str(files['wav'])})
    files['plan'] = write(w / 'timeline.json', {
        'script_text': SCRIPT,
        'caption_semantic_contract': {'review': {'script_sha256': hashlib.sha256(SCRIPT.encode()).hexdigest()}},
        'narration_policy': {'profile': 'sentence_preserved_v1'},
        'voice_source': {'sha256': digest(files['wav'])}})
    video, cover = write(w / 'video.mp4', b'final'), write(w / 'cover.png', b'cover')
    files['video'] = video
    files['delivery'] = write(w / 'delivery-receipt.json', {
        'video': str(video), 'cover': str(cover), 'video_sha256': digest(video),
        'cover_sha256': digest(cover), 'full_decode': True, 'faststart': True})
    return files


def answers(stage):
    contract = json.loads(stage_gate.CONTRACT.read_text('utf-8'))
    return {c['id']: {'answer': '확인함', 'evidence': ['frame 00:01']}
            for c in contract['stages'][stage]['checks']}


def outputs(files, stage):
    return {'source': {'sources': [str(files['source'])]},
            'script': {'writing_result': str(files['writing']), 'selected_script': str(files['script'])},
            'voice': {'voice_result': str(files['voice'])},
            'edit': {'plan': str(files['plan'])},
            'deliver': {'delivery_receipt': str(files['delivery'])}}[stage]


def run(gates, files, stage):
    stage_gate.begin(gates, stage, **ID)
    return stage_gate.end(gates, stage, answers=answers(stage), outputs=outputs(files, stage))


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


def test_end_needs_every_answer_with_evidence(root, work, tmp_path):
    gates = tmp_path / 'gates'
    stage_gate.begin(gates, 'script', **ID)
    partial = answers('script')
    partial['script_hook']['evidence'] = []
    with pytest.raises(ValueError, match='script_hook.*첫 문장'):
        stage_gate.end(gates, 'script', answers=partial, outputs=outputs(work, 'script'))


def test_rule_changed_after_begin_requires_reading_it_again(root, work, tmp_path):
    gates = tmp_path / 'gates'
    stage_gate.begin(gates, 'script', **ID)
    (root / 'hotpost' / 'writing' / 'RULES.md').write_text('updated rule', 'utf-8')
    with pytest.raises(ValueError, match='run begin again'):
        stage_gate.end(gates, 'script', answers=answers('script'), outputs=outputs(work, 'script'))
    stage_gate.begin(gates, 'script', **ID)
    stage_gate.end(gates, 'script', answers=answers('script'), outputs=outputs(work, 'script'))


def test_unofficial_outputs_are_rejected(root, work, tmp_path):
    gates = tmp_path / 'gates'
    stage_gate.begin(gates, 'script', **ID)
    work['script'].write_text('제작자가 임의로 고친 원고', 'utf-8')
    with pytest.raises(ValueError, match='not one of the variants'):
        stage_gate.end(gates, 'script', answers=answers('script'), outputs=outputs(work, 'script'))
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
        stage_gate.end(gates, 'edit', answers=answers('edit'), outputs=outputs(work, 'edit'))


def test_refined_script_is_accepted_only_with_official_selection_record(root, work, tmp_path):
    gates = tmp_path / 'gates'
    refined = SCRIPT.replace('덜 닿아요', '안 닿아요')
    work['script'].write_text(refined, 'utf-8')
    selection = write(tmp_path / 'selection.json', {
        'text': refined, 'before': SCRIPT, 'calls': [{'requested_model': 'gpt-6-sol', 'fallback': False}]})
    stage_gate.begin(gates, 'script', **ID)
    stage_gate.end(gates, 'script', answers=answers('script'),
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
