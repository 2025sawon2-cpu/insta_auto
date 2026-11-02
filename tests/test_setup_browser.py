"""Settings UI against an isolated publication server; no service login or publishing."""
from contextlib import contextmanager
import os
from pathlib import Path
import threading

import pytest

from hotpost.config import Settings
from hotpost.installation_settings import read, save
from hotpost.publication_server import PublicationServer, make_publication_handler


@contextmanager
def settings_page(tmp_path, width=1280):
    pw = pytest.importorskip('playwright.sync_api')
    settings = Settings(data_dir=tmp_path/'data', influencer_file=tmp_path/'accounts.txt',
                        web_dir=Path(__file__).resolve().parents[1]/'web')
    save(settings.data_dir, {'revision': 0, 'values': {
        'publication_accounts': ['first.brand', 'second.brand'], 'discovery_account': 'reader',
        'storefront_url': 'https://influencers.coupang.com/s/test', 'collection': 'Test',
        'littly_logins': {'first.brand': {'provider': 'google', 'account_hint': 'first@example.test'},
                          'second.brand': {'provider': 'chrome', 'account_hint': 'second@example.test'}}}})
    server = PublicationServer(('127.0.0.1', 0), make_publication_handler(settings))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page(viewport={'width': width, 'height': 950}, color_scheme='light')
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}/settings.html')
            pw.expect(page.locator('#account-count')).to_have_text('2개')
            yield page, settings, pw.expect
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def capture(page, name):
    folder = os.environ.get('HOTPOST_UI_REVIEW_DIR')
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(Path(folder)/name), full_page=True)


def test_settings_register_delete_and_chrome_route_persist_through_real_api(tmp_path):
    with settings_page(tmp_path) as (page, settings, expect):
        expect(page.locator('[data-account="first.brand"] select')).to_have_value('google')
        page.locator('#publication-account').fill('@NEW.brand')
        page.locator('#publication-account').press('Enter')
        row = page.locator('[data-account="new.brand"]')
        expect(row.locator('select')).to_have_value('chrome')
        row.locator('input').fill('saved@example.test')
        page.get_by_role('button', name='연결 정보 저장', exact=True).click()
        expect(page.locator('#setup-save-status')).to_contain_text('저장 완료')
        stored = read(settings.data_dir)['values']
        assert stored['publication_accounts'] == ['first.brand', 'second.brand', 'new.brand']
        assert stored['littly_logins']['new.brand'] == {
            'provider': 'chrome', 'account_hint': 'saved@example.test'}
        page.reload()
        expect(page.locator('#account-count')).to_have_text('3개')
        expect(row.locator('input')).to_have_value('saved@example.test')
        capture(page, 'settings-desktop.png')
        page.get_by_role('button', name='@second.brand 등록 삭제', exact=True).click()
        expect(page.locator('#setup-done')).to_be_hidden()
        page.get_by_role('button', name='연결 정보 저장', exact=True).click()
        expect(page.locator('#setup-save-status')).to_contain_text('저장 완료')
        stored = read(settings.data_dir)['values']
        assert stored['publication_accounts'] == ['first.brand', 'new.brand']
        assert 'second.brand' not in stored['littly_logins']
        assert stored['littly_logins']['first.brand']['provider'] == 'google'


def test_settings_mobile_handles_duplicate_and_pending_input_without_overflow(tmp_path):
    with settings_page(tmp_path, width=390) as (page, settings, expect):
        page.locator('#publication-account').fill('@FIRST.brand')
        page.get_by_role('button', name='등록', exact=True).click()
        expect(page.locator('#account-add-status')).to_contain_text('이미 등록')
        page.locator('#publication-account').fill('pending')
        page.get_by_role('button', name='연결 정보 저장', exact=True).click()
        expect(page.locator('#account-add-status')).to_contain_text('등록 버튼을 먼저')
        assert read(settings.data_dir)['revision'] == 1
        page.locator('#publication-account').fill('')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        assert page.get_by_role('button', name='등록', exact=True).bounding_box()['height'] >= 44
        capture(page, 'settings-mobile.png')
