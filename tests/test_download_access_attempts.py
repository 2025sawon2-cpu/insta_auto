from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost import source_finder as finder, tiktok_download, youtube_download
from hotpost.browser_search import BrowserSearcher
from hotpost.source_search.models import Candidate
from hotpost.source_outcomes import platform_outcomes


@pytest.mark.parametrize('provider,url',[
    ('tiktok','https://www.tiktok.com/@selected/video/123456789'),
    ('youtube','https://www.youtube.com/watch?v=E2vmIs5gmTc'),
])
def test_saved_gate_without_navigation_does_not_count_download_attempt(tmp_path,monkeypatch,provider,url):
    settings=Settings(data_dir=tmp_path)
    monkeypatch.setattr('hotpost.config.load_settings',lambda:settings)
    monkeypatch.setattr(finder,'SOURCE_COOLDOWNS',{})
    monkeypatch.setattr(BrowserSearcher,'_cooling_down',lambda *a,**k:True)
    module=tiktok_download if provider=='tiktok' else youtube_download
    monkeypatch.setattr(module,'endpoint',lambda _: 'existing-browser')
    monkeypatch.setattr(module,'attach_browser',lambda *a:pytest.fail('Saved gate forbids navigation'))
    directory=tmp_path/'videos';directory.mkdir()
    candidate=Candidate(url,provider,download_attempted=True)
    assert finder.download_candidate(candidate,directory,1,80) is None
    assert candidate.download_attempted is False
    assert candidate.error
    outcomes=platform_outcomes([candidate],[])[provider]
    assert outcomes['download_attempts']==0
    assert outcomes['reasons']=={'not_attempted':1}


def test_captcha_after_actual_video_navigation_retains_attempt(tmp_path,monkeypatch):
    import playwright.sync_api
    settings=Settings(data_dir=tmp_path)
    calls=[]
    class Page:
        url='https://www.tiktok.com/@other/video/987654321'
        def is_closed(self):return False
        def on(self,*a):pass
        def remove_listener(self,*a):pass
        def bring_to_front(self):pass
        def goto(self,url,**kwargs):
            calls.append(url);self.url=url
            return SimpleNamespace(status=200,headers={})
    page=Page()
    monkeypatch.setattr('hotpost.config.load_settings',lambda:settings)
    monkeypatch.setattr(finder,'SOURCE_COOLDOWNS',{})
    monkeypatch.setattr(tiktok_download,'endpoint',lambda _: 'existing-browser')
    monkeypatch.setattr(tiktok_download,'attach_browser',lambda *a:SimpleNamespace(pages=[page]))
    monkeypatch.setattr(tiktok_download,'browser_lease',lambda *a:nullcontext())
    monkeypatch.setattr(tiktok_download,'pace',lambda *a:None)
    monkeypatch.setattr(playwright.sync_api,'sync_playwright',lambda:nullcontext(SimpleNamespace()))
    monkeypatch.setattr(BrowserSearcher,'_cooling_down',lambda *a,**k:False)
    monkeypatch.setattr(BrowserSearcher,'_check_block',lambda self,p,provider,audit,response=None:response is not None)
    directory=tmp_path/'videos';directory.mkdir()
    url='https://www.tiktok.com/@selected/video/123456789'
    candidate=Candidate(url,'tiktok')
    assert finder.download_candidate(candidate,directory,1,80) is None
    assert calls==[url]
    assert candidate.download_attempted is True
    assert '인증' in candidate.error
    outcomes=platform_outcomes([candidate],[])
    assert outcomes['tiktok']['download_attempts']==1
