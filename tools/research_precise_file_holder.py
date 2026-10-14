"""Inspect one observed product/result in the existing collector Chrome tab."""
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

ROOT = Path('data/daily-rework-20261011/DeRFXHpEwck')
PRODUCT = 'https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo=1064379'


def main():
    settings = replace(load_settings(), source_browser_captcha_wait=0)
    folder = ROOT / 'official-product-1064379'
    folder.mkdir(exist_ok=True)
    searcher = BrowserSearcher(settings, folder)
    searcher.progress = lambda message: print(message, flush=True)
    with browser_lease(settings), sync_playwright() as pw:
        context = attach_browser(pw, settings)
        pages = [p for p in context.pages if p.url == 'https://www.youtube.com/watch?v=dWjQvAq0Cck']
        if len(pages) != 1:
            raise RuntimeError('Expected previously inspected YouTube result in the existing tab; no new tab.')
        page = pages[0]
        return_url = page.url
        audit = {'provider': 'daisomall', 'operation': 'observed official product', 'time': time.time()}
        if searcher._cooling_down('daisomall'):
            raise RuntimeError('Provider access paused; no navigation.')
        pace(settings, 'daisomall', searcher.progress)
        response = page.goto(PRODUCT, wait_until='domcontentloaded', timeout=45000)
        blocked = searcher._check_block(page, 'daisomall', audit, response)
        body = page.locator('body').inner_text(timeout=15000)
        receipt = {'url': page.url, 'title': page.title(), 'body': body, 'audit': audit,
                   'http_status': response.status if response else None, 'blocked': blocked,
                   'return_url': return_url, 'time': time.time(),
                   'media': page.locator('video,iframe').evaluate_all(
                       'els=>els.map(e=>({tag:e.tagName,src:e.getAttribute("src")}))')}
        _atomic_json(folder / 'visible-metadata.json', receipt)
        page.screenshot(path=str(folder / 'page.png'), full_page=False)
        print(json.dumps({'url': receipt['url'], 'http_status': receipt['http_status'],
                          'blocked': blocked, 'body': body[:18000], 'media': receipt['media']}, ensure_ascii=False), flush=True)
        # Restore the exact inspected result in this same tab, leaving other tabs untouched.
        if not searcher._cooling_down('youtube'):
            pace(settings, 'youtube', searcher.progress)
            page.goto(return_url, wait_until='domcontentloaded', timeout=45000)
            print(json.dumps({'restored': page.url, 'inputs': page.locator('input').evaluate_all(
                'els=>els.map(e=>({name:e.name,placeholder:e.getAttribute("placeholder"),aria:e.getAttribute("aria-label"),visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)}))')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
