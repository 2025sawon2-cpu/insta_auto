from types import SimpleNamespace

import pytest

from hotpost import browser_search as bs
from hotpost.config import Settings


FOOTER = {'href': 'https://www.bilibili.com/video/BV1Xx411c7cH/', 'text': '高级弹幕'}
CARD_THUMB = {'href': 'https://www.bilibili.com/video/BV1nrAUz8Eaw/',
              'text': '1030 27 01:02', 'duration': '01:02'}
CARD_TITLE = {'href': CARD_THUMB['href'], 'title': '双层网纱科目文件袋'}
HIDDEN_CARD = {'href': 'https://www.bilibili.com/video/BV1Ux411u7Vm/',
               'title': 'Hidden stale responsive card', 'card_visible': False}


def test_bilibili_cards_exclude_footer_and_merge_duration_with_title():
    selectors = []
    def locator(selector):
        selectors.append(selector)
        rows = [CARD_THUMB, CARD_TITLE, HIDDEN_CARD] if '.bili-video-card' in selector else [FOOTER, CARD_THUMB, CARD_TITLE, HIDDEN_CARD]
        return SimpleNamespace(evaluate_all=lambda _: rows)
    page = SimpleNamespace(url='https://search.bilibili.com/all?keyword=A7', locator=locator)
    rows = bs._anchors(page, 'playwright-bilibili', 'A7', 'platform-search')
    assert selectors == ['.bili-video-card a[href], .video-item a[href]']
    assert len(rows) == 1 and rows[0]['url'] == CARD_THUMB['href']
    assert rows[0]['title'] == CARD_TITLE['title']
    assert rows[0]['discovery_meta']['duration'] == 62


def test_footer_hydration_ids_do_not_count_as_bilibili_search_results():
    page = SimpleNamespace(content=lambda: '<footer><a href="/video/BV1Xx411c7cH">高级弹幕</a></footer>')
    assert bs._embedded_candidates(page, 'bilibili', 'A7') == []


def test_bilibili_result_wait_continues_past_footer_until_cards_hydrate(tmp_path, monkeypatch):
    calls = []
    hydrated = [False]
    def locator(selector):
        calls.append(selector)
        rows = [CARD_TITLE] if hydrated[0] else []
        if selector == 'a[href]': rows = [FOOTER, *rows]
        return SimpleNamespace(evaluate_all=lambda _: rows)
    def wait(milliseconds):
        assert milliseconds == 1000
        hydrated[0] = True
    page = SimpleNamespace(url='https://search.bilibili.com/all?keyword=A7', locator=locator,
                           wait_for_timeout=wait, content=lambda: '<a href="/video/BV1Xx411c7cH">高级弹幕</a>')
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path, source_browser_result_timeout=3), tmp_path / 'debug')
    monkeypatch.setattr(searcher, '_check_block', lambda *a: False)
    monkeypatch.setattr(bs, 'empty_results_on_page', lambda _: False)
    audit = {}
    result = searcher._wait_platform_results(page, 'bilibili', 'A7', audit, [])
    assert hydrated[0] and len(result) == 1 and result[0]['url'] == CARD_TITLE['href']
    assert audit['result_method'] == 'search_card_links'
    assert 'a[href]' not in calls


def test_other_search_providers_keep_document_links():
    selected = []
    page = SimpleNamespace(url='https://yandex.com/images/search',
        locator=lambda selector: (selected.append(selector) or SimpleNamespace(evaluate_all=lambda _: [CARD_TITLE])))
    assert bs._anchors(page, 'yandex-images', 'A7', 'visual-match')[0]['url'] == CARD_TITLE['href']
    assert selected == ['a[href]']


@pytest.mark.parametrize('initial_url', ['https://www.bilibili.com/video/BV1jwieB2Esb/',
                                        'https://www.bilibili.com/',
                                        'https://search.bilibili.com/'])
def test_header_search_reuses_tab_instead_of_waiting_for_popup(tmp_path, monkeypatch, initial_url):
    from urllib.parse import urlencode
    events = []
    class Field:
        def wait_for(self, **kw): pass
        def count(self): return 1
        def input_value(self): return self.query
        def press_sequentially(self, query, **kw): self.query = query
        def press(self, key):
            events.append(key)
            if key == 'Enter':
                assert page.url == 'https://search.bilibili.com/'
                page.url = 'https://search.bilibili.com/all?' + urlencode({'keyword': self.query})
    field = Field()
    field.first = field
    def goto(url, **kw):
        events.append(('goto', url))
        page.url = url
    page = SimpleNamespace(url=initial_url,
        locator=lambda _: field, goto=goto, wait_for_timeout=lambda _: None,
        wait_for_url=lambda predicate, **kw: predicate(page.url) or (_ for _ in ()).throw(AssertionError(page.url)))
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path / 'debug')
    monkeypatch.setattr(searcher, '_check_block', lambda *args: False)
    monkeypatch.setattr(searcher, '_pace', lambda *args, **kw: None)
    audit = {'provider': 'bilibili'}
    assert searcher._submit_search(page, 'bilibili', 'A7 魔术贴 收纳袋', audit)
    if initial_url.startswith('https://www.bilibili.com/'):
        assert events[0] == ('goto', 'https://search.bilibili.com/')
        assert [r['operation'] for r in audit['requests']] == ['search_home', 'search_input']
    else:
        assert not any(isinstance(e,tuple) and e[0]=='goto' for e in events)
        assert [r['operation'] for r in audit['requests']] == ['search_input']
    assert events.count('Enter') == 1
    assert audit['execution']['query_url_matched']


@pytest.mark.parametrize('initial_url',['https://www.bilibili.com/video/BV1jwieB2Esb/',
                                      'https://www.bilibili.com/'])
def test_header_authentication_is_not_hidden_by_search_home_navigation(tmp_path, monkeypatch,initial_url):
    page = SimpleNamespace(url=initial_url,
                           goto=lambda *a, **kw: (_ for _ in ()).throw(AssertionError('navigation must stop')))
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path / 'debug')
    monkeypatch.setattr(searcher, '_check_block', lambda *args: True)
    assert searcher._submit_search(page, 'bilibili', 'A7', {}) is False
