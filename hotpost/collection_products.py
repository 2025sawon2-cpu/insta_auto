"""Collection product outbox; visible Chrome actions are performed by the collector.

Publishing never sends a comment. The daily collector consumes this durable outbox
with its existing browser tools and records each observed result before advancing.
External effects share the legacy actor/shortcode uniqueness ledger.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid

from .coupang_onelink import storefront_url, link_identity
from .coupang_partners import product_identity, verify_product_match
from .monetization_store import MonetizationStore, canonical_account

ACTIVE = ('comment_reserved', 'comment_confirmed', 'dm_received', 'product_verified', 'link_reserved')
NEXT = dict(comment_reserved='comment_confirmed', comment_confirmed='dm_received',
            dm_received='product_verified', product_verified='link_reserved', link_reserved='completed')


@contextmanager
def admission(root):
    from .state_lock import file_lock
    with file_lock(Path(root)/'monetization/product-admission.lock'):
        yield


def keyword_from_caption(caption):
    from .daily_ranking import post_body
    body = post_body(caption)
    matches = re.findall(r"(?:댓글[^\n]{0,25}|궁금하신[^\n]{0,20})[‘'\"“]([^’'\"”\n]{1,30})[’'\"”][^\n]{0,25}(?:남겨|댓글)", body)
    words = set(matches)
    if len(words) == 1:
        word = next(iter(words))
        return {'keyword': word, 'quote': next(line for line in body.splitlines() if word in line)}
    if not words and re.search(r'아무\s*(?:글자|댓글)', body):
        return {'keyword': '나도', 'quote': next(line for line in body.splitlines() if re.search(r'아무\s*(?:글자|댓글)', line))}
    raise ValueError('댓글 요청 키워드를 한 개로 확인하지 못했습니다. 추정 댓글을 보내지 마세요.')


def _code(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise ValueError('Invalid shortcode')
    return value


def read_result(root, code):
    """No schema creation, recovery, browser calls or draft writes on page reads."""
    path = Path(root) / 'monetization/state.sqlite3'
    if not path.is_file():
        return None
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='collection_product_queue'").fetchone():
            return None
        row = db.execute('SELECT state FROM collection_product_queue WHERE shortcode=?', (code,)).fetchone()
    if not row:
        return None
    state = json.loads(row[0])
    if state['status'] == 'cancelled':
        return None  # A cancelled local test owns no external operation or UI result.
    result = {'status': state['status'], 'message': state.get('message', '')}
    if state['status'] == 'completed':
        ready = state['steps']['completed']['value']
        link_identity(ready['one_link'])
        result.update({k: ready[k] for k in ('one_link', 'product_name', 'product_url', 'storefront_url')})
    return result


class CollectionProducts:
    def __init__(self, root):
        self.root = Path(root)
        self.store = MonetizationStore(self.root / 'monetization')
        with self.store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS collection_product_seen (shortcode TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS collection_product_queue (
                    shortcode TEXT PRIMARY KEY, state TEXT NOT NULL);
            ''')

    def config(self):
        with self.store.connect() as db:
            row = db.execute("SELECT value FROM configuration WHERE name='collection_products'").fetchone()
            installation = db.execute("SELECT value FROM configuration WHERE name='installation'").fetchone()
        value = json.loads(row[0]) if row else {'enabled': False}
        if installation:
            saved = json.loads(installation[0])['values']
            value = {**value,'account':saved['discovery_account'],
                     'storefront_url':saved['storefront_url'],'collection':saved['collection']}
        return value

    def configure(self, account, storefront, collection, browser_extension):
        value = dict(enabled=True, account=canonical_account(account), storefront_url=storefront_url(storefront),
                     collection=collection.strip(), browser_extension=browser_extension.strip(),
                     scope='newly_collected_qualified_only')
        if not value['collection'] or not value['browser_extension']:
            raise ValueError('확인한 Chrome 연결과 컬렉션이 필요합니다.')
        # Establish the installation boundary; never backfill historical posts.
        known = set()
        if (self.root / 'hotpost.db').is_file():
            with closing(sqlite3.connect((self.root/'hotpost.db').resolve().as_uri()+'?mode=ro', uri=True)) as prior:
                known.update(r[0] for r in prior.execute('SELECT shortcode FROM posts'))
        if (self.root / 'report.json').is_file():
            known.update(p['shortcode'] for p in json.loads((self.root/'report.json').read_text('utf8'))['posts'])
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute("SELECT value FROM configuration WHERE name='collection_products'").fetchone()
            if old and json.loads(old[0]) != value:
                raise ValueError('기존 설정이 다릅니다. 진행 중 작업을 확인한 뒤 별도로 변경하세요.')
            db.executemany('INSERT OR IGNORE INTO collection_product_seen VALUES(?)', ((c,) for c in known))
            db.execute("INSERT OR REPLACE INTO configuration VALUES('collection_products',?)", (json.dumps(value),))
        return value

    @staticmethod
    def _save(db, state):
        db.execute('INSERT INTO collection_product_queue VALUES(?,?) ON CONFLICT(shortcode) DO UPDATE SET state=excluded.state',
                   (state['shortcode'], json.dumps(state, ensure_ascii=False)))

    def get(self, code):
        with self.store.connect() as db:
            row = db.execute('SELECT state FROM collection_product_queue WHERE shortcode=?', (_code(code),)).fetchone()
        if not row:
            raise ValueError('상품 확인 대기열에 없는 게시물입니다.')
        return json.loads(row[0])

    def items(self):
        with self.store.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT state FROM collection_product_queue ORDER BY rowid')]

    def enqueue(self, report, known=(), *, test_code=None, authorization=None):
        config = self.config()
        if not config['enabled']:
            return []
        if report.get('is_sample') or report.get('ranking_mode') != 'views_per_follower_72h':
            raise ValueError('실제 72시간 수집 리포트만 사용할 수 있습니다.')
        if test_code and not authorization:
            raise ValueError('기존 게시물 실검증에는 명시 사용자 지시가 필요합니다.')
        added = []
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.executemany('INSERT OR IGNORE INTO collection_product_seen VALUES(?)', ((c,) for c in known))
            for post in report['posts']:
                code = _code(post['shortcode'])
                seen = db.execute('SELECT 1 FROM collection_product_seen WHERE shortcode=?', (code,)).fetchone()
                existing = db.execute('SELECT 1 FROM collection_product_queue WHERE shortcode=?', (code,)).fetchone()
                if ((not seen or code == test_code) and not existing and post.get('eligible') is True
                        and post.get('kind') == 'reel' and (not test_code or code == test_code)):
                    from .daily_ranking import excluded_topics
                    if not excluded_topics(post.get('caption', '')):
                        state = dict(shortcode=code, author=post['username'], caption=post['caption'],
                                     snapshot=report['collection_started_at'], config=config,
                                     status='pending', created=time.time(), steps={}, revision=0)
                        if test_code:
                            state['test_authorization'] = authorization
                        self._save(db, state)
                        added.append(code)
                db.execute('INSERT OR IGNORE INTO collection_product_seen VALUES(?)', (code,))
        return added

    def _prior_link_job(self, code):
        path = self.root/'post-preparation.sqlite3'
        if not path.is_file():
            return None
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            table = db.execute("SELECT 1 FROM sqlite_master WHERE name='coupang_link_jobs'").fetchone()
            row = db.execute('SELECT * FROM coupang_link_jobs WHERE shortcode=? ORDER BY created DESC,rowid DESC LIMIT 1', (code,)).fetchone() if table else None
            return dict(row) if row else None

    def evidence(self, path):
        path = Path(path).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError('근거는 이 저장소의 Git 제외 data 폴더에 보관하세요.')
        raw = path.read_bytes()
        value = json.loads(raw)
        stamp = value.get('observed_at')
        if not isinstance(stamp, (int, float)) or isinstance(stamp, bool):
            raise ValueError('실제 관측 시각 observed_at이 필요합니다.')
        return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(), value=value)

    def begin(self, code, evidence):
        with admission(self.root):
            return self._begin(code, evidence)

    def _begin(self, code, evidence):
        proof = self.evidence(evidence)
        state = self.get(code)
        config, value = state['config'], proof['value']
        report = json.loads((self.root/'report.json').read_text('utf8'))
        published = any(p['shortcode'] == code and p.get('eligible') is True for p in report['posts'])
        if not published or (not state.get('test_authorization') and state['snapshot'] > report['collection_started_at']):
            raise ValueError('아직 현재 리포트에 반영된 신규 적격 게시물이 아닙니다.')
        if any(value.get(k) != expected for k, expected in
               [('account', config['account']), ('author', state['author']), ('shortcode', code),
                ('browser_extension', config['browser_extension']), ('storefront_url', config['storefront_url'])]):
            raise ValueError('실제 Chrome·인스타·스토어·게시물 연결이 설정과 다릅니다.')
        keyword = keyword_from_caption(value.get('caption', ''))
        if value.get('keyword') != keyword['keyword'] or not isinstance(value.get('dm_baseline'), list):
            raise ValueError('원작의 실제 댓글 키워드와 기존 DM 기준선이 필요합니다.')
        prior_job = self._prior_link_job(code)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = json.loads(db.execute('SELECT state FROM collection_product_queue WHERE shortcode=?', (code,)).fetchone()[0])
            if current['status'] != 'pending':
                raise ValueError('이미 시작한 시도입니다. 댓글을 다시 보내지 마세요.')
            if prior_job:
                result = json.loads(prior_job['result'])
                if (prior_job['status'] != 'completed' or result.get('landing_verified') is not True
                        or result.get('status') != 'one_link_ready'):
                    raise ValueError('기존 원링크 시도 이력이 있습니다. 자동으로 다시 시작하지 않습니다.')
                identity = link_identity(result.get('one_link',''))
                if (result.get('storefront_url') != config['storefront_url']
                        or product_identity(result.get('final_url','')) != identity or not result.get('product_name')):
                    raise ValueError('기존 원링크의 내 스토어·상품·옵션 검증이 일치하지 않습니다.')
                result = {**result, 'product_url':result['final_url']}
                current.update(status='completed',reused_link_job_id=prior_job['id'],revision=current['revision']+1)
                current['steps']['completed'] = {'value':result, 'source':'existing_verified_link_job'}
                self._save(db,current)
                return current
            if any(json.loads(r[0])['status'] in ACTIVE for r in db.execute('SELECT state FROM collection_product_queue')):
                raise ValueError('앞선 상품 확인 시도가 아직 끝나지 않았습니다.')
            effect = uuid.uuid4().hex
            try:
                db.execute('INSERT INTO effects VALUES(?,?,?,?,?,?,?,?)',
                           (config['account'], code, 'product_discovery', effect, 'dispatching',
                            json.dumps({'origin':'collection','attempt_count':1,'evidence':proof['path']}),time.time(),time.time()))
            except sqlite3.IntegrityError:
                raise ValueError('이 계정·게시물의 기존 상품 확인 시도가 있습니다. 자동 재시도하지 않습니다.') from None
            current.update(status='comment_reserved', token=uuid.uuid4().hex, effect_id=effect,
                           reserved_at=time.time(), revision=current['revision']+1)
            current['steps']['comment_reserved'] = proof
            self._save(db, current)
        return current

    def advance(self, code, token, stage, evidence):
        proof = self.evidence(evidence)
        value = proof['value']
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = json.loads(db.execute('SELECT state FROM collection_product_queue WHERE shortcode=?', (_code(code),)).fetchone()[0])
            followup = stage == 'dm_received' and state['status'] == 'dm_received'
            if state.get('token') != token or (NEXT.get(state['status']) != stage and not followup):
                raise ValueError('현재 시도·단계와 다릅니다. 재전송하지 마세요.')
            effect = db.execute('SELECT status FROM effects WHERE id=?', (state['effect_id'],)).fetchone()
            if not effect or effect[0] != 'dispatching':
                raise ValueError('시도 결과가 불명확하거나 이미 종료됐습니다. 완료로 덮어쓰지 않습니다.')
            if value['observed_at'] < state['reserved_at']:
                raise ValueError('현재 시도보다 이전의 근거입니다.')
            if stage == 'comment_confirmed':
                if (value.get('account') != state['config']['account'] or not value.get('comment_id')
                        or value.get('keyword') != state['steps']['comment_reserved']['value']['keyword']):
                    raise ValueError('우리 계정의 실제 새 댓글 확인이 필요합니다.')
            elif stage == 'dm_received':
                baseline = state['steps']['comment_reserved']['value']['dm_baseline']
                if (value.get('sender') != state['author'] or value.get('incoming') is not True
                        or not value.get('message_id') or value['message_id'] in baseline):
                    raise ValueError('댓글 이후 원작성자가 보낸 새 DM만 사용할 수 있습니다.')
                if followup:
                    reserved = db.execute("SELECT 1 FROM effects WHERE account=? AND shortcode=? AND kind='collection_follow_check'",
                                          (state['config']['account'],code)).fetchone()
                    if (not reserved or 'dm_received_followup' in state['steps']
                            or value['message_id'] == state['steps']['dm_received']['value']['message_id']):
                        raise ValueError('팔로우 확인 이후의 실제 새 상품 DM만 한 번 기록하세요.')
            elif stage == 'product_verified':
                identity = product_identity(value.get('product_url', ''))
                received = state['steps'].get('dm_received_followup',state['steps']['dm_received'])['value']
                if (len(identity) != 3 or not value.get('product_name') or not value.get('dm_button_url')
                        or value.get('message_id') != received['message_id']):
                    raise ValueError('DM 버튼과 정확한 상품·옵션 세 식별자를 확인하세요.')
            elif stage == 'link_reserved':
                if (value.get('storefront_url') != state['config']['storefront_url']
                        or value.get('collection') != state['config']['collection']):
                    raise ValueError('로그인한 내 스토어·컬렉션을 확인하세요.')
                effect = uuid.uuid4().hex
                db.execute('INSERT INTO effects VALUES(?,?,?,?,?,?,?,?)',
                           (state['config']['account'],code,'collection_onelink',effect,'dispatching',
                            json.dumps({'origin':'collection','evidence':proof['path']}),time.time(),time.time()))
            elif stage == 'completed':
                original = state['steps']['product_verified']['value']
                identity = link_identity(value.get('one_link', ''))
                own_record = value.get('store_record_evidence', {})
                if (identity != product_identity(original['product_url']) or value.get('landing_verified') is not True
                        or value.get('storefront_url') != state['config']['storefront_url']
                        or value.get('product_url') != original['product_url'] or not isinstance(own_record, dict)
                        or own_record.get('one_link') != value.get('one_link')
                        or own_record.get('storefront_url') != state['config']['storefront_url']
                        or any(own_record.get(k) != v for k,v in identity.items())
                        or not value.get('product_name')):
                    raise ValueError('내 스토어 원링크·확인 상품·실제 랜딩의 일치 근거가 필요합니다.')
                verify_product_match(original['product_url'], value.get('final_url', ''))
                for prior in state['steps'].values():
                    if hashlib.sha256(Path(prior['path']).read_bytes()).hexdigest() != prior['sha256']:
                        raise ValueError('이전 단계 근거 파일이 달라졌습니다.')
                db.execute("UPDATE effects SET status='completed',updated=? WHERE account=? AND shortcode=? AND (kind='product_discovery' OR kind LIKE 'collection_%')",
                           (time.time(),state['config']['account'],code))
            state.update(status=stage,revision=state['revision']+1)
            state['steps']['dm_received_followup' if followup else stage] = proof
            self._save(db,state)
        return state

    def fail(self, code, token, reason):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = json.loads(db.execute('SELECT state FROM collection_product_queue WHERE shortcode=?', (_code(code),)).fetchone()[0])
            if state.get('token') != token or state['status'] not in ACTIVE:
                raise ValueError('현재 실행 중인 시도만 실패 기록할 수 있습니다.')
            state.update(status='failed', message=reason, revision=state['revision']+1)
            self._save(db,state)
            db.execute("UPDATE effects SET status='error',updated=? WHERE account=? AND shortcode=? AND (kind='product_discovery' OR kind LIKE 'collection_%')",
                       (time.time(),state['config']['account'],code))
        return state

    def reserve_action(self, code, token, action):
        """Reserve optional follow/check/product-button clicks before dispatch."""
        if action not in ('follow', 'follow_check', 'product_button'):
            raise ValueError('알 수 없는 외부 동작입니다.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = json.loads(db.execute('SELECT state FROM collection_product_queue WHERE shortcode=?', (_code(code),)).fetchone()[0])
            allowed = ('comment_reserved','comment_confirmed','dm_received') if action != 'product_button' else ('dm_received',)
            if state.get('token') != token or state['status'] not in allowed:
                raise ValueError('현재 단계에서 실행할 수 없는 외부 동작입니다.')
            kind = 'collection_' + action
            try:
                db.execute('INSERT INTO effects VALUES(?,?,?,?,?,?,?,?)',
                           (state['config']['account'],code,kind,uuid.uuid4().hex,'dispatching','{"origin":"collection"}',time.time(),time.time()))
            except sqlite3.IntegrityError:
                raise ValueError('이미 예약한 버튼·팔로우입니다. 결과가 불명확해도 다시 누르지 마세요.') from None
        return {'reserved': action, 'shortcode':code}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    conf = sub.add_parser('configure')
    for key in ('account','storefront','collection','browser-extension'):
        conf.add_argument('--'+key, required=True)
    sub.add_parser('list')
    test = sub.add_parser('add-test')
    test.add_argument('--code',required=True); test.add_argument('--authorization',required=True)
    begin = sub.add_parser('begin')
    begin.add_argument('--code',required=True); begin.add_argument('--evidence',type=Path,required=True)
    record = sub.add_parser('record')
    for key in ('code','token','stage','evidence'):
        record.add_argument('--'+key,required=True)
    failure = sub.add_parser('fail')
    for key in ('code','token','reason'):
        failure.add_argument('--'+key,required=True)
    action = sub.add_parser('reserve-action')
    for key in ('code','token','action'):
        action.add_argument('--'+key,required=True)
    args = parser.parse_args(argv)
    from .config import load_settings
    settings = load_settings(); service = CollectionProducts(settings.data_dir)
    if args.command == 'configure':
        result = service.configure(args.account,args.storefront,args.collection,args.browser_extension)
    elif args.command == 'list':
        result = service.items()
    elif args.command == 'add-test':
        result = service.enqueue(json.loads(settings.report_path.read_text('utf8')),test_code=args.code,authorization=args.authorization)
    elif args.command == 'begin':
        result = service.begin(args.code,args.evidence)
    elif args.command == 'record':
        result = service.advance(args.code,args.token,args.stage,args.evidence)
    elif args.command == 'reserve-action':
        result = service.reserve_action(args.code,args.token,args.action)
    else:
        result = service.fail(args.code,args.token,args.reason)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
