"""Retimed actual drying footage with an explicit parent timeline and normal gates."""
import argparse,copy,json,subprocess,time
from pathlib import Path
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.source_quality import sha256_file
from hotpost.source_finder import probe_video
from hotpost.editing_adapter import _atomic_json

ROOT=Path('data/source-recovery-20261012-v1').resolve();CODE='DeWFM7RyO0t'

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--code',choices=('DeWFM7RyO0t','DeWPBQyzpfR'),default=CODE)
    CODE=parser.parse_args().code
    if CODE=='DeWFM7RyO0t':
        index,start,end,rate,label=13,14.5,16.05,.62,'drying-slow-062'
        purpose='Keep the full drying sentence visible without reusing original time; not a new download.'
    else:
        index,start,end,rate,label=3,3.95,5.8,.65,'manual-flat-pan-slow-065'
        purpose='Continuous manual-cooking comparison for the opening conflict only; not the automatic machine demonstration or a new download.'
    studio=Studio(load_settings(),workers=False);state=next(t for t in studio.store.list() if t['shortcode']==CODE)
    parent=json.loads((ROOT/CODE/'ledger.json').read_text('utf-8'))['candidates'][index]
    assert parent['full_decode_passed'] and sha256_file(Path(parent['path']))==parent['sha256']
    target=ROOT/CODE/(label+'.mp4')
    if not target.exists():
        subprocess.run(['ffmpeg','-v','error','-ss',str(start),'-t',str(end-start),'-i',parent['path'],
            '-an','-vf',f'setpts=(PTS-STARTPTS)/{rate}','-r','30','-c:v','libx264','-crf','18',
            '-preset','veryfast',str(target)],check=True,capture_output=True)
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(target),'-f','null','-'],check=True,capture_output=True)
    digest=sha256_file(target);meta=probe_video(target)
    assert abs(meta['duration']-(end-start)/rate)<.06
    recipe={'method':'ffmpeg-setpts','playback_rate':rate,'source_sha256':digest,
        'original_sha256':parent['sha256'],'full_decode_passed':True,
        'input_interval':{'start':start,'end':end},'output_duration':meta['duration'],
        'purpose':purpose}
    source={'id':'focused-'+CODE+'-'+label,'path':str(target),'sha256':digest,
        'origin_url':parent['url'],'rights':'unknown','source_quality':'unknown','editing_eligible':False,
        'relevance_review_required':True,'original_sha256':parent['sha256'],
        'original_interval':{'start':start,'end':end},'video_meta':meta,'retiming':recipe}
    def stage(s,db):
        assert not db.execute("select 1 from jobs where task_id=? and status='running'",(s['id'],)).fetchone()
        assert not any(v['sha256']==digest for v in s['sources']),'Existing retimed review must be inspected instead of repeated'
        s.setdefault('quality_recovery_history',[]).append({'at':time.time(),'quality':copy.deepcopy(s['daily_quality']),
            'automation_active':s['automation'].get('active'),'new_source':digest})
        for row in db.execute("select id,checkpoint from jobs where task_id=? and status='queued'",(s['id'],)).fetchall():
            cp=json.loads(row['checkpoint']);cp['superseded_by_retimed_scene']=digest
            db.execute("update jobs set status='paused',checkpoint=? where id=?",(json.dumps(cp),row['id']))
        s['sources']=[source,*s['sources']];s['automation']['active']=False
        studio.release_source_hold(s)
        s['daily_quality'].update(status='repair',pending='recollecting')
        job=studio.store.enqueue(db,s['id'],'collect_sources',{'round':s.get('source_acquisition',{}).get('round',0),
            'run_id':s['run_id'],'source_policy':s['source_policy'],'daily_quality_repair':False},'retimed-scene-review:'+digest)
        cp={'not_before':time.time()+3600,'batch_reservation':'retimed-source-'+digest[:12],'batch_original_not_before':0}
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),job))
        s.update(status='source_wait',message='속도를 조정한 실제 구간의 일반 소스 검토 대기',error='')
        studio.store.event(db,s['id'],'actual_footage_retimed',{'source_id':source['id'],'recipe':recipe,
            'review_job':job,'new_download':False,'script_and_voice_unchanged':True})
    studio.store.change(state['id'],stage)
    _atomic_json(ROOT/CODE/(label+'-recipe.json'),recipe)
    print('Retimed actual clip',meta,'pending normal source review; source collection count unchanged',flush=True)
