"""Receive the selected YouTube player's media in the existing Chrome session.

No extractor requests, copied cookies, URL signatures, or new browser profiles.
Video-only tracks are permitted for source footage with a separate narration.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

from .source_browser_runtime import attach_browser, browser_lease, endpoint, pace
from .tiktok_download import MediaAssembly, publish_video, start_visible_playback
from .youtube_ump import BrowserUmpMedia
from .operation_progress import run_progress_command, NoProgressTimeout


def video_id(url):
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or host not in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'):
        return None
    if host == 'youtu.be':
        value = parsed.path.strip('/')
    elif parsed.path == '/watch':
        value = parse_qs(parsed.query).get('v', [''])[0]
    else:
        match = re.fullmatch(r'/(?:shorts|embed)/([A-Za-z0-9_-]{11})/?', parsed.path)
        value = match[1] if match else ''
    return value if re.fullmatch(r'[A-Za-z0-9_-]{11}', value) else None


def stream_key(url):
    parts = urlparse(url)
    return urlunparse(parts._replace(query=urlencode([(k, v) for k, v in parse_qsl(parts.query) if k != 'range'])))


def selected_player_media_urls(value, selected_id):
    """Use only URLs already loaded by this exact visible player's response."""
    if not isinstance(value, dict) or (value.get('videoDetails') or {}).get('videoId') != selected_id:
        return set()
    data = value.get('streamingData') or {}
    urls = {data['sabrStreamingUrl']} if isinstance(data.get('sabrStreamingUrl'), str) else set()
    for row in [*data.get('formats', []), *data.get('adaptiveFormats', [])]:
        if isinstance(row, dict) and isinstance(row.get('url'), str):
            urls.add(row['url'])
    return urls


def player_media_identity(url):
    """Match an observed signed resource; never construct or request a media URL."""
    parts = urlparse(url)
    if (parts.scheme != 'https' or not (parts.hostname or '').endswith('.googlevideo.com')
            or parts.path != '/videoplayback'):
        return None
    query = parse_qs(parts.query)
    if not query.get('id') or not any(query.get(key) for key in ('sig', 'signature', 'lsig')):
        return None
    # Sparams names identify the signed resource. Player requests may append
    # changing transfer counters/ranges; those are not a new media identity.
    signed = set((query.get('sparams') or [''])[0].split(','))
    signed.update(('id', 'expire', 'ip', 'sig', 'signature', 'lsig', 'sparams', 'lsparams'))
    signed.update((query.get('lsparams') or [''])[0].split(','))
    return tuple((key, tuple(query.get(key, []))) for key in sorted(signed) if key)


def transfer_matches_selected_player(url, player_response, selected_id, *, page_url, ad=False):
    if ad or video_id(page_url) != selected_id:
        return False
    identity = player_media_identity(url)
    return bool(identity and any(player_media_identity(candidate) == identity
        for candidate in selected_player_media_urls(player_response, selected_id)))


def read_selected_player_context(page):
    return page.evaluate('''() => {
        const players = [...document.querySelectorAll('.html5-video-player')].filter(
            e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length));
        if (players.length !== 1) return {ad:true, response:null};
        const p = players[0];
        let response = null;
        try { response = typeof p.getPlayerResponse === 'function' ? p.getPlayerResponse() : null; } catch (_) {}
        return {ad:p.classList.contains('ad-showing'),
            response:response || window.ytInitialPlayerResponse || null};
    }''')


def final_buffer_observed(info):
    """Avoid repeatedly decoding every partial prefix while playback is filling."""
    return not info.get('ad', False) and bool(info.get('ended') or info.get('buffered_end', 0) >= info['duration'] - .25)


def publish_track(body, target, visible):
    """Publish only a duration/dimension-matching, fully decoded video track."""
    target = Path(target)
    staging = target.with_name(target.stem + '-verified-reception.mp4')
    if staging.exists() or target.exists():
        raise RuntimeError('Existing source file must be preserved.')
    try:
        if not publish_video(body, staging, visible['duration']):
            return False
        probe = subprocess.run([shutil.which('ffprobe') or 'ffprobe', '-v', 'error',
            '-show_entries', 'stream=codec_type,width,height', '-of', 'json', str(staging)],
            capture_output=True, text=True, check=True, timeout=30)
        streams = json.loads(probe.stdout).get('streams', [])
        videos = [s for s in streams if s.get('codec_type') == 'video']
        if len(videos) != 1 or (videos[0]['width'], videos[0]['height']) != (visible['width'], visible['height']):
            return False
        decoded = run_progress_command([shutil.which('ffmpeg') or 'ffmpeg', '-v', 'error', '-xerror',
            '-i', str(staging), '-map', '0:v:0', '-progress', 'pipe:1', '-nostats',
            '-f', 'null', '-'], idle_seconds=60)
        if decoded.returncode:
            return False
        progress = dict(line.split('=', 1) for line in decoded.stdout.splitlines() if '=' in line)
        decoded_duration = int(progress.get('out_time_us', 0)) / 1_000_000
        decoded_frames = int(progress.get('frame', 0))
        # Fragmented MP4's initialization can declare the FULL duration even
        # while only early fragments arrived. A successful FFmpeg exit alone
        # also accepts such an early EOF. Verify the actual decoded endpoint.
        if progress.get('progress') != 'end' or decoded_frames <= 0 or abs(decoded_duration - visible['duration']) > .25:
            return False
        staging.replace(target)
        return {'has_audio': any(s.get('codec_type') == 'audio' for s in streams),
                'full_decode_passed': True, 'decoded_video_duration':decoded_duration,
                'decoded_video_frames':decoded_frames}
    except (subprocess.SubprocessError, NoProgressTimeout, ValueError, KeyError):
        return False
    finally:
        staging.unlink(missing_ok=True)


def download(settings, url, target, max_bytes, deadline=None, diagnostics=None, *, visible_quality=None):
    from playwright.sync_api import sync_playwright
    from .browser_search import BrowserSearcher
    from .editing_adapter import _atomic_json

    stats = diagnostics if diagnostics is not None else {}
    stats.update(attempted=False, navigation_started=False)
    selected_id = video_id(url)
    if not selected_id:
        raise ValueError('A searched YouTube video detail URL is required.')
    target = Path(target)
    if target.exists():
        raise RuntimeError('Existing source file must be preserved.')
    target.parent.mkdir(parents=True, exist_ok=True)
    searcher = BrowserSearcher(replace(settings, source_browser_captcha_wait=0), target.parent)
    from .search_access import access_record, manual_required
    gate=access_record(settings.data_dir,'youtube')
    if not (gate.get('reason')=='captcha' and manual_required(gate)) and searcher._cooling_down('youtube'):
        raise RuntimeError('YouTube 접근 중지 또는 휴식 상태입니다.')
    if not endpoint(settings):
        raise RuntimeError('기존 수집용 Chrome이 연결되지 않았습니다. 새 브라우저로 대체하지 않습니다.')
    from .operation_progress import ProgressWatch, watch_browser_transfer
    watch = ProgressWatch(settings.source_download_idle_timeout, 'YouTube 영상 수신')
    stats.update(video_id=selected_id, completed=False, method='existing_browser_playback_responses',
        explicit_media_requests=0, media_responses=0, ump_responses=0, body_errors=0, verification_attempts=0,
        rights='unknown-check-before-reuse')
    ump, assemblies, rejected, fatal = BrowserUmpMedia(selected_id, max_bytes), {}, set(), []
    audit = {'provider': 'youtube', 'operation': 'selected source playback'}
    with browser_lease(settings), sync_playwright() as pw:
        context = attach_browser(pw, settings)
        pages = [p for p in context.pages if urlparse(p.url).hostname in ('www.youtube.com', 'youtube.com', 'm.youtube.com')]
        if len(pages) != 1:
            raise RuntimeError('기존 YouTube 탭을 하나로 지정해야 합니다. 새 탭은 만들지 않습니다.')
        page, playback, main_started = pages[0], {}, False
        selected_media = set()
        player_context = {'ad':True, 'response':None}
        def selected_transfer(src):
            return (not player_context.get('ad', True) and video_id(page.url) == selected_id
                and (src in selected_media or transfer_matches_selected_player(src, player_context.get('response'),
                    selected_id, page_url=page.url, ad=player_context.get('ad', True))))
        close_transfer = watch_browser_transfer(context, page, watch, selected_transfer,max_bytes=max_bytes,
            transfer_identity=lambda src:player_media_identity(src) or stream_key(src))
        if searcher._cooling_down('youtube',page=page):
            raise RuntimeError('YouTube 현재 화면의 인증 또는 요청 제한 때문에 영상 페이지를 열지 않습니다.')

        def receive(request):
            response = request.response()
            if not response:
                return
            host = urlparse(response.url).hostname or ''
            if host not in ('youtube.com', 'www.youtube.com', 'm.youtube.com') and not host.endswith('.googlevideo.com'):
                return
            if response.status == 429:
                searcher._block('youtube', audit, 'rate_limited', response)
                fatal.append('YouTube 요청 제한이 확인됐습니다.')
                return
            mime = response.headers.get('content-type', '').split(';')[0].lower()
            if response.status not in (200, 206) or mime not in ('application/vnd.yt-ump', 'video/mp4', 'application/mp4'):
                return
            try:
                if int(response.headers.get('content-length', 0)) > max_bytes:
                    raise ValueError('Media response exceeds byte limit.')
                body = response.body()
                if mime == 'application/vnd.yt-ump':
                    before_bytes = sum(len(part) for spans in ump.tracks.values() for part in spans.values())
                    ump.add(body)
                    if sum(len(part) for spans in ump.tracks.values() for part in spans.values()) > before_bytes:
                        selected_media.add(response.url)
                    stats['ump_responses'] += 1
                else:
                    key = stream_key(response.url)
                    if key not in assemblies and len(assemblies) >= 4:
                        return
                    assemblies.setdefault(key, MediaAssembly(max_bytes)).add(response.status, response.headers, body)
                    stats['media_responses'] += 1
            except ValueError as exc:
                fatal.append(str(exc))
            except Exception:
                stats['body_errors'] += 1

        page.on('requestfinished', receive)
        try:
            if searcher._check_block(page, 'youtube', audit):
                raise RuntimeError('현재 YouTube 페이지의 로그인·인증 확인이 필요합니다.')
            pace(settings, 'youtube')
            watch.reset()
            timeout = settings.source_browser_navigation_timeout * 1000
            if visible_quality is not None:
                # Explicit recovery of this exact source through its currently
                # open, visible quality menu. Never guess media URLs/formats.
                if video_id(page.url) != selected_id or visible_quality not in ('360p', '720p', '1080p HD'):
                    raise RuntimeError('기존 선택 영상의 보이는 화질 메뉴가 필요합니다.')
                stats['attempted'] = True
                page.locator('.ytp-settings-menu:visible').get_by_text(visible_quality, exact=True).click(timeout=timeout)
                stats['visible_quality_recovery'] = visible_quality
                response = None
            else:
                stats.update(attempted=True, navigation_started=True)
                response = (page.reload(wait_until='domcontentloaded', timeout=timeout) if video_id(page.url) == selected_id
                    else page.goto(url, wait_until='domcontentloaded', timeout=timeout))
            if searcher._check_block(page, 'youtube', audit, response):
                raise RuntimeError('YouTube 영상 페이지에서 인증 또는 요청 제한이 확인됐습니다.')
            while True:
                # Bind the FIRST still-in-flight UMP response through the exact
                # selected player's browser-loaded metadata, before body() or
                # requestfinished is available. Ads and older players cannot
                # renew its watch.
                player_context.update(read_selected_player_context(page))
                watch.check()
                if fatal:
                    raise RuntimeError(fatal[0])
                if video_id(page.url) != selected_id or searcher._check_block(page, 'youtube', audit):
                    raise RuntimeError('선택 영상 이탈 또는 인증 대기 상태입니다.')
                playback_errors = page.locator('.ytp-error[role="alert"]:visible').all_text_contents()
                if any(text.strip() for text in playback_errors):
                    stats['player_error'] = playback_errors[0].strip()[:300]
                    raise RuntimeError('YouTube 플레이어 재생 오류: ' + stats['player_error'])
                visible = page.locator('video').evaluate_all('els=>els.filter(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)).map(e=>({src:e.currentSrc||e.src,duration:Number.isFinite(e.duration)?e.duration:null,width:e.videoWidth,height:e.videoHeight,ready:e.readyState,time:e.currentTime,paused:e.paused,ended:e.ended,ad:!!e.closest(".html5-video-player")?.classList.contains("ad-showing"),buffered_end:e.buffered.length?e.buffered.end(e.buffered.length-1):0}))')
                if len(visible) == 1 and visible[0]['ready'] >= 2 and visible[0]['duration']:
                    info = visible[0]
                    if info.get('ad'):
                        stats['ad_observed'] = True
                        if not playback.get('ready'):
                            playback = start_visible_playback(page)
                        page.wait_for_timeout(500)
                        continue
                    selected_media.add(info['src'])
                    watch.observe('ump_bytes', sum(len(body) for spans in ump.tracks.values() for body in spans.values()))
                    for src, assembly in assemblies.items():
                        if src == stream_key(info['src']):
                            watch.observe(('covered', src), sum(b-a for a,b in assembly.ranges))
                    stats['visible_player'] = {k:v for k,v in info.items() if k != 'src'}
                    if not main_started:
                        original_muted = playback.get('original_muted')
                        # Watch pages may resume the previous failed position.
                        # Start the selected main video from its beginning so
                        # early media bytes can be received in this session.
                        playback = start_visible_playback(page, start_time=0)
                        stats['main_playback_requested_from_start'] = True
                        if original_muted is not None:
                            playback['original_muted'] = original_muted
                        main_started = playback.get('ready', False)
                    if not final_buffer_observed(info):
                        page.wait_for_timeout(500)
                        continue
                    candidates = [(track['body'], 'browser-ump') for track in ump.contiguous_tracks() if track['gap_free']]
                    direct = assemblies.get(stream_key(info['src'])) if not info['src'].startswith('blob:') else None
                    if direct and direct.result():
                        candidates.append((direct.result(), 'browser-mp4'))
                    for body, method in candidates:
                        digest = hashlib.sha256(body).hexdigest()
                        validation_key = (digest, info['duration'], info['width'], info['height'])
                        if validation_key in rejected:
                            continue
                        stats['verification_attempts'] += 1
                        verified = publish_track(body, target, info)
                        if verified:
                            stats.update(verified, completed=True, saved_bytes=len(body), sha256=digest,
                                media_method=method, ignored_other_video_headers=ump.ignored_other_video_headers)
                            return target
                        rejected.add(validation_key)
                page.wait_for_timeout(500)
            raise RuntimeError('표시된 YouTube 영상의 완전한 파일을 제한 시간 안에 확보하지 못했습니다.')
        except Exception as exc:
            stats['error'] = str(exc)[:300]
            raise
        finally:
            close_transfer()
            stats['ump_track_ranges'] = [
                {'itag': key[0], 'segments': len(spans),
                 'ranges': [[start, start + len(body)] for start, body in sorted(spans.items())]}
                for key, spans in ump.tracks.items()]
            if not stats['completed']:
                folder = target.parent / (target.stem + '-incomplete-reception')
                stats['diagnostic_tracks'] = []
                for track in ump.contiguous_tracks():
                    folder.mkdir(exist_ok=True)
                    digest = hashlib.sha256(track['body']).hexdigest()
                    path = folder / f"itag-{track['itag']}-{digest[:12]}.mp4"
                    if not path.exists():
                        path.write_bytes(track['body'])
                    stats['diagnostic_tracks'].append({'path': str(path), 'sha256': digest,
                        'gap_free_to_received_end_only': track['gap_free'], 'editing_eligible': False})
            page.remove_listener('requestfinished', receive)
            if playback.get('playing') and video_id(page.url) == selected_id:
                try:
                    page.locator('video').evaluate_all('(els, muted)=>{const v=els.filter(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length));if(v.length===1){v[0].pause();v[0].muted=muted;}}', playback['original_muted'])
                    stats['player_paused_after_reception'] = True
                except Exception:
                    stats['player_paused_after_reception'] = False
            _atomic_json(target.with_suffix('.reception.json'), stats)
