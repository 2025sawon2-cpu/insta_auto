"""Serialize missing-product research after the current Chrome job finishes."""
import argparse,json,time
from pathlib import Path
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.editing_adapter import _atomic_json
from recover_sources_20261012 import search

ROOT=Path('data/source-recovery-20261012-v1').resolve()
REQUESTS={'initial':[
    ('DeVKHqHSJcG','シリコーン お玉 計量 立つ'),
    ('DeVKt3UyHyA','5 in 1 magnetic makeup brush cleaning case'),
    ('DeWQJJuTUNw','dust bag snap frame pouch tutorial'),
], 'remaining':[
    ('DeVII63TEmt','hidden pocket travel hoodie passport'),
    ('DeVSMKKTpVq','モンベル 防寒 ブーツ'),
    ('DeWVLYMSVzY','Transparent Sound speaker driver movement'),
    ('DeWm2yMRffK','고구마 치즈빵 밀가루 없이'),
]}

def main():
    studio=Studio(load_settings(),workers=False)
    parser=argparse.ArgumentParser();parser.add_argument('--batch',choices=REQUESTS,default='initial');args=parser.parse_args()
    waiting='job-3a3b66ea72d244e9';previous=None
    while True:
        with studio.store.connect() as db:
            row=db.execute('select status from jobs where id=?',(waiting,)).fetchone()
        status=row['status'] if row else 'missing'
        if status!=previous:print('Existing Danton job:',waiting,status,flush=True);previous=status
        if status not in ('running','queued'):break
        time.sleep(5)
    receipts=[]
    for code,query in REQUESTS[args.batch]:
        print('Next grounded product search:',code,query,flush=True)
        search(code,query)
        files=sorted((ROOT/code).glob('search-*.json'),key=lambda p:p.stat().st_mtime)
        result=json.loads(files[-1].read_text('utf-8'))
        receipts.append({'code':code,'query':query,'at':time.time(),'receipt':str(files[-1]),
                         'searches':result.get('searches',[])})
        _atomic_json(ROOT/('missing-products-search-batch-'+args.batch+'.json'),receipts)
        # No repeated calls when the current page actually has an auth challenge.
        if any(x.get('reason') in ('captcha','login_required') or
               x.get('status')=='auth_blocked' for x in result.get('searches',[])):
            print('Actual auth blocker; stop this batch and recheck current page before a later attempt',flush=True)
            break
    print('Grounded search batch complete; downloaded footage still needs separate review',flush=True)

if __name__=='__main__':main()
