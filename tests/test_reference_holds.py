import copy
import json

import pytest

from hotpost.final_qa import file_input
from hotpost.reference_registry import context, load, main, mark, save, transaction


@pytest.fixture
def current(tmp_path):
    path = tmp_path / 'registry.json'
    registry = load(path)
    registry['posts']['a'] = {'video_id': 'a', 'reference': {},
                               'production': {'state': 'unknown'}}
    mark(registry, 'a', 'in_progress', 'Bound actual workers', expected='unknown',
         stage='source', task_id='task', run_id='run', owner='producer', monitor='monitor')
    save(path, registry)
    return path, registry


@pytest.fixture
def review(tmp_path):
    files = {}
    for name, content in [('script', 'Selected script'),
                          ('source_review', 'C07 0.2-1.2 title masks the relevant object; related context inspected'),
                          ('rule', 'Five independent parents; honest context is allowed'),
                          ('source', 'original clip bytes'),
                          ('failure', 'Current tool result: permission denied')]:
        path = tmp_path / (name + '.txt')
        path.write_text(content, 'utf-8')
        files[name] = {**file_input(path), 'role': name}

    def observation(role, location, detail):
        return {'input': files[role]['path'], 'location': location, 'observation': detail}

    return {'video_id': 'a', 'task_id': 'task', 'run_id': 'run',
            'inputs': list(files.values()),
            'requirements': [observation('rule', 'source policy', 'Five reviewed independent parents required')],
            'segments': [observation('source', '0.2-1.2 s', 'Title masks the object throughout the candidate interval')],
            'alternatives': [{'action': 'Use the related context interval with a different crop',
                              'outcome': 'ruled_out', 'evidence': [observation(
                                  'source_review', 'C07 crop result', 'Crop removes the object; masking crosses the hand')]}],
            'main_decision': {'decision': 'hold', 'evidence': [observation(
                'source_review', 'main comparison', 'Current reviewed alternatives cannot fill the missing parent role')]},
            'blocker': [observation('failure', 'tool result', 'Required input cannot be read without new permission')]}


def block(registry, **kwargs):
    return mark(registry, 'a', 'blocked', 'Existing explanation remains plain text',
                expected='in_progress', **kwargs)


def test_quality_hold_uses_existing_review_section_without_finished_source_gate(current, review, tmp_path):
    path, registry = current
    existing = tmp_path / 'source-answers.json'
    existing.write_text(json.dumps({'answers': {'source_log': 'ongoing'}, 'hold_review': review}), 'utf-8')
    block(registry, hold_review=existing)
    production = registry['posts']['a']['production']
    assert production['state'] == 'blocked'
    receipt = production['history'][-1]['hold_review']
    assert receipt['kind'] == 'source_quality'
    assert receipt['record'] == file_input(existing)
    assert production['evidence'][-1] == 'Existing explanation remains plain text'
    assert not (tmp_path / 'source.end.json').exists()


@pytest.mark.parametrize('change', ['video_id', 'task_id', 'run_id', 'stale', 'missing_input',
                                   'requirements', 'segments', 'alternatives', 'main_decision',
                                   'unbound', 'checkbox', 'viable', 'untried', 'duplicate', 'missing_role'])
def test_missing_or_unbound_quality_review_never_changes_the_registry(current, review, change):
    path, registry = current
    before = copy.deepcopy(dict(registry))
    if change in {'video_id', 'task_id', 'run_id'}:
        review[change] = 'another'
    elif change == 'stale':
        from pathlib import Path
        Path(review['inputs'][0]['path']).write_text('changed script', 'utf-8')
    elif change == 'missing_input':
        from pathlib import Path
        Path(review['inputs'][0]['path']).unlink()
    elif change in {'requirements', 'segments', 'alternatives', 'main_decision'}:
        del review[change]
    elif change == 'unbound':
        review['segments'][0]['input'] = str(path)
    elif change == 'checkbox':
        review['main_decision'] = {'decision': 'hold', 'evidence': [True]}
    elif change in {'viable', 'untried'}:
        review['alternatives'][0]['outcome'] = change
    elif change == 'duplicate':
        review['inputs'].append(copy.deepcopy(review['inputs'][0]))
    elif change == 'missing_role':
        review['inputs'][0]['role'] = 'misc'
    with pytest.raises(ValueError, match='hold review'):
        block(registry, hold_review=review)
    assert registry == before


@pytest.mark.parametrize('kind', ['access', 'permission', 'technical'])
def test_cause_label_alone_cannot_bypass_quality_review(current, review, kind):
    path, registry = current
    before = copy.deepcopy(dict(registry))
    with pytest.raises(ValueError, match='hold review'):
        block(registry, block_kind=kind)
    invalid = copy.deepcopy(review)
    invalid['blocker'][0]['input'] = invalid['inputs'][0]['path']  # script, not a tool failure
    with pytest.raises(ValueError, match='actual failure'):
        block(registry, block_kind=kind, hold_review=invalid)
    assert registry == before
    block(registry, block_kind=kind, hold_review=review)
    assert registry['posts']['a']['production']['state'] == 'blocked'


def test_actual_user_stop_stays_immediate_and_old_holds_and_completions_are_read_only(current):
    path, registry = current
    mark(registry, 'a', 'paused', 'Actual user stop', expected='in_progress')
    assert registry['posts']['a']['production']['state'] == 'paused'
    for state in ('blocked', 'completed'):
        registry['posts']['old-' + state] = {'production': {'state': state, 'stage': 'source',
                                                          'evidence': ['Historical record']}}
    save(path, registry)
    before = path.read_bytes()
    for state in ('blocked', 'completed'):
        assert context(registry, 'old-' + state)['state'] == state
    assert path.read_bytes() == before


def test_source_stage_cannot_be_hidden_by_relabelling_the_proposed_stage(current):
    path, registry = current
    with pytest.raises(ValueError, match='hold review'):
        block(registry, stage='other')
    assert registry['posts']['a']['production']['stage'] == 'source'


def test_quality_hold_cannot_replace_task_or_run_and_keeps_inline_observations(current, review):
    path, registry = current
    with pytest.raises(ValueError, match='bound run_id'):
        block(registry, hold_review=review, run_id='another')
    block(registry, hold_review=review)
    recorded = copy.deepcopy(registry['posts']['a']['production']['history'][-1])
    review['segments'][0]['observation'] = 'mutated by caller'
    assert registry['posts']['a']['production']['history'][-1] == recorded


def test_rejected_hold_preserves_persisted_revision_and_state_conflict_precedes_review(current):
    path, registry = current
    before = path.read_bytes()
    with pytest.raises(ValueError, match='hold review'):
        with transaction(path, expected_revision=1) as registry:
            block(registry)
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match='State changed'):
        mark(load(path), 'a', 'blocked', 'Stale caller', expected='paused')
    assert path.read_bytes() == before


def test_cli_accepts_existing_review_json_and_keeps_descriptive_evidence(current, review, tmp_path):
    path, registry = current
    existing = tmp_path / 'manifest.json'
    existing.write_text(json.dumps({'hold_review': review}), 'utf-8')
    main(['--registry', str(path), 'mark', 'a', '--state', 'blocked', '--expected-state', 'in_progress',
          '--expected-revision', '1', '--evidence', 'Human explanation, not a file path',
          '--block-kind', 'source_quality', '--hold-review', str(existing)])
    current = load(path)
    assert current['revision'] == 2
    assert current['posts']['a']['production']['evidence'][-1] == 'Human explanation, not a file path'


@pytest.mark.parametrize('stage', ['edit', 'final_qa'])
def test_content_quality_uses_same_bound_review(current, review, stage):
    path, registry = current
    registry['posts']['a']['production']['stage'] = stage
    with pytest.raises(ValueError, match='hold review'):
        block(registry)
    block(registry, hold_review=review)
    assert registry['posts']['a']['production']['history'][-1]['hold_review']['kind'] == 'content_quality'


def test_file_change_during_validation_cannot_be_recorded_as_current(current, review, monkeypatch):
    from pathlib import Path
    from hotpost import final_qa

    path, registry = current
    source = next(item for item in review['inputs'] if item['role'] == 'source')
    original_digest = final_qa.digest
    visits = []

    def changed_after_first_read(path):
        if Path(path) == Path(source['path']):
            visits.append(path)
            if len(visits) == 2:
                Path(path).write_text('replaced during validation', 'utf-8')
        return original_digest(path)

    monkeypatch.setattr(final_qa, 'digest', changed_after_first_read)
    before = copy.deepcopy(dict(registry))
    with pytest.raises(ValueError, match='input bytes changed during validation'):
        block(registry, hold_review=review)
    assert registry == before


@pytest.mark.parametrize('content', [None, 'not JSON', '[]', '{"hold_review": true}'])
def test_bad_existing_review_file_never_becomes_a_hold(current, tmp_path, content):
    path, registry = current
    existing = tmp_path / 'ongoing-answers.json'
    if content is not None:
        existing.write_text(content, 'utf-8')
    before = copy.deepcopy(dict(registry))
    with pytest.raises(ValueError, match='hold review'):
        block(registry, hold_review=existing)
    assert registry == before


def test_source_quality_hold_uses_current_brief_without_requiring_a_finished_script(current, review):
    path, registry = current
    review['inputs'][0]['role'] = 'brief'
    # Source has no script predecessor: a real topic brief is valid before writing.
    block(registry, hold_review=review)
    assert registry['posts']['a']['production']['state'] == 'blocked'
