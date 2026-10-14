"""One bounded live check of the existing collector; preserve tabs and sessions."""
import json
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from hotpost.browser_search import BrowserSearcher
from hotpost.config import load_settings
from hotpost.search_access import access_record, manual_required
from hotpost.source_browser_runtime import attach_browser, browser_lease, endpoint
from hotpost.source_search.readiness import readiness_blocked
from hotpost.source_search.tiktok_results import search_response_candidates


def main():
    settings = replace(load_settings(), source_browser_captcha_wait=0)
    root = settings.data_dir / 'tiktok-diagnostics-20261011'
    root.mkdir(parents=True, exist_ok=True)
    report = {'query': 'bed sleeping tent', 'started_at': time.time(), 'responses': []}
    if manual_required(access_record(settings.data_dir, 'tiktok')) or readiness_blocked(settings.data_dir, 'tiktok'):
        report['status'] = 'existing_access_gate'
    elif not endpoint(settings):
        report['status'] = 'existing_browser_not_connected'
    else:
        with browser_lease(settings), sync_playwright() as pw:
            context = attach_browser(pw, settings)
            searcher = BrowserSearcher(settings, root)
            searcher.progress = lambda message: print(message, flush=True)
            searcher.deadline = time.monotonic() + 110
            pages = [page for page in context.pages if (urlparse(page.url).hostname or '') in ('www.tiktok.com', 'tiktok.com')]
            if len(pages) != 1:
                raise RuntimeError('기존 TikTok 탭을 하나로 지정해야 합니다. 새 탭은 만들지 않습니다.')
            page = pages[0]
            report['session'] = 'existing collector Chrome and existing TikTok tab'
            hits = []

            def observe(response):
                if '/api/search/' not in response.url:
                    return
                row = {'path': response.url.split('?', 1)[0], 'status': response.status}
                try:
                    body = response.json()
                    row['status_code'] = body.get('status_code') if isinstance(body, dict) else None
                    row['candidates'] = search_response_candidates(response.url, body, report['query'])
                    hits.extend(row['candidates'])
                except Exception as exc:
                    row['parse_error'] = type(exc).__name__
                report['responses'].append(row)

            page.on('response', observe)
            audit = {'provider': 'tiktok', 'query': report['query'], 'status': 'started'}
            began = time.monotonic()
            try:
                report['submitted'] = searcher._submit_search(page, 'tiktok', report['query'], audit)
                report['status'] = 'submitted' if report['submitted'] else 'access_stopped'
                if report['submitted']:
                    report['results'] = searcher._wait_platform_results(page, 'tiktok', report['query'], audit, hits)
            except Exception as exc:
                report.update(status='failed', error_type=type(exc).__name__, error=str(exc)[:2000])
            finally:
                report['seconds'] = round(time.monotonic() - began, 2)
                report['audit'] = audit
                report['page_url'] = page.url
                report['notes'] = searcher.notes
                try:
                    report['visible_text'] = page.locator('body').inner_text(timeout=5000)[:1600]
                    report['inputs'] = page.locator('input').evaluate_all('els => els.map(e => ({type:e.type, placeholder:e.getAttribute("placeholder"), name:e.name, data_e2e:e.getAttribute("data-e2e"), visible:!!(e.offsetWidth || e.offsetHeight || e.getClientRects().length)}))')
                    report['search_controls'] = page.get_by_text('Search', exact=True).evaluate_all('els => els.map(e => ({tag:e.tagName,role:e.getAttribute("role"),aria:e.getAttribute("aria-label"),visible:!!(e.offsetWidth || e.offsetHeight || e.getClientRects().length)}))')
                    page.screenshot(path=str(root / 'search-state.png'), full_page=False, timeout=5000)
                except Exception as exc:
                    report['snapshot_error'] = str(exc)[:300]
                page.remove_listener('response', observe)
    previous = root / 'report.json'
    if previous.exists():
        (root / f'report-before-{time.time_ns()}.json').write_bytes(previous.read_bytes())
    previous.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
