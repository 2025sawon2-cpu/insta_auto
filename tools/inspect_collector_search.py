"""Read current collector's visible search controls; no navigation."""
import json
import re
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from hotpost.config import load_settings
from hotpost.source_browser_runtime import attach_browser,browser_lease

s=load_settings()
with browser_lease(s),sync_playwright() as pw:
    context=attach_browser(pw,s)
    p=next(p for p in context.pages if urlparse(p.url).hostname=='www.tiktok.com')
    print(json.dumps({'page':p.url,'inputs':p.locator('input').evaluate_all('els=>els.map(e=>({type:e.type,name:e.name,placeholder:e.getAttribute("placeholder"),e2e:e.getAttribute("data-e2e"),visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)}))'),
        'body':p.locator('body').inner_text()[:900],
        'controls':p.get_by_text('mini envelope velcro stationery',exact=True).evaluate_all('els=>els.map(e=>({tag:e.tagName,role:e.getAttribute("role"),e2e:e.getAttribute("data-e2e"),html:e.parentElement.outerHTML.slice(0,2400),visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)}))')},ensure_ascii=False))
