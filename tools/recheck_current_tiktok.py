"""Read the existing collector TikTok page without navigation or authentication."""
import json
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json
from hotpost.search_access import challenge_on_page, login_wall_on_page, access_record
from hotpost.source_browser_runtime import attach_browser, browser_lease, existing_page


def main():
    settings = load_settings()
    marker = settings.source_browser_profile_dir / 'hotpost-live-session-v1'
    if not marker.exists():
        raise RuntimeError('Existing live-session marker missing; no session migration attempted.')
    root = Path('data/tiktok-current-recheck') / datetime.now().strftime('%Y%m%d-%H%M%S')
    root.mkdir(parents=True, exist_ok=False)
    with browser_lease(settings), sync_playwright() as pw:
        context = attach_browser(pw, settings)
        page = existing_page(context, settings, 'tiktok')
        state = {
            'checked_at': datetime.now().astimezone().isoformat(),
            'url': page.url,
            'captcha_visible': challenge_on_page(page),
            'login_wall_visible': login_wall_on_page(page, 'tiktok'),
            'visible_iframes': page.locator('iframe:visible').count(),
            'visible_videos': page.locator('video:visible').count(),
            'visible_video_links': page.locator('a[href*="/video/"]:visible').count(),
            'visible_text': page.locator('body').inner_text()[:1200],
            'access_record': access_record(settings.data_dir, 'tiktok'),
            'navigation_performed': False,
        }
        page.screenshot(path=str(root / 'page.png'))
        _atomic_json(root / 'state.json', state)
    print(json.dumps({'root': str(root), **state}, ensure_ascii=False))


if __name__ == '__main__':
    main()
