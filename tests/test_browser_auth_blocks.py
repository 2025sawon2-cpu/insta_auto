from types import SimpleNamespace

import pytest

from hotpost.browser_profile import probe_platform_auth
from hotpost.search_access import challenge_on_page
from hotpost.search_access import login_wall_on_page


@pytest.mark.parametrize('text',[
    '슬라이더를 드래그하여 퍼즐을 맞추세요',
    '슬라이더를 끌어서 퍼즐을 맞춰 주세요',
])
def test_actual_korean_tiktok_challenge_is_not_misreported_as_empty_or_loading(text):
    page=SimpleNamespace(url='https://www.tiktok.com/search/video',
        locator=lambda _:SimpleNamespace(inner_text=lambda:text))
    assert challenge_on_page(page)


@pytest.mark.parametrize('url,body',[
    ('https://www.tiktok.com/captcha',''),
    ('https://www.tiktok.com/login','Drag the slider to fit the puzzle'),
])
def test_auth_probe_keeps_captcha_distinct_from_unverified(url,body):
    response=SimpleNamespace(status=200,url=url,text=lambda:body)
    context=SimpleNamespace(request=SimpleNamespace(get=lambda *a,**k:response))
    assert probe_platform_auth(context,'tiktok')=='verification_required'


def test_unused_captcha_script_is_not_a_live_challenge():
    response = SimpleNamespace(status=200, url='https://www.tiktok.com/login',
        text=lambda:'<script>const msg="Drag the slider to fit the puzzle";</script><main>Log in</main>')
    context = SimpleNamespace(request=SimpleNamespace(get=lambda *a, **k: response))
    assert probe_platform_auth(context, 'tiktok') == 'unverified'


@pytest.mark.parametrize('heading,phone,code,expected', [
    ('登录后免费畅享高清视频', True, True, True),
    ('登录后免费畅享高清视频', False, False, False),
    ('登录后免费畅享高清视频', True, False, False),
    ('精选 搜索 登录 验证码登录', True, True, False),
])
def test_douyin_search_login_modal_requires_visible_fields(heading, phone, code, expected):
    def locator(selector):
        if selector == 'body':
            return SimpleNamespace(inner_text=lambda: heading)
        visible = phone if '手机号' in selector else code
        assert selector.endswith(':visible')
        return SimpleNamespace(count=lambda: int(visible))
    page = SimpleNamespace(locator=locator)
    assert login_wall_on_page(page, 'douyin') == expected
    assert not login_wall_on_page(page, 'tiktok')


def test_douyin_modal_halts_before_search_and_survives_restart(tmp_path, monkeypatch):
    from hotpost import browser_search as bs
    from hotpost.config import Settings
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    page = SimpleNamespace(url='https://www.douyin.com/jingxuan', locator=lambda selector:
        SimpleNamespace(inner_text=lambda: '登录后免费畅享高清视频', count=lambda: 1))
    settings = Settings(data_dir=tmp_path, source_browser_captcha_wait=0)
    audit = {}
    assert bs.BrowserSearcher(settings, tmp_path)._check_block(page, 'douyin', audit)
    assert audit['status'] == 'login_required'
    bs.BROWSER_COOLDOWNS.clear()
    later = bs.BrowserSearcher(settings, tmp_path)
    assert later._cooling_down('douyin')
    assert later.searches[0]['status'] == 'login_required'
