"""Opt-in existing Ego TaskSpace transport; never grants media/quality approval."""
from __future__ import annotations
import contextvars
import functools
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager

_OWNER = contextvars.ContextVar('ego_source_owner', default=None)
SUPPORTED = frozenset({'tiktok'})


def configured(settings):
    return bool(str(getattr(settings, 'source_ego_binding', '')).strip())


def waiting(reason, rows=None):
    from .source_access_preflight import SourceAccessWaiting
    raise SourceAccessWaiting('ego-lite 소스 대기 · ' + reason, time.time() + 30, rows)


def binding(settings, task_id):
    try:
        path = Path(settings.source_ego_binding).resolve(strict=True)
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        if (type(value['spaceId']) is not int or value['spaceId'] <= 0
                or not isinstance(value['authorizedTaskIds'], list)
                or task_id not in value['authorizedTaskIds']
                or not isinstance(value['pages'], dict)
                or any(not isinstance(p, str) or not __import__('re').fullmatch(r'p\d+', p)
                       for p in value['pages'].values())):
            waiting('현재 작업에 결속된 기존 TaskSpace가 없습니다')
        return path, value
    except (OSError, ValueError, KeyError, TypeError) as exc:
        waiting('브라우저 binding 확인 불가: ' + type(exc).__name__)


def owner_bound(function):
    """The native owner supplies task/job/run; no scope inferred from filenames."""
    @functools.wraps(function)
    def wrapped(settings, *args, **kwargs):
        if not configured(settings):
            return function(settings, *args, **kwargs)
        if not settings.source_browser_search:
            waiting('ego backend에서 별도 indexed HTTP 검색은 허용하지 않습니다')
        context = kwargs.get('search_context') or {}
        if not all(context.get(k) for k in ('task_id', 'job_id', 'run_id')):
            waiting('영속 담당자의 task/job/run 결속 필요')
        binding(settings, context['task_id'])
        token = _OWNER.set((settings, dict(context)))
        try:
            return function(settings, *args, **kwargs)
        finally:
            _OWNER.reset(token)
    return wrapped


def _cancel():
    from .studio_pause import active_cancel
    callback = active_cancel()
    if callback:
        callback()


@contextmanager
def _lease(path):
    """One transport across preflight, search, details and all owner threads."""
    handle = path.open('a+b')
    try:
        handle.seek(0); handle.write(b'0'); handle.flush(); handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            waiting('같은 TaskSpace의 다른 요청 종료 대기')
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()


def _write(path, value):
    from .editing_adapter import _atomic_json
    _atomic_json(path, value)


def _invoke(settings, task_id, operation, *, provider=None, **arguments):
    """Real CLI only; tests replace this external boundary, never browser objects."""
    path, config = binding(settings, task_id)
    if provider and provider not in SUPPORTED:
        return {'status':'not_attempted', 'reason':'ego_provider_not_implemented'}
    work = settings.data_dir / 'ego_transport' / ('space'+str(config['spaceId']))
    work.mkdir(parents=True, exist_ok=True)
    with _lease(work / 'transport.lock'):
        state_path = work / 'clock.json'
        try:
            clock = json.loads(state_path.read_text('utf-8'))
        except FileNotFoundError:
            clock = {}
        config_sha=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
        if clock.get('halted'):
            if clock['halted'].get('binding_sha256')==config_sha:
                waiting('사용자 제어/TaskSpace 중단 유지 · 명시 복구 binding 필요')
            clock.pop('halted',None)  # Only an explicit changed binding can renew control.
        if clock.get('pending'):
            waiting('앞선 CLI 요청의 실제 종료/늦은 효과 확인 필요')
        if operation in {'search', 'download'}:
            interval = max(30 if provider == 'tiktok' else 10,
                           float(getattr(settings, 'source_browser_search_interval', 10)))
            until = clock.get(provider, 0) + interval
            while time.time() < until:
                _cancel(); time.sleep(min(.25, until-time.time()))
            _cancel()
            # Re-read authorization after pacing; revocation never borrows an old proof.
            if binding(settings, task_id)[1] != config:
                waiting('대기 중 TaskSpace binding 변경')
            clock[provider] = time.time()
        _cancel()
        call_dir = work / uuid.uuid4().hex
        call_dir.mkdir()
        request = {'operation':operation, 'provider':provider, 'task_id':task_id,
                   'binding_path':str(path), 'binding':config,
                   'result_path':str(call_dir/'result.json'), 'evidence_dir':str(call_dir),
                   **arguments}
        owner=_OWNER.get()
        request['owner_context']=owner[1] if owner else {'task_id':task_id}
        bridge=Path(__file__).with_suffix('.mjs').resolve()
        request['bridge_sha256']=hashlib.sha256(bridge.read_bytes()).hexdigest()
        _write(call_dir/'request.json', request)
        module_uri = Path(__file__).with_suffix('.mjs').resolve().as_uri()
        entry = 'const m=await import('+json.dumps(module_uri)+');await m.run('+json.dumps(str(call_dir/'request.json'))+');\n'
        script = call_dir/'entry.mjs'; script.write_text(entry, encoding='utf-8')
        executable = shutil.which('ego-browser')
        if not executable:
            waiting('ego-browser CLI 실행 파일 없음')
        # Keep unresolved submissions blocked across worker/process replacement.
        clock['pending'] = str(call_dir)
        _write(state_path, clock)
        command = [executable, 'nodejs', '-e', 'await import('+json.dumps(script.as_uri())+')']
        try:
            with (call_dir/'cli-stdout.log').open('wb') as stdout, (call_dir/'cli-stderr.log').open('wb') as stderr:
                process=subprocess.Popen(command,stdout=stdout,stderr=stderr,
                    creationflags=(0x08000000 if os.name=='nt' else 0))
                try:
                    deadline=time.monotonic()+100
                    while process.poll() is None:
                        _cancel()
                        if time.monotonic()>deadline:raise subprocess.TimeoutExpired(command,100)
                        time.sleep(.2)
                    _cancel()
                finally:
                    if process.poll() is None:
                        # This is the owned CLI, never browser or TaskSpace processes.
                        process.terminate()
                        try:process.wait(timeout=5)
                        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                if process.returncode:
                    waiting('CLI 비정상 종료 · 실행/늦은 효과 확인 필요 · '+str(call_dir))
        except (OSError, subprocess.TimeoutExpired):
            waiting('CLI transport 종료 확인 대기 · '+str(call_dir))
        if not (call_dir/'result.json').is_file():
            waiting('CLI 결과 영수증 없음 · '+str(call_dir))
        try:
            row = json.loads((call_dir/'result.json').read_text('utf-8'))
        except (OSError, ValueError):
            waiting('CLI 영수증 파싱 대기 · '+str(call_dir))
        if row.get('task_id') != task_id or row.get('spaceId') != config['spaceId']:
            waiting('CLI 결과의 작업/TaskSpace 불일치')
        if row.get('bridge_sha256')!=request['bridge_sha256']:
            waiting('CLI bridge SHA 불일치')
        if row.get('owner_context')!=request['owner_context']:
            waiting('CLI 영수증의 영속 작업/run 결속 불일치')
        if row.get('status')=='started' or row.get('mayHaveLateEffects') is True:
            waiting('CLI 중간 결과 또는 늦은 효과 확인 필요 · '+str(call_dir))
        if row.get('status') in {'user_control','space_unavailable'}:
            clock['halted']={'binding_sha256':config_sha,'evidence_path':str(call_dir/'result.json'),
                             'status':row['status']}
        clock.pop('pending', None); _write(state_path, clock)
        row['ego_receipt_path'] = str(call_dir/'result.json')
        row['ego_receipt_sha256'] = hashlib.sha256((call_dir/'result.json').read_bytes()).hexdigest()
        return row


def _saved_gate(settings, provider):
    from .source_collection_access import disabled_platforms
    from .search_access import access_record, manual_required
    disabled = disabled_platforms(settings)
    if provider in disabled:
        return {'status':'platform_disabled', 'reason':disabled[provider]}
    saved = access_record(settings.data_dir, provider)
    if manual_required(saved):
        return {'status':'verification_required', 'reason':saved.get('reason','saved_manual_gate')}
    if saved.get('until', 0) > time.time():
        return {'status':'cooldown', 'reason':saved.get('reason','saved_cooldown'), 'retry_at':saved['until']}
    from .source_search.readiness import readiness_record
    readiness=readiness_record(settings.data_dir,provider)
    if readiness.get('reason')=='page_unresolved' and not readiness.get('recheck_requested'):
        return {'status':'readiness_blocked','reason':'saved_parser_failure_requires_explicit_recheck','readiness':readiness}
    return None


def _retain_access(settings, provider, row):
    if row.get('status') not in {'captcha_review_pending','login_required','rate_limited','access_denied'}:
        return
    manual = row['status'] in {'captcha_review_pending','login_required','access_denied'}
    from .search_access import access_record
    previous=access_record(settings.data_dir,provider)
    if (row['status']=='rate_limited' and previous.get('reason')=='rate_limited'
            and (previous.get('ego_evidence') or {}).get('rate_event')==row.get('rate_event')):
        return  # Re-observing the same document/request never renews Retry-After.
    _write(settings.data_dir/'search_cooldowns'/f'{provider}.json',
           {'reason':row['status'], 'requires_verification':manual,
            'until':0 if manual else time.time()+max(30, row.get('retry_after',600)),
            'ego_evidence':row, 'observed_at':time.time()})


def current_routes(settings, providers, task_id):
    binding(settings, task_id)
    actual = _invoke(settings, task_id, 'observe', providers=list(providers))
    if actual.get('status') not in {None,'observed'}:
        waiting(actual.get('reason',actual.get('status','ego_observation_unavailable')),[actual])
    rows=[]
    for provider in providers:
        row={'provider':provider,'query':'','attempted':False,'observed_at':time.time()}
        if provider not in SUPPORTED:
            row.update(status='not_attempted',reason='ego_provider_not_implemented')
        else:
            value=(actual.get('routes') or {}).get(provider, {'status':'browser_busy','reason':'ego_observation_missing'})
            _retain_access(settings,provider,value)
            row.update(_saved_gate(settings,provider) or value)
        rows.append(row)
    return rows


def search(settings, queries, limit, debug_dir, previous_searches=None, progress=None,
           routes=None, provider_queries=None, search_minimums=None,search_only=False,search_identity=None):
    from .studio_pause import active_receipt_hook
    path=Path(debug_dir)/('search-checkpoint-'+uuid.uuid4().hex+'.json')
    initial={'candidates':[],'terms':[],'notes':[],'searches':[],'message':'ego_worker_registered'}
    _write(path,initial)
    registered=getattr(progress,'source_worker_checkpoint',None) or active_receipt_hook('source_worker_checkpoint')
    settled=getattr(progress,'source_worker_settled',None) or active_receipt_hook('source_worker_settled')
    if registered:registered(path)
    try:
        return _search(settings,queries,limit,path,previous_searches,progress,routes,
                       provider_queries,search_minimums,search_only,search_identity)
    finally:
        if settled:settled(path)


def _search(settings, queries, limit, checkpoint_path, previous_searches=None, progress=None,
           routes=None, provider_queries=None, search_minimums=None,search_only=False,search_identity=None):
    context=_OWNER.get()
    if not context or context[0] is not settings:
        waiting('검색 요청의 영속 담당자 결속 없음')
    task_id=context[1]['task_id']; binding(settings,task_id)
    from .source_queries import platform_queries, language, register_tiktok_noun_head
    from .source_search.strategy import minimum_search_queries
    from .source_query_identity import matches_identity
    output={'candidates':[],'terms':[],'notes':[],'searches':[]}
    history=list(previous_searches or [])
    for provider in (routes if routes is not None else ['tiktok','bilibili','youtube']):
        if provider not in SUPPORTED:
            output['searches'].append({'provider':provider,'query':'','status':'not_attempted','candidates':0,'reason':'ego_provider_not_implemented'})
            continue
        pool=list((provider_queries or {}).get(provider,queries))
        for query in pool: register_tiktok_noun_head(query)
        pool=platform_queries(pool,provider,len(pool),search_minimums=search_minimums or {})
        amount=max(getattr(settings,'source_queries_per_platform',3),sum((search_minimums or {}).values()))
        selected=minimum_search_queries(pool,provider,history,search_minimums or {},amount,
                                       search_only=search_only,search_identity=search_identity)
        for query in selected:
            if len(query.split())>10 or not query.strip() or (search_identity is not None and not matches_identity(query,search_identity)):
                waiting('native 검색어 계약 불일치 · 미전송')
            if gate:=_saved_gate(settings,provider):
                waiting('플랫폼 접근 확인 대기', [{'provider':provider, 'query':query,**gate}])
            if progress: progress(f'{provider} · ego-lite 실제 검색: {query}')
            _cancel()
            started={'provider':provider,'query':query,'language':language(query),
                     'status':'started','stage':'prepare_search_input','candidates':0,
                     'execution':{'query_submitted':False}}
            _write(checkpoint_path,{**output,'searches':[*output['searches'],started]})
            row=_invoke(settings,task_id,'search',provider=provider,query=query,
                        limit=max(1,min(limit,len(selected)*3)))
            _retain_access(settings,provider,row)
            audit={**row,'provider':provider,'query':query,'language':language(query),
                   'parser_revision':'ego-visible-search-v1','candidates':len(row.get('candidates') or [])}
            output['searches'].append(audit); history.append(audit)
            # Preserve exact execution evidence before a pause; never mark pending as no_results.
            _write(checkpoint_path,output)
            if row.get('status') not in {'results','no_results'}:
                if row.get('status')=='browser_busy' and row.get('execution',{}).get('query_submitted'):
                    _write(settings.data_dir/'search_readiness'/f'{provider}.json',
                        {'reason':'page_unresolved','parser_revision':'ego-visible-search-v1',
                         'at':time.time(),'query':query,'recheck_requested':False,
                         'ego_receipt_path':row.get('ego_receipt_path')})
                waiting(row.get('reason',row.get('status','ego_search_unresolved')),output['searches'])
            for item in row.get('candidates') or []:
                output['candidates'].append({'url':item['url'],'provider':'ego-'+provider,
                    'title':item.get('title','')[:400], 'query':query,'match_kind':'platform-search',
                    'rights':'unknown-check-before-reuse'})
            _write(checkpoint_path,output)
            if len(output['candidates'])>=limit and not search_only:
                break
    unique={item['url']:item for item in output['candidates']}
    output['candidates']=list(unique.values())[:limit]
    return output


def download(candidate, target, max_bytes):
    owner=_OWNER.get()
    if not owner:
        waiting('영상 수신의 영속 담당자 결속 없음')
    settings,context=owner; binding(settings,context['task_id'])
    if candidate.platform not in SUPPORTED:
        candidate.download_attempted=False
        candidate.rejection_reasons=['not_attempted']
        candidate.error='ego_provider_download_not_implemented'
        return None
    if gate:=_saved_gate(settings,candidate.platform):
        waiting('영상 수신 접근 대기', [{'provider':candidate.platform,**gate}])
    from .source_urls import video_url
    if not video_url(candidate.url):
        waiting('영상 상세 URL 검증 실패')
    target=Path(target).resolve()
    if not target.is_relative_to(settings.source_dir.resolve()):
        waiting('현재 수집 폴더 밖 수신 금지')
    if target.exists():
        waiting('기존 수신 파일 보존 · native 재사용 또는 새 후보 확인 필요')
    incoming=target.with_name(target.stem+'.'+uuid.uuid4().hex+'.receiving.mp4')
    candidate.download_attempted=False
    row=_invoke(settings,context['task_id'],'download',provider=candidate.platform,
                url=candidate.url,target=str(incoming),max_bytes=max_bytes)
    _retain_access(settings,candidate.platform,row)
    candidate.download_diagnostics={'attempted':bool(row.get('attempted')),
        'navigation_started':bool(row.get('navigation_started')),
        'navigation_attempted':bool(row.get('navigation_attempted',row.get('navigation_started'))),
        'access_status':row.get('status'),
        'method':'ego-existing-page-playback','saved_bytes':row.get('bytes',0)}
    candidate.download_attempted=bool(row.get('attempted'))
    if row.get('status') == 'candidate_unavailable':
        # A completed, exact-page validation is local to this candidate.
        # Control/transport/access errors never enter this branch.
        from .source_urls import canonical_video_key
        expected_id=candidate.url.rstrip('/').split('/')[-1].split('?')[0]
        if (row.get('attempted') is not False or row.get('navigation_attempted') is not True
                or row.get('expected_id')!=expected_id or row.get('observed_id')!=expected_id
                or canonical_video_key(row.get('source_url',''))!=canonical_video_key(candidate.url)
                or row.get('reason') not in {'exact_video_metadata_missing','no_exact_playable_video',
                    'no_observed_successful_exact_playback_resource'}):
            waiting('후보 단위 실패의 실제 URL/진단 결속 확인 대기',[row])
        candidate.error='ego_candidate_unavailable: '+row['reason']
        candidate.rejection_reasons=['candidate_unavailable']
        candidate.download_diagnostics.update(reason=row['reason'],
            ego_receipt_path=row.get('ego_receipt_path'),ego_receipt_sha256=row.get('ego_receipt_sha256'))
        return None
    if row.get('status') != 'received':
        waiting(row.get('reason',row.get('status','ego_download_pending')),[row])
    from .source_urls import canonical_video_key
    meta=row.get('meta') or {}
    expected_id=candidate.url.rstrip('/').split('/')[-1].split('?')[0]
    if (str(meta.get('id',''))!=expected_id
            or canonical_video_key(meta.get('source_url',''))!=canonical_video_key(candidate.url)):
        waiting('후보 URL과 실제 재생 영상 정체성 불일치')
    if (not incoming.is_file() or incoming.stat().st_size<12
            or incoming.stat().st_size>max_bytes or incoming.read_bytes()[:8][4:]!=b'ftyp'):
        candidate.error='ego_received_file_invalid';candidate.rejection_reasons=['invalid_media'];return None
    digest=hashlib.sha256(incoming.read_bytes()).hexdigest()
    if row.get('sha256')!=digest or row.get('bytes')!=incoming.stat().st_size:
        waiting('실제 수신 파일 SHA/크기 불일치')
    incoming.replace(target)
    candidate.acquisition='existing-browser-playback'
    return target  # Native probe, decode, duplicate, product/overlay/portrait review follow unchanged.
