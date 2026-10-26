import json
from pathlib import Path
import subprocess
import sys

import pytest

from hotpost.reference_registry import context, load, main, mark, save, transaction


def seeded(tmp_path):
    path = tmp_path / 'registry.json'
    registry = load(path)
    for code in ('first', 'second'):
        registry['posts'][code] = {'video_id': code, 'reference': {'in_latest_report': True},
                                   'production': {'state': 'unknown', 'evidence': []}}
    save(path, registry)
    return path


def test_stale_writer_cannot_erase_another_sessions_stop(tmp_path):
    path = seeded(tmp_path)
    stale, current = load(path), load(path)
    mark(current, 'first', 'paused', 'User stopped', expected='unknown')
    save(path, current)
    stale['posts']['second']['production']['state'] = 'not_started'
    with pytest.raises(ValueError, match='changed; reload'):
        save(path, stale)
    assert load(path)['posts']['first']['production']['state'] == 'paused'
    assert load(path)['revision'] == 2


def test_same_revision_manual_edit_is_not_overwritten(tmp_path):
    path = seeded(tmp_path)
    stale = load(path)
    changed = json.loads(path.read_bytes())
    changed['posts']['first']['production']['reason'] = 'External correction'
    path.write_text(json.dumps(changed), 'utf8')
    with pytest.raises(ValueError, match='changed; reload'):
        save(path, stale)
    with pytest.raises(ValueError, match='Load this'):
        save(path, changed)


def test_transaction_failure_preserves_bytes_and_releases_lock(tmp_path):
    path = seeded(tmp_path)
    before = path.read_bytes()
    with pytest.raises(RuntimeError):
        with transaction(path) as registry:
            registry['posts'].clear()
            raise RuntimeError('failed operation')
    assert path.read_bytes() == before
    with transaction(path, expected_revision=1) as registry:
        registry['posts']['first']['production']['reason'] = 'confirmed'
    with pytest.raises(ValueError, match='revision changed'):
        with transaction(path, expected_revision=1):
            pytest.fail('stale caller entered transaction')


def test_native_lock_blocks_second_process_and_crash_does_not_leave_a_live_lock(tmp_path):
    path = seeded(tmp_path)
    script = ('from hotpost.reference_registry import transaction\n'
              'from pathlib import Path\nimport sys\n'
              'with transaction(Path(sys.argv[1])):\n'
              ' print("locked", flush=True)\n sys.stdin.readline()\n')
    holder = subprocess.Popen([sys.executable, '-u', '-c', script, str(path)],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == 'locked'
        with pytest.raises(ValueError, match='busy'):
            with transaction(path):
                pytest.fail('two writers entered')
    finally:
        holder.kill()
        holder.communicate(timeout=10)
    with transaction(path) as registry:
        assert registry['revision'] == 1
    assert load(path)['revision'] == 2


def test_cli_second_video_cannot_start_and_revision_protects_same_state_update(tmp_path, capsys):
    path = seeded(tmp_path)
    args = ['--registry', str(path), 'mark', 'first', '--state', 'in_progress',
            '--expected-state', 'unknown', '--evidence', 'Actual workers bound', '--task-id', 'task',
            '--run-id', 'run', '--owner', 'producer', '--monitor', 'monitor', '--expected-revision', '1']
    main(args)
    args[3] = 'second'
    with pytest.raises(ValueError, match='revision changed'):
        main(args)
    args[-1] = '2'
    with pytest.raises(ValueError, match='Another video'):
        main(args)
    assert load(path)['revision'] == 2


def test_context_is_read_only_and_does_not_invent_live_monitoring(tmp_path, capsys):
    path = seeded(tmp_path)
    with transaction(path) as registry:
        mark(registry, 'first', 'blocked', 'Access evidence', expected='unknown',
             stage='source_acquisition', task_id='task', run_id='run', owner='producer', monitor='monitor',
             reason='Normal acquisition failed')
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    main(['--registry', str(path), 'context', 'first'])
    recovered = json.loads(capsys.readouterr().out)
    assert recovered['next_action'] == 'require_explicit_resume_and_new_progress_evidence'
    assert recovered['grants_execution_authority'] is False
    assert recovered['worker_observation'].startswith('unverified')
    assert recovered['stage'] == 'source_acquisition' and recovered['revision'] == 2
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before
