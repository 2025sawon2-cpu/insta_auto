"""Durable explicit One-Link attempts, separate from drafts and production."""
import json
import os
import threading
import time
import uuid

import psutil

from .coupang_onelink import find_one_link, link_identity, storefront_url
from .coupang_partners import product_identity, verify_product_match
from .post_preparation import DraftConflict


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS coupang_link_jobs (
        id TEXT PRIMARY KEY, shortcode TEXT NOT NULL, status TEXT NOT NULL,
        payload TEXT NOT NULL, result TEXT NOT NULL, message TEXT NOT NULL,
        created REAL NOT NULL, owner_pid INTEGER NOT NULL, owner_birth REAL NOT NULL)''')


def _alive(row):
    try:
        return psutil.Process(row['owner_pid']).create_time() == row['owner_birth']
    except psutil.Error:
        return False


def _public(row):
    if row is None:
        return dict(status='idle', payload={'storefront_url': os.environ.get('COUPANG_STOREFRONT_URL', '')})
    state = dict(id=row['id'], status=row['status'], payload=json.loads(row['payload']),
                 result=json.loads(row['result']), message=row['message'])
    if state['status'] == 'running' and not _alive(row):
        state.update(status='interrupted', message='직전 요청이 중단됐습니다. 스토어 상태를 확인하세요. 자동 재실행하지 않습니다.')
    return state


def status(service, code):
    with service.connect() as db:
        row = db.execute('SELECT * FROM coupang_link_jobs WHERE shortcode=? ORDER BY created DESC, rowid DESC LIMIT 1', (code,)).fetchone()
    return _public(row)


def start(service, code, payload, *, finder=None):
    from .collection_products import admission
    with admission(service.root):
        return _start(service, code, payload, finder=finder)


def _start(service, code, payload, *, finder=None):
    from .collection_products import read_result
    collected = read_result(service.root, code)
    if collected and collected['status'] != 'cancelled':
        raise ValueError('수집 단계의 상품 확인 이력이 있습니다. 저장된 결과·실패를 확인하고 중복 등록하지 마세요.')
    if (not isinstance(payload, dict) or set(payload) != {'revision', 'product_name', 'storefront_url', 'product_url', 'register'}
            or type(payload['revision']) is not int or payload['revision'] < 0
            or type(payload['register']) is not bool):
        raise ValueError('원링크 요청의 입력 항목을 확인하세요.')
    query = {key: payload[key] for key in ('product_name', 'storefront_url', 'product_url', 'register')}
    for key, limit in [('product_name', 300), ('storefront_url', 2048), ('product_url', 2048)]:
        if not isinstance(query[key], str) or len(query[key]) > limit:
            raise ValueError('원링크 검색 입력의 길이·형식을 확인하세요.')
        query[key] = query[key].strip()
    if not query['product_name']:
        raise ValueError('제품명 풀네임을 입력하세요.')
    storefront_url(query['storefront_url'])
    if query['product_url']:
        product_identity(query['product_url'])
    if not service.source(code)['media']['final']:
        raise ValueError('완성 영상이 준비된 게시물에서 원링크를 찾을 수 있습니다.')
    job_id, created = uuid.uuid4().hex, time.time()
    with service.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT revision FROM drafts WHERE shortcode=?', (code,)).fetchone()
        if (row['revision'] if row else 0) != payload['revision']:
            raise DraftConflict('다른 화면에서 초안이 변경됐습니다. 저장 상태를 확인하세요.')
        for active in db.execute("SELECT * FROM coupang_link_jobs WHERE status='running'").fetchall():
            if _alive(active):
                raise DraftConflict('진행 중인 원링크 요청이 있습니다. 현재 요청의 결과를 먼저 확인하세요.')
            db.execute("UPDATE coupang_link_jobs SET status='interrupted', message=? WHERE id=?",
                       ('요청이 중단됐습니다. 스토어 확인 전 자동 재등록하지 않습니다.', active['id']))
        db.execute('INSERT INTO coupang_link_jobs VALUES (?,?,?,?,?,?,?,?,?)',
                   (job_id, code, 'running', json.dumps(query, ensure_ascii=False), '{}',
                    '쿠팡 원링크를 찾고 실제 연결 상품을 확인하고 있습니다.', created,
                    os.getpid(), psutil.Process().create_time()))

    def run():
        try:
            result = (finder or find_one_link)(service.settings, query)
            # Do not accept the upstream short-url fallback or metadata-only verification.
            if result.get('status') != 'one_link_ready' or result.get('landing_verified') is not True:
                raise ValueError('실제 연결 상품 검증을 완료하지 못했습니다. 기존 제품 링크를 유지합니다.')
            identity = link_identity(result['one_link'])
            if any(result.get(key) != value for key, value in identity.items()):
                raise ValueError('원링크와 결과의 상품·옵션이 다릅니다.')
            expected = ('https://www.coupang.com/vp/products/' + identity['product_id']
                        + '?itemId=' + identity['item_id'] + '&vendorItemId=' + identity['vendor_item_id'])
            verify_product_match(expected, result.get('final_url', ''))
            if query['product_url']:
                verify_product_match(query['product_url'], result['final_url'])
            message, outcome = '원링크 확인 완료. 상품·옵션을 확인하고 아래 사용 버튼을 누르세요.', 'completed'
        except Exception as exc:
            result, outcome = {}, 'failed'
            message = str(exc) if isinstance(exc, ValueError) else '원링크 요청이 중단됐습니다. 기존 Chrome 연결·로그인·현재 화면을 확인하세요.'
        with service.connect() as db:
            db.execute('UPDATE coupang_link_jobs SET status=?, result=?, message=? WHERE id=?',
                       (outcome, json.dumps(result, ensure_ascii=False), message, job_id))

    try:
        threading.Thread(target=run, daemon=True, name='publication-coupang-' + job_id).start()
    except Exception:
        with service.connect() as db:
            db.execute("UPDATE coupang_link_jobs SET status='failed', message=? WHERE id=?", ('요청을 시작하지 못했습니다.', job_id))
        raise ValueError('원링크 요청을 시작하지 못했습니다.') from None
    return dict(id=job_id, status='running', payload=query, result={},
                message='원링크 요청을 시작했습니다. 화면을 닫아도 결과는 보존됩니다.')
