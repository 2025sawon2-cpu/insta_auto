"""Persistent source acquisition independent of script and voice production."""
from __future__ import annotations

import copy
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from .source_quality import editing_ready, sha256_file, frame_duplicate
from .source_urls import canonical_video_key
from .source_policy import run_policy, source_platform, goal_message, adopt_policy
from .source_coverage import coverage_goal, reviewed_core, footage_coordinates, current_search_rows, search_scope_for_state
from .source_diversity import acquisition_policy
from .studio_store import change_claimed

PLATFORMS = {'tiktok':'틱톡','douyin':'더우인','xiaohongshu':'샤오홍슈',
             'instagram':'인스타그램','youtube':'유튜브','youtu.be':'유튜브','bilibili':'빌리빌리','pexels':'Pexels','lazada':'Lazada'}


def platform_name(source):
    host = urlparse(source.get('origin_url', '')).hostname or ''
    return next((name for key, name in PLATFORMS.items() if key in host), host or '기타')


def unique_sources(sources, *, core_priority=False):
    result, hashes, urls = [], set(), set()
    for source in sources:
        sha = source.get('sha256')
        url = canonical_video_key(source.get('origin_url', ''))
        related_parent = False
        if sha and sha in hashes:
            continue
        if url and url in urls:
            # Different reviewed trims of one download remain usable. Their
            # overlaps are unioned in coverage_goal instead of dropping later
            # windows just because the platform URL is identical.
            coordinates = footage_coordinates(source)
            previous = [s for s in result if canonical_video_key(s.get('origin_url', '')) == url]
            parent_hashes = []
            for prior in previous:
                prior_coordinates = footage_coordinates(prior)
                parent_hashes.append(prior_coordinates[0][1] if prior_coordinates else prior.get('sha256'))
            # A full parent arriving after its trim is just as valid as the
            # opposite order. Coverage unions their actual parent intervals.
            parent=coordinates[0][1] if coordinates else sha
            related_parent=bool(parent and all(p==parent for p in parent_hashes) and
                (coordinates or any(footage_coordinates(p) for p in previous)))
            if not related_parent:
                continue
        frames = [int(v, 16) for v in source.get('frame_hashes') or []]
        from .source_core_priority import recording_duplicate
        if frames and not related_parent and any(recording_duplicate(source,prior) if core_priority else
                frame_duplicate(frames, [int(v, 16) for v in prior.get('frame_hashes') or []]) for prior in result):
            continue
        hashes.add(sha); urls.add(url); result.append(source)
    return result


def source_goal(state, target=10):
    run = next((r for r in state.get('runs', []) if r['id'] == state.get('run_id')), {})
    if run.get('inputs', {}).get('photo_story'):
        photos = run.get('artifacts', {}).get('photo_assets', [])
        ready = bool(photos) and all(p.get('kind') == 'still_image'
            and Path(p.get('path') or '').is_file() and p.get('sha256') == sha256_file(Path(p['path'])) for p in photos)
        return {'target':1, 'count':len(photos), 'platforms':{'원본 사진':len(photos)},
                'policy_version':'photo-story-v1', 'platform_targets':{}, 'core_ready':False,
                'ready':ready, 'source_ids':[], 'asset_kind':'still_image', 'photo_count':len(photos)}
    if state.get('creation_mode') == 'self_shot':
        run = next((r for r in state.get('runs', []) if r['id'] == state.get('run_id')), {})
        ids = run.get('inputs', {}).get('source_ids')
        sources = [s for s in state.get('sources', []) if s.get('rights') == 'user_supplied'
                   and Path(s.get('path') or '').is_file() and (ids is None or s['id'] in ids)]
        return {'target':1, 'maximum':20, 'count':len(sources), 'platforms':{'내 촬영':len(sources)},
                'policy_version':'self-shot-v1', 'platform_targets':{}, 'core_ready':bool(sources),
                'ready':bool(sources) and (ids is None or len(sources) == len(set(ids))),
                'source_ids':[s['id'] for s in sources]}
    policy = run_policy(state, target)
    target = policy['minimum_total']
    from .source_functional import needs_identity_reanalysis
    from .source_core_priority import enabled as core_enabled
    sources = unique_sources([s for s in state.get('sources', [])
                              if Path(s.get('path') or '').is_file() and editing_ready(s)
                              and not needs_identity_reanalysis(state,s)],core_priority=core_enabled(policy))
    platforms = {}
    for source in sources:
        name = platform_name(source)
        platforms[name] = platforms.get(name, 0)+1
    core_ready = any(reviewed_core(s) for s in sources)
    platform_targets = {p: {'target': minimum, 'usable': sum(source_platform(s) == p for s in sources)}
                        for p, minimum in policy.get('platform_minimums', {}).items()}
    for coverage in platform_targets.values():
        coverage['status'] = 'met' if coverage['usable'] >= coverage['target'] else 'shortfall'
    result = {'target':target, 'count':len(sources), 'platforms':platforms,
            'policy_version':policy['version'], 'platform_targets':platform_targets,
            'core_ready':core_ready, 'ready':len(sources)>=target and core_ready
                and all(c['status'] == 'met' for c in platform_targets.values()),
            'source_ids':[s['id'] for s in sources]}
    if policy.get('completion_mode') == 'scene_duration':
        coverage = coverage_goal(sources, state, policy)
        result.update(coverage)
        result['ready'] = bool(sources) and coverage.get('ready', coverage['duration_ready'] and coverage['core_ready'])
        original_key=lambda s: (footage_coordinates(s) or (('footage',s.get('sha256') or s['id']),0,1))[0]
        result['original_count']=len({original_key(s) for s in sources})
        result['platform_preferences'] = {p: {'target': preferred,
            'usable': len({original_key(s) for s in sources if source_platform(s)==p}), 'required': False}
            for p, preferred in policy.get('platform_preferences', {}).items()}
        if coverage.get('related_source_ids') is not None:
            result['source_ids']=coverage['related_source_ids']
    gap=state.get('source_diversity_gap') or {}
    if gap:
        result.update(ready=False,selection_recovery_required=True)
    return result


def resolve_diversity_recovery(state):
    gap=state.get('source_diversity_gap') or {}
    if not gap:return False
    from .source_diversity import inventory_material,new_inventory_material
    if not new_inventory_material(gap.get('baseline_material'),inventory_material(state)):return False
    candidate={k:v for k,v in state.items() if k!='source_diversity_gap'}
    goal=source_goal(candidate)
    if not goal['ready']:return False
    state.pop('source_diversity_gap',None)
    gap['resolved_at']=time.time()
    gap['resolution']='changed_reviewed_footage_retry_layout'
    state['source_diversity_generation']=state.get('source_diversity_generation',0)+1
    for history in state.get('source_diversity_history',[]):
        if history.get('job_id')==gap.get('job_id') and history.get('inventory_signature')==gap.get('inventory_signature'):
            history.update(resolved_at=gap['resolved_at'],resolution=gap['resolution'])
    run=next((r for r in state.get('runs',[]) if r['id']==state.get('run_id')),None)
    if run is not None:run.setdefault('inputs',{})['source_ids']=goal['source_ids']
    quality=state.get('daily_quality',{})
    if quality.get('pending')=='source_diversity_collect':quality.pop('pending',None)
    return True


def sync_ready_source_status(state, db, target=10):
    """Reconcile recovered inventory without masking a live acquisition job."""
    goal = source_goal(state, target)
    state['source_goal'] = goal
    if goal['ready'] and not db.execute(
            "SELECT 1 FROM jobs WHERE task_id=? AND kind IN ('collect_sources','refresh_sources') "
            "AND status IN ('queued','running')", (state['id'],)).fetchone():
        state['source_search'] = {'status':'done', 'message':'소스 준비 완료 · '+goal_message(goal), 'progress':100}
    return goal


class SourceAcquisitionMixin:
    def release_source_hold(self, state):
        record = state.setdefault('source_acquisition', {})
        if record.get('hold'):
            record.setdefault('hold_history', []).append(record.pop('hold'))
        # Resuming does not erase completed unsuccessful attempts or their cap.
        # A genuinely improved reviewed result resets no-progress in accept_source_round.
        record.setdefault('bounded_rounds',0)
        record.setdefault('no_progress_rounds',0)
        record.setdefault('started_at',time.time())
        record.setdefault('execution_seconds',0)
        record['resumed_at']=time.time()

    def _stop_source_collection(self, state, db, reason, details):
        record = state.setdefault('source_acquisition', {})
        hold = {'reason':reason, 'details':details, 'at':time.time(),
                'rounds':record.get('bounded_rounds', 0),
                'no_progress_rounds':record.get('no_progress_rounds', 0)}
        record['hold'] = hold
        labels = {'no_progress':'연속 수집에서 제작 가능한 소스 증가 없음',
                  'strategy_exhausted':'새로 실행할 검색 조건 없음',
                  'round_limit':'수집 회차 한도 도달', 'time_limit':'수집 총시간 한도 도달'}
        message = '소스 자동 수집 중지 · ' + labels[reason]
        if details: message += ' · ' + ' / '.join(details)
        state['source_search'] = {'status':'blocked', 'message':message, 'progress':0, 'hold':hold}
        db.execute("UPDATE jobs SET status='paused' WHERE task_id=? AND kind='collect_sources' AND status='queued'", (state['id'],))
        self.store.event(db, state['id'], 'source_collection_stopped', hold)

    def ensure_source_collection(self, state, db, *, finishing=None):
        if state.get('creation_mode') == 'self_shot':
            return
        auto = state.get('automation', {})
        if auto.get('protocol') != 2 or auto.get('paused_by_user') or auto.get('consumed_by_daily_policy'):
            return
        selected_run=next((r for r in state.get('runs',[]) if r['id']==state.get('run_id')),None)
        completed=(state.get('status')=='completed' and (selected_run is None or selected_run.get('status')=='completed'))
        if not auto.get('active') or completed or not state.get('original_text'):
            return
        # Adopt the new contract only for unfinished work; saved outputs retain
        # their historical policy and source attribution.
        adopt_policy(state, self.settings)
        goal = source_goal(state, self.settings.source_min_usable)
        state['source_goal'] = goal
        if goal['ready']:
            state.setdefault('source_acquisition', {}).pop('hold', None)
            state['production_blockers'] = [x for x in state.get('production_blockers', []) if x != 'core_footage_gap']
            return
        running = db.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind IN ('collect_sources','refresh_sources') AND status IN ('queued','running') AND id<>?", (state['id'], finishing or '')).fetchone()
        if running:
            return
        record = state.setdefault('source_acquisition', {'round':0, 'queries':[], 'urls':[]})
        record.setdefault('round', 0)
        if record.get('hold'):
            # Preserve the exhausted round and its hold. A separate normal
            # worker must obtain fresh validated planning evidence.
            from .video_agent_actions import source_recovery_job
            rows = db.execute("SELECT * FROM jobs WHERE task_id=? AND kind='collect_sources' AND status='done' ORDER BY updated DESC",
                              (state['id'],)).fetchall()
            owner = next((row for row in rows if source_recovery_job(state, row)), None)
            if owner is not None:
                payload = {'round':record['round'], 'run_id':state['run_id'],
                           'source_policy':adopt_policy(state, self.settings),
                           'planning_recovery_from':owner['id']}
                self.store.enqueue(db, state['id'], 'collect_sources', payload,
                    'source-plan-recovery:'+state['run_id']+':'+owner['id'])
            return
        from .source_search.strategy import restore_history
        restore_history(record)
        record.setdefault('queued_at', time.time())
        run = state.get('run_id', 'initial')
        failed = db.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind='collect_sources' AND status='failed'", (state['id'],)).fetchone()
        if failed:
            return  # Persistent authentication/configuration errors need repair, not another identical request.
        policy = adopt_policy(state, self.settings)
        goal = source_goal(state, self.settings.source_min_usable)
        state['source_goal'] = goal
        job_id = self.store.enqueue(db, state['id'], 'collect_sources', {'round':record['round'], 'run_id':run, 'source_policy':policy}, f"collect:{run}:{record['round']}")
        # Each round has a finite candidate count. Queue the next strategy
        # fairly after other tasks; pacing is independent of operation progress.
        not_before = record.get('next_attempt_at', 0)
        if not_before > time.time():
            db.execute('UPDATE jobs SET checkpoint=? WHERE id=?', (json.dumps({'not_before':not_before}), job_id))
        state['source_search'] = {'status':'queued', 'message':('소스 접근·서비스 재개 대기 · '
            + ' / '.join(record['waiting'].get('diagnostics', [])) if record.get('waiting')
            else '자동 추가 수집 대기 · '+goal_message(goal)), 'progress':0}

    def handle_source_error(self, job, error):
        from .source_visual_queries import VisualQueryRejection, register_rejection_evidence
        if isinstance(error, VisualQueryRejection):
            change_claimed(self.store,job,lambda state,db: register_rejection_evidence(state,job,error))
        from .source_access_preflight import SourceAccessWaiting
        if isinstance(error, SourceAccessWaiting):
            self.store.defer(job, str(error), max(1,error.retry_at-time.time()), waiting=True, waiting_status='source_wait')
            return
        from .retry_policy import classify_failure
        from .retry_budget import reserve
        decision = classify_failure(error, stage=job['kind'])
        job['checkpoint']['failure_classification'] = decision
        if reserve(self.store, job, decision, self.store.get(job['task_id'])):
            self.store.defer(job, str(error), max(60, decision['retry_after_seconds'] or 0))
        else:
            self.store.fail(job, error)

    def _bind_source_attempt_progress(self, state, job, progress):
        from .source_pause_receipts import binding, validate_root, validate_child
        job.setdefault('checkpoint', {})
        def created(path):
            entry = {**binding(state, job), 'manifest_path':str(Path(path).resolve()), 'workers':[]}
            validate_root(self.settings.source_dir, entry, state, job)
            job['checkpoint'].setdefault('source_attempts', []).append(entry)
            self.store.checkpoint(job, job['checkpoint'])
        def worker(path, settled=False):
            entries = job['checkpoint'].get('source_attempts', [])
            if not entries:
                raise ValueError('검색 작업자 소유 수집 영수증이 등록되지 않았습니다.')
            entry = entries[-1]
            manifest = validate_root(self.settings.source_dir, entry, state, job)
            path = str(validate_child(manifest, path))
            match = next((w for w in entry['workers'] if w['path'] == path), None)
            if match is None:
                if settled:raise ValueError('등록되지 않은 검색 작업자의 종료 기록입니다.')
                entry['workers'].append({'path':path, 'settled':False})
            elif settled:
                match['settled'] = True
            self.store.checkpoint(job, job['checkpoint'])
        def visual_query_input(input_sha256):
            owner={'task_id':state['id'],'job_id':job['id'],'run_id':state.get('run_id')}
            if job.get('task_id') != state['id'] or job.get('payload',{}).get('run_id') != state.get('run_id'):
                raise ValueError('시각 검색 입력의 작업 소유권이 다릅니다.')
            job['checkpoint']['visual_query_input']={**owner,'input_sha256':input_sha256}
            self.store.checkpoint(job,job['checkpoint'])
            return owner
        progress.visual_query_input = visual_query_input
        progress.source_attempt_created = created
        progress.source_worker_checkpoint = worker
        progress.source_worker_settled = lambda path: worker(path, True)
        return progress

    def _settled_empty_product_candidate(self, state, job, entry):
        from .source_pause_receipts import binding, snapshot, read_bound_json, SourceReceiptWaiting
        expected = binding(state, job)
        context = entry.get('search_context')
        wanted = expected.get('search_context')
        if (entry.get('receipt_path') or not isinstance(context, dict)
                or not isinstance(wanted, dict) or context.get('product') != ''
                or not wanted.get('product')
                or any(entry.get(k) != v for k, v in expected.items() if k != 'search_context')
                or {k:v for k,v in context.items() if k != 'product'} !=
                   {k:v for k,v in wanted.items() if k != 'product'}
                or not entry.get('workers')
                or any(w.get('settled') is not True for w in entry['workers'])):
            raise SourceReceiptWaiting('빈 제품 등록 문맥의 제한적 복구 조건 확인 대기')
        candidate = copy.deepcopy(entry)
        candidate['search_context'] = copy.deepcopy(wanted)
        receipt = snapshot(self.settings.source_dir, candidate, state, job)
        manifest, digest = read_bound_json(candidate['manifest_path'])
        if (manifest.get('status') != 'failed'
                or manifest.get('execution_audit_available') is not True
                or manifest.get('run_id') != expected['run_id']
                or manifest.get('search_context') != wanted
                or manifest.get('source_policy') != expected.get('source_policy')
                or digest != receipt['manifest_sha256']):
            raise SourceReceiptWaiting('실패 실행 원본의 문맥 복구 증명 확인 대기')
        candidate['descriptor_recovery'] = {
            'method':'atomic-settled-empty-product-v3',
            'previous_descriptor':copy.deepcopy(entry), 'manifest_sha256':digest}
        return candidate, receipt

    def _restore_source_attempt_history(self, state, job):
        from .source_pause_receipts import verified_receipt, merge_receipt, SourceReceiptWaiting
        receipts=[]
        for entry in job.get('checkpoint', {}).get('source_attempts', []):
            if not entry.get('receipt_path'):
                self._preserve_source_attempt_history(state, job)
            try:receipt=verified_receipt(self.settings.source_dir, entry, state, job)
            except SourceReceiptWaiting as exc:
                self._record_source_receipt_wait(job, str(exc));raise
            receipts.append({**receipt, 'receipt_path':entry['receipt_path'], 'receipt_sha256':entry['receipt_sha256']})
        context = job.get('checkpoint', {}).get('parser_repair_context')
        if context:
            from .source_pause_receipts import binding, read_bound_json, validate_child
            from pathlib import PureWindowsPath
            import re
            if (job.get('task_id') != state['id']
                    or job.get('payload', {}).get('run_id') != state.get('run_id')
                    or context.get('task_id') != state['id']
                    or context.get('run_id') != state.get('run_id')):
                raise SourceReceiptWaiting('검색 복구 작업·실행 결속 확인 대기')
            for accepted in state.get('source_acquisition', {}).get('interrupted_attempts', []):
                if (accepted.get('run_id') != state.get('run_id')
                        or accepted.get('search_context') != binding(state, job).get('search_context')):
                    continue
                owned = {**accepted, 'workers': [dict(path=w['path'], settled=True)
                    for w in accepted.get('worker_checkpoints', [])]}
                owner = {'id': accepted.get('studio_job_id'), 'payload': {
                    'run_id': accepted.get('run_id'), 'request': accepted.get('source_request', '')}}
                try:
                    receipt = verified_receipt(self.settings.source_dir, owned, state, owner)
                except SourceReceiptWaiting as exc:
                    self._record_source_receipt_wait(job, str(exc));raise
                receipts.append({**receipt, 'receipt_path':accepted['receipt_path'],
                    'receipt_sha256':accepted['receipt_sha256']})
        if not receipts:return state
        recoveries = []
        if context:
            from .source_coverage import bind_search_rows
            from .source_search.readiness import readiness_record, parser_revision
            from .search_access import access_record, manual_required
            preflight = job.get('checkpoint', {}).get('source_access_preflight', {})
            for observation in context.get('observations', []):
                saved = observation.get('readiness')
                if (observation.get('provider') != 'tiktok'
                        or observation.get('status') != 'readiness_blocked'
                        or observation.get('manual_gate_active') is not False
                        or observation not in preflight.get('observations', [])
                        or not isinstance(saved, dict)
                        or saved.get('reason') != 'page_unresolved'
                        or saved.get('parser_revision') != parser_revision('tiktok')
                        or saved.get('recheck_requested') is not False
                        or type(saved.get('at')) not in (int, float)
                        or readiness_record(self.settings.data_dir, 'tiktok') != saved):
                    continue
                access = access_record(self.settings.data_dir, 'tiktok')
                if manual_required(access) or access.get('until', 0) > time.time():continue
                for receipt in receipts:
                    for worker in receipt.get('worker_checkpoints', []):
                        child = validate_child(receipt['manifest_path'], worker['path'])
                        document, digest = read_bound_json(child)
                        if digest != worker['sha256']:
                            raise SourceReceiptWaiting('복구 검색 체크포인트 SHA 확인 대기')
                        rows = bind_search_rows(document.get('searches', []),
                            receipt.get('run_id'), receipt.get('search_context'))
                        for row in rows:
                            requests = row.get('requests')
                            execution = row.get('execution')
                            if (row.get('provider') != 'tiktok'
                                    or row.get('language') == 'image'
                                    or row.get('query') != saved.get('query')
                                    or row.get('parser_revision') != saved.get('parser_revision')
                                    or row.get('run_id') != state.get('run_id')
                                    or row.get('search_context') != receipt.get('search_context')
                                    or row.get('status') != 'page_unresolved'
                                    or row.get('stage') != 'locate_search_input'
                                    or row.get('reason') != 'search_input_unavailable_before_submit'
                                    or row.get('error') != 'PermissionError'
                                    or execution != {'query_submitted':False,'query_url_matched':False}
                                    or not isinstance(requests, list) or len(requests) != 1
                                    or requests[0].get('operation') != 'search_input'
                                    or type(requests[0].get('at')) not in (int, float)
                                    or not 0 <= saved['at'] - requests[0]['at'] <= 5):
                                continue
                            detail = row.get('error_detail')
                            match = (re.search(r"'([^']+)' -> '([^']+)'$", detail)
                                if isinstance(detail, str) and detail.startswith('[WinError 5]') else None)
                            if not match:continue
                            temporary, target = map(PureWindowsPath, match.groups())
                            expected = PureWindowsPath(str(child))
                            if (target != expected or temporary.parent != expected.parent
                                    or temporary.suffix != '.tmp'):continue
                            recoveries.append((copy.deepcopy(saved), receipt['receipt_sha256'], row))
        def restore(s, db):
            from .source_search.strategy import restore_history
            record=s.setdefault('source_acquisition', {})
            for receipt in receipts:merge_receipt(record,receipt)
            restore_history(record)
            for saved, digest, observed in recoveries:
                for row in record.get('queries', []):
                    if all(observed.get(k) == v for k,v in row.items()):
                        previous = copy.deepcopy(row)
                        row['execution'].update(resolution='confirmed_not_submitted',
                            resolution_receipt_sha256=digest)
                        record.setdefault('search_resolutions', []).append({
                            'basis':'settled_worker_pre_input_checkpoint_failure',
                            'receipt_sha256':digest,'previous':previous})
            record.pop('receipt_wait',None)
        restored = change_claimed(self.store, job, restore)
        if recoveries:
            from .studio_pause import check_paused
            from .editing_adapter import _atomic_json
            for saved, digest, observed in recoveries:
                resolutions = restored.get('source_acquisition', {}).get('search_resolutions', [])
                if not any(r.get('receipt_sha256') == digest
                        and r.get('previous', {}).get('query') == saved['query']
                        and r.get('basis') == 'settled_worker_pre_input_checkpoint_failure'
                        for r in resolutions):continue
                check_paused(self.store, job)
                self.store.checkpoint(job, job['checkpoint'])
                access = access_record(self.settings.data_dir, 'tiktok')
                if (manual_required(access) or access.get('until', 0) > time.time()
                        or readiness_record(self.settings.data_dir, 'tiktok') != saved):continue
                _atomic_json(Path(self.settings.data_dir)/'search_readiness'/'tiktok.json',
                    {**saved,'recheck_requested':True,'recheck_at':time.time(),
                     'storage_failure_recovery':{'task_id':restored['id'],'job_id':job['id'],
                        'run_id':restored.get('run_id'),'receipt_sha256':digest,
                        'previous_readiness':saved}})
                break
        return restored

    def _record_source_receipt_wait(self, job, message):
        change_claimed(self.store,job,lambda s,db:s.setdefault('source_acquisition',{}).update(
            receipt_wait={'status':'receipt_wait','message':message,'at':time.time()}))

    def _preserve_source_attempt_history(self, state, job):
        from .source_pause_receipts import snapshot, sha, merge_receipt, SourceReceiptWaiting
        from .editing_adapter import _atomic_json
        for entry in job.get('checkpoint', {}).get('source_attempts', []):
            if entry.get('receipt_path'):continue
            # Reject a stale claim before creating even an append-only receipt.
            self.store.checkpoint(job,job['checkpoint'])
            candidate = copy.deepcopy(entry)
            try:
                try:
                    receipt=snapshot(self.settings.source_dir,candidate,state,job)
                except SourceReceiptWaiting:
                    candidate, receipt = self._settled_empty_product_candidate(state,job,entry)
            except SourceReceiptWaiting as exc:
                self._record_source_receipt_wait(job,str(exc));raise
            path=Path(entry['manifest_path']).parent/'interrupted-execution-receipt.json'
            if path.is_file():
                if json.loads(path.read_text(encoding='utf-8'))!=receipt:
                    raise SourceReceiptWaiting('기존 수집 중단 영수증과 현재 기록이 달라 확인 대기')
            else:_atomic_json(path,receipt)
            candidate.update(receipt_path=str(path.resolve()),receipt_sha256=sha(path))
            previous = copy.deepcopy(entry)
            entry.clear();entry.update(candidate)
            try:
                self.store.checkpoint(job,job['checkpoint'])
            except BaseException:
                entry.clear();entry.update(previous)
                raise
            bound={**receipt,'receipt_path':entry['receipt_path'],'receipt_sha256':entry['receipt_sha256']}
            change_claimed(self.store,job,lambda s,db:merge_receipt(s.setdefault('source_acquisition',{}),bound))

    def _collect_sources(self, state, job):
        job.setdefault('task_id', state['id'])
        # Queue delay and execution duration are diagnostics, never a remaining
        # time budget inherited by searches, downloads or visual reviews.
        started = time.monotonic()
        result = None
        access_wait = False
        try:
            result = self._collect_source_attempt(state, job)
            return result
        except Exception as exc:
            from .source_access_preflight import SourceAccessWaiting
            # A settled model/service wait also keeps its actual evidence, so
            # retrying that wait does not lose scopes or become a false hold.
            self._preserve_source_attempt_history(self.store.get(state['id']), job)
            access_wait = isinstance(exc, SourceAccessWaiting)
            raise
        finally:
            if not access_wait and (result is None or not result.get('stopped')):
                elapsed = max(0, time.monotonic()-started)
                from .source_core_priority import enabled as core_enabled
                if result is not None and core_enabled(run_policy(state)):
                    result['execution_seconds_including_model_wait']=elapsed
                def record_execution(s, db):
                    record = s.setdefault('source_acquisition', {})
                    record['execution_seconds'] = record.get('execution_seconds', 0)+elapsed
                change_claimed(self.store, job, record_execution)

    def _settled_source_withdrawal(self, source):
        if (not source.get('source_interval_withdrawal')
                or source.get('reviewed_intervals') != []
                or source.get('editing_eligible') is not False
                or (source.get('manual_usage_review') or {}).get('editing_eligible') is not False):
            return False
        from .source_review_withdrawals import apply_withdrawals
        try:
            if sha256_file(Path(source['path'])) != source.get('sha256'):
                return False
            checked = apply_withdrawals(self.settings, source)
            return bool(checked.get('source_interval_withdrawal') == source['source_interval_withdrawal']
                        and checked.get('reviewed_intervals') == []
                        and checked.get('editing_eligible') is False
                        and (checked.get('manual_usage_review') or {}).get('editing_eligible') is False
                        and Path(source['source_interval_withdrawal']['receipt']).is_file())
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def _collect_source_attempt(self, state, job):
        job.setdefault('task_id', state['id'])
        if state.get('creation_mode') == 'self_shot':
            raise ValueError('내 촬영 영상 작업에는 외부 영상을 수집하지 않습니다.')
        from .source_finder import find_sources
        from .source_overlay_review import needs_overlay_review
        from .source_presentation import needs_pending_presentation_review
        from .studio_pause import check_paused
        def progress(message, pct):
            check_paused(self.store, job)
            def update(s, db):
                old = s.get('source_search', {})
                strategy_message = str(message) if str(message).startswith('검색 전략 · ') else old.get('strategy_message', '')
                s['source_search'] = {'status':'running','message':str(message)[:300], 'progress':pct,
                                      'strategy_message':strategy_message[:400]}
            change_claimed(self.store, job, update)
        progress.check_cancel = lambda: check_paused(self.store, job)
        state = self._restore_source_attempt_history(state,job)
        progress.check_cancel()
        from .source_search.strategy import restore_history
        # Recovered queued jobs also migrate pre-upgrade search manifests once.
        resolved_hashes=set()
        def initialize(s, db):
            from .scene_requirements import clear_cached_review_errors
            for source in s.get('sources',[]):
                if clear_cached_review_errors(source):resolved_hashes.add(source['sha256'])
            record = s.setdefault('source_acquisition', {})
            restore_history(record)
        state = change_claimed(self.store, job, initialize)
        acquisition = state.get('source_acquisition', {})
        recovery_owner = job.get('payload', {}).get('planning_recovery_from')
        if recovery_owner:
            from .video_agent_actions import source_recovery_job
            from .source_preparation import PreparationEvidenceWaiting
            with self.store.connect() as db:
                owner = db.execute('SELECT * FROM jobs WHERE id=?', (recovery_owner,)).fetchone()
            if (job.get('kind') != 'collect_sources'
                    or job.get('task_id') != state.get('id')
                    or job.get('payload', {}).get('run_id') != state.get('run_id')
                    or job.get('payload', {}).get('round') != acquisition.get('round')
                    or not source_recovery_job(state, owner)):
                raise PreparationEvidenceWaiting('계획 복구 작업의 마지막 완료 수집·작업·실행 결속이 다릅니다.')
        if acquisition.get('hold'):
            if not recovery_owner:
                return {'stopped':True}
            preserved_hold=copy.deepcopy(acquisition['hold'])
            acquisition_config=acquisition_policy(state,run_policy(state))
            context={'task_id':state['id'],'job_id':job['id'],
                'run_id':state.get('run_id'),'search_context':search_scope_for_state(state),
                'source_policy':acquisition_config,
                'rounds':[*acquisition.get('rounds',[]),*acquisition.get('interrupted_attempts',[])],
                'expected_reference_sha256':sha256_file(Path(state['reference_video']))}
            if not job['checkpoint'].get('planning_preparation'):
                self._bind_source_attempt_progress(state,job,progress)
                prepared=find_sources(self.settings,state['shortcode'],progress,
                    search_request=state.get('source_search_brief',''),
                    search_round=job['payload'].get('round',0),
                    previous_searches=current_search_rows(state),
                    exclude_urls=[*acquisition.get('urls',[]),*acquisition.get('inspected_urls',[])],
                    search_context={**context,'preparation_only':True})
                self._preserve_source_attempt_history(self.store.get(state['id']),job)
                if (prepared.get('preparation_only') is not True
                        or prepared.get('run_id')!=context['run_id']
                        or prepared.get('search_context')!=context['search_context']):
                    raise PreparationEvidenceWaiting('계획 복구 준비 반환의 실행·제품 결속이 다릅니다.')
                job['checkpoint']['planning_preparation']={
                    **{k:copy.deepcopy(context[k]) for k in
                       ('task_id','job_id','run_id','search_context','source_policy')},
                    'path':prepared['preparation_bundle_path'],
                    'sha256':prepared['preparation_bundle_sha256']}
                self.store.checkpoint(job,job['checkpoint'])
            state=self.store.get(state['id'])
            ready=self._source_access_gate(state,job,current_search_rows(state))
            if not ready:
                raise PreparationEvidenceWaiting('계획 복구의 실제 미사용 접근 경로 확인 대기')
            def accept_planning(s,db):
                current=s.setdefault('source_acquisition',{})
                owner=db.execute('SELECT * FROM jobs WHERE id=?',(recovery_owner,)).fetchone()
                if (current.get('hold')!=preserved_hold
                        or not source_recovery_job(s,owner)
                        or search_scope_for_state(s)!=context['search_context']
                        or acquisition_policy(s,run_policy(s))!=acquisition_config):
                    raise PreparationEvidenceWaiting('계획 복구 수용 중 소유 작업·보류·검색 문맥이 변경되었습니다.')
                self.release_source_hold(s)
                # Consume the scheduling marker atomically with acceptance.
                # A later claim resumes normal acquisition with its bound bundle.
                accepted_payload=copy.deepcopy(job['payload'])
                accepted_payload.pop('planning_recovery_from',None)
                db.execute('UPDATE jobs SET payload=? WHERE id=? AND task_id=?',
                    (json.dumps(accepted_payload),job['id'],s['id']))
                self.store.event(db,s['id'],'source_planning_recovered',{
                    'owner_job_id':recovery_owner,'job_id':job['id'],
                    'preparation':copy.deepcopy(job['checkpoint']['planning_preparation']),
                    'ready_routes':copy.deepcopy(ready)})
            state=change_claimed(self.store,job,accept_planning)
            job['payload'].pop('planning_recovery_from',None)
            acquisition=state.get('source_acquisition',{})
        if (job['kind']=='collect_sources' and not job.get('payload',{}).get('daily_quality_repair')
                and source_goal(state,self.settings.source_min_usable)['ready']):
            return {'stopped':True,'reason':'current_coverage_met'}
        from .source_functional import needs_identity_reanalysis
        if any(needs_identity_reanalysis(state,s) for s in state.get('sources',[])):
            # Explicit identity reanalysis precedes old deferred batches too.
            # Otherwise access waits can leave the original core labels stale.
            identity_review=self._review_pending_local_sources(state,job,progress)
            if identity_review is not None:return identity_review
        deferred=self._review_deferred_downloads(state,job,progress)
        if deferred is not None:return deferred
        if not state.get('reference_duration') and state.get('reference_video'):
            from .source_finder import probe_video
            meta = probe_video(Path(state['reference_video']))
            if meta.get('duration'):
                state = change_claimed(self.store, job, lambda s, db: s.update(reference_duration=meta['duration']))
        result = None
        visual_review_only = False
        manifest_path = job['checkpoint'].get('manifest')
        if manifest_path and Path(manifest_path).is_file():
            result = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
        if result is None:
            from .source_functional import needs_identity_reanalysis
            pending = [s for s in state.get('sources', [])
                       if Path(s['path']).is_file() and not self._settled_source_withdrawal(s)
                       and (not s.get('overlay_review_error') or needs_overlay_review(s))
                       and (needs_overlay_review(s) or needs_pending_presentation_review(s)
                            or needs_identity_reanalysis(state,s) or s['sha256'] in resolved_hashes)]
            if pending:
                # Finish the missing local review before requesting more files.
                # A completed local review participates in the no-progress check.
                visual_review_only = True
                manifest_path = state.get('source_search_manifest_path') or state['manifest_path']
                result = {'candidates':[], 'source_policy':state.get('source_policy'),
                          'search_audit':[{'provider':'saved-overlay-review','status':'results',
                                           'query':'','candidates':len(pending)}]}
            else:
                local=self._recover_local_source_intervals(state,job,progress,inventory_only=True)
                if local is not None:return local
                if (job['kind']=='collect_sources' and not job.get('payload',{}).get('daily_quality_repair')
                        and source_goal(self.store.get(state['id']),self.settings.source_min_usable)['ready']):
                    return {'stopped':True,'reason':'current_coverage_met'}
                state=self._prepare_source_queries(state,job,progress)
                acquisition=state.get('source_acquisition',{})
                ready_routes = (self._source_access_gate(state,job,acquisition.get('queries',[]))
                    if acquisition.get('waiting') or acquisition.get('rounds') else None)
                current=self.store.get(state['id'])
                if current.get('source_acquisition',{}).get('hold'):return {'stopped':True}
                if source_goal(current,self.settings.source_min_usable)['ready']:
                    return {'sources':current['sources'],'source_search_manifest_path':current.get('source_search_manifest_path',''),
                            'round':job['payload'].get('round',0),'visual_review_only':True,
                            'source_policy':run_policy(current),'searches':[],'core_fallback_accepted':True}
                state=current;acquisition=state.get('source_acquisition',{})
                change_claimed(self.store,job,lambda s,db:s.setdefault('source_acquisition',{}).setdefault('started_at',time.time()))
                from .source_batches import TaskBatchReviewer
                from .source_core_priority import support_search
                from .source_coverage import query_receipts_only
                batch_reviewer = (TaskBatchReviewer(self,job,progress)
                    if state.get('automation',{}).get('active') and
                    (job['kind']=='collect_sources' or job['payload'].get('daily_quality_repair')) else None)
                # Bind callbacks to the same final state used by acquisition.
                self._bind_source_attempt_progress(state,job,progress)
                result = find_sources(self.settings, state['shortcode'], progress,
                    search_request=state.get('source_search_brief', ''),
                    search_round=job['payload'].get('round',0),
                    previous_searches=(current_search_rows(state)
                        if state.get('source_policy',{}).get('search_minimums') else acquisition.get('queries', [])),
                    exclude_urls=[*acquisition.get('urls', []), *acquisition.get('inspected_urls', [])],
                    search_context={'task_id':state['id'],'job_id':job['id'],
                                    **({'planning_preparation':copy.deepcopy(job['checkpoint']['planning_preparation'])}
                                       if job['checkpoint'].get('planning_preparation') else {}),
                                    'completed_rounds':acquisition.get('bounded_rounds',0),
                                    'rounds':[*acquisition.get('rounds',[]), *acquisition.get('interrupted_attempts',[])],
                                    'expected_reference_sha256':(sha256_file(Path(state['reference_video']))
                                        if state.get('reference_video') and Path(state['reference_video']).is_file() else None),
                                    'ready_routes':ready_routes,
                                    'search_context':search_scope_for_state(state),
                                    'source_policy':acquisition_policy(state,run_policy(state)),
                                    'support_search':support_search(state),
                                    'query_only':bool(batch_reviewer is not None and query_receipts_only(
                                        state,job,source_goal(state,self.settings.source_min_usable))),
                                    'run_id':state.get('run_id')}, review_batch=batch_reviewer)
                manifest_path = str(Path(result['zip_path']).parent/'manifest.json')
                job['checkpoint']['manifest'] = manifest_path
                self.store.checkpoint(job, job['checkpoint'])
                # Once acquisition has returned, searches/transfers are settled
                # even if the following task-scoped visual review is paused.
                self._preserve_source_attempt_history(state,job)
        manifest = Path(manifest_path)
        candidates = [c for c in result.get('candidates',[]) if c.get('selected_for_zip')]
        files = [manifest.parent/c['downloaded_file'] for c in candidates if c.get('downloaded_file')]
        incoming = self._source_records(files, manifest)
        incoming.sort(key=lambda s: not bool(s.get('similarity_warnings')), reverse=True)
        # Review saved sources too; previously downloaded context footage stays
        # usable, while a high appearance score alone cannot assert core action.
        from .source_core_priority import enabled as core_enabled
        merged = unique_sources([*copy.deepcopy(state['sources']), *incoming],core_priority=core_enabled(run_policy(state)))
        from .source_batches import cached_records
        batch_cache = cached_records(self,job)
        merged = [copy.deepcopy(batch_cache.get(s['sha256'],s)) for s in merged]
        if manifest.is_file() and not visual_review_only:
            from .editing_adapter import _atomic_json
            visual = job['checkpoint'].get('source_visual_review')
            visual_key = str(manifest.resolve()) + ':' + sha256_file(manifest)
            if visual and visual.get('input_key') == visual_key and Path(visual.get('path', '')).is_file() and sha256_file(Path(visual['path'])) == visual.get('sha256'):
                cached = json.loads(Path(visual['path']).read_text(encoding='utf-8')).get('sources', {})
                merged = [copy.deepcopy(cached.get(s['sha256'], s)) for s in merged]
            else:
                path = manifest.parent / ('source-review-' + (job.get('claim_token') or job['id']) + '.json')
                _atomic_json(path, {'input_key': visual_key, 'sources': {}})
                job['checkpoint']['source_visual_review'] = {'path': str(path.resolve()), 'sha256': sha256_file(path), 'input_key': visual_key}
                self.store.checkpoint(job, job['checkpoint'])
        reviewed, review_completion = self._review_source_records(state, job, merged, progress)
        from .source_audit import reviewed_platform_outcomes
        outcomes = (reviewed_platform_outcomes(manifest, result, reviewed)
                    if not visual_review_only and result.get('execution_audit_available', 'search_audit' in result)
                    else result.get('platform_outcomes', {}))
        from .source_search.strategy import candidate_ledgers
        return {'sources':reviewed, 'source_search_manifest_path':str(manifest),
                'source_policy':result.get('source_policy'), 'platform_outcomes':outcomes,
                'searches':result.get('search_audit', []),
                **candidate_ledgers(result.get('candidates', [])),
                'visual_review_only':visual_review_only,
                'review_completion':review_completion,
                'round':job['payload'].get('round',0)}

    def _prepare_source_queries(self,state,job,progress):
        from .source_preparation import preflight_preparation, PreparationEvidenceWaiting
        from .source_finder import find_sources
        from .studio_pause import check_paused
        check_paused(self.store,job)
        if not self.settings.source_browser_search or not run_policy(state).get('search_minimums'):
            return state
        plan,frames=preflight_preparation(self.settings,state,job)
        if not frames:return state
        if plan is not None:
            return self._prepare_after_parser_recovery(state,job,progress,plan,frames)
        acquisition=state.get('source_acquisition',{})
        acquisition_config=acquisition_policy(state,run_policy(state))
        owner={'task_id':state['id'],'job_id':job['id'],'run_id':state.get('run_id'),
               'search_context':search_scope_for_state(state),'source_policy':acquisition_config}
        if (job.get('task_id')!=state['id']
                or job.get('payload',{}).get('run_id')!=state.get('run_id')
                or acquisition.get('hold') or state.get('creation_mode')=='self_shot'):
            raise PreparationEvidenceWaiting('검색 준비 획득의 작업·실행 조건 확인 대기')
        self._bind_source_attempt_progress(state,job,progress)
        prepared=find_sources(self.settings,state['shortcode'],progress,
            search_request=state.get('source_search_brief',''),
            search_round=job.get('payload',{}).get('round',0),
            previous_searches=current_search_rows(state),
            exclude_urls=[*acquisition.get('urls',[]),*acquisition.get('inspected_urls',[])],
            search_context={**owner,'preparation_only':True,
                'rounds':[*acquisition.get('rounds',[]),*acquisition.get('interrupted_attempts',[])],
                'expected_reference_sha256':sha256_file(Path(state['reference_video']))})
        self._preserve_source_attempt_history(self.store.get(state['id']),job)
        current=self.store.get(state['id'])
        if (prepared.get('preparation_only') is not True
                or prepared.get('run_id')!=owner['run_id']
                or prepared.get('search_context')!=owner['search_context']
                or current.get('run_id')!=owner['run_id']
                or search_scope_for_state(current)!=owner['search_context']
                or acquisition_policy(current,run_policy(current))!=acquisition_config
                or current.get('source_acquisition',{}).get('hold')):
            raise PreparationEvidenceWaiting('검색 준비 획득 중 작업·실행·근거 변경 확인 대기')
        selected={**copy.deepcopy(owner),'path':prepared['preparation_bundle_path'],
                  'sha256':prepared['preparation_bundle_sha256']}
        candidate=copy.deepcopy(job)
        candidate['checkpoint']['planning_preparation']=selected
        plan,frames=preflight_preparation(self.settings,current,candidate)
        if plan is None or not frames:
            raise PreparationEvidenceWaiting('검색 준비의 독립 검토 계약 확인 대기')
        check_paused(self.store,job)
        job['checkpoint']['planning_preparation']=selected
        self.store.checkpoint(job,job['checkpoint'])
        return current

    def _prepare_after_parser_recovery(self,state,job,progress,plan,frames):
        from .source_access_preflight import SourceAccessWaiting
        from .source_preparation import (PreparationEvidenceWaiting, preflight_preparation,
            acquisition_bundle_path, replanning_bundle_path, load_bundle, save_bundle, digest)
        from .source_visual_queries import cached_visual_queries, apply_visual_queries, verify
        from .source_finder import _post, _transcript_evidence
        from .studio_pause import check_paused
        acquisition=state.get('source_acquisition') or {}
        initial=job.get('checkpoint',{}).get('parser_repair_context')
        prior_response=job.get('checkpoint',{}).get('parser_response_recovery') or {}
        if ((not initial and prior_response.get('status')!='response_validated')
                or job.get('kind')!='collect_sources'
                or job.get('task_id')!=state['id']
                or job.get('payload',{}).get('run_id')!=state.get('run_id')
                or acquisition.get('hold') or acquisition.get('waiting')
                or acquisition.get('receipt_wait') or state.get('creation_mode')=='self_shot'):
            return state
        try:
            self._source_access_gate(state,job)
        except SourceAccessWaiting:
            pass
        else:
            return self.store.get(state['id'])
        current=self.store.get(state['id'])
        recovered=job['checkpoint'].get('parser_response_recovery') or {}
        observations=(job['checkpoint'].get('source_access_preflight') or {}).get('observations',[])
        exhausted=next((r for r in observations if r.get('provider')=='tiktok'),{})
        owner={'task_id':state['id'],'job_id':job['id'],'run_id':state.get('run_id')}
        if (any(recovered.get(k)!=v for k,v in owner.items())
                or recovered.get('status')!='response_validated'
                or recovered.get('grants_media_approval') is not False
                or recovered.get('query_submitted') is not False
                or exhausted.get('status')!='query_exhausted'
                or exhausted.get('reason')!='no_unused_supported_scope'):
            raise PreparationEvidenceWaiting('실제 응답 복구와 미사용 검색 범위 확인 대기')
        check_paused(self.store,job)
        config=acquisition_policy(current,run_policy(current))
        scope=search_scope_for_state(current)
        if (current.get('run_id')!=owner['run_id'] or scope!=search_scope_for_state(state)
                or config!=acquisition_policy(state,run_policy(state))
                or any((current.get('source_acquisition') or {}).get(k)
                       for k in ('hold','waiting','receipt_wait'))):
            raise PreparationEvidenceWaiting('응답 복구 후 검색 준비 결속 변경 확인 대기')
        previous=plan['visual_query_evidence']
        verify(previous)
        feedback={'owner':owner,'previous_receipt':copy.deepcopy(previous),
            'search_context':scope,'search_history':current_search_rows(current),
            'access_observations':[{k:r[k] for k in
                ('provider','status','reason','manual_gate_active') if k in r}
                for r in observations],
            'reason':'validated_parser_recovery_with_consumed_text_scopes'}
        evidence=previous['evidence']
        self._bind_source_attempt_progress(current,job,progress)
        capture=getattr(progress,'visual_query_input',None)
        from .source_visual_queries import binding as visual_binding, digest as visual_digest
        visual_input=visual_binding(current['reference_video'],frames,evidence['text']['caption'],
            evidence['text'],search_minimums=config['search_minimums'],subject_hint=current.get('product',''))
        if not capture or capture(visual_digest(visual_input))!=owner:
            raise PreparationEvidenceWaiting('복구 계획의 현재 작업 입력 결속 확인 대기')
        receipt=cached_visual_queries(self.settings,current['reference_video'],frames,
            evidence['text']['caption'],evidence['text'],search_minimums=config['search_minimums'],
            subject_hint=current.get('product',''),owner_binding=owner,_pool_feedback=feedback)
        updated=apply_visual_queries(plan,receipt,reference_sha256=sha256_file(Path(current['reference_video'])))
        updated.update(run_id=owner['run_id'],search_context=copy.deepcopy(scope))
        post=_post(self.settings,current['shortcode'])
        raw=_transcript_evidence(self.settings,current['shortcode'])
        base=acquisition_bundle_path(self.settings,current['shortcode'],post.caption,raw,config,current.get('product',''))
        selected=job['checkpoint'].get('planning_preparation')
        original=Path(selected['path']) if selected else base
        prepared=load_bundle(original,post.caption,raw)
        destination=replanning_bundle_path(base,updated)
        if destination.resolve()==original.resolve():
            raise PreparationEvidenceWaiting('복구 계획이 새로운 독립 검토 근거를 제공하지 않았습니다.')
        if not destination.exists():
            save_bundle(destination,post.caption,raw,prepared['reference'],frames,prepared['sheet'],
                transcript=prepared['transcript'],query_plan=updated,
                **{k:prepared.get(k,[]) for k in ('visual_product_queries','google_vision_terms',
                    'openclip_product_evidence','subject_reference_indices')})
        selection={**owner,'search_context':scope,'source_policy':config,
            'path':str(destination.resolve()),'sha256':digest(destination)}
        candidate=copy.deepcopy(job);candidate['checkpoint']['planning_preparation']=selection
        fresh=self.store.get(state['id'])
        if (fresh.get('run_id')!=owner['run_id'] or search_scope_for_state(fresh)!=scope
                or acquisition_policy(fresh,run_policy(fresh))!=config
                or any((fresh.get('source_acquisition') or {}).get(k) for k in ('hold','waiting','receipt_wait'))):
            raise PreparationEvidenceWaiting('독립 계획 획득 중 작업 근거 변경 확인 대기')
        new_plan,new_frames=preflight_preparation(self.settings,fresh,candidate)
        if new_plan!=updated or list(new_frames)!=list(frames):
            raise PreparationEvidenceWaiting('복구 계획의 실제 준비 수용 확인 대기')
        check_paused(self.store,job)
        job['checkpoint']['planning_preparation']=selection
        self.store.checkpoint(job,job['checkpoint'])
        return fresh

    def _source_access_gate(self,state,job,history=None):
        from .studio_pause import check_paused
        from .source_access_preflight import check_access, SourceAccessWaiting
        from .source_preparation import preflight_preparation
        check_paused(self.store,job)
        if not self.settings.source_browser_search:
            return None  # Indexed routes keep their own request/access gates.
        if run_policy(state).get('search_minimums'):history=current_search_rows(state)
        try:
            plan,frames=preflight_preparation(self.settings,state,job)
        except (ValueError,OSError,KeyError) as exc:
            raise SourceAccessWaiting('소스 준비 근거 보존 대기 · '+str(exc)) from exc
        from .source_coverage import query_receipts_only
        from .source_core_priority import support_search, support_plan
        supporting=bool(plan and support_search(state))
        if supporting:plan=support_plan(plan)
        error=None
        try:
            ready=check_access(self.settings,state,job,history=history,plan=plan,frames=frames,
                search_only=query_receipts_only(state,job,source_goal(state,self.settings.source_min_usable)))
        except SourceAccessWaiting as exc:
            error=exc;ready=[]
            from .source_parser_recovery import recover_response
            if recover_response(self.settings,self.store,state,job):
                return self._source_access_gate(self.store.get(state['id']),job,history)
        from .source_core_priority import enabled, finite_search_plan, exhausted_fallback, context
        if enabled(run_policy(state)) and plan and not supporting:
            observations=job['checkpoint'].get('source_access_preflight',{}).get('observations',[])
            finite=finite_search_plan(state,plan,frames,observations,history or [])
            saved=state.get('source_acquisition',{}).get('core_search_plan')
            if saved and saved.get('context')==context(state):
                # Temporarily unavailable planned routes remain required, never disappear as scarcity.
                if finite and (finite['queries']!=saved['queries'] or finite['identity']!=saved['identity']):
                    finite=None  # A changed independent contract needs a fresh bound search plan.
                else:
                    old=copy.deepcopy(saved)
                    if finite:
                        from .source_visual_queries import digest
                        old['routes']=sorted(set(old['routes'])|set(finite['routes']))
                        old['excluded_routes']=[r for r in finite['excluded_routes'] if r['provider'] not in old['routes']]
                        old['sha256']=digest({k:v for k,v in old.items() if k not in {'sha256','excluded_routes'}})
                    finite=old
            if finite:
                def retain(s,db):s.setdefault('source_acquisition',{})['core_search_plan']=copy.deepcopy(finite)
                state=change_claimed(self.store,job,retain)
                receipt=exhausted_fallback(state,finite,observations)
                if error and receipt:
                    def fallback(s,db):
                        s.setdefault('source_acquisition',{})['core_fallback']=receipt
                        self.store.event(db,s['id'],'core_product_shortfall_fallback',receipt)
                    change_claimed(self.store,job,fallback)
                    if not source_goal(self.store.get(state['id']),self.settings.source_min_usable)['ready']:
                        return self._source_access_gate(self.store.get(state['id']),job,history)
                    error=None
        if supporting and error:
            observations=job['checkpoint'].get('source_access_preflight',{}).get('observations',[])
            active=[r for r in observations if r.get('status') not in {'platform_disabled','no_supported_queries'}
                    and r.get('reason')!='existing_browser_search_not_implemented']
            if active and all(r['status']=='query_exhausted' for r in active):
                change_claimed(self.store,job,lambda s,db:self._stop_source_collection(s,db,'strategy_exhausted',
                    ['핵심 제품과 보조 제품의 실제 유한 탐색 완료 · 관련 원본 최소 5개 미달']))
                error=None
        if error:raise error
        check_paused(self.store,job)
        self.store.checkpoint(job,job['checkpoint'])
        return ready

    def _recover_local_source_intervals(self,state,job,progress,*,inventory_only=False):
        """Review observed short scopes before any additional platform request."""
        from .source_interval_recovery import recover, key, POLICY
        from .source_coverage import usable_seconds
        from .source_review_status import failed_outcome, ReviewResponseInvalid
        from .source_functional import REVIEW_POLICY
        from .source_preparation import PreparationEvidenceWaiting
        from .model_service import ModelServiceUnavailable
        from .studio_pause import check_paused
        goal=source_goal(state,self.settings.source_min_usable)
        if goal['ready']:return None
        if (goal.get('policy_version',0)>=5 and goal.get('core_ready')
                and goal.get('search_ready') is False and not state.get('source_diversity_gap')):
            # Re-reviewing intervals of the same parents cannot supply missing
            # actual language searches. Discover under the new identity first;
            # pending local/download reviews above this step still run normally.
            return None
        if goal.get('source_diversity_ready') and goal.get('core_ready') and not state.get('source_diversity_gap'):
            return None  # Missing actual query receipts do not need more local footage review.
        reference=Path(state.get('reference_video') or '')
        if not reference.is_file():return None
        binding={'policy':POLICY,'task_id':state['id'],
            'reference_sha256':sha256_file(reference),'product':state.get('product',''),
            'original_text':state.get('reviewed_original_text') or state.get('original_text','')}
        context_key=key(binding)
        owner_run=state.get('run_id')
        saved=job.setdefault('checkpoint',{}).setdefault('interval_recovery',{})
        context=saved.setdefault(context_key,{'receipts':{}})
        context.setdefault('proposals',{})
        context.update(binding,context_key=context_key)
        from .source_interval_recovery import restore_proposal_ledger
        with self.store.connect() as db:
            prior_rows=db.execute(
                'SELECT checkpoint FROM jobs WHERE task_id=? AND id<>? AND status=?',
                (state['id'],job['id'],'done')).fetchall()
        restore_proposal_ledger(context,binding,context_key,
            [json.loads(row[0]) for row in prior_rows])
        self.store.checkpoint(job,job['checkpoint'])
        def check():
            check_paused(self.store,job)
            self.store.checkpoint(job,job['checkpoint'])
            current=self.store.get(state['id'])
            current_reference=Path(current.get('reference_video') or '')
            current_binding={**binding,'product':current.get('product',''),
                'reference_sha256':sha256_file(current_reference) if current_reference.is_file() else None,
                'original_text':current.get('reviewed_original_text') or current.get('original_text','')}
            if current.get('run_id')!=owner_run or key(current_binding)!=context_key:
                raise PreparationEvidenceWaiting('짧은 구간 검토 중 작업·원본·제품 맥락이 바뀌어 수용 보류')
        context['checkpoint']=lambda:self.store.checkpoint(job,job['checkpoint'])
        # Callables cannot enter the serialized checkpoint.
        runtime={**context,'checkpoint':context.pop('checkpoint')}
        updated=copy.deepcopy(state.get('sources',[]));changed=[]
        def current_goal(candidate):
            from .source_batches import current_records, state_with_search_audit
            current=self.store.get(state['id'])
            current=state_with_search_audit(current,{'run_id':owner_run,
                'search_context':search_scope_for_state(state),
                'search_audit':(state.get('source_acquisition') or {}).get('queries',[])})
            pool=[candidate if s['sha256']==candidate['sha256'] else s for s in updated]
            pool=current_records(current,pool)
            return source_goal({**current,'sources':pool},self.settings.source_min_usable)
        # Ordinary acquisition needs additional usable parents. More seconds from an
        # already counted parent cannot satisfy that shortage. Explicit editing
        # gaps and callers explicitly requesting full interval rescue retain it.
        parent_inventory = bool(inventory_only and goal.get('core_ready')
            and goal.get('duration_requirement')=='preference'
            and goal.get('policy_version',0)>=5 and not state.get('source_diversity_gap')
            and not job.get('payload',{}).get('daily_quality_repair')
            and not (state.get('daily_quality') or {}).get('scene_requirements'))
        def sufficient(candidate):
            inventory=current_goal(candidate)
            if inventory['ready']:return True
            if not parent_inventory:return False
            return candidate.get('id') in inventory.get('source_ids',[])
        for index,source in enumerate(updated):
            if sufficient(source):
                if current_goal(source)['ready']:break
                continue
            if (source.get('manual_usage_review') or {}).get('editing_eligible') is False:continue
            path=Path(source.get('path') or '')
            if not path.is_file():continue
            function=source.get('functional_review') or {}
            if (function.get('reviewed') is True and function.get('source_sha256')==source.get('sha256')
                    and function.get('policy')==REVIEW_POLICY and function.get('same_core_function') is False
                    and function.get('context_usable') is False):continue
            duration=(source.get('video_meta') or {}).get('duration') or 0
            if duration-usable_seconds(source)<.6 and not source.get('overlay_review_error'):continue
            check();progress('기존 영상에서 짧고 선명한 제품 구간 확인',88)
            folder=self.folder(state['id'])/'source-mask-checks'/source['sha256'][:20]/'local-interval-recovery'/context_key[:20]
            def review(candidate):
                rows,_=self._review_source_records(state,job,[candidate],progress)
                if len(rows)!=1:raise ValueError('Recovered scope did not complete normal review')
                return rows[0]
            try:
                candidate=recover(self.settings,source,folder,runtime,review,check=check,sufficient=sufficient)
            except (ModelServiceUnavailable,PreparationEvidenceWaiting):raise
            except ReviewResponseInvalid as exc:
                candidate=copy.deepcopy(source)
                candidate['interval_recovery_diagnostic']=failed_outcome('interval_recovery',exc,source)
            except (ValueError,OSError,KeyError,TypeError) as exc:
                raise PreparationEvidenceWaiting('짧은 구간의 실제 파일·검토 영수증 확인 대기 · '+str(exc)) from exc
            check()
            if candidate!=source:
                updated[index]=candidate;changed.append(candidate)
            if current_goal(candidate)['ready']:break
        if not changed:return None
        return {'sources':changed,'source_search_manifest_path':state.get('source_search_manifest_path') or state['manifest_path'],
            'source_policy':state.get('source_policy'),'searches':[],'attempted_urls':[],'inspected_urls':[],
            'visual_review_only':True,'local_deferred_review':True,'local_interval_recovery':True,
            'round':job.get('payload',{}).get('round',state.get('source_acquisition',{}).get('round',0)),
            'review_completion':{'reason':'local_interval_recovery','reviewed_source_sha256':[s['sha256'] for s in changed]}}

    def _review_pending_local_sources(self,state,job,progress):
        from .source_overlay_review import needs_overlay_review
        from .source_functional import needs_identity_reanalysis
        from .source_presentation import needs_pending_presentation_review
        settled_withdrawal = self._settled_source_withdrawal
        pending=[s for s in state.get('sources',[]) if Path(s.get('path') or '__missing__').is_file()
                 and not settled_withdrawal(s)
                 and (not s.get('overlay_review_error') or needs_overlay_review(s))
                 and (needs_overlay_review(s) or needs_pending_presentation_review(s)
                      or needs_identity_reanalysis(state,s))]
        manifest=state.get('source_search_manifest_path') or state.get('manifest_path')
        if not pending or not manifest:return None
        from .source_batches import review_context
        from .source_preparation import PreparationEvidenceWaiting
        from .source_functional import REVIEW_POLICY
        from .editing_adapter import _atomic_json
        binding={**review_context(state),'policy':REVIEW_POLICY,
            'script_sha256':hashlib.sha256(next((s['text'] for s in state.get('scripts',[])
                if s['id']==state.get('script_id')),'').encode()).hexdigest(),
            'source_inputs':{s['sha256']:hashlib.sha256(json.dumps(s,sort_keys=True).encode()).hexdigest()
                             for s in pending},
            'source_sha256':sorted(s['sha256'] for s in pending)}
        input_key=hashlib.sha256(json.dumps(binding,sort_keys=True).encode()).hexdigest()
        saved=job.setdefault('checkpoint',{}).get('identity_source_review')
        if saved and saved.get('input_key')==input_key:
            path=Path(saved['path'])
            if not path.is_file() or sha256_file(path)!=saved['sha256']:
                raise PreparationEvidenceWaiting('기존 소스 재분석 체크포인트 SHA 확인 대기')
            value=json.loads(path.read_text('utf8'))
            if value.get('binding')!=binding:
                raise PreparationEvidenceWaiting('기존 소스 재분석 입력 확인 대기')
            pending=[copy.deepcopy(value['sources'].get(s['sha256'],s)) for s in pending]
        else:
            folder=self.folder(state['id'])/'source-local-reviews';folder.mkdir(parents=True,exist_ok=True)
            path=folder/(job.get('id','local')+'-'+input_key[:20]+'.json')
            if path.exists():
                raise PreparationEvidenceWaiting('소스 재분석 영수증 소유권 확인 대기')
            _atomic_json(path,{'binding':binding,'input_key':input_key,'sources':{}})
            saved={'input_key':input_key,'path':str(path.resolve()),'sha256':sha256_file(path),
                   'source_sha256':binding['source_sha256']}
            job['checkpoint']['identity_source_review']=saved
            self.store.checkpoint(job,job['checkpoint'])
        reviewed,completion=self._review_source_records(state,job,copy.deepcopy(pending),progress)
        current=self.store.get(state['id'])
        current_script=next((s['text'] for s in current.get('scripts',[])
                             if s['id']==current.get('script_id')),'')
        if (review_context(current)!=review_context(state)
                or hashlib.sha256(current_script.encode()).hexdigest()!=binding['script_sha256']):
            raise PreparationEvidenceWaiting('기존 소스 재분석 중 작업·원본·제작 대본 변경 확인 대기')
        return {'sources':reviewed,'source_search_manifest_path':manifest,'source_policy':state.get('source_policy'),
                'searches':[],'attempted_urls':[],'inspected_urls':[],'visual_review_only':True,
                'local_deferred_review':True,'review_completion':completion,
                'round':job.get('payload',{}).get('round',state.get('source_acquisition',{}).get('round',0))}

    def _deferred_download_records(self,state,owner_job=None):
        """Only this task's explicitly unfinished acquisition receipts authorize reuse."""
        known=list(state.get('sources',[]))
        for run in state.get('runs',[]):known.extend(run.get('artifacts',{}).get('sources',[]))
        hashes={s.get('sha256') for s in known if s.get('sha256')}
        urls={canonical_video_key(s.get('origin_url','')) for s in known if s.get('origin_url')}
        origins=[];records=[];seen=set()
        acquisition=state.get('source_acquisition',{})
        receipts=[*acquisition.get('rounds',[]),
                  *[{**r,'interrupted':True} for r in acquisition.get('interrupted_attempts',[])]]
        for receipt in [*receipts,*acquisition.get('local_source_reviews',[])]:
            completion=receipt.get('review_completion') or {}
            hashes.update(completion.get('reviewed_source_sha256',[]))
            urls.update(canonical_video_key(u) for u in completion.get('reviewed_origin_urls',[]) if u)
        if owner_job is not None:
            # A refresh that already searched may resume only its registered
            # settled attempts, without prioritizing another job's old reviews.
            from .source_pause_receipts import verified_receipt
            descriptors=owner_job.get('checkpoint',{}).get('source_attempts',[])
            allowed=set()
            for descriptor in descriptors:
                verified_receipt(self.settings.source_dir,descriptor,state,owner_job)
                allowed.add((descriptor['manifest_path'],descriptor['receipt_sha256']))
            receipts=[r for r in receipts if r.get('interrupted')
                and r.get('studio_job_id')==owner_job['id']
                and (r.get('manifest_path'),r.get('receipt_sha256')) in allowed]
        for receipt in receipts:
            completion=receipt.get('review_completion') or {}
            interrupted=receipt.get('interrupted')
            if ((not interrupted and (completion.get('reason')!='quota_met' or not completion.get('deferred_sources',0)))
                    or receipt.get('run_id') and receipt['run_id']!=state.get('run_id')):continue
            manifest=Path(receipt.get('manifest_path') or '')
            if not manifest.is_file():
                if interrupted:
                    from .source_pause_receipts import SourceReceiptWaiting
                    raise SourceReceiptWaiting('미검토 수신 영상의 중단 원본 영수증 확인 대기')
                continue
            data=json.loads(manifest.read_text(encoding='utf-8'))
            if data.get('shortcode') and data['shortcode']!=state.get('shortcode'):continue
            origins.append({'manifest_path':str(manifest.resolve()),'manifest_sha256':sha256_file(manifest),
                            'round':receipt.get('round'),'job_id':receipt.get('job_id')})
            selected=[]
            raw_candidates=list(enumerate(data.get('candidates',[])))
            if any(c.get('source_quality') in {'clean-source','light-overlay','edited-with-text'} for _,c in raw_candidates):
                def _deferred_sort_key(item):
                    idx,c=item
                    qual=c.get('source_quality') or 'unknown'
                    meta=c.get('video_meta') or {}
                    landscape=(meta.get('width') or 0)>(meta.get('height') or 0)
                    no_cap_wm=float(c.get('caption_frame_ratio') or 0)==0.0 and float(c.get('watermark_frame_ratio') or 0)==0.0
                    qual_rank=(0 if qual in {'clean-source','light-overlay'} and no_cap_wm else
                               1 if qual in {'clean-source','light-overlay'} else
                               2 if qual=='unknown' else 3)
                    return (qual=='edited-with-text',landscape,qual_rank,idx)
                raw_candidates.sort(key=_deferred_sort_key)
            for _,candidate in raw_candidates:
                digest=candidate.get('file_sha256');url=canonical_video_key(candidate.get('original_url') or candidate.get('url',''))
                if ((not interrupted and not candidate.get('selected_for_zip')) or not candidate.get('downloaded_file')
                        or interrupted and (not candidate.get('video_meta') or not candidate.get('preview_file'))
                        or not isinstance(digest,str) or len(digest)!=64 or digest in hashes or digest in seen
                        or 'deferred_source_sha256' in completion and digest not in completion['deferred_source_sha256']
                        or url and url in urls or candidate.get('rejection_reasons') or candidate.get('error')
                        or candidate.get('editing_eligible') is False
                        or (candidate.get('manual_usage_review') or {}).get('editing_eligible') is False):continue
                path=(manifest.parent/candidate['downloaded_file']).resolve()
                if not path.is_relative_to(manifest.parent.resolve()) or not path.is_file():
                    if interrupted:
                        from .source_pause_receipts import SourceReceiptWaiting
                        raise SourceReceiptWaiting('미검토 수신 영상의 소유 파일 확인 대기')
                    continue
                if sha256_file(path)!=digest:
                    if interrupted:
                        from .source_pause_receipts import SourceReceiptWaiting
                        raise SourceReceiptWaiting('미검토 수신 영상의 실제 SHA 확인 대기')
                    raise ValueError('미검토 수신 영상의 실제 SHA가 수집 영수증과 다릅니다.')
                selected.append(path);seen.add(digest)
            if selected:
                if interrupted:
                    from .source_pause_receipts import verified_receipt
                    # The immutable receipt and current task/reference must still
                    # bind the partial, before any received file enters local review.
                    owned={**receipt,'workers':[{'path':w['path'],'settled':True}
                        for w in receipt.get('worker_checkpoints',[])]}
                    verified_receipt(self.settings.source_dir,owned,state,
                        {'id':receipt['studio_job_id'],'payload':{'run_id':receipt.get('run_id'),
                         'request':receipt.get('source_request','')}})
                rows=self._source_records(selected,manifest)
                from .source_batches import cached_records
                saved_batch=data.get('batch_review_checkpoint')
                if saved_batch:
                    restored=cached_records(self,job={},saved=saved_batch,state=state)
                    rows=[copy.deepcopy(restored.get(s['sha256'],s)) for s in rows]
                for source in rows:
                    source['deferred_download_origin']={'manifest_path':str(manifest.resolve()),
                        'manifest_sha256':sha256_file(manifest),'round':receipt.get('round'),'job_id':receipt.get('job_id')}
                records.extend(rows)
        return records,origins

    def _review_deferred_downloads(self,state,job,progress,*,own_attempts_only=False):
        records,origins=(self._deferred_download_records(state,owner_job=job)
                        if own_attempts_only else self._deferred_download_records(state))
        saved=job.setdefault('checkpoint',{}).get('deferred_source_review')
        if not records:return None
        from .editing_adapter import _atomic_json
        import hashlib
        reference=Path(state.get('reference_video') or '')
        binding={'task_id':state['id'],'run_id':state.get('run_id'),
            'reference_sha256':sha256_file(reference) if reference.is_file() else None,
            'original_text':state.get('reviewed_original_text') or state.get('original_text'),
            'product':state.get('product'),'origins':origins}
        key=hashlib.sha256(json.dumps(binding,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if saved and saved.get('input_key')!=key:
            raise ValueError('미검토 수신 파일의 작업·원본·수집 영수증이 변경되어 이전 검토를 재사용할 수 없습니다.')
        if not saved:
            folder=self.folder(state['id'])/job['id'];folder.mkdir(parents=True,exist_ok=True)
            receipt=folder/'deferred-source-review.json'
            _atomic_json(receipt,{'input_key':key,'sources':{}})
            saved={'input_key':key,'path':str(receipt.resolve()),'sha256':sha256_file(receipt)}
            job['checkpoint']['deferred_source_review']=saved
            self.store.checkpoint(job,job['checkpoint'])
        receipt=Path(saved['path'])
        if not receipt.is_file() or sha256_file(receipt)!=saved['sha256']:
            raise ValueError('미검토 수신 영상의 검토 재개 체크포인트 파일이 변경되었습니다.')
        cache=json.loads(receipt.read_text(encoding='utf-8'))
        if cache.get('input_key')!=key:raise ValueError('미검토 수신 영상 검토의 입력 결속이 다릅니다.')
        from .source_batches import cached_records
        batch_cache=cached_records(self,job)
        restored=[]
        for source in records:
            cached=cache['sources'].get(source['sha256']) or batch_cache.get(source['sha256'])
            if cached and (cached.get('sha256')!=source['sha256']
                    or Path(cached.get('path') or '').resolve()!=Path(source['path']).resolve()
                    or canonical_video_key(cached.get('origin_url',''))!=canonical_video_key(source.get('origin_url',''))):
                raise ValueError('수신 영상의 검토 체크포인트가 실제 파일·URL과 다릅니다.')
            restored_source = copy.deepcopy(cached or source)
            # Routing provenance comes from the currently verified receipt,
            # even when review content is restored from an older batch.
            if source.get('deferred_download_origin'):
                restored_source['deferred_download_origin'] = copy.deepcopy(source['deferred_download_origin'])
            restored.append(restored_source)
        records=restored
        reviewed,completion=self._review_source_records(state,job,records,progress)
        if completion is None:
            completion={'reason':'completed_deferred_reviews','checked_sources':len(reviewed),
                'reviewed_sources':len(reviewed),'available_sources':len(records),'deferred_sources':len(records)-len(reviewed),
                'reviewed_source_sha256':[s['sha256'] for s in reviewed],
                'reviewed_origin_urls':[s['origin_url'] for s in reviewed if s.get('origin_url')]}
        return {'sources':reviewed,'source_search_manifest_path':origins[0]['manifest_path'],
            'source_policy':state.get('source_policy'),'searches':[], 'attempted_urls':[],
            'visual_review_only':True,'local_deferred_review':True,'deferred_review_origins':origins,
            'review_completion':completion,'round':job.get('payload',{}).get('round',state.get('source_acquisition',{}).get('round',0))}

    def _checkpoint_deferred_review(self,job,source):
        deferred=job.get('checkpoint',{}).get('deferred_source_review')
        identity=job.get('checkpoint',{}).get('identity_source_review')
        saved=(identity if identity and source['sha256'] in identity.get('source_sha256',[]) else
               deferred if deferred and source.get('deferred_download_origin')
               else job.get('checkpoint',{}).get('source_visual_review'))
        if not saved:return
        from .editing_adapter import _atomic_json
        previous=Path(saved['path'])
        data=json.loads(previous.read_text(encoding='utf-8'))
        if data.get('input_key')!=saved['input_key']:raise ValueError('미검토 영상 체크포인트 입력이 변경되었습니다.')
        path=(previous.parent/('source-review-'+job['claim_token']+'.json')
              if job.get('claim_token') else previous)
        data['sources'][source['sha256']]=copy.deepcopy(source)
        _atomic_json(path,data);saved.update(path=str(path.resolve()),sha256=sha256_file(path))
        batch=job.get('checkpoint',{}).get('source_batch_review')
        if batch and batch.get('input_key')==saved.get('input_key'):
            batch.update(path=saved['path'],sha256=saved['sha256'])
        self.store.checkpoint(job,job['checkpoint'])

    def _review_source_records(self, state, job, merged, progress):
        """Actual visual review is shared by automatic and manual collection."""
        job.setdefault('task_id', state['id'])
        from .source_finder import extract_frames, probe_video
        from .source_functional import review_function, needs_function_review, apply_function_review, reference_review_info
        from .source_overlay_review import POLICY as overlay_policy, needs_overlay_review, review_source_overlays
        from .source_review_withdrawals import apply_withdrawals
        from .source_presentation import (needs_presentation_review, review_presentation,
                                           apply_presentation_review, review_scope, ERROR_POLICY as presentation_policy)
        frames = extract_frames(Path(state['reference_video']), self.folder(state['id'])/'source-reference', max_frames=6)
        reference_info=None
        reviewed = []
        review_completion = None
        from .source_core_priority import enabled as core_enabled, kind as core_kind
        if core_enabled(run_policy(state)):
            # Confirmed core first; unknown candidates before already settled support.
            merged=sorted(merged,key=lambda s:{'core_product':0,'unverified':1,'related_product':2,'context':3}[core_kind(s,state)])
        for index, source in enumerate(merged, 1):
            if not Path(source['path']).is_file(): continue
            from .scene_requirements import clear_cached_review_errors
            clear_cached_review_errors(source)
            from .daily_quality import enabled as daily_quality_enabled
            if daily_quality_enabled(state) and not source.get('mask_review'):
                # A label or OCR miss cannot establish small creator handles are absent.
                source=copy.deepcopy(source)
                source['source_quality']='unknown'
            if not (source.get('video_meta') or {}).get('duration'):
                source['video_meta'] = probe_video(Path(source['path']))
            if 'reviewed_intervals' in source or source.get('mask_review'):
                source = apply_withdrawals(self.settings, source)
            if (source.get('source_interval_withdrawal') and not source.get('reviewed_intervals')):
                reviewed.append(source)
                self._checkpoint_deferred_review(job,source)
                continue
            if source.get('overlay_review_error') and not needs_overlay_review(source):
                # Function similarity cannot reverse a failed overlay approval.
                source['editing_eligible'] = False
                reviewed.append(source)
                self._checkpoint_deferred_review(job,source)
                continue
            if needs_overlay_review(source):
                progress(f'사용할 장면의 글자·블러 확인 {index}/{len(merged)}',90)
                try:
                    source = review_source_overlays(self.settings, source,
                        self.folder(state['id'])/'source-mask-checks'/source['sha256'][:20])
                    source.pop('overlay_review_error', None)
                    self._checkpoint_deferred_review(job,source)
                except Exception as exc:
                    from .model_service import ModelServiceUnavailable
                    if isinstance(exc,ModelServiceUnavailable):raise
                    # A failed visual approval keeps the source for diagnosis,
                    # but cannot count toward quotas or silently become clean.
                    source['editing_eligible'] = False
                    source['overlay_review_error'] = str(exc)[:500]
                    source['overlay_review_attempted_policy'] = overlay_policy
                    source['overlay_review_attempted_sha256'] = source['sha256']
                    from .source_review_status import failed_outcome
                    source['review_outcome']=failed_outcome('overlay',exc,source)
                    reviewed.append(source)
                    self._checkpoint_deferred_review(job,source)
                    continue
            if source.get('source_interval_withdrawal') and not source.get('reviewed_intervals'):
                reviewed.append(source)
                self._checkpoint_deferred_review(job,source)
                continue
            review = source.get('functional_review') or {}
            from .source_functional import needs_identity_reanalysis
            if needs_function_review(source) or needs_identity_reanalysis(state,source):
                if reference_info is None:reference_info=reference_review_info(state,self.folder(state['id']))
                progress(f'사용할 핵심·보조 장면 확인 {index}/{len(merged)}',94)
                mask_review = source.get('mask_review') or {}
                if mask_review.get('source_sha256') == source['sha256'] and source.get('reviewed_intervals'):
                    from .source_overlay_review import accepted_interval_frames
                    try:
                        candidate_frames = accepted_interval_frames(source)
                    except ValueError as exc:
                        # Keep the invalid receipt for diagnosis, never approval.
                        source = copy.deepcopy(source)
                        source['editing_eligible'] = False
                        source['overlay_review_error'] = str(exc)[:500]
                        source['overlay_review_attempted_policy'] = overlay_policy
                        source['overlay_review_attempted_sha256'] = source['sha256']
                        from .source_review_status import failed_outcome
                        source['review_outcome'] = failed_outcome('overlay', exc, source)
                        reviewed.append(source)
                        self._checkpoint_deferred_review(job, source)
                        continue
                else:
                    candidate_frames = extract_frames(Path(source['path']), self.folder(state['id'])/'source-checks'/source['sha256'][:20], max_frames=6)
                supplied_info={**reference_info,'candidate_provenance':{
                    'source_sha256':source['sha256'],'origin_url':source.get('origin_url',''),
                    'source_title':source.get('source_title',''),
                    'note':'untrusted source attribution, not the search query or verified performance'}}
                review = review_function(self.settings, SimpleNamespace(file_sha256=source['sha256']), frames, candidate_frames,supplied_info)
            apply_function_review(source, review)
            self._checkpoint_deferred_review(job,source)
            if source.get('editing_eligible'):
                if needs_presentation_review(source):
                    progress(f'세로 편집 화질·동작 보존 확인 {index}/{len(merged)}',96)
                    try:
                        receipt = review_presentation(self.settings, source,
                            self.folder(state['id'])/'source-portrait-checks'/source['sha256'][:20])
                        apply_presentation_review(source, receipt)
                        source.pop('presentation_review_error', None)
                    except Exception as exc:
                        from .model_service import ModelServiceUnavailable
                        if isinstance(exc,ModelServiceUnavailable):raise
                        source.update(editing_eligible=False, presentation_review_required=True,
                            presentation_review_error=str(exc)[:500],
                            presentation_review_error_policy=presentation_policy,
                            presentation_review_error_sha256=source['sha256'],
                            presentation_review_error_scope=copy.deepcopy(review_scope(source)))
                        from .source_review_status import failed_outcome
                        source['review_outcome']=failed_outcome('presentation',exc,source,scope=review_scope(source))
                elif source.get('presentation_review'):
                    apply_presentation_review(source, source['presentation_review'])
            reviewed.append(source)
            self._checkpoint_deferred_review(job,source)
            repair_batch = bool(job.get('payload', {}).get('daily_quality_repair'))
            if state.get('automation', {}).get('active') and (job['kind'] == 'collect_sources' or repair_batch):
                # Only completed task-scoped reviews can finish the automatic
                # acquisition goal. Extra downloads stay in the original
                # manifest/library; they are not approved for this edit.
                combined = [*state.get('sources', []), *reviewed] if repair_batch else reviewed
                goal = source_goal({**state, 'sources': combined}, self.settings.source_min_usable)
                min_new = 2 if not state.get('edit_id') else 3
                ready_batch = goal['ready'] and (not repair_batch or sum(1 for s in reviewed if editing_ready(s)) >= min_new)
                if ready_batch and core_enabled(run_policy(state)) and index<len(merged):
                    # Finish the already received small batch; do not discard its sixth useful core original.
                    continue
                if ready_batch:
                    review_completion = {'reason': 'quota_met', 'checked_sources': index,
                        'reviewed_sources': len(reviewed), 'available_sources': len(merged),
                        'deferred_sources': len(merged)-index, 'goal': goal}
                    review_completion.update(reviewed_source_sha256=[s['sha256'] for s in reviewed],
                        reviewed_origin_urls=[s['origin_url'] for s in reviewed if s.get('origin_url')],
                        deferred_source_sha256=[s['sha256'] for s in merged[index:]],
                        deferred_origin_urls=[s['origin_url'] for s in merged[index:] if s.get('origin_url')])
                    progress('사용 소스 검토 완료 · '+goal_message(goal), 100)
                    break
        return reviewed, review_completion

    def accept_source_round(self, state, job, result, db):
        if result.get('stopped'):
            return
        before = source_goal(state, self.settings.source_min_usable)
        old_by_hash = {s['sha256']:s for s in state['sources']}
        from .studio_store import uid
        for source in result['sources']:
            old = old_by_hash.get(source['sha256'])
            if old:
                denial = copy.deepcopy(old.get('manual_usage_review')) if (
                    old.get('manual_usage_review') or {}).get('editing_eligible') is False else None
                # Preserve stable source IDs used by existing rendered plans.
                old.update({k:v for k,v in source.items() if k != 'id'})
                from .scene_requirements import clear_resolved_errors
                clear_resolved_errors(old,source)
                # An in-flight review may have started before a manual exclusion.
                # Its old snapshot cannot undo the current task-scoped denial.
                if denial is not None:
                    old['manual_usage_review'] = denial
                    old['editing_eligible']=False
            else:
                source['id'] = uid('source-'); state['sources'].append(source)
        record = state.setdefault('source_acquisition', {})
        record['round'] = max(record.get('round',0), result['round']+1)
        from .source_search.strategy import merge_history, consumed_scope, ACCESS_WAITS, stop_diagnostics
        from .source_coverage import search_scope_for_state
        scope=search_scope_for_state(state)
        searches = [{**row,**({'run_id':state.get('run_id'),'search_context':scope}
            if 'run_id' not in row and 'search_context' not in row else {})} for row in result.get('searches', [])]
        record['queries'] = merge_history(record.get('queries', []), searches)
        record['urls'] = list(dict.fromkeys([*record.get('urls',[]), *result.get('attempted_urls',[])]))
        record['inspected_urls'] = list(dict.fromkeys([*record.get('inspected_urls', []), *result.get('inspected_urls', [])]))
        record.setdefault('rounds', []).append({'job_id':job['id'], 'round':result['round'],
            'searches':copy.deepcopy(searches),
            'run_id':job.get('payload',{}).get('run_id',state.get('run_id')),
            'manifest_path':result['source_search_manifest_path'], 'source_policy':result.get('source_policy'),
            'platform_outcomes':result.get('platform_outcomes', {}),
            'review_completion':result.get('review_completion')})
        resolve_diversity_recovery(state)
        goal = source_goal(state, self.settings.source_min_usable)
        record['rounds'][-1]['goal'] = copy.deepcopy(goal)
        if goal.get('core_target'):
            record['rounds'][-1]['core_priority_metrics']={
                'core_before':before.get('core_parent_count',0),'core_after':goal['core_parent_count'],
                'core_target':goal['core_target'],'completion_mode':goal['completion_mode'],
                'phase':'support' if any(r.get('search_purpose')=='support' for r in searches) else 'core',
                'actual_search_scopes':sum(bool(consumed_scope(r)) for r in searches),
                'execution_seconds_including_model_wait':result.get('execution_seconds_including_model_wait'),
                'timing_note':'Round wall time; not additive with concurrent script/voice or job queue waits'}
        def score(g):
            if g.get('policy_version',0)>=5:
                counts=g.get('search_coverage',{})
                return [g.get('related_parent_count',g['count']),g.get('core_parent_count',int(g['core_ready'])),
                        counts.get('en',{}).get('count',0),counts.get('zh',{}).get('count',0)]
            if 'required_seconds' in g:
                return [min(g['usable_seconds'], g['required_seconds']),
                        min(g['core_seconds'], g['core_required_seconds'])]
            return [min(g['count'], g['target']), int(g['core_ready']), *[min(v['usable'], v['target'])
                for _, v in sorted(g.get('platform_targets', {}).items())]]
        prior = record.get('progress_high_water', score(before))
        if record.get('progress_policy_version') != goal['policy_version']:
            prior = score(before)
            record['progress_policy_version'] = goal['policy_version']
        current = score(goal)
        improved = any(c > p for c, p in zip(current, prior))
        record['progress_high_water'] = [max(c, p) for c, p in zip(current, prior)]
        searches = result.get('searches', [])
        # Authentication, transfer throttling and unavailable browser/service
        # are not evidence that the remaining product footage cannot be found.
        waits = [s for s in [*searches, *result.get('access_waits', [])] if s.get('status') in ACCESS_WAITS]
        content_attempt = bool(result.get('visual_review_only') or result.get('attempted_urls')
            or any(consumed_scope(s) or s.get('provider') in
                {'operator-shortlist','deferred-candidates','local-cache','source-library'}
                and s.get('candidates') and not waits for s in searches))
        if not result.get('visual_review_only') and content_attempt:
            record['bounded_rounds'] = record.get('bounded_rounds', 0) + 1
        if improved:
            record['no_progress_rounds'] = 0
        elif content_attempt:
            record['no_progress_rounds'] = record.get('no_progress_rounds', 0) + 1
        record['next_attempt_at'] = (max(time.time(),record.get('next_attempt_at',0))
            if result.get('local_interval_recovery') else time.time()+min(600,max(30,self.settings.source_browser_search_interval)))
        state.update(source_goal=goal, source_search_manifest_path=result['source_search_manifest_path'])
        if not state.get('product_override'):
            from .studio_automation import refresh_resolved_subject
            from .reference_context import post_caption
            manifest_file = Path(result.get('source_search_manifest_path') or '')
            manifest_data = json.loads(manifest_file.read_text(encoding='utf-8')) if manifest_file.is_file() else {}
            caption=post_caption(self.settings,state) if getattr(self.settings,'db_path',None) else state.get('original_caption','')
            manifest_data = {**manifest_data, 'caption':caption or manifest_data.get('caption','')}
            refresh_resolved_subject(state,manifest_data)
            goal=source_goal(state,self.settings.source_min_usable)
            state['source_goal']=goal
        state['source_search'] = {'status':'done' if goal['ready'] else 'queued',
            'message':f"{'소스 준비 완료' if goal['ready'] else '다른 방법으로 자동 추가 수집'} · "+goal_message(goal), 'progress':100 if goal['ready'] else 0}
        if goal['ready']:
            record.pop('hold', None)
            record.pop('waiting', None)
        elif waits and not improved:
            record['waiting'] = {'at':time.time(), 'searches':copy.deepcopy(waits),
                'diagnostics':stop_diagnostics(searches, goal, result.get('platform_outcomes'))}
            retry_at = max((s.get('retry_at', 0) or 0 for s in waits), default=0)
            record['next_attempt_at'] = max(record['next_attempt_at'], retry_at)
            state['source_search'].update(status='queued', message='소스 접근·서비스 재개 대기 · '
                + ' / '.join(stop_diagnostics(searches, goal, result.get('platform_outcomes'))))
        elif not result.get('visual_review_only') and 'searches' in result and not improved and not content_attempt:
            record.pop('waiting', None)
            self._stop_source_collection(state, db, 'strategy_exhausted', stop_diagnostics(searches, goal, result.get('platform_outcomes')))
        else:
            record.pop('waiting', None)
        # Unsuccessful rounds remain diagnostic history. A finite frozen query
        # pool, consumed scope ledger and inspected URL ledger prevent repeats;
        # a count cannot establish that a different unused scope will also fail.
        self.ensure_source_collection(state, db, finishing=job['id'])
        if job['payload'].get('daily_quality_repair') and goal['ready']:
            # Locally received targeted clips still use the normal bounded
            # reviewers. Resume editing only after their real review finishes.
            from .scene_requirements import coverage_current
            state['daily_quality']['pending']='reedit' if coverage_current(state) else 'recollect'
        # A collection result must not automatically repeat a failed voice/model
        # request. That failure keeps its own bounded retry policy.
        if not state.get('error') and state.get('status') != 'completed':
            self._advance_auto(state, db)
