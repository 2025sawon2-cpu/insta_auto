"""One exact observed SKU search in the already used collector tab."""
import json
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
    root = Path('data/daily-rework-20261011/DeRFXHpEwck/yandex-sku')
    root.mkdir(exist_ok=True)
    previous = json.loads((root.parent / 'youtube-dWjQvAq0Cck/visible-metadata.json').read_text('utf-8'))
    settings = replace(load_settings(), source_browser_captcha_wait=0)
    searcher = BrowserSearcher(settings, root)
    searcher.progress = lambda message: print(message, flush=True)
    with browser_lease(settings), sync_playwright() as pw:
        context = attach_browser(pw, settings)
        pages = [p for p in context.pages if urlparse(p.url).hostname == 'www.youtube.com']
        if len(pages) != 1:
            raise RuntimeError('Expected exact previously used tab; no new tab.')
        page = pages[0]
        audit = {'provider': 'yandex-images', 'query': '다이소 1064379 영상', 'time': time.time()}
        if searcher._cooling_down('yandex-images'):
            raise RuntimeError('Yandex access paused.')
        pace(settings, 'yandex-images', searcher.progress)
        response = page.goto(previous['return_url'], wait_until='domcontentloaded', timeout=45000)
        if searcher._check_block(page, 'yandex-images', audit, response):
            raise RuntimeError('Yandex verification required; no search.')
        control = page.locator('input[name="text"]:visible')
        control.wait_for(state='visible', timeout=15000)
        pace(settings, 'yandex-images', searcher.progress)
        control.fill(audit['query'])
        audit['submitted_at'] = time.time()
        control.press('Enter')
        page.wait_for_url(lambda u: '1064379' in str(u), timeout=30000)
        blocked = searcher._check_block(page, 'yandex-images', audit)
        page.locator('.serp-list').wait_for(state='visible', timeout=30000)
        body = page.locator('body').inner_text()
        links = page.locator('a[href]').evaluate_all('els=>els.map(e=>({url:e.href,text:e.innerText})).filter(e=>e.text.trim())')
        value = {'url': page.url, 'body': body, 'links': links, 'audit': audit, 'blocked': blocked,
                 'time': time.time(), 'downloaded': 0, 'session': 'same existing collector tab'}
        _atomic_json(root / 'visible-results.json', value)
        page.screenshot(path=str(root / 'page.png'), full_page=False)
        print(json.dumps({'url': page.url, 'body': body, 'blocked': blocked,
                          'links': [r for r in links if any(s in r['url'] for s in ('youtube.com', 'tiktok.com', 'instagram.com', 'naver.com', 'daisomall.co.kr'))]}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
