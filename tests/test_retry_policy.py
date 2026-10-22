"""Typed retry boundaries: misleading prose cannot request a retry."""
from datetime import datetime, timezone
from email.utils import format_datetime
import errno
import socket
import sqlite3
import subprocess
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest
import requests
from urllib3 import exceptions as u3

from hotpost.retry_policy import classify_failure
from hotpost.operation_progress import NoProgressTimeout, ProgressWatch
from hotpost.model_service import ModelServiceUnavailable
from hotpost.collectors.base import CollectionBlocked


def http_error(status, headers=None, text='content timeout HTTP 503 CAPTCHA'):
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    return requests.HTTPError(text, response=response)


@pytest.mark.parametrize('exc', [
    RuntimeError('timeout HTTP 503 connection reset'),
    ValueError('HTTP 429 connection refused'),
    RuntimeError('CAPTCHA login'), RuntimeError('normal long running work'),
    TimeoutError('HTTP 503'), subprocess.TimeoutExpired(['render'], 1800),
    requests.Timeout('timeout'), requests.exceptions.ReadTimeout('HTTP 503'),
    NoProgressTimeout('connection reset HTTP 503'),
    sqlite3.OperationalError('database is locked timeout 503'),
    sqlite3.IntegrityError('connection'), PermissionError('connection timeout'),
    FileNotFoundError('HTTP 503 input.wav'), requests.exceptions.InvalidURL('connection'),
    requests.exceptions.SSLError('connection reset'), requests.exceptions.ProxyError('HTTP 503'),
    URLError('connection reset'), u3.MaxRetryError(None, '/x', 'HTTP 503'),
    u3.ProtocolError('connection reset'), ModelServiceUnavailable('HTTP 503'),
    CollectionBlocked('captcha', 'connection reset'),
])
def test_unknown_content_access_storage_and_timeouts_never_blind_retry(exc):
    for stage in ['', 'connect', 'edit', 'source_search', 'voice']:
        assert not classify_failure(exc, stage=stage)['retryable']


@pytest.mark.parametrize('exc', [
    ConnectionResetError('input caption says CAPTCHA'), ConnectionRefusedError(),
    ConnectionAbortedError(), BrokenPipeError(), ConnectionError(),
    OSError(errno.ENETUNREACH, 'text'), requests.ConnectionError('login in quoted caption'),
    requests.exceptions.ConnectTimeout(), u3.ConnectTimeoutError(),
    u3.NewConnectionError(None, 'refused'),
    URLError(ConnectionRefusedError()),
    u3.MaxRetryError(None, '/x', ConnectionResetError()),
    requests.ConnectionError(u3.ProtocolError('aborted', ConnectionResetError())),
    socket.gaierror(socket.EAI_AGAIN, 'temporary'),
])
def test_typed_connection_failures_are_retry_candidates_independent_of_text(exc):
    assert classify_failure(exc)['retryable']


@pytest.mark.parametrize('code,eligible', [(401, False), (403, False), (407, False),
    (404, False), (408, False), (409, False), (429, True), (500, False),
    (502, True), (503, True), (504, True)])
def test_only_explicit_status_codes_are_retryable(code, eligible):
    for exc in [http_error(code), HTTPError('https://example.test', code, 'HTTP 503', {}, None)]:
        assert classify_failure(exc)['retryable'] is eligible


def test_response_body_strings_and_untyped_response_attributes_are_not_status_proof():
    error = RuntimeError('503')
    error.response = SimpleNamespace(status_code=503, headers={'Retry-After': '60'})
    assert not classify_failure(error)['retryable']
    for value in [None, '503', True, 99, 600]:
        exc = requests.HTTPError('503', response=SimpleNamespace(status_code=value, headers={}))
        assert not classify_failure(exc)['retryable']
    assert not classify_failure(requests.HTTPError('HTTP 503'))['retryable']
    assert not classify_failure(http_error(400, {'Retry-After': '60'}))['retryable']


@pytest.mark.parametrize('header,expected', [('120', 120), (' 0 ', 0), ('-1', None),
    ('1.5', None), ('nan', None), ('infinity', None), ('HTTP 503', None),
    ('99999999999999999999999999', None), ('１２', None), ('', None)])
def test_retry_after_requires_valid_delta_seconds(header, expected):
    assert classify_failure(http_error(429, {'retry-after': header}))['retry_after_seconds'] == expected


def test_retry_after_http_date_and_response_status_are_bound(monkeypatch):
    now = 1800000000
    monkeypatch.setattr('hotpost.retry_policy.time.time', lambda: now)
    value = format_datetime(datetime.fromtimestamp(now + 90, timezone.utc), usegmt=True)
    assert classify_failure(http_error(503, {'Retry-After': value}))['retry_after_seconds'] == 90
    assert classify_failure(http_error(401, {'Retry-After': value}))['retry_after_seconds'] is None
    old = format_datetime(datetime.fromtimestamp(now - 5, timezone.utc), usegmt=True)
    assert classify_failure(http_error(503, {'Retry-After': old}))['retry_after_seconds'] == 0


def test_transport_wrappers_cannot_hide_permanent_or_no_progress_error():
    for inner in [NoProgressTimeout(), requests.exceptions.SSLError(),
                  socket.gaierror(socket.EAI_NONAME, 'unknown host'), ValueError('HTTP 503')]:
        assert not classify_failure(requests.ConnectionError(inner))['retryable']
    err = RuntimeError('VoiceBench unknown submission')
    err.__cause__ = requests.ConnectionError()
    assert not classify_failure(err)['retryable']
    for wrapper in [requests.ConnectionError('503'), http_error(503), RuntimeError('timeout')]:
        wrapper.__cause__ = NoProgressTimeout('actual progress stalled')
        assert classify_failure(wrapper)['category'] == 'no_progress'
        assert not classify_failure(wrapper)['retryable']
    error = requests.ConnectionError('transport')
    error.__cause__ = requests.exceptions.SSLError('certificate')
    assert not classify_failure(error)['retryable']


def test_cyclic_transport_reason_is_rejected():
    error = URLError('placeholder')
    error.reason = error
    assert not classify_failure(error)['retryable']


def test_real_readonly_voice_wrapper_preserves_typed_transport_but_submit_does_not(tmp_path):
    from hotpost.voicebench_adapter import VoiceBenchAdapter
    class Session:
        def get(self, *a, **kw): raise requests.ConnectionError('network')
        def post(self, *a, **kw): raise requests.ConnectionError('network')
    adapter = VoiceBenchAdapter(SimpleNamespace(voicebench_url='http://localhost'), session=Session())
    adapter._headers = lambda: {}
    for operation in [adapter.voices, lambda: adapter.preview('voice')]:
        with pytest.raises(RuntimeError) as caught: operation()
        assert classify_failure(caught.value)['retryable']
    with pytest.raises(RuntimeError) as caught:
        adapter._synthesis_request('post', '/v1/tts', headers={}, timeout=1, safe_retry=False)
    assert not classify_failure(caught.value)['retryable']


def test_long_work_with_actual_progress_is_not_a_failure_and_stall_never_retries():
    now = [0]
    watch = ProgressWatch(10, 'CPU solver', clock=lambda: now[0])
    for step in range(1, 100):
        now[0] += 9
        watch.observe('completed_nodes', step)
        watch.check()
    now[0] += 10
    with pytest.raises(NoProgressTimeout) as caught: watch.check()
    outcome = classify_failure(caught.value, stage='edit')
    assert outcome['category'] == 'no_progress' and not outcome['retryable']


def test_signature_omits_messages_urls_and_keeps_structured_material():
    a = classify_failure(ConnectionResetError('secret input one'), stage='voice')
    b = classify_failure(ConnectionResetError('different caption HTTP 503'), stage='voice')
    assert a == b and a['signature_material']['stage'] == 'voice'
    assert 'secret' not in str(a)
