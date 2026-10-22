"""Persistent identities for searches, independent of round and temporary folders."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from ..source_attempts import candidate_execution, search_execution, unresolved_search_scope, SEARCH_ACCESS_WAITS

SKIPPED = {'not_attempted', 'cooldown', 'verification_required', 'login_required',
           'no_supported_queries', 'query_exhausted', 'image_exhausted', 'budget_exhausted',
           'strategy_skipped', 'readiness_blocked', 'platform_disabled'}
ACCESS_WAITS = SEARCH_ACCESS_WAITS

# Conservative, inspectable equivalence classes. Unknown wording retains its
# literal identity; modifiers, language and corpus remain distinct.
ACTION_ALIASES = {
    'cold_storage': r'refrigerator storage|refrigerated storage|refrigeration|냉장\s*보관(?:법)?|冷藏保存(?:方法)?',
    'scoop': r'spooning demonstration|scooping|with a spoon|숟가락으로\s*뜨는\s*장면|한\s*스푼\s*떠서\s*사용하기|用勺子舀(?:取)?|舀取演示',
    'portion': r'portioning|소분\s*장면|소분|分装',
    'storage': r'storage preparation|storage tips|storage|보관\s*준비|보관\s*방법|보관법|보관|保存准备|保存方法|保存',
    'prepare': r'preparation process|hands on preparation|ingredient preparation|step by step cooking|detailed cooking tutorial|cooking tutorial|cooking technique|recipe|preparation|준비\s*과정|직접\s*준비하는\s*장면|단계별\s*조리\s*과정|자세한\s*조리\s*과정|요리\s*과정|조리\s*방법|재료\s*준비|레시피|준비|准备过程|分步烹饪|详细制作教程|制作教程|实际准备|烹饪方法|食材准备|做法|准备',
}


def query_fingerprint(query):
    """Known subject/action synonyms share an identity, without merging facts."""
    q = normalize_query(query)
    scopes = re.findall(r'(?:site:|inurl:)\S+', q)
    body = re.sub(r'(?:site:|inurl:)\S+', '', q).strip()
    lang = 'zh' if re.search(r'[\u3400-\u9fff]', body) else 'ko' if re.search(r'[가-힣]', body) else 'en'
    facets = []
    for key, pattern in (
        ('clean', r'raw footage|no captions|unedited footage|원본\s*영상|자막\s*없는|无字幕|实拍'),
        ('closeup', r'close[ -]?up(?: footage| demonstration| preparation| cooking)?|클로즈업(?:\s*영상)?|特写(?:视频)?'),
    ):
        if re.search(pattern, body):
            facets.append(key)
            body = re.sub(pattern, '', body)
    # Garlic preparation is a catalog subject, not an action in itself.
    subject = None
    for pattern in (r'minced garlic(?: preparation)?', r'다진\s*마늘(?:\s*준비)?', r'蒜(?:末|蓉)(?:准备)?'):
        if re.search(pattern, body):
            subject = 'minced_garlic'
            body = re.sub(pattern, '', body)
            break
    actions = []
    for key, pattern in ACTION_ALIASES.items():
        if re.search(pattern, body):
            actions.append(key)
            body = re.sub(pattern, '', body)
    remainder = normalize_query(re.sub(r'\b(?:how to|video|footage|tutorial|demonstration|a|the|with|of)\b|영상|장면|视频', '', body))
    if not actions and not facets:
        return q
    return '|'.join([lang, subject or '', remainder, ','.join(sorted(actions)),
                     ','.join(sorted(set(facets))), ','.join(sorted(scopes))])


def normalize_query(query):
    return ' '.join(unicodedata.normalize('NFKC', str(query)).casefold().split())


def attempted(row):
    return search_execution(row)['attempted']


def consumed_scope(row):
    """An access/service wait does not establish a failed content search."""
    return search_execution(row)['consumed']


def candidate_ledgers(candidates):
    """Inspection consumes a URL independently of whether network bytes were sent."""
    attempted_urls, inspected_urls, waits = [], [], []
    deferred = {'platform_disabled','platform_cooldown','platform_budget_exhausted',
                'not_probed','not_attempted','download_budget_deferred','valid_candidate_limit_reached'}
    for row in candidates:
        url = row.get('original_url') or row.get('url')
        execution = candidate_execution(row)
        if execution['waiting']:
            waits.append({'provider':row.get('platform','browser-worker'), 'url':url,
                'status':execution['access_status'], 'observed':execution['observed'],
                'basis':execution['basis']})
            continue
        if row.get('downloaded_file') or execution['attempted']:
            attempted_urls.append(url)
        if row.get('downloaded_file') or set(row.get('rejection_reasons') or []) - deferred - {'download_failed'}:
            inspected_urls.append(url)
    return {'attempted_urls':list(dict.fromkeys(u for u in attempted_urls if u)),
            'inspected_urls':list(dict.fromkeys(u for u in inspected_urls if u)), 'access_waits':waits}


def search_key(row):
    mode = 'image' if row.get('language') == 'image' else 'text'
    value = row.get('image_sha256') if mode == 'image' else None
    return (row.get('provider', ''), mode, value or normalize_query(row.get('query', '')), search_scope(row))


def search_scope(row):
    """Only observed pagination changes a search scope; IDs/time/prose do not.

    Missing pagination and the initial page are the same scope. Cursors remain
    case sensitive because they are provider tokens, rather than query prose.
    Callers must actually navigate the requested page/cursor, never synthesize
    one merely to make a previously completed search appear unused.
    """
    scope = row.get('search_scope') or {}
    if not isinstance(scope, dict):
        scope = {}
    values = {**scope, **{k: row[k] for k in ('page', 'page_number', 'cursor',
              'continuation_token', 'offset') if k in row}}
    page = values.get('page', values.get('page_number'))
    if page is not None:
        try:
            page = str(int(page))
        except (ValueError, TypeError):
            page = str(page).strip()
    cursor = values.get('cursor', values.get('continuation_token'))
    offset = values.get('offset')
    if offset is not None:
        try:
            offset = str(int(offset))
        except (ValueError, TypeError):
            offset = str(offset).strip()
    return (page if page not in (None, '', '1') else '',
            str(cursor) if cursor not in (None, '') else '',
            offset if offset not in (None, '', '0') else '')


def fresh_queries(queries, provider, history, *, scope=None):
    from .readiness import parser_revision
    requested_scope = search_scope({'search_scope': scope or {}})
    blocked = lambda r: consumed_scope(r) or unresolved_search_scope(r, parser_revision(provider))
    used = {search_key(r) for r in history if blocked(r)}
    semantic_used = {(query_fingerprint(r.get('query', '')), search_scope(r)) for r in history
                     if blocked(r) and r.get('provider') == provider and r.get('language') != 'image'}
    seen, result = set(), []
    for query in queries:
        key = (provider, 'text', normalize_query(query), requested_scope)
        semantic = (query_fingerprint(query), requested_scope)
        if key[2] and key not in used and semantic not in semantic_used and semantic not in seen:
            result.append(query); seen.add(semantic)
    return result


def minimum_search_queries(queries, provider, history, minimums, limit, *, search_only=False,search_identity=None):
    """Spend remaining language scope before repeating queries on another site."""
    from ..source_queries import language, platform_queries
    from ..source_coverage import actual_search_coverage
    from ..source_query_identity import query_identity,matches_identity
    fresh=fresh_queries(queries,provider,history)
    if search_identity is not None:fresh=[q for q in fresh if matches_identity(q,search_identity)]
    if not minimums:return platform_queries(fresh,provider,limit)
    coverage=actual_search_coverage(history,minimums,search_identity)
    completed={q['identity'] for row in coverage.values() for q in row['queries']}
    wanted={lang for lang,row in coverage.items() if not row['ready']}
    priority=[q for q in fresh if language(q) in wanted and query_identity(q,search_identity) not in completed]
    if search_only:
        unique=[];seen=set(completed)
        for query in priority:
            identity=query_identity(query,search_identity)
            if identity not in seen:unique.append(query);seen.add(identity)
        return platform_queries(unique,provider,limit,search_minimums=minimums)
    others=[q for q in fresh if q not in priority]
    return [*platform_queries(priority,provider,len(priority),search_minimums=minimums),
            *platform_queries(others,provider,len(others),search_minimums=minimums)][:max(0,limit)]


def search_quota_needed(history,minimums,query=None,*,search_identity=None):
    from ..source_coverage import actual_search_coverage
    from ..source_queries import language
    from ..source_query_identity import matches_identity
    coverage=actual_search_coverage(history,minimums,search_identity)
    if query is not None:
        if not matches_identity(query,search_identity):return False
        return not coverage.get(language(query),{'ready':True})['ready']
    return any(not row['ready'] for row in coverage.values())


def image_sha256(frame):
    return hashlib.sha256(Path(frame).read_bytes()).hexdigest()


def image_signature(frame):
    """Small luminance thumbnail: tolerant of JPEG recompression, conservative.

    Thumbnail distance plus dHash prevents flat but different-colour frames
    sharing a perceptual identity. Invalid legacy test/files use exact hashes.
    """
    try:
        from PIL import Image, ImageOps
        with Image.open(frame) as im:
            im = ImageOps.exif_transpose(im).convert('RGB')
            rgb = im.resize((8, 8)).tobytes()
            gray = im.convert('L').resize((9, 8)).tobytes()
        dh = sum(int(gray[y*9+x] > gray[y*9+x+1]) << (y*8+x) for y in range(8) for x in range(8))
        return {'dhash':f'{dh:016x}', 'rgb':rgb.hex()}
    except (OSError, ValueError):
        return None


def similar_signature(a, b):
    if not a or not b:
        return False
    try:
        left, right = bytes.fromhex(a['rgb']), bytes.fromhex(b['rgb'])
        return (len(left) == len(right) == 192
                and (int(a['dhash'],16) ^ int(b['dhash'],16)).bit_count() <= 6
                and sum(abs(x-y) for x,y in zip(left,right))/192 <= 10)
    except (KeyError, ValueError, TypeError):
        return False


def fresh_frames(frames, provider, history):
    from .readiness import parser_revision
    blocked = lambda r: consumed_scope(r) or unresolved_search_scope(r, parser_revision(provider))
    used = {search_key(r) for r in history if blocked(r)}
    signatures = [r.get('image_signature') for r in history if blocked(r) and r.get('provider') == provider]
    seen, result = set(), []
    for frame in frames:
        key = (provider, 'image', image_sha256(frame), search_scope({}))
        # Old manifests have stable frame names but no content hash.
        legacy = (provider, 'image', normalize_query(frame.name), search_scope({}))
        signature = image_signature(frame)
        if key not in used and legacy not in used and key not in seen and not any(similar_signature(signature, old) for old in signatures):
            result.append(frame); seen.add(key); signatures.append(signature)
    return result


def merge_history(*histories):
    """Preserve observed access attempts separately from consumed content scopes.

    An actual CAPTCHA/429 request is acquisition evidence even though it cannot
    establish a failed content search. Later waits must not overwrite the last
    confirmed content result; scope comparison uses consumed_scope, not mere
    ledger membership. Unattempted saved gates remain in immutable manifests.
    """
    import copy
    import json
    records = {}
    for history in histories:
        for row in history:
            content = consumed_scope(row)
            pending = search_execution(row)['pending']
            actual_wait = row.get('status') in ACCESS_WAITS and bool(row.get('requests'))
            if content or actual_wait or pending:
                context=(row.get('run_id'),json.dumps(row.get('search_context'),sort_keys=True,ensure_ascii=False))
                key = (('content', search_key(row)) if content else
                    ('pending' if pending else 'access', search_key(row), row.get('status'),
                        json.dumps(row.get('requests',[]), sort_keys=True, ensure_ascii=False)))
                key=(context,key)
                records[key] = {k: copy.deepcopy(row[k]) for k in ('provider', 'query', 'language', 'status',
                    'image_sha256', 'image_signature', 'requests', 'candidates', 'error', 'strategy', 'parser_revision',
                    'http_status', 'reason', 'search_scope', 'page', 'page_number', 'cursor',
                    'continuation_token', 'offset', 'stage', 'execution', 'result_method',
                    'error_detail', 'visible_search_controls','run_id','search_context','search_identity','captcha_review','search_purpose') if k in row}
    return list(records.values())


def restore_history(record):
    from ..source_pause_receipts import resolve_settled_pre_submit
    resolve_settled_pre_submit(record)
    if record.get('inspection_ledger_version') != 1:
        # Older acquisition receipts omitted inspected-but-undownloaded URLs.
        # Restore that evidence before another shortlist execution, preserving
        # the original network history and every immutable manifest.
        import json
        inspected = list(record.get('inspected_urls', []))
        for entry in record.get('rounds', []):
            try:
                saved = json.loads(Path(entry['manifest_path']).read_text(encoding='utf-8'))
                inspected.extend(candidate_ledgers(saved.get('candidates', []))['inspected_urls'])
            except (OSError, ValueError, KeyError):
                continue
        record['inspected_urls'] = list(dict.fromkeys(inspected))
        record['inspection_ledger_version'] = 1
    if (record.get('strategy_version') == 2 and record.get('search_context_ledger_version')==1
            and record.get('search_identity_ledger_version')==1):
        return record.get('queries', [])
    histories = [record.get('queries', [])]
    for entry in record.get('rounds', []):
        try:
            import json
            data = json.loads(Path(entry['manifest_path']).read_text(encoding='utf-8'))
            rows = data.get('search_audit', [])
            binding=entry.get('search_context') or data.get('search_context')
            run_id=entry.get('run_id') or data.get('run_id')
            conflict=any(k in entry and k in data and entry[k]!=data[k] for k in ('run_id','search_context'))
            if not conflict and run_id and isinstance(binding,dict) and {'product','reference_sha256','reference_text_sha256'}<=set(binding):
                from ..source_coverage import bind_search_rows
                rows=bind_search_rows(rows,run_id,binding)
            for row in rows:
                # Only an explicit receipt binding can restore missing tags;
                # never assign old manifests to the current run by inference.
                if row.get('language') == 'image' and not row.get('image_signature') and row.get('query'):
                    row['image_signature'] = image_signature(Path(entry['manifest_path']).parent/'reference_frames'/Path(row['query']).name)
            histories.append(rows)
        except (OSError, ValueError, KeyError):
            continue
    record['queries'] = merge_history(*histories)
    record['strategy_version'] = 2
    record['search_context_ledger_version']=1
    record['search_identity_ledger_version']=1
    resolve_settled_pre_submit(record)
    return record['queries']


def stop_diagnostics(searches, goal, outcomes=None):
    blocked = sorted({r.get('provider', '') for r in searches if r.get('status') in
                      {'captcha', 'verification_required', 'login_required', 'rate_limited', 'cooldown'}})
    parts = []
    if blocked:
        parts.append('인증·로그인·요청 제한: ' + ', '.join(blocked))
    pending_reviews=sorted({r.get('provider','') for r in searches if r.get('status')=='captcha_review_pending'})
    if pending_reviews:
        parts.append('인증 의심 화면 캡처·재검토 대기(CAPTCHA 미확정): '+', '.join(pending_reviews))
    unresolved = sorted({r.get('provider','') for r in searches if search_execution(r)['pending'] or r.get('status') in {'page_unresolved','readiness_blocked'}
                         or (r.get('status') == 'strategy_skipped' and '판독' in r.get('reason',''))})
    if unresolved:
        parts.append('검색 화면 판독 실패로 경로 중지: ' + ', '.join(unresolved))
    if any(r.get('status') == 'query_exhausted' for r in searches):
        parts.append('해당 검색 경로의 미사용 텍스트 검색어 소진')
    if any(r.get('status') == 'image_exhausted' for r in searches):
        parts.append('미사용 장면 이미지 소진')
    if any(r.get('status') == 'no_supported_queries' for r in searches):
        parts.append('지원 언어 검색어 없음')
    if any(r.get('status') == 'strategy_skipped' for r in searches):
        parts.append('이전 실패 원인에 따라 성과 없는 검색 경로 제외')
    if not goal.get('core_ready'):
        parts.append('핵심 동작을 보여주는 검증 영상 부족')
    if goal.get('source_diversity_ready') is False:
        parts.append(f"관련 승인 원본 {goal.get('related_parent_count',0)}/{goal.get('required_parent_sources',5)}개 · 부족분을 무관·중복 영상으로 대체하지 않음")
    for lang,row in goal.get('search_coverage',{}).items():
        if not row.get('ready'):
            parts.append(f"{'영어' if lang=='en' else '중국어'} 고유 실제 검색 {row['count']}/{row['minimum']}개 · 미시도·접근 대기는 수행으로 세지 않음")
    labels = {'no_candidates':'검색 결과 없음', 'quality_rejected':'주제·화질·편집 적합성 검증 탈락',
              'metadata_rejected':'검색 결과의 영상 길이가 사용 기준과 불일치',
              'duplicate':'기존 영상과 중복', 'download_failed':'영상 다운로드 실패',
              'search_failed':'검색 요청 실패', 'access_denied':'접근 거부', 'budget_exhausted':'회차 실행 예산 소진'}
    reasons = {reason for outcome in (outcomes or {}).values() for reason, count in outcome.get('reasons', {}).items() if count}
    parts.extend(label for reason, label in labels.items() if reason in reasons)
    return parts
