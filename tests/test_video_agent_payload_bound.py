"""Bound actual owner wire input, preserving durable incident and read delivery."""
import copy
import hashlib
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from hotpost.video_agent_payload import MAX_INPUT_BYTES, input_bytes, owner_prompt


ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT/'data/writing/codex5abaa1627384599fd8360d4d0d6c5039/payload.json'


@pytest.fixture
def captured():
    if not CAPTURE.is_file():
        pytest.skip('Optional preserved actual input_too_large owner payload')
    raw = CAPTURE.read_bytes()
    return raw, json.loads(raw)


def project(payload, schema=None):
    text = owner_prompt(payload['instruction'], payload['evidence'], [], schema or {})
    assert input_bytes(payload['instruction'], text, schema or {}) <= MAX_INPUT_BYTES
    return text, json.loads(text)['evidence']


def entries(value):
    return value['items'] if isinstance(value, dict) and '_projection' in value else value


def test_actual_oversized_owner_payload_keeps_current_jobs_failure_and_full_latest_read(captured):
    raw, payload = captured
    before = copy.deepcopy(payload)
    original_prompt = json.dumps({'evidence': payload['evidence'], 'image_labels': []}, ensure_ascii=False)
    assert input_bytes(payload['instruction'], original_prompt, {}) > 1024 * 1024
    text, evidence = project(payload)
    assert payload == before and CAPTURE.read_bytes() == raw
    assert evidence['id'] == before['evidence']['id']
    assert evidence['fingerprint'] == before['evidence']['fingerprint']
    assert evidence['owner_epoch'] == before['evidence']['owner_epoch']
    assert evidence['production_tools_available'] == before['evidence']['production_tools_available']
    assert {j['id'] for j in entries(evidence['jobs'])} == {j['id'] for j in before['evidence']['jobs']}
    for job in before['evidence']['jobs']:
        projected = next(j for j in entries(evidence['jobs']) if j['id'] == job['id'])
        assert projected['status'] == job['status'] and projected['error'] == job['error']
        if 'failure_trace' in job['checkpoint']:
            assert projected['checkpoint']['failure_trace'] == job['checkpoint']['failure_trace']
    latest = next(step for step in reversed(before['evidence']['previous_steps'])
                  if isinstance(step.get('result'), dict) and isinstance(step['result'].get('content'), str))
    delivered = evidence['previous_steps']['latest_complete_read']
    assert delivered['result']['content'] == latest['result']['content']
    assert delivered['result'].get('next_offset') == latest['result'].get('next_offset')
    summary = evidence['model_input_projection']
    assert summary['projection_only'] is True and 'recall(decision_id' in summary['retrieval']
    assert summary['original_evidence_sha256'] == hashlib.sha256(json.dumps(before['evidence'], ensure_ascii=False, allow_nan=False).encode()).hexdigest()


@pytest.mark.parametrize('large', ['한글😀' * 90000, '\0"\\' * 90000], ids=['utf8', 'escaped'])
def test_utf8_and_escaped_wire_budget_not_character_budget(large):
    payload = {'instruction': 'Keep original ownership', 'evidence': {
        'id': 'work-0123456789abcdef', 'owner_epoch': 1,
        'allowed_actions': ['inspect_code', 'propose_patch'], 'old_result': large}}
    before = copy.deepcopy(payload)
    _, value = project(payload)
    assert value['allowed_actions'] == payload['evidence']['allowed_actions']
    assert value['old_result']['omitted'] is True
    assert payload == before


def test_complete_latest_read_is_not_excerpted_and_older_omitted_body_has_no_next_offset():
    content = ('한글😀 tail\n' * 6000)[:48000]
    step = {'action': {'kind': 'inspect_code', 'repo': 'main', 'path': 'hotpost/source_finder.py',
                       'offset': 4000, 'limit': 48000},
            'result': {'status': 'completed', 'content': content, 'offset': 4000,
                       'next_offset': 4000 + len(content), 'base_sha256': 'a' * 64}}
    payload = {'instruction': 'Original guards', 'evidence': {
        'id': 'work-0123456789abcdef', 'previous_steps': [step],
        'working_evidence': [dict(decision_id=str(n), **copy.deepcopy(step)) for n in range(10)],
        'padding': 'x' * 900000}}
    _, value = project(payload)
    latest = value['previous_steps']['latest_complete_read']['result']
    assert latest['content'] == content and latest['next_offset'] == 4000 + len(content)
    omitted = [row['result'] for row in entries(value['working_evidence'])
               if isinstance(row.get('result'), dict) and 'content_omitted' in row['result']]
    assert omitted
    for row in omitted:
        assert 'next_offset' not in row and 'content' not in row
        again = row['content_omitted']['read_again']
        assert again['offset'] == 4000 and again['path'] == 'hotpost/source_finder.py'


def test_current_job_is_kept_before_older_jobs_and_no_mutable_aliases():
    current = {'id': 'job-current', 'kind': 'collect_sources', 'status': 'paused', 'error': 'real error',
               'checkpoint': {'failure_trace': {'type': 'ValueError', 'message': 'actual current cause',
                                               'frames': [{'path': 'hotpost/current.py', 'line': 42}]},
                              'huge_history': [{'noise': 'x' * 50000}] * 40}, 'payload': {'run_id': 'run-current'}}
    payload = {'instruction': 'Original guards', 'evidence': {
        'recovery_job_id': 'job-current', 'jobs': [current, *[dict(id='job-' + str(n), noise='x' * 80000) for n in range(40)]]}}
    _, value = project(payload)
    actual = entries(value['jobs'])[0]
    assert actual['id'] == 'job-current' and actual['error'] == 'real error'
    assert actual['checkpoint']['failure_trace'] == current['checkpoint']['failure_trace']
    actual['checkpoint']['failure_trace']['message'] = 'changed projection only'
    assert current['checkpoint']['failure_trace']['message'] == 'actual current cause'


def test_repair_diagnostic_has_short_explicit_failure_lines_and_exact_log_reference():
    diagnostics = {'repair_id': 'repair-actual', 'incident_fixture': {'sha256': 'b' * 64},
                   'tests': [{'log_path': 'C:/evidence/verified-tests.log', 'log_sha256': 'c' * 64,
                              'passed': False, 'returncode': 1,
                              'log_excerpt': 'setup details\n' * 400 + '\nE AssertionError: External call count before=6 after=8\nFAILED test_real_entry\n' + 'tail\n' * 2000}],
                   'incident': {'task': {'id': 'work-real'}, 'noise': 'x' * 180000}}
    payload = {'instruction': 'Original guards', 'evidence': {
        'previous_steps': [{'action': {'kind': 'inspect_repair', 'repair_id': 'repair-actual'},
                            'result': {'status': 'completed', 'diagnostics': diagnostics}}], 'padding': 'x' * 900000}}
    _, value = project(payload)
    text = json.dumps(value, ensure_ascii=False)
    assert 'External call count before=6 after=8' in text
    assert 'C:/evidence/verified-tests.log' in text and 'c' * 64 in text
    assert 'inspect_repair' in text and 'repair-actual' in text


def test_small_input_is_unchanged_and_oversized_instruction_fails_before_model():
    original = {'allowed_actions': ['inspect_code'], 'jobs': []}
    assert json.loads(owner_prompt('rules', original, [], {}))['evidence'] == original
    with pytest.raises(ValueError, match='no model request sent'):
        owner_prompt('x' * MAX_INPUT_BYTES, original, [], {})


def test_large_recall_search_preserves_exact_query_and_page_for_reread():
    payload = {'instruction': 'Preserve durable recall navigation', 'evidence': {
        'previous_steps': [{'action': {'kind': 'recall', 'query': 'External call count', 'offset': 20, 'limit': 10},
                            'result': {'status': 'completed', 'entries': [
                                {'decision_id': str(n), 'reason': 'x' * 80000} for n in range(20)]}}]}}
    _, projected = project(payload)
    def readers(value):
        if isinstance(value, dict):
            if isinstance(value.get('read_again'), dict):
                yield value['read_again']
            for child in value.values():
                yield from readers(child)
        elif isinstance(value, list):
            for child in value:
                yield from readers(child)
    again = [r for r in readers(projected) if r.get('kind') == 'recall']
    assert again and all(r['query'] == 'External call count' and r['offset'] == 20 and r['limit'] == 10 for r in again)


def test_real_writer_entry_bounds_actual_request_and_preserves_original_payload(captured, tmp_path, monkeypatch):
    from hotpost.writing import codex_writer, owner_session
    from hotpost.writing.jobs import Jobs
    from test_video_owner_session import response
    raw, payload = captured
    original = copy.deepcopy(payload)
    expected = {'action': {'kind': 'inspect_code', 'hypothesis': 'Read the exact preserved incident next.'}}
    calls = []
    def transport(binary, cwd, schema, output, thread):
        request = (Path(output).parent/'request.txt').read_bytes()
        calls.append(len(request))
        assert len(request) < MAX_INPUT_BYTES
        return response(output, thread or str(uuid4()), text=json.dumps(expected))
    monkeypatch.setattr(codex_writer, 'executable', lambda: sys.executable)
    monkeypatch.setattr(owner_session, 'command', transport)
    jobs = Jobs(tmp_path/'writing')
    job = jobs.create('video_agent', payload)
    saved_file = jobs.root/job['id']/'payload.json'
    before = saved_file.read_bytes()
    jobs.execute(job)
    finished = jobs.get(job['id'])
    assert finished['state'] == 'completed', finished.get('error')
    assert finished['result']['value'] == expected
    assert len(calls) == 1
    assert saved_file.read_bytes() == before and payload == original and CAPTURE.read_bytes() == raw
    assert finished['payload'] == original


def test_projection_helper_is_protected_from_domain_repairs():
    from hotpost.video_agent_repairs import _PROTECTED
    assert 'video_agent_payload.py' in _PROTECTED
