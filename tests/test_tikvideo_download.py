from pathlib import Path
import pytest
from hotpost.config import Settings
from hotpost import tikvideo_download as fallback, tiktok_download as direct
from hotpost.browser_search import BrowserSearcher


def test_successful_browser_download_does_not_use_third_party(tmp_path,monkeypatch):
    target=tmp_path/'one.mp4'
    monkeypatch.setattr(direct,'download',lambda *args,**kwargs:target)
    monkeypatch.setattr(fallback,'download',lambda *args,**kwargs:pytest.fail('Direct success must not contact fallback'))
    diagnostics={}
    assert fallback.with_fallback(Settings(data_dir=tmp_path),'url',target,100,diagnostics=diagnostics)==target
    assert diagnostics['method']=='existing_browser_playback'


def test_incomplete_media_uses_one_authorized_fallback(tmp_path,monkeypatch):
    calls=[]
    def fail(*args,**kwargs):raise RuntimeError('현재 TikTok 페이지에서 표시된 영상의 완전한 MP4 응답을 확보하지 못했습니다.')
    monkeypatch.setattr(direct,'download',fail)
    monkeypatch.setattr(BrowserSearcher,'_cooling_down',lambda *args:False)
    target=tmp_path/'one.mp4'
    monkeypatch.setattr(fallback,'download',lambda *args,**kwargs:calls.append(args[1]) or target)
    diagnostics={}
    assert fallback.with_fallback(Settings(data_dir=tmp_path),'observed-url',target,100,diagnostics=diagnostics)==target
    assert calls==['observed-url']
    assert diagnostics['method']=='tikvideo_visible_form'


@pytest.mark.parametrize('reason',['CAPTCHA 인증 확인 필요','요청 제한 429','사용자가 다른 영상으로 이동하여 저장을 중지했습니다.'])
def test_authentication_or_changed_tab_never_uses_fallback(tmp_path,monkeypatch,reason):
    def fail(*args,**kwargs):raise RuntimeError(reason)
    monkeypatch.setattr(direct,'download',fail)
    monkeypatch.setattr(fallback,'download',lambda *args,**kwargs:pytest.fail('Stop conditions must not switch routes'))
    with pytest.raises(RuntimeError,match=reason):
        fallback.with_fallback(Settings(data_dir=tmp_path),'url',tmp_path/'one.mp4',100)


def test_cooldown_record_blocks_even_incomplete_media_fallback(tmp_path,monkeypatch):
    def fail(*args,**kwargs):raise RuntimeError('완전한 MP4 응답을 확보하지 못했습니다.')
    monkeypatch.setattr(direct,'download',fail)
    monkeypatch.setattr(BrowserSearcher,'_cooling_down',lambda *args:True)
    monkeypatch.setattr(fallback,'download',lambda *args,**kwargs:pytest.fail('Saved cooldown is binding'))
    with pytest.raises(RuntimeError):fallback.with_fallback(Settings(data_dir=tmp_path),'url',tmp_path/'one.mp4',100)


def test_response_block_cooldown_is_distinct_from_tiktok_authentication(tmp_path,monkeypatch):
    from hotpost.editing_adapter import _atomic_json
    _atomic_json(tmp_path/'search_cooldowns/tikvideo.json',{'reason':'response_blocked'})
    monkeypatch.setattr(fallback,'endpoint',lambda _: 'existing-browser')
    monkeypatch.setattr(BrowserSearcher,'_cooling_down',lambda self,provider:provider=='tikvideo')
    monkeypatch.setattr(fallback,'attach_browser',lambda *args:pytest.fail('Blocked fallback must not access the browser'))
    diagnostics={}
    with pytest.raises(RuntimeError,match='tikvideo 브라우저 응답 차단'):
        fallback.download(Settings(data_dir=tmp_path),'https://www.tiktok.com/@one/video/123',tmp_path/'one.mp4',100,diagnostics=diagnostics)
    assert diagnostics=={'blocked_provider':'tikvideo','blocked_reason':'response_blocked',
                         'submitted':False,'attempted':False,'navigation_started':False}


def test_browser_file_transfer_keeps_waiting_while_bytes_arrive():
    from types import SimpleNamespace
    from hotpost.operation_progress import ProgressWatch
    now=[0];transfers={'file':{'url':'selected','receivedBytes':0,'state':'inProgress'}}
    def receive(_):
        now[0]+=.6
        transfers['file']['receivedBytes']+=10
        if transfers['file']['receivedBytes']==100:transfers['file']['state']='completed'
    fallback._await_transfer(SimpleNamespace(wait_for_timeout=receive),SimpleNamespace(url='selected'),
        transfers,ProgressWatch(1,clock=lambda:now[0]),200)
    assert now[0]>5


def test_browser_file_transfer_stops_when_receiving_same_bytes():
    from types import SimpleNamespace
    from hotpost.operation_progress import ProgressWatch,NoProgressTimeout
    now=[0];transfers={'file':{'url':'selected','receivedBytes':10,'state':'inProgress'}}
    def waiting(_):now[0]+=.6
    with pytest.raises(NoProgressTimeout):
        fallback._await_transfer(SimpleNamespace(wait_for_timeout=waiting),SimpleNamespace(url='selected'),
            transfers,ProgressWatch(1,clock=lambda:now[0]),200)
