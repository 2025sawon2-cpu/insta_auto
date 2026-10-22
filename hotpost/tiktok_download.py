"""Receive a complete MP4 played by the existing logged-in TikTok tab.

No new browser/profile, raw page refetch, signatures, or authentication bypass.
Only the visible video's actual completed media response can become a file.
"""
from dataclasses import replace
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlparse

from .search_access import access_record, manual_required
from .source_browser_runtime import attach_browser, browser_lease, endpoint, pace, existing_page, BrowserTabSelectionUnavailable
from .operation_progress import run_progress_command, NoProgressTimeout


class MediaAssembly:
    """One URL/representation; never concatenate different media or missing bytes."""
    def __init__(self, max_bytes):
        self.max_bytes = max_bytes
        self.total = None
        self.data = None
        self.ranges = []
        self.validator = None

    def add(self, status, headers, body):
        if headers.get('content-type', '').split(';', 1)[0].lower() not in ('video/mp4', 'application/mp4'):
            return False
        if not body or len(body) > self.max_bytes:
            return False
        if status == 200:
            if not complete_media_response(status, headers, len(body)):
                return False
            start, end, total = 0, len(body), len(body)
        else:
            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', headers.get('content-range', ''))
            if status != 206 or not match:
                return False
            start, last, total = map(int, match.groups())
            end = last + 1
            if not (0 <= start < end <= total) or end - start != len(body):
                return False
        if total > self.max_bytes:
            return False
        validator = headers.get('etag') or headers.get('last-modified')
        if self.total is not None and (total != self.total or
                (self.validator and validator and self.validator != validator)):
            raise ValueError('영상 조각의 크기 또는 버전이 달라 합칠 수 없습니다.')
        if self.data is None:
            self.total, self.data = total, bytearray(total)
        if validator:
            self.validator = validator
        for a, b in self.ranges:
            left, right = max(start, a), min(end, b)
            if left < right and self.data[left:right] != body[left-start:right-start]:
                raise ValueError('겹치는 영상 조각의 내용이 달라 합칠 수 없습니다.')
        self.data[start:end] = body
        merged = []
        for a, b in sorted(self.ranges + [(start, end)]):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
            else:
                merged.append((a, b))
        self.ranges = merged
        return True

    def result(self):
        return bytes(self.data) if self.ranges == [(0, self.total)] else None


def item_media_urls(value, item_id):
    """Bind blob playback to URLs in this exact item's browser-loaded metadata."""
    urls = set()
    def strings(node):
        if isinstance(node, str) and node.startswith('https://'):
            urls.add(node)
        elif isinstance(node, dict):
            for child in node.values(): strings(child)
        elif isinstance(node, list):
            for child in node: strings(child)
    def walk(node):
        if isinstance(node, dict):
            if str(node.get('id', '')) == item_id and isinstance(node.get('video'), dict):
                strings(node['video'])
            for child in node.values(): walk(child)
        elif isinstance(node, list):
            for child in node: walk(child)
    walk(value)
    return urls


def publish_video(body, target, expected_duration=None):
    """Audio/init-only responses are not completed video downloads."""
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        raise RuntimeError('영상 파일 검증에 필요한 ffprobe가 없습니다.')
    target = Path(target)
    handle, name = tempfile.mkstemp(prefix=target.stem + '-', suffix='.receiving.mp4', dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(handle, 'wb') as file:
            file.write(body)
        result = subprocess.run([ffprobe, '-v', 'error', '-show_entries',
            'format=duration:stream=codec_type,width,height', '-of', 'json', str(temporary)],
            capture_output=True, text=True, timeout=30)
        try:
            info = json.loads(result.stdout)
            duration = float(info.get('format', {}).get('duration') or 0)
            video = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), {})
            valid = result.returncode == 0 and duration > 0 and video.get('width', 0) > 0
        except (ValueError, TypeError):
            return False
        if not valid or (expected_duration and abs(duration - expected_duration) > 1):
            return False
        decoded = run_progress_command([shutil.which('ffmpeg') or 'ffmpeg', '-v', 'error', '-xerror',
            '-i', str(temporary), '-map', '0:v:0', '-progress', 'pipe:1', '-nostats', '-f', 'null', '-'],
            idle_seconds=60)
        progress = dict(line.split('=', 1) for line in decoded.stdout.splitlines() if '=' in line)
        if (decoded.returncode or progress.get('progress') != 'end'
                or int(progress.get('frame', 0)) <= 0
                or abs(int(progress.get('out_time_us', 0)) / 1_000_000 - duration) > 1):
            return False
        temporary.replace(target)
        return True
    except (NoProgressTimeout, ValueError, KeyError):
        return False
    finally:
        temporary.unlink(missing_ok=True)


def complete_media_response(status, headers, size):
    mime = headers.get('content-type', '').split(';', 1)[0].lower()
    if mime not in ('video/mp4', 'application/mp4') or size <= 0:
        return False
    if status == 200:
        length = headers.get('content-length')
        try:
            return not length or int(length) == size
        except (ValueError, TypeError):
            return False
    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', headers.get('content-range', ''))
    if status != 206 or not match:
        return False
    start, end, total = map(int, match.groups())
    return start == 0 and end + 1 == total == size


def start_visible_playback(page, start_time=None):
    """Let the existing player fetch its own remaining segments through playback."""
    return page.locator('video').evaluate_all('''async (els, startTime) => {
        const visible = els.filter(e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length));
        if (visible.length !== 1 || visible[0].readyState < 1) return {ready:false};
        const video = visible[0], muted = video.muted;
        video.muted = true;
        try {
            if (startTime !== null) video.currentTime = startTime;
            if (video.paused && !video.ended) await video.play();
            return {ready:true, playing:!video.paused, original_muted:muted};
        } catch (_) {
            video.muted = muted;
            return {ready:true, playing:false};
        }
    }''', start_time)


def selected_photo_redirect(current_url, item_id):
    parsed=urlparse(current_url)
    return ((parsed.hostname or '') in ('tiktok.com','www.tiktok.com') and
            bool(re.fullmatch(r'/@[^/]+/photo/'+re.escape(item_id),parsed.path.rstrip('/'))))


def record_access_observation(stats,audit=None,response=None,*,observed=True,basis='current_page'):
    status=(audit or {}).get('status') or (audit or {}).get('reason')
    http_status=getattr(response,'status',None)
    kinds={'captcha':'captcha','verification_required':'captcha','login_required':'login_required',
           'rate_limited':'rate_limited','cooldown':'rate_limited','access_denied':'access_denied',
           'readiness_blocked':'readiness_blocked','captcha_review_pending':'captcha_review_pending'}
    kind=kinds.get(status) or ('rate_limited' if http_status==429 else 'access_denied' if http_status==403 else None)
    if kind:
        stats['access_status']=kind
        stats['access_observation']={'kind':kind,'observed':bool(observed),'basis':basis,
                                     'http_status':http_status}


def record_cooling_observation(stats, searcher, provider):
    """Report the decision that stopped this request, not an obsolete gate reason."""
    audit = next((row for row in reversed(searcher.searches) if row.get('provider') == provider), {})
    check = audit.get('captcha_check') or {}
    record_access_observation(stats, audit, observed=check.get('status') in {'captcha', 'login_required'},
                              basis='current_request_gate')


def resolve_download_page(context,settings,stats):
    """Same selected source target; tab ambiguity/error is not a login wall."""
    try:return existing_page(context,settings,'tiktok')
    except LookupError as exc:
        reason=getattr(exc,'reason',str(exc))
        kind=('browser_error_page' if 'browser_error_page' in reason else
              'tab_ambiguous' if 'ambiguous' in reason else
              'tab_missing' if 'tab_missing' in reason else 'window_unavailable')
        stats.update(access_status='not_attempted',tab_resolution=kind,access_resolution_error=kind)
        raise BrowserTabSelectionUnavailable(reason) from exc


def download(settings, url, target, max_bytes, deadline=None, diagnostics=None):
    from playwright.sync_api import sync_playwright
    from .browser_search import BrowserSearcher

    stats = diagnostics if diagnostics is not None else {}
    stats.update(attempted=False, navigation_started=False)
    if not endpoint(settings):
        stats.update(access_status='not_attempted',tab_resolution='window_unavailable',access_resolution_error='window_unavailable')
        raise RuntimeError('기존 수집용 Chrome이 연결되지 않았습니다. 새 브라우저로 대체하지 않습니다.')
    searcher = BrowserSearcher(replace(settings, source_browser_captcha_wait=0), Path(target).parent)
    gate=access_record(settings.data_dir,'tiktok')
    if not (gate.get('reason') in {'captcha','captcha_review_pending'} and manual_required(gate)) and searcher._cooling_down('tiktok'):
        record_cooling_observation(stats,searcher,'tiktok')
        raise RuntimeError('TikTok 접근 중지 또는 휴식 상태입니다. 영상 페이지를 열지 않습니다.')
    if not re.fullmatch(r'https://(?:www\.)?tiktok\.com/@[^/?]+/video/\d+', url):
        raise ValueError('검색에서 확인한 TikTok 영상 상세 URL이 필요합니다.')
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    from .operation_progress import ProgressWatch, watch_browser_transfer
    from .source_transfer_trace import event
    watch = ProgressWatch(settings.source_download_idle_timeout, 'TikTok 영상 수신')
    stats.update(media_responses=0, partial_responses=0, body_errors=0, metadata_urls=0, max_visible_players=0,
                 assembled_files=0, explicit_media_requests=0)
    item_id = url.rsplit('/', 1)[-1]
    with browser_lease(settings), sync_playwright() as pw:
        context = attach_browser(pw, settings)
        page = resolve_download_page(context,settings,stats)
        stats['tab_resolution']='selected_existing_target'
        if searcher._cooling_down('tiktok',page=page):
            record_cooling_observation(stats,searcher,'tiktok')
            raise RuntimeError('TikTok 현재 화면의 인증 또는 요청 제한 때문에 영상 페이지를 열지 않습니다.')
        playback = {}
        assemblies = {}
        bound_urls = set()
        fatal = []
        rejected = set()
        last_playback_sample = 0
        selected_media = set()
        close_transfer = watch_browser_transfer(context, page, watch,
            lambda src: src in selected_media or src in bound_urls, max_bytes=max_bytes)

        def receive(request):
            response = request.response()
            if response is None:
                return
            headers = response.headers
            mime = headers.get('content-type', '').split(';', 1)[0].lower()
            if mime == 'application/json' and urlparse(response.url).hostname in ('www.tiktok.com', 'tiktok.com'):
                try:
                    bound_urls.update(item_media_urls(response.json(), item_id))
                except Exception:
                    pass
            if mime not in ('video/mp4', 'application/mp4'):
                return
            stats['media_responses'] += 1
            stats.setdefault('first_response_at',time.time())
            stats['partial_responses'] += int(response.status == 206)
            if response.status not in (200, 206):
                if response.status==429 or response.url in selected_media or response.url in bound_urls:
                    record_access_observation(stats,response=response,basis='media_response')
                if response.status == 429:
                    searcher._block('tiktok', {}, 'rate_limited', response)
                    fatal.append('TikTok 영상 응답에서 요청 제한이 확인됐습니다.')
                return
            try:
                if int(headers.get('content-length', 0)) > max_bytes:
                    return
                event(stats,'reading_response_body')
                body = response.body()
                if response.url not in assemblies and len(assemblies) >= 4:
                    return
                assembly = assemblies.setdefault(response.url, MediaAssembly(max_bytes))
                assembly.add(response.status, headers, body)
                event(stats,'awaiting_media')
            except ValueError as exc:
                fatal.append(str(exc))
            except Exception:
                stats['body_errors'] += 1
                return

        page.on('requestfinished', receive)
        audit = {'provider': 'tiktok'}
        try:
            if searcher._check_block(page, 'tiktok', audit):
                record_access_observation(stats,audit)
                raise RuntimeError('현재 TikTok 페이지의 로그인·인증 확인이 필요합니다.')
            page.bring_to_front()
            pace(settings, 'tiktok')
            watch.reset()
            timeout = settings.source_browser_navigation_timeout * 1000
            stats.update(attempted=True, navigation_started=True)
            event(stats,'navigation')
            if page.url.split('?', 1)[0] == url:
                response = page.reload(wait_until='domcontentloaded', timeout=timeout)
            else:
                response = page.goto(url, wait_until='domcontentloaded', timeout=timeout)
            if searcher._check_block(page, 'tiktok', audit, response):
                record_access_observation(stats,audit,response)
                raise RuntimeError('TikTok 상세 페이지에서 로그인·인증 또는 요청 제한이 확인됐습니다.')
            if response is not None and response.status==403:
                record_access_observation(stats,response=response,basis='navigation_response')
                raise RuntimeError('TikTok access_denied HTTP 403 · current target preserved')
            event(stats,'awaiting_media')
            # TikTok may replace its document once after DOMContentLoaded.
            # Keep the same navigation and received bytes; retry only the DOM
            # read, under the existing URL/auth/progress checks below.
            dom_resets = 0
            while True:
                watch.check()
                if fatal:
                    raise RuntimeError(fatal[0])
                if selected_photo_redirect(page.url,item_id):
                    raise RuntimeError('선택한 TikTok 항목은 사진 게시물입니다. 영상 소스에서 제외합니다.')
                if page.url.split('?', 1)[0] != url:
                    raise RuntimeError('사용자가 다른 영상으로 이동하여 저장을 중지했습니다.')
                if searcher._check_block(page, 'tiktok', audit):
                    record_access_observation(stats,audit)
                    raise RuntimeError('TikTok 상세 페이지의 인증 확인이 필요합니다.')
                try:
                    if not bound_urls:
                        for raw in page.locator('script[type="application/json"]').all_text_contents():
                            try: bound_urls.update(item_media_urls(json.loads(raw), item_id))
                            except (ValueError, TypeError): pass
                    # Bind to the visible player, never recommendation media.
                    visible = page.locator('video').evaluate_all('els => els.filter(e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length)).map(e => ({src:e.currentSrc || e.src,duration:Number.isFinite(e.duration)?e.duration:null}))')
                except Exception as exc:
                    if 'Execution context was destroyed' not in str(exc) or dom_resets >= 3:
                        raise
                    dom_resets += 1
                    stats['document_read_resets'] = dom_resets
                    page.wait_for_timeout(1000)
                    continue
                visible_urls = [v['src'] for v in visible if v.get('src')]
                selected_media.update(visible_urls)
                for src, assembly in assemblies.items():
                    if src in selected_media or src in bound_urls:
                        watch.observe(('covered', src), sum(b-a for a,b in assembly.ranges))
                stats['max_visible_players'] = max(stats['max_visible_players'],len(visible))
                expected_duration = next((v['duration'] for v in visible if v.get('duration')), None)
                stats['metadata_urls'] = len(bound_urls)
                stats['source_kind'] = 'blob' if any(src.startswith('blob:') for src in visible_urls) else 'url'
                try:
                    if time.monotonic() - last_playback_sample >= 10:
                        stats.setdefault('playback_samples', []).append(page.locator('video').evaluate_all('''els => els
                            .filter(e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length))
                            .map(e => ({time:e.currentTime, paused:e.paused, ended:e.ended,
                                readyState:e.readyState, networkState:e.networkState,
                                buffered:Array.from({length:e.buffered.length},(_,i)=>[e.buffered.start(i),e.buffered.end(i)])}))'''))
                        last_playback_sample = time.monotonic()
                        event(stats,'awaiting_media',last_progress_at=time.time()-max(0,time.monotonic()-watch.last_progress),
                              covered_bytes=sum(sum(b-a for a,b in item.ranges) for src,item in assemblies.items()
                                                if src in selected_media or src in bound_urls))
                    if not playback.get('ready'):
                        playback = start_visible_playback(page)
                        stats['playback_started'] = playback.get('playing', False)
                except Exception as exc:
                    # These are DOM reads too. Preserve received bytes/listeners
                    # across TikTok's own document replacement; do not reload.
                    if 'Execution context was destroyed' not in str(exc) or dom_resets >= 3:
                        raise
                    dom_resets += 1
                    stats['document_read_resets'] = dom_resets
                    page.wait_for_timeout(1000)
                    continue
                matching = [src for src, assembly in assemblies.items()
                    if (src in visible_urls or (stats['source_kind'] == 'blob' and src in bound_urls))
                    and src not in rejected
                    and assembly.result() is not None]
                if matching:
                    selected = matching[0]
                    if not publish_video(assemblies[selected].result(), target, expected_duration):
                        rejected.add(selected)
                        stats['rejected_non_video_streams'] = len(rejected)
                        continue
                    stats['assembled_files'] = 1
                    stats['saved_bytes'] = target.stat().st_size
                    stats['covered_bytes'] = assemblies[selected].total
                    return target
                page.wait_for_timeout(500)
            stats['failure_stage'] = ('no_visible_player' if not stats['max_visible_players'] else
                'incomplete_media_reception' if assemblies else 'no_media_response')
            raise RuntimeError('현재 TikTok 페이지에서 표시된 영상의 완전한 MP4 응답을 확보하지 못했습니다.')
        finally:
            close_transfer()
            stats['received_streams'] = [{'total_bytes': a.total, 'covered_bytes': sum(b-a0 for a0,b in a.ranges),
                'bound_to_item': src in bound_urls} for src,a in assemblies.items()]
            event(stats)
            page.remove_listener('requestfinished', receive)
            if playback.get('playing') and page.url.split('?', 1)[0] == url:
                try:
                    page.locator('video').evaluate_all('''(els, originalMuted) => {
                        const visible = els.filter(e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length));
                        if (visible.length === 1) { visible[0].pause(); visible[0].muted = originalMuted; }
                    }''', playback['original_muted'])
                except Exception:
                    pass
