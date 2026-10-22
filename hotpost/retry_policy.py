"""Conservative retry eligibility from exception types, never message keywords.

Eligibility is not permission to repeat a side effect: callers still own claims,
idempotency, backoff and retry limits. Capacity/access waits have their own handlers.
"""
from __future__ import annotations

import errno
from email.utils import parsedate_to_datetime
import socket
import sqlite3
import ssl
import subprocess
import time
from urllib.error import HTTPError, URLError

import requests
from urllib3 import exceptions as urllib3_errors

from .collectors.base import CollectionBlocked
from .model_service import ModelServiceUnavailable
from .operation_progress import NoProgressTimeout
from .source_access_preflight import SourceAccessWaiting


_HTTP_RETRY = {429, 502, 503, 504}
_CONNECTION_ERRNOS = {errno.ECONNRESET, errno.ECONNABORTED, errno.ECONNREFUSED,
                      errno.EPIPE, errno.ENETUNREACH, errno.EHOSTUNREACH}


def _retry_after(headers):
    """Only a real HTTP failure's header is passed here; body text is irrelevant."""
    if not hasattr(headers, 'items'):
        return None
    value = next((v for k, v in headers.items()
                  if isinstance(k, str) and k.casefold() == 'retry-after'), None)
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.isascii() and value.isdecimal() and len(value) <= 10:
        return int(value)
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is not None:
            return max(0.0, parsed.timestamp() - time.time())
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def _readonly_voice_wrapper(exc):
    """Preserve two known GET-only wrappers, never ambiguous synthesis submits."""
    if type(exc) is not RuntimeError or not isinstance(exc.__cause__, requests.RequestException):
        return False
    tb = exc.__traceback__
    if tb is None:
        return False
    while tb.tb_next is not None:
        tb = tb.tb_next
    # Match the actual loaded code object, not the error wording or caller stage.
    from .voicebench_adapter import VoiceBenchAdapter
    return tb.tb_frame.f_code in {VoiceBenchAdapter.voices.__code__, VoiceBenchAdapter.preview.__code__}


def classify_failure(exc, *, stage=''):
    """Return serializable classification without inspecting exception message text.

    ``stage`` is diagnostic context, not proof that a timeout is safe to repeat.
    Read/process/unknown timeouts require supervision or their dedicated handler.
    """
    seen = set()

    def result(error, category, retryable, reason, *, status=None, delay=None):
        material = {'exception_type': type(error).__module__ + '.' + type(error).__qualname__,
                    'stage': stage if isinstance(stage, str) else '', 'reason': reason}
        if status is not None:
            material['http_status'] = status
        number = getattr(error, 'errno', None)
        if type(number) is int:
            material['errno'] = number
        return {'category': category, 'retryable': retryable, 'reason': reason,
                'retry_after_seconds': delay, 'signature_material': material}

    def classify(error):
        if id(error) in seen:
            return result(error, 'unknown', False, 'cyclic_exception_wrapper')
        seen.add(id(error))
        if isinstance(error, NoProgressTimeout):
            return result(error, 'no_progress', False, 'useful_progress_stalled_requires_diagnosis')
        if isinstance(error, ModelServiceUnavailable):
            return result(error, 'model_service_wait', False, 'dedicated_model_capacity_handler')
        if isinstance(error, (CollectionBlocked, SourceAccessWaiting)):
            return result(error, 'access_blocked', False, 'dedicated_access_or_session_handler')
        if isinstance(error, sqlite3.Error):
            return result(error, 'storage', False, 'storage_error_requires_diagnosis')
        if isinstance(error, (requests.exceptions.SSLError, requests.exceptions.ProxyError,
                              urllib3_errors.SSLError, urllib3_errors.ProxyError, ssl.SSLError)):
            return result(error, 'transport_configuration', False, 'tls_or_proxy_requires_diagnosis')
        if isinstance(error, (requests.HTTPError, HTTPError)):
            if isinstance(error, HTTPError):
                status, headers = error.code, error.headers
            else:
                response = error.response
                status = getattr(response, 'status_code', None)
                headers = getattr(response, 'headers', None)
            if type(status) is not int or not 100 <= status <= 599:
                return result(error, 'unknown', False, 'http_status_unverified')
            if status in {401, 403, 407}:
                return result(error, 'access_blocked', False, 'http_auth_or_access_denied', status=status)
            retryable = status in _HTTP_RETRY
            return result(error, 'http_status', retryable, 'verified_http_' + str(status),
                          status=status, delay=_retry_after(headers) if retryable else None)
        if isinstance(error, (ValueError, TypeError, LookupError, AssertionError)):
            return result(error, 'input_validation', False, 'input_or_contract_defect')
        if isinstance(error, (PermissionError, FileNotFoundError, IsADirectoryError, NotADirectoryError)):
            return result(error, 'storage', False, 'filesystem_or_permission_defect')
        # urllib3 distinguishes temporary DNS failure from a nonexistent hostname.
        if isinstance(error, urllib3_errors.NameResolutionError):
            reason = getattr(error, '_reason', None)
            if isinstance(reason, socket.gaierror):
                return classify(reason)
            return result(error, 'transport_configuration', False, 'dns_reason_unverified')
        if isinstance(error, socket.gaierror):
            retryable = error.errno == socket.EAI_AGAIN
            return result(error, 'transport' if retryable else 'transport_configuration', retryable,
                          'temporary_dns_failure' if retryable else 'dns_configuration_or_unknown')
        if isinstance(error, (requests.exceptions.ConnectTimeout, urllib3_errors.ConnectTimeoutError)):
            return result(error, 'transport', True, 'typed_connect_failure')
        if isinstance(error, (TimeoutError, subprocess.TimeoutExpired, requests.Timeout,
                              urllib3_errors.TimeoutError)):
            return result(error, 'timeout_ambiguous', False, 'timeout_acceptance_or_progress_unknown')
        # Only transport-library wrappers may propagate a typed underlying cause.
        if isinstance(error, (URLError, urllib3_errors.MaxRetryError)):
            cause = error.reason
            if isinstance(cause, BaseException):
                return classify(cause)
            return result(error, 'unknown', False, 'transport_wrapper_without_typed_reason')
        if _readonly_voice_wrapper(error):
            return classify(error.__cause__)
        if isinstance(error, (requests.ConnectionError, urllib3_errors.ProtocolError)):
            nested = [arg for arg in error.args if isinstance(arg, BaseException)]
            if isinstance(error.__cause__, BaseException) and error.__cause__ not in nested:
                nested.append(error.__cause__)
            if nested:
                outcomes = [classify(arg) for arg in nested]
                return next((r for r in outcomes if not r['retryable']), outcomes[0])
            if isinstance(error, requests.ConnectionError):
                return result(error, 'transport', True, 'typed_connection_failure')
            return result(error, 'unknown', False, 'protocol_failure_without_typed_connection_reason')
        if isinstance(error, ConnectionError) or (
                isinstance(error, OSError) and error.errno in _CONNECTION_ERRNOS):
            return result(error, 'transport', True, 'typed_connection_failure')
        return result(error, 'unknown', False, 'unclassified_requires_diagnosis')

    # An explicit wrapper must never hide the watchdog's diagnosis by presenting
    # a broader transport/timeout type. Do not inspect unrelated implicit context.
    cause, causes = exc, set()
    while isinstance(cause, BaseException) and id(cause) not in causes:
        if isinstance(cause, NoProgressTimeout):
            return classify(cause)
        causes.add(id(cause))
        cause = cause.__cause__
    return classify(exc)
