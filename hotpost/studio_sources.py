"""Persistent source acquisition independent of script and voice production."""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from .source_quality import editing_ready, sha256_file, frame_duplicate
from .source_urls import canonical_video_key
from .source_policy import run_policy, source_platform, goal_message, adopt_policy
from .source_coverage import coverage_goal, reviewed_core, footage_coordinates
from .studio_store import change_claimed

PLATFORMS = {'tiktok':'틱톡','douyin':'더우인','xiaohongshu':'샤오홍슈',
             'instagram':'인스타그램','youtube':'유튜브','youtu.be':'유튜브','bilibili':'빌리빌리','pexels':'Pexels','lazada':'Lazada'}


def platform_name(source):
    host = urlparse(source.get('origin_url', '')).hostname or ''
    return next((name for key, name in PLATFORMS.items() if key in host), host or '기타')


def unique_sources(sources):
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
        if frames and not related_parent and any(frame_duplicate(frames, [int(v, 16) for v in prior.get('frame_hashes') or []]) for prior in result):
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
    sources = unique_sources([s for s in state.get('sources', [])
                              if Path(s.get('path') or '').is_file() and editing_ready(s)])
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
        result['ready'] = bool(sources) and coverage['duration_ready'] and coverage['core_ready']
        original_key=lambda s: (footage_coordinates(s) or (('footage',s.get('sha256') or s['id']),0,1))[0]
        result['original_count']=len({original_key(s) for s in sources})
        result['platform_preferences'] = {p: {'target': preferred,
            'usable': len({original_key(s) for s in sources if source_platform(s)==p}), 'required': False}
            for p, preferred in policy.get('platform_preferences', {}).items()}
    return result


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
        if not auto.get('active') or state.get('status') == 'completed' or not state.get('original_text'):
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
        from .source_access_preflight import SourceAccessWaiting
        if isinstance(error, SourceAccessWaiting):
            self.store.defer(job, str(error), max(1,error.retry_at-time.time()), waiting=True, waiting_status='source_wait')
            return
        from .studio_workflow import transient
        if transient(error) and job['checkpoint'].get('auto_retries',0) < 2:
            self.store.defer(job, str(error), 60)
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
        progress.source_attempt_created = created
        progress.source_worker_checkpoint = worker
        progress.source_worker_settled = lambda path: worker(path, True)
        return progress

    def _restore_source_attempt_history(self, state, job):
        from .source_pause_receipts import verified_receipt, merge_receipt, SourceReceiptWaiting
        receipts=[]
        for entry in job.get('checkpoint', {}).get('source_attempts', []):
            if not entry.get('receipt_path'):
                self._record_source_receipt_wait(job, '수집 중단 미정착 기록 확인 대기 · 자동 재검색 보류')
                raise SourceReceiptWaiting('수집 중단 미정착 기록 확인 대기 · 자동 재검색 보류')
            try:receipt=verified_receipt(self.settings.source_dir, entry, state, job)
            except SourceReceiptWaiting as exc:
                self._record_source_receipt_wait(job, str(exc));raise
            receipts.append({**receipt, 'receipt_path':entry['receipt_path'], 'receipt_sha256':entry['receipt_sha256']})
        if not receipts:return state
        def restore(s, db):
            record=s.setdefault('source_acquisition', {})
            for receipt in receipts:merge_receipt(record,receipt)
            record.pop('receipt_wait',None)
        return change_claimed(self.store, job, restore)

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
            try:receipt=snapshot(self.settings.source_dir,entry,state,job)
            except SourceReceiptWaiting as exc:
                self._record_source_receipt_wait(job,str(exc));raise
            path=Path(entry['manifest_path']).parent/'interrupted-execution-receipt.json'
            if path.is_file():
                if json.loads(path.read_text(encoding='utf-8'))!=receipt:
                    raise SourceReceiptWaiting('기존 수집 중단 영수증과 현재 기록이 달라 확인 대기')
            else:_atomic_json(path,receipt)
            entry.update(receipt_path=str(path.resolve()),receipt_sha256=sha(path))
            self.store.checkpoint(job,job['checkpoint'])
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
            self._preserve_source_attempt_history(state, job)
            access_wait = isinstance(exc, SourceAccessWaiting)
            raise
        finally:
            if not access_wait and (result is None or not result.get('stopped')):
                elapsed = max(0, time.monotonic()-started)
                def record_execution(s, db):
                    record = s.setdefault('source_acquisition', {})
                    record['execution_seconds'] = record.get('execution_seconds', 0)+elapsed
                change_claimed(self.store, job, record_execution)

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
        self._bind_source_attempt_progress(state,job,progress)
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
        if acquisition.get('hold'):
            return {'stopped':True}
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
            pending = [s for s in state.get('sources', [])
                       if Path(s['path']).is_file() and (not s.get('overlay_review_error') or needs_overlay_review(s))
                       and (needs_overlay_review(s) or needs_pending_presentation_review(s) or s['sha256'] in resolved_hashes)]
            if pending:
                # Finish the missing local review before requesting more files.
                # A completed local review participates in the no-progress check.
                visual_review_only = True
                manifest_path = state.get('source_search_manifest_path') or state['manifest_path']
                result = {'candidates':[], 'source_policy':state.get('source_policy'),
                          'search_audit':[{'provider':'saved-overlay-review','status':'results',
                                           'query':'','candidates':len(pending)}]}
            else:
                ready_routes = (self._source_access_gate(state,job,acquisition.get('queries',[]))
                    if acquisition.get('waiting') or acquisition.get('rounds') else None)
                change_claimed(self.store,job,lambda s,db:s.setdefault('source_acquisition',{}).setdefault('started_at',time.time()))
                result = find_sources(self.settings, state['shortcode'], progress,
                    search_request=state.get('source_search_brief', ''),
                    search_round=job['payload'].get('round',0),
                    previous_searches=acquisition.get('queries', []),
                    exclude_urls=[*acquisition.get('urls', []), *acquisition.get('inspected_urls', [])],
                    search_context={'completed_rounds':acquisition.get('bounded_rounds',0),
                                    'rounds':acquisition.get('rounds',[]),
                                    'expected_reference_sha256':(sha256_file(Path(state['reference_video']))
                                        if state.get('reference_video') and Path(state['reference_video']).is_file() else None),
                                    'ready_routes':ready_routes})
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
        # Review saved sources too; previously downloaded context footage stays
        # usable, while a high appearance score alone cannot assert core action.
        merged = unique_sources([*copy.deepcopy(state['sources']), *incoming])
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

    def _source_access_gate(self,state,job,history=None):
        from .studio_pause import check_paused
        from .source_access_preflight import check_access, SourceAccessWaiting
        from .source_preparation import preflight_preparation
        check_paused(self.store,job)
        if not self.settings.source_browser_search:
            return None  # Indexed routes keep their own request/access gates.
        try:
            plan,frames=preflight_preparation(self.settings,state,job)
        except (ValueError,OSError,KeyError) as exc:
            raise SourceAccessWaiting('소스 준비 근거 보존 대기 · '+str(exc)) from exc
        ready=check_access(self.settings,state,job,history=history,plan=plan,frames=frames)
        check_paused(self.store,job)
        self.store.checkpoint(job,job['checkpoint'])
        return ready

    def _review_pending_local_sources(self,state,job,progress):
        from .source_overlay_review import needs_overlay_review
        from .source_presentation import needs_pending_presentation_review
        pending=[s for s in state.get('sources',[]) if Path(s.get('path') or '__missing__').is_file()
                 and (not s.get('overlay_review_error') or needs_overlay_review(s))
                 and (needs_overlay_review(s) or needs_pending_presentation_review(s))]
        manifest=state.get('source_search_manifest_path') or state.get('manifest_path')
        if not pending or not manifest:return None
        reviewed,completion=self._review_source_records(state,job,copy.deepcopy(pending),progress)
        return {'sources':reviewed,'source_search_manifest_path':manifest,'source_policy':state.get('source_policy'),
                'searches':[],'attempted_urls':[],'inspected_urls':[],'visual_review_only':True,
                'local_deferred_review':True,'review_completion':completion}

    def _deferred_download_records(self,state):
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
            if interrupted:
                from .source_pause_receipts import verified_receipt
                # The immutable receipt and current task/reference must still
                # bind the partial, before any received file enters local review.
                owned={**receipt,'workers':[{'path':w['path'],'settled':True}
                    for w in receipt.get('worker_checkpoints',[])]}
                verified_receipt(self.settings.source_dir,owned,state,
                    {'id':receipt['studio_job_id'],'payload':{'run_id':receipt.get('run_id'),
                     'request':receipt.get('source_request','')}})
            data=json.loads(manifest.read_text(encoding='utf-8'))
            if data.get('shortcode') and data['shortcode']!=state.get('shortcode'):continue
            origins.append({'manifest_path':str(manifest.resolve()),'manifest_sha256':sha256_file(manifest),
                            'round':receipt.get('round'),'job_id':receipt.get('job_id')})
            selected=[]
            for candidate in data.get('candidates',[]):
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
                rows=self._source_records(selected,manifest)
                for source in rows:
                    source['deferred_download_origin']={'manifest_path':str(manifest.resolve()),
                        'manifest_sha256':sha256_file(manifest),'round':receipt.get('round'),'job_id':receipt.get('job_id')}
                records.extend(rows)
        return records,origins

    def _review_deferred_downloads(self,state,job,progress):
        records,origins=self._deferred_download_records(state)
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
        restored=[]
        for source in records:
            cached=cache['sources'].get(source['sha256'])
            if cached and (cached.get('sha256')!=source['sha256']
                    or Path(cached.get('path') or '').resolve()!=Path(source['path']).resolve()
                    or canonical_video_key(cached.get('origin_url',''))!=canonical_video_key(source.get('origin_url',''))):
                raise ValueError('수신 영상의 검토 체크포인트가 실제 파일·URL과 다릅니다.')
            restored.append(copy.deepcopy(cached or source))
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
        saved=(deferred if deferred and source.get('deferred_download_origin')
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
                    reviewed.append(source)
                    self._checkpoint_deferred_review(job,source)
                    continue
            if source.get('source_interval_withdrawal') and not source.get('reviewed_intervals'):
                reviewed.append(source)
                self._checkpoint_deferred_review(job,source)
                continue
            review = source.get('functional_review') or {}
            if needs_function_review(source):
                if reference_info is None:reference_info=reference_review_info(state,self.folder(state['id']))
                progress(f'사용할 핵심·보조 장면 확인 {index}/{len(merged)}',94)
                mask_review = source.get('mask_review') or {}
                if mask_review.get('source_sha256') == source['sha256'] and source.get('reviewed_intervals'):
                    candidate_frames = [{'path':f['path'],'source_timestamp':f['source_timestamp']} for f in mask_review.get('evidence_frames', [])
                        if any(w['source_start'] <= f['source_timestamp'] < w['source_end']
                               for w in source['reviewed_intervals'])]
                else:
                    candidate_frames = extract_frames(Path(source['path']), self.folder(state['id'])/'source-checks'/source['sha256'][:20], max_frames=6)
                review = review_function(self.settings, SimpleNamespace(file_sha256=source['sha256']), frames, candidate_frames,reference_info)
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
                elif source.get('presentation_review'):
                    apply_presentation_review(source, source['presentation_review'])
            reviewed.append(source)
            self._checkpoint_deferred_review(job,source)
            if state.get('automation', {}).get('active') and job['kind'] == 'collect_sources':
                # Only completed task-scoped reviews can finish the automatic
                # acquisition goal. Extra downloads stay in the original
                # manifest/library; they are not approved for this edit.
                goal = source_goal({**state, 'sources': reviewed}, self.settings.source_min_usable)
                if goal['ready']:
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
        record['queries'] = merge_history(record.get('queries', []), result.get('searches', []))
        record['urls'] = list(dict.fromkeys([*record.get('urls',[]), *result.get('attempted_urls',[])]))
        record['inspected_urls'] = list(dict.fromkeys([*record.get('inspected_urls', []), *result.get('inspected_urls', [])]))
        record.setdefault('rounds', []).append({'job_id':job['id'], 'round':result['round'],
            'run_id':job.get('payload',{}).get('run_id',state.get('run_id')),
            'manifest_path':result['source_search_manifest_path'], 'source_policy':result.get('source_policy'),
            'platform_outcomes':result.get('platform_outcomes', {}),
            'review_completion':result.get('review_completion')})
        goal = source_goal(state, self.settings.source_min_usable)
        record['rounds'][-1]['goal'] = copy.deepcopy(goal)
        def score(g):
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
        record['next_attempt_at'] = time.time()+min(600,max(30,self.settings.source_browser_search_interval))
        state.update(source_goal=goal, source_search_manifest_path=result['source_search_manifest_path'])
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
