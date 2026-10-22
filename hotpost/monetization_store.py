"""Durable post-production state; independent of video completion and its queue.

External effects are reserved BEFORE dispatch. An ambiguous dispatch is never
silently retried, including after a process restart or for another task ID.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
import time
import uuid


@contextmanager
def effect_lease(root, effect_id):
    """OS-released ownership; a durable marker or elapsed time is not liveness."""
    if not re.fullmatch(r'[a-f0-9]{32}', effect_id):
        raise ValueError('올바르지 않은 실행 식별자')
    import os
    path = Path(root) / ('effect-' + effect_id + '.lock')
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise MonetizationConflict('실제 실행 소유자가 아직 작업 중입니다.') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class MonetizationConflict(ValueError):
    pass


class NextPostBusy(MonetizationConflict):
    pass


class ConnectionsNotReady(ValueError):
    pass


def canonical_account(account):
    value = str(account).strip().removeprefix('@').casefold()
    if not re.fullmatch(r'[a-z0-9_.]{1,30}', value):
        raise ValueError('실제 연결할 인스타 계정명을 확인하세요.')
    return value


class MonetizationStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'state.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS records (
                    task_id TEXT PRIMARY KEY, account TEXT NOT NULL,
                    shortcode TEXT NOT NULL, revision INTEGER NOT NULL,
                    state TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS effects (
                    account TEXT NOT NULL, shortcode TEXT NOT NULL,
                    kind TEXT NOT NULL, id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL, details TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL,
                    PRIMARY KEY(account, shortcode, kind));
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, task_id TEXT NOT NULL,
                    kind TEXT NOT NULL, details TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS next_post_slots (
                    account TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                    status TEXT NOT NULL, details TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS configuration (
                    name TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=10000')
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, task_id):
        with self.connect() as db:
            row = db.execute('SELECT state FROM records WHERE task_id=?', (task_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def automation(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM configuration WHERE name='automation'").fetchone()
        return json.loads(row[0]) if row else {'enabled': False, 'account': ''}

    def configure_automation(self, enabled, account, discovery_account=None):
        if not isinstance(enabled, bool):
            raise ValueError('자동 후속 실행 설정은 true/false여야 합니다.')
        account = canonical_account(account)
        value = {'enabled': enabled, 'account': account}
        discovery_account = discovery_account if discovery_account is not None else self.automation().get('discovery_account')
        if discovery_account:
            value['discovery_account'] = canonical_account(discovery_account)
        with self.connect() as db:
            db.execute('INSERT INTO configuration VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',
                ('automation', json.dumps(value)))
        return value

    def next_post_busy(self, account, task_id=None):
        with self.connect() as db:
            row = db.execute('SELECT task_id FROM next_post_slots WHERE account=?', (canonical_account(account),)).fetchone()
            return bool(row and row['task_id'] != task_id)

    def prepare(self, task_id, account, shortcode, binding, discovery_account=None):
        account = canonical_account(account)
        discovery_account = canonical_account(discovery_account or account)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', str(shortcode)):
            raise ValueError('올바른 레퍼런스 shortcode가 필요합니다.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM records WHERE task_id=?', (task_id,)).fetchone()
            if row:
                state = json.loads(row[0])
                if (state['account'] != account or state.get('discovery_account', state['account']) != discovery_account
                        or state['shortcode'] != shortcode or state['binding'] != binding):
                    raise MonetizationConflict('기존 수익화 대상과 영상·대본 연결이 다릅니다. 기록을 보존합니다.')
                return state
            state = dict(task_id=task_id, account=account, shortcode=shortcode,
                         binding=binding, status='ready', stage='product', revision=1,
                         created=time.time(), updated=time.time())
            if discovery_account != account:
                state['discovery_account'] = discovery_account
            db.execute('INSERT INTO records VALUES(?,?,?,?,?,?)',
                (task_id, account, shortcode, 1, json.dumps(state, ensure_ascii=False), state['updated']))
            return state

    def change(self, task_id, changes, *, expected=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM records WHERE task_id=?', (task_id,)).fetchone()
            if not row:
                raise MonetizationConflict('수익화 작업을 먼저 준비하세요.')
            state = json.loads(row[0])
            if expected is not None and state['revision'] != expected:
                raise MonetizationConflict('다른 요청이 먼저 진행됐습니다. 현재 상태를 다시 확인하세요.')
            protected = {'task_id', 'account', 'discovery_account', 'shortcode', 'binding', 'created', 'revision', 'product_retry'}
            if protected.intersection(changes):
                raise ValueError('대상 식별자는 변경할 수 없습니다.')
            state.update(changes)
            state['revision'] += 1
            state['updated'] = time.time()
            db.execute('UPDATE records SET revision=?,state=?,updated=? WHERE task_id=?',
                (state['revision'], json.dumps(state, ensure_ascii=False), state['updated'], task_id))
            if state['status'] == 'error':
                db.execute("DELETE FROM next_post_slots WHERE account=? AND task_id=? AND status='workflow'",
                           (state['account'], task_id))
            db.execute('INSERT INTO events(task_id,kind,details,created) VALUES(?,?,?,?)',
                (task_id, state['stage'], json.dumps(changes, ensure_ascii=False), time.time()))
            return state

    def rebind_unstarted_account(self, task_id, account, *, expected, discovery_account=None):
        """Explicit correction only, before any reservation or external attempt."""
        account = canonical_account(account)
        discovery_account = canonical_account(discovery_account or account)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM records WHERE task_id=?', (task_id,)).fetchone()
            if not row:
                raise MonetizationConflict('수익화 작업을 먼저 준비하세요.')
            state = json.loads(row[0])
            if state['revision'] != expected:
                raise MonetizationConflict('다른 요청이 먼저 진행됐습니다. 현재 상태를 다시 확인하세요.')
            if state['account'] == account and state.get('discovery_account', state['account']) == discovery_account:
                return state
            attempted = db.execute('SELECT 1 FROM effects WHERE shortcode=? AND account IN (?,?,?,?) LIMIT 1',
                                   (state['shortcode'], state['account'], account,
                                    state.get('discovery_account',state['account']), discovery_account)).fetchone()
            reserved = db.execute('SELECT 1 FROM next_post_slots WHERE task_id=? LIMIT 1', (task_id,)).fetchone()
            if (state['stage'] != 'product' or state['status'] != 'ready' or attempted or reserved
                    or any(key in state for key in ('effect_id', 'product', 'affiliate', 'package', 'littly', 'publication'))):
                raise MonetizationConflict('이미 시도·예약된 작업의 계정은 바꾸지 않습니다. 기존 기록을 보존합니다.')
            previous = state['account']
            previous_discovery = state.get('discovery_account',previous)
            state.update(account=account, revision=state['revision'] + 1, updated=time.time())
            if discovery_account != account or 'discovery_account' in state:
                state['discovery_account'] = discovery_account
            db.execute('UPDATE records SET account=?,revision=?,state=?,updated=? WHERE task_id=?',
                       (account, state['revision'], json.dumps(state, ensure_ascii=False), state['updated'], task_id))
            details = {'previous_account':previous, 'account':account}
            if previous_discovery != previous or discovery_account != account:
                details.update(previous_discovery_account=previous_discovery, discovery_account=discovery_account)
            db.execute('INSERT INTO events(task_id,kind,details,created) VALUES(?,?,?,?)',
                       (task_id, 'account_rebound', json.dumps(details), state['updated']))
            return state

    def authorize_product_retry(self, task_id, previous_effect_id, approval_ref, *, expected):
        """One explicit human instruction; retain every previous attempt in history."""
        if not isinstance(approval_ref,str) or not approval_ref.strip() or len(approval_ref)>1200:
            raise ValueError('이번 재실행을 승인한 사용자 지시 근거가 필요합니다.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state FROM records WHERE task_id=?',(task_id,)).fetchone()
            state=json.loads(row[0]) if row else {}
            if (state.get('revision')!=expected or state.get('stage')!='product' or state.get('status')!='error'
                    or state.get('effect_id')!=previous_effect_id or state.get('product')):
                raise MonetizationConflict('승인한 실패 시도와 현재 작업이 달라 재실행하지 않습니다.')
            effect=db.execute('SELECT * FROM effects WHERE id=?',(previous_effect_id,)).fetchone()
            if (not effect or effect['kind']!='product_discovery' or effect['status']!='error'
                    or effect['shortcode']!=state['shortcode']
                    or effect['account']!=state.get('discovery_account',state['account'])):
                raise MonetizationConflict('명확한 상품 확인 오류 시도만 사용자 승인으로 다시 진행할 수 있습니다.')
            old=json.loads(effect['details'])
            grant={'id':uuid.uuid4().hex,'previous_effect_id':previous_effect_id,
                   'approval_ref':approval_ref.strip(),'approved_at':time.time(),'status':'authorized',
                   'attempt_count':int(old.get('attempt_count',1))+1,
                   'previous_error':state.get('error',''),'previous_error_evidence_path':state.get('error_evidence_path')}
            state.update(product_retry=grant,status='ready',error='',updated=time.time(),revision=state['revision']+1)
            db.execute('UPDATE records SET state=?,revision=?,updated=? WHERE task_id=?',
                       (json.dumps(state,ensure_ascii=False),state['revision'],state['updated'],task_id))
            db.execute('INSERT INTO events(task_id,kind,details,created) VALUES(?,?,?,?)',
                       (task_id,'user_authorized_product_retry',json.dumps(grant,ensure_ascii=False),state['updated']))
            return state

    def reserve_effect(self, state, kind, details, *, effect_id=None):
        """The durable uniqueness key deliberately excludes task/job IDs."""
        effect_id = effect_id or uuid.uuid4().hex
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            stored = db.execute('SELECT state FROM records WHERE task_id=?', (state['task_id'],)).fetchone()
            if not stored or json.loads(stored[0])['revision'] != state['revision']:
                raise MonetizationConflict('현재 상태가 바뀌어 외부 동작을 시작하지 않습니다.')
            running = json.loads(stored[0])
            if kind in {'product_discovery', 'littly_create'}:
                account = canonical_account(state['account'])
                slot = db.execute('SELECT * FROM next_post_slots WHERE account=?', (account,)).fetchone()
                if slot and (slot['task_id'] != state['task_id'] or slot['status'] != 'workflow'):
                    raise NextPostBusy('이 인스타 계정의 앞선 상품·다음 게시물 연결이 끝나지 않아 대기합니다.')
                slot_status = 'workflow' if kind == 'product_discovery' else 'reserved'
                if slot:
                    db.execute('UPDATE next_post_slots SET status=?,updated=? WHERE account=?', (slot_status, now, account))
                else:
                    db.execute('INSERT INTO next_post_slots VALUES(?,?,?,?,?)',
                        (account, state['task_id'], slot_status, '{}', now))
            if kind == 'instagram_publish':
                slot = db.execute('SELECT * FROM next_post_slots WHERE account=?', (state['account'],)).fetchone()
                if (not slot or slot['task_id'] != state['task_id'] or slot['status'] != 'registered'
                        or json.loads(slot['details']).get('automation_id') != state['littly']['automation_id']):
                    raise NextPostBusy('이 게시 패키지의 리틀리 등록·계정 예약 소유권이 필요합니다.')
            actor=canonical_account(state.get('discovery_account',state['account']) if kind=='product_discovery' else state['account'])
            prior=db.execute('SELECT * FROM effects WHERE account=? AND shortcode=? AND kind=?',
                             (actor,state['shortcode'],kind)).fetchone()
            grant=running.get('product_retry',{})
            retry=bool(kind=='product_discovery' and prior and prior['status']=='error'
                       and grant.get('status')=='authorized' and grant.get('previous_effect_id')==prior['id'])
            try:
                if retry:
                    previous=dict(prior)
                    previous_details=json.loads(previous['details'])
                    history=previous_details.pop('previous_attempts',[])
                    previous['details']=previous_details
                    details={**details,'attempt_count':grant['attempt_count'],'approval_id':grant['id'],
                             'previous_attempts':[*history,previous]}
                    db.execute('UPDATE effects SET id=?,status=?,details=?,created=?,updated=? WHERE id=?',
                               (effect_id,'dispatching',json.dumps(details,ensure_ascii=False),now,now,prior['id']))
                    running['product_retry']={**grant,'status':'consumed','effect_id':effect_id,'consumed_at':now}
                else:
                    db.execute('INSERT INTO effects VALUES(?,?,?,?,?,?,?,?)',
                        (actor,state['shortcode'],kind,effect_id,'dispatching',json.dumps(details,ensure_ascii=False),now,now))
            except sqlite3.IntegrityError as exc:
                raise MonetizationConflict('이 계정·레퍼런스의 해당 동작은 이미 시도했습니다. 자동 재시도하지 않습니다.') from exc
            running.update(status='running', effect_id=effect_id, updated=now,
                           revision=running['revision'] + 1)
            db.execute('UPDATE records SET revision=?,state=?,updated=? WHERE task_id=?',
                (running['revision'], json.dumps(running, ensure_ascii=False), now, state['task_id']))
        return effect_id

    def continue_unsubmitted_product(self, task_id, effect_id, approval_id, *, expected):
        """Continue the same approved attempt only with positive no-submit proof."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state FROM records WHERE task_id=?',(task_id,)).fetchone()
            state=json.loads(row[0]) if row else {}
            effect=db.execute('SELECT * FROM effects WHERE id=?',(effect_id,)).fetchone()
            details=json.loads(effect['details']) if effect else {}
            grant=state.get('product_retry',{})
            if (state.get('revision')!=expected or state.get('status')!='error' or state.get('stage')!='product'
                    or state.get('effect_id')!=effect_id or not effect or effect['status']!='error'
                    or effect['kind']!='product_discovery' or details.get('comment_submit_called') is not False
                    or details.get('comment_id') or details.get('comment_receipt')
                    or grant.get('id')!=approval_id or grant.get('effect_id')!=effect_id or grant.get('status')!='consumed'):
                raise MonetizationConflict('댓글 미전송이 확인된 동일 승인 시도만 이어갈 수 있습니다.')
            history=details.get('pre_submit_repairs',[])
            details={**details,'pre_submit_repairs':[*history,{'error':state.get('error'),
                     'error_evidence_path':state.get('error_evidence_path'),'at':time.time(),'revision':state['revision']}],
                     'continuation_at':time.time()}
            state.update(status='running',error='',updated=time.time(),revision=state['revision']+1)
            db.execute('UPDATE effects SET status=?,details=?,updated=? WHERE id=?',
                       ('dispatching',json.dumps(details,ensure_ascii=False),state['updated'],effect_id))
            db.execute('UPDATE records SET state=?,revision=?,updated=? WHERE task_id=?',
                       (json.dumps(state,ensure_ascii=False),state['revision'],state['updated'],task_id))
            db.execute('INSERT INTO events(task_id,kind,details,created) VALUES(?,?,?,?)',
                       (task_id,'unsubmitted_approved_attempt_continued',json.dumps(details,ensure_ascii=False),state['updated']))
            return state

    def publish_progress(self, task_id, effect_id, phase, details=None):
        if phase not in {'uploading', 'submitting', 'platform_processing'}:
            raise ValueError('알 수 없는 게시 단계')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM records WHERE task_id=?', (task_id,)).fetchone()
            state = json.loads(row[0]) if row else {}
            effect = db.execute('SELECT * FROM effects WHERE id=?', (effect_id,)).fetchone()
            if (not effect or effect['kind'] != 'instagram_publish' or effect['status'] != 'dispatching'
                    or state.get('effect_id') != effect_id or state.get('status') != 'running'):
                raise MonetizationConflict('게시 실행 소유권이 달라졌습니다.')
            progress = {**state.get('publication', {}), **(details or {}), 'phase': phase, 'updated': time.time()}
            state.update(publication=progress, updated=time.time(), revision=state['revision'] + 1)
            db.execute('UPDATE records SET revision=?,state=?,updated=? WHERE task_id=?',
                       (state['revision'], json.dumps(state, ensure_ascii=False), state['updated'], task_id))
            db.execute('INSERT INTO events(task_id,kind,details,created) VALUES(?,?,?,?)',
                       (task_id, phase, json.dumps(progress, ensure_ascii=False), state['updated']))

    def resolve_effect(self, task_id, effect_id, status, details, changes, *, reconcile=False, expected_revision=None):
        """Atomically accept the external receipt AND its video-independent state."""
        if status not in {'completed', 'error', 'unknown'}:
            raise ValueError('올바르지 않은 동작 결과')
        if {'task_id', 'account', 'discovery_account', 'shortcode', 'binding', 'created', 'revision', 'effect_id','product_retry'}.intersection(changes):
            raise ValueError('대상 식별자는 변경할 수 없습니다.')
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM records WHERE task_id=?', (task_id,)).fetchone()
            state = json.loads(row[0]) if row else {}
            effect = db.execute('SELECT * FROM effects WHERE id=?', (effect_id,)).fetchone()
            recovering = (reconcile and effect and effect['kind'] == 'littly_create'
                          and effect['status'] == 'unknown' and state.get('status') == 'error'
                          and state.get('stage') == 'littly' and status == 'completed'
                          and expected_revision == state.get('revision'))
            if (not effect or (not recovering and (effect['status'] != 'dispatching' or state.get('status') != 'running'))
                    or state.get('effect_id') != effect_id):
                raise MonetizationConflict('해당 외부 동작의 실행 소유권이 없습니다.')
            if status == 'completed' and effect['kind'] == 'littly_create':
                count = db.execute('UPDATE next_post_slots SET status=?,details=?,updated=? WHERE account=? AND task_id=? AND status=?',
                    ('registered', json.dumps(details, ensure_ascii=False), now, state['account'], task_id, 'reserved')).rowcount
                if count != 1:
                    raise MonetizationConflict('다음 게시물 예약 소유권이 없습니다.')
            if status == 'error':
                # No next-post automation can have been created by discovery.
                # Keep the one-shot effect forever, but let another reference
                # proceed after this product's definitive discovery error.
                db.execute("DELETE FROM next_post_slots WHERE account=? AND task_id=? AND status='workflow'",
                           (state['account'], task_id))
            state.update(changes)
            state.update(status='ready' if status == 'completed' else 'error',
                         updated=now, revision=state['revision'] + 1)
            db.execute('UPDATE records SET revision=?,state=?,updated=? WHERE task_id=?',
                (state['revision'], json.dumps(state, ensure_ascii=False), now, task_id))
            old_details = json.loads(effect['details'])
            db.execute('UPDATE effects SET status=?,details=?,updated=? WHERE id=?',
                (status, json.dumps({**old_details, **details}, ensure_ascii=False), now, effect_id))
            db.execute('INSERT INTO events(task_id,kind,details,created) VALUES(?,?,?,?)',
                (task_id, effect['kind'] + '_' + status, json.dumps(changes, ensure_ascii=False), now))
            return state

    def recover_abandoned(self):
        with self.connect() as db:
            pending = db.execute("SELECT * FROM effects WHERE status='dispatching'").fetchall()
        for effect in pending:
            try:
                with effect_lease(self.root, effect['id']):
                    with self.connect() as db:
                        db.execute('BEGIN IMMEDIATE')
                        current = db.execute('SELECT status FROM effects WHERE id=?', (effect['id'],)).fetchone()
                        if current[0] != 'dispatching':
                            continue
                        details = json.loads(effect['details'])
                        details.update(error='실행 소유자가 종료돼 외부 결과를 확인할 수 없습니다. 재요청하지 않습니다.',
                                       outcome='interrupted_unknown')
                        db.execute('UPDATE effects SET status=?,details=?,updated=? WHERE id=?',
                            ('unknown', json.dumps(details, ensure_ascii=False), time.time(), effect['id']))
                        rows = db.execute('SELECT task_id,state FROM records WHERE shortcode=? AND json_extract(state,\'$.effect_id\')=?',
                                          (effect['shortcode'], effect['id'])).fetchall()
                        for row in rows:
                            state = json.loads(row['state'])
                            if state.get('effect_id') != effect['id']:
                                continue
                            state.update(status='error', error=details['error'], updated=time.time(), revision=state['revision'] + 1)
                            db.execute('UPDATE records SET state=?,revision=?,updated=? WHERE task_id=?',
                                (json.dumps(state, ensure_ascii=False), state['revision'], state['updated'], row['task_id']))
                            db.execute("DELETE FROM next_post_slots WHERE account=? AND task_id=? AND status='workflow'",
                                       (state['account'], row['task_id']))
                            db.execute('INSERT INTO events(task_id,kind,details,created) VALUES(?,?,?,?)',
                                (row['task_id'], 'interrupted_unknown', json.dumps(details, ensure_ascii=False), time.time()))
            except MonetizationConflict:
                continue  # A verified live lease owner is not interrupted.

    def finish_effect(self, effect_id, status, details):
        if status not in {'completed', 'error', 'unknown'}:
            raise ValueError('올바르지 않은 동작 결과')
        with self.connect() as db:
            changed = db.execute('UPDATE effects SET status=?,details=?,updated=? WHERE id=? AND status=?',
                (status, json.dumps(details, ensure_ascii=False), time.time(), effect_id, 'dispatching')).rowcount
            if changed != 1:
                raise MonetizationConflict('이미 종료됐거나 소유하지 않은 동작입니다.')

    def effects(self, state):
        with self.connect() as db:
            rows = db.execute('''SELECT id,kind,status,details,created,updated FROM effects WHERE shortcode=?
                AND ((kind='product_discovery' AND account=?) OR (kind!='product_discovery' AND account=?))''',
                              (state['shortcode'],canonical_account(state.get('discovery_account',state['account'])),canonical_account(state['account']))).fetchall()
        return [{**dict(row), 'details': json.loads(row['details'])} for row in rows]

    def reserve_next_post(self, state):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            account = canonical_account(state['account'])
            row = db.execute('SELECT * FROM next_post_slots WHERE account=?', (account,)).fetchone()
            if row:
                raise MonetizationConflict('이 인스타 계정에 다음 게시물 자동화가 이미 예약됐거나 결과 확인 중입니다.')
            db.execute('INSERT INTO next_post_slots VALUES(?,?,?,?,?)',
                (account, state['task_id'], 'reserved', '{}', time.time()))

    def confirm_next_post(self, state, receipt):
        """A slot stays occupied until a verified post association is recorded."""
        with self.connect() as db:
            count = db.execute('UPDATE next_post_slots SET status=?,details=?,updated=? WHERE account=? AND task_id=?',
                ('registered', json.dumps(receipt, ensure_ascii=False), time.time(),
                 canonical_account(state['account']), state['task_id'])).rowcount
            if count != 1:
                raise MonetizationConflict('다음 게시물 예약 소유권이 없습니다.')

    def associate_post(self, state, receipt):
        if not receipt.get('post_id') or not receipt.get('automation_id') or not receipt.get('verified'):
            raise ValueError('실제 게시물·자동화 연결 확인이 필요합니다.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            account = canonical_account(state['account'])
            row = db.execute('SELECT * FROM next_post_slots WHERE account=?', (account,)).fetchone()
            if not row or row['task_id'] != state['task_id'] or row['status'] != 'registered':
                raise MonetizationConflict('연결을 확인할 등록 자동화가 없습니다.')
            original = json.loads(row['details'])
            if original.get('automation_id') != receipt['automation_id']:
                raise ValueError('등록한 자동화와 게시물 연결 대상이 다릅니다.')
            db.execute('DELETE FROM next_post_slots WHERE account=?', (account,))
            db.execute('INSERT INTO events(task_id,kind,details,created) VALUES(?,?,?,?)',
                (state['task_id'], 'post_associated', json.dumps(receipt, ensure_ascii=False), time.time()))
            row = db.execute('SELECT state FROM records WHERE task_id=?', (state['task_id'],)).fetchone()
            current = json.loads(row[0])
            if current['revision'] != state['revision']:
                raise MonetizationConflict('게시물 연결 확인 중 다른 변경이 저장됐습니다.')
            current.update(stage='awaiting_delivery', post_connection=receipt, delivery_verified=False,
                           status='ready', error='',
                           updated=time.time(), revision=current['revision'] + 1)
            # Reconciliation is read-only. Preserve the uncertain upload
            # effect and append its observed result; never make it dispatchable.
            if current.get('publication'):
                current['publication'].update(phase='post_connected', post_url=receipt.get('post_url'),
                                              connection_verified=True, updated=time.time())
            db.execute('UPDATE records SET revision=?,state=?,updated=? WHERE task_id=?',
                (current['revision'], json.dumps(current, ensure_ascii=False), current['updated'], current['task_id']))
            return current
