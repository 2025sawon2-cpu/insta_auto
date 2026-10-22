"""Observe one user-requested search; never solve or retry authentication."""
from urllib.parse import parse_qs, quote_plus, urlparse

from .search_access import challenge_on_page, empty_results_on_page, login_wall_on_page, search_restriction_on_page
from .source_search.tiktok_results import search_response_candidates
from .source_queries import within_query_word_limit


class TikTokSearchVerification:
    def __init__(self, query,settings=None):
        if not within_query_word_limit(query):
            raise ValueError('검색어는 띄어쓰기 기준 1~10단어로 입력하세요.')
        self.query = ' '.join(query.split())
        self.url = 'https://www.tiktok.com/search/video?q=' + quote_plus(self.query)
        self.candidates = {}
        self.settings=settings

    def attach(self, page):
        def receive(response):
            parsed = urlparse(response.url)
            if parsed.hostname not in {'www.tiktok.com', 'tiktok.com'} or parsed.path not in {
                    '/api/search/item/full/', '/api/search/general/full/'}:
                return
            try:
                for item in search_response_candidates(response.url, response.json(), self.query):
                    self.candidates[item['url']] = item
            except Exception:
                pass
        page.on('response', receive)

    def observe(self, page):
        parsed = urlparse(page.url)
        if parsed.hostname not in {'www.tiktok.com', 'tiktok.com'}:
            return {'status': 'loading', 'candidates': 0}
        if challenge_on_page(page):
            from .captcha_review import review_page
            if self.settings is None:
                from .config import load_settings
                self.settings=load_settings()
            review=review_page(self.settings,'tiktok',page,query=self.query)
            if review['status']!='clear':
                return {'status':review['status'],'candidates':0,'captcha_review':review}
        if login_wall_on_page(page, 'tiktok'):
            return {'status': 'login_required', 'candidates': 0}
        if (parsed.path.rstrip('/') not in {'/search', '/search/video'} or
                parse_qs(parsed.query).get('q', [''])[0] != self.query):
            return {'status': 'page_changed', 'candidates': 0}
        if search_restriction_on_page(page):
            return {'status': 'query_restricted', 'candidates': 0}
        if self.candidates:
            return {'status': 'results', 'candidates': len(self.candidates)}
        if empty_results_on_page(page):
            return {'status': 'no_results', 'candidates': 0}
        return {'status': 'loading', 'candidates': 0}

    @staticmethod
    def message(result):
        status = result['status']
        if status == 'captcha':
            return '검색 화면에 인증이 필요합니다. Chrome에서 직접 완료한 뒤 세션 저장 완료를 누르세요.'
        if status == 'captcha_review_pending':
            return '인증 의심 화면의 캡처·재검토 대기 중입니다. CAPTCHA로 확정되지 않았습니다.'
        if status == 'login_required':
            return '검색 화면에서 로그인한 뒤 세션 저장 완료를 누르세요.'
        if status == 'results':
            return f"검색 결과 {result['candidates']}개 확인 · 확인을 마치면 세션 저장 완료를 누르세요."
        if status == 'no_results':
            return '검색은 정상 응답했지만 결과가 없습니다. 확인을 마치면 세션 저장 완료를 누르세요.'
        if status == 'query_restricted':
            return '검색어 제한 안내가 표시되어 결과가 없습니다. CAPTCHA가 아니며 다른 제품 검색어가 필요합니다.'
        if status == 'page_changed':
            return '검색 확인 화면으로 돌아온 뒤 세션 저장 완료를 누르세요.'
        return '검색 화면 로딩을 기다리는 중 · 창을 유지합니다.'
