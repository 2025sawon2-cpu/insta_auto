"""Retain and execute the installed native production-entry regressions.

This adds their collection to the current incident test run without changing
their fixtures, internal validators, entry points or assertions.
"""
import json
import os
from pathlib import Path

import inspect
import test_preserved_native_reader_boundary as retained

# Keep the installed regression immutable. Its future external readiness
# timestamp was fixed to a value now equal to the preserved incident input.
# Execute the exact retained integration with only that future value repaired;
# every production call and assertion remains unchanged.
_retained_source = inspect.getsource(retained.test_preserved_query_receives_native_event)
_old_future = "changed['at'] = 1792477701.4271672"
assert _retained_source.count(_old_future) == 1
_current_source = _retained_source.replace(
    _old_future, "changed['at'] = readiness['at'] + 1")
# Rebind the copied selected checkpoint to the bundle actually installed
# below. Keep the original invalid query contract and every validator real.
_install = "    destination.write_text(json.dumps(bundle), encoding='utf8')"
assert _current_source.count(_install) == 1
_rebind = '''
    original_selection = original['job']['checkpoint']['planning_preparation']
    installed_sha = hashlib.sha256(destination.read_bytes()).hexdigest()
    substitutions[original_selection['path']] = str(destination.resolve())
    substitutions[original_selection['sha256']] = installed_sha
    isolated_job['checkpoint']['planning_preparation'].update(
        path=str(destination.resolve()), sha256=installed_sha)
    assert destination.resolve().is_relative_to(tmp_path.resolve())
    assert isolated_job['id'] == original['job']['id']
    assert isolated_job['checkpoint']['planning_preparation']['run_id'] == original['task']['run_id']
'''
_current_source = _current_source.replace(_install, _install + '\n' + _rebind)
# Exercise unchanged selection guards before the positive production route.
_preflight = "    plan, frames = preparation.preflight_preparation(settings, store.get(task['id']), isolated_job)"
assert _current_source.count(_preflight) == 1
_rejections = '''
    selection_before = copy.deepcopy(isolated_job['checkpoint']['planning_preparation'])
    for field, invalid_value in [('job_id', 'foreign-job'), ('sha256', '0' * 64)]:
        invalid_job = copy.deepcopy(isolated_job)
        invalid_job['checkpoint']['planning_preparation'][field] = invalid_value
        with pytest.raises(preparation.PreparationEvidenceWaiting):
            preparation.preflight_preparation(settings, store.get(task['id']), invalid_job)
        assert isolated_job['checkpoint']['planning_preparation'] == selection_before
    assert preparation.load_bundle(destination, caption, transcript)['query_plan'] == bundle['query_plan']
'''
_current_source = _current_source.replace(_preflight, _rejections + '\n' + _preflight)
# Match the actual production topic call's optional positional generator.
_topic_signature = '    def current_topic(settings, reference, frames, caption, transcript, **kwargs):'
assert _current_source.count(_topic_signature) == 1
_current_source = _current_source.replace(
    _topic_signature,
    '    def current_topic(settings, reference, frames, caption, transcript, supplied_generate=None, **kwargs):')
# Preserve the owned source-job hierarchy in the isolated path mapping.
_flat_path = ' ' * 16 + "return str(root / hashlib.sha256(value.encode()).hexdigest())"
assert _current_source.count(_flat_path) == 1
_owned_path = '''                    parts = PureWindowsPath(value).parts
                    if 'source_jobs' in parts:
                        relative = parts[parts.index('source_jobs') + 1:]
                        target = settings.source_dir.joinpath(*relative).resolve()
                        assert target.is_relative_to(settings.source_dir.resolve())
                        assert target.is_relative_to(tmp_path.resolve())
                        return str(target)
                    return str(root / hashlib.sha256(value.encode()).hexdigest())'''
# The retained nested rewrite return is indented sixteen spaces.
_owned_path = '\n'.join(line[4:] for line in _owned_path.splitlines())
assert all(not line.strip() or len(line) - len(line.lstrip()) >= 16
           for line in _owned_path.splitlines())
_current_source = _current_source.replace(_flat_path, _owned_path)
# Install the preserved current attempt before resuming its real entry.
_resume = "    resumed_job = rewrite(copy.deepcopy(original['job']))"
assert _current_source.count(_resume) == 1
_attempt_files = '''
    def captured_document(path, expected_sha):
        matches = [a for a in original['artifacts']
                   if PureWindowsPath(a.get('path', '')) == PureWindowsPath(path)
                   and isinstance(a.get('content'), str)]
        assert len(matches) == 1, 'Exact captured attempt artifact required'
        raw = matches[0]['content'].encode('utf8')
        assert hashlib.sha256(raw).hexdigest() == expected_sha
        return json.loads(raw)
    def install_document(path, old_sha, document):
        target = Path(rewrite(path)).resolve()
        assert target.is_relative_to(settings.source_dir.resolve())
        assert target.is_relative_to(tmp_path.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(rewrite(copy.deepcopy(document))), encoding='utf8')
        substitutions[old_sha] = hashlib.sha256(target.read_bytes()).hexdigest()
        assert json.loads(target.read_text('utf8')) == rewrite(copy.deepcopy(document))
    for attempt in original['job']['checkpoint'].get('source_attempts', []):
        receipt = captured_document(attempt['receipt_path'], attempt['receipt_sha256'])
        assert receipt['manifest_path'] == attempt['manifest_path']
        assert receipt['task_id'] == original['task']['id']
        assert receipt['studio_job_id'] == original['job']['id']
        assert receipt['run_id'] == original['task']['run_id']
        manifest = captured_document(receipt['manifest_path'], receipt['manifest_sha256'])
        for worker in receipt.get('worker_checkpoints', []):
            document = captured_document(worker['path'], worker['sha256'])
            install_document(worker['path'], worker['sha256'], document)
        install_document(receipt['manifest_path'], receipt['manifest_sha256'], manifest)
        install_document(attempt['receipt_path'], attempt['receipt_sha256'], receipt)
    # Apply the same derived hash substitutions to the isolated task history.
    isolated_task = rewrite(copy.deepcopy(original['task']))
    assert isolated_task['id'] == original['task']['id']
    assert isolated_task['run_id'] == original['task']['run_id']
'''
_current_source = _current_source.replace(_resume, _attempt_files + '\n' + _resume)
_namespace = dict(vars(retained))
exec(compile(_current_source, retained.__file__, 'exec'), _namespace)
test_preserved_query_receives_native_event = _namespace['test_preserved_query_receives_native_event']


def test_current_incident_binding_is_preserved():
    incident = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    task, job = incident['task'], incident['job']
    assert task['id'] == 'work-6a9b6d9f920d4a3c'
    assert job['id'] == 'job-30789cffdc5c4d21'
    assert job['task_id'] == task['id']
    assert job['payload']['run_id'] == task['run_id']
    assert job['status'] == 'queued'
    receipt = job['checkpoint']['parser_response_recovery']
    assert receipt['status'] == 'unavailable'
    assert receipt['error_type'] == 'RuntimeError'
    assert receipt['query_submitted'] is False
    assert receipt['grants_media_approval'] is False
