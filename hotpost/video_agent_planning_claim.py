"""Admit a verified planning-recovery child without clearing its source hold."""
import json


def internal_wait_parking_proof(db,state,job):
    """Prove an unchanged internal defer, solely for signed repair parking.

    This never restores a paused job or grants claim/retry permission. A fresh
    reviewed repair must still pass the normal park/apply/load/retry sequence.
    """
    import math,time
    try:
        job=dict(job)
        if job.get('status')!='paused' or not planning_recovery_candidate(state,job):return None
        from .video_agent_actions import _gate
        _gate(state,'park_for_repair',job)
        cp=job['checkpoint'];cp=json.loads(cp) if isinstance(cp,str) else cp
        trace=cp.get('failure_trace') or {}
        if (cp.get('internal_evidence_wait') is not True or cp.get('deferred_wait') is not False
                or trace.get('type') not in {'PreparationEvidenceWaiting','SourceReceiptWaiting'}
                or trace.get('stage')!='collect_sources' or not cp.get('_claim_token')):return None
        for value in (job['updated'],cp['_claim_started_at'],cp['not_before']):
            if type(value) not in (int,float) or not math.isfinite(value):return None
        if cp['not_before']>time.time() or cp['_claim_started_at']<=0:return None
        event=db.execute("""SELECT id,detail FROM events WHERE task_id=? AND kind='job_timing'
            AND CASE WHEN json_valid(detail) THEN json_extract(detail,'$.job_id') END=?
            ORDER BY id DESC LIMIT 1""",(state['id'],job['id'])).fetchone()
        if not event:return None
        detail=json.loads(event['detail'])
        expected={'job_id':job['id'],'kind':'collect_sources','claim_token':cp['_claim_token'],
            'started_at':cp['_claim_started_at'],'not_before':cp['not_before'],
            'observed_at':job['updated'],'outcome':'deferred','wait_kind':'retry_wait'}
        if any(detail.get(k)!=v for k,v in expected.items()) or job['updated']<cp['_claim_started_at']:return None
        if db.execute("""SELECT 1 FROM events WHERE task_id=? AND id>? AND kind='job_paused'
            AND CASE WHEN json_valid(detail) THEN json_extract(detail,'$.job_id') END=? LIMIT 1""",
            (state['id'],event['id'],job['id'])).fetchone():return None
        return {'job_id':job['id'],'timing_event_id':event['id'],'deferred':detail,
            'basis':'exact_current_claim_internal_defer_and_unchanged_job_timestamp',
            'continuation':'fresh test/review -> park_for_repair -> apply_patch -> loaded retry_repaired; no direct resume'}
    except (TypeError,ValueError,KeyError,AttributeError,OverflowError):return None


def planning_recovery_candidate(state,job):
    """Structural eligibility only; mutation still needs a fresh signed repair."""
    try:
        job=dict(job);payload=job.get('payload') or {};cp=job.get('checkpoint') or {}
        if isinstance(payload,str):payload=json.loads(payload)
        if isinstance(cp,str):cp=json.loads(cp)
        acquisition=state.get('source_acquisition') or {};rounds=acquisition.get('rounds') or []
        last=rounds[-1] if rounds else {};parent=payload.get('planning_recovery_from')
        return bool(job.get('kind')=='collect_sources' and job.get('task_id')==state.get('id')
            and job.get('status') in {'failed','paused','queued'} and isinstance(parent,str) and parent
            and (acquisition.get('hold') or {}).get('reason')=='strategy_exhausted'
            and not acquisition.get('waiting') and not acquisition.get('receipt_wait')
            and not (state.get('source_goal') or {}).get('ready')
            and last.get('job_id')==parent and last.get('run_id')==state.get('run_id')
            and last.get('manifest_path')==state.get('source_search_manifest_path')
            and payload.get('run_id')==state.get('run_id')
            and payload.get('round')==acquisition.get('round')
            and payload.get('source_policy')==state.get('source_policy')
            and job.get('key')=='source-plan-recovery:'+state['run_id']+':'+parent
            and (cp.get('failure_classification') or {}).get('category')!='access_blocked')
    except (TypeError,ValueError,KeyError,AttributeError):return False


def repaired_child_receipt(db,row,state,epoch):
    """Recognize the normal retry executor's durable, current repair receipt."""
    from .video_agent_context import semantic_fingerprint
    cp=json.loads(row['checkpoint']);fingerprint=semantic_fingerprint(state)
    admission=cp.get('video_agent_retry_admission')
    if not isinstance(admission,dict):return False
    for recovery in cp.get('video_agent_recoveries',[]):
        if not isinstance(recovery,dict) or recovery.get('changed_input') is not True:continue
        if admission!={k:recovery.get(k) for k in ('decision_id','method_key')}:continue
        saved=db.execute('SELECT result,method_key FROM video_agent_action_receipts WHERE task_id=? AND decision_id=?',
            (row['task_id'],recovery.get('decision_id'))).fetchone()
        if not saved:continue
        receipt=json.loads(saved['result'])
        if (not isinstance(receipt,dict) or receipt.get('status')!='queued' or receipt.get('job_ids')!=[row['id']]
                or receipt.get('method_key')!=saved['method_key'] or saved['method_key']!=recovery.get('method_key')
                or not isinstance(receipt.get('evidence'),list) or receipt['evidence']!=recovery.get('evidence')):continue
        for evidence in receipt['evidence']:
            repair=evidence.get('repair') if isinstance(evidence,dict) else None
            binding=repair.get('binding') if isinstance(repair,dict) else None
            if (isinstance(binding,dict) and binding.get('task_id')==row['task_id']
                    and binding.get('job_id')==row['id'] and binding.get('agent_epoch')==epoch
                    and binding.get('input_fingerprint')==fingerprint
                    and repair.get('review_binding_sha256') and repair.get('files')):return True
    return False


def _accepted_retry_unclaimed(db,row):
    """Restore only an accepted retry stopped before any subsequent execution.

    Broad hold SQL changes status alone. Require the executor's receipt/event,
    its unchanged write timestamp, and no later execution or stop evidence.
    """
    import math
    if row['error']:return False
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='supervision_jobs'").fetchone():
        if db.execute("SELECT 1 FROM supervision_jobs WHERE task_id=? AND phase='held'",
                (row['task_id'],)).fetchone():return False
    cp=json.loads(row['checkpoint']);admission=cp.get('video_agent_retry_admission') or {}
    saved=db.execute('SELECT result,created FROM video_agent_action_receipts WHERE task_id=? AND decision_id=?',
        (row['task_id'],admission.get('decision_id'))).fetchone()
    if not saved:return False
    receipt=json.loads(saved['result'])
    expected={'decision_id':admission.get('decision_id'),'kind':'retry_repaired',**receipt}
    events=db.execute("SELECT id,detail,created FROM events WHERE task_id=? AND kind='video_agent_action' ORDER BY id DESC",
        (row['task_id'],)).fetchall()
    event=next((e for e in events if json.loads(e['detail'])==expected),None)
    if not event:return False
    recovery=next((r for r in reversed(cp.get('video_agent_recoveries',[]))
        if isinstance(r,dict) and {k:r.get(k) for k in ('decision_id','method_key')}==admission),None)
    if not recovery:return False
    times=(cp.get('_claim_started_at'),recovery.get('at'),row['updated'],saved['created'],event['created'])
    if not all(type(t) in (int,float) and math.isfinite(t) for t in times):return False
    if not (0<times[0]<times[1]<=times[2]<=times[3]<=times[4]):return False
    if not cp.get('_claim_token'):return False
    # Event IDs remain authoritative when worker clocks repeat or move back.
    for later in db.execute('SELECT kind,detail FROM events WHERE task_id=? AND id>?',
            (row['task_id'],event['id'])):
        detail=json.loads(later['detail'])
        if later['kind']=='source_collection_stopped':return False
        if isinstance(detail,dict) and (detail.get('job_id')==row['id']
                or row['id'] in (detail.get('job_ids') or [])):return False
    return True


def admitted_planning_children(db):
    from .video_agent_actions import _gate, _hash, ActionHeld, source_recovery_job
    from .video_agent_context import semantic_fingerprint, job_method_fingerprint, _job_method_fingerprint
    tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'video_agents','video_agent_action_receipts'}<=tables:return set()
    admitted=set()
    rows=db.execute("""SELECT * FROM jobs WHERE kind='collect_sources'
        AND status IN ('queued','paused')
        AND json_type(payload,'$.planning_recovery_from')='text'""").fetchall()
    for row in rows:
        try:
            payload=json.loads(row['payload']);checkpoint=json.loads(row['checkpoint'])
            state_row=db.execute('SELECT state FROM tasks WHERE id=?',(row['task_id'],)).fetchone()
            owner=db.execute('SELECT epoch FROM video_agents WHERE task_id=?',(row['task_id'],)).fetchone()
            if not state_row or not owner:continue
            state=json.loads(state_row['state']);parent_id=payload['planning_recovery_from']
            parent=db.execute('SELECT * FROM jobs WHERE id=? AND task_id=?',(parent_id,row['task_id'])).fetchone()
            if state.get('status')=='completed' or not source_recovery_job(state,parent):continue
            _gate(state,'continue_repaired',parent)
            if not planning_recovery_candidate(state,row):continue
            fingerprint=semantic_fingerprint(state)
            repaired=repaired_child_receipt(db,row,state,owner['epoch'])
            from .video_agent_source_wait import resolved_claimed_wait
            continued=resolved_claimed_wait(db,row,state,owner['epoch']) if not repaired else None
            repaired=bool(repaired or continued)
            if ('failure_classification' in checkpoint or 'failure_trace' in checkpoint) and not repaired:continue
            valid=False
            # Compatibility is restricted to the original durable parent
            # continuation. New repairs and approvals use the current hash.
            parent_fingerprints={job_method_fingerprint(parent),
                _job_method_fingerprint(parent,normalize_preflight=False)}
            for saved in db.execute('SELECT result,method_key FROM video_agent_action_receipts WHERE task_id=?',(row['task_id'],)):
                receipt=json.loads(saved['result'])
                if (not isinstance(receipt,dict) or receipt.get('status')!='queued'
                        or not isinstance(receipt.get('job_ids'),list) or row['id'] not in receipt['job_ids']
                        or not isinstance(receipt.get('evidence'),list)):continue
                for evidence in receipt.get('evidence',[]):
                    repair=evidence.get('repair') if isinstance(evidence,dict) else None
                    if not isinstance(repair,dict):continue
                    binding=repair.get('binding') or {}
                    if (not isinstance(binding,dict) or binding.get('task_id')!=row['task_id'] or binding.get('job_id')!=parent_id
                            or binding.get('agent_epoch')!=owner['epoch']
                            or (binding.get('input_fingerprint')!=fingerprint and not repaired)
                            or binding.get('job_fingerprint') not in parent_fingerprints
                            or not repair.get('review_binding_sha256') or not repair.get('files')):continue
                    # This durable host receipt was committed only after signed
                    # applied/loaded repair verification and exact child creation.
                    expected=_hash({'kind':'continue_repaired','binding':binding,'files':repair['files']})
                    if receipt.get('method_key')==saved['method_key']==expected:valid=True
            if not valid:continue
            if row['status']=='paused':
                if 'supervision_jobs' in tables and db.execute(
                        "SELECT 1 FROM supervision_jobs WHERE task_id=? AND phase='held'",
                        (row['task_id'],)).fetchone():continue
                # The broad rule can stop either a never-claimed continuation
                # or a freshly accepted repair before its next claim. The
                # latter requires exact durable executor and event proof.
                never_claimed=not checkpoint and not row['error'] and row['created']==row['updated']
                if not never_claimed and not (continued or (repaired and _accepted_retry_unclaimed(db,row))):continue
                db.execute("UPDATE jobs SET status='queued' WHERE id=? AND status='paused'",(row['id'],))
            admitted.add(row['id'])
        except (ActionHeld,TypeError,ValueError,KeyError,AttributeError):
            continue
    return admitted
