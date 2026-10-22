"""Specific, proven workflow transitions. Recovery never grants media approval."""
import hashlib
import json
import time
from pathlib import Path

PREPARATION_CONTRACT = 'automatic-reference-before-source-review-v2'
OVERLAY_FAILURE = '워터마크·삽입 텍스트를 가릴 CapCut 블러 영역을 먼저 검토해야 합니다.'


def verified_preparation_incident(studio,state,job,evidence):
    """Maintenance-issued incident receipt; never inferred from an error string."""
    from .studio_runtime import generation
    try:
        receipt=json.loads((studio.store.root/'preparation-recovery.json').read_text('utf8'))
        module=Path(generation.__file__)
        if receipt['contract']!=PREPARATION_CONTRACT:return False
        if receipt['generation_sha256']!=generation.LOADED_SOURCE_SHA256:return False
        if hashlib.sha256(module.read_bytes()).hexdigest()!=generation.LOADED_SOURCE_SHA256:return False
        incident=next(r for r in receipt['incidents'] if r['task_id']==state['id'] and r['job_id']==job['id'])
        return (incident['error']==job['error'] and incident['failed_at']==job['updated']
                and incident['evidence']==evidence and incident.get('cause')=='worker-claimed-before-automatic-protocol'
                and incident.get('reproduced') is True)
    except (OSError,ValueError,KeyError,StopIteration,TypeError):return False


def preparation_ready(studio,state):
    try:
        with studio.store.connect() as db:
            job=db.execute("SELECT * FROM jobs WHERE task_id=? AND kind='prepare' AND status='failed' AND error=?",
                (state['id'],OVERLAY_FAILURE)).fetchone()
        if not job:return False
        evidence=[{'path':str(Path(state[k]).resolve()),'sha256':hashlib.sha256(Path(state[k]).read_bytes()).hexdigest()}
            for k in ('reference_video','transcript_path')]
        return verified_preparation_incident(studio,state,job,evidence)
    except (OSError,ValueError,KeyError,TypeError):return False


def recover_preparation(studio, db, state, action, decision_id):
    from .video_agent_actions import ActionHeld, _release_exact_hold, _hash
    job = db.execute("SELECT * FROM jobs WHERE task_id=? AND id=? AND kind='prepare' AND status='failed'",
                     (state['id'],action.get('job_id'))).fetchone()
    if (not job or job['error'] != OVERLAY_FAILURE or state.get('automation',{}).get('protocol')!=2
            or state.get('scripts') or state.get('voices') or state.get('edits')):
        raise ActionHeld('Recovery requires the exact legacy preparation failure before narration/editing')
    reference=Path(state.get('reference_video') or '')
    transcript=Path(state.get('transcript_path') or '')
    root=studio.settings.data_dir.resolve()
    if not all(p.is_file() and p.resolve().is_relative_to(root) for p in (reference,transcript)):
        raise ActionHeld('Verified retained reference and transcript are required')
    evidence=[{'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (reference,transcript)]
    if not verified_preparation_incident(studio,state,job,evidence):
        raise ActionHeld('Exact diagnosed incident and tested loaded preparation contract are required')
    method=_hash({'contract':PREPARATION_CONTRACT,'job_id':job['id'],'evidence':evidence})
    if db.execute('SELECT 1 FROM video_agent_action_receipts WHERE task_id=? AND method_key=?',(state['id'],method)).fetchone():
        raise ActionHeld('This preparation recovery has already run; diagnose the resulting new failure')
    checkpoint=json.loads(job['checkpoint'])
    if checkpoint.get('not_before',0)>time.time():
        raise ActionHeld('Existing service cooldown has not elapsed; retain not_before')
    if (checkpoint.get('failure_classification') or {}).get('category')=='access_blocked':
        raise ActionHeld('Session recovery is required before this job can execute')
    # Only source-attempt receipts from this job establish ownership. A nearby
    # timestamp/shortcode is not a binding; legacy unbound files remain untouched.
    bound_job=dict(job)
    bound_job['payload']=json.loads(job['payload'])
    for attempt in reversed(checkpoint.get('source_attempts',[])):
        from .source_pause_receipts import snapshot, SourceReceiptWaiting
        try:
            retained=snapshot(studio.settings.source_dir,attempt,state,bound_job)
        except (SourceReceiptWaiting,ValueError,OSError,KeyError,TypeError):continue
        state['recovery_source_manifest_path']=retained['manifest_path']
        state['recovery_source_manifest_sha256']=retained['manifest_sha256']
        break
    receipt={'contract':PREPARATION_CONTRACT,'decision_id':decision_id,'at':time.time(),'evidence':evidence,
             'old_error':job['error'],'method_key':method}
    checkpoint.setdefault('video_agent_recoveries',[]).append(receipt)
    _release_exact_hold(db,state['id'],job['id'],decision_id,method,evidence)
    db.execute("UPDATE jobs SET status='queued',error='',checkpoint=?,updated=? WHERE id=?",
               (json.dumps(checkpoint,ensure_ascii=False),time.time(),job['id']))
    state.update(status='preparing',error='',message='보존한 원본과 수신 자료를 정상 자동 검토 경로로 복구합니다')
    return {'status':'queued','job_ids':[job['id']],'method_key':method,'evidence':evidence,'recovery':receipt}


def retained_candidates(studio,state):
    """Import only real bytes; all independent review requirements stay attached."""
    raw=state.get('recovery_source_manifest_path')
    if not raw:return []
    path=Path(raw).resolve()
    if not path.is_relative_to(studio.settings.source_dir.resolve()):raise ValueError('Recovery manifest outside source root')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=state.get('recovery_source_manifest_sha256'):
        raise ValueError('Recovery manifest changed; inspect its new receipt')
    manifest=json.loads(path.read_text('utf8'));files=[]
    for row in manifest.get('candidates',[]):
        if not row.get('selected_for_zip') or not row.get('downloaded_file'):continue
        file=(path.parent/row['downloaded_file']).resolve()
        if not file.is_relative_to(path.parent) or not file.is_file():continue
        sha=hashlib.sha256(file.read_bytes()).hexdigest()
        if row.get('file_sha256')!=sha:continue
        files.append(file)
    return studio._source_records(files,path)
