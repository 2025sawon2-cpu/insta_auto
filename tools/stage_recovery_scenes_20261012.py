"""Atomically add a batch of bounded existing clips to the normal source reviews."""
import argparse,copy,json,subprocess,time
from pathlib import Path
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.source_quality import sha256_file
from hotpost.source_finder import probe_video
from hotpost.editing_adapter import _atomic_json

ROOT=Path('data/source-recovery-20261012-v1').resolve()
BATCHES={
    'DeVUqoBMBYf':[(0,10.0,18.8,'actual-inner-down-vest-wearing'),
        (23,7.73,8.78,'actual-round-neck-vest-shop')],
    'DeWWWOeDhGk':[(12,13.3,17.1,'actual-wiping')],
    'DeWWtERKroR':[(9,22,30,'neck-climbing'),(10,17,23,'body-play')],
    'DeWFM7RyO0t':[(13,12.5,14.1,'inverted-stretch')],
    'DeVsIG8S6Pd':[(1,1.7,6.5,'white-opening'),(9,0,3.8,'yellow-opening'),(9,6.7,10,'two-sleeping-spaces')],
    'DeWPBQyzpfR':[(3,3.1,6.7,'manual-comparison'),(0,2,4.5,'empty-round-pan'),
        (0,5,7.7,'ingredients-in'),(0,10.2,11.35,'finished-plate'),
        (3,8.85,10.3,'serve-one-ball'),(3,11.3,12.2,'sauce-finish'),
        (0,18.3,19.3,'plate-garnish-only'),(3,13.7,14.95,'equipment-finish'),
        (0,5.7,7.3,'ingredients-stable-caption'),(3,3.95,5.8,'manual-flat-pan')],
    'DeVKnW6z_Rl':[(0,2.8,5.2,'large-print-context'),(0,5.6,7.7,'front-liquid-application'),
        (0,10.1,12.5,'pink-print-removal')],
}

def main():
    p=argparse.ArgumentParser();p.add_argument('--code',choices=BATCHES,required=True);p.add_argument('--prepare-only',action='store_true');a=p.parse_args()
    studio=Studio(load_settings(),workers=False);t=next(t for t in studio.store.list() if t['shortcode']==a.code)
    ledger=json.loads((ROOT/a.code/'ledger.json').read_text('utf-8'))['candidates'];incoming=[]
    for index,start,end,label in BATCHES[a.code]:
        parent=ledger[index];assert parent.get('full_decode_passed')
        assert sha256_file(Path(parent['path']))==parent['sha256'] and 0<=start<end<=parent['video_meta']['duration']
        target=ROOT/a.code/('focused-'+label+'.mp4')
        if not target.exists():
            subprocess.run(['ffmpeg','-v','error','-ss',str(start),'-i',parent['path'],'-t',str(end-start),
                '-an','-c:v','libx264','-crf','18','-preset','veryfast',str(target)],check=True,capture_output=True)
        subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(target),'-f','null','-'],check=True,capture_output=True)
        incoming.append({'id':'focused-'+a.code+'-'+label,'path':str(target),'sha256':sha256_file(target),
            'origin_url':parent['url'],'rights':'unknown','source_quality':'unknown','editing_eligible':False,
            'relevance_review_required':True,'original_sha256':parent['sha256'],
            'original_interval':{'start':start,'end':end},'video_meta':probe_video(target)})
    if a.prepare_only:
        _atomic_json(ROOT/a.code/'local-scene-batch-prepared.json',incoming)
        print(a.code,'bounded files prepared; not registered or approved',flush=True)
        return
    def stage(s,db):
        if s.get('automation',{}).get('paused_by_user') or s.get('daily_quality',{}).get('pending') in {'failed','exhausted'}:
            raise ValueError('사용자 중지·과거 품질 중단 유지: 정상 제작실의 새 근거 평가와 명시 재개가 먼저 필요합니다.')
        assert not db.execute("select 1 from jobs where task_id=? and status='running'",(s['id'],)).fetchone(), 'Wait for the existing live job; do not interrupt it'
        known={v['sha256'] for v in s['sources']};added=[v for v in incoming if v['sha256'] not in known]
        assert added,'This batch was already registered; inspect its existing review'
        obsolete=db.execute("select id,checkpoint from jobs where task_id=? and status='queued' and kind in ('quality_reedit','quality_review')",(s['id'],)).fetchall()
        for old in obsolete:
            cp=json.loads(old['checkpoint']);cp.update(superseded_by_local_scene_batch=True,superseded_at=time.time())
            db.execute("update jobs set status='paused',checkpoint=?,updated=? where id=? and status='queued'",
                (json.dumps(cp),time.time(),old['id']))
        s['sources']=[*added,*s['sources']]
        q=s['daily_quality'];s.setdefault('quality_recovery_history',[]).append({'at':time.time(),'quality':copy.deepcopy(q),
            'new_local_scenes':[v['sha256'] for v in added]})
        q.update(pending='recollecting',status='repair')
        s['automation'].update(active=True,stage='sources');studio.release_source_hold(s)
        job=studio.store.enqueue(db,s['id'],'collect_sources',{'round':s.get('source_acquisition',{}).get('round',0),
            'run_id':s['run_id'],'source_policy':s['source_policy'],'daily_quality_repair':True},
            'review-local-batch:'+a.code+':'+':'.join(v['sha256'][:12] for v in added))
        s.update(status='source_wait',message='새로 분리한 실제 구간의 자막·기능·세로 화질 검토 중',error='')
        studio.store.event(db,s['id'],'new_local_scene_batch',{'job':job,'sha256s':[v['sha256'] for v in added],
            'network_search':False,'approval_granted':False,'superseded_queued_jobs':[v['id'] for v in obsolete]})
    studio.store.change(t['id'],stage)
    _atomic_json(ROOT/a.code/'local-scene-batch-pending.json',incoming)
    print(a.code,'bounded batch queued for normal source gates; originals preserved',flush=True)

if __name__=='__main__':main()
