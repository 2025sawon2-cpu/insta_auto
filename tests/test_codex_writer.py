import json
import sys
import time

import pytest

from hotpost.writing import codex_writer


@pytest.mark.skipif(codex_writer.os.name != 'nt', reason='Windows desktop installation')
def test_scheduled_task_resolves_installed_cli_without_desktop_path(tmp_path, monkeypatch):
    binary = tmp_path/'OpenAI'/'Codex'/'bin'/'installed-version'/'codex.exe'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'fixture')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(codex_writer.shutil, 'which', lambda name:None)
    assert codex_writer.executable() == str(binary)


def test_missing_cli_still_fails_instead_of_using_another_model(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(codex_writer.shutil, 'which', lambda name:None)
    with pytest.raises(RuntimeError, match='CLI'):
        codex_writer.executable()

def test_cli_command_is_text_only_and_uses_existing_auth():
    args = codex_writer.command('codex', 'cwd', 'schema', 'output')
    assert '--ignore-user-config' in args and '--ephemeral' in args
    assert args[args.index('--sandbox')+1] == 'read-only'
    assert 'shell_tool' in args and 'web_search="disabled"' in args
    assert '-m' not in args and not any('token' in arg.lower() for arg in args)


def test_inner_schema_is_validated():
    schema = {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}
    assert codex_writer.decode(json.dumps({'text': '{"text":"ok"}'}), schema) == {'text': 'ok'}
    with pytest.raises(ValueError, match='형식'):
        codex_writer.decode(json.dumps({'text': '{"text":1}'}), schema)


@pytest.mark.parametrize('purpose', ['script_writing', 'repair_review', None])
def test_script_model_is_explicit_through_format_repair_without_changing_other_calls(tmp_path, monkeypatch, purpose):
    original = codex_writer.command
    launched = []

    def transport(binary, directory, schema, output, **options):
        launched.append(original(binary, directory, schema, output, **options))
        # First response needs JSON encoding repair; the second is valid.
        value = '{"text":"ok",}' if len(launched) == 1 else '{"text":"ok"}'
        code = ('import json;'
                f'open({str(output)!r},"w").write(json.dumps({{"text":{value!r}}}));'
                'print(json.dumps({"type":"turn.completed"}),flush=True)')
        return [sys.executable, '-c', code]

    monkeypatch.setattr(codex_writer, 'executable', lambda: sys.executable)
    monkeypatch.setattr(codex_writer, 'command', transport)
    state = {'directory':tmp_path, 'calls':[], 'purpose':purpose}
    schema = {'type':'object', 'properties':{'text':{'type':'string'}}, 'required':['text']}
    assert codex_writer.chat('rules', 'data', schema, lambda:None, state) == {'text':'ok'}
    assert len(launched) == 2
    for args, receipt in zip(launched, state['calls']):
        if purpose == 'script_writing':
            assert args[args.index('--model')+1] == 'gpt-6-sol'
            assert receipt['model_selection'] == 'explicit'
            assert receipt['requested_model'] == 'gpt-6-sol'
        else:
            assert '--model' not in args
            assert receipt['model_selection'] == 'codex_cli_default'
            assert 'requested_model' not in receipt
        assert receipt['fallback'] is False


def test_unavailable_script_model_fails_without_default_model_retry(tmp_path, monkeypatch):
    requests = []
    def transport(binary, directory, schema, output, **options):
        requests.append(options)
        return [sys.executable, '-c', 'import json,sys;print(json.dumps({"type":"turn.failed","error":{"message":"model unavailable"}}),flush=True);sys.exit(1)']
    monkeypatch.setattr(codex_writer, 'executable', lambda:sys.executable)
    monkeypatch.setattr(codex_writer, 'command', transport)
    state = {'directory':tmp_path, 'calls':[], 'purpose':'script_writing'}
    with pytest.raises(RuntimeError, match='완료되지'):
        codex_writer.chat('rules', 'data', None, lambda:None, state)
    assert requests == [{'model':'gpt-6-sol'}]
    assert state['calls'][0]['status'] == 'failed'


def test_timeout_terminates_only_spawned_child_and_records_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_writer, 'executable', lambda: sys.executable)
    monkeypatch.setattr(codex_writer, 'command', lambda *a: [sys.executable, '-c', 'import time;time.sleep(30)'])
    state = {'directory': tmp_path, 'calls': []}
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        codex_writer.chat('rules', 'data', None, lambda: None, state, timeout=.1)
    assert time.monotonic()-start < 10
    assert state['calls'][0]['status'] == 'failed'
    import psutil
    assert not psutil.pid_exists(state['calls'][0]['pid'])
