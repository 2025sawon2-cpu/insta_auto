"""Exercise the daily quality worker on preserved real media in an isolated store.

Uses the same review, source refresh and editing implementations. Does not
enqueue today's collection or mutate existing seven productions.
"""
import argparse,copy,json,time
from dataclasses import replace
from pathlib import Path
from hotpost.config import load_settings
from hotpost.daily_quality import POLICY
from hotpost.editing_adapter import _atomic_json
from hotpost.studio import Studio
from hotpost.studio_workflow import snapshot

ROOT=Path('data/daily-quality-live-test-20261011-v2').resolve()
CODE='DeRFXHpEwck';WORK='work-440c6d0fc4794fa5'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--jobs',type=int,default=1);parser.add_argument('--resume-test',action='store_true');parser.add_argument('--resume-edit',action='store_true');parser.add_argument('--resume-review',action='store_true');args=parser.parse_args()
    settings=load_settings();original=Studio(settings,workers=False).store.get(WORK)
    studio=Studio(replace(settings,data_dir=ROOT,studio_auto_top_enabled=False,
        source_max_probe_downloads=4,source_max_downloads=4,source_max_attempts=8,
        source_probe_time_budget=180,source_platform_probe_budget=90,source_browser_timeout=120,
        source_queries_per_platform=2,source_browser_frames=0),workers=False)
    from hotpost.storage import Storage
    origin_db=Storage(settings.db_path);test_db=Storage(studio.settings.db_path)
    post=origin_db.conn.execute('SELECT * FROM posts WHERE shortcode=?',(CODE,)).fetchone()
    profile=origin_db.conn.execute('SELECT * FROM profiles WHERE username=?',(post['username'],)).fetchone()
    for table,row in [('profiles',profile),('posts',post)]:
        if row:
            columns=list(row.keys())
            test_db.conn.execute(f"INSERT OR IGNORE INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",tuple(row))
    test_db.conn.commit();test_db.close();origin_db.close()
    receipt=ROOT/'fixture.json'
    if not receipt.exists():
        prior=next(e for e in original['edits'] if e['id']=='a7-receipt-review-20261011-v6')
        plan=json.loads(Path(prior['plan_path']).read_text('utf-8'))
        state,_=studio.store.create(CODE,'미니 파일 홀더 실제 품질 시험',automation={
            'active':True,'protocol':2,'selection_mode':'manual','finish_selected_batch':True,'stage':'quality_review'},prepare=False)
        def init(s,db):
            script=copy.deepcopy(next(x for x in original['scripts'] if x['id']==prior['script_id']))
            voice=copy.deepcopy(next(x for x in original['voices'] if x['id']==prior['voice_id']))
            s.update(original_text=original['original_text'],reference_video=original['reference_video'],
                product='미니 파일 홀더',scripts=[script],script_id=script['id'],approved_script_id=script['id'],
                script_candidates=original['script_candidates'],selected_candidate=original.get('selected_candidate'),
                voices=[voice],voice_id=voice['id'],approved_voice_id=voice['id'],
                edits=[copy.deepcopy(prior)],edit_id=prior['id'],sources=copy.deepcopy(plan['sources']),
                daily_quality={'policy':POLICY,'max_repairs':3,'repair_round':0,'status':'pending','reviews':[]},
                manifest_path=original.get('manifest_path',''),source_policy=copy.deepcopy(original['source_policy']),
                source_acquisition=copy.deepcopy(original.get('source_acquisition',{})),
                benchmark_analysis=copy.deepcopy(original.get('benchmark_analysis',{})))
            snapshot(s);studio.advance_workflow(s,db)
        studio.store.change(state['id'],init)
        _atomic_json(receipt,{'task_id':state['id'],'original_task':WORK,'baseline_edit':prior['id'],'production_store_isolated':True})
    task=json.loads(receipt.read_text('utf-8'))['task_id']
    if args.resume_review:
        def resume_review(s,db):
            _atomic_json(ROOT/'failed-review-before-resume.json',copy.deepcopy(s))
            s['automation']['active']=True;s['daily_quality'].pop('pending',None)
            s['daily_quality'].pop('error',None);s['error']='';studio.advance_workflow(s,db)
        studio.store.change(task,resume_review)
    if args.resume_edit:
        def resume_edit(s,db):
            _atomic_json(ROOT/'failed-edit-before-resume.json',copy.deepcopy(s))
            # Legacy manual revisions have their selected cover in the plan,
            # whereas tomorrow's writer stores it on each of the three candidates.
            prior=s['edits'][0];plan=json.loads(Path(prior['plan_path']).read_text('utf-8'))
            text=plan['script_text']
            if not any(c.get('text')==text for c in s['script_candidates']):
                s['script_candidates'].append({'text':text,'thumbnail_lines':plan['cover_spec']['lines'],
                    'origin':'preserved_legacy_selected_plan_for_test'})
            s['automation']['active']=True;s['daily_quality'].update(pending='reedit',status='repair')
            s['daily_quality'].pop('error',None);s['error']='';studio.advance_workflow(s,db)
        studio.store.change(task,resume_edit)
    if args.resume_test:
        def resume(s,db):
            _atomic_json(ROOT/'failed-before-resume.json',copy.deepcopy(s))
            s['automation']['active']=True;s['daily_quality'].update(pending='recollect',status='repair')
            s['daily_quality'].pop('error',None);s['error']='';studio.advance_workflow(s,db)
        studio.store.change(task,resume)
    for _ in range(args.jobs):
        job=studio.store.claim(task_id=task)
        if not job:print('No queued work; current state: '+studio.store.get(task)['status'],flush=True);break
        print('Executing '+job['kind']+' '+job['id'],flush=True)
        try:
            state=studio.store.get(task)
            if job['kind']=='refresh_sources':
                # The real source service uses the original reference/session/library;
                # only the production store is isolated. No empty test login profile.
                isolated=studio.settings
                studio.settings=replace(isolated,data_dir=settings.data_dir)
                try:result=studio._refresh_sources(state,job)
                finally:studio.settings=isolated
            else:result=getattr(studio,'_'+job['kind'])(state,job)
            _atomic_json(ROOT/(job['id']+'-result.json'),result)
            studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
        except Exception as exc:
            from hotpost.daily_quality import QualitySceneGap
            if isinstance(exc,QualitySceneGap):studio.handle_daily_scene_gap(job,exc)
            else:
                studio.store.fail(job,exc);studio.fail_daily_quality(job,exc);raise
        finally:
            _atomic_json(ROOT/'current-state.json',studio.store.get(task))
        current=studio.store.get(task)
        print(json.dumps({'status':current['status'],'quality_status':current['daily_quality']['status'],
            'pending':current['daily_quality'].get('pending'),'repair_round':current['daily_quality']['repair_round'],
            'issues':current['daily_quality'].get('feedback',[])},ensure_ascii=False),flush=True)
    _atomic_json(ROOT/'jobs.json',studio.store.jobs(task))

if __name__=='__main__':main()
