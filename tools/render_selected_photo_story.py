"""Produce the user-authorized original-photo story through a separate runner."""
import json
import os
import subprocess
import time
import argparse
from pathlib import Path
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.studio_store import uid
from hotpost.studio_workflow import current_run
from hotpost.source_quality import sha256_file

TASK='work-2edceeb819694427'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repair',action='store_true');args=parser.parse_args()
    settings=load_settings();studio=Studio(settings,workers=False)
    if not settings.photo_production_enabled:
        raise SystemExit('사진·캐러셀 게시물의 영상 제작은 비활성화되어 있습니다.')
    def start(s,db):
        if s['status']=='completed':
            if not args.repair:raise ValueError('Existing completed edit preserved')
            old=current_run(s)
            run={'id':uid('run-photo-'),'number':len(s['runs'])+1,'created':time.time(),
                 'status':'running','inputs':{'photo_story':True,'base_edit_id':s['edit_id']},'artifacts':{}}
            s['runs'].append(run);s['run_id']=run['id'];s['edit_id']=None
        if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status='running' AND kind NOT IN ('collect_sources','refresh_sources')",(TASK,)).fetchone():
            raise ValueError('Another production stage is running')
        run=current_run(s);run['inputs']['photo_story']=True
        s['approved_voice_id']=s['voice_id']
        s['automation'].update(stage='edit',active=True)
        s.update(status='editing',message='사진 화면 이동·확대와 음성·자막 구성 중',error='')
        db.execute("UPDATE jobs SET status='superseded' WHERE task_id=? AND status IN ('queued','paused') AND kind IN ('collect_sources','refresh_sources')",(TASK,))
        p={'voice_id':s['voice_id'],'script_id':s['script_id'],'photo_story':True}
        job_id=studio.store.enqueue(db,TASK,'edit',p,'photo-story:'+run['id'])
        db.execute("UPDATE jobs SET status='running',error='' WHERE id=? AND status IN ('queued','failed')",(job_id,))
        return job_id,p
    state=studio.store.get(TASK)
    # Reserve this explicitly handled job atomically before the old worker sees it.
    with studio.store.transaction() as db:
        state=studio.store.get(TASK,db);job_id,p=start(state,db);studio.store.save(db,state)
    job={'id':job_id,'task_id':TASK,'kind':'edit','payload':p,'checkpoint':{}}
    folder=studio.folder(TASK)/job_id;folder.mkdir(exist_ok=True)
    crops=[(0,210,1080,790),(0,270,1080,1100),(0,270,1080,1270),
           (0,270,1080,1100),(0,180,720,840),(0,280,1080,1250)]
    photos=[{'id':f'photo-{i+1}','path':str(Path(path).resolve()),'sha256':sha256_file(Path(path)),
             'crop':list(crops[i]),'origin_url':'https://www.instagram.com/p/DeOZa4ulJ0J/',
             'rights':'unknown-check-before-reuse','kind':'still_image',
             'usage':'explicit_user_requested_photo_video','reviewed_by':'agent_actual_original_images'}
            for i,path in enumerate(state['reference_images'])]
    req={'output_dir':str(folder.resolve()),'title':'네이비 맨투맨으로 완성한 파리 룩',
         'voice':next(v for v in state['voices'] if v['id']==state['voice_id']),
         'script':next(s for s in state['scripts'] if s['id']==state['script_id']),'photos':photos}
    request=folder/'photo-request.json';result=folder/'photo-result.json'
    request.write_text(json.dumps(req,ensure_ascii=False,indent=2),'utf-8')
    env=os.environ.copy();env['PYTHONUTF8']='1'
    ffmpeg=list(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    if ffmpeg:env['PATH']=str(ffmpeg[0])+os.pathsep+env['PATH']
    try:
        with (folder/'photo-render.log').open('w',encoding='utf-8') as log:
            proc=subprocess.Popen([str(settings.auto_capcut_python),'-X','utf8','-m','auto_capcut.photo_story_runner',
                 '--request',str(request.resolve()),'--result',str(result.resolve())],
                 cwd=settings.auto_capcut_root,env=env,stdout=log,stderr=log,
                 creationflags=subprocess.CREATE_NO_WINDOW)
            studio.store.checkpoint(job_id,{'photo_story_pid':proc.pid})
            proc.wait(timeout=settings.auto_capcut_timeout)
        receipt=json.loads(result.read_text('utf-8'))
        if receipt.get('status')!='completed' or receipt.get('export_verified') is not True:
            raise RuntimeError(receipt.get('error','Photo video export not verified'))
        receipt.update(id=job_id,script_id=p['script_id'],voice_id=p['voice_id'],created=time.time(),
                       registration_deferred=True,registration_note='CapCut을 닫은 뒤 포터블 프로젝트를 등록할 수 있습니다.')
        studio.store.finish(job,receipt,lambda s,db,r:studio._accept(s,job,r,db))
        print('Photo story completed',receipt['export_path'],flush=True)
    except Exception as exc:
        studio.store.fail(job,exc);raise


if __name__=='__main__':main()
