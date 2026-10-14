import json, os, time, traceback
from pathlib import Path
from hotpost.config import load_settings
from hotpost.studio import Studio
os.environ['PATH']=str(next(Path('C:/Users/s98se/AppData/Local/Microsoft/WinGet/Packages').glob('Gyan.FFmpeg*/ffmpeg*/bin')))+os.pathsep+os.environ['PATH']
s=Studio(load_settings(),workers=False)
if not s.settings.photo_production_enabled:
    raise SystemExit('사진·캐러셀 게시물의 영상 제작은 비활성화되어 있습니다.')
for taskid in ['work-e6e9f219d29e4cf2','work-2edceeb819694427']:
    with s.store.transaction() as db:
        s.store.enqueue(db,taskid,'prepare',{},'photo-reference:'+taskid)
        r=dict(db.execute("select * from jobs where key=?",('photo-reference:'+taskid,)).fetchone())
        if r['status']=='done':
            continue
        db.execute("update jobs set status='running',updated=? where id=?",(time.time(),r['id']))
    r['payload']=json.loads(r['payload']);r['checkpoint']=json.loads(r['checkpoint'])
    try:
        print('Preparing',taskid,flush=True)
        result=s._prepare(s.store.get(taskid),r)
        def accept(state,db,result):
            s._accept(state,r,result,db)
            # The already-running source lane predates photo support. Preserve
            # its current job; a freshly loaded scoped consumer handles these.
            for row in db.execute("select id,checkpoint from jobs where task_id=? and kind='collect_sources' and status='queued'",(taskid,)).fetchall():
                checkpoint=json.loads(row['checkpoint']);checkpoint['not_before']=time.time()+86400
                db.execute('update jobs set checkpoint=? where id=?',(json.dumps(checkpoint),row['id']))
        s.store.finish(r,result,accept)
        print('Prepared',taskid,len(result['reference_images']),flush=True)
    except Exception as exc:
        s.store.fail(r,exc);print('Failed',taskid,str(exc),flush=True);traceback.print_exc()
