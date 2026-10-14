"""One exact product search using the existing collector YouTube page."""
import json
import argparse
import hashlib
import re
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from hotpost.browser_search import BrowserSearcher
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json
from hotpost.source_browser_runtime import attach_browser, browser_lease, pace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--query', default='다이소 A7 파스텔 파일 홀더')
    parser.add_argument('--code', default='DeRFXHpEwck')
    args = parser.parse_args()
    settings = replace(load_settings(), source_browser_captcha_wait=0)
    query = args.query
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.code):
        raise ValueError('A valid existing product code is required.')
    root = Path('data/daily-rework-20261011') / args.code / 'youtube-exact-product' / hashlib.sha256(query.encode()).hexdigest()[:12]
    root.mkdir(parents=True, exist_ok=True)
    searcher = BrowserSearcher(settings, root)
    searcher.progress = lambda message: print(message, flush=True)
    with browser_lease(settings), sync_playwright() as pw:
        context = attach_browser(pw, settings)
        pages = [p for p in context.pages if urlparse(p.url).hostname == 'www.youtube.com']
        if len(pages) != 1:
            raise RuntimeError('Expected one existing YouTube page; no new page.')
        page = pages[0]
        audit = {'provider': 'youtube', 'query': query, 'time': time.time(), 'requests': []}
        if searcher._cooling_down('youtube') or searcher._check_block(page, 'youtube', audit):
            raise RuntimeError('YouTube access paused; no search.')
        page.locator('input[name="search_query"]:visible').wait_for(state='visible', timeout=30000)
        print(json.dumps({'before': page.url, 'input': page.locator('input[name="search_query"]:visible').get_attribute('name')}, ensure_ascii=False), flush=True)
        pace(settings, 'youtube', searcher.progress)
        control = page.locator('input[name="search_query"]:visible')
        control.fill(query)
        audit['requests'].append({'operation': 'visible search input Enter', 'at': time.time()})
        # URL changes before the SPA replaces the old result cards. Observe the
        # existing browser's search response; do not issue a second request.
        with page.expect_response(lambda r: '/youtubei/v1/search' in r.url,
                                  timeout=30000) as search_response:
            control.press('Enter')
        response = search_response.value
        response.finished()
        audit['search_response_status'] = response.status
        page.wait_for_timeout(1000)
        page.wait_for_url('**/results?**', timeout=30000)
        blocked = searcher._check_block(page, 'youtube', audit)
        if not blocked:
            page.locator('ytd-video-renderer,ytd-reel-shelf-renderer,ytm-shorts-lockup-view-model').first.wait_for(state='visible', timeout=30000)
        body = page.locator('body').inner_text()
        links = page.locator('ytd-video-renderer,ytm-shorts-lockup-view-model').evaluate_all('''els=>els.filter(e=>{
            const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&r.top<innerHeight&&r.bottom>0&&getComputedStyle(e).visibility!=="hidden";
        }).map(e=>{const a=[...e.querySelectorAll('a[href]')].find(a=>a.href.includes('/watch?')||a.href.includes('/shorts/'));
            return a?{url:a.href,text:e.innerText,title:a.getAttribute('title')}:null;}).filter(Boolean)''')
        value = {'url': page.url, 'query': query, 'body': body, 'links': links,
                 'audit': audit, 'blocked': blocked, 'time': time.time(), 'downloaded': 0,
                 'candidate_scope': 'visible result cards in current viewport; no watch/quality review'}
        _atomic_json(root / 'visible-results.json', value)
        page.screenshot(path=str(root / 'page.png'), full_page=False)
        print(json.dumps({k:v for k,v in value.items() if k!='body'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
