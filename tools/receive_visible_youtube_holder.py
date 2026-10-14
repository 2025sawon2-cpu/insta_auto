"""Inspect one observed Shorts result and receive only its player responses."""
import json
import argparse
import os
import re
from pathlib import Path
import time
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from dataclasses import replace
from playwright.sync_api import sync_playwright
from hotpost.config import load_settings
from hotpost.browser_search import BrowserSearcher
from hotpost.source_browser_runtime import attach_browser, browser_lease, pace
from hotpost.tiktok_download import MediaAssembly, publish_video, start_visible_playback
from hotpost.editing_adapter import _atomic_json as save
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file

VIDEO = 'xxQiZmoYNTE'
ROOT = Path('data/daily-rework-20261011/DeRFXHpEwck/youtube-photo-case-' + VIDEO).resolve()


def main():
    global VIDEO, ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument('--video', default=VIDEO)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', args.video):
        raise ValueError('A visible Shorts video ID is required.')
    VIDEO = args.video
    if VIDEO != 'xxQiZmoYNTE':
        ROOT = ROOT.parent / ('youtube-observed-' + VIDEO)
    ROOT.mkdir(parents=True, exist_ok=True)
    target = ROOT / (VIDEO + '.mp4')
    if target.exists():
        print('Previously received original retained.', flush=True)
        return
    settings = replace(load_settings(), source_browser_captcha_wait=0)
    bins = next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']
    searcher = BrowserSearcher(settings, ROOT)
    audit = {'provider': 'youtube', 'operation': 'one observed visible Shorts card'}
    report = {'video_id': VIDEO, 'completed': False, 'editing_eligible': False,
              'rights': 'unknown-check-before-reuse', 'method': 'existing_browser_playback_responses',
              'body_errors': 0, 'media_responses': 0, 'partial_responses': 0}
    prior = ROOT / 'reception.json'
    if prior.exists():
        prior.rename(ROOT / f'reception-before-{time.time_ns()}.json')
    streams, fatal, samples = {}, [], []
    with browser_lease(settings), sync_playwright() as pw:
        context = attach_browser(pw, settings)
        pages = [p for p in context.pages if urlparse(p.url).hostname == 'www.youtube.com']
        if len(pages) != 1:
            raise RuntimeError('One existing collector YouTube tab required.')
        page = pages[0]
        if searcher._cooling_down('youtube') or searcher._check_block(page, 'youtube', audit):
            raise RuntimeError('Provider access paused.')
        # Require the actual result already present in the current page.
        card = page.locator(f'a[href="/shorts/{VIDEO}"]:visible').first
        already_visible = urlparse(page.url).path == '/shorts/' + VIDEO
        if not already_visible and not card.count():
            raise RuntimeError('Expected visible source card is absent; no guessed navigation.')
        report['observed_result_text'] = card.inner_text() if card.count() else page.title()

        def observe_response(response):
            if (urlparse(response.url).hostname or '').endswith('.googlevideo.com'):
                headers = response.headers
                report.setdefault('observed_media_headers', []).append({
                    'status': response.status, 'mime': headers.get('content-type'),
                    'length': headers.get('content-length'), 'range': headers.get('content-range')})

        def receive(request):
            response = request.response()
            if not response:
                return
            if response.status == 429:
                searcher._block('youtube', audit, 'rate_limited', response)
                fatal.append('Rate limited; stop.')
                return
            headers = response.headers
            if headers.get('content-type', '').split(';')[0].lower() == 'application/vnd.yt-ump':
                try:
                    body = response.body()
                    if 0 < len(body) <= 80 * 1024 * 1024:
                        digest = __import__('hashlib').sha256(body).hexdigest()
                        packet = ROOT / 'ump-responses' / (digest + '.ump')
                        packet.parent.mkdir(exist_ok=True)
                        packet.write_bytes(body)
                        report.setdefault('ump_bodies', []).append({'path': str(packet), 'size': len(body),
                            'sha256': digest, 'status': response.status})
                except Exception:
                    report['body_errors'] += 1
                return
            if headers.get('content-type', '').split(';')[0].lower() not in ('video/mp4', 'application/mp4'):
                return
            report['media_responses'] += 1
            report['partial_responses'] += int(response.status == 206)
            # Only the range varies; do not merge different codec/version URLs.
            parts = urlparse(response.url)
            key = urlunparse(parts._replace(query=urlencode([(k, v) for k, v in parse_qsl(parts.query) if k != 'range'])))
            try:
                streams.setdefault(key, MediaAssembly(80 * 1024 * 1024)).add(response.status, headers, response.body())
            except ValueError as exc:
                fatal.append(str(exc))
            except Exception:
                report['body_errors'] += 1

        page.on('requestfinished', receive)
        page.on('response', observe_response)
        try:
            pace(settings, 'youtube', lambda msg: print(msg, flush=True))
            if already_visible:
                page.reload(wait_until='domcontentloaded', timeout=30000)
            else:
                card.click()
            page.wait_for_url('**/shorts/' + VIDEO, timeout=30000)
            deadline = time.monotonic() + 50
            started = time.monotonic()
            while time.monotonic() < deadline:
                if fatal:
                    raise RuntimeError(fatal[0])
                if urlparse(page.url).path != '/shorts/' + VIDEO:
                    raise RuntimeError('Player moved to another video; stop.')
                if searcher._check_block(page, 'youtube', audit):
                    raise RuntimeError('Authentication required during playback.')
                visible = page.locator('video').evaluate_all('els=>els.filter(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)).map(e=>({duration:e.duration,width:e.videoWidth,height:e.videoHeight,paused:e.paused,time:e.currentTime,ready:e.readyState}))')
                if len(visible) == 1 and visible[0]['ready'] >= 2:
                    info = visible[0]
                    report['visible_player'] = info
                    if info['paused']:
                        start_visible_playback(page)
                    elapsed = time.monotonic() - started
                    if not samples or elapsed > len(samples) * 12:
                        image = ROOT / f'visible-{len(samples)}.png'
                        try:
                            page.screenshot(path=str(image), timeout=4000)
                            samples.append({'path': str(image), 'player_time': info['time']})
                        except Exception as exc:
                            samples.append({'player_time': info['time'], 'capture_error': str(exc)[:200]})
                    for assembly in streams.values():
                        body = assembly.result()
                        if not body or not publish_video(body, target, info['duration']):
                            continue
                        meta = probe_video(target)
                        if (meta['width'], meta['height']) != (info['width'], info['height']):
                            target.unlink()
                            continue
                        report.update(completed=True, path=str(target), sha256=sha256_file(target),
                                      video_meta=meta, received_bytes=len(body), observed_ranges=assembly.ranges)
                        return
                page.wait_for_timeout(1000)
            report['error'] = 'Player responses did not yield a complete matching MP4 in the bounded wait.'
        except Exception as exc:
            report['error'] = str(exc)
            raise
        finally:
            page.remove_listener('requestfinished', receive)
            page.remove_listener('response', observe_response)
            report.update(url=page.url, title=page.title(), body=page.locator('body').inner_text()[:10000],
                          samples=samples, audit=audit, time=time.time(), tabs=len(context.pages),
                          received_streams=[{'total': a.total, 'ranges': a.ranges} for a in streams.values()])
            save(ROOT / 'reception.json', report)
            print(json.dumps({k:v for k,v in report.items() if k!='body'}, ensure_ascii=False), flush=True)
            if report.get('ump_bodies'):
                from tools.assemble_visible_youtube_holder import assemble
                assembled = assemble(ROOT)
                report['ump_assembly_completed'] = assembled['completed']
                save(ROOT / 'reception.json', report)


if __name__ == '__main__':
    main()
