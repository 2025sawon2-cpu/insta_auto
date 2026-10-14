"""Offline browser regression: authenticate the current user, not ig_user."""
import pytest
from playwright.sync_api import sync_playwright
from hotpost.config import Settings
from hotpost.instagram_browser import InstagramBrowser
from hotpost.collectors.base import CollectionBlocked


@pytest.fixture(scope="module")
def chrome():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        yield browser
        browser.close()


@pytest.mark.parametrize("configured,session,markup,expected", [
    ("old_account", True, '<nav><a href="https://www.instagram.com/current_user/"><img alt="current_user님의 프로필 사진" width="30" height="30"></a></nav>', "current_user"),
    ("", True, '<nav><a href="https://www.instagram.com/current_user/"><img alt="current_user&#39;s profile picture" width="30" height="30"></a></nav>', "current_user"),
    ("", False, '<nav><a href="https://www.instagram.com/current_user/"><img alt="current_user님의 프로필 사진" width="30" height="30"></a></nav>', ""),
    ("", True, '<main><a href="https://www.instagram.com/viewed_profile/"><img alt="viewed_profile님의 프로필 사진" width="30" height="30"></a></main>', ""),
    ("", True, '<nav><a href="https://example.com/current_user/"><img alt="current_user님의 프로필 사진" width="30" height="30"></a></nav>', ""),
])
def test_current_account_detection(chrome, monkeypatch, configured, session, markup, expected):
    with chrome.new_context() as context:
        if session:
            context.add_cookies([{"name":"sessionid", "value":"offline-test", "domain":".instagram.com", "path":"/"}])
        page = context.new_page()
        page.set_content(markup)
        monkeypatch.setattr(page, "wait_for_timeout", lambda _: None)
        client = InstagramBrowser(Settings(ig_user=configured))
        client.context, client.page = context, page
        if expected:
            assert client.verify_identity() == expected
        else:
            with pytest.raises(CollectionBlocked) as error:
                client.verify_identity()
            assert error.value.reason == "login_required"


def test_challenge_still_blocks(chrome):
    with chrome.new_context() as context:
        page = context.new_page()
        page.set_content("<body>본인 확인</body>")
        client = InstagramBrowser(Settings())
        client.context, client.page = context, page
        with pytest.raises(CollectionBlocked) as error:
            client.verify_identity()
        assert error.value.reason == "verification_required"
