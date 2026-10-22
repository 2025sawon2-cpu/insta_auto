"""Claim-independent, transactional production actions for a responsible video agent.

Decisions are suggestions. Existing source/quality queues retain their contracts;
this module never calls the user-only resume command or grants media approval.
"""
from __future__ import annotations

import hashlib
import copy
import json
import math
from pathlib import Path
import time

from .studio_store import Conflict


class ActionHeld(ValueError):
    pass


def _fingerprint(state):
    from .video_agent_context import semantic_fingerprint
    return semantic_fingerprint(state)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _digest(path):
    from .supervision_evidence import _digest as digest
    return digest(Path(path))


def parser_repair_context(state, job):
    """Only diagnose a host-observed local route failure; never clear its gate."""
    if not job or job['kind'] not in {'collect_sources', 'refresh_sources'}:return False
    try:
        cp=job['checkpoint'];cp=json.loads(cp) if isinstance(cp,str) else cp
        payload=dict(job).get('payload') or {};payload=json.loads(payload) if isinstance(payload,str) else payload
    except (TypeError,ValueError):return False
    context=cp.get('parser_repair_context') or {}
    if (not state.get('run_id') or payload.get('run_id')!=state['run_id']
            or context.get('run_id')!=state['run_id'] or context.get('task_id')!=state.get('id')):return False
    if (state.get('source_acquisition') or {}).get('receipt_wait'):return False
    if (cp.get('failure_classification') or {}).get('category')=='access_blocked':return False
    rows=context.get('observations') or []
    preflight=(cp.get('source_access_preflight') or {}).get('observations') or []
    return bool(rows) and all(isinstance(row,dict) and row in preflight
        and row.get('status')=='readiness_blocked' and row.get('reason')=='page_unresolved'
        and row.get('manual_gate_active') is False
        and (row.get('readiness') or {}).get('reason')=='page_unresolved'
        and (row.get('readiness') or {}).get('parser_revision')
        and not (row.get('readiness') or {}).get('recheck_requested') for row in rows)


def repair_has_available_route(state,job):
    """Internal contract repair may use an already observed unblocked route.

    This does not clear platform holds or authorize requests to a blocked route;
    the resumed source worker must perform its normal access preflight again.
    """
    if parser_repair_context(state,job):return True
    if not job or job['kind'] not in {'collect_sources','refresh_sources'}:return False
    cp=job['checkpoint'];cp=json.loads(cp) if isinstance(cp,str) else cp
    payload=dict(job).get('payload') or {};payload=json.loads(payload) if isinstance(payload,str) else payload
    if not state.get('run_id') or payload.get('run_id')!=state['run_id']:return False
    classification=cp.get('failure_classification') or {}
    if classification.get('category')!='input_validation':return False
    material=classification.get('signature_material') or {}
    trace=cp.get('failure_trace') or {}
    # This typed failure is raised while validating the query proposal, before
    # the current source attempt can submit a platform search. Generic input
    # failures (including download failures) do not qualify for this exception.
    if (material.get('exception_type')!='hotpost.source_visual_queries.VisualQueryRejection'
            or material.get('stage')!='collect_sources' or trace.get('type')!='VisualQueryRejection'
            or trace.get('stage')!='collect_sources'
            or not any(frame.get('function')=='cached_visual_queries' for frame in trace.get('frames',[]))):return False
    waiting=(state.get('source_acquisition') or {}).get('waiting') or {}
    since=waiting.get('at')
    if type(since) not in (int,float) or not math.isfinite(since):return False
    blocked={row.get('provider') for row in waiting.get('searches',[])}
    preflight=cp.get('source_access_preflight') or {}
    return any(isinstance(row,dict) and type(row.get('observed_at')) in (int,float)
        and math.isfinite(row['observed_at'])
        and row.get('provider') not in blocked and row.get('provider') in preflight.get('ready_routes',[])
        and row.get('status')=='ready' and row.get('reason')=='current_existing_page_observed'
        and row['observed_at']>=since for row in preflight.get('observations',[]))


def local_topic_repair_context(state, job):
    """Recognize an intact failed preparation, never grant search permission.

    Existing transaction/repair executors still verify current owner epoch,
    semantic/job fingerprints, signed review, exact applied bytes, loaded process,
    idle queues, cooldown, and unchanged method budget.
    """
    from .source_visual_queries import digest
    from .source_quality import sha256_file
    from .source_topic_queries import _validate
    try:
        job = dict(job)
        payload = job.get('payload') or {}
        cp = job.get('checkpoint') or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(cp, str):
            cp = json.loads(cp)
        if (job.get('kind') != 'collect_sources'
                or job.get('status') not in {'failed', 'paused'}
                or job.get('task_id') != state.get('id')
                or not state.get('run_id')
                or payload.get('run_id') != state['run_id']
                or payload.get('source_policy') != state.get('source_policy')):
            return False
        acquisition = state.get('source_acquisition') or {}
        if acquisition.get('hold') or acquisition.get('receipt_wait'):
            return False
        # This proposal deliberately covers NB's old connection failure only.
        # Login/CAPTCHA/429/denial are not brought under the local exception.
        for row in (acquisition.get('waiting') or {}).get('searches', []):
            if (not isinstance(row, dict)
                    or row.get('provider') != 'browser-worker'
                    or row.get('status') != 'connection_failed'):
                return False
        classification = cp.get('failure_classification') or {}
        material = classification.get('signature_material') or {}
        trace = cp.get('failure_trace') or {}
        if (classification.get('category') != 'input_validation'
                or material.get('exception_type') !=
                'hotpost.source_visual_queries.VisualQueryRejection'
                or material.get('stage') != 'collect_sources'
                or trace.get('type') != 'VisualQueryRejection'
                or trace.get('stage') != 'collect_sources'):
            return False
        frames = trace.get('frames') or []
        if (not any(r.get('function') == '_prepare_source_queries'
                    and Path(r.get('path', '')).name == 'studio_sources.py'
                    for r in frames)
                or not any(r.get('function') == 'cached_topic_queries'
                    and Path(r.get('path', '')).name == 'source_topic_queries.py'
                    for r in frames)):
            return False
        owner = {'task_id': state['id'], 'job_id': job['id'],
                 'run_id': state['run_id']}
        rejected = acquisition.get('visual_query_rejection') or {}
        evidence = rejected.get('evidence') or {}
        input_sha = digest(evidence)
        if (rejected.get('binding') != owner or evidence.get('owner') != owner
                or evidence.get('policy') != 'natural-topic-search-v1'
                or evidence.get('discovery_contract_version') != 4
                or evidence.get('subject_hint') != state.get('product')
                or evidence.get('search_minimums') !=
                    (state.get('source_policy') or {}).get('search_minimums')
                or rejected.get('input_sha256') != input_sha
                or cp.get('visual_query_input') !=
                    {**owner, 'input_sha256': input_sha}):
            return False
        files = rejected.get('files') or []
        if len(files) != 2:
            return False
        proposal_path = Path(files[0]['path']).resolve()
        root = proposal_path.parent
        if (root.parent.name != 'source-topic-query-receipts'
                or root.name != digest({'evidence': evidence, 'owner': owner})):
            return False
        for row, name in zip(files, ('proposal.json', 'review.json')):
            path = root / name
            if (Path(row['path']).resolve() != path
                    or sha256_file(path) != row['sha256']):
                return False
        reference_sha = evidence.get('reference_sha256')
        if (reference_sha != rejected.get('reference_sha256')
                or sha256_file(Path(state['reference_video'])) != reference_sha
                or sha256_file(Path(evidence['reference_path'])) != reference_sha):
            return False
        for row in evidence['frames']:
            if sha256_file(Path(row['path'])) != row['sha256']:
                return False
        saved = json.loads(proposal_path.read_text('utf-8'))
        review = json.loads((root / 'review.json').read_text('utf-8'))
        proposal = saved['proposal']
        if (saved.get('input_sha256') != input_sha
                or review.get('input_sha256') != input_sha
                or review.get('proposal_sha256') != digest(proposal)
                or review.get('search_only') is not True
                or review.get('subject_identity_supported') is not True
                or not any(r.get('kind') in {'brand', 'model'}
                    and r.get('source') == 'visual'
                    for r in proposal.get('subject_identity', {}).get('required_terms', []))):
            return False
        try:
            _validate(proposal, review, evidence)  # REAL validator, unchanged.
        except ValueError as exc:
            return str(exc) == '시각 고정 조건의 실제 관찰 근거가 없습니다.'
        return False  # Already-valid old input is not this diagnosed incident.
    except (TypeError, ValueError, KeyError, OSError, AttributeError):
        return False



def quality_recovery_job(state, job):
    """A finished QA execution may still leave this selected edit unresolved.

    This is repair context, never permission to rerun or approve that QA job.
    """
    if not job:return False
    job=dict(job)
    if job.get('status')!='done' or job.get('kind')!='quality_review' or job.get('task_id')!=state.get('id'):return False
    payload=job.get('payload') or {}
    try:payload=json.loads(payload) if isinstance(payload,str) else payload
    except (ValueError,TypeError):return False
    if not isinstance(payload,dict):return False
    quality=state.get('daily_quality') or {}
    if quality.get('pending')!='scene_wait' or quality.get('status')!='needs_attention' or not quality.get('feedback'):return False
    if not state.get('run_id') or not state.get('edit_id') or quality.get('reviewed_edit_id')!=state['edit_id']:return False
    if any(not state.get(k) or payload.get(k)!=state[k] for k in ('script_id','voice_id','edit_id')):return False
    reviews=quality.get('reviews') or []
    return bool(reviews and reviews[-1].get('edit_id')==state['edit_id']
        and reviews[-1].get('passed') is False and reviews[-1].get('issues')==quality['feedback'])


def source_recovery_job(state,job):
    """Exact settled source round whose current internal strategy is exhausted."""
    if not job:return False
    job=dict(job)
    if job.get('status')!='done' or job.get('kind')!='collect_sources' or job.get('task_id')!=state.get('id'):return False
    acquisition=state.get('source_acquisition') or {}
    if (acquisition.get('hold') or {}).get('reason')!='strategy_exhausted':return False
    if acquisition.get('waiting') or acquisition.get('receipt_wait') or (state.get('source_goal') or {}).get('ready'):return False
    rounds=acquisition.get('rounds') or []
    if not rounds or not isinstance(rounds[-1],dict):return False
    last=rounds[-1]
    try:
        payload=job.get('payload') or {};payload=json.loads(payload) if isinstance(payload,str) else payload
        cp=job.get('checkpoint') or {};cp=json.loads(cp) if isinstance(cp,str) else cp
    except (TypeError,ValueError):return False
    if not isinstance(payload,dict) or not isinstance(cp,dict):return False
    if (cp.get('not_before') or 0)>time.time():return False
    return bool(state.get('run_id') and payload.get('run_id')==last.get('run_id')==state['run_id']
        and last.get('job_id')==job.get('id') and payload.get('round')==last.get('round')
        and last.get('manifest_path') and cp.get('manifest')==last['manifest_path']==state.get('source_search_manifest_path')
        and (cp.get('failure_classification') or {}).get('category')!='access_blocked')


def context_recovery_job(state,job):
    return quality_recovery_job(state,job) or source_recovery_job(state,job)


def _gate(state, kind, repair_job=None):
    auto = state.get('automation') or {}
    if (auto.get('paused_by_user') or auto.get('consumed_by_daily_policy')
            or auto.get('pause_reason') in {'save-script','restore-script','apply-proposal','pause-auto'}):
        raise ActionHeld('User pause or consumed run remains in force')
    source_context=kind in {'apply_context_repair','continue_repaired'} and source_recovery_job(state,repair_job)
    from .video_agent_planning_claim import planning_recovery_candidate
    planning_context=kind in {'park_for_repair','retry_repaired'} and planning_recovery_candidate(state,repair_job)
    if ((state.get('source_acquisition') or {}).get('hold') and not (source_context or planning_context)) or state.get('editorial_content_hold'):
        raise ActionHeld('Existing source/content hold requires its specific evidence resolution')
    waiting = (state.get('source_acquisition') or {}).get('waiting') or {}
    route_repair=(kind in {'park_for_repair','retry_repaired'}
        and (repair_has_available_route(state,repair_job)
             or local_topic_repair_context(state,repair_job)))
    if (waiting.get('searches') and not route_repair) or ((state.get('source_acquisition') or {}).get('receipt_wait')
                                 and kind not in {'park_for_repair','retry_repaired'}):
        raise ActionHeld('Access or unsettled-receipt wait must be resolved before production')
    quality = state.get('daily_quality') or {}
    if kind == 'quality_review' and quality.get('pending') in {'rewrite','reedit','recollect','recheck','stop_method'}:
        raise ActionHeld('Existing quality defects require their recorded repair method before review')
    if kind == 'collect_sources' and state.get('creation_mode') == 'self_shot':
        raise ActionHeld('Self-shot production does not collect external sources')
    contextual_repair=kind in {'apply_context_repair','continue_repaired'} and quality_recovery_job(state,repair_job)
    if (quality.get('pending') in {'exhausted', 'scene_wait'} and not contextual_repair) or quality.get('narration_context_hold'):
        raise ActionHeld('Quality evidence hold remains in force')
    if quality.get('pending') == 'failed' and kind not in {'retry', 'retry_repaired','park_for_repair'}:
        raise ActionHeld('Failed quality job needs a verified recovery method')
    if not auto.get('active'):
        raise ActionHeld('Automatic production is not active')
    if state.get('status') == 'completed':
        raise ActionHeld('Completed production is preserved')


def capabilities(studio, state):
    result = []
    repair_job=None
    if ((state.get('source_acquisition') or {}).get('waiting') or {}).get('searches'):
        with studio.store.connect() as db:
            for row in db.execute("SELECT * FROM jobs WHERE task_id=? AND status IN ('failed','paused','queued')",(state['id'],)):
                if repair_has_available_route(state,row) or local_topic_repair_context(state,row):repair_job=row;break
    with studio.store.connect() as db:
        if repair_job is None:
            from .video_agent_planning_claim import planning_recovery_candidate
            repair_job=next((r for r in db.execute("SELECT * FROM jobs WHERE task_id=? AND status IN ('failed','paused','queued') ORDER BY updated DESC",(state['id'],))
                             if planning_recovery_candidate(state,r)),None)
        quality_job=next((r for r in db.execute("SELECT * FROM jobs WHERE task_id=? AND status='done' AND kind IN ('quality_review','collect_sources') ORDER BY updated DESC",(state['id'],)) if context_recovery_job(state,r)),None)
    for kind in ('advance', 'collect_sources', 'repair_scenes', 'quality_review', 'retry', 'retry_repaired', 'park_for_repair','recover_preparation','continue_repaired'):
        try:
            if kind=='continue_repaired' and not quality_job:continue
            _gate(state, kind,quality_job if kind=='continue_repaired' else repair_job)
        except ActionHeld:
            continue
        if kind == 'repair_scenes' and (state.get('daily_quality') or {}).get('pending') != 'recollect':
            continue
        if kind == 'quality_review' and not state.get('edit_id'):
            continue
        if kind == 'collect_sources' and state.get('creation_mode') == 'self_shot':
            continue
        if kind == 'recover_preparation':
            from .video_agent_recovery import OVERLAY_FAILURE,preparation_ready
            if (state.get('error')!=OVERLAY_FAILURE or state.get('automation',{}).get('protocol')!=2
                    or any(state.get(k) for k in ('scripts','voices','edits')) or not preparation_ready(studio,state)):continue
        result.append(kind)
    return result


def _evidence(studio, state, action):
    """Only current selected assets can establish production input evidence."""
    allowed = {}
    for field in ('reference_video','transcript_path','manifest_path'):
        if state.get(field):allowed[str(Path(state[field]).resolve())]=state
    for collection in ('sources', 'voices', 'scripts', 'edits'):
        for row in state.get(collection, []):
            selected_ids = {'voices':{state.get('voice_id'),state.get('approved_voice_id')},
                            'scripts':{state.get('script_id'),state.get('approved_script_id')},
                            'edits':{state.get('edit_id')}}
            if collection in selected_ids and row.get('id') not in selected_ids[collection]:
                continue
            for field in ('path', 'plan_path', 'preview_path', 'export_path'):
                if row.get(field):
                    allowed[str(Path(row[field]).resolve())] = row
    result = []
    for reference in action.get('evidence') or []:
        if not isinstance(reference, dict) or not reference.get('path') or not reference.get('sha256'):
            raise ActionHeld('Evidence requires an exact artifact path and SHA')
        path = str(Path(reference['path']).resolve())
        if path not in allowed or not Path(path).is_file() or _digest(path) != reference['sha256']:
            raise ActionHeld('Evidence is not a current, unchanged task artifact')
        result.append({'path': path, 'sha256': reference['sha256']})
    return result


def _changed_input(db, old, state, evidence, signature):
    baseline = (old['checkpoint'].get('retry_budget') or {}).get('fingerprint')
    if not baseline or baseline == signature or not evidence:
        return False
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='retry_budget_attempts'").fetchone():
        return False
    row = db.execute('SELECT material FROM retry_budget_attempts WHERE fingerprint=? AND task_id=? AND job_id=? ORDER BY id DESC LIMIT 1',
                     (baseline,state['id'],old['id'])).fetchone()
    if not row:
        return False
    material = json.loads(row['material'])
    previous_shas = {s.get('sha256') for s in material.get('sources',[])}
    previous_shas.add((material.get('selected_voice') or {}).get('sha256'))
    # New identifiers, output paths, hypotheses or code hashes cannot establish
    # new media inputs. Require actual new selected media bytes absent at failure.
    current = [*state.get('sources',[])]
    voice = _selected(state,'voices','approved_voice_id')
    if voice: current.append(voice)
    return any(reference['sha256'] not in previous_shas
               and any(asset.get('sha256') == reference['sha256'] and asset.get('path')
                       and str(Path(asset['path']).resolve()) == reference['path'] for asset in current)
               for reference in evidence)


def _selected(state, collection, field):
    return next((row for row in state.get(collection, []) if row.get('id') == state.get(field)), None)


def _jobs(db, task_id):
    return {row['id']: dict(row) for row in db.execute(
        'SELECT id,kind,status FROM jobs WHERE task_id=?', (task_id,))}


def _quality_inputs(state, action):
    edit = _selected(state, 'edits', 'edit_id')
    voice = _selected(state, 'voices', 'approved_voice_id')
    script = _selected(state, 'scripts', 'approved_script_id')
    if not edit or not voice or not script or edit.get('voice_id') != voice['id'] or edit.get('script_id') != script['id']:
        raise ActionHeld('Latest edit must match the approved voice and script')
    if state.get('script_id') != script['id'] or state.get('voice_id') != voice['id'] or voice.get('script_id') != script['id']:
        raise ActionHeld('Approved narration must also be the currently selected narration')
    if action.get('edit_id') != edit['id']:
        raise ActionHeld('Decision does not target the latest edit')
    render = edit.get('export_path') or edit.get('preview_path')
    plan = edit.get('plan_path')
    if not render or not plan or not Path(render).is_file() or not Path(plan).is_file():
        raise ActionHeld('Rendered video and exact plan are required')
    render_sha, plan_sha = _digest(render), _digest(plan)
    if action.get('render_sha256') != render_sha or action.get('plan_sha256') != plan_sha:
        raise ActionHeld('Render or plan SHA changed after the decision')
    return edit, voice, script, render_sha, plan_sha


def _release_exact_hold(db, task_id, job_id, decision_id, method_key, evidence):
    job=db.execute('SELECT checkpoint FROM jobs WHERE task_id=? AND id=?',(task_id,job_id)).fetchone()
    if job and (json.loads(job['checkpoint']).get('failure_classification') or {}).get('category')=='access_blocked':
        raise ActionHeld('Access failure needs verified session recovery; media/code changes cannot release its hold')
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='supervision_jobs'").fetchone():
        return
    row = db.execute('SELECT phase,record FROM supervision_jobs WHERE task_id=? AND job_id=?',
                     (task_id, job_id)).fetchone()
    if row and row['phase'] == 'held':
        record = json.loads(row['record'])
        record.update(phase='method_changed', method_change={'decision_id': decision_id,
            'method_key': method_key, 'evidence': evidence, 'at': time.time()},
            reason='Verified method/input change; original incident retained')
        db.execute("UPDATE supervision_jobs SET phase='method_changed',record=? WHERE task_id=? AND job_id=?",
                   (json.dumps(record, ensure_ascii=False), task_id, job_id))


def _retry(studio, db, state, action, decision_id, evidence):
    row = db.execute("SELECT * FROM jobs WHERE task_id=? AND id=? AND status IN ('failed','paused')",
                     (state['id'], action.get('job_id'))).fetchone()
    if not row:
        raise ActionHeld('Exact failed/held job no longer exists')
    old = dict(row)
    old['payload'] = json.loads(old['payload']);old['checkpoint'] = json.loads(old['checkpoint'])
    payload, checkpoint = old['payload'], old['checkpoint']
    if payload.get('run_id') and payload['run_id']!=state.get('run_id'):
        raise ActionHeld('Old failed job belongs to a different video run')
    if ((state.get('source_acquisition') or {}).get('receipt_wait')
            and not (action['kind']=='retry_repaired' and checkpoint.get('internal_evidence_wait'))):
        raise ActionHeld('Unsettled receipt requires an exact internal-error repair')
    if payload.get('script_id') and payload['script_id'] != state.get('script_id'):
        raise ActionHeld('Old script job cannot be resumed against a different selected script')
    if old['kind'] in {'edit', 'revision', 'quality_reedit'} and payload.get('voice_id') != state.get('approved_voice_id'):
        raise ActionHeld('Old edit job is bound to a different approved voice')
    if old['kind'] == 'quality_review' and payload.get('edit_id') != state.get('edit_id'):
        raise ActionHeld('Old quality job is not the latest edit')
    from .retry_budget import _material, _sha, LIMIT
    classification = checkpoint.get('failure_classification') or {}
    if classification.get('category')=='access_blocked':
        raise ActionHeld('Access failure needs verified session recovery; media/code changes do not authorize a retry')
    material = _material(old, classification, state)
    signature = _sha(material)
    changed = _changed_input(db,old,state,evidence,signature)
    typed = (row['status'] == 'failed' and classification.get('retryable') is True
             and classification.get('category') in {'transport', 'http_status'}
             and classification.get('signature_material'))
    if action['kind'] == 'retry_repaired':
        # The repair executor owns validation of an applied, tested receipt.
        from .video_agent_repairs import verified_repair
        receipt = verified_repair(studio, state, action, old)
        if not receipt:
            raise ActionHeld('Applied repair/test evidence is missing or stale')
        changed = True
        evidence = [*evidence, {'repair': receipt}]
    if not changed and not typed:
        raise ActionHeld('Same failed input is not retryable without verified new material')
    held_rows = (db.execute("SELECT job_id FROM supervision_jobs WHERE task_id=? AND phase='held'",(state['id'],)).fetchall()
                 if db.execute("SELECT 1 FROM sqlite_master WHERE name='supervision_jobs'").fetchone() else [])
    if held_rows and (not changed or len(held_rows)!=1 or held_rows[0]['job_id']!=old['id']):
        raise ActionHeld('Typed retry cannot clear an unchanged or unrelated supervision hold')
    # Receipt/decision IDs are provenance, not a new repair method. The same
    # applied file contents cannot buy another attempt under a different receipt.
    repair_files = (sorted((r for r in receipt.get('files', [])), key=lambda r:json.dumps(r,sort_keys=True))
                    if action['kind']=='retry_repaired' else None)
    method_key = _hash({'kind':'retry', 'job_kind':old['kind'], 'input':signature,
                        'repair_files':repair_files})
    if changed and db.execute('SELECT 1 FROM video_agent_action_receipts WHERE task_id=? AND method_key=?',
                             (state['id'], method_key)).fetchone():
        raise ActionHeld('This changed-input method has already been attempted')
    if not changed:
        # Same durable budget as automatic worker retries, in this transaction.
        db.execute('''CREATE TABLE IF NOT EXISTS retry_budget_attempts (
            id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL, task_id TEXT NOT NULL,
            job_id TEXT NOT NULL, claim_token TEXT NOT NULL, created REAL NOT NULL,
            eligible INTEGER NOT NULL, reserved INTEGER NOT NULL, reason TEXT NOT NULL,
            classification TEXT NOT NULL, material TEXT NOT NULL)''')
        used = db.execute('SELECT COUNT(*) FROM retry_budget_attempts WHERE fingerprint=? AND reserved=1',
                          (signature,)).fetchone()[0]
        if used >= LIMIT:
            raise ActionHeld('Typed transient retry budget exhausted')
        db.execute('INSERT INTO retry_budget_attempts(fingerprint,task_id,job_id,claim_token,created,eligible,reserved,reason,classification,material) VALUES(?,?,?,?,?,1,1,?,?,?)',
                   (signature,state['id'],old['id'],'agent:'+decision_id,time.time(),'reserved',
                    json.dumps(classification),json.dumps(material)))
    if row['status'] == 'paused' and not changed:
        raise ActionHeld('A supervision hold requires verified changed input or repair')
    if row['status'] == 'paused':
        held = (db.execute("SELECT phase FROM supervision_jobs WHERE task_id=? AND job_id=?",(state['id'],old['id'])).fetchone()
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='supervision_jobs'").fetchone() else None)
        parked = (action['kind'] == 'retry_repaired'
                  and checkpoint.get('video_agent_parked_repair') == action.get('repair_id'))
        if action['kind']=='retry_repaired' and not parked:
            # A reviewed replacement repair may supersede the original parking
            # repair. Prove that parking was actually accepted for these inputs.
            prior=checkpoint.get('video_agent_park_receipt') or {}
            prior_repair=prior.get('repair') or {}
            saved=db.execute('SELECT result FROM video_agent_action_receipts WHERE task_id=? AND decision_id=?',
                (state['id'],prior.get('decision_id'))).fetchone()
            accepted=json.loads(saved['result']) if saved else {}
            parked=(accepted.get('parked') is True and receipt.get('repair_id')==action.get('repair_id')
                and prior_repair.get('repair_id')==checkpoint.get('video_agent_parked_repair')
                and all((prior_repair.get('binding') or {}).get(k)==(receipt.get('binding') or {}).get(k)
                        for k in ('task_id','job_id','agent_epoch'))
                and {'repair':prior_repair} in accepted.get('evidence',[]))
        from .production_control import held_method
        attempt=held_method(db,state['id'],old['id']) or {}
        attempt_parked=(changed and old['id'] in attempt.get('jobs',{})
            and checkpoint.get('no_progress_hold')==attempt.get('id')
            and attempt.get('run_id')==state.get('run_id'))
        if not parked and not attempt_parked and (not held or held['phase'] != 'held'):
            raise ActionHeld('Only an exact diagnosed supervision hold may be recovered automatically')
    if changed:
        _release_exact_hold(db,state['id'],old['id'],decision_id,method_key,evidence)
    if checkpoint.get('not_before', 0) > time.time():
        raise ActionHeld('Existing service cooldown has not elapsed')
    # Release the diagnostic reservation only after the normal evidence/repair
    # checks succeeded, in the same transaction as requeueing this exact job.
    db.execute("UPDATE video_agents SET record=json_remove(record,'$.recovery_job_id') WHERE task_id=? AND json_extract(record,'$.recovery_job_id')=?",(state['id'],old['id']))
    checkpoint.setdefault('video_agent_recoveries', []).append({'decision_id':decision_id,
        'method_key':method_key,'changed_input':changed,'evidence':evidence,'at':time.time()})
    if action['kind']=='retry_repaired':
        checkpoint['video_agent_retry_admission']={'decision_id':decision_id,'method_key':method_key}
    else:checkpoint.pop('video_agent_retry_admission',None)
    if old['kind'] in {'voice','rewrite'}:
        checkpoint['retry_requested'] = True
    db.execute("UPDATE jobs SET status='queued',error='',checkpoint=?,updated=? WHERE id=? AND status IN ('failed','paused')",
               (json.dumps(checkpoint,ensure_ascii=False),time.time(),old['id']))
    state.update(error='', message='영상 책임 에이전트가 검증한 복구 방법으로 이어갑니다')
    return {'status':'queued','job_ids':[old['id']], 'method_key':method_key,'evidence':evidence}


def _park_for_repair(studio, db, state, action, decision_id):
    """Bind a queued or proven internally deferred job to a signed repair."""
    row = db.execute("SELECT * FROM jobs WHERE task_id=? AND id=? AND status IN ('queued','paused')",
                     (state['id'],action.get('job_id'))).fetchone()
    if not row:
        raise ActionHeld('Only the exact queued job may be parked for an approved repair')
    if row['status']=='paused':
        from .video_agent_planning_claim import internal_wait_parking_proof
        if not internal_wait_parking_proof(db,state,row):
            raise ActionHeld('Paused job lacks exact internal-defer evidence for signed repair parking')
    pipeline = getattr(studio,'video_repair_pipeline',None)
    validate = getattr(pipeline,'ready_to_apply',None)
    if not callable(validate):
        raise ActionHeld('Signed repair approval verifier is unavailable')
    try:
        receipt = validate(action.get('repair_id'))
    except (ValueError,OSError) as exc:
        raise ActionHeld('Repair approval is unavailable or stale: '+str(exc)) from exc
    if not isinstance(receipt,dict):
        raise ActionHeld('Exact repair approval or dependency snapshot is stale. Use propose_patch with prior_repair_id='+str(action.get('repair_id'))+' to restage current inputs/dependencies, then test and independently review again.')
    checkpoint = json.loads(row['checkpoint'])
    if (checkpoint.get('failure_classification') or {}).get('category')=='access_blocked':
        raise ActionHeld('Access-blocked job requires verified session recovery before code repair')
    if not checkpoint.get('video_agent_job_fingerprint') or not (receipt.get('binding') or {}).get('job_fingerprint'):
        raise ActionHeld('Legacy repair lacks exact job inputs; propose_patch with prior_repair_id='+str(action.get('repair_id'))+', then test and independently review again')
    if checkpoint.get('video_agent_job_fingerprint'):
        from .video_agent_context import job_method_fingerprint
        current_job=job_method_fingerprint(row)
        if (current_job!=checkpoint['video_agent_job_fingerprint']
                or (receipt.get('binding') or {}).get('job_fingerprint')!=current_job
                or (action.get('_expected_job_signature') and action['_expected_job_signature']!=current_job)):
            raise ActionHeld('Reviewed repair job method changed; restage, test and review current job inputs')
    if ((state.get('source_acquisition') or {}).get('receipt_wait')
            and not checkpoint.get('internal_evidence_wait')):
        raise ActionHeld('Unsettled receipt is not a diagnosed internal-error repair')
    fingerprint = checkpoint.get('video_agent_input_fingerprint')
    expected = {'task_id':state['id'],'job_id':row['id'],
                'input_fingerprint':fingerprint,'agent_epoch':action['_agent_epoch']}
    if (not fingerprint or fingerprint != _fingerprint(state) or receipt.get('repair_id') != action.get('repair_id')
            or any((receipt.get('binding') or {}).get(k)!=v for k,v in expected.items())):
        raise ActionHeld('Reviewed repair is bound to a different task, job, input or owner. For the same task/job/owner, use propose_patch with prior_repair_id='+str(action.get('repair_id'))+' to bind current inputs, then test and independently review again.')
    method_key = _hash({'kind':'park_for_repair','binding':expected,'repair_files':receipt.get('files')})
    checkpoint['video_agent_parked_repair'] = receipt['repair_id']
    checkpoint['video_agent_park_receipt'] = {'decision_id':decision_id,'at':time.time(),'repair':receipt}
    updated = db.execute("UPDATE jobs SET status='paused',checkpoint=?,updated=? WHERE task_id=? AND id=? AND status=?",
        (json.dumps(checkpoint,ensure_ascii=False),time.time(),state['id'],row['id'],row['status']))
    if updated.rowcount != 1:
        raise ActionHeld('Queued job ownership changed before repair parking')
    return {'status':'completed','job_ids':[row['id']],'parked':True,
            'method_key':method_key,'evidence':[{'repair':receipt}]}


def _continue_repaired(studio,db,state,action):
    row=db.execute('SELECT * FROM jobs WHERE id=? AND task_id=?',(action.get('job_id'),state['id'])).fetchone()
    if not context_recovery_job(state,row):raise ActionHeld('Current unresolved completed-work context is required')
    old=dict(row)
    for key in ('payload','checkpoint'):old[key]=json.loads(old[key])
    from .video_agent_repairs import verified_repair
    receipt=verified_repair(studio,state,action,old)
    if not receipt:raise ActionHeld('Applied repair/test evidence is missing or stale')
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='supervision_jobs'").fetchone():
        if db.execute("SELECT 1 FROM supervision_jobs WHERE task_id=? AND phase='held'",(state['id'],)).fetchone():
            raise ActionHeld('Existing supervision hold requires its specific recovery')
    key=_hash({'kind':'continue_repaired','binding':receipt['binding'],'files':receipt['files']})
    if db.execute('SELECT 1 FROM video_agent_action_receipts WHERE task_id=? AND method_key=?',(state['id'],key)).fetchone():
        raise ActionHeld('Same repaired continuation already executed')
    before=_jobs(db,state['id'])
    quality=state.get('daily_quality') or {}
    qa_evidence=copy.deepcopy({k:quality.get(k) for k in ('reviewed_edit_id','feedback','reviews')})
    source_hold=copy.deepcopy((state.get('source_acquisition') or {}).get('hold'))
    studio._advance_auto(state,db)
    after=_jobs(db,state['id'])
    if any(before[j]['status']!=after[j]['status'] for j in before):
        raise ActionHeld('Quality continuation cannot change prior job outcomes')
    if dict(db.execute('SELECT * FROM jobs WHERE id=?',(old['id'],)).fetchone())!=dict(row):
        raise ActionHeld('Original completed QA evidence must remain unchanged')
    if state.get('daily_quality',{}).get('status')=='passed' or state.get('status')=='completed':
        raise ActionHeld('Code continuation cannot approve media')
    if any(state.get('daily_quality',{}).get(k)!=v for k,v in qa_evidence.items()):
        raise ActionHeld('Existing QA failure evidence must remain unchanged')
    if (state.get('source_acquisition') or {}).get('hold')!=source_hold:
        raise ActionHeld('Internal source hold must remain until normal worker evidence resolves it')
    created=[j for j in after if j not in before]
    if not created:raise ActionHeld('Repaired workflow found no eligible next operation; original hold is preserved')
    return {'status':'queued','job_ids':created,'method_key':key,'evidence':[{'repair':receipt}]}


def execute(studio, task_id, action, decision_id, expected_fingerprint):
    """Apply one decision atomically, retaining holds, history and queue ownership."""
    if not isinstance(action, dict) or not isinstance(decision_id, str) or not decision_id:
        return {'status':'held','reason':'Invalid action/decision identity'}
    kind = action.get('kind')
    if kind not in {'advance','collect_sources','repair_scenes','quality_review','retry','retry_repaired','park_for_repair','recover_preparation','continue_repaired'}:
        return {'status':'held','reason':'Unsupported production action'}
    if not isinstance(action.get('hypothesis'), str) or not action['hypothesis'].strip():
        return {'status':'held','reason':'A concrete method hypothesis is required'}
    result = {}
    def apply(state, db):
        db.execute('''CREATE TABLE IF NOT EXISTS video_agent_action_receipts (
            task_id TEXT NOT NULL, decision_id TEXT NOT NULL, action_sha TEXT NOT NULL,
            method_key TEXT NOT NULL, result TEXT NOT NULL, created REAL NOT NULL,
            PRIMARY KEY(task_id,decision_id))''')
        existing = db.execute('SELECT action_sha,result FROM video_agent_action_receipts WHERE task_id=? AND decision_id=?',
                              (task_id,decision_id)).fetchone()
        if existing:
            if existing['action_sha'] != _hash(action):
                raise ActionHeld('Decision identity was reused with a different action')
            result.update(json.loads(existing['result']));return
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='video_agents'").fetchone():
            raise ActionHeld('Responsible-agent enrollment is missing')
        owner = db.execute('SELECT epoch FROM video_agents WHERE task_id=?',(task_id,)).fetchone()
        if not owner or type(action.get('_agent_epoch')) is not int or owner['epoch'] != action['_agent_epoch']:
            raise ActionHeld('Responsible-agent ownership changed since the decision')
        if _fingerprint(state) != expected_fingerprint:
            raise ActionHeld('Task semantic input changed since the decision')
        if action.get('_expected_revision',state['revision'])!=state['revision']:
            raise ActionHeld('Task revision changed before explicit attempt resume')
        from .production_control import held_method, admit
        attempt=held_method(db,task_id,action.get('job_id'))
        if attempt:
            if action.get('hold_id')!=attempt['id'] or kind not in {'retry','retry_repaired','continue_repaired'}:
                raise ActionHeld('Held attempt requires its exact hold_id and a verified resolution')
            if kind=='retry' and not action.get('evidence'):
                raise ActionHeld('Held attempt requires actual changed-input evidence')
        if not admit(db,task_id):
            raise ActionHeld('Another video must finish its current final QA before this action')
        repair_job=(db.execute('SELECT * FROM jobs WHERE id=? AND task_id=?',(action.get('job_id'),task_id)).fetchone()
                    if kind in {'park_for_repair','retry_repaired','continue_repaired'} else None)
        _gate(state, kind,repair_job)
        evidence = _evidence(studio,state,action)
        before = _jobs(db,task_id)
        if any(j['status']=='running' or (j['status']=='queued' and kind!='park_for_repair') for j in before.values()):
            raise ActionHeld('Existing production job must settle before another action')
        method_key = _hash({'kind':kind,'input':expected_fingerprint})
        if kind == 'continue_repaired':
            result.update(_continue_repaired(studio,db,state,action))
            method_key=result['method_key']
        elif kind == 'recover_preparation':
            from .video_agent_recovery import recover_preparation
            result.update(recover_preparation(studio,db,state,action,decision_id))
            method_key=result['method_key']
        elif kind == 'park_for_repair':
            result.update(_park_for_repair(studio,db,state,action,decision_id))
            method_key = result['method_key']
        elif kind in {'retry','retry_repaired'}:
            result.update(_retry(studio,db,state,action,decision_id,evidence))
            method_key = result['method_key']
        else:
            if db.execute('SELECT 1 FROM video_agent_action_receipts WHERE task_id=? AND method_key=?',
                          (task_id,method_key)).fetchone():
                raise ActionHeld('Same production method/input already executed')
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='supervision_jobs'").fetchone():
                held = db.execute("SELECT job_id FROM supervision_jobs WHERE task_id=? AND phase='held'",(task_id,)).fetchall()
                if held:
                    if len(held)!=1 or held[0]['job_id']!=action.get('held_job_id') or kind not in {'collect_sources','repair_scenes'}:
                        raise ActionHeld('Exact held method requires a separately verified recovery')
                    failed = db.execute('SELECT * FROM jobs WHERE id=? AND task_id=?',(action['held_job_id'],task_id)).fetchone()
                    if not failed:
                        raise ActionHeld('Held job evidence no longer exists')
                    old=dict(failed);old['payload']=json.loads(old['payload']);old['checkpoint']=json.loads(old['checkpoint'])
                    from .retry_budget import _material,_sha
                    signature=_sha(_material(old,old['checkpoint'].get('failure_classification') or {},state))
                    if not _changed_input(db,old,state,evidence,signature):
                        raise ActionHeld('New collection/scene method has no verified input change since the hold')
                    _release_exact_hold(db,task_id,old['id'],decision_id,method_key,evidence)
            if kind == 'advance':
                studio._advance_auto(state,db)
            elif kind == 'collect_sources':
                studio.ensure_source_collection(state,db)
            elif kind == 'repair_scenes':
                quality = state.get('daily_quality') or {}
                if quality.get('pending') != 'recollect' or not quality.get('feedback'):
                    raise ActionHeld('Bound, unresolved scene feedback is required')
                studio.advance_daily_quality(state,db,_selected(state,'scripts','script_id'),
                    _selected(state,'voices','voice_id'),_selected(state,'edits','edit_id'))
            elif kind == 'quality_review':
                edit,voice,script,render_sha,plan_sha = _quality_inputs(state,action)
                from .daily_quality import REVIEW_INSTRUCTION
                contract = hashlib.sha256(REVIEW_INSTRUCTION.encode()).hexdigest()
                key = 'agent-quality:'+edit['id']+':'+render_sha+':'+plan_sha+':'+contract
                if db.execute('SELECT 1 FROM jobs WHERE key=?',(key,)).fetchone():
                    raise ActionHeld('Same render/plan/review contract already queued or reviewed')
                jid=studio.store.enqueue(db,task_id,'quality_review',{'edit_id':edit['id'],
                    'voice_id':voice['id'],'script_id':script['id'],'render_sha256':render_sha,
                    'plan_sha256':plan_sha,'review_contract_sha256':contract,'agent_bound_review':True},key)
                state.update(status='quality_review',message='현재 완성 영상과 계획의 실제 품질 검토')
                state.setdefault('daily_quality',{}).update(status='pending',pending='quality_review')
            after = _jobs(db,task_id)
            if any(before[j]['status'] in {'failed','paused'} and after[j]['status']=='queued' for j in before):
                raise ActionHeld('Normal advancement cannot resurrect a failed or held method')
            created = [j for j in after if j not in before]
            result.update(status='queued' if created else 'completed',job_ids=created,method_key=method_key,evidence=evidence)
            if not created and kind != 'advance':
                raise ActionHeld('Existing workflow found no eligible new operation')
        if attempt:
            from .production_control import release
            release(db,state,action,decision_id,result)
        db.execute('INSERT INTO video_agent_action_receipts VALUES(?,?,?,?,?,?)',
                   (task_id,decision_id,_hash(action),method_key,json.dumps(result,ensure_ascii=False),time.time()))
        studio.store.event(db,task_id,'video_agent_action',{'decision_id':decision_id,'kind':kind,**result})
    try:
        studio.store.change(task_id,apply)
    except (ActionHeld,Conflict,FileNotFoundError) as exc:
        return {'status':'held','reason':str(exc),'decision_id':decision_id}
    return result
