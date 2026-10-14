"""Observed search pagination is independent from query wording and task IDs."""
from hotpost.source_search.strategy import fresh_queries, merge_history, restore_history
from hotpost.source_finder import Candidate, _dedupe
from hotpost.source_urls import canonical_video_key


def test_completed_first_page_does_not_consume_an_observed_second_page():
    history = merge_history([{'provider': 'youtube', 'query': 'silver mirror',
                             'status': 'no_results', 'page': 1}])
    assert fresh_queries(['silver mirror'], 'youtube', history) == []
    assert fresh_queries(['silver mirror'], 'youtube', history, scope={'page': 2}) == ['silver mirror']
    history = merge_history(history, [{'provider': 'youtube', 'query': 'silver mirror',
                                      'status': 'results', 'page': 2, 'candidates': 3}])
    assert len(history) == 2
    assert fresh_queries(['silver mirror'], 'youtube', history, scope={'page': '2'}) == []


def test_equivalent_failed_queries_only_consume_their_actual_cursor():
    history = [{'provider': 'bing', 'query': 'garlic storage preparation',
                'cursor': 'AbC', 'status': 'no_results'}]
    assert not fresh_queries(['garlic storage tips'], 'bing', history, scope={'cursor': 'AbC'})
    assert fresh_queries(['garlic storage tips'], 'bing', history, scope={'cursor': 'abc'})
    assert fresh_queries(['garlic storage tips'], 'bing', history, scope={'cursor': 'NextToken'})


def test_new_job_metadata_never_reopens_an_identical_failed_search():
    history = merge_history([{'provider': 'tiktok', 'query': '빨간 패딩',
                             'status': 'query_restricted', 'job_id': 'old', 'date': 'yesterday'}])
    assert not fresh_queries([' 빨간  패딩 '], 'tiktok', history,
                             scope={'job_id': 'new', 'policy': 'new-code', 'date': 'today'})


def test_scope_history_survives_manifest_migration_and_restart(tmp_path):
    import json
    manifest = tmp_path / 'manifest.json'
    rows = [{'provider': 'youtube', 'query': 'knit polo', 'status': 'no_results', 'page_number': 2},
            {'provider': 'youtube', 'query': 'knit polo', 'status': 'no_results',
             'search_scope': {'continuation_token': 'NEXT', 'offset': 20}}]
    manifest.write_text(json.dumps({'search_audit': rows}), encoding='utf-8')
    record = {'queries': [], 'rounds': [{'manifest_path': str(manifest)}]}
    history = restore_history(record)
    assert len(history) == 2
    manifest.unlink()
    history = restore_history(record)
    assert not fresh_queries(['knit polo'], 'youtube', history, scope={'page': 2})
    assert not fresh_queries(['knit polo'], 'youtube', history,
                             scope={'cursor': 'NEXT', 'offset': '20'})
    assert fresh_queries(['knit polo'], 'youtube', history)


def test_login_and_cooldown_skips_do_not_consume_requested_page():
    history = [{'provider': 'youtube', 'query': 'knit polo', 'page': 2,
                'status': status} for status in ('login_required', 'cooldown', 'not_attempted')]
    assert fresh_queries(['knit polo'], 'youtube', merge_history(history), scope={'page': 2})


def test_actual_access_wait_request_does_not_erase_a_prior_failed_scope():
    wait = {'provider': 'youtube', 'query': 'knit polo', 'page': 2,
            'status': 'rate_limited', 'requests': [{'operation': 'navigate'}]}
    assert fresh_queries(['knit polo'], 'youtube', [wait], scope={'page': 2})
    failed = {**wait, 'status': 'no_results'}
    history = merge_history([failed], [wait])
    assert history[0]['status'] == 'no_results'
    assert not fresh_queries(['knit polo'], 'youtube', history, scope={'page': 2})


def test_same_video_across_search_queries_and_url_forms_is_one_candidate():
    rows = [Candidate('https://youtu.be/abcdefghijk', 'first-query'),
            Candidate('https://www.youtube.com/watch?v=abcdefghijk&feature=share', 'second-query'),
            Candidate('https://www.youtube.com/shorts/abcdefghijk', 'third-query'),
            Candidate('https://www.youtube.com/watch?v=lmnopqrstuv', 'second-query')]
    unique = _dedupe(rows)
    assert len(unique) == 2
    # This is the same gate used before downloading and for refinement rounds.
    tried = {canonical_video_key('https://youtube.com/shorts/abcdefghijk')}
    assert [c.url for c in unique if canonical_video_key(c.url) not in tried] == [rows[-1].url]
