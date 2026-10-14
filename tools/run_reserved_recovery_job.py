"""Run one queued job with updated code without restarting live server jobs."""
import argparse,json,time
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.studio_workflow import current_run,init_run

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--code');p.add_argument('--kind');p.add_argument('--resume-inputs',action='store_true');a=p.parse_args()
    studio=Studio(load_settings(),workers=False)
    task=next(t for t in studio.store.list() if t['shortcode']==a.code)
    from hotpost.photo_reference import assert_creation_enabled
    assert_creation_enabled(studio.settings,task,a.kind)
    token='quality-recovery-'+str(time.time_ns())
    if a.resume_inputs:
        assert a.kind=='quality_reedit'
        def recover(s,db):
            assert not db.execute("select 1 from jobs where task_id=? and status in ('running','queued')",(s['id'],)).fetchone()
            from hotpost.quality_progress import resume_assessment
            if s.get('automation',{}).get('paused_by_user') or not resume_assessment(s):
                raise ValueError('사용자 중지 또는 새로운 실제 보완 근거 없음: 정상 명시 재개 평가가 필요합니다.')
            s['automation']['active']=True
            script=next(v for v in s['scripts'] if v['id']==s['script_id'])
            voice=next(v for v in s['voices'] if v['id']==s['voice_id'])
            edit=next(v for v in s['edits'] if v['id']==s['edit_id'])
            studio.advance_daily_quality(s,db,script,voice,edit)
            row=db.execute("select id,checkpoint from jobs where task_id=? and kind=? and status='queued' order by created limit 1",(s['id'],a.kind)).fetchone()
            assert row,'Newly approved sources did not produce a fresh job'
            cp=json.loads(row['checkpoint']);cp.update(batch_reservation=token,batch_original_not_before=cp.get('not_before',0),not_before=time.time()+3600)
            db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),row['id']))
            studio.store.event(db,s['id'],'source_inputs_reedit_resumed',{'job':row['id'],'reason':'new approved source identity, previous queued job preserved'})
        studio.store.change(task['id'],recover)
    with studio.store.transaction() as db:
        current=studio.store.get(task['id'],db)
        if current.get('automation',{}).get('paused_by_user') or current.get('daily_quality',{}).get('pending') in {'failed','exhausted'}:
            raise ValueError('사용자 중지·과거 품질 중단을 복구 도구로 우회하지 않습니다.')
        row=db.execute("select * from jobs where task_id=? and kind=? and status='queued' order by created limit 1",(task['id'],a.kind)).fetchone()
        assert row,'No queued job to reserve; do not interrupt an active job'
        cp=json.loads(row['checkpoint']);cp.update(batch_reservation=token,batch_original_not_before=cp.get('batch_original_not_before',cp.get('not_before',0)),not_before=time.time()+3600)
        db.execute('update jobs set checkpoint=? where id=? and status=\'queued\'',(json.dumps(cp),row['id']))
    job=studio.store.claim(task_id=task['id'],reservation=token,job_id=row['id'])
    if job is None:
        cp.pop('batch_reservation',None);cp['not_before']=cp.pop('batch_original_not_before',0)
        studio.store.checkpoint(row['id'],cp)
        raise RuntimeError('Another stage is still running; reservation released without claiming unrelated work')
    print('Running',job['id'],job['kind'],flush=True)
    try:
        state=studio.store.get(task['id'])
        assert_creation_enabled(studio.settings,state,job['kind'])
        payload=job['payload']
        from hotpost.studio_runtime.lifecycle import claimed_quality_permit
        from hotpost.quality_progress import QualityProgressHold
        if payload.get('script_id') is not None and payload['script_id']!=state.get('script_id'):
            raise ValueError('복구할 작업의 대본 선택이 현재 대본과 다릅니다.')
        stage='rewrite' if payload.get('quality_rewrite') else 'reedit' if job['kind']=='quality_reedit' or payload.get('quality_repair') else None
        if stage and not claimed_quality_permit(studio.store,job,stage):
            raise QualityProgressHold('복구 경로의 동일·동등한 확정 실패 방법 차단')
        result=getattr(studio,'_'+job['kind'])(state,job)
        studio.store.finish(job,result,lambda state,db,result:studio._accept(state,job,result,db))
        print('Completed',job['id'],flush=True)
    except Exception as exc:
        from hotpost.daily_quality import QualitySceneGap
        from hotpost.quality_progress import QualityProgressHold, finish_attempt, hold
        from hotpost.model_service import ModelServiceUnavailable
        from hotpost.source_browser_runtime import BrowserBusy
        from hotpost.photo_reference import PhotoProductionDisabled
        if isinstance(exc,PhotoProductionDisabled):
            studio.store.fail(job,exc)
        elif isinstance(exc,QualityProgressHold):
            def held(state,db,result):
                finish_attempt(state,job,failed=True);hold(state,str(exc),'stop_method')
            studio.store.finish(job,{'no_render':True},held)
        elif isinstance(exc,(ModelServiceUnavailable,BrowserBusy)):
            studio.store.defer(job,str(exc),max(1,getattr(exc,'retry_at',time.time()+30)-time.time()),waiting=True,waiting_status='retry_wait')
        elif isinstance(exc,QualitySceneGap):studio.handle_daily_scene_gap(job,exc)
        else:
            studio.store.fail(job,exc)
            if job['kind'] in {'quality_review','quality_reedit'}:studio.fail_daily_quality(job,exc)
        raise
