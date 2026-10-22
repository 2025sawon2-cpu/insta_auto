"""Task-bound receipts for interrupted acquisition, independent of approval."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from .source_access_preflight import SourceAccessWaiting
from .source_search.strategy import merge_history, candidate_ledgers


class SourceReceiptWaiting(SourceAccessWaiting):
    """Unsettled or unverifiable evidence must not authorize another request."""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_bound_json(path):
    raw=Path(path).read_bytes()
    return json.loads(raw.decode('utf-8')), hashlib.sha256(raw).hexdigest()


def binding(state, job):
    reference=Path(state.get('reference_video') or '')
    result={'task_id': state['id'], 'studio_job_id': job['id'],
            'run_id': job.get('payload', {}).get('run_id', state.get('run_id')),
            'shortcode': state['shortcode'], 'source_request':job.get('payload',{}).get('request',''),
            'reference_sha256':sha(reference) if reference.is_file() else None}
    from .source_policy import run_policy
    from .source_coverage import diversity_required, search_scope_for_state
    policy=run_policy(state)
    if diversity_required(policy):
        result.update(source_policy=policy,search_context=search_scope_for_state(state))
    return result


def validate_root(source_dir, descriptor, state, job):
    if any(descriptor.get(k) != v for k, v in binding(state, job).items()):
        raise SourceReceiptWaiting('수집 중단 영수증의 작업·실행 결속 확인 대기')
    try:path = Path(descriptor['manifest_path']).resolve()
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceReceiptWaiting('수집 중단 영수증 식별 경로 확인 대기') from exc
    root = path.parent
    if (path.name != 'manifest.json' or root.parent != Path(source_dir).resolve()
            or not re.fullmatch(re.escape(state['shortcode']) + r'-\d+', root.name)):
        raise SourceReceiptWaiting('수집 중단 영수증 경로 확인 대기')
    return path


def validate_child(manifest, path):
    try:path = Path(path).resolve()
    except (TypeError,ValueError) as exc:
        raise SourceReceiptWaiting('등록된 검색 체크포인트 식별 확인 대기') from exc
    if (path.parent.parent != Path(manifest).resolve().parent
            or path.parent.name not in {'browser_debug', 'refinement_debug'}
            or not re.fullmatch(r'search-checkpoint-[a-f0-9]{32}\.json', path.name)):
        raise SourceReceiptWaiting('등록된 검색 체크포인트 경로 확인 대기')
    return path


def snapshot(source_dir, descriptor, state, job):
    """Read only registered, settled checkpoints. Never scan sibling attempts."""
    manifest = validate_root(source_dir, descriptor, state, job)
    if any(not w.get('settled') for w in descriptor.get('workers', [])):
        raise SourceReceiptWaiting('수집 작업자 종료 미확인 · 실제 기록 확인 대기')
    try:
        data, manifest_sha = read_bound_json(manifest)
        if data.get('shortcode') != state['shortcode'] or data.get('job_id') != manifest.parent.name:
            raise SourceReceiptWaiting('수집 중단 원본 영수증 식별 확인 대기')
        scope=binding(state,job)
        if scope.get('search_context') and any(k in data and data[k]!=scope[k] for k in ('run_id','search_context')):
            raise SourceReceiptWaiting('수집 중단 manifest의 실행·제품 범위 결속 확인 대기')
        searches = copy.deepcopy(data.get('search_audit', []))
        if data.get('execution_audit_available') is False and not descriptor.get('workers'):
            raise SourceReceiptWaiting('실제 검색 실행 기록 미확정 · 자동 재검색 보류')
        candidates = {r['url']: copy.deepcopy(r) for r in data.get('candidates', []) if r.get('url')}
        checkpoints = []
        for worker in descriptor.get('workers', []):
            path = validate_child(manifest, worker['path'])
            if not path.is_file():
                raise SourceReceiptWaiting('등록된 검색 체크포인트 누락 · 실제 요청 기록 확인 대기')
            saved, digest = read_bound_json(path)
            checkpoints.append({'path': str(path), 'sha256': digest})
            searches.extend(copy.deepcopy(saved.get('searches', [])))
            for row in saved.get('candidates', []):
                if row.get('url'):
                    candidates.setdefault(row['url'], copy.deepcopy(row))
        if scope.get('search_context'):
            from .source_coverage import bind_search_rows
            searches=bind_search_rows(searches,scope['run_id'],scope['search_context'])
        return {**scope, 'manifest_path': str(manifest),
                'manifest_sha256': manifest_sha, 'worker_checkpoints': checkpoints,
                'searches': searches, 'candidates': list(candidates.values())}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SourceReceiptWaiting('수집 중단 실제 기록 읽기·무결성 확인 대기') from exc


def verified_receipt(source_dir, descriptor, state, job):
    validate_root(source_dir, descriptor, state, job)
    try:
        path = Path(descriptor['receipt_path']).resolve()
        if path != Path(descriptor['manifest_path']).resolve().parent/'interrupted-execution-receipt.json':
            raise SourceReceiptWaiting('저장된 수집 중단 영수증 소유 경로 확인 대기')
        if sha(path) != descriptor['receipt_sha256']:
            raise SourceReceiptWaiting('저장된 수집 중단 영수증 SHA 확인 대기')
        receipt = json.loads(path.read_text(encoding='utf-8'))
        if any(receipt.get(k) != v for k, v in binding(state, job).items()):
            raise SourceReceiptWaiting('저장된 수집 중단 영수증 작업 결속 확인 대기')
        if receipt['manifest_path'] != descriptor['manifest_path'] or sha(receipt['manifest_path']) != receipt['manifest_sha256']:
            raise SourceReceiptWaiting('수집 중단 원본 manifest SHA 확인 대기')
        expected = {str(validate_child(receipt['manifest_path'], w['path'])) for w in descriptor.get('workers', [])}
        actual = {str(validate_child(receipt['manifest_path'], w['path'])) for w in receipt.get('worker_checkpoints', [])}
        if any(not w.get('settled') for w in descriptor.get('workers', [])) or expected != actual:
            raise SourceReceiptWaiting('수집 중단 검색 작업자 목록·종료 결속 확인 대기')
        for worker in receipt.get('worker_checkpoints', []):
            validate_child(receipt['manifest_path'], worker['path'])
            if sha(worker['path']) != worker['sha256']:
                raise SourceReceiptWaiting('수집 중단 검색 체크포인트 SHA 확인 대기')
        return receipt
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SourceReceiptWaiting('저장된 수집 중단 영수증 확인 대기') from exc


def merge_receipt(record, receipt):
    """Execution ledgers only: no rounds, failure counters or source approval."""
    from .source_coverage import bind_search_rows
    searches=bind_search_rows(receipt.get('searches',[]),receipt.get('run_id'),receipt.get('search_context'))
    record['queries'] = merge_history(record.get('queries', []), searches)
    ledgers = candidate_ledgers(receipt.get('candidates', []))
    for field, incoming in [('urls', 'attempted_urls'), ('inspected_urls', 'inspected_urls')]:
        record[field] = list(dict.fromkeys([*record.get(field, []), *ledgers[incoming]]))
    saved = record.setdefault('interrupted_attempts', [])
    if not any(r.get('receipt_sha256') == receipt.get('receipt_sha256') for r in saved):
        saved.append(copy.deepcopy(receipt))


def resolve_settled_pre_submit(record):
    """Release only a host-accepted, byte-verified interruption before typing.

    The immutable receipt is created only after all registered children settle.
    A bare ``started`` row, elapsed time or parser change cannot authorize replay.
    Submitted/submit-intent and actual UI failures remain unresolved.
    Native search checkpoints a search_input request synchronously BEFORE typing;
    accepting only rows without that marker also excludes killed-after-Enter gaps.
    """
    for accepted in record.get('interrupted_attempts', []):
        try:
            path = Path(accepted['receipt_path']).resolve()
            manifest = Path(accepted['manifest_path']).resolve()
            if path != manifest.parent/'interrupted-execution-receipt.json':
                continue
            receipt, digest = read_bound_json(path)
            if digest != accepted['receipt_sha256']:
                continue
            if receipt != {k:v for k,v in accepted.items() if k not in {'receipt_path','receipt_sha256'}}:
                continue
            if sha(manifest) != receipt['manifest_sha256']:
                continue
            workers = receipt.get('worker_checkpoints') or []
            if not workers:
                continue
            from .source_coverage import bind_search_rows
            actual_rows = []
            for worker in workers:
                child = validate_child(manifest, worker['path'])
                data, actual_sha = read_bound_json(child)
                if actual_sha != worker['sha256']:
                    raise ValueError('changed child')
                actual_rows.extend(bind_search_rows(data.get('searches', []),
                    receipt.get('run_id'), receipt.get('search_context')))
            for row in record.get('queries', []):
                execution = row.get('execution') or {}
                if (row.get('status') != 'started' or row.get('language') == 'image'
                        or row.get('stage') not in {'locate_search_input','open_search_panel'}
                        or execution.get('query_submitted') is not False
                        or execution.get('query_url_matched') is not False
                        or execution.get('submit_intent') or execution.get('submitted_at')
                        or execution.get('input_value') or execution.get('actual_input_value')
                        or row.get('requests') or execution.get('resolution')):
                    continue
                if not any(all(observed.get(k) == v for k,v in row.items())
                           for observed in actual_rows):
                    continue
                before = copy.deepcopy(row)
                execution.update(resolution='confirmed_not_submitted',
                                 resolution_receipt_sha256=digest)
                record.setdefault('search_resolutions', []).append({
                    'basis':'settled_worker_interrupted_before_input',
                    'receipt_sha256':digest, 'previous':before})
        except (OSError, ValueError, KeyError, TypeError, SourceReceiptWaiting):
            # Keep uncertainty blocked; never repair a damaged receipt by guessing.
            continue
