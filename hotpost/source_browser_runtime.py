"""Visible, independently owned Chrome shared by login and search workers.

Only the controller may launch Chrome; disposable workers only attach. Never
close an attached context/browser: leaving Playwright disconnects its client.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler


class BrowserBusy(RuntimeError):
    pass


class BrowserTabSelectionUnavailable(LookupError):
    """Tab/window resolution is not authentication evidence."""
    def __init__(self,reason):
        super().__init__(reason)
        self.reason=reason


@contextmanager
def browser_lease(settings, name='operation'):
    """OS lock shared by processes; automatically released after worker death."""
    root = settings.source_browser_profile_dir
    root.mkdir(parents=True, exist_ok=True)
    with (root / f'hotpost-{name}.lock').open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BrowserBusy('수집용 Chrome에서 다른 검색·로그인 작업이 진행 중입니다. 완료 후 다시 시도하세요.') from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def endpoint(settings):
    """Validate the endpoint belongs to this dedicated profile, never personal Chrome."""
    try:
        lines = (settings.source_browser_profile_dir / 'DevToolsActivePort').read_text().splitlines()
        port = int(lines[0])
        if not 1 <= port <= 65535 or not lines[1].startswith('/devtools/browser/'):
            return None
        address = f'http://127.0.0.1:{port}'
        with build_opener(ProxyHandler({})).open(address + '/json/version', timeout=.5) as response:
            info = json.load(response)
        if info.get('webSocketDebuggerUrl', '').endswith(lines[1]):
            return address
    except (OSError, ValueError, IndexError):
        pass
    return None


def chrome_executable():
    candidates = []
    if os.name == 'nt':
        for key in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
            if os.environ.get(key):
                candidates.append(Path(os.environ[key]) / 'Google/Chrome/Application/chrome.exe')
    elif sys.platform == 'darwin':
        candidates.append(Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
    for name in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser'):
        located = shutil.which(name)
        if located:
            candidates.append(Path(located))
    for path in candidates:
        if path.is_file():
            return str(path)
    raise RuntimeError('수집용 Google Chrome 실행 파일을 찾을 수 없습니다.')


def ensure_browser(settings):
    if getattr(settings,'source_browser_existing_window_only',False):
        address=endpoint(settings)
        if not address:raise RuntimeError('existing_source_browser_unavailable: current window only')
        return address
    with browser_lease(settings, 'launch'):
        address = endpoint(settings)
        if address:
            return address
        options = ({'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
                   if os.name == 'nt' else {'start_new_session': True})
        # Launched by the controller, NOT its bounded worker (taskkill /T).
        subprocess.Popen([chrome_executable(),
            f'--user-data-dir={settings.source_browser_profile_dir.resolve()}',
            '--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1',
            '--no-first-run', '--no-default-browser-check', '--lang=ko-KR',
            '--new-window', 'about:blank'], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            address = endpoint(settings)
            if address:
                return address
            time.sleep(.2)
    raise RuntimeError('수집용 Chrome 연결 실패. 기존 수집 프로필 창이 다른 방식으로 열려 있는지 확인하세요.')


def _recover_hung_cdp_pages(address: str) -> None:
    import asyncio
    from urllib.parse import urlparse
    import websockets

    async def _probe_and_stop():
        with build_opener(ProxyHandler({})).open(address + '/json/list', timeout=2.0) as resp:
            tabs = json.load(resp)
        for tab in tabs:
            if tab.get('type') != 'page' or not tab.get('webSocketDebuggerUrl'):
                continue
            ws_url = tab['webSocketDebuggerUrl']
            hung = False
            try:
                async with asyncio.timeout(1.5):
                    async with websockets.connect(ws_url) as ws:
                        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': '1'}}))
                        await ws.recv()
            except Exception:
                hung = True
            if hung:
                try:
                    async with asyncio.timeout(2.0):
                        async with websockets.connect(ws_url) as ws:
                            await ws.send(json.dumps({'id': 2, 'method': 'Page.stopLoading'}))
                            await ws.recv()
                            parsed = urlparse(tab.get('url') or '')
                            if parsed.scheme in {'http', 'https'} and parsed.netloc:
                                home = f'{parsed.scheme}://{parsed.netloc}/'
                                await ws.send(json.dumps({'id': 3, 'method': 'Page.navigate', 'params': {'url': home}}))
                                await ws.recv()
                except Exception:
                    pass

    try:
        asyncio.run(_probe_and_stop())
    except Exception:
        pass


def attach_browser(playwright, settings):
    address = endpoint(settings)
    if not address:
        raise RuntimeError('수집용 Chrome 연결이 끊겼습니다. Chrome을 다시 열어 작업을 재개하세요.')
    try:
        browser = playwright.chromium.connect_over_cdp(address, timeout=10000)
    except Exception:
        if getattr(settings, 'source_browser_existing_window_only', False):
            raise  # Attachment-only callers must never navigate other tabs.
        _recover_hung_cdp_pages(address)
        browser = playwright.chromium.connect_over_cdp(address, timeout=10000)
    if not browser.contexts:
        raise RuntimeError('수집용 Chrome 기본 세션을 찾을 수 없습니다.')
    context = browser.contexts[0]
    context.set_default_timeout(15000)
    # One-time migration of existing cookie-only login records. Subsequent
    # logins and searches use live storage in this exact context.
    marker = settings.source_browser_profile_dir / 'hotpost-live-session-v1'
    if not marker.exists() and not getattr(settings,'source_browser_existing_window_only',False):
        from .browser_profile import restore_platform_cookies
        from .login_exchange import apply_sessions
        platforms = ['google', 'tiktok', 'douyin', 'xiaohongshu', 'youtube']
        restore_platform_cookies(context, settings.data_dir, platforms)
        apply_sessions(context, settings.data_dir, settings.source_browser_profile_dir, platforms)
        marker.write_text('1', encoding='utf-8')
    return context


def existing_page(context, settings, provider):
    """Select an already open platform page; never create a replacement tab."""
    if getattr(settings,'source_browser_existing_window_only',False):
        return _bound_existing_page(context,settings,provider)
    from urllib.parse import urlparse
    domain = {'google-lens':'google.com', 'yandex-images':'yandex.com','tikvideo':'tikvideo.app'}.get(provider, provider + '.com')
    domains = {domain, 'yandex.ru'} if provider == 'yandex-images' else {domain}
    matches = [page for page in context.pages if not page.is_closed() and any(
        (urlparse(page.url).hostname or '') == host or
        (urlparse(page.url).hostname or '').endswith('.' + host) for host in domains)]
    if len(matches) == 1:
        return matches[0]
    if matches:
        try:
            targets = json.loads((settings.source_browser_profile_dir / 'hotpost-tabs.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            targets = {}
        for page in matches:
            session = context.new_cdp_session(page)
            try:
                identity = session.send('Target.getTargetInfo')['targetInfo']['targetId']
            finally:
                session.detach()
            if identity == targets.get(provider):
                return page
    raise LookupError('existing_browser_tab_ambiguous' if matches else 'existing_browser_tab_missing')


def managed_page(context, settings, provider):
    """Reuse only our recorded target, leaving all user-created tabs untouched."""
    if getattr(settings,'source_browser_existing_window_only',False):
        return existing_page(context,settings,provider)
    from .editing_adapter import _atomic_json
    path = settings.source_browser_profile_dir / 'hotpost-tabs.json'
    try:
        targets = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        targets = {}
    def target_id(page):
        session = context.new_cdp_session(page)
        try:
            return session.send('Target.getTargetInfo')['targetInfo']['targetId']
        finally:
            session.detach()
    page = None
    for candidate in context.pages:
        if target_id(candidate) == targets.get(provider):
            page = candidate
            break
    if page is None:
        page = context.new_page()
        targets[provider] = target_id(page)
        _atomic_json(path, targets)
    page.bring_to_front()
    return page


def _json_record(path):
    try:
        value=json.loads(Path(path).read_text('utf-8'))
        return value if isinstance(value,dict) else {}
    except FileNotFoundError:return {}


def _browser_identity(settings):
    address=endpoint(settings)
    if not address:raise BrowserTabSelectionUnavailable('existing_source_browser_unavailable')
    lines=(settings.source_browser_profile_dir/'DevToolsActivePort').read_text().splitlines()
    return {'endpoint':address,'browser_id':lines[1],'profile':str(settings.source_browser_profile_dir.resolve())}


def _window_inventory(context,settings):
    identity=_browser_identity(settings)
    pages={}
    for page in context.pages:
        if page.is_closed():continue
        session=context.new_cdp_session(page)
        try:pages[session.send('Target.getTargetInfo')['targetInfo']['targetId']]=page
        finally:session.detach()
    if not pages:raise BrowserTabSelectionUnavailable('existing_source_window_missing')
    session=context.new_cdp_session(next(iter(pages.values())))
    try:
        targets=session.send('Target.getTargets')['targetInfos']
        rows=[]
        for target in targets:
            if target.get('type')!='page':continue
            window=session.send('Browser.getWindowForTarget',{'targetId':target['targetId']})['windowId']
            rows.append({**target,'window_id':window,'page':pages.get(target['targetId'])})
    finally:session.detach()
    # Confirm the caller's CDP context belongs to this configured endpoint.
    with build_opener(ProxyHandler({})).open(identity['endpoint']+'/json/list',timeout=2) as response:
        endpoint_targets={row['id'] for row in json.load(response) if row.get('type')=='page'}
    if not rows or any(row['targetId'] not in endpoint_targets for row in rows):
        raise BrowserTabSelectionUnavailable('source_context_endpoint_mismatch')
    return identity,rows


def bind_source_window(context,settings,window_id=None):
    """Explicit root action: bind the already open source window, never create one."""
    from .editing_adapter import _atomic_json
    if not getattr(settings,'source_browser_existing_window_only',False):
        raise BrowserTabSelectionUnavailable('same_window_policy_not_enabled')
    with browser_lease(settings):
        identity,rows=_window_inventory(context,settings)
        windows={row['window_id'] for row in rows}
        if window_id is None:
            if len(windows)!=1:raise BrowserTabSelectionUnavailable('existing_source_window_ambiguous')
            window_id=next(iter(windows))
        if window_id not in windows:raise BrowserTabSelectionUnavailable('approved_source_window_missing')
        path=settings.source_browser_profile_dir/'hotpost-source-window.json'
        old=_json_record(path)
        if old and any(old.get(k)!=v for k,v in {**identity,'window_id':window_id}.items()):
            raise BrowserTabSelectionUnavailable('source_window_binding_changed_requires_explicit_resolution')
        if not old:
            old={**identity,'window_id':window_id,'bound_at':time.time(),
                 'provenance':'explicit_current_window_authorization'}
            _atomic_json(path,old)
        return old


def _bound_inventory(context,settings):
    identity,rows=_window_inventory(context,settings)
    binding=_json_record(settings.source_browser_profile_dir/'hotpost-source-window.json')
    if not binding:raise BrowserTabSelectionUnavailable('approved_source_window_not_bound')
    if any(binding.get(k)!=value for k,value in identity.items()):
        raise BrowserTabSelectionUnavailable('source_browser_identity_changed')
    if not any(row['window_id']==binding['window_id'] for row in rows):
        raise BrowserTabSelectionUnavailable('approved_source_window_missing')
    return binding,rows


def _provider_host(provider):
    host={'google-lens':'google.com','yandex-images':'yandex.com','tikvideo':'tikvideo.app'}.get(provider,provider+'.com')
    return {host,'yandex.ru'} if provider=='yandex-images' else {host}


def _provider_matches(url,provider):
    from urllib.parse import urlparse
    host=urlparse(url).hostname or ''
    return any(host==domain or host.endswith('.'+domain) for domain in _provider_host(provider))


def _provider_rows(rows,provider,window_id):
    return [row for row in rows if row['window_id']==window_id and (
        _provider_matches(row.get('url',''),provider) or row.get('page') is not None
        and _provider_matches(row['page'].url,provider))]


def _is_error_page(page):
    return page.url.startswith(('chrome-error://','about:neterror','chrome://network-error'))


def _bound_existing_page(context,settings,provider):
    binding,rows=_bound_inventory(context,settings)
    records=_json_record(settings.source_browser_profile_dir/'hotpost-source-tabs.json')
    targets=_json_record(settings.source_browser_profile_dir/'hotpost-tabs.json')
    record=records.get(provider,{})
    target=record.get('target_id') or targets.get(provider)
    if record and any(record.get(k)!=binding.get(k) for k in ('browser_id','profile','window_id')):
        raise BrowserTabSelectionUnavailable('source_tab_binding_changed')
    if target:
        chosen=next((row for row in rows if row['targetId']==target),None)
        if chosen is not None and not record and (
                chosen['window_id']!=binding['window_id'] or chosen.get('page') is None
                or not (_provider_matches(chosen.get('url',''),provider) or _provider_matches(chosen['page'].url,provider))):
            chosen=None  # An unbound legacy hint cannot override the current window.
        if chosen is not None:
            if chosen['window_id']!=binding['window_id']:
                raise BrowserTabSelectionUnavailable('source_tab_outside_approved_window')
            if chosen.get('page') is None:raise BrowserTabSelectionUnavailable('source_tab_context_unavailable')
            if _is_error_page(chosen['page']):raise BrowserTabSelectionUnavailable('browser_error_page')
            if not (_provider_matches(chosen.get('url',''),provider) or _provider_matches(chosen['page'].url,provider)):
                raise BrowserTabSelectionUnavailable('source_tab_provider_changed')
            return chosen['page']
        # An explicit owned target disappearing never authorizes automatic replacement.
        if record:raise BrowserTabSelectionUnavailable('owned_source_tab_missing')
    matches=_provider_rows(rows,provider,binding['window_id'])
    if len(matches)>1:raise BrowserTabSelectionUnavailable('tab_ambiguous')
    if not matches:raise BrowserTabSelectionUnavailable('tab_missing')
    page=matches[0].get('page')
    if page is None:raise BrowserTabSelectionUnavailable('source_tab_context_unavailable')
    if _is_error_page(page):raise BrowserTabSelectionUnavailable('browser_error_page')
    return page


def create_source_tab(context,settings,provider,request_id=None,*,purpose='search',
                      expected_access_record_sha256=None,observation_before=None):
    """Explicit action only. Create a truly missing route in the bound single window.

    Ambiguous outcomes remain pending; no close/restart/replacement recovery.
    """
    import uuid
    from .editing_adapter import _atomic_json
    from .source_collection_access import disabled_platforms
    from .search_access import access_record, manual_required
    from .source_search.readiness import readiness_blocked
    homes={'tiktok':'https://www.tiktok.com/','youtube':'https://www.youtube.com/',
           'bilibili':'https://www.bilibili.com/','yandex-images':'https://yandex.com/images/',
           'google-lens':'https://www.google.com/','douyin':'https://www.douyin.com/',
           'xiaohongshu':'https://www.xiaohongshu.com/','tikvideo':'https://tikvideo.app/ko',
           'coupang':'https://www.coupang.com/'}
    if provider not in homes:raise ValueError('unsupported_source_tab_provider')
    if purpose not in {'search','access_observation'}:raise ValueError('unsupported_source_tab_purpose')
    if not (getattr(settings,'source_browser_allow_same_window_tabs',False)
            and getattr(settings,'source_browser_existing_window_only',False)):
        raise BrowserTabSelectionUnavailable('same_window_tab_creation_not_authorized')
    with browser_lease(settings):
        binding,rows=_bound_inventory(context,settings)
        if len({row['window_id'] for row in rows})!=1:
            raise BrowserTabSelectionUnavailable('source_tab_creation_window_ambiguous')
        request_path=settings.source_browser_profile_dir/'hotpost-source-tab-requests.json'
        requests=_json_record(request_path)
        previous=requests.get(provider)
        if previous and previous.get('status')!='resolved':
            raise BrowserTabSelectionUnavailable('source_tab_creation_outcome_unknown')
        # Existing blocked/error/owned targets are not missing platforms.
        try:return existing_page(context,settings,provider)
        except BrowserTabSelectionUnavailable as exc:
            if exc.reason!='tab_missing':raise
        gate=access_record(settings.data_dir,provider)
        historical_observation=False
        if purpose=='access_observation' and manual_required(gate) and gate.get('reason') in {'captcha','captcha_review_pending'}:
            import hashlib
            path=settings.data_dir/'search_cooldowns'/(provider+'.json')
            actual=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            latest=max([gate.get('blocked_at',gate.get('at',0)) or 0,
                *(r.get('at',0) or 0 for r in gate.get('captcha_observations',[]) if r.get('status')=='captcha'),
                (gate.get('last_captcha_check',{}).get('at',0) or 0)
                    if gate.get('last_captcha_check',{}).get('status')=='captcha' else 0])
            historical_observation=bool(expected_access_record_sha256 and actual==expected_access_record_sha256
                and latest>0 and observation_before is not None and latest<float(observation_before))
        if (provider in disabled_platforms(settings) or manual_required(gate) and not historical_observation
                or gate.get('until',0)>time.time()
                or purpose!='access_observation' and readiness_blocked(settings.data_dir,provider)):
            raise BrowserTabSelectionUnavailable('source_tab_creation_access_gate_preserved')
        pending={**binding,'provider':provider,'request_id':request_id or uuid.uuid4().hex,
                 'status':'submitted','at':time.time(),'url':homes[provider],
                 'provenance':'explicit_missing_platform_same_window_tab','purpose':purpose,
                 'observed_gate_sha256':expected_access_record_sha256 if historical_observation else None,
                 'observation_before':observation_before if historical_observation else None}
        requests[provider]=pending;_atomic_json(request_path,requests)
        anchor_row=next(row for row in rows if row['window_id']==binding['window_id'] and row.get('page') is not None)
        anchor=anchor_row['page']
        session=context.new_cdp_session(anchor)
        try:
            params={'url':homes[provider],'newWindow':False,'background':True}
            if anchor_row.get('browserContextId'):params['browserContextId']=anchor_row['browserContextId']
            created=session.send('Target.createTarget',params)
            target_id=created['targetId']
            pending['target_id']=target_id;_atomic_json(request_path,requests)
            window=session.send('Browser.getWindowForTarget',{'targetId':target_id})['windowId']
            if window!=binding['window_id']:
                pending.update(status='window_mismatch',observed_window_id=window);_atomic_json(request_path,requests)
                raise BrowserTabSelectionUnavailable('created_source_tab_window_mismatch')
            identity=_browser_identity(settings)
            if any(binding.get(k)!=value for k,value in identity.items()):
                pending.update(status='identity_mismatch');_atomic_json(request_path,requests)
                raise BrowserTabSelectionUnavailable('source_browser_identity_changed')
        finally:session.detach()
        records=_json_record(settings.source_browser_profile_dir/'hotpost-source-tabs.json')
        records[provider]={**pending,'status':'resolved','window_id':window,'target_id':target_id}
        _atomic_json(settings.source_browser_profile_dir/'hotpost-source-tabs.json',records)
        targets=_json_record(settings.source_browser_profile_dir/'hotpost-tabs.json');targets[provider]=target_id
        _atomic_json(settings.source_browser_profile_dir/'hotpost-tabs.json',targets)
        pending['status']='resolved';_atomic_json(request_path,requests)
        # Let Playwright receive its target-created event, without creating another tab.
        for _ in range(20):
            try:return existing_page(context,settings,provider)
            except BrowserTabSelectionUnavailable as exc:
                if exc.reason not in {'owned_source_tab_missing','source_tab_context_unavailable'}:raise
                anchor.wait_for_timeout(50)
        raise BrowserTabSelectionUnavailable('created_source_tab_context_pending')


def operation_interval(settings, provider, minimum=None):
    interval = max(1, settings.source_browser_search_interval if minimum is None else minimum)
    # Search and detail playback share this interval across workers. A shorter
    # caller override must not restore rapid TikTok navigation.
    return max(30, interval) if provider == 'tiktok' else interval


def pace(settings, provider, progress=lambda _: None, deadline=None, reserve=0, minimum=None, on_wait=None):
    """Caller holds operation lease. Persist starts across jobs and processes."""
    from .editing_adapter import _atomic_json
    provider = {'Google Lens': 'google-lens', 'Yandex': 'yandex-images'}.get(provider, provider)
    path = settings.source_browser_profile_dir / 'hotpost-search-starts.json'
    try:
        starts = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        starts = {}
    interval = operation_interval(settings, provider, minimum)
    now = time.time()
    last = starts.get(provider)
    remaining = max(0, interval - max(0, now - float(last))) if last is not None else 0
    if remaining:
        if on_wait:
            on_wait(time.time() + remaining)
        progress(f'{provider} · 다음 검색까지 {remaining:.1f}초 대기')
        time.sleep(remaining)
    if on_wait:
        on_wait(0)
    starts[provider] = time.time()
    _atomic_json(path, starts)


def connection_status(settings):
    return 'connected' if endpoint(settings) else 'disconnected'
