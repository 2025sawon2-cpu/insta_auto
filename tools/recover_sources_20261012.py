"""Recovery uses the user's existing browser and bounded, serialized downloads."""
import argparse,json,subprocess,time,shutil
from pathlib import Path
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json
from hotpost.source_quality import sha256_file
from hotpost.source_finder import probe_video
from hotpost.source_browser_runtime import BrowserBusy,browser_lease,attach_browser,existing_page
from hotpost.search_access import challenge_on_page,login_wall_on_page,request_manual_recheck,access_record
from playwright.sync_api import sync_playwright

ROOT=Path('data/source-recovery-20261012-v1').resolve()
def read(p):return json.loads(p.read_text('utf-8'))
def folder(code):
    p=ROOT/code;p.mkdir(exist_ok=True);return p

def recheck():
    s=load_settings();before=access_record(s.data_dir,'tiktok')
    with browser_lease(s),sync_playwright() as pw:
        context=attach_browser(pw,s);page=existing_page(context,s,'tiktok')
        assert not challenge_on_page(page),'A visible challenge requires the user; do not bypass'
        assert not login_wall_on_page(page,'tiktok')
        links=page.locator('a[href*="/video/"]:visible').count();assert links>0
        page.screenshot(path=str(ROOT/'tiktok-explicit-retry-current.png'))
        _atomic_json(ROOT/'tiktok-explicit-retry.json',{'authorization':'User requested investigate and retry source acquisition','at':time.time(),'current_page':page.url,'visible_video_links':links,'visible_challenge':False,'before':before})
        request_manual_recheck(s.data_dir,'tiktok')
    print('Existing TikTok page: visible results, no visible challenge; one explicit retry authorized',flush=True)

def visible(code):
    s=load_settings();out=folder(code)
    with browser_lease(s),sync_playwright() as pw:
        page=existing_page(attach_browser(pw,s),s,'tiktok')
        assert not challenge_on_page(page) and not login_wall_on_page(page,'tiktok')
        items=page.locator('a[href*="/video/"]:visible').evaluate_all('els => els.map(e=>({url:e.href,title:e.innerText}))')
        unique={}
        for row in items:unique.setdefault(row['url'].split('?')[0],row)
        rows=[dict(row,url=url,observed_from=page.url) for url,row in unique.items()]
    _atomic_json(out/'ledger.json',{'candidates':rows,'method':'actual visible links in existing TikTok search page','at':time.time()})
    print(code,len(rows),'visible candidates',flush=True)
    for i,row in enumerate(rows):print(i,row['url'],row['title'][:100],flush=True)

def search(code,query):
    from hotpost.browser_search import browser_search
    out=folder(code);result=browser_search(load_settings(),[],[query],12,out/'browser-debug',routes=['tiktok'],progress=lambda m:print(m,flush=True))
    _atomic_json(out/('search-'+str(time.time_ns())+'.json'),result)
    old=read(out/'ledger.json') if (out/'ledger.json').exists() else {'candidates':[]}
    seen={c['url'] for c in old['candidates']}
    for row in result['candidates']:
        if row['url'] not in seen:old['candidates'].append(row);seen.add(row['url'])
    _atomic_json(out/'ledger.json',old)
    print(code,'candidates',len(old['candidates']),[(a.get('status'),a.get('candidates')) for a in result.get('searches',[])],flush=True)

def download(code,index):
    from hotpost.tikvideo_download import with_fallback
    out=folder(code);ledger=read(out/'ledger.json');row=ledger['candidates'][index]
    if not row.get('path'):
        assert not row.get('attempted'),'Failure receipt preserved; investigate before another attempt'
        row['attempted']=True;row['attempted_at']=time.time();_atomic_json(out/'ledger.json',ledger)
        target=out/(row['url'].split('?')[0].rstrip('/').split('/')[-1]+'.mp4');diagnostics={}
        try:
            path=with_fallback(load_settings(),row['url'],target,80*1024*1024,deadline=time.monotonic()+330,diagnostics=diagnostics)
            row.update(path=str(path.resolve()),sha256=sha256_file(path),video_meta=probe_video(path))
        except BrowserBusy as exc:
            row.setdefault('not_attempted_history',[]).append({'at':time.time(),
                'reason':'browser_busy','message':str(exc),'platform_request_performed':False})
            row.update(attempted=False,not_attempted_reason='browser_busy')
            print(code,index,'not attempted: existing Chrome is in use; no platform request performed',flush=True)
            return
        except Exception as exc:row['error']=str(exc);raise
        finally:row['diagnostics']=diagnostics;_atomic_json(out/'ledger.json',ledger)
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',row['path'],'-f','null','-'],check=True,capture_output=True)
    duration=row['video_meta']['duration'];contact=out/(str(index)+'-contact.jpg')
    subprocess.run(['ffmpeg','-v','error','-y','-i',row['path'],'-vf',f'fps=16/{duration},scale=200:356:force_original_aspect_ratio=decrease,pad=200:356:(ow-iw)/2:(oh-ih)/2,tile=4x4','-frames:v','1',str(contact)],check=True,capture_output=True)
    row['full_decode_passed']=True;row['contact_path']=str(contact);_atomic_json(out/'ledger.json',ledger)
    print(code,index,row['video_meta'],str(contact),flush=True)

def hints(code,indices):
    """Copies keep network receipts and enter the standard visual review path."""
    s=load_settings();out=folder(code);ledger=read(out/'ledger.json')
    target_dir=s.source_dir/('recovery-20261012-'+code)/'videos';target_dir.mkdir(parents=True,exist_ok=True)
    path=s.source_dir/'source-hints.json';saved=read(path) if path.exists() else {};rows=[]
    for index in indices:
        row=ledger['candidates'][index];assert row.get('full_decode_passed')
        source=Path(row['path']);assert sha256_file(source)==row['sha256'];target=target_dir/source.name
        if not target.exists():shutil.copy2(source,target)
        assert sha256_file(target)==row['sha256']
        rows.append({'url':row['url'],'title':row.get('title',''),'query':'实际产品使用 / 실제 제품 사용 동작','cached_file':str(target)})
    saved[code]=rows;_atomic_json(path,saved);_atomic_json(out/'published-hints.json',rows)
    print(code,len(rows),'received files published to standard source review',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['recheck','visible','search','download','hints']);parser.add_argument('--code');parser.add_argument('--query');parser.add_argument('--index',type=int,default=0);parser.add_argument('--indices',type=int,nargs='+');a=parser.parse_args()
    if a.action=='recheck':recheck()
    elif a.action=='search':search(a.code,a.query)
    elif a.action=='download':download(a.code,a.index)
    elif a.action=='hints':hints(a.code,a.indices)
    else:visible(a.code)
