"""Inspect the user-named fallback in the existing collector profile."""
import json
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from hotpost.config import load_settings
from hotpost.source_browser_runtime import attach_browser,browser_lease,pace
from hotpost.search_access import challenge_on_page

s=load_settings()
with browser_lease(s),sync_playwright() as pw:
    c=attach_browser(pw,s)
    pages=[p for p in c.pages if urlparse(p.url).hostname=='tikvideo.app']
    p=pages[0] if len(pages)==1 else c.new_page()
    pace(s,'tikvideo',minimum=30)
    response=p.goto('https://tikvideo.app/ko',wait_until='domcontentloaded',timeout=30000)
    print(json.dumps({'page':p.url,'status':response.status if response else None,'challenge':challenge_on_page(p),
        'text':p.locator('body').inner_text()[:1000],
        'inputs':p.locator('input').evaluate_all('els=>els.map(e=>({type:e.type,placeholder:e.getAttribute("placeholder"),name:e.name,visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)}))'),
        'buttons':p.get_by_role('button').all_text_contents()},ensure_ascii=False))
