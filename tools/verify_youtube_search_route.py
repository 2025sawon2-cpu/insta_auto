"""One real production search in the existing collector, with tab inventory."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import time
from playwright.sync_api import sync_playwright
from hotpost.browser_search import browser_search
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json
from hotpost.source_browser_runtime import attach_browser, browser_lease


def inventory(settings):
    with browser_lease(settings), sync_playwright() as pw:
        context = attach_browser(pw, settings)
        rows = []
        for page in context.pages:
            session = context.new_cdp_session(page)
            try:
                identity = session.send('Target.getTargetInfo')['targetInfo']['targetId']
            finally:
                session.detach()
            rows.append({'target_id':identity, 'url':page.url})
        return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--code', required=True)
    parser.add_argument('--query', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.code):
        raise ValueError('Valid product code required')
    root = Path('data/daily-rework-20261011') / args.code / 'youtube-exact-product' / hashlib.sha256(args.query.encode()).hexdigest()[:12]
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'visible-results.json').exists():
        raise RuntimeError('Existing evidence retained; choose a new supported search rather than overwrite')
    settings = replace(load_settings(), source_browser_captcha_wait=0, source_queries_per_platform=1,
                       source_candidates_per_platform=8)
    before = inventory(settings)
    result = browser_search(settings, [], [args.query], 8, root,
                            routes=['youtube'], progress=lambda message:print(message, flush=True))
    after = inventory(settings)
    retained = {p['target_id'] for p in before} == {p['target_id'] for p in after}
    record = {'query':args.query, 'links':result['candidates'], 'audit':result.get('searches', []),
        'notes':result.get('notes', []), 'blocked':any(r.get('status') in
            {'captcha','rate_limited','login_required','verification_required','cooldown'} for r in result.get('searches', [])),
        'time':time.time(), 'downloaded':0, 'production_entry':'hotpost.browser_search.browser_search',
        'candidate_scope':'viewport-visible cards also bound to this query\'s observed browser search response',
        'before_tabs':before, 'after_tabs':after, 'same_tab_inventory':retained}
    _atomic_json(root / 'visible-results.json', record)
    print(json.dumps(record, ensure_ascii=False), flush=True)
    if not retained or not result['candidates']:
        raise RuntimeError('Production search did not yield verified visible candidates; see saved evidence')


if __name__ == '__main__':
    main()
