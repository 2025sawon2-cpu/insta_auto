"""Shared maintenance service and cooperative restart of the owned consumer."""
from __future__ import annotations
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time

def source_module_current(module,path):
    """Compare source with the receipt captured by the actual source loader."""
    if Path(module.__file__).resolve()!=path.resolve():raise RuntimeError('수정 모듈 로드 경로 불일치')
    return getattr(module,'__hotpost_source_sha256__',None)==hashlib.sha256(path.read_bytes()).hexdigest()


def restored_process_ready(pipeline,record,created):
    if not record.get('interruption_recovered') or created<=record['restored_at']:return False
    for row in record['files']:
        path=pipeline.roots[row['repo']]/row['path']
        actual=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if actual!=row['base_sha256']:raise RuntimeError('복구 원본 SHA 불일치')
        if actual and row['repo']=='main' and row['path'].startswith('hotpost/') and path.suffix=='.py':
            module=importlib.import_module(row['path'][:-3].replace('/','.'))
            if not source_module_current(module,path):return False
    return True


def resume_loaded_repairs(studio,manager):
    """Finish the owner's approved repair intent through the normal guarded tool."""
    from .video_agent_actions import execute
    from .video_agent_context import semantic_fingerprint
    for receipt in (getattr(studio,'loaded_code_receipts',{}) or {}).values():
        binding=receipt.get('binding') or {};task=binding.get('task_id');epoch=binding.get('agent_epoch')
        decision='loaded-repair-resume:'+receipt['repair_id']+':'+str(epoch)
        with studio.store.connect() as db:
            # The job may have paused again after this exact continuation ran.
            # A replayed action receipt is history, not permission to overwrite
            # the owner's current pending diagnosis or update the task revision.
            if (db.execute("SELECT 1 FROM sqlite_master WHERE name='video_agent_action_receipts'").fetchone()
                    and db.execute('SELECT 1 FROM video_agent_action_receipts WHERE task_id=? AND decision_id=?',
                                   (task,decision)).fetchone()):continue
            owner=db.execute('select epoch,record from video_agents where task_id=?',(task,)).fetchone()
            job=db.execute('select status,checkpoint from jobs where id=? and task_id=?',(binding.get('job_id'),task)).fetchone()
            if not owner or owner['epoch']!=epoch or not job or job['status'] not in {'failed','paused'}:continue
            checkpoint=json.loads(job['checkpoint'])
            record=json.loads(owner['record'])
            incident=record.get('no_progress_hold') or (record.get('held_method_incidents') or {}).get(binding.get('job_id')) or {}
            attempt_bound=(binding.get('job_id') in incident.get('jobs',{})
                and (job['status']=='failed' or checkpoint.get('no_progress_hold')==incident.get('id')))
            if not checkpoint.get('video_agent_park_receipt') and not attempt_bound:continue
            state=studio.store.get(task,db)
        auto=state.get('automation') or {}
        if not auto.get('active') or auto.get('paused_by_user'):continue
        action={'kind':'retry_repaired','job_id':binding['job_id'],'repair_id':receipt['repair_id'],
            '_agent_epoch':epoch,'evidence':[],
            'hypothesis':'Complete the owner-approved repair after verified fresh code loading; preserve original inputs and all normal retry gates.'}
        from .production_control import held_method
        with studio.store.connect() as db:
            attempt=held_method(db,task,binding.get('job_id'))
        if attempt:action['hold_id']=attempt['id']
        fingerprint=semantic_fingerprint(state)
        try:
            result=execute(studio,task,action,decision,fingerprint)
        except Exception as exc:
            # One video's malformed legacy input must not take down the service.
            # Keep its original parked job and give its owner the exact failure.
            import traceback
            result={'status':'failed','error':str(exc),'failure_type':type(exc).__name__,
                'failure_trace':traceback.format_exc()}
            manager._save(task,epoch,{'pending':None,'last_action':'retry_repaired','last_result':result,
                'runtime_error':str(exc),'status':'recovering','next_at':time.time()+30},
                {'origin':'verified_repair_continuation','action':action,'result':result,'fingerprint':fingerprint},decision)
            continue
        if result.get('status')=='queued':
            manager._save(task,epoch,{'pending':None,'last_action':'retry_repaired','last_result':result,
                'status':'active','idle_decisions':0,'next_at':time.time()+2},
                {'origin':'verified_repair_continuation','action':action,'result':result,'fingerprint':fingerprint},decision)

def configure(studio,manager):
    from .video_agent_repairs import VideoRepairPipeline, AppliedSourceChanged
    root=Path(__file__).resolve().parents[1]
    def independent_review(request):
        if manager.stop.is_set() or manager.maintenance.is_set() or manager.restart_requested.is_set():raise RuntimeError('서비스 전환 중 검토 시작을 보류합니다.')
        payload={'instruction':request['instruction']+' You are the independent repair reviewer, not the proposing agent. Inspect the exact diff and tests. Reply only JSON.',
                 'evidence':request,'media':[]}
        job=manager.jobs.create('repair_review',payload,'repair-review-'+request['binding_sha256'])
        if job['state']=='failed' and (job.get('result') or {}).get('error_reason')=='model_capacity':
            from .model_service import ModelServiceUnavailable
            retry=(job.get('result') or {}).get('retry_at') or time.time()+60
            if retry>time.time():raise ModelServiceUnavailable(str(job.get('error')),retry,False)
            manager.jobs.update(job['id'],state='queued',error='',result=None)
            job=manager.jobs.get(job['id'],include_payload=False)
        manager.jobs.start()
        while job['state'] in {'queued','running'}:
            if manager.stop.wait(1):raise RuntimeError('검토 중 서비스 종료 · 적용하지 않습니다.')
            job=manager.jobs.get(job['id'],include_payload=False)
        if job['state']!='completed':
            if (job.get('result') or {}).get('error_reason')=='model_capacity':
                from .model_service import ModelServiceUnavailable
                raise ModelServiceUnavailable(str(job.get('error')),(job.get('result') or {}).get('retry_at'))
            raise ValueError('독립 코드 검토 실패: '+str(job.get('error')))
        review=dict(job['result']['value']);review['reviewer_call_id']=job['id']
        return review
    studio.video_repair_pipeline=VideoRepairPipeline(root,studio.settings.auto_capcut_root,
        studio.store.root/'code-repairs',interpreters={'main':sys.executable,'renderer':str(studio.settings.auto_capcut_python)},
        regression_tests={'main':['tests/test_video_agent_actions.py','tests/test_retry_policy.py'],
                          'renderer':['tests/test_failed_source_intervals.py','tests/test_core_product_priority.py']},
        independent_reviewer=independent_review,require_incident=True)
    barrier=studio.store.root/'agent-maintenance.json'
    if barrier.is_file():
        interrupted=json.loads(barrier.read_text('utf8'))
        record=studio.video_repair_pipeline._read(interrupted['repair_id'])
        if interrupted.get('phase')=='restored_restart_required':
            import psutil
            if not restored_process_ready(studio.video_repair_pipeline,record,psutil.Process(os.getpid()).create_time()):
                manager.restart_requested.set()
                return
            barrier.unlink()
        elif record.get('status') in {'applying','apply_failed'}:
            from .video_agent_repairs import recover_partial_apply
            recover_partial_apply(studio.video_repair_pipeline,studio.store,record)
            manager.restart_requested.set()
            return  # Restored files must be reimported in a fresh process.
    marker=studio.store.root/'agent-restart.json'
    studio.loaded_code_receipt=None
    studio.loaded_code_receipts={}
    studio.superseded_code_receipts=[]
    def publish_empty_load():
        from .editing_adapter import _atomic_json
        _atomic_json(studio.store.root/'agent-loaded.json',
            {'process_id':os.getpid(),'loaded_at':time.time(),'status':'no_current_applied_repair'})
        _atomic_json(studio.store.root/'agent-loaded-repairs.json',{})
    def superseded(record):
        # A signed historical repair is not authority over changed live code.
        # Preserve its original record; expose only a stale diagnostic.
        if barrier.is_file():
            raise RuntimeError('Pending apply barrier has superseded source; preserve recovery barrier')
        item={'repair_id':record.get('repair_id'),'binding':record.get('binding') or {},
              'status':'source_changed','reason':'Authenticated applied receipt no longer matches current source'}
        if item not in studio.superseded_code_receipts:studio.superseded_code_receipts.append(item)
        from .editing_adapter import _atomic_json
        _atomic_json(studio.store.root/'agent-superseded-repairs.json',
            {'process_id':os.getpid(),'observed_at':time.time(),'repairs':studio.superseded_code_receipts})
    # Recover a crash after atomic code application but before the restart marker.
    candidates=[]
    for record_path in studio.video_repair_pipeline.receipts.glob('repair-*/repair.json'):
        record=json.loads(record_path.read_text('utf-8'))
        if record.get('status')=='applied':candidates.append(record)
    for index,latest in enumerate(sorted(candidates,key=lambda row:row['applied_at'],reverse=True)):
        try:authenticated=studio.video_repair_pipeline.applied_receipt(latest['repair_id'])
        except AppliedSourceChanged:
            superseded(latest);continue
        except (ValueError,OSError):
            if index==0:raise  # Unauthenticated latest apply remains fail-closed.
            continue  # Older invalid receipts were never current load authority.
        from .editing_adapter import _atomic_json
        _atomic_json(marker,authenticated)
        break
    if marker.is_file():
        receipt=json.loads(marker.read_text('utf-8'))
        try:receipt=studio.video_repair_pipeline.applied_receipt(receipt['repair_id'])
        except AppliedSourceChanged:
            superseded(receipt)
            publish_empty_load()
            return  # No proof, no automatic retry; ordinary owners may diagnose.
        import psutil
        if psutil.Process(os.getpid()).create_time()<=receipt['applied_at']:
            manager.request_restart(receipt)
            return  # Cached Python modules cannot attest that new code was loaded.
        for row in receipt['files']:
            path=studio.video_repair_pipeline.roots[row['repo']]/row['path']
            if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError('적용 코드 SHA가 변경되어 실행을 보류합니다.')
            if row['repo']=='main' and row['path'].startswith('hotpost/') and path.suffix=='.py':
                module=importlib.import_module(row['path'][:-3].replace('/','.'))
                if not source_module_current(module,path):
                    manager.request_restart(receipt)
                    return
        studio.loaded_code_receipt={**receipt,'process_id':os.getpid(),'loaded_at':time.time()}
        studio.loaded_code_receipts={receipt['repair_id']:studio.loaded_code_receipt}
        # Multiple video owners may have independent repairs loaded together.
        # Keep each exact still-current proof; never substitute another task's ID.
        for candidate in candidates:
            rid=candidate['repair_id']
            if rid in studio.loaded_code_receipts:continue
            try:older=studio.video_repair_pipeline.applied_receipt(rid)
            except (ValueError,OSError):continue  # Superseded/changed bytes are not certified.
            current=True
            for row in older['files']:
                path=studio.video_repair_pipeline.roots[row['repo']]/row['path']
                if row['repo']=='main' and row['path'].startswith('hotpost/') and path.suffix=='.py':
                    module=importlib.import_module(row['path'][:-3].replace('/','.'))
                    current=current and source_module_current(module,path)
            if current:studio.loaded_code_receipts[rid]={**older,'process_id':os.getpid(),'loaded_at':time.time()}
        from .editing_adapter import _atomic_json
        _atomic_json(studio.store.root/'agent-loaded.json',studio.loaded_code_receipt)
        _atomic_json(studio.store.root/'agent-loaded-repairs.json',studio.loaded_code_receipts)
        if barrier.is_file():
            if json.loads(barrier.read_text('utf8')).get('repair_id')!=receipt['repair_id']:
                raise RuntimeError('복구 적용 장벽과 실제 로드 영수증이 다릅니다.')
            barrier.unlink()

    else:
        publish_empty_load()
    resume_loaded_repairs(studio,manager)

def restart_process(arguments):
    """Called only after HTTP requests and all owned queues have drained."""
    os.execv(sys.executable,[sys.executable,'-X','utf8','-m','hotpost',*arguments])
