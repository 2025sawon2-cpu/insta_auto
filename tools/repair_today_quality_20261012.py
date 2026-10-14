"""Evidence-bound local repairs; preserve original scripts, voices and renders."""
import argparse,copy,json,subprocess,time
from pathlib import Path
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.source_quality import sha256_file,editing_ready
from hotpost.source_finder import probe_video
from hotpost.editing_adapter import _atomic_json
ROOT=Path('data/source-recovery-20261012-v1').resolve()

def mat_prepare():
    studio=Studio(load_settings(),workers=False)
    state=next(t for t in studio.store.list() if t['shortcode']=='DeWWWOeDhGk')
    ledger=json.loads((ROOT/state['shortcode']/'ledger.json').read_text('utf-8'))
    parent=ledger['candidates'][11];assert sha256_file(Path(parent['path']))==parent['sha256']
    sources=[]
    for label,start,end in [('raised-edge',15,21),('cushion',27,34),('standing',35,42)]:
        target=ROOT/state['shortcode']/('focused-'+label+'.mp4')
        if not target.exists():
            subprocess.run(['ffmpeg','-v','error','-ss',str(start),'-i',parent['path'],'-t',str(end-start),
                '-an','-c:v','libx264','-crf','18','-preset','veryfast',str(target)],check=True,capture_output=True)
        subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(target),'-f','null','-'],check=True,capture_output=True)
        sources.append({'id':'focused-mat-'+label,'path':str(target),'sha256':sha256_file(target),
            'origin_url':parent['url'],'rights':'unknown','source_quality':'unknown','editing_eligible':False,
            'relevance_review_required':True,'original_sha256':parent['sha256'],
            'original_interval':{'start':start,'end':end},'video_meta':probe_video(target)})
    evidence=str(ROOT/state['shortcode']/'first-render-overview.jpg')
    def stage(s,db):
        assert not db.execute("select 1 from jobs where task_id=? and status in ('running','queued')",(s['id'],)).fetchone()
        for source in s['sources']:
            if source['id'] in ('source-9252917bb5a94aba','source-b6fbbcd15b9c4580'):
                source['manual_usage_review']={'editing_eligible':False,'reason':'Actual rendered cabinet interior liner is not the reference floor standing cushion.',
                    'evidence':evidence,'at':time.time(),'reference_shortcode':s['shortcode']}
                source['editing_eligible']=False
            if source['id']=='source-642117aca90946f5':
                old=copy.deepcopy(source['functional_review'])
                source.setdefault('functional_review_history',[]).append(old)
                source['functional_review'].update(same_core_function=False,context_usable=True,
                    context_usage_limits=['Transparent thin floor liner may show floor cleaning/standing context; not proof of thick cushioning or the reference raised L edge.'],
                    reviewer='manual_actual_contact_review',reason='Actual contact sheet shows clear thin floor film, not the thick reference cushion.')
                source['source_role']='context_only'
        for source in sources:
            if not any(v['sha256']==source['sha256'] for v in s['sources']):s['sources'].append(source)
        s['automation']['active']=True
        # Hold downstream review of the known wrong draft until focused scenes
        # have gone through the normal bounded overlay/function/crop reviewers.
        s['daily_quality'].update(status='repair',pending='failed',feedback=[{'kind':'scene_gap','beat_id':'',
            'reason':'Cabinet-interior liners wrongly used for standing floor cushion/raised edge.','search_query':'Llip raised edge kitchen floor cushion mat'}])
        studio.release_source_hold(s)
        acquisition=s.setdefault('source_acquisition',{})
        job=studio.store.enqueue(db,s['id'],'collect_sources',{'round':acquisition.get('round',0),'run_id':s['run_id'],
            'source_policy':s['source_policy']},'focused-mat-local-review-20261012-v1')
        s.update(status='source_wait',message='바닥 매트의 가장자리·쿠션·서 있는 장면 실제 구간 검토 중')
        studio.store.event(db,s['id'],'manual_wrong_product_exclusion',{'evidence':evidence,'local_review_job':job})
    studio.store.change(state['id'],stage)
    _atomic_json(ROOT/state['shortcode']/'focused-scenes-pending.json',sources)
    print('Mat cabinet liners excluded; three actual bounded product intervals queued for normal review',flush=True)

def status():
    studio=Studio(load_settings(),workers=False)
    for t in sorted([t for t in studio.store.list() if t.get('automation',{}).get('selection_date_kst')=='2026-10-12'],key=lambda t:t['automation']['rank']):
        live=[(j['kind'],j['status']) for j in studio.store.jobs(t['id']) if j['status'] in ('running','queued')]
        print(t['automation']['rank'],t['shortcode'],t['status'],t['daily_quality'].get('pending'),t['daily_quality'].get('error',''),
            len(t['edits']),live,t.get('source_search',{}).get('message',''),flush=True)

def local_sources(code,indices):
    studio=Studio(load_settings(),workers=False)
    state=next(t for t in studio.store.list() if t['shortcode']==code)
    ledger=json.loads((ROOT/code/'ledger.json').read_text('utf-8'))['candidates']
    incoming=[]
    for index in indices:
        row=ledger[index];assert row.get('full_decode_passed')
        assert sha256_file(Path(row['path']))==row['sha256']
        incoming.append({'id':'local-recovery-'+str(index)+'-'+row['sha256'][:8],'path':row['path'],
            'sha256':row['sha256'],'origin_url':row['url'],'rights':'unknown','source_quality':'unknown',
            'editing_eligible':False,'relevance_review_required':True,'video_meta':row['video_meta']})
    def stage(s,db):
        assert not db.execute("select 1 from jobs where task_id=? and kind in ('collect_sources','refresh_sources') and status in ('running','queued')",(s['id'],)).fetchone()
        known={v['sha256'] for v in s['sources']}
        added=[v for v in incoming if v['sha256'] not in known]
        s['sources']=[*added,*s['sources']]
        studio.release_source_hold(s)
        acquisition=s.setdefault('source_acquisition',{})
        studio.store.enqueue(db,s['id'],'collect_sources',{'round':acquisition.get('round',0),
            'run_id':s['run_id'],'source_policy':s['source_policy'],
            'daily_quality_repair':s.get('daily_quality',{}).get('pending')=='recollecting'},'local-source-review:'+code+':'+','.join(map(str,indices)))
        studio.store.event(db,s['id'],'local_received_sources_review',{'sha256s':[v['sha256'] for v in added]})
    studio.store.change(state['id'],stage)
    print(code,'local received sources queued for normal review',flush=True)

def focused_source(code,index,start,end,label):
    studio=Studio(load_settings(),workers=False)
    state=next(t for t in studio.store.list() if t['shortcode']==code)
    parent=json.loads((ROOT/code/'ledger.json').read_text('utf-8'))['candidates'][index]
    assert parent.get('full_decode_passed') and sha256_file(Path(parent['path']))==parent['sha256']
    assert 0<=start<end<=parent['video_meta']['duration']
    target=ROOT/code/('focused-'+label+'.mp4')
    if not target.exists():
        subprocess.run(['ffmpeg','-v','error','-ss',str(start),'-i',parent['path'],'-t',str(end-start),
            '-an','-c:v','libx264','-crf','18','-preset','veryfast',str(target)],check=True,capture_output=True)
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(target),'-f','null','-'],check=True,capture_output=True)
    source={'id':'focused-'+code+'-'+label,'path':str(target),'sha256':sha256_file(target),
        'origin_url':parent['url'],'rights':'unknown','source_quality':'unknown','editing_eligible':False,
        'relevance_review_required':True,'original_sha256':parent['sha256'],
        'original_interval':{'start':start,'end':end},'video_meta':probe_video(target)}
    def stage(s,db):
        assert not db.execute("select 1 from jobs where task_id=? and kind in ('collect_sources','refresh_sources') and status='running'",(s['id'],)).fetchone()
        if not any(v['sha256']==source['sha256'] for v in s['sources']):s['sources'].insert(0,source)
        queued=db.execute("select id from jobs where task_id=? and kind='collect_sources' and status='queued'",(s['id'],)).fetchone()
        if not queued:
            studio.release_source_hold(s)
            studio.store.enqueue(db,s['id'],'collect_sources',{'round':s.get('source_acquisition',{}).get('round',0),
                'run_id':s['run_id'],'source_policy':s['source_policy'],
                'daily_quality_repair':s.get('daily_quality',{}).get('pending')=='recollecting'},
                'local-focused-review:'+source['sha256'])
        studio.store.event(db,s['id'],'actual_action_window',{'source_sha256':source['sha256'],
            'parent_sha256':parent['sha256'],'parent_start':start,'parent_end':end,
            'reason':'Explicit action inspected in a dense contact sheet; not an approval outside reviewed intervals'})
    studio.store.change(state['id'],stage)
    _atomic_json(ROOT/code/('focused-'+label+'-pending.json'),source)
    print(code,label,'actual bounded interval queued for normal review',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['mat-prepare','status','local-sources','focus']);p.add_argument('--code');p.add_argument('--indices',type=int,nargs='+');p.add_argument('--index',type=int);p.add_argument('--start',type=float);p.add_argument('--end',type=float);p.add_argument('--label');a=p.parse_args()
    if a.action=='mat-prepare':mat_prepare()
    elif a.action=='local-sources':local_sources(a.code,a.indices)
    elif a.action=='focus':focused_source(a.code,a.index,a.start,a.end,a.label)
    else:status()
