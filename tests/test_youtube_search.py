"""No new sessions, stale search cards, or alternate HTTP search on failure."""
from types import SimpleNamespace
import pytest
from hotpost.browser_search import BrowserSearcher
from hotpost.config import Settings
from hotpost.youtube_search import response_video_ids

OLD = 'oldvideo001'
NEW = 'newvideo001'


class Locator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector
    def wait_for(self, **kwargs):
        pass
    def fill(self, query):
        self.page.query = query
    def input_value(self):
        return self.page.query
    def press(self, key, **kwargs):
        self.page.presses += 1
        if self.page.fail:
            raise TimeoutError('search failed')
        self.page.url = 'https://www.youtube.com/results?search_query=cart'
    def is_visible(self):
        return self.page.empty_visible
    def evaluate_all(self, js):
        assert self.page.finished, 'Old SPA cards must not be read before the new response finishes'
        self.page.reads += 1
        return [{'url':f'https://www.youtube.com/shorts/{i}', 'text':i} for i in self.page.cards]


class Page:
    url = 'https://www.youtube.com/shorts/oldvideo001'
    def __init__(self, *, fail=False, status=200, ids=(NEW,), cards=(OLD, NEW), empty_visible=False):
        self.fail, self.ids, self.cards, self.empty_visible = fail, ids, cards, empty_visible
        self.presses, self.reads, self.finished = 0, 0, False
        self.response = SimpleNamespace(url='https://www.youtube.com/youtubei/v1/search', status=status,
            request=SimpleNamespace(post_data_json={'query':'cart'}), finished=self.finish,
            json=lambda:{'contents':{'items':[{'videoId':i} for i in self.ids]}})
    def finish(self):
        self.finished = True
    def is_closed(self):
        return False
    def locator(self, selector):
        return Locator(self, selector)
    def expect_response(self, predicate, **kwargs):
        assert predicate(self.response)
        assert not predicate(SimpleNamespace(url='https://www.youtube.com/youtubei/v1/search',
            status=200, request=SimpleNamespace(post_data_json={'query':'another query'})))
        assert not predicate(SimpleNamespace(url='https://evil.example/youtubei/v1/search'))
        return Pending(self.response)
    def wait_for_url(self, predicate, **kwargs):
        assert predicate(self.url)
    def wait_for_timeout(self, milliseconds):
        pass
    def screenshot(self, **kwargs):
        pass


class Pending:
    def __init__(self, response):
        self.value = response
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


def searcher(tmp_path, monkeypatch):
    worker = BrowserSearcher(Settings(data_dir=tmp_path, source_queries_per_platform=1,
        source_browser_result_timeout=1), tmp_path / 'debug')
    monkeypatch.setattr(worker, '_cooling_down', lambda *_,**kwargs:False)
    monkeypatch.setattr(worker, '_pace', lambda *_args, **_kwargs:None)
    def block(page, provider, audit, response=None):
        if response is not None and response.status == 429:
            audit['status'] = 'rate_limited'
            return True
        return False
    monkeypatch.setattr(worker, '_check_block', block)
    return worker


def test_contents_scope_excludes_page_recommendations():
    assert response_video_ids({'contents':{'x':[{'videoId':NEW}]}, 'recommendations':{'videoId':OLD}}) == {NEW}


def test_new_response_required_and_stale_card_excluded(tmp_path, monkeypatch):
    worker = searcher(tmp_path, monkeypatch)
    page = Page()
    worker._youtube(SimpleNamespace(pages=[page]), ['cart'], 5)
    assert [c['url'] for c in worker.candidates] == [f'https://www.youtube.com/shorts/{NEW}']
    assert page.presses == 1 and page.finished and page.reads == 1
    assert worker.searches[0]['status'] == 'results'
    assert worker.searches[0]['requests'][0]['operation'] == 'visible_search_input_enter'


@pytest.mark.parametrize('started_at,accepted', [(9999999999, True), (0, False)])
def test_missing_cdp_body_requires_request_after_our_enter(tmp_path, monkeypatch, started_at, accepted):
    worker = searcher(tmp_path, monkeypatch)
    page = Page()
    page.response.request = SimpleNamespace(post_data_json=None, timing={'startTime':started_at * 1000})
    def pending(predicate, **kwargs):
        assert predicate(page.response) is accepted
        if not accepted:
            raise TimeoutError('Old request cannot be used')
        return Pending(page.response)
    page.expect_response = pending
    worker._youtube(SimpleNamespace(pages=[page]), ['cart'], 5)
    assert bool(worker.candidates) is accepted


@pytest.mark.parametrize('page_kwargs,status', [({'fail':True}, 'error'), ({'status':429}, 'rate_limited'),
                                               ({'status':500}, 'http_error')])
def test_failed_search_does_not_read_old_cards_or_retry(tmp_path, monkeypatch, page_kwargs, status):
    worker = searcher(tmp_path, monkeypatch)
    page = Page(**page_kwargs)
    worker._youtube(SimpleNamespace(pages=[page]), ['cart'], 5)
    assert worker.candidates == [] and page.presses == 1 and page.reads == 0
    assert worker.searches[0]['status'] == status


@pytest.mark.parametrize('count,reason', [(0, 'existing_youtube_tab_missing'), (2, 'existing_youtube_tab_ambiguous')])
def test_missing_or_ambiguous_tab_never_opens_new_page(tmp_path, monkeypatch, count, reason):
    worker = searcher(tmp_path, monkeypatch)
    context = SimpleNamespace(pages=[Page() for _ in range(count)])
    worker._youtube(context, ['cart'], 5)
    assert worker.searches[0]['status'] == 'not_attempted' and worker.searches[0]['reason'] == reason
    assert worker.candidates == []


@pytest.mark.parametrize('visible,status', [(False, 'page_unresolved'), (True, 'no_results')])
def test_empty_response_alone_does_not_prove_empty_results(tmp_path, monkeypatch, visible, status):
    worker = searcher(tmp_path, monkeypatch)
    page = Page(ids=(), cards=(OLD,), empty_visible=visible)
    worker._youtube(SimpleNamespace(pages=[page]), ['cart'], 5)
    assert not worker.candidates and worker.searches[0]['status'] == status
