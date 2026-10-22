from types import SimpleNamespace

import pytest

from hotpost.source_queries import platform_queries, tiktok_product_queries
from hotpost.source_planning import enrich_plan
from hotpost.config import Settings
from hotpost.search_access import challenge_on_page, empty_results_on_page, search_restriction_on_page
from hotpost.platform_verification import TikTokSearchVerification
from hotpost.source_outcomes import platform_outcomes
from hotpost import browser_search as bs


NOTICE = ('결과를 찾을 수 없음 이 문구는 증오 행동과 관련될 수 있습니다. '
          'TikTok은 커뮤니티를 안전하게 유지하기 위해 최선을 다하며 증오 확산을 방지하도록 '
          '노력합니다. 자세한 내용은 커뮤니티 가이드라인을 읽어보시기 바랍니다.')


def page(body=NOTICE, url='https://www.tiktok.com/search?q=국자'):
    return SimpleNamespace(url=url, locator=lambda _: SimpleNamespace(inner_text=lambda: body),
                           wait_for_timeout=lambda _: pytest.fail('Known restriction must not wait'))


def test_product_modifiers_survive_but_scene_and_collection_instructions_do_not():
    queries = ['국자로 냄비 바닥 긁기 원본 영상 자막 없는',
               'scraping pot bottom with ladle raw footage no captions',
               '실리콘 국자 원본 영상 자막 없는', '빨간 패딩', '은색 거울',
               'silver mirror', 'silicone ladle raw footage no captions', '硅胶汤勺 实拍 无字幕']
    assert platform_queries(queries, 'tiktok', 20) == [
        'silver mirror', '실리콘 국자', '硅胶汤勺', 'silicone ladle', '빨간 패딩', '은색 거울']
    assert platform_queries([queries[0]], 'youtube', 3) == [queries[0]]


def test_product_pool_keeps_grounded_appearance_and_sku_without_action_suffixes():
    plan = {'products': [], 'query_details': [
        {'query': '국자로 냄비 바닥 긁기', 'intent': 'action'},
        {'query': '실리콘 국자', 'intent': 'subject'},
        {'query': 'DAISO SKU 1064379', 'intent': 'model'}]}
    assert tiktok_product_queries(plan) == ['실리콘 국자', 'DAISO SKU 1064379']
    assert tiktok_product_queries({}, ['국자로 냄비 바닥 긁기']) == []


def test_tool_names_are_not_confused_with_action_instructions():
    assert platform_queries(['ice cream scoop', 'pot scraper', 'frying pan'], 'tiktok', 3) == [
        'ice cream scoop', 'pot scraper', 'frying pan']
    assert platform_queries(['전기 온열기', '접이식 거울'], 'tiktok', 3) == ['전기 온열기', '접이식 거울']


def test_separate_tiktok_generation_requires_literal_evidence():
    response = {'queries': [], 'tiktok_queries': [
        {'query': '국자', 'language': 'ko', 'source': 'caption', 'quote': '국자'},
        {'query': '금속 국자', 'language': 'ko', 'source': 'caption', 'quote': '금속 국자'},
        {'query': '국자로 냄비 바닥 긁기', 'language': 'ko', 'source': 'caption', 'quote': '국자'}]}
    prompts = []
    def generate(settings, instruction, evidence):
        prompts.append(instruction)
        return response
    plan = enrich_plan(Settings(), {'query_details': []}, '국자', {}, generate)
    assert tiktok_product_queries(plan) == ['국자']
    assert 'tiktok_queries' in prompts[0] and 'noun phrases' in prompts[0]


def test_supplied_restriction_screen_is_not_captcha_or_parser_failure(tmp_path, monkeypatch):
    current = page()
    assert not challenge_on_page(current)
    assert empty_results_on_page(current) and search_restriction_on_page(current)
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    audit = {}
    assert searcher._wait_platform_results(current, 'tiktok', '국자', audit, []) == []
    assert audit['status'] == 'query_restricted'
    assert not (tmp_path / 'search_cooldowns/tiktok.json').exists()
    assert not (tmp_path / 'search_readiness/tiktok.json').exists()
    assert TikTokSearchVerification('국자').observe(current)['status'] == 'query_restricted'
    outcome = platform_outcomes([], [{'provider': 'tiktok', 'query': '국자', 'status': audit['status']}])['tiktok']
    assert outcome['reasons'] == {'query_restricted': 1}


def test_real_challenge_has_priority_over_restriction_notice(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    audit = {}
    assert searcher._wait_platform_results(page(NOTICE + ' 슬라이더를 드래그하여 퍼즐을 맞추세요'),
                                           'tiktok', '국자', audit, []) is None
    assert audit['status'] == 'captcha_review_pending'


def test_search_query_containing_captcha_path_is_not_a_challenge_url():
    assert not challenge_on_page(page('검색 결과가 없습니다', 'https://www.tiktok.com/search?q=/captcha'))


def test_browser_route_uses_tiktok_pool_without_changing_other_providers(tmp_path, monkeypatch):
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    searcher.provider_queries = {'tiktok': ['실리콘 국자']}
    calls = []
    monkeypatch.setattr(searcher, '_platforms', lambda c, q, limit, providers: calls.append((providers, q)))
    searcher._run_route(None, 'tiktok', [], ['국자로 냄비 바닥 긁기'], 5)
    searcher._run_route(None, 'douyin', [], ['국자로 냄비 바닥 긁기'], 5)
    assert calls == [({'tiktok'}, ['실리콘 국자']), ({'douyin'}, ['국자로 냄비 바닥 긁기'])]


def test_restricted_query_is_not_retried_and_next_product_query_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    current = page()
    current.wait_for_timeout = lambda _: None
    current.mouse = SimpleNamespace(wheel=lambda *a: None)
    monkeypatch.setattr(searcher, '_page', lambda *a: current)
    submitted = []
    monkeypatch.setattr(searcher, '_submit_search', lambda p, provider, query, audit: submitted.append(query) or True)
    monkeypatch.setattr(searcher, '_retry_pause', lambda *a: pytest.fail('Must not retry restricted query'))
    searcher._platforms(None, ['실리콘 국자', '국자'], 10, providers={'tiktok'})
    assert submitted == ['실리콘 국자', '국자']
    assert [r['status'] for r in searcher.searches] == ['query_restricted', 'query_restricted']
    assert not (tmp_path / 'search_cooldowns/tiktok.json').exists()
    assert not (tmp_path / 'search_readiness/tiktok.json').exists()


def test_worker_payload_retains_product_pool_across_process_boundary(tmp_path, monkeypatch):
    from hotpost import source_browser_worker as worker
    captured = []
    monkeypatch.setattr(worker, 'run_bounded', lambda command, payload, *args:
                        captured.append(payload) or {'searches': []})
    worker.isolated_search(Settings(data_dir=tmp_path, source_browser_search=False), [],
                           ['국자로 냄비 바닥 긁기'], 3, tmp_path,
                           provider_queries={'tiktok': ['실리콘 국자']})
    assert captured[0]['provider_queries'] == {'tiktok': ['실리콘 국자']}
