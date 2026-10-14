import json,time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from hotpost.config import load_settings
from hotpost.browser_search import BrowserSearcher
from hotpost.source_browser_runtime import browser_lease,attach_browser
from hotpost.source_search.tiktok_results import search_response_candidates
from tools.rework_tiktok_batch import ROOT,save
s=load_settings();code='DeRFXHpEwck';q='迷你 魔术贴 文件袋';ledger=ROOT/code/'discovery.json';d=json.loads(ledger.read_text('utf-8'));hits=[]
with browser_lease(s),sync_playwright() as pw:
 c=attach_browser(pw,s);p=next(p for p in c.pages if urlparse(p.url).hostname=='www.tiktok.com');searcher=BrowserSearcher(s,ROOT/code);searcher.deadline=time.monotonic()+110
 audit={'query':q};assert not searcher._check_block(p,'tiktok',audit);searcher._pace('tiktok',reserve=45);searcher._audit_request(audit,'search_input')
 p.get_by_text('mini envelope velcro stationery',exact=True).filter(visible=True).click()
 field=p.locator('input[data-e2e="search-user-input"]:visible').first;field.fill('');field.press_sequentially(q,delay=140);p.wait_for_timeout(800)
 print('Before submit',json.dumps(p.locator('input').evaluate_all('els=>els.map(e=>({value:e.value,visible:!!e.offsetHeight}))'),ensure_ascii=False),flush=True)
 def receive(r):
  if '/api/search/' in r.url:
   if r.status==429:searcher._block('tiktok',{},'rate_limited',r)
   try:hits.extend(search_response_candidates(r.url,r.json(),q))
   except Exception:pass
 p.on('response',receive);p.locator('button[data-e2e="search-box-button"]:visible').click()
 searcher._wait_platform_results(p,'tiktok',q,audit,hits);seen={x['url'] for x in d['candidates']}
 for x in hits:
  if x['url'] not in seen:x.update(selected=False,rights='unknown-check-before-reuse');d['candidates'].append(x);seen.add(x['url'])
 print(json.dumps({'url':p.url,'hits':hits,'audit':audit},ensure_ascii=False),flush=True)
 d['queries'].append({'query':q,'results':len(hits),'audit':audit,'time':time.time()});save(ledger,d)
