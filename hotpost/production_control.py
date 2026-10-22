"""Durable video admission and evidence-bound no-progress holds.

These gates grant neither access nor media approval. Existing worker, retry and
quality validators still decide whether an admitted operation may run.
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
import uuid
from pathlib import Path


def ensure(db):
    db.execute('''CREATE TABLE IF NOT EXISTS production_slot (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        task_id TEXT NOT NULL, acquired REAL NOT NULL, completion TEXT)''')


def owner_record(db, task_id):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='video_agents'").fetchone():
        return {}
    row = db.execute('SELECT record FROM video_agents WHERE task_id=?', (task_id,)).fetchone()
    return json.loads(row[0]) if row else {}


def hold(db, task_id):
    return owner_record(db, task_id).get('no_progress_hold')


def held_method(db, task_id, job_id):
    record=owner_record(db,task_id)
    return record.get('no_progress_hold') or (record.get('held_method_incidents') or {}).get(job_id)


def admit(db, task_id):
    """Reserve one entire video in the caller's BEGIN IMMEDIATE transaction.

    Pausing/failure never releases its turn. Only the current file/plan QA and
    settled production queue let the next video enter. Constructors do not elect.
    """
    ensure(db)
    slot = db.execute('SELECT * FROM production_slot WHERE singleton=1').fetchone()
    if slot:
        row = db.execute('SELECT state FROM tasks WHERE id=?', (slot['task_id'],)).fetchone()
        busy = db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('queued','running')",
                          (slot['task_id'],)).fetchone()
        from .video_agent_context import completion
        done = completion(json.loads(row[0])) if row and not busy and not hold(db, slot['task_id']) else None
        if done:
            db.execute('DELETE FROM production_slot WHERE singleton=1')
            db.execute('INSERT INTO events(task_id,kind,detail,created) VALUES(?,?,?,?)',
                       (slot['task_id'], 'production_turn_completed', json.dumps(done), time.time()))
        else:
            return slot['task_id'] == task_id
    # Adopt existing running work; never start a second video beside it.
    running = db.execute("SELECT DISTINCT task_id FROM jobs WHERE status='running'").fetchall()
    if len(running) > 1:
        return False
    if running:
        chosen = running[0][0]
    else:
        row = db.execute('''SELECT id FROM tasks t
            WHERE (COALESCE(json_extract(state,'$.automation.paused_by_user'),0)<>1 OR EXISTS (
                SELECT 1 FROM jobs manual WHERE manual.task_id=t.id AND manual.status='queued'
                AND ((manual.kind='refresh_sources'
                    AND json_extract(manual.payload,'$.manual_source_request')=1
                    AND json_extract(manual.payload,'$.pause_token')=json_extract(t.state,'$.automation.paused_at'))
                    OR json_extract(manual.payload,'$.launch')=1)))
              AND (json_extract(state,'$.automation.active')=1 OR EXISTS (
                  SELECT 1 FROM jobs j WHERE j.task_id=t.id AND j.status='queued'))
              AND (COALESCE(json_extract(state,'$.status'),'')<>'completed' OR EXISTS (
                  SELECT 1 FROM jobs j WHERE j.task_id=t.id AND j.status='queued'))
            ORDER BY COALESCE(json_extract(state,'$.automation.priority'),0) DESC,
                     COALESCE(json_extract(state,'$.automation.rank'),2147483647),
                     COALESCE(json_extract(state,'$.created'),updated),id LIMIT 1''').fetchone()
        chosen = row[0] if row else None
    if chosen is None:
        return False
    db.execute('INSERT INTO production_slot VALUES(1,?,?,NULL)', (chosen, time.time()))
    return chosen == task_id


def refusal(reason):
    """Recognize existing exhausted-method guards, not ordinary tool failures."""
    return any(text in str(reason) for text in (
        '진단 예산 소진', '동일 입력에서 실패한 같은 행동',
        'Same production method/input already executed',
        'This changed-input method has already been attempted'))


def park(store, task_id, epoch, reason, observation, decision_id):
    """Freeze only this attempt, retaining the responsible owner and exact jobs."""
    from .video_agent_context import semantic_fingerprint, job_method_fingerprint
    with store.transaction() as db:
        from .video_agents import ensure as ensure_owner_tables
        ensure_owner_tables(db)
        row = db.execute('SELECT epoch,record FROM video_agents WHERE task_id=?', (task_id,)).fetchone()
        if not row or row['epoch'] != epoch:
            return None
        record = json.loads(row['record'])
        if record.get('no_progress_hold'):
            return record['no_progress_hold']
        state = store.get(task_id, db)
        if state.get('automation', {}).get('paused_by_user'):
            return None
        jobs = [dict(r) for r in db.execute('SELECT * FROM jobs WHERE task_id=?', (task_id,))]
        if any(j['status'] == 'running' for j in jobs):
            return None  # A progressing worker is not a failed diagnostic loop.
        bound = [j for j in jobs if j['status'] in {'queued', 'failed', 'paused'}]
        incident = {
            'id': 'hold-' + uuid.uuid4().hex, 'task_id': task_id,
            'run_id': state.get('run_id'), 'epoch': epoch, 'at': time.time(),
            'input_fingerprint': semantic_fingerprint(state), 'reason': str(reason),
            'decision_id': decision_id, 'observation': copy.deepcopy(observation),
            'jobs': {j['id']: {'status': j['status'], 'kind': j['kind'], 'error':j.get('error'),
                     'failure':json.loads(j['checkpoint']).get('failure_classification'),
                     'fingerprint': job_method_fingerprint(j)} for j in bound},
            'responsible_owner': task_id, 'resolution_status': 'needs_resolution',
            'next_action': 'Resolve the recorded cause in a separate repair or evidence step; '
                           'then use the guarded resume-held-attempt/retry_repaired route.',
            'resume_condition': 'Verified changed material or tested/reviewed/applied/loaded repair; '
                                'current owner, run, input, access and quality gates remain required.',
            'checkpoint': {key: state.get(key) for key in
                           ('script_id', 'approved_script_id', 'voice_id', 'approved_voice_id', 'edit_id')},
        }
        for j in bound:
            if j['status'] == 'queued':
                cp = json.loads(j['checkpoint']); cp['no_progress_hold'] = incident['id']
                db.execute("UPDATE jobs SET status='paused',checkpoint=? WHERE id=? AND status='queued'",
                           (json.dumps(cp), j['id']))
        record.update(status='held', no_progress_hold=incident, pending=None,
                      next_at=0, blocked_observation=None, recovery_mode=False,
                      last_result={'status': 'held', 'reason': reason, 'hold_id': incident['id']})
        db.execute('UPDATE video_agents SET record=?,updated=? WHERE task_id=? AND epoch=?',
                   (json.dumps(record, ensure_ascii=False), time.time(), task_id, epoch))
        store.event(db, task_id, 'production_attempt_held', incident)
        if decision_id:
            db.execute('''INSERT INTO video_agent_steps(task_id,epoch,decision_id,observation,created)
                VALUES(?,?,?,?,?) ON CONFLICT(task_id,decision_id) DO UPDATE SET observation=excluded.observation''',
                       (task_id, epoch, decision_id, json.dumps(observation, ensure_ascii=False), time.time()))
    write_record(store, incident)
    return incident


def write_record(store, incident):
    """A durable DB incident remains authoritative if its Markdown projection fails."""
    task_key=hashlib.sha256(incident['task_id'].encode()).hexdigest()[:24]
    folder = store.root / 'production-records' / task_key
    target = folder / (incident['id'] + '.md')
    content = ('# 영상 제작 시도 보류 및 해결 인계\n\n'
               '- 발생 당시 상태: needs_resolution · 영상 미완료\n'
               '- 후속 해결/재개 상태: 같은 폴더 source-search-*.md 및 DB production_attempt_* event\n'
               '- 해결 담당: 기존 영상 담당자 유지\n'
               '- 다음 행동: 원인별 별도 수정/근거 확보 → 검증된 명시 재개 → 같은 영상 최종 QA\n\n'
               '```json\n' + json.dumps(incident, ensure_ascii=False, indent=2) + '\n```\n')
    try:
        folder.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.tmp')
        temporary.write_text(content, encoding='utf-8')
        temporary.replace(target)
    except OSError as exc:
        with store.transaction() as db:
            store.event(db, incident['task_id'], 'production_record_write_failed',
                        {'hold_id': incident['id'], 'error': str(exc)})


def release(db, state, action, decision_id, result):
    """Called only AFTER the normal production action proved a changed method."""
    record = owner_record(db, state['id'])
    incident = record.get('no_progress_hold') or (record.get('held_method_incidents') or {}).get(action.get('job_id'))
    if not incident:
        return
    if result.get('status') != 'queued' or action['kind'] not in {'retry', 'retry_repaired', 'continue_repaired'}:
        raise ValueError('Held attempt requires a validated changed-input or repaired continuation')
    if incident.get('run_id') != state.get('run_id'):
        raise ValueError('Held attempt belongs to a different run')
    resumed = result.get('job_ids') or []
    if action['kind'] != 'continue_repaired' and action.get('job_id') not in incident.get('jobs', {}):
        raise ValueError('Resume must target a job bound to this held attempt')
    if action['kind']=='retry' and not any(
            item.get('changed_input') is True for jid in resumed for item in (
                json.loads(db.execute('SELECT checkpoint FROM jobs WHERE id=?', (jid,)).fetchone()[0])
                    .get('video_agent_recoveries') or [])[-1:]):
        raise ValueError('Unchanged transient retries cannot release a no-progress hold')
    # Parking the attempt also parked untouched queued follow-up work. Restore
    # only never-claimed, unchanged jobs with still-current selected inputs.
    # Failed/previously paused/previously executed methods require their own
    # explicit evidence-bound resolution, retained independently of this hold.
    from .video_agent_context import job_method_fingerprint
    remaining=dict(record.get('held_method_incidents') or {})
    restored=[]
    for job_id,original in incident.get('jobs',{}).items():
        if job_id in resumed or job_id==action.get('job_id'):
            remaining.pop(job_id,None);continue
        row=db.execute('SELECT * FROM jobs WHERE id=? AND task_id=?',(job_id,state['id'])).fetchone()
        if not row or row['status'] in {'done','superseded','cancelled'}:
            remaining.pop(job_id,None);continue
        cp=json.loads(row['checkpoint']);payload=json.loads(row['payload'])
        fresh=(original['status']=='queued' and row['status']=='paused'
            and cp.get('no_progress_hold')==incident['id']
            and not cp.get('_claim_token') and not cp.get('failure_classification')
            and job_method_fingerprint(row)==original['fingerprint']
            and (not payload.get('run_id') or payload['run_id']==state.get('run_id'))
            and (not payload.get('script_id') or payload['script_id']==state.get('script_id'))
            and (not payload.get('voice_id') or payload['voice_id']==state.get('approved_voice_id'))
            and (not payload.get('edit_id') or payload['edit_id']==state.get('edit_id')))
        supervised=db.execute("SELECT 1 FROM sqlite_master WHERE name='supervision_jobs'").fetchone()
        if supervised and db.execute("SELECT 1 FROM supervision_jobs WHERE job_id=? AND phase='held'",(job_id,)).fetchone():
            fresh=False
        if fresh:
            cp.pop('no_progress_hold',None)
            db.execute("UPDATE jobs SET status='queued',checkpoint=? WHERE id=?",(json.dumps(cp),job_id))
            remaining.pop(job_id,None);restored.append(job_id)
        else:
            remaining[job_id]={**incident,'jobs':{job_id:original}}
    record['held_method_incidents']=remaining
    if restored:result['restored_job_ids']=restored
    record.setdefault('hold_history', []).append({**incident, 'resolution_status': 'resumed',
        'remaining_job_ids':sorted(remaining),
        'resumed_at': time.time(), 'resume_decision_id': decision_id, 'result': copy.deepcopy(result)})
    record.pop('no_progress_hold', None)
    record.update(status='active', pending=None, next_at=0, idle_decisions=0,
                  consecutive_failures=0, invalid_decisions=0, recovery_mode=False,
                  runtime_error=None, recovery_job_id=None, repair_evidence_used=[])
    for job_id in resumed:
        db.execute("UPDATE jobs SET checkpoint=json_remove(checkpoint,'$.no_progress_hold') WHERE id=? AND task_id=?",
                   (job_id, state['id']))
    db.execute('UPDATE video_agents SET record=?,updated=? WHERE task_id=?',
               (json.dumps(record, ensure_ascii=False), time.time(), state['id']))
    db.execute('INSERT INTO events(task_id,kind,detail,created) VALUES(?,?,?,?)',
               (state['id'], 'production_attempt_resumed', json.dumps({
                   'hold_id': incident['id'], 'decision_id': decision_id, 'job_ids': resumed}), time.time()))
