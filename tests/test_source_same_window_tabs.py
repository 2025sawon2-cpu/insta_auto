import json
import time
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost import source_browser_runtime as runtime
from hotpost.tiktok_download import resolve_download_page, record_access_observation


class Page:
    def __init__(self,identity,url,window=1,target_url=None):
        self.identity=identity;self.url=url;self.window=window;self.target_url=target_url or url
    def is_closed(self):return False
    def wait_for_timeout(self,*a):pass


class Context:
    def __init__(self,pages):
        self.pages=pages;self.creations=[];self.create_window=1;self.lose_response=False
    def new_cdp_session(self,page):
        def send(command,params=None):
            if command=='Target.createTarget':
                self.creations.append(params)
                added=Page('new-'+str(len(self.creations)),params['url'],self.create_window)
                self.pages.append(added)
                if self.lose_response:raise RuntimeError('response lost')
                return {'targetId':added.identity}
            if command=='Browser.getWindowForTarget':
                found=next(p for p in self.pages if p.identity==params['targetId'])
                return {'windowId':found.window}
            raise AssertionError(command)
        return SimpleNamespace(send=send,detach=lambda:None)


def fixture(tmp_path,monkeypatch,pages=None):
    settings=Settings(data_dir=tmp_path,source_browser_allow_same_window_tabs=True,
                      source_browser_existing_window_only=True)
    context=Context(pages or [Page('yt','https://www.youtube.com/')])
    identity={'endpoint':'http://127.0.0.1:1234','browser_id':'/devtools/browser/same',
              'profile':str(settings.source_browser_profile_dir.resolve())}
    monkeypatch.setattr(runtime,'_browser_identity',lambda *_:identity.copy())
    monkeypatch.setattr(runtime,'_window_inventory',lambda c,s:(identity.copy(),[
        {'targetId':p.identity,'type':'page','url':p.target_url,'window_id':p.window,'page':p} for p in c.pages]))
    runtime.bind_source_window(context,settings)
    return settings,context,identity


def test_current_window_only_missing_endpoint_never_launches_or_creates_profile(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path,source_browser_existing_window_only=True)
    monkeypatch.setattr(runtime.subprocess,'Popen',lambda *a,**k:pytest.fail('No Chrome launch'))
    with pytest.raises(RuntimeError,match='current window only'):runtime.ensure_browser(settings)
    assert not settings.source_browser_profile_dir.exists()


def test_current_window_attach_does_not_import_cookies_or_set_migration_marker(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path,source_browser_existing_window_only=True)
    monkeypatch.setattr(runtime,'endpoint',lambda *_:'http://same')
    monkeypatch.setattr('hotpost.browser_profile.restore_platform_cookies',lambda *a:pytest.fail('No cookie import'))
    monkeypatch.setattr('hotpost.login_exchange.apply_sessions',lambda *a:pytest.fail('No session replacement'))
    context=SimpleNamespace(set_default_timeout=lambda *a:None)
    playwright=SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=lambda *a,**k:SimpleNamespace(contexts=[context])))
    assert runtime.attach_browser(playwright,settings) is context
    assert not (settings.source_browser_profile_dir/'hotpost-live-session-v1').exists()


def test_resolver_is_read_only_and_explicit_creation_reuses_same_window(tmp_path,monkeypatch):
    settings,context,_=fixture(tmp_path,monkeypatch)
    with pytest.raises(LookupError,match='tab_missing'):runtime.existing_page(context,settings,'bilibili')
    with pytest.raises(LookupError,match='tab_missing'):runtime.managed_page(context,settings,'bilibili')
    assert context.creations==[]
    page=runtime.create_source_tab(context,settings,'bilibili',request_id='approved-one')
    assert context.creations==[{'url':'https://www.bilibili.com/','newWindow':False,'background':True}]
    assert runtime.create_source_tab(context,settings,'bilibili',request_id='same-retry') is page
    assert len(context.creations)==1 and page.window==1
    receipt=json.loads((settings.source_browser_profile_dir/'hotpost-source-tabs.json').read_text('utf-8'))['bilibili']
    assert receipt['target_id']==page.identity and receipt['window_id']==1 and receipt['request_id']=='approved-one'


def test_multi_window_or_stale_browser_binding_cannot_create_tabs(tmp_path,monkeypatch):
    settings,context,identity=fixture(tmp_path,monkeypatch)
    context.pages.append(Page('else','https://example.com/',window=2))
    with pytest.raises(LookupError,match='window_ambiguous'):runtime.create_source_tab(context,settings,'bilibili')
    context.pages.pop();identity['browser_id']='/devtools/browser/other'
    with pytest.raises(LookupError,match='identity_changed'):runtime.create_source_tab(context,settings,'bilibili')
    assert context.creations==[]


def test_existing_error_target_is_not_missing_and_cannot_be_replaced(tmp_path,monkeypatch):
    pages=[Page('blocked','chrome-error://chromewebdata/',target_url='https://www.tiktok.com/@sample/video/123')]
    settings,context,_=fixture(tmp_path,monkeypatch,pages)
    stats={'attempted':False}
    with pytest.raises(LookupError,match='browser_error_page'):resolve_download_page(context,settings,stats)
    assert stats['tab_resolution']=='browser_error_page' and stats['attempted'] is False
    assert 'access_observation' not in stats
    with pytest.raises(LookupError,match='browser_error_page'):runtime.create_source_tab(context,settings,'tiktok')
    assert context.creations==[] and context.pages==pages


@pytest.mark.parametrize('gate',[{'reason':'captcha','requires_verification':True},
    {'reason':'login_required','requires_verification':True},{'reason':'rate_limited','until':time.time()+3600}])
def test_new_tab_permission_does_not_override_access_gate(tmp_path,monkeypatch,gate):
    settings,context,_=fixture(tmp_path,monkeypatch)
    folder=tmp_path/'search_cooldowns';folder.mkdir()
    (folder/'bilibili.json').write_text(json.dumps(gate),encoding='utf-8')
    with pytest.raises(LookupError,match='access_gate_preserved'):runtime.create_source_tab(context,settings,'bilibili')
    assert context.creations==[] and json.loads((folder/'bilibili.json').read_text('utf-8'))==gate


def test_user_exclusion_prevents_new_tab(tmp_path,monkeypatch):
    settings,context,_=fixture(tmp_path,monkeypatch)
    (tmp_path/'source_collection_policy.json').write_text(json.dumps({'disabled_platforms':{'bilibili':'user'}}))
    with pytest.raises(LookupError,match='access_gate_preserved'):runtime.create_source_tab(context,settings,'bilibili')
    assert context.creations==[]


@pytest.mark.parametrize('lost,window',[(True,1),(False,2)])
def test_unknown_creation_or_wrong_window_does_not_close_or_retry(tmp_path,monkeypatch,lost,window):
    settings,context,_=fixture(tmp_path,monkeypatch)
    context.lose_response=lost;context.create_window=window
    with pytest.raises((LookupError,RuntimeError)):runtime.create_source_tab(context,settings,'bilibili')
    assert len(context.creations)==1 and len(context.pages)==2
    with pytest.raises(LookupError):runtime.create_source_tab(context,settings,'bilibili')
    assert len(context.creations)==1 and len(context.pages)==2


def test_explicit_target_resolves_multiple_tiktok_tabs_and_ambiguity_is_not_auth(tmp_path,monkeypatch):
    pages=[Page('one','https://www.tiktok.com/'),Page('two','https://www.tiktok.com/search?q=apple')]
    settings,context,_=fixture(tmp_path,monkeypatch,pages)
    stats={'attempted':False}
    with pytest.raises(LookupError,match='ambiguous'):resolve_download_page(context,settings,stats)
    assert stats['tab_resolution']=='tab_ambiguous' and 'access_observation' not in stats
    (settings.source_browser_profile_dir/'hotpost-tabs.json').write_text(json.dumps({'tiktok':'two'}))
    assert resolve_download_page(context,settings,{}) is pages[1]


def test_unbound_stale_legacy_hint_does_not_hide_the_current_unique_tab(tmp_path,monkeypatch):
    current=Page('now','https://www.tiktok.com/search?q=apple')
    settings,context,_=fixture(tmp_path,monkeypatch,[current])
    path=settings.source_browser_profile_dir/'hotpost-tabs.json'
    path.write_text(json.dumps({'tiktok':'closed-past-target'}))
    before=path.read_bytes()
    assert runtime.existing_page(context,settings,'tiktok') is current
    assert path.read_bytes()==before and context.creations==[]


def test_typed_403_is_denial_and_saved_login_is_not_current_observation():
    stats={};record_access_observation(stats,response=SimpleNamespace(status=403))
    assert stats['access_status']=='access_denied' and stats['access_observation']['observed'] is True
    record_access_observation(stats,{'reason':'login_required'},observed=False,basis='saved_gate')
    assert stats['access_observation']=={'kind':'login_required','observed':False,'basis':'saved_gate','http_status':None}


def observation_gate(tmp_path,settings,at=500):
    import hashlib
    folder=tmp_path/'search_cooldowns';folder.mkdir()
    path=folder/'yandex-images.json'
    path.write_text(json.dumps({'reason':'captcha','requires_verification':True,'blocked_at':at,'until':600,
        'captcha_observations':[{'at':at,'status':'captcha'}]}),encoding='utf-8')
    return path,hashlib.sha256(path.read_bytes()).hexdigest()


def test_explicit_historical_captcha_observation_opens_home_only_and_preserves_gate(tmp_path,monkeypatch):
    settings,context,_=fixture(tmp_path,monkeypatch);path,sha=observation_gate(tmp_path,settings)
    original=path.read_bytes()
    with pytest.raises(LookupError):runtime.create_source_tab(context,settings,'yandex-images')
    page=runtime.create_source_tab(context,settings,'yandex-images',purpose='access_observation',
        expected_access_record_sha256=sha,observation_before=1000,request_id='observe-past-captcha')
    assert page.url=='https://yandex.com/images/' and page.window==1
    assert context.creations==[{'url':'https://yandex.com/images/','newWindow':False,'background':True}]
    assert path.read_bytes()==original
    request=json.loads((settings.source_browser_profile_dir/'hotpost-source-tab-requests.json').read_text('utf-8'))['yandex-images']
    assert request['purpose']=='access_observation' and request['observed_gate_sha256']==sha


@pytest.mark.parametrize('case',['new_captcha','changed_receipt','future_cooldown','user_exclusion'])
def test_observation_permission_never_replaces_current_gate_or_exclusion(tmp_path,monkeypatch,case):
    import hashlib
    settings,context,_=fixture(tmp_path,monkeypatch);path,sha=observation_gate(tmp_path,settings)
    if case=='new_captcha':
        value=json.loads(path.read_text('utf-8'));value['last_captcha_check']={'status':'captcha','at':1500}
        path.write_text(json.dumps(value));sha=hashlib.sha256(path.read_bytes()).hexdigest()
    elif case=='changed_receipt':path.write_text(path.read_text('utf-8')+' ')
    elif case=='future_cooldown':
        value=json.loads(path.read_text('utf-8'));value['until']=time.time()+3600
        path.write_text(json.dumps(value));sha=hashlib.sha256(path.read_bytes()).hexdigest()
    else:(tmp_path/'source_collection_policy.json').write_text(json.dumps({'disabled_platforms':{'yandex-images':'user'}}))
    before=path.read_bytes()
    with pytest.raises(LookupError):runtime.create_source_tab(context,settings,'yandex-images',purpose='access_observation',
        expected_access_record_sha256=sha,observation_before=1000)
    assert context.creations==[] and path.read_bytes()==before


def test_tikvideo_fallback_creates_missing_tab_in_bound_window_and_reuses_it(tmp_path,monkeypatch):
    from hotpost.tikvideo_download import prepare_fallback_tab
    settings,context,_=fixture(tmp_path,monkeypatch)
    stats={};page=prepare_fallback_tab(context,settings,stats)
    assert page.url=='https://tikvideo.app/ko' and page.window==1 and len(context.creations)==1
    assert prepare_fallback_tab(context,settings,{}) is page and len(context.creations)==1
    assert stats['tab_resolution']=='created_same_window_fallback_target'


def test_tikvideo_current_error_tab_is_not_replaced_by_fallback(tmp_path,monkeypatch):
    from hotpost.tikvideo_download import prepare_fallback_tab
    settings,context,_=fixture(tmp_path,monkeypatch,[Page('error','chrome-error://chromewebdata/',
        target_url='https://tikvideo.app/ko')])
    with pytest.raises(LookupError,match='browser_error_page'):prepare_fallback_tab(context,settings,{})
    assert context.creations==[]


def test_tikvideo_multi_tab_uses_explicit_target_and_403_does_not_enter_fallback(tmp_path,monkeypatch):
    from hotpost import tikvideo_download as fallback
    pages=[Page('a','https://tikvideo.app/ko'),Page('b','https://tikvideo.app/ko')]
    settings,context,_=fixture(tmp_path,monkeypatch,pages)
    (settings.source_browser_profile_dir/'hotpost-tabs.json').write_text(json.dumps({'tikvideo':'b'}))
    assert fallback.prepare_fallback_tab(context,settings,{}) is pages[1]
    monkeypatch.setattr('hotpost.tiktok_download.download',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('access_denied HTTP 403')))
    monkeypatch.setattr(fallback,'download',lambda *a,**k:pytest.fail('403 must not authorize fallback'))
    with pytest.raises(RuntimeError,match='403'):fallback.with_fallback(settings,'https://tiktok.com/@a/video/123',tmp_path/'out.mp4',1000)
    assert context.creations==[]


def test_bound_media_403_then_no_progress_does_not_authorize_fallback(tmp_path,monkeypatch):
    from hotpost import tikvideo_download as fallback
    from hotpost.operation_progress import NoProgressTimeout
    settings,context,_=fixture(tmp_path,monkeypatch)
    def direct(*a,**kwargs):
        stats=kwargs['diagnostics'];stats.update(access_status='access_denied',
            access_observation={'kind':'access_denied','observed':True,'http_status':403})
        raise NoProgressTimeout('No completed MP4')
    monkeypatch.setattr('hotpost.tiktok_download.download',direct)
    monkeypatch.setattr(fallback,'download',lambda *a,**k:pytest.fail('Typed denial must block fallback'))
    with pytest.raises(NoProgressTimeout):fallback.with_fallback(settings,'https://tiktok.com/@a/video/123',tmp_path/'out.mp4',1000)
    assert context.creations==[]
