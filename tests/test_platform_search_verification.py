from types import SimpleNamespace
import json

import pytest

from hotpost.config import Settings
from hotpost.platform_verification import TikTokSearchVerification
from hotpost.platform_session import PlatformSessionManager
from hotpost.search_access import access_record, manual_required


def page_for(verification, text):
    return SimpleNamespace(url=verification.url,
        locator=lambda _: SimpleNamespace(inner_text=lambda:text))


def test_loading_home_and_search_results_are_distinct():
    verify=TikTokSearchVerification('mushroom skewers')
    page=page_for(verify, 'Top Users Videos LIVE')
    assert verify.observe(page)['status']=='loading'
    verify.candidates={'one':{'url':'one'}}
    assert verify.observe(page)=={'status':'results','candidates':1}
    page.url='https://www.tiktok.com/search?q=mushroom+skewers'
    assert verify.observe(page)['status']=='results'
    page.url='https://www.tiktok.com/'
    assert verify.observe(page)['status']=='page_changed'
    page.url='https://www.tiktok.com/search/video?q=a+different+query'
    assert verify.observe(page)['status']=='page_changed'


@pytest.mark.parametrize('text,status',[
    ('슬라이더를 드래그하여 퍼즐을 맞추세요','captcha'),
    ('Log in to search','login_required'),
    ('No results found','no_results'),
])
def test_visible_authentication_and_empty_search_are_distinct(text,status):
    verify=TikTokSearchVerification('mushroom skewers')
    assert verify.observe(page_for(verify,text))['status']==status


def test_observation_uses_existing_matching_response_without_new_requests():
    verify=TikTokSearchVerification('mushroom skewers')
    handlers={}
    page=page_for(verify,'Top Users Videos LIVE')
    page.on=lambda event,handler:handlers.update({event:handler})
    verify.attach(page)
    body={'status_code':0,'item_list':[{'id':'1234567890123','author':{'uniqueId':'cook'},'video':{}}]}
    response=lambda keyword:SimpleNamespace(url='https://www.tiktok.com/api/search/item/full/?keyword='+keyword,
        json=lambda:body)
    handlers['response'](response('other'))
    assert verify.observe(page)['status']=='loading'
    handlers['response'](response('mushroom+skewers'))
    assert verify.observe(page)['status']=='results'


@pytest.mark.parametrize('body,explicit,expected_gate',[
    ('Top Users Videos LIVE',True,True),
    ('슬라이더를 드래그하여 퍼즐을 맞추세요',True,True),
    ('No results found',False,True),
    ('No results found',True,False),
    ('결과를 찾을 수 없음 이 문구는 증오 행동과 관련될 수 있습니다.',True,False),
])
def test_verification_preserves_window_until_done_and_only_confirmed_search_releases_gate(
        tmp_path,monkeypatch,body,explicit,expected_gate):
    import playwright.sync_api as pw
    import hotpost.platform_session as module
    gate=tmp_path/'search_cooldowns/tiktok.json';gate.parent.mkdir()
    gate.write_text(json.dumps({'reason':'captcha','requires_verification':True}))
    verify=TikTokSearchVerification('mushroom skewers')
    page=page_for(verify,body)
    events=[];handlers={}
    page.on=lambda event,handler:handlers.update({event:handler})
    page.goto=lambda url,**kw:events.append(('navigate',url))
    page.is_closed=lambda:False
    context=SimpleNamespace(pages=[page],cookies=lambda:[dict(domain='.tiktok.com',path='/',
        name='sessionid',value='fixture',expires=-1)],close=lambda:events.append(('closed',None)))
    paths=[]
    def launch(path,**kw): paths.append(path); return context
    class Runtime:
        def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
        def __exit__(self,*a):pass
    monkeypatch.setattr(pw,'sync_playwright',Runtime)
    monkeypatch.setattr(module,'ensure_browser',lambda _:None)
    monkeypatch.setattr(module,'attach_browser',lambda *a: paths.append(str(a[1].source_browser_profile_dir)) or context)
    monkeypatch.setattr(module,'managed_page',lambda *a:page)
    monkeypatch.setattr('hotpost.browser_search.BrowserSearcher._submit_search',lambda *a: events.append(('input',verify.query)) or True)
    monkeypatch.setattr(module.time,'sleep',lambda _:None)
    monkeypatch.setattr('hotpost.browser_profile.probe_platform_auth',lambda *a:pytest.fail('No extra /login request'))
    class Stop:
        count=0
        def wait(self,_):
            self.count+=1
            if self.count<=3:
                assert not any(e[0]=='closed' for e in events)
                return False
            return True
        def is_set(self):return explicit
    manager=PlatformSessionManager(Settings(data_dir=tmp_path))
    manager.stop_event=Stop();manager.active_platform='tiktok'
    manager._work('tiktok',verify)
    assert not manager.error
    assert paths==[str(manager.settings.source_browser_profile_dir)]
    assert len([e for e in events if e[0]=='input'])==1
    assert not any(e[0]=='closed' for e in events)
    assert manual_required(access_record(tmp_path,'tiktok')) is expected_gate
    assert not module.BROWSER_LOCK.locked()


def test_busy_collection_cannot_be_opened_twice_but_lock_is_not_released(tmp_path,monkeypatch):
    import playwright.sync_api as pw
    import hotpost.platform_session as module
    class Runtime:
        def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(
            launch_persistent_context=lambda *a,**kw:pytest.fail('Cannot share busy profile')))
        def __exit__(self,*a):pass
    monkeypatch.setattr(pw,'sync_playwright',Runtime)
    manager=PlatformSessionManager(Settings(data_dir=tmp_path))
    module.BROWSER_LOCK.acquire()
    try:
        manager._work('tiktok',TikTokSearchVerification('mushroom skewers'))
        assert '수집 검색이 진행 중' in manager.error
        assert module.BROWSER_LOCK.locked()
    finally:module.BROWSER_LOCK.release()


def test_query_validation_occurs_before_launch(tmp_path):
    manager=PlatformSessionManager(Settings(data_dir=tmp_path))
    with pytest.raises(ValueError):manager.start('instagram','mushroom skewers')
    for query in ('',None,123,'x'*181):
        with pytest.raises(ValueError):TikTokSearchVerification(query)
    assert not manager.active


@pytest.mark.parametrize('provider', ['bilibili','tiktok'])
def test_controlled_search_replaces_old_query_instead_of_concatenating_it(tmp_path,monkeypatch,provider):
    from urllib.parse import urlencode
    from hotpost.browser_search import BrowserSearcher
    old='이전 검색어';query='A7 미니 파일'
    class Field:
        first=None
        value=old
        def is_visible(self):return True
        def count(self):return 1
        def wait_for(self,**kw):pass
        def fill(self,value):self.value+=value  # observed stale controlled state
        def input_value(self):return self.value
        def press_sequentially(self,value,**kw):self.value+=value
        def press(self,key):
            if key=='ControlOrMeta+A':self.value=''
            elif key=='Enter':
                name='q' if provider=='tiktok' else 'keyword'
                page.url=f'https://www.{provider}.com/search?'+urlencode({name:self.value})
    field=Field();field.first=field
    page=SimpleNamespace(url=f'https://www.{provider}.com/search?old=1',locator=lambda _:field,
                         wait_for_timeout=lambda _:None)
    def wait_for_url(predicate,**kw):assert predicate(page.url),page.url
    page.wait_for_url=wait_for_url
    searcher=BrowserSearcher(Settings(data_dir=tmp_path),tmp_path/'debug')
    monkeypatch.setattr(searcher,'_check_block',lambda *a:False)
    monkeypatch.setattr(searcher,'_pace',lambda *a,**kw:None)
    assert searcher._submit_search(page,provider,query,{})
    assert field.value==query
