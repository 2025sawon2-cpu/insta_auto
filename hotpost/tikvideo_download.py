"""User-authorized visible form fallback, in the existing collector Chrome.

Never use this route to bypass a stored TikTok challenge or request limit.
"""
from dataclasses import replace
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse
from .source_browser_runtime import attach_browser,browser_lease,endpoint,pace,existing_page,create_source_tab
from .tiktok_download import publish_video

VIDEO_LABEL = re.compile(r'^(?:MP4\s*다운로드|다운로드\s*(?:MP4|HD|비디오|영상)|워터마크\s*없이.*다운로드.*|Download\s*(?:MP4|HD|without watermark).*)$', re.I)


def prepare_fallback_tab(context,settings,stats=None):
    """An authorized fallback action may create only a truly missing same-window tab."""
    if not getattr(settings,'source_browser_existing_window_only',False):return None
    try:return existing_page(context,settings,'tikvideo')
    except LookupError as exc:
        reason=getattr(exc,'reason',str(exc))
        if stats is not None:stats.update(tab_resolution=reason,access_status='not_attempted')
        if reason!='tab_missing':raise
        page=create_source_tab(context,settings,'tikvideo',request_id='tikvideo-authorized-visible-fallback')
        if stats is not None:stats['tab_resolution']='created_same_window_fallback_target'
        return page


def _await_transfer(page,artifact,transfers,watch,max_bytes):
    watch.reset('대체 영상 파일 수신')
    while True:
        matches=[(guid,t) for guid,t in transfers.items() if t.get('url')==artifact.url]
        if len(matches)>1:raise RuntimeError('대체 다운로드를 하나로 특정할 수 없습니다.')
        if matches:
            guid,transfer=matches[0]
            size=transfer.get('receivedBytes',0)
            if size>max_bytes:raise RuntimeError('대체 영상 크기 제한 초과')
            watch.observe(guid,size)
            if transfer.get('state')=='completed':return
            if transfer.get('state')=='canceled':raise RuntimeError('대체 다운로드가 취소되었습니다.')
        watch.check();page.wait_for_timeout(500)


def download(settings,url,target,max_bytes,deadline=None,diagnostics=None):
    from playwright.sync_api import sync_playwright
    from .browser_search import BrowserSearcher
    stats=diagnostics if diagnostics is not None else {}
    stats.update(attempted=False,navigation_started=False,submitted=False)
    if not endpoint(settings):raise RuntimeError('기존 수집용 Chrome이 연결되지 않았습니다.')
    searcher=BrowserSearcher(replace(settings,source_browser_captcha_wait=0),Path(target).parent)
    for provider in ('tiktok','tikvideo'):
        if searcher._cooling_down(provider):
            from .search_access import access_record
            reason=access_record(settings.data_dir,provider).get('reason','access_gate')
            if diagnostics is not None:
                diagnostics.update(blocked_provider=provider,blocked_reason=reason,submitted=False)
            if reason=='response_blocked':
                raise RuntimeError(f'{provider} 브라우저 응답 차단 후 휴식 중이라 대체 다운로드를 하지 않습니다.')
            raise RuntimeError(f'{provider} 인증·요청 제한 중에는 대체 다운로드도 하지 않습니다.')
    if not re.fullmatch(r'https://(?:www\.)?tiktok\.com/@[^/?]+/video/\d+',url):
        raise ValueError('검색에서 확인한 TikTok 영상 링크가 필요합니다.')
    from .operation_progress import ProgressWatch
    watch=ProgressWatch(settings.source_download_idle_timeout,'대체 영상 결과 응답')
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    stats.update(method='tikvideo_visible_form',site='https://tikvideo.app/ko',submitted=False)
    with sync_playwright() as pw:
        context=attach_browser(pw,settings)
        prepare_fallback_tab(context,settings,stats)
        with browser_lease(settings):
            if getattr(settings,'source_browser_existing_window_only',False):
                page=existing_page(context,settings,'tikvideo')
            else:
                pages=[p for p in context.pages if urlparse(p.url).hostname=='tikvideo.app']
                if len(pages)>1:raise RuntimeError('tikvideo.app 탭을 하나로 지정해야 합니다.')
                page=pages[0] if pages else context.new_page()
            pace(settings,'tikvideo',minimum=30)
            watch.reset()
            audit={'provider':'tikvideo'}
            try:
                stats['navigation_started']=True
                response=page.goto('https://tikvideo.app/ko',wait_until='domcontentloaded',timeout=30000)
            except Exception as exc:
                if 'ERR_BLOCKED_BY_RESPONSE' in str(exc):
                    searcher._block('tikvideo',audit,'response_blocked')
                    stats['response_blocked']=True
                    raise RuntimeError('tikvideo.app 페이지 응답이 브라우저에서 차단되어 대체 다운로드를 중지했습니다.') from exc
                raise
            if searcher._check_block(page,'tikvideo',audit,response):raise RuntimeError('tikvideo.app 인증 또는 요청 제한으로 중지했습니다.')
            field=page.get_by_placeholder('여기에 틱톡 링크 붙여넣기',exact=True)
            field.wait_for(state='visible',timeout=15000)
            field.fill(url)
            stats['attempted']=True
            page.get_by_role('button',name='다운로드',exact=True).click(timeout=15000)
            stats['submitted']=True
            watch.reset()
            while True:
                watch.check()
                if searcher._check_block(page,'tikvideo',audit):raise RuntimeError('tikvideo.app 인증 확인이 필요합니다.')
                if urlparse(page.url).hostname!='tikvideo.app':raise RuntimeError('다른 사이트로 이동하여 대체 다운로드를 중지했습니다.')
                # Only a video-specific result, never the submit button, MP3, an
                # advertisement, installer, or navigation link.
                control=page.get_by_role('link',name=VIDEO_LABEL).filter(visible=True)
                if not control.count():
                    control=page.get_by_role('button',name=VIDEO_LABEL).filter(visible=True)
                if control.count():
                    transfers={}
                    session=None
                    browser=getattr(context,'browser',None)
                    if hasattr(browser,'new_browser_cdp_session'):
                        session=browser.new_browser_cdp_session()
                        session.on('Browser.downloadWillBegin',lambda e:transfers.update({e['guid']:{'url':e['url'],'state':'inProgress'}}))
                        session.on('Browser.downloadProgress',lambda e:transfers.setdefault(e['guid'],{}).update(e))
                        session.send('Browser.setDownloadBehavior',{'behavior':'default','eventsEnabled':True})
                    if session is None:
                        raise RuntimeError('브라우저 파일 수신 진행을 확인할 수 없어 대체 다운로드를 중지했습니다.')
                    try:
                        with page.expect_download(timeout=settings.source_download_idle_timeout*1000) as event:
                            control.first.click(timeout=15000)
                        artifact=event.value
                        _await_transfer(page,artifact,transfers,watch,max_bytes)
                    except Exception:
                        if 'artifact' in locals():artifact.cancel()
                        raise
                    finally:
                        if session:session.detach()
                    failure=artifact.failure()
                    if failure:raise RuntimeError('브라우저 다운로드가 완료되지 않았습니다.')
                    with tempfile.TemporaryDirectory(dir=target.parent,prefix='tikvideo-') as folder:
                        temporary=Path(folder)/'received.mp4'
                        artifact.save_as(temporary)
                        if temporary.stat().st_size>max_bytes:raise RuntimeError('대체 영상 파일이 크기 제한을 초과했습니다.')
                        if not publish_video(temporary.read_bytes(),target):raise RuntimeError('대체 파일이 완전한 영상이 아닙니다.')
                    stats.update(saved_bytes=target.stat().st_size,complete=True)
                    return target
                page.wait_for_timeout(1000)

def with_fallback(settings,url,target,max_bytes,deadline=None,diagnostics=None):
    from .tiktok_download import download as direct
    from .browser_search import BrowserSearcher
    stats=diagnostics if diagnostics is not None else {}
    from .source_transfer_trace import event, finish
    try:
        event(stats,'direct')
        try:
            path=direct(settings,url,target,max_bytes,diagnostics=stats)
            stats['method']='existing_browser_playback'
        except Exception as exc:
            stats['direct_error']=str(exc)[:300]
            stats['direct_ended_at']=time.time()
            if (stats.get('access_status') in {'access_denied','captcha','login_required','rate_limited'}
                    or stats.get('access_resolution_error')):
                raise
            from .operation_progress import NoProgressTimeout
            if not isinstance(exc,NoProgressTimeout) and '완전한 MP4 응답을 확보하지 못했습니다' not in str(exc):raise
            if BrowserSearcher(settings,Path(target).parent)._cooling_down('tiktok'):raise
            fallback={'_checkpoint':stats.get('_checkpoint')};stats['fallback']=fallback
            event(stats,'fallback')
            event(fallback,'starting')
            try:
                path=download(settings,url,target,max_bytes,diagnostics=fallback)
            except Exception as fallback_error:
                finish(fallback,error=fallback_error)
                raise
            finish(fallback)
            stats['method']='tikvideo_visible_form'
        finish(stats)
        return path
    except Exception as exc:
        finish(stats,error=exc)
        raise
