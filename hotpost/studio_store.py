"""Transactional studio state, immutable revision references, and a durable outbox."""
from __future__ import annotations

import copy
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class Conflict(ValueError):
    pass


class StaleClaim(Conflict):
    """A recovered/reclaimed worker no longer owns this durable job."""


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def uid(prefix=""):
    return prefix + uuid.uuid4().hex[:16]


def change_claimed(store, job, fn):
    """Worker writes retain their claim; lightweight non-worker test ports work."""
    options = {'job': job} if job.get('claim_token') else {}
    return store.change(job['task_id'], fn, **options)


class StudioStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "studio.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks (
                  id TEXT PRIMARY KEY, shortcode TEXT UNIQUE NOT NULL,
                  revision INTEGER NOT NULL, state TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, task_id TEXT NOT NULL, kind TEXT NOT NULL,
                  key TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL,
                  checkpoint TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '',
                  created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY, task_id TEXT NOT NULL, kind TEXT NOT NULL,
                  detail TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS automatic_runs (
                  run_key TEXT PRIMARY KEY, selection TEXT NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS jobs_task_activity ON jobs(task_id,status,kind);
                CREATE TABLE IF NOT EXISTS postproduction_outbox (
                  task_id TEXT NOT NULL, edit_id TEXT NOT NULL, binding TEXT NOT NULL,
                  status TEXT NOT NULL, error TEXT NOT NULL, created REAL NOT NULL,
                  PRIMARY KEY(task_id,edit_id));
            """)
            from .production_control import ensure as ensure_production_control
            ensure_production_control(db)
            from .production_records import ensure as ensure_record_outbox
            ensure_record_outbox(db)
        # Existing daily automatic tasks adopt the shared workflow without
        # launching new work or changing manually selected studio tasks.
        with self.transaction() as db:
            for row in db.execute('SELECT state FROM tasks').fetchall():
                state = json.loads(row[0])
                auto = state.get('automation', {})
                if auto.get('selection_mode') == 'automatic' and auto.get('protocol') != 2:
                    from .studio_workflow import snapshot
                    auto['protocol'] = 2
                    auto['needs_top_pick'] = bool(state.get('script_candidates'))
                    snapshot(state)
                    self.save(db, state)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, code, title, automation=None, *, initial=None, prepare=True):
        with self.transaction() as db:
            row = db.execute("SELECT state FROM tasks WHERE shortcode=?", (code,)).fetchone()
            if row:
                return json.loads(row[0]), False
            state = dict(id=uid("work-"), shortcode=code, title=title, revision=0,
                         status="preparing", message="자료 준비 대기", error="",
                         scripts=[], voices=[], edits=[], proposals=[], sources=[],
                         script_id=None, approved_script_id=None, voice_id=None,
                         approved_voice_id=None, edit_id=None, original_text="",
                         created=time.time(), updated=time.time())
            from .source_policy import montage_policy
            state['source_policy'] = montage_policy()
            if initial:
                state.update(copy.deepcopy(initial))
            if automation:
                state['automation'] = automation
                if automation.get('protocol') == 2:
                    from .studio_workflow import init_run
                    init_run(state)
            db.execute("INSERT INTO tasks VALUES (?,?,?,?,?)", (
                state["id"], code, 0, json.dumps(state, ensure_ascii=False), state["updated"]))
            from .video_agents import enroll
            origin = ('automatic' if (automation or {}).get('selection_mode') == 'automatic'
                      else 'self_shot' if state.get('creation_mode') == 'self_shot' else 'manual')
            enroll(db, state, origin)
            if prepare:
                self.enqueue(db, state["id"], "prepare", {}, "prepare:" + state["id"])
            self.event(db, state["id"], "created", {})
            return state, True

    def freeze_selection(self, run_key, selection):
        with self.transaction() as db:
            db.execute('INSERT OR IGNORE INTO automatic_runs VALUES(?,?,?)',
                       (str(run_key), json.dumps(selection, ensure_ascii=False), time.time()))
            return json.loads(db.execute('SELECT selection FROM automatic_runs WHERE run_key=?',
                                         (str(run_key),)).fetchone()[0])

    def events(self, task_id):
        with self.connect() as db:
            return [{**dict(r), 'detail':json.loads(r['detail'])} for r in db.execute(
                'SELECT kind,detail,created FROM events WHERE task_id=? ORDER BY id DESC LIMIT 60', (task_id,))]

    def get(self, task_id, db=None):
        if db is None:
            with self.connect() as conn:
                return self.get(task_id, conn)
        row = db.execute("SELECT state FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError("제작 작업을 찾을 수 없습니다.")
        return json.loads(row[0])

    def list(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT state FROM tasks ORDER BY updated DESC")]

    def change(self, task_id, fn, expected=None, *, job=None):
        with self.transaction() as db:
            if job is not None and not self.owns(db, job, statuses=('running', 'failed')):
                raise StaleClaim('작업 소유권이 변경되어 이전 실행의 저장을 중지합니다.')
            state = self.get(task_id, db)
            if expected is not None and state["revision"] != expected:
                raise Conflict("다른 변경사항이 저장되었습니다. 새로고침 후 다시 적용하세요.")
            fn(state, db)
            self.save(db, state)
            return copy.deepcopy(state)

    def save(self, db, state):
        previous = db.execute("SELECT json_extract(state,'$.status') FROM tasks WHERE id=?", (state['id'],)).fetchone()
        state["revision"] += 1
        state["updated"] = time.time()
        db.execute("UPDATE tasks SET state=?,revision=?,updated=? WHERE id=?", (
            json.dumps(state, ensure_ascii=False), state["revision"], state["updated"], state["id"]))
        from .monetization_completion import record_completion
        record_completion(db, state, previous[0] if previous else None)
        from .production_records import queue as queue_record
        queue_record(db,state)

    def postproduction_pending(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM postproduction_outbox WHERE status IN ('pending','waiting_connections','waiting_slot','dispatched') ORDER BY created LIMIT 1").fetchall()
        return [{**dict(row), 'binding': json.loads(row['binding'])} for row in rows]

    def postproduction_update(self, task_id, edit_id, status, error=''):
        if status not in {'waiting_connections', 'waiting_slot', 'dispatched', 'done', 'error', 'superseded'}:
            raise ValueError('올바르지 않은 후속 작업 상태')
        with self.transaction() as db:
            db.execute('UPDATE postproduction_outbox SET status=?,error=? WHERE task_id=? AND edit_id=?',
                (status, error, task_id, edit_id))

    def postproduction_status(self, task_id):
        with self.connect() as db:
            row = db.execute('SELECT status,error FROM postproduction_outbox WHERE task_id=? ORDER BY created DESC LIMIT 1', (task_id,)).fetchone()
        return dict(row) if row else None

    def event(self, db, task_id, kind, detail):
        db.execute("INSERT INTO events(task_id,kind,detail,created) VALUES(?,?,?,?)", (
            task_id, kind, json.dumps(detail, ensure_ascii=False), time.time()))

    def enqueue(self, db, task_id, kind, payload, key):
        row = db.execute("SELECT id,status,checkpoint FROM jobs WHERE key=?", (key,)).fetchone()
        if row:
            if row["status"] == "failed":
                db.execute("UPDATE jobs SET status='queued',error='',updated=? WHERE id=?", (time.time(), row["id"]))
                if kind in {'rewrite', 'voice'}:
                    checkpoint = json.loads(row['checkpoint'])
                    checkpoint['retry_requested'] = True
                    db.execute('UPDATE jobs SET checkpoint=? WHERE id=?', (json.dumps(checkpoint), row['id']))
            return row["id"]
        job_id = uid("job-")
        db.execute("INSERT INTO jobs(id,task_id,kind,key,payload,status,created,updated) VALUES(?,?,?,?,?,'queued',?,?)",
                   (job_id, task_id, kind, key, json.dumps(payload, ensure_ascii=False), time.time(), time.time()))
        return job_id

    def claim(self, lane=None, *, task_id=None, reservation=None, job_id=None):
        if (self.root/'agent-maintenance.json').exists():return None
        owner=getattr(self,'video_agents',None)
        if owner and (not owner.healthy() or owner.restart_requested.is_set() or owner.maintenance.is_set()):return None
        supervisor = getattr(self, 'supervisor', None)
        if supervisor and not supervisor.healthy():
            return None
        with self.transaction() as db:
            if (self.root/'agent-maintenance.json').exists():return None
            if not supervisor and db.execute("SELECT 1 FROM sqlite_master WHERE name='supervision_runtime'").fetchone():
                return None  # A deployed store may only execute through its supervised owner.
            if owner and (not owner.healthy() or owner.restart_requested.is_set() or owner.maintenance.is_set()):return None
            self.consume_previous_daily(db)
            self.pause_queued(db)
            from .production_control import admit
            admit(db, task_id or '')
            # Finish an already-prepared video's downstream stages before the
            # next slow source search, so the first review becomes ready sooner.
            lane_filter = (" AND kind IN ('collect_sources','refresh_sources')" if lane == 'sources' else
                           " AND kind IN ('rewrite','proposal')" if lane == 'scripts' else
                           " AND kind NOT IN ('collect_sources','refresh_sources','rewrite','proposal')" if lane == 'media' else
                           " AND kind NOT IN ('collect_sources','refresh_sources')" if lane == 'production' else '')
            parameters = [time.time()]
            due = "COALESCE(json_extract(checkpoint,'$.not_before'),0)<=?"
            if reservation:
                due = "(" + due + " OR (json_extract(checkpoint,'$.batch_reservation')=? AND COALESCE(json_extract(checkpoint,'$.batch_original_not_before'),0)<=?))"
                parameters.extend([reservation, time.time()])
            if task_id is not None:
                lane_filter += ' AND task_id=?'
                parameters.append(task_id)
            if job_id is not None:
                lane_filter += ' AND id=?'
                parameters.append(job_id)
            if supervisor:
                lane_filter += " AND NOT EXISTS (SELECT 1 FROM supervision_jobs s WHERE s.task_id=jobs.task_id AND s.phase='held')"
            if owner:
                lane_filter += " AND NOT EXISTS (SELECT 1 FROM video_agents a WHERE a.task_id=jobs.task_id AND (json_extract(a.record,'$.status')='user_command' OR json_extract(a.record,'$.runtime_error') IS NOT NULL))"
                lane_filter += " AND NOT EXISTS (SELECT 1 FROM video_agents a WHERE a.task_id=jobs.task_id AND json_extract(a.record,'$.recovery_job_id')=jobs.id)"
            lane_filter += " AND task_id=(SELECT task_id FROM production_slot WHERE singleton=1)"
            lane_filter += """ AND NOT EXISTS (SELECT 1 FROM tasks paused WHERE paused.id=jobs.task_id
                AND json_extract(paused.state,'$.automation.paused_by_user')=1
                AND NOT (COALESCE(json_extract(jobs.payload,'$.launch'),0)=1 OR
                    (jobs.kind='refresh_sources' AND COALESCE(json_extract(jobs.payload,'$.manual_source_request'),0)=1
                    AND COALESCE(json_extract(jobs.payload,'$.pause_token')=json_extract(paused.state,'$.automation.paused_at'),0))))"""
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='video_agents'").fetchone():
                lane_filter += " AND NOT EXISTS (SELECT 1 FROM video_agents a WHERE a.task_id=jobs.task_id AND json_type(a.record,'$.no_progress_hold') IS NOT NULL)"
            row = db.execute("""SELECT * FROM jobs WHERE status='queued'
                AND """ + due + """
                AND (jobs.kind IN ('collect_sources','refresh_sources','proposal') OR NOT EXISTS (
                  SELECT 1 FROM jobs AS running WHERE running.task_id=jobs.task_id
                  AND running.status='running'
                  AND running.kind NOT IN ('collect_sources','refresh_sources','proposal')
                ))
                """ + lane_filter + """
                ORDER BY COALESCE((SELECT json_extract(tasks.state,'$.automation.priority')
                  FROM tasks WHERE tasks.id=jobs.task_id),0) DESC,
                CASE WHEN kind<>'prepare' AND EXISTS (
                  SELECT 1 FROM tasks WHERE tasks.id=jobs.task_id
                  AND json_extract(tasks.state,'$.automation.active')=1
                ) THEN 0 ELSE 1 END,created LIMIT 1""", parameters).fetchone()
            if row is None:
                return None
            checkpoint = json.loads(row['checkpoint'])
            checkpoint['_claim_token'] = uid('claim-')
            checkpoint['_claim_started_at'] = time.time()
            db.execute("UPDATE jobs SET status='running',checkpoint=?,updated=? WHERE id=?",
                       (json.dumps(checkpoint), time.time(), row["id"]))
            state = self.get(row['task_id'], db)
            if row['kind'] == 'collect_sources':
                state['source_search'] = {'status':'running','message':'소스 영상을 자동으로 확보하는 중','progress':0}
                self.save(db,state)
            stages = {'prepare':('preparing','자료 준비'), 'rewrite':('rewriting','대본 재가공'),
                      'voice':('voice_generating','음성 제작'), 'edit':('editing','장면·자막 편집'),
                      'revision':('editing','구간 수정'), 'register':('registering','프로젝트 등록'),
                      'export':('exporting','최종 영상 내보내기')}
            if state['status'] in {'retry_wait','waiting_capcut'} and row['kind'] in stages:
                status, label = stages[row['kind']]
                state.update(status=status, error='', message=label+' 다시 진행 중')
                self.save(db, state)
            elif state.get('automation', {}).get('active') and row['kind'] in stages:
                status, label = stages[row['kind']]
                state.update(status=status, message=label+' 진행 중')
                self.save(db, state)
            result = dict(row)
            result["payload"] = json.loads(result["payload"])
            result["checkpoint"] = checkpoint
            result['claim_token'] = checkpoint['_claim_token']
            if supervisor:
                supervisor.register(db, result)
            from .studio_timing import record
            record(self, db, result, 'claimed')
            return result

    @staticmethod
    def owns(db, job, *, statuses=('running',)):
        row = db.execute('SELECT status,checkpoint,task_id,kind FROM jobs WHERE id=?', (job['id'],)).fetchone()
        if row is None or row['status'] not in statuses or row['task_id'] != job['task_id'] or row['kind'] != job['kind']:
            return False
        token = job.get('claim_token') or job.get('checkpoint', {}).get('_claim_token')
        return bool(token and token == json.loads(row['checkpoint']).get('_claim_token'))

    def consume_previous_daily(self, db):
        """Consume legacy daily picks; full batches keep processing after midnight."""
        from .daily_hot import date_key
        today = date_key(time.time())
        rows = db.execute("SELECT state FROM tasks WHERE json_extract(state,'$.automation.selection_mode')='automatic' AND json_extract(state,'$.automation.active')=1 AND COALESCE(json_extract(state,'$.automation.finish_selected_batch'),0)<>1").fetchall()
        for row in rows:
            state = json.loads(row[0])
            auto = state['automation']
            day = auto.get('selection_date_kst') or date_key(auto.get('selected_at', state['created']))
            if day and day < today and state['status'] != 'completed':
                auto.update(active=False, consumed_by_daily_policy=True)
                db.execute("UPDATE jobs SET status='paused' WHERE task_id=? AND status='queued' AND kind NOT IN ('proposal','refresh_sources','suggest_edit') AND COALESCE(json_extract(payload,'$.launch'),0)<>1", (state['id'],))
                state.update(status='paused', message='이전 감지일 · 소모 처리 · 명시적 재개 시 이어집니다')
                self.save(db, state)
                self.event(db, state['id'], 'daily_policy_consumed', {'selection_date_kst':day, 'today_kst':today})

    def checkpoint(self, job_id, value):
        with self.transaction() as db:
            # Worker callers pass the claimed job. String IDs remain available
            # to explicit administration of queued checkpoints.
            if isinstance(job_id, dict):
                job = job_id
                direct = db.execute('SELECT status FROM jobs WHERE id=?', (job['id'],)).fetchone()
                if not job.get('claim_token') and direct is None:
                    return False
                if not job.get('claim_token') and direct['status'] in {'queued', 'paused'}:
                    job_id = job['id']  # Explicit/direct administration, not a worker claim.
                elif not self.owns(db, job):
                    raise StaleClaim('이전 실행의 체크포인트 저장을 중지합니다.')
                else:
                    job_id = job['id']
                    value = {**value, '_claim_token': job['claim_token']}
            else:
                row = db.execute('SELECT checkpoint FROM jobs WHERE id=?', (job_id,)).fetchone()
                if row:
                    token = json.loads(row['checkpoint']).get('_claim_token')
                    if token:
                        value = {**value, '_claim_token': token}
            db.execute("UPDATE jobs SET checkpoint=?,updated=? WHERE id=?", (
                json.dumps(value, ensure_ascii=False), time.time(), job_id))

    def assert_owned(self, job):
        with self.connect() as db:
            if not self.owns(db, job):
                raise StaleClaim('이전 실행은 작업 파일·외부 실행을 시작할 수 없습니다.')

    @staticmethod
    def pause_queued(db):
        from .video_agent_planning_claim import admitted_planning_children
        planning=sorted(admitted_planning_children(db))
        db.execute("""UPDATE jobs SET status='paused' WHERE status='queued' AND kind='collect_sources'
            AND EXISTS (SELECT 1 FROM tasks WHERE tasks.id=jobs.task_id
                AND json_extract(tasks.state,'$.status')='completed')""")
        db.execute("""UPDATE jobs SET status='paused' WHERE status='queued' AND kind='collect_sources'
            AND EXISTS (SELECT 1 FROM tasks WHERE tasks.id=jobs.task_id
                AND json_extract(tasks.state,'$.source_acquisition.hold') IS NOT NULL)"""
            + (' AND id NOT IN ('+','.join('?' for _ in planning)+')' if planning else ''),planning)
        db.execute("""UPDATE jobs SET status='paused' WHERE status='queued'
            AND (kind NOT IN ('proposal','refresh_sources','suggest_edit')
                 OR (kind='refresh_sources' AND json_extract(payload,'$.daily_quality_repair')=1))
            AND COALESCE(json_extract(payload,'$.launch'),0)<>1
            AND EXISTS (SELECT 1 FROM tasks WHERE tasks.id=jobs.task_id
                AND json_extract(tasks.state,'$.automation.protocol')=2
                AND (json_extract(tasks.state,'$.automation.paused_by_user')=1
                     OR json_extract(tasks.state,'$.automation.consumed_by_daily_policy')=1))""")

    def defer(self, job, message, seconds, waiting=False, waiting_status=None):
        with self.transaction() as db:
            if not self.owns(db, job):
                return False
            state = self.get(job['task_id'], db)
            checkpoint = job['checkpoint']
            checkpoint['not_before'] = time.time()+seconds
            checkpoint['deferred_wait'] = bool(waiting)
            from .studio_timing import record
            deferred_at=record(self, db, job, 'deferred', wait_kind=(waiting_status or 'service_wait') if waiting else 'retry_wait',
                   not_before=checkpoint['not_before'])
            if not waiting:
                checkpoint['auto_retries'] = checkpoint.get('auto_retries',0)+1
                checkpoint['retry_requested'] = True
            if job['kind'] == 'collect_sources':
                state['source_search'] = {'status':'queued','message':message if waiting else '소스 자동 수집 재시도 대기',
                                          'error':'' if waiting else str(message)[:500], 'progress':0}
            else:
                state.update(status=(waiting_status or 'waiting_capcut') if waiting else 'retry_wait', error='',
                             message=message if waiting else f"일시적 오류 · 자동 재시도 {checkpoint['auto_retries']}/2 대기: {message}")
            if state.get('pending_reproduction') and job['kind'] != 'collect_sources':
                # The deferred job is no longer running; let the worker consume it
                # once and transition at its boundary without losing the request.
                checkpoint['not_before'] = 0
            db.execute("UPDATE jobs SET status='queued',checkpoint=?,updated=? WHERE id=?",
                       (json.dumps(checkpoint),deferred_at if deferred_at is not None else time.time(),job['id']))
            if (state.get('automation', {}).get('paused_by_user') or state.get('automation', {}).get('consumed_by_daily_policy')) and (job['kind'] not in {'proposal','refresh_sources','suggest_edit'} or job['payload'].get('daily_quality_repair')) and not job['payload'].get('launch'):
                db.execute("UPDATE jobs SET status='paused' WHERE id=?", (job['id'],))
                state.update(status='paused', message='자동 진행 중지 · 재개하면 중단 단계부터 이어집니다')
                if job['kind'] == 'collect_sources': state['source_search']['status'] = 'paused'
            self.save(db,state)

    def pause_claimed(self, job, message):
        """Stop a cancelled claim once; never requeue a zero-delay pause loop."""
        with self.transaction() as db:
            if not self.owns(db, job):
                return False
            from .studio_timing import record
            record(self, db, job, 'paused')
            db.execute("UPDATE jobs SET status='paused',updated=? WHERE id=?", (time.time(),job['id']))
            state = self.get(job['task_id'],db)
            state.update(status='paused',message=message)
            self.save(db,state)
            self.event(db,job['task_id'],'job_paused',{'job_id':job['id'],'kind':job['kind']})
            return True

    def recover(self):
        # Called only after the process-exclusive studio worker lock is held.
        with self.transaction() as db:
            from .studio_timing import record
            for row in db.execute("SELECT * FROM jobs WHERE status='running'").fetchall():
                record(self, db, {**dict(row), 'checkpoint':json.loads(row['checkpoint'])}, 'interrupted_unknown_end')
            db.execute("UPDATE jobs SET status='queued' WHERE status='running'")
            supervisor = getattr(self, 'supervisor', None)
            if supervisor:
                supervisor.recover(db)
            self.pause_queued(db)

    def jobs(self, task_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT id,kind,status,error,updated FROM jobs WHERE task_id=? ORDER BY created DESC,rowid DESC", (task_id,))]

    def finish(self, job, result, apply):
        with self.transaction() as db:
            if not self.owns(db, job):
                return False
            state = self.get(job["task_id"], db)
            apply(state, db, result)
            wait_until = result.get('_defer_until')
            if wait_until is not None:
                from .studio_timing import record
                record(self, db, job, 'deferred', wait_kind=state.get('status'), not_before=wait_until)
                checkpoint = {**job['checkpoint'], 'not_before': wait_until}
                db.execute("UPDATE jobs SET status='queued',checkpoint=?,error='',updated=? WHERE id=?",
                           (json.dumps(checkpoint), time.time(), job['id']))
                self.pause_queued(db)
                self.save(db, state)
                self.event(db, state['id'], job['kind']+'_waiting', {'job_id':job['id'], 'not_before':wait_until})
                return True
            if (job.get('payload',{}).get('quality_repair') or job.get('payload',{}).get('quality_rewrite')
                    or job.get('kind')=='quality_reedit') and state.get('daily_quality'):
                from .quality_progress import finish_attempt
                finish_attempt(state,job,result,failed=bool(result.get('no_render')))
            self.save(db, state)
            from .studio_timing import record
            record(self, db, job, 'done')
            db.execute("UPDATE jobs SET status='done',error='',updated=? WHERE id=?", (time.time(), job["id"]))
            self.event(db, state["id"], job["kind"] + "_finished", {"job_id": job["id"]})
            return True

    def fail(self, job, error):
        with self.transaction() as db:
            if not self.owns(db, job):
                return False
            from .studio_timing import record
            record(self, db, job, 'failed')
            state = self.get(job["task_id"], db)
            import traceback
            checkpoint = dict(job.get('checkpoint') or {})
            checkpoint.pop('video_agent_retry_admission',None)
            checkpoint['failure_trace'] = {'type':type(error).__name__, 'stage':job['kind'],
                'message':str(error)[:1500],
                'frames':[{'path':f.filename,'line':f.lineno,'function':f.name}
                          for f in traceback.extract_tb(getattr(error,'__traceback__',None))[-15:]]}
            payload = job.get("payload", {})
            if job['kind'] in {'refresh_sources','collect_sources'}:
                state['source_search'] = {'status': 'failed', 'message': str(error)[:500], 'progress': 0}
            current = payload.get("script_id", state["script_id"]) == state["script_id"]
            current &= job['kind'] not in {'refresh_sources','collect_sources'}
            if job['kind'] in {'proposal','suggest_edit'} and state.get('automation', {}).get('protocol')==2:
                current = False
                state['feedback_message'] = '수정안 생성 실패: '+str(error)[:500]
            if job["kind"] == "voice":
                current &= payload.get("voice_id") == state.get("pending_voice_id")
            if job["kind"] in {"edit", "revision", "edit_request"}:
                current &= payload.get("voice_id") == state.get("approved_voice_id")
            if current:
                state.update(error=str(error)[:700], message="확인이 필요합니다")
                if job["kind"] not in {"proposal", "register"} or (job['kind'] == 'register' and state.get('automation')):
                    state["status"] = "attention"
            self.save(db, state)
            db.execute("UPDATE jobs SET status='failed',error=?,checkpoint=?,updated=? WHERE id=?", (
                str(error)[:700], json.dumps(checkpoint,ensure_ascii=False),time.time(), job["id"]))
            self.event(db, state["id"], "failed", {"job_id": job["id"], "error": str(error)[:700]})
            return True
