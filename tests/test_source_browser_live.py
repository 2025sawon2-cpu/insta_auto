"""Opt-in visible Chrome integration using intercepted fixture pages only."""
import os
import sys
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.source_browser_runtime import ensure_browser, attach_browser, managed_page, endpoint
from hotpost.source_browser_worker import run_bounded
from hotpost.browser_search import BrowserSearcher


@pytest.mark.skipif(os.environ.get('HOTPOST_TEST_VISIBLE_CHROME') != '1', reason='Opt-in visible Chrome fixture')
def test_visible_chrome_survives_disconnect_and_worker_timeout(tmp_path):
    from playwright.sync_api import sync_playwright
    settings = Settings(data_dir=tmp_path)
    address = ensure_browser(settings)
    try:
        with sync_playwright() as pw:
            context = attach_browser(pw, settings)
            user_tab = context.new_page()
            user_tab.goto('data:text/html,<title>User-owned fixture</title>Keep this tab')
            page = managed_page(context, settings, 'tiktok')
            # No TikTok network access: all requests are intercepted in this context.
            context.route('**/*', lambda route: route.fulfill(content_type='text/html', body='''
                <title>Hotpost search fixture</title>
                <form action="/search"><input name="q" placeholder="Search"><button>Search</button></form>
                <p>No results found</p>'''))
            searcher = BrowserSearcher(settings, tmp_path)
            assert searcher._submit_search(page, 'tiktok', 'visible fixture', {})
            assert 'q=visible+fixture' in page.url
            assert not user_tab.is_closed()
            expected_url = page.url
        assert endpoint(settings) == address
        with sync_playwright() as pw:
            context = attach_browser(pw, settings)
            assert managed_page(context, settings, 'tiktok').url == expected_url
            assert len([p for p in context.pages if p.url == expected_url]) == 1
            assert any('User-owned' in p.title() for p in context.pages)
        script = """
import json,sys,time
from pathlib import Path
from playwright.sync_api import sync_playwright
from hotpost.config import Settings
from hotpost.source_browser_runtime import attach_browser
p=json.load(sys.stdin)
with sync_playwright() as pw:
    context=attach_browser(pw, Settings(data_dir=Path(p['data_dir'])))
    Path(p['checkpoint']).write_text(json.dumps({'candidates':[{'url':'fixture'}]}))
    time.sleep(60)
"""
        checkpoint = tmp_path / 'worker.json'
        result = run_bounded([sys.executable, '-c', script],
            {'data_dir': str(tmp_path), 'checkpoint': str(checkpoint)}, checkpoint, 5)
        assert result['candidates'] == [{'url': 'fixture'}]
        assert result['searches'][-1]['status'] == 'timeout'
        assert endpoint(settings) == address
    finally:
        # Only this temporary fixture browser is explicitly closed by the test.
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(address)
            browser.new_browser_cdp_session().send('Browser.close')
