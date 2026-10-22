"""Classify execution receipts independently from human-readable error text.

Transport markers, submitted queries and consumed content scopes are distinct.
Legacy successful result receipts remain usable; local UI failures cannot become
content failures merely because they contain a query string.
"""
from __future__ import annotations

import unicodedata
import copy

SEARCH_ACCESS_WAITS = {
    'captcha', 'captcha_review_pending', 'verification_required', 'login_required', 'rate_limited',
    'cooldown', 'browser_busy', 'model_wait', 'service_wait', 'waiting',
    'connection_failed', 'access_denied', 'current_browser_error',
    'tab_missing', 'tab_ambiguous', 'tab_unavailable', 'browser_error_page',
    'window_unavailable', 'readiness_blocked',
}
SEARCH_SKIPS = {
    'not_attempted', 'no_supported_queries', 'query_exhausted',
    'image_exhausted', 'budget_exhausted', 'strategy_skipped',
    'readiness_blocked', 'platform_disabled',
}
CONTENT_RESULTS = {'results', 'no_results', 'query_restricted'}
LOCAL_SEARCH_STAGES = {
    'locate_search_input', 'open_search_panel', 'locate_search_panel',
    'input_mismatch', 'query_input_mismatch', 'query_input_intent',
    'prepare_search_input', 'select_search_input',
}
QUERY_TRANSPORT_OPERATIONS = {
    'indexed_search', 'visible_search_input_enter', 'query_submit',
    'search_submit', 'image_upload',
}


def _normalize(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value)).casefold().split())


def search_execution(row):
    """Return evidence-only query execution and content-consumption decisions."""
    status = str(row.get('status', ''))
    stage = str(row.get('stage', ''))
    raw_requests = row.get('requests') or []
    requests = raw_requests if isinstance(raw_requests, (list, tuple)) else []
    legacy_count = raw_requests if isinstance(raw_requests, int) else len(requests)
    execution = row.get('execution')
    execution = execution if isinstance(execution, dict) else {}
    result = {'attempted': False, 'consumed': False, 'pending': False,
              'query_submitted': False, 'query_url_matched': False,
              'request_marker_count': max(0, legacy_count), 'basis': 'unverified'}
    if row.get('provider') == 'browser-worker' or not row.get('query'):
        result['basis'] = 'no_query_execution'
        return result
    if execution:
        submitted = execution.get('query_submitted') is True
        matched = execution.get('query_url_matched') is True
        value = execution.get('actual_input_value', execution.get('input_value'))
        if value is not None and row.get('language') != 'image' and _normalize(value) != _normalize(row['query']):
            result.update(pending=True, basis='input_query_mismatch')
            return result
        result.update(attempted=submitted, query_submitted=submitted,
                      query_url_matched=matched)
        if submitted and matched and status in CONTENT_RESULTS:
            result.update(consumed=True, basis='submitted_matching_content_result')
        elif status in SEARCH_ACCESS_WAITS:
            result['basis'] = 'access_wait_after_submit' if submitted else 'access_wait_before_submit'
        elif not submitted:
            resolved = execution.get('resolution') == 'confirmed_not_submitted'
            result.update(pending=not resolved and status not in SEARCH_SKIPS,
                          basis='confirmed_not_submitted' if resolved else 'query_not_submitted')
        else:
            result.update(pending=True, basis='submitted_result_unconfirmed')
        return result
    # These stages occur before Enter. A navigation/search-home request cannot
    # contradict the explicit evidence that the query itself was never sent.
    if stage in LOCAL_SEARCH_STAGES:
        result.update(pending=status not in SEARCH_SKIPS | SEARCH_ACCESS_WAITS,
                      basis='legacy_local_pre_submit')
        return result
    # Old results/no-results receipts are the historical content evidence. Do
    # not discard them because their original implementation predates execution.
    if status in CONTENT_RESULTS:
        result.update(attempted=True, consumed=True, query_submitted=True,
                      basis='legacy_content_result')
        return result
    operations = {r.get('operation') for r in requests if isinstance(r, dict)}
    submitted = bool(operations & QUERY_TRANSPORT_OPERATIONS)
    # Legacy HTTP/access receipts prove transport happened, without proving a
    # completed content search. Explicit new pre-submit flags take precedence.
    transport = (legacy_count > 0 and status in SEARCH_ACCESS_WAITS or
                 row.get('http_status') is not None)
    # A legacy search_input marker is recorded BEFORE actual typing/Enter.
    # It proves intent, not that the requested query reached the platform.
    result.update(attempted=submitted or transport, query_submitted=submitted)
    if status in SEARCH_ACCESS_WAITS:
        result['basis'] = 'legacy_access_wait'
    elif status in {'', 'started'} and (submitted or 'search_input' in operations):
        result.update(pending=True, basis='legacy_started_execution_unconfirmed')
    elif status in SEARCH_SKIPS | {'', 'started'}:
        result['basis'] = 'legacy_no_content_result'
    else:
        result.update(pending=True, basis='legacy_execution_unconfirmed')
    return result


def candidate_execution(row):
    """Classify candidate transfer/access, respecting explicit non-attempts."""
    diagnostics = row.get('download_diagnostics') or {}
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    fallback = diagnostics.get('fallback') or {}
    observation = diagnostics.get('access_observation') or {}
    observation = observation if isinstance(observation, dict) else {}
    resolution = diagnostics.get('access_resolution_error') or diagnostics.get('tab_resolution')
    status = observation.get('kind') or diagnostics.get('access_status')
    explicit = row.get('download_attempted')
    attempted = explicit is True
    if explicit is None:
        attempted = bool(row.get('downloaded_file') or diagnostics.get('attempted') or
                         isinstance(fallback, dict) and fallback.get('attempted') or
                         'download_failed' in (row.get('rejection_reasons') or []))
    if isinstance(resolution, dict):
        resolution = resolution.get('reason') or resolution.get('status')
    local = {'tab_missing', 'tab_ambiguous', 'tab_unavailable', 'browser_error_page',
             'window_unavailable', 'current_browser_error'}
    if resolution in local:
        status = str(resolution)
    elif status == 'auth_required':
        status = 'login_required'
    elif status in {'', None}:
        status = None
    error = str(row.get('error', '')).lower()
    if status is None and not diagnostics:
        # Preserve legacy saved gates, but do not interpret the phrase
        # "existing logged-in tab" as an observed login-wall error.
        if ('existing_browser_tab_' in error or 'existing_youtube_tab_' in error or
                ('탭' in error and any(t in error for t in ('하나로 지정', '찾을 수 없', '없습니다')))):
            status = 'tab_unavailable'
        elif '429' in error or 'rate_limited' in error:
            status = 'rate_limited'
        elif 'captcha_review_pending' in error:
            status = 'captcha_review_pending'
        elif 'captcha' in error or 'verification_required' in error:
            status = 'captcha'
        elif '403' in error:
            status = 'access_denied'
        elif any(t in error for t in ('login', '401', 'authentication', 'sign in', '로그인', '인증 확인')):
            status = 'login_required'
        elif 'cooldown' in error:
            status = 'cooldown'
    reason = {'login_required': 'auth_required'}.get(status, status)
    return {'attempted': attempted, 'access_status': status, 'reason': reason,
            'waiting': not row.get('downloaded_file') and status in SEARCH_ACCESS_WAITS,
            'observed': observation.get('observed') is True,
            'basis': observation.get('basis') or ('typed_tab_resolution' if resolution else
                     'typed_access_status' if diagnostics.get('access_status') else
                     'typed_transfer_receipt' if diagnostics else 'legacy_transfer_record')}


def unresolved_search_scope(row, current_parser_revision=None):
    """Pending is not consumed, but must not silently authorize retransmission."""
    receipt = search_execution(row)
    if not receipt['pending']:
        return False
    if receipt['query_submitted']:
        return True  # A code/parser change cannot prove the prior request failed.
    previous = row.get('parser_revision')
    return not previous or not current_parser_revision or previous == current_parser_revision


def _transfer_text(value):
    import re
    value=re.sub(r'https?://[^\s\"\'<>]+','[redacted-url]',value)
    value=re.sub(r'(?i)(authorization|(?:set-)?cookie)\s*[:=][^\r\n]+',r'\1: [redacted]',value)
    return re.sub(r'(?i)\bBearer\s+[^\s]+','Bearer [redacted]',value)[:500]


def transfer_diagnostics(stats):
    """Keep typed transfer provenance across the candidate/manifest boundary."""
    keys = {'attempted', 'navigation_started', 'access_status', 'tab_resolution',
            'access_resolution_error', 'access_observation'}
    result = {key: copy.deepcopy(stats[key]) for key in keys if key in stats}
    import math
    import re
    for key in ('started_at','ended_at','direct_ended_at','first_response_at','last_progress_at',
                'media_responses','partial_responses','body_errors','metadata_urls',
                'max_visible_players','assembled_files','saved_bytes','covered_bytes'):
        value=stats.get(key)
        if type(value) in (int,float) and math.isfinite(value) and value>=0:
            result[key]=value
    for key in ('stage','failure_stage','error_type','error','direct_error','method','source_kind',
                'blocked_provider','blocked_reason'):
        if isinstance(stats.get(key),str):
            result[key]=_transfer_text(stats[key])
    for key in ('complete','submitted','response_blocked','playback_started'):
        if type(stats.get(key)) is bool:result[key]=stats[key]
    result['stage_events']=[{'stage':_transfer_text(str(r.get('stage','')))[:60],'at':r['at']}
        for r in (stats.get('stage_events') or [])[:40]
        if isinstance(r,dict) and type(r.get('at')) in (int,float) and math.isfinite(r['at'])]
    # Preserve numeric summaries, never media URLs, headers or response bodies.
    if isinstance(stats.get('received_streams'),list):
        result['received_streams']=[{k:v for k,v in row.items() if
            (k in {'total_bytes','covered_bytes'} and type(v) is int and v>=0)
            or (k=='bound_to_item' and type(v) is bool)}
            for row in stats['received_streams'][:4] if isinstance(row,dict)]
    if isinstance(stats.get('fallback'), dict):
        result['fallback'] = transfer_diagnostics(stats['fallback'])
    return result
