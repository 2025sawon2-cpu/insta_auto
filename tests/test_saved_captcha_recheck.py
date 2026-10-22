from types import SimpleNamespace
import time
import pytest
from hotpost.config import Settings
from hotpost.editing_adapter import _atomic_json
from hotpost.search_access import access_record, manual_required, observe_saved_captcha
from hotpost import browser_search as bs


@pytest.fixture(autouse=True)
def mocked_image_reviewer(monkeypatch):
    from hotpost.studio_adapter import StudioAdapter
    def review(self,instruction,evidence,media):
        positive=bool(evidence['detector'].get('matched_text') or evidence['detector'].get('challenge_url'))
        return {'verdict':'captcha' if positive else 'not_captcha','visible_challenge':positive,
                'observations':['fixture image review'],'reason':'fixture image review'}
    monkeypatch.setattr(StudioAdapter,'editorial',review)

def saved(settings, reason='captcha'):
    record={'reason':reason,'requires_verification':reason=='captcha','until':time.time()+3600,
            'blocked_at':time.time(),'strikes':3,'server_retry_after':reason=='rate_limited'}
    _atomic_json(settings.data_dir/'search_cooldowns/tiktok.json',record)
    return record

def page(body='TikTok Search videos Profile',url='https://www.tiktok.com/search?q=wallet'):
    from PIL import Image
    return SimpleNamespace(url=url,locator=lambda _:SimpleNamespace(inner_text=lambda **kw:body),
        screenshot=lambda path,**kw:Image.new('RGB',(64,64),'white').save(path),
        goto=lambda *a,**k:pytest.fail('A CAPTCHA recheck must not navigate'),
        reload=lambda *a,**k:pytest.fail('A CAPTCHA recheck must not reload'))

def test_old_captcha_clears_only_after_current_existing_page_is_read(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path);old=saved(settings)
    monkeypatch.setattr(bs,'BROWSER_COOLDOWNS',{'tiktok':old['until']})
    searcher=bs.BrowserSearcher(settings,tmp_path/'debug')
    assert not searcher._cooling_down('tiktok',page=page())
    record=access_record(tmp_path,'tiktok')
    assert record['reason']=='captcha' and record['strikes']==3
    assert not manual_required(record) and record['until']==0
    assert record['last_captcha_check']['status']=='clear'
    assert record['last_captcha_check']['navigation_performed'] is False
    assert not searcher.searches

def test_actual_captcha_is_kept_even_when_the_old_timer_expired(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path);old=saved(settings);old['until']=1
    _atomic_json(tmp_path/'search_cooldowns/tiktok.json',old)
    monkeypatch.setattr(bs,'BROWSER_COOLDOWNS',{})
    searcher=bs.BrowserSearcher(settings,tmp_path/'debug')
    assert searcher._cooling_down('tiktok',page=page('슬라이더를 드래그하여 퍼즐을 맞추세요'))
    assert manual_required(access_record(tmp_path,'tiktok'))
    assert searcher.searches[-1]['captcha_check']['status']=='captcha'

@pytest.mark.parametrize('current',[page(''),page(url='https://example.com/search')])
def test_empty_or_wrong_platform_cannot_release_saved_challenge(tmp_path,current):
    settings=Settings(data_dir=tmp_path);old=saved(settings)
    assert observe_saved_captcha(settings,'tiktok',current)['status']=='unavailable'
    assert access_record(tmp_path,'tiktok')==old

def test_missing_existing_tab_is_unconfirmed_not_a_new_captcha(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path);old=saved(settings)
    searcher=bs.BrowserSearcher(settings,tmp_path/'debug')
    monkeypatch.setattr(searcher,'_page',lambda *_:(_ for _ in ()).throw(LookupError('existing_browser_tab_missing')))
    assert searcher._cooling_down('tiktok',context=SimpleNamespace())
    assert searcher.searches[-1]['status']=='not_attempted'
    assert searcher.searches[-1]['reason']=='captcha_recheck_unavailable'
    assert access_record(tmp_path,'tiktok')==old

def test_a_login_wall_does_not_become_clear_when_captcha_is_absent(tmp_path):
    settings=Settings(data_dir=tmp_path);saved(settings)
    result=observe_saved_captcha(settings,'tiktok',page('Log in to search'))
    assert result['status']=='login_required'
    assert manual_required(access_record(tmp_path,'tiktok'))

def test_429_wait_cannot_be_cleared_by_an_unblocked_page(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path);old=saved(settings,'rate_limited')
    monkeypatch.setattr(bs,'BROWSER_COOLDOWNS',{})
    searcher=bs.BrowserSearcher(settings,tmp_path/'debug')
    monkeypatch.setattr(searcher,'_recheck_saved_captcha',lambda *_:pytest.fail('429 is a different gate'))
    assert searcher._cooling_down('tiktok',page=page())
    assert access_record(tmp_path,'tiktok')==old

def test_search_route_supplies_the_current_context_to_captcha_check(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path);saved(settings)
    monkeypatch.setattr(bs,'BROWSER_COOLDOWNS',{})
    searcher=bs.BrowserSearcher(settings,tmp_path/'debug');existing=page('슬라이더를 드래그하여 퍼즐을 맞추세요')
    context=SimpleNamespace();reads=[]
    def current(ctx,provider):
        assert ctx is context and provider=='tiktok';reads.append(provider);return existing
    monkeypatch.setattr(searcher,'_page',current)
    searcher._platforms(context,['small wallet'],4,providers={'tiktok'})
    assert reads==['tiktok']
    assert searcher.searches[-1]['captcha_check']['status']=='captcha'

def test_tikvideo_recheck_requires_its_existing_app_tab(tmp_path):
    settings=Settings(data_dir=tmp_path)
    _atomic_json(tmp_path/'search_cooldowns/tikvideo.json',{'reason':'captcha','requires_verification':True})
    result=observe_saved_captcha(settings,'tikvideo',page('링크 붙여넣기 다운로드',url='https://tikvideo.app/ko'))
    assert result['status']=='clear'
    assert not manual_required(access_record(tmp_path,'tikvideo'))
