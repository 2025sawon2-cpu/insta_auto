"""Read-only timeline comparison for the user's seven-output revision review."""
import json
import hashlib
from pathlib import Path
from hotpost.config import load_settings
from hotpost.studio import Studio

ROOT=Path('data/quality-scope-audit-20261011-v1')
def read(p): return json.loads(Path(p).read_text('utf-8'))
def summary(path):
    p=read(path); sources={s['id']:s for s in p['sources']};shots={s['id']:s for s in p['shots']}
    uses={};screen={};parents={};clips=set()
    for b in p['beats']:
        sh=shots[b['selected_shot_id']];s=sources[sh['source_id']]
        key=s.get('original_sha256') or s['sha256'];offset=s.get('original_interval',{}).get('start',0)
        start=offset+b['source_start'];end=offset+b['source_end']
        uses.setdefault(key,[]).append((start,end));screen[key]=screen.get(key,0)+b['end']-b['start'];clips.add(sh['id'])
        parents[key]={'provider':s.get('provider'),'url':s.get('url') or s.get('origin_url'),'path':s.get('original_path') or s['path']}
    unique=0;total=0
    for intervals in uses.values():
        total+=sum(e-s for s,e in intervals); merged=[]
        for s,e in sorted(intervals):
            if merged and s<=merged[-1][1]:merged[-1][1]=max(e,merged[-1][1])
            else:merged.append([s,e])
        unique+=sum(e-s for s,e in merged)
    return {'duration':p['duration'],'parent_files':len(parents),'tiktok_used_files':sum(x['provider']=='tiktok' for x in parents.values()),
        'action_clips':len(clips),'repeated_source_seconds':round(total-unique,3),'largest_source_share':round(max(screen.values())/p['duration']*100,1),
        'parents':parents,'script':p.get('script_text'),'cover':p.get('cover_spec',{}).get('lines'),'plan_path':str(path)}
def main():
    studio=Studio(load_settings(),workers=False);out=[]
    for row in read(ROOT/'completion-audit.json')['seven_current_outputs']:
        state=studio.store.get(row['task_id']);versions=[]
        # Earlier preserved baseline snapshots may contain edits preceding the live store history.
        seen=set()
        for edit in state['edits']:
            path=Path(edit['plan_path'])
            if path.exists() and str(path) not in seen:
                versions.append({'id':edit['id'],**summary(path)});seen.add(str(path))
        early=Path('data/daily-rework-20261011')/row['code']/'final/timeline.json'
        if early.exists() and str(early.resolve()) not in seen:
            versions.insert(0,{'id':'daily-rework-initial-preserved',**summary(early)})
        downloaded={}
        ledger_roots=['tiktok-rework-20261011','tiktok-quality-20261011-v2','daily-rework-20261011','a7-receipt-review-20261011-v6','folder-phone-review-20261011-v8']
        for base in ledger_roots:
            ledger=Path('data')/base/row['code']/'discovery.json'
            if not ledger.exists():continue
            for candidate in read(ledger).get('candidates',[]):
                url=candidate.get('url','');path=Path(candidate.get('path') or '__missing__')
                if 'tiktok.com/' in url and path.is_file():
                    digest=hashlib.sha256(path.read_bytes()).hexdigest()
                    downloaded[digest]={'url':url,'path':str(path)}
        out.append({'code':row['code'],'versions':versions,'downloaded_tiktok_files_in_discovery_ledgers':len(downloaded),'downloaded_tiktok_ledger_files':downloaded})
    (ROOT/'revision-comparison.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),'utf-8')
    for row in out:
        print(row['code'])
        print('downloaded pool:',row['downloaded_tiktok_files_in_discovery_ledgers'])
        for v in row['versions']:
            print(json.dumps({k:v[k] for k in ['id','duration','parent_files','tiktok_used_files','action_clips','repeated_source_seconds','largest_source_share','cover']},ensure_ascii=False))
        old=row['versions'][0]['parents'];new=row['versions'][-1]['parents']
        print('new used tiktok:',sum(v['provider']=='tiktok' and k not in old for k,v in new.items()),'removed tiktok:',sum(v['provider']=='tiktok' and k not in new for k,v in old.items()))
if __name__=='__main__': main()
