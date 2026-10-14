"""Compact operational evidence and dense frame sampling; no source approval."""
import argparse,json,subprocess
from pathlib import Path
from PIL import Image,ImageDraw
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.source_quality import sha256_file
from hotpost.editing_adapter import _atomic_json

ROOT=Path('data/source-recovery-20261012-v1').resolve()

def main():
    p=argparse.ArgumentParser();p.add_argument('--code',required=True)
    p.add_argument('--sample',action='store_true');p.add_argument('--start',type=float,default=0)
    p.add_argument('--end',type=float);p.add_argument('--raw-index',type=int)
    a=p.parse_args();studio=Studio(load_settings(),workers=False)
    t=next(t for t in studio.store.list() if t['shortcode']==a.code)
    e=next((e for e in t['edits'] if e['id']==t.get('edit_id')),None)
    q=t.get('daily_quality',{});r=q.get('reviews',[])
    out={'code':a.code,'status':t['status'],'quality':{k:q.get(k) for k in ('pending','repair_round','max_repairs')},
        'last_issues':r[-1].get('issues') if r else None,'live':[{k:j.get(k) for k in ('id','kind','status')} for j in studio.store.jobs(t['id']) if j['status'] in ('running','queued')]}
    if e:
        plan=json.loads(Path(e['plan_path']).read_text('utf-8'));shots={x['id']:x for x in plan['shots']}
        out['edit']={k:e.get(k) for k in ('id','plan_path','preview_path','quality_review_path')}
        out['beats']=[{'id':b['id'],'text':b['text'],'start':b['start'],'end':b['end'],
            'source':shots[b['selected_shot_id']]['source_id'],
            'source_interval':[shots[b['selected_shot_id']]['start'],shots[b['selected_shot_id']]['end']]} for b in plan['beats']]
    out['sources']=[{'id':v['id'],'sha256':v['sha256'],'role':v.get('source_role'),
        'ready':v.get('editing_eligible'),'intervals':v.get('reviewed_intervals'),
        'relevance_pending':v.get('relevance_review_required')} for v in t['sources']]
    if a.sample:
        if a.raw_index is None:
            assert e;raw=Path(e['preview_path']);duration=e['duration'];name='render-'+e['id']
        else:
            row=json.loads((ROOT/a.code/'ledger.json').read_text('utf-8'))['candidates'][a.raw_index]
            assert row.get('full_decode_passed');raw=Path(row['path']);assert sha256_file(raw)==row['sha256']
            duration=row['video_meta']['duration'];name='raw-'+str(a.raw_index)
        end=min(a.end if a.end is not None else duration-.08,duration-.08)
        assert 0<=a.start<end
        folder=ROOT/a.code/(name+f'-dense-{a.start:g}-{end:g}');folder.mkdir(exist_ok=True)
        count=max(16,min(60,int((end-a.start)*3)+1));frames=[]
        sheet=Image.new('RGB',(960,((count+3)//4)*452),'#222');draw=ImageDraw.Draw(sheet)
        for i in range(count):
            ts=a.start+(end-a.start)*i/(count-1);target=folder/f'{i:02}.jpg'
            subprocess.run(['ffmpeg','-v','error','-y','-ss',str(ts),'-i',str(raw),'-frames:v','1',
                '-vf','scale=240:426',str(target)],check=True,capture_output=True,timeout=30)
            with Image.open(target) as im:sheet.paste(im,(i%4*240,i//4*452+24))
            draw.text((i%4*240+3,i//4*452+3),f'{ts:.3f}s',fill='white')
            frames.append({'path':str(target),'timestamp':ts,'sha256':sha256_file(target)})
        sheet.save(folder/'contact.jpg',quality=94)
        _atomic_json(folder/'sampling.json',{'source':str(raw),'source_sha256':sha256_file(raw),'frames':frames,
            'actual_visual_review_pending':True,'new_download':False})
        out['contact']=str(folder/'contact.jpg')
    _atomic_json(ROOT/(a.code+'-current-inspection.json'),out)
    display={'code':a.code,'status':out['status'],'live':out['live'],'contact':out.get('contact')} if a.sample else out
    print(json.dumps(display,ensure_ascii=False,separators=(',',':')),flush=True)

if __name__=='__main__':main()
