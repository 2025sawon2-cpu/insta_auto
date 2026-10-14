"""One observed Bilibili clip: receive the current player's MP4 byte ranges.

Analysis-only original, not an editing approval or redistribution permission.
Uses the existing collector tab; never requests unobserved CDN URLs or cookies.
"""
import json
import argparse
import os
from pathlib import Path
import time
from urllib.parse import urlparse
from dataclasses import replace
from playwright.sync_api import sync_playwright
from hotpost.config import load_settings
from hotpost.browser_search import BrowserSearcher
from hotpost.source_browser_runtime import attach_browser, browser_lease, pace
from hotpost.tiktok_download import MediaAssembly, publish_video
from hotpost.editing_adapter import _atomic_json
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file


def main():
    parser = argparse.ArgumentParser()
    folders = {'BV1jwieB2Esb': 'bilibili-official-2230',
               'BV1E8iTBkEy3': 'bilibili-official-mini',
               'BV1KVNHeGEpS': 'bilibili-official-magnetic-kit'}
    parser.add_argument('--video', choices=list(folders), default='BV1jwieB2Esb')
    args = parser.parse_args()
    video_id = args.video
    folder = folders[video_id]
    root = Path('data/daily-rework-20261011/DeSoiZvyyqj') / folder
    target = root / (video_id + '.mp4')
    if target.exists():
        raise RuntimeError('Existing original retained; do not redownload.')
    settings = replace(load_settings(), source_browser_captcha_wait=0)
    bins = next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']
    searcher = BrowserSearcher(settings, root)
    stats = {'video_id': video_id, 'partial_responses': 0, 'media_responses': 0,
             'body_errors': 0, 'method': 'existing_browser_playback_ranges',
             'rights': 'permission_required_before_redistribution', 'editing_eligible': False}
    streams, fatal = {}, []
    with browser_lease(settings), sync_playwright() as pw:
        context = attach_browser(pw, settings)
        pages = [p for p in context.pages if urlparse(p.url).hostname == 'www.bilibili.com']
        if len(pages) != 1:
            raise RuntimeError('Exactly the already observed Bilibili player is required.')
        page = pages[0]
        audit = {'provider': 'bilibili'}
        if searcher._cooling_down('bilibili') or searcher._check_block(page, 'bilibili', audit):
            raise RuntimeError('Authentication/cooldown requires stopping.')

        def receive(request):
            response = request.response()
            if not response:
                return
            if response.status == 429:
                searcher._block('bilibili', audit, 'rate_limited', response)
                fatal.append('Rate limited; stop.')
                return
            headers = response.headers
            if headers.get('content-type', '').split(';')[0].lower() not in ('video/mp4', 'application/mp4'):
                return
            stats['media_responses'] += 1
            stats['partial_responses'] += int(response.status == 206)
            if response.status not in (200, 206):
                return
            try:
                assembly = streams.setdefault(response.url, MediaAssembly(80 * 1024 * 1024))
                assembly.add(response.status, headers, response.body())
            except ValueError as exc:
                fatal.append(str(exc))
            except Exception:
                stats['body_errors'] += 1

        page.on('requestfinished', receive)
        try:
            pace(settings, 'bilibili', print)
            observed = json.loads((root / 'visible-inspection.json').read_text('utf-8'))['url']
            expected_path = '/video/' + video_id + '/'
            if urlparse(observed).path != expected_path:
                raise RuntimeError('Saved visible source does not match the requested original.')
            response = (page.reload(wait_until='domcontentloaded', timeout=30000)
                        if urlparse(page.url).path == expected_path else
                        page.goto(observed, wait_until='domcontentloaded', timeout=30000))
            deadline = time.monotonic() + 55
            if searcher._check_block(page, 'bilibili', audit, response):
                raise RuntimeError('Authentication required after reload.')
            while time.monotonic() < deadline:
                if fatal:
                    raise RuntimeError(fatal[0])
                if urlparse(page.url).path != expected_path:
                    raise RuntimeError('Player moved to another clip; stop.')
                if searcher._check_block(page, 'bilibili', audit):
                    raise RuntimeError('Authentication required during playback.')
                # Stop Bilibili's next-video navigation, not the current video.
                # This switch was inspected in the existing page before use.
                autoplay = page.locator('.switch-btn.on')
                if autoplay.count() == 1 and autoplay.is_visible():
                    autoplay.click()
                    stats['autoplay_next_disabled'] = True
                visible = page.locator('video').evaluate_all('els=>els.filter(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)).map(e=>({duration:e.duration,width:e.videoWidth,height:e.videoHeight,paused:e.paused,time:e.currentTime,ready:e.readyState}))')
                if len(visible) == 1 and visible[0]['ready'] >= 2:
                    info = visible[0]
                    stats['visible_player'] = info
                    if info['paused']:
                        page.get_by_role('button', name='播放/暂停', exact=True).click()
                    for assembly in streams.values():
                        body = assembly.result()
                        if not body or not publish_video(body, target, info['duration']):
                            continue
                        meta = probe_video(target)
                        if meta['width'] != info['width'] or meta['height'] != info['height']:
                            target.unlink()
                            continue
                        stats.update(path=str(target.resolve()), sha256=sha256_file(target),
                                     video_meta=meta, received_bytes=len(body), audit=audit,
                                     observed_stream_ranges=assembly.ranges, completed=True)
                        _atomic_json(root / 'range-reception.json', stats)
                        print(json.dumps(stats, ensure_ascii=False), flush=True)
                        return
                page.wait_for_timeout(1000)
            raise RuntimeError('Visible playback did not produce a complete matching MP4 in the bounded wait.')
        except Exception as exc:
            stats.update(error=str(exc), completed=False, audit=audit,
                         received_streams=[{'total': a.total, 'ranges': a.ranges} for a in streams.values()])
            _atomic_json(root / 'range-reception.json', stats)
            raise
        finally:
            page.remove_listener('requestfinished', receive)


if __name__ == '__main__':
    main()
