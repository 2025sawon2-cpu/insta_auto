"""Execution provenance is not inferred from query/error prose."""
import copy
import json

import pytest

from hotpost.source_attempts import candidate_execution, search_execution, transfer_diagnostics
from hotpost.source_outcomes import platform_outcomes
from hotpost.source_search.strategy import attempted, candidate_ledgers, consumed_scope, fresh_frames, fresh_queries, image_sha256, merge_history


def native(**extra):
    return {'provider': 'tiktok', 'query': '사과', 'language': 'ko', **extra}


@pytest.mark.parametrize('requests', [[], [{'operation': 'search_home'}], [{'operation': 'search_input'}]])
def test_locator_error_before_enter_is_not_an_attempt_or_consumed_scope(requests):
    row = native(status='error', stage='locate_search_input', requests=requests,
                 visible_search_controls=3, error='TimeoutError')
    assert not attempted(row) and not consumed_scope(row)
    assert search_execution(row)['pending']
    outcome = platform_outcomes([], [row])['tiktok']
    assert outcome['search_attempts'] == 0 and outcome['consumed_search_scopes'] == 0
    assert 'search_failed' not in outcome['reasons']
    assert 'auth_required' not in outcome['reasons']


def test_explicit_query_not_submitted_overrides_request_intent_and_results_label():
    row = native(status='results', requests=[{'operation': 'search_input'}],
                 execution={'query_submitted': False, 'query_url_matched': False, 'input_value': '사과'})
    assert not attempted(row) and not consumed_scope(row)


def test_actual_submitted_matching_result_consumes_only_its_scope():
    row = native(status='results', candidates=5, page=2,
                 execution={'query_submitted': True, 'query_url_matched': True, 'input_value': '사과'})
    assert attempted(row) and consumed_scope(row)
    assert not fresh_queries(['사과'], 'tiktok', [row], scope={'page': 2})
    assert fresh_queries(['사과'], 'tiktok', [row]) == ['사과']


@pytest.mark.parametrize('status', ['no_results', 'query_restricted'])
def test_confirmed_empty_or_restricted_response_is_content_evidence(status):
    row = native(status=status, execution={'query_submitted': True, 'query_url_matched': True})
    assert attempted(row) and consumed_scope(row)


@pytest.mark.parametrize('status', ['captcha', 'login_required', 'rate_limited', 'access_denied'])
def test_real_access_response_does_not_consume_content_scope(status):
    row = native(status=status, execution={'query_submitted': True, 'query_url_matched': True})
    assert attempted(row) and not consumed_scope(row)
    assert not search_execution(row)['pending']


def test_submitted_unknown_response_remains_pending_without_automatic_retransmission(monkeypatch):
    row = native(status='error', parser_revision='old',
                 execution={'query_submitted': True, 'query_url_matched': False}, error='TimeoutError')
    monkeypatch.setattr('hotpost.source_search.readiness.parser_revision', lambda _: 'fixed')
    assert attempted(row) and not consumed_scope(row)
    assert search_execution(row)['pending']
    assert fresh_queries(['사과'], 'tiktok', [row]) == []
    outcome = platform_outcomes([], [row])['tiktok']
    assert outcome['reasons']['search_unconfirmed'] == 1
    assert 'search_failed' not in outcome['reasons']


def test_input_value_mismatch_is_unresolved_even_with_forged_success():
    row = native(status='results',
                 execution={'query_submitted': True, 'query_url_matched': True, 'input_value': 'apple사과'})
    assert not attempted(row) and not consumed_scope(row)
    assert search_execution(row)['basis'] == 'input_query_mismatch'


def test_legacy_verified_result_survives_receipt_upgrade():
    row = native(status='results', candidates=5, result_method='search_response')
    assert attempted(row) and consumed_scope(row)
    assert merge_history([row])[0]['result_method'] == 'search_response'


def test_legacy_numeric_transport_counter_remains_a_nonconsuming_access_receipt():
    row = native(status='captcha', requests=1)
    receipt = search_execution(row)
    assert receipt['attempted'] and not receipt['consumed'] and not receipt['pending']
    assert receipt['request_marker_count'] == 1


def test_generic_error_has_no_fabricated_content_failure_and_is_not_replayed():
    row = native(status='error', error='unclassified legacy parser failure')
    assert not attempted(row) and not consumed_scope(row)
    assert fresh_queries(['사과'], 'tiktok', [row]) == []
    saved = copy.deepcopy(row)
    assert merge_history([row]) and row == saved


def test_legacy_started_request_without_result_is_preserved_as_pending():
    row = native(status='started', requests=[{'operation': 'visible_search_input_enter'}])
    assert search_execution(row)['pending'] and not consumed_scope(row)
    assert merge_history([row]) and fresh_queries(['사과'], 'tiktok', [row]) == []


def test_pre_submit_pending_scope_requires_actual_parser_change(monkeypatch):
    row = native(status='page_unresolved', stage='locate_search_input', parser_revision='same')
    monkeypatch.setattr('hotpost.source_search.readiness.parser_revision', lambda _: 'same')
    assert fresh_queries(['사과'], 'tiktok', [row]) == []
    monkeypatch.setattr('hotpost.source_search.readiness.parser_revision', lambda _: 'repaired-method')
    assert fresh_queries(['사과'], 'tiktok', [row]) == ['사과']


def test_scoped_not_submitted_correction_preserves_other_confirmed_queries():
    apple = native(query='apple', language='en', status='results', candidates=5)
    corrected = native(status='not_attempted', stage='locate_search_input',
                       execution={'query_submitted': False, 'query_url_matched': False,
                                  'resolution': 'confirmed_not_submitted'})
    history = [apple, corrected]
    before = copy.deepcopy(history)
    assert fresh_queries(['apple', '사과'], 'tiktok', history) == ['사과']
    assert history == before and consumed_scope(apple)


def test_merge_history_preserves_pending_execution_stage_and_confirmed_result():
    confirmed = native(status='results')
    pending = native(status='error', stage='submit_search',
                     execution={'query_submitted': True, 'query_url_matched': False},
                     requests=[{'operation': 'search_input'}])
    history = merge_history([confirmed], [pending])
    assert len(history) == 2
    assert history[1]['execution'] == pending['execution'] and history[1]['stage'] == 'submit_search'
    assert not fresh_queries(['사과'], 'tiktok', history)


def test_pending_image_upload_is_not_automatically_repeated_for_the_same_frame(tmp_path):
    frame = tmp_path / 'frame.jpg'
    frame.write_bytes(b'unchanged actual frame bytes')
    next_frame = tmp_path / 'different.jpg'
    next_frame.write_bytes(b'actual different frame')
    row = {'provider': 'google-lens', 'language': 'image', 'query': frame.name,
           'image_sha256': image_sha256(frame), 'status': 'error',
           'requests': [{'operation': 'image_upload'}]}
    assert not consumed_scope(row) and search_execution(row)['pending']
    assert fresh_frames([frame, next_frame], 'google-lens', merge_history([row])) == [next_frame]


def candidate(**extra):
    return {'url': 'https://www.tiktok.com/@a/video/1234567890', 'platform': 'tiktok',
            'download_attempted': False, 'rejection_reasons': ['not_attempted'], **extra}


@pytest.mark.parametrize('resolution', ['tab_missing', 'tab_ambiguous', 'browser_error_page', 'window_unavailable'])
def test_typed_tab_resolution_is_not_a_login_wall(resolution):
    row = candidate(error='기존 로그인된 TikTok 탭을 하나로 지정해야 합니다.',
                    download_diagnostics={'access_status': 'not_attempted',
                                          'tab_resolution': resolution, 'attempted': False})
    execution = candidate_execution(row)
    assert not execution['attempted'] and execution['access_status'] == resolution
    ledgers = candidate_ledgers([row])
    assert ledgers['access_waits'][0]['status'] == resolution
    assert not ledgers['attempted_urls'] and not ledgers['inspected_urls']
    outcome = platform_outcomes([row], [])['tiktok']
    assert outcome['download_attempts'] == 0
    assert 'auth_required' not in outcome['reasons'] and 'download_failed' not in outcome['reasons']


def test_legacy_existing_logged_in_tab_description_does_not_invent_auth():
    row = candidate(error='TikTok 현재 브라우저 영상 수신 실패: 기존 로그인된 TikTok 탭을 하나로 지정해야 합니다. 새 탭은 만들지 않습니다.')
    assert candidate_execution(row)['access_status'] == 'tab_unavailable'
    assert candidate_ledgers([row])['access_waits'][0]['status'] == 'tab_unavailable'


@pytest.mark.parametrize('message', [
    '로그인한 Chrome 세션 연결 오류',
    'captcha 재확인 페이지를 못 찾아 현재 미확인',
    'cache key 403 was unavailable',
])
def test_typed_nonattempt_cannot_invent_access_state_from_error_words(message):
    row = candidate(error=message, download_diagnostics={'attempted': False, 'access_status': 'not_attempted'})
    receipt = candidate_execution(row)
    assert receipt['access_status'] == 'not_attempted' and not receipt['waiting']
    ledger = candidate_ledgers([row])
    assert not ledger['access_waits'] and not ledger['attempted_urls'] and not ledger['inspected_urls']
    outcome = platform_outcomes([row], [])['tiktok']
    assert outcome['download_attempts'] == 0 and outcome['reasons'] == {'not_attempted': 1}


def test_typed_attempt_without_access_observation_cannot_invent_auth_failure():
    row = candidate(error='로그인한 세션 연결 오류', download_attempted=True,
                    rejection_reasons=['download_failed'], download_diagnostics={'attempted': True})
    assert not candidate_execution(row)['access_status']
    assert platform_outcomes([row], [])['tiktok']['reasons'] == {'download_failed': 1}


def test_real_403_is_access_denied_and_preserves_actual_transfer_attempt():
    row = candidate(download_attempted=True, rejection_reasons=['download_failed'],
                    error='existing login tab', download_diagnostics={
                        'attempted': True, 'access_status': 'access_denied',
                        'access_observation': {'kind': 'access_denied', 'observed': True, 'http_status': 403}})
    result = candidate_execution(row)
    assert result['attempted'] and result['observed'] and result['access_status'] == 'access_denied'
    outcome = platform_outcomes([row], [])['tiktok']
    assert outcome['download_attempts'] == 1 and outcome['reasons'] == {'access_denied': 1}


@pytest.mark.parametrize('kind', ['login_required', 'captcha', 'rate_limited'])
def test_observed_access_and_saved_gate_remain_distinct_from_content_failure(kind):
    for observed in (True, False):
        row = candidate(download_diagnostics={
            'attempted': False, 'access_status': kind,
            'access_observation': {'kind': kind, 'observed': observed, 'basis': 'current_screen' if observed else 'saved_gate'}})
        receipt = candidate_execution(row)
        assert receipt['waiting'] and receipt['observed'] is observed
        assert receipt['attempted'] is False
        assert not candidate_ledgers([row])['attempted_urls']


def test_local_cache_receipt_does_not_fabricate_network_transfer():
    row = candidate(downloaded_file='cached.mp4', acquisition='local-cache', rejection_reasons=[])
    assert not candidate_execution(row)['attempted']
    assert platform_outcomes([row], [])['tiktok']['download_attempts'] == 0


def test_transfer_diagnostics_crosses_manifest_boundary_without_unrelated_data():
    stats = {'attempted': False, 'access_status': 'not_attempted', 'tab_resolution': 'tab_missing',
             'access_observation': {'kind': 'tab_missing', 'observed': False},
             'unrelated_response_body': 'do not copy', 'fallback': {'attempted': False, 'access_status': 'cooldown'}}
    result = transfer_diagnostics(stats)
    assert result['tab_resolution'] == 'tab_missing' and result['fallback']['access_status'] == 'cooldown'
    assert 'unrelated_response_body' not in result
    result['access_observation']['kind'] = 'changed'
    assert stats['access_observation']['kind'] == 'tab_missing'
    assert json.loads(json.dumps(result)) == result


def test_downloader_typed_provenance_reaches_the_serialized_candidate(tmp_path, monkeypatch):
    from dataclasses import asdict
    from hotpost.config import Settings
    from hotpost.source_finder import Candidate, download_candidate
    from hotpost import tikvideo_download
    monkeypatch.setattr('hotpost.config.load_settings', lambda: Settings(data_dir=tmp_path))
    monkeypatch.setattr('hotpost.source_collection_access.collection_disabled', lambda _: False)
    def fail(*args, diagnostics, **kwargs):
        diagnostics.update(attempted=False, access_status='not_attempted', tab_resolution='browser_error_page')
        raise RuntimeError('existing logged-in session tab is unavailable')
    monkeypatch.setattr(tikvideo_download, 'with_fallback', fail)
    folder = tmp_path / 'run' / 'videos'
    folder.mkdir(parents=True)
    row = Candidate('https://www.tiktok.com/@a/video/1234567890', 'tiktok')
    assert download_candidate(row, folder, 1, 80) is None
    serialized = asdict(row)
    assert serialized['download_attempted'] is False
    assert serialized['download_diagnostics']['tab_resolution'] == 'browser_error_page'
    assert candidate_execution(serialized)['access_status'] == 'browser_error_page'
