import hashlib
import json
from pathlib import Path

import pytest

from hotpost import final_qa


@pytest.fixture
def reviewed(tmp_path):
    files = {}
    for name in ('script', 'voice', 'plan', 'video', 'cover', 'source', 'rule'):
        path = tmp_path / name
        path.write_bytes(('reviewed ' + name).encode())
        files[name] = path
    binding = lambda name: {'path': str(files[name]),
                            'sha256': hashlib.sha256(files[name].read_bytes()).hexdigest()}
    record = {'schema_version': 2, 'video_id': 'post', 'task_id': 'task', 'run_id': 'run',
              'edit_id': 'edit', 'producer': 'producer', 'reviewed_at': '2026-10-26T14:00:00+09:00',
              'artifacts': {name: dict(binding(name), id=name) for name in
                            ('script', 'voice', 'plan', 'video', 'cover')},
              'dependencies': {'sources': [binding('source')], 'rules': [binding('rule')]},
              'checks': {name: {'status': '충족', 'evidence': [{'asset': asset,
                         'location': 'opening / 00:01', 'observation': 'Reviewed fixture content'}]}
                         for name, asset in final_qa.CHECK_ASSETS.items()}}
    path = tmp_path / 'qa.json'
    path.write_text(json.dumps(record), 'utf8')
    return path, files, record


@pytest.mark.parametrize('name', ['script', 'voice', 'plan', 'source', 'rule'])
def test_changed_input_invalidates_qa_even_when_final_video_unchanged(reviewed, name):
    path, files, _ = reviewed
    result = final_qa.validate(path, video_id='post')
    assert result['input_binding'] == 'files'
    video = files['video'].read_bytes()
    files[name].write_bytes(b'new unreviewed input')
    with pytest.raises(ValueError, match='bytes changed after review'):
        final_qa.validate(path, video_id='post')
    assert files['video'].read_bytes() == video


@pytest.mark.parametrize('name', ['script', 'voice', 'plan', 'sources', 'rules'])
def test_missing_bound_input_cannot_be_silently_downgraded(reviewed, name):
    path, _, record = reviewed
    if name in ('sources', 'rules'):
        record['dependencies'][name] = []
    else:
        del record['artifacts'][name]['path']
    path.write_text(json.dumps(record), 'utf8')
    with pytest.raises(ValueError):
        final_qa.validate(path, video_id='post')


def test_input_changed_during_long_media_check_is_rejected(reviewed, monkeypatch):
    path, files, _ = reviewed
    original = final_qa.digest
    def changing_digest(filename):
        if filename == files['video']:
            files['script'].write_bytes(b'changed while video was hashing')
        return original(filename)
    monkeypatch.setattr(final_qa, 'digest', changing_digest)
    with pytest.raises(ValueError, match='script bytes changed'):
        final_qa.validate(path, video_id='post')


def test_legacy_completed_qa_remains_readable_and_reports_its_scope(reviewed):
    path, _, record = reviewed
    record['schema_version'] = 1
    for name in ('script', 'voice', 'plan'):
        del record['artifacts'][name]['path']
    del record['dependencies']
    path.write_text(json.dumps(record), 'utf8')
    assert final_qa.validate(path, video_id='post')['input_binding'] == 'legacy_metadata_only'


def test_capture_inputs_does_not_write_or_approve_a_review(reviewed, capsys):
    path, files, _ = reviewed
    before = path.read_bytes()
    args = ['inputs']
    for name in ('script', 'voice', 'plan', 'source', 'rule'):
        args += ['--' + name, str(files[name])]
    final_qa.main(args)
    snapshot = json.loads(capsys.readouterr().out)
    assert snapshot['schema_version'] == 2 and 'checks' not in snapshot
    assert snapshot['artifacts']['script']['sha256'] == hashlib.sha256(files['script'].read_bytes()).hexdigest()
    rules = [Path(item['path']).name for item in snapshot['dependencies']['rules']]
    assert rules[0] == Path(files['rule']).name and 'CAPTION_SEGMENTATION.md' in rules
    assert path.read_bytes() == before


def test_completed_video_is_not_reopened_by_later_rule_or_qa_edits(reviewed, tmp_path, monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr('hotpost.stage_gate.REQUIRED_SINCE', datetime(2999, 1, 1, tzinfo=timezone.utc))
    from hotpost.reference_registry import context, load, mark
    from hotpost.daily_ranking import public_production, select_next
    path, files, record = reviewed
    registry = load(tmp_path / 'registry.json')
    registry['posts']['post'] = {'video_id': 'post', 'reference': {'in_latest_report': True},
                                'production': {'state': 'unknown'}}
    mark(registry, 'post', 'in_progress', 'Bound workers', expected='unknown',
         task_id='task', run_id='run', owner='producer', monitor='monitor')
    mark(registry, 'post', 'completed', 'Reviewed current inputs and outputs', expected='in_progress',
         qa_evidence=path, final_sha256=hashlib.sha256(files['video'].read_bytes()).hexdigest())
    production = registry['posts']['post']['production']
    # User decision 2026-10-27: a reviewed completion stays done when guidance changes later.
    files['rule'].write_bytes(b'new rules')
    path.write_text(json.dumps({**record, 'edited': True}), 'utf8')
    assert public_production('post', production)['completed_video_ready'] is True
    assert context(registry, 'post')['qa'] == {'status': 'completed'}
    assert select_next(registry) == {'action': 'no_candidate'}


def test_export_rechecks_bound_inputs_after_copy(reviewed, tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from hotpost import publication_export as exports
    path, files, _ = reviewed
    config = tmp_path / 'local' / 'storage.json'
    exports.configure(tmp_path / 'export', config)
    source = {'run_id': 'run', 'edit_id': 'edit', 'media_version': 'current',
              'media': {'final': files['video'], 'cover': files['cover'], 'reference': None}}
    files['cover'].rename(files['cover'].with_suffix('.png'))
    files['cover'] = files['cover'].with_suffix('.png')
    source['media']['cover'] = files['cover']
    record = json.loads(path.read_bytes())
    record['artifacts']['cover']['path'] = str(files['cover'])
    path.write_text(json.dumps(record), 'utf8')
    monkeypatch.setattr(exports, 'validate_video', lambda _: None)
    original = exports.shutil.copyfile
    def copy_then_change(*args, **kwargs):
        result = original(*args, **kwargs)
        files['voice'].write_bytes(b'voice changed during export')
        return result
    monkeypatch.setattr(exports.shutil, 'copyfile', copy_then_change)
    with pytest.raises(ValueError, match='voice bytes changed'):
        exports.save_current(SimpleNamespace(source=lambda _: source), 'post', topic='test',
                             config=config, now=datetime.now(timezone.utc), qa_record=path)
    assert not list((tmp_path / 'export').rglob('*.mp4'))
