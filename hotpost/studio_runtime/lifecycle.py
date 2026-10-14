"""Worker lanes, completion handling, and legacy automatic advancement."""
from __future__ import annotations

from ..studio_store import change_claimed

import time
from pathlib import Path

from ..studio_store import Conflict
from ..studio_workflow import enabled, init_run, snapshot, current_run, capcut_running, transient
from .common import digest, selected


def repair_render_accounting(state,job,result):
    """Accepted render history, rather than a queued lane name, defines a repair."""
    prior=[e['id'] for e in state.get('edits',[]) if e.get('id') and not e.get('no_render')
           and e['id']!=result.get('id')]
    quality=state.get('daily_quality',{})
    before=quality.get('repair_round',0)
    charge=1 if prior else 0
    return {'policy':'actual-prior-render-v1','job_id':job.get('id'),
        'job_kind':job.get('kind'),'edit_id':result.get('id'),'prior_edit_ids':prior,
        'classification':'quality_repair' if prior else 'initial_baseline',
        'repair_round_before':before,'repair_charge':charge,'repair_round_after':before+charge,
        'max_repairs':quality.get('max_repairs',3)}


def claimed_quality_permit(store, job, stage):
    """The normal worker and explicit recovery share the same method boundary."""
    from ..quality_progress import permit
    allowed = []
    change_claimed(store, job, lambda s, db: allowed.append(permit(s, stage, reserve=True, job_id=job['id'])))
    return allowed[0]


class LifecycleMixin:
    def _resume_claimed_retry_phase(self,state,job):
        phases={'quality_review':('quality_review','완성본 품질 검토 다시 진행 중'),
                'quality_reedit':('editing','장면·표지 검토 및 편집 다시 진행 중'),
                'refresh_sources':('source_wait','소스 수집·검토 다시 진행 중'),
                'collect_sources':('source_wait','소스 수집·검토 다시 진행 중')}
        if state.get('status')!='retry_wait' or job['kind'] not in phases:return state
        status,message=phases[job['kind']]
        def resume(current,db):
            if current.get('status')=='retry_wait':current.update(status=status,message=message)
        return change_claimed(self.store, job,resume)

    def _watch_top(self):
        from ..studio_automation import enqueue_latest
        while not self.stop.is_set():
            try:
                enqueue_latest(self.settings)
            except (OSError, ValueError, KeyError):
                pass  # A report may not exist yet; the collection hook also enqueues.
            self.stop.wait(30)

    def _worker(self, lane=None):
        while not self.stop.is_set():
            job = self.store.claim(lane)
            if not job:
                self.stop.wait(.6); continue
            try:
                state = self.store.get(job["task_id"])
                from ..photo_reference import assert_creation_enabled
                assert_creation_enabled(self.settings,state,job['kind'])
                if enabled(state) and not current_run(state):
                    state = change_claimed(self.store, job, lambda s, db: init_run(s))
                if enabled(state) and state.get('pending_reproduction') and job['kind'] not in {'collect_sources','refresh_sources','proposal','suggest_edit'}:
                    self.store.finish(job, {}, lambda s, db, r: self.activate_reproduction(s, db))
                    continue
                if job['kind'] in {'register', 'export'} and not job['payload'].get('launch') and capcut_running():
                    edit = next((e for e in state['edits'] if e['id'] == job['payload'].get('edit_id')), {})
                    portable_ready = Path(edit.get('portable_draft_path') or '__missing__').joinpath('draft_content.json').is_file()
                    if job['kind'] == 'register' and enabled(state) and portable_ready:
                        # A user's open editor must not block an already rendered
                        # automatic MP4. Keep the portable draft without claiming
                        # it was registered in the running native application.
                        self.store.finish(job, {'registration_deferred': True,
                            'registration_note': 'CapCut 사용 중 · 편집 가능한 프로젝트는 보존하고 MP4를 먼저 내보냅니다.'},
                            lambda s, db, r: self._accept(s, job, r, db))
                        continue
                    registered = (job['kind'] == 'export' and any(
                        e['id'] == job['payload'].get('edit_id') and (e.get('draft_path')
                        or (e.get('registration_deferred') and portable_ready)) for e in state['edits']))
                    if registered:
                        # The editable draft is already registered. Exporting
                        # its saved plan on the web path does not touch an open
                        # CapCut session or any user edits in that draft.
                        job['checkpoint'].setdefault('native_export_unavailable',
                            'CapCut 창이 열려 있어 저장된 장면·음성·자막으로 웹 내보내기')
                        self.store.checkpoint(job, job['checkpoint'])
                    else:
                        self.store.defer(job, 'CapCut 종료 대기 · 저장하고 앱을 닫으면 자동으로 이어집니다', 15, waiting=True)
                        continue
                payload = job["payload"]
                if payload.get('daily_quality_repair') or payload.get('quality_rewrite'):
                    if state.get('automation',{}).get('paused_by_user'):
                        self.store.defer(job,'사용자 중지 유지',0,waiting=True)
                        continue
                    if state.get('daily_quality',{}).get('pending') in {'exhausted','failed'}:
                        self.store.finish(job,{'no_render':True,'historical_quality_stop':True},lambda *_:None)
                        continue
                if "script_id" in payload and payload["script_id"] != state["script_id"]:
                    self.store.finish(job, {}, lambda *_: None); continue
                from ..daily_quality import rewrite_repair_context
                context=rewrite_repair_context(state,payload) if job['kind']=='edit' else None
                if context and not payload.get('quality_repair'):
                    from ..scene_requirements import repair_render_signature
                    payload.update(quality_repair=True, parent_edit_id=context['parent_edit_id'],
                                   repair_input_signature=repair_render_signature(state))
                    self.store.checkpoint(job,job['checkpoint'])
                if job['kind']=='quality_reedit' or payload.get('quality_repair'):
                    quality=state.get('daily_quality',{})
                    from ..quality_progress import permit, QualityProgressHold
                    allowed=claimed_quality_permit(self.store,job,'reedit')
                    if not allowed:
                        latest=self.store.get(state['id'])
                        if latest.get('automation',{}).get('paused_by_user'):
                            self.store.defer(job,'사용자 중지 유지',0,waiting=True)
                        else:self.store.finish(job,{'no_render':True,'quality_method_held':True},lambda *_:None)
                        continue
                    state=self.store.get(state['id'])
                    from ..scene_requirements import repair_render_signature,REPAIR_SIGNATURE_POLICY
                    frozen_signature=repair_render_signature(state)
                    previous=payload.get('repair_input_signature')
                    if previous and previous!=frozen_signature:
                        payload['previous_repair_input_signature']=previous
                        job['checkpoint']['previous_repair_input_signature']=previous
                    payload['repair_input_signature']=frozen_signature
                    payload['repair_signature_policy']=REPAIR_SIGNATURE_POLICY
                    job['checkpoint']['repair_input_signature']=frozen_signature
                    job['checkpoint']['repair_signature_policy']=REPAIR_SIGNATURE_POLICY
                    self.store.checkpoint(job,job['checkpoint'])
                state=self._resume_claimed_retry_phase(state,job)
                if payload.get('quality_rewrite'):
                    from ..quality_progress import permit, QualityProgressHold
                    allowed=claimed_quality_permit(self.store,job,'rewrite')
                    if not allowed:raise QualityProgressHold('동일 사실 보완 방법 차단 · 새 근거 대기')
                    state=self.store.get(state['id'])
                result = getattr(self, "_" + job["kind"])(state, job)
                if job['kind']=='quality_reedit' or payload.get('quality_repair'):
                    result['repair_input_signature']=payload['repair_input_signature']
                    result['repair_signature_policy']=REPAIR_SIGNATURE_POLICY
                    if payload.get('previous_repair_input_signature'):
                        result['previous_repair_input_signature']=payload['previous_repair_input_signature']
                self.store.finish(job, result, lambda s, db, r: self._accept(s, job, r, db))
            except Exception as exc:
                from ..studio_pause import StudioPaused
                if isinstance(exc, StudioPaused):
                    self.store.defer(job, str(exc), 0, waiting=True)
                    continue
                from ..source_access_preflight import SourceAccessWaiting
                if isinstance(exc,SourceAccessWaiting):
                    self.store.defer(job,str(exc),max(1,exc.retry_at-time.time()),
                                     waiting=True,waiting_status='source_wait')
                    continue
                from ..studio_store import StaleClaim
                if isinstance(exc, StaleClaim):
                    continue
                from ..photo_reference import PhotoProductionDisabled
                if isinstance(exc,PhotoProductionDisabled):
                    self.store.fail(job,exc)
                    continue  # A user production setting is not a quality failure.
                from ..collectors.base import CollectionBlocked
                from ..daily_quality import QualitySceneGap, enabled as daily_quality_enabled
                from ..model_service import ModelServiceUnavailable
                from ..source_browser_runtime import BrowserBusy
                from ..scene_narration_prepare import NarrationContextHold
                from ..quality_progress import QualityProgressHold, hold, finish_attempt
                if isinstance(exc,QualityProgressHold):
                    if exc.waiting or self.store.get(job['task_id']).get('automation',{}).get('paused_by_user'):
                        self.store.defer(job,str(exc),0,waiting=True)
                        continue
                    def stop_method(s,db,r):
                        finish_attempt(s,job,failed=True)
                        hold(s,str(exc),'stop_method')
                    self.store.finish(job,{'no_render':True,'quality_method_held':True},stop_method)
                elif isinstance(exc,NarrationContextHold):
                    self.handle_narration_context_hold(job,exc)
                elif isinstance(exc,QualitySceneGap):
                    self.handle_daily_scene_gap(job,exc)
                elif isinstance(exc, ModelServiceUnavailable):
                    job['checkpoint']['retry_requested']=True
                    if exc.attempted:
                        job['checkpoint']['service_retries'] = job['checkpoint'].get('service_retries',0)+1
                    # Shared capacity/Retry-After gates control actual attempts.
                    # The cumulative diagnostic counter is not a content limit.
                    self.store.defer(job, str(exc), max(1,exc.retry_at-time.time()),
                                     waiting=True, waiting_status='retry_wait')
                elif isinstance(exc,BrowserBusy):
                    self.store.defer(job,'수집용 브라우저 사용 종료 대기',30,
                                     waiting=True,waiting_status='retry_wait')
                elif isinstance(exc, CollectionBlocked) and exc.reason == 'profile_busy':
                    # Daily collection owns this same saved login profile. Waiting
                    # for its lease is not a failed download or an auth retry.
                    self.store.defer(job, 'Instagram 브라우저 사용 종료 대기 · 비면 자동으로 이어집니다',
                                     30, waiting=True, waiting_status='retry_wait')
                elif job['kind'] == 'collect_sources':
                    self.handle_source_error(job, exc)
                elif enabled(self.store.get(job['task_id'])) and transient(exc) and job['checkpoint'].get('auto_retries', 0) < 2:
                    self.store.defer(job, str(exc), 15 * (job['checkpoint'].get('auto_retries', 0)+1))
                else:
                    if self.store.fail(job, exc) is False:
                        continue
                    state = self.store.get(job['task_id'])
                    if daily_quality_enabled(state) and job['kind'] in {'quality_review','quality_reedit','refresh_sources','rewrite','edit'}:
                        self.fail_daily_quality(job,exc)
                    if enabled(state) and state.get('pending_reproduction'):
                        change_claimed(self.store, job, lambda s, db: self.activate_reproduction(s, db))

    def handle_narration_context_hold(self,job,error):
        """An ambiguous old/new narration mapping is not another source search."""
        if self.store.fail(job,error) is False:
            return
        def hold(state,db):
            quality=state.setdefault('daily_quality',{})
            quality.update(status='needs_attention',pending='scene_wait',
                narration_context_hold={'job_id':job['id'],'reason':str(error)[:700],
                    'issues':getattr(error,'issues',[]),'at':time.time()})
            state.setdefault('automation',{}).update(active=False,stage='quality_review')
            state.update(status='attention',error=str(error)[:700],
                message='새 대본과 이전 시각 문제의 대응 불명확 · 결과 보존, 자동 수집·편집 보류')
            state['source_search']={'status':'done','progress':100,'scene_wait':True,
                'message':'대본 문맥 연결 보류 · 같은 조건의 외부 검색을 반복하지 않음'}
            self.store.event(db,state['id'],'narration_context_held',{'job_id':job['id'],
                'reason':str(error)[:700],'no_render':True,'no_external_search':True})
        change_claimed(self.store, job,hold)

    def _accept(self, state, job, result, db=None):
        kind, p = job["kind"], job["payload"]
        if kind == 'quality_review':
            self.accept_daily_quality(state,job,result,db)
            snapshot(state)
            return
        if kind == 'collect_sources':
            self.accept_source_round(state, job, result, db)
            if (current_run(state) or {}).get('status') != 'completed':
                snapshot(state)
            return
        if kind == 'suggest_edit':
            if result['base_edit_id'] != state.get('edit_id'):
                raise Conflict('수정안 준비 중 새 편집본이 만들어졌습니다. 새 영상에서 다시 요청하세요.')
            if self.feedback_hash(state.get('feedback', {})) != result['feedback_hash']:
                raise Conflict('요청 후 피드백이 변경되었습니다. 수정 요청을 다시 보내세요.')
            feedback = state.setdefault('feedback', {})
            feedback['base_edit_id'] = result['base_edit_id']
            changes = [{k:v for k,v in c.items() if k in {'beat_id','emphasis'}} for c in result['changes'] if 'emphasis' in c]
            if changes: feedback.pop('caption_only', None)
            by_id = {c['beat_id']:c for c in feedback.get('changes', [])}
            for c in changes: by_id.setdefault(c['beat_id'], {}).update(c)
            if by_id: feedback['changes'] = list(by_id.values())
            state['candidate_requests'] = [c['beat_id'] for c in result['changes'] if c.get('choose_candidates')]
            state['feedback_message'] = result['summary']
            state['feedback_revision'] = state.get('feedback_revision',0)+1
            return
        if kind == 'refresh_sources':
            if p.get('daily_quality_repair') and job.get('id') in state.get('daily_quality',{}).get('accepted_source_jobs',[]):
                return
            from ..source_search.strategy import merge_history, restore_history
            record = state.setdefault('source_acquisition', {})
            restore_history(record)
            record['queries'] = merge_history(record.get('queries', []), result.get('searches', []))
            record['urls'] = list(dict.fromkeys([*record.get('urls', []), *result.get('attempted_urls', [])]))
            record['inspected_urls'] = list(dict.fromkeys([*record.get('inspected_urls', []), *result.get('inspected_urls', [])]))
            # Append assets; existing renders and source references stay playable.
            hashes = {s['sha256'] for s in state['sources']}
            urls = {s.get('origin_url') for s in state['sources'] if s.get('origin_url')}
            added = [s for s in result['sources'] if s['sha256'] not in hashes and s.get('origin_url') not in urls]
            from ..scene_requirements import merge_sources
            state['sources']=merge_sources(state['sources'],result['sources'])
            from ..studio_sources import source_goal
            state['source_goal']=source_goal(state,self.settings.source_min_usable)
            state['source_search_manifest_path'] = result['source_search_manifest_path']
            local_context=result.get('local_narration_preparation') is True
            local_review=result.get('local_deferred_review') is True or result.get('visual_review_only') is True
            from ..source_outcomes import SKIPPED
            searches=result.get('searches',[])
            outcomes=result.get('platform_outcomes',{})
            external_attempted=(not local_context and not local_review and (
                any(r.get('requests') or (r.get('query') and r.get('status') not in SKIPPED) for r in searches)
                or any(v.get('search_attempts',0) or v.get('download_attempts',0) for v in outcomes.values())))
            history_key=('local_narration_preparations' if local_context else
                         'local_source_reviews' if local_review else 'rounds')
            state.setdefault('source_acquisition', {}).setdefault(history_key, []).append({
                'job_id':job.get('id'), 'manifest_path':result['source_search_manifest_path'],
                'source_policy':result.get('source_policy'), 'platform_outcomes':result.get('platform_outcomes', {}),
                'external_search_attempted':bool(external_attempted),
                'local_deferred_review':local_review,
                'review_completion':result.get('review_completion'),
                'deferred_review_origins':result.get('deferred_review_origins',[])})
            state['source_search'] = {'status': 'done', 'message': f'추가 수집 완료 · 신규 {len(added)}개 / 보유 {len(state["sources"])}개', 'progress': 100}
            if local_context:state['source_search']['message']='새 대본 분석·필수 장면 검토 완료 · 외부 검색 없음'
            elif local_review:state['source_search']['message']=f'기존 수신파일 검토 완료 · 신규 {len(added)}개 / 외부 검색 없음'
            goal = result.get('platform_targets', {}).get('tiktok')
            if goal:
                state['source_search']['message'] += f" · TikTok {goal['usable']}/{goal['target']}개"
                if goal['status'] != 'met':
                    state['source_search']['message'] += ' · 목표 미달/검색 미완료 (검색 기록 확인)'
            if p.get('daily_quality_repair'):
                quality=state['daily_quality']
                if result.get('cover_repair_evidence'):quality['cover_repair_evidence']=result['cover_repair_evidence']
                previous=quality.get('scene_requirements',{})
                coverage=result.get('scene_requirements') or {'ready':False}
                quality['scene_requirements']=coverage
                # New inventory alone cannot solve a named defect. Compare the
                # relevant actual replacement facts with completed methods.
                from ..quality_progress import relevant_coverage_gain, decide
                improved=relevant_coverage_gain(state,previous)
                if local_context and coverage.get('ready') and not improved:
                    # Narration preparation commits coverage before returning;
                    # comparing it with itself cannot measure this first unused,
                    # defect-bound method. Render preflight still checks output.
                    from ..quality_progress import permit
                    improved = bool(permit(state, 'reedit', job_id=job.get('id')))
                completed_statuses={'results','no_results','query_restricted','error','search_failed'}
                completed_attempt=(local_context or local_review or
                    any(r.get('status') in completed_statuses for r in searches) or
                    any(v.get('network_received',0) for v in outcomes.values()))
                attempt_key=('local_context_attempt' if local_context else
                             'local_review_attempt' if local_review else 'collection_attempt')
                if not completed_attempt and not improved:
                    # Authentication, pacing and unavailable routes are waits,
                    # not completed no-gain work. Preserve the full audit and
                    # stop identical automatic replay without spending its cap.
                    quality.setdefault('source_waits',[]).append({'job_id':job.get('id'),
                        'searches':searches,'platform_outcomes':outcomes,'at':time.time()})
                    waits = [*searches, *result.get('access_waits', [])]
                    from ..source_search.strategy import ACCESS_WAITS
                    waits = [r for r in waits if r.get('status') in ACCESS_WAITS]
                    if not waits:
                        from ..quality_progress import hold
                        hold(state,'필요한 결함의 새 장면·검토 근거 대기')
                        return
                    retry_at = max((r.get('retry_at', 0) or 0 for r in waits), default=0)
                    pacing = min(600, max(30, self.settings.source_browser_search_interval))
                    result['_defer_until'] = max(time.time()+pacing, retry_at)
                    quality['pending']='recollecting'
                    state.update(status='source_wait',message='소스 접근 또는 새 검토 입력 대기 · 미시도는 무진전 횟수에 포함하지 않음')
                    state['source_search'].update(status='queued',waiting=True,not_before=result['_defer_until'])
                    return
                quality.setdefault('accepted_source_jobs',[]).append(job.get('id'))
                quality[attempt_key]=quality.get(attempt_key,0)+1
                quality['scene_no_progress']=0 if improved else quality.get('scene_no_progress',0)+1
                quality['pending']='reedit' if improved and coverage.get('ready') else 'recollect'
                if not improved and (local_context or local_review or not external_attempted):
                    from ..quality_progress import hold
                    hold(state,'필요한 결함의 새 장면·검토 근거 대기')
                    return
                decide(state,'continue' if improved else 'switch',
                    '잔존 결함에 사용할 새 승인 근거 확보' if improved else '완료한 방법에 진전 없음 · 미사용 검색 범위만 탐색')
                self.advance_workflow(state,db)
            return
        if kind == "prepare":
            # Uploads may arrive while preparation is running. Never discard
            # them when the worker commits its earlier snapshot.
            incoming = list(result.get('sources', []))
            identity = lambda v: ('sha256', v['sha256']) if v.get('sha256') else ('path', v['path'])
            known = {identity(v) for v in incoming}
            incoming.extend(v for v in state['sources'] if identity(v) not in known)
            result = {**result, 'sources': incoming}
            state.update({k: v for k, v in result.items() if k != "text"})
            if not state["scripts"] and result.get('text'): self._script(state, result["text"], result.get('script_origin', "recommended"))
        elif kind == 'rewrite':
            if p.get('quality_rewrite'):
                from ..quality_progress import finish_attempt
                finish_attempt(state,job,result)
            if p.get('quality_rewrite') and enabled(state):
                # A new selected script needs fresh voice/edit queue identities.
                # Reusing the same run key otherwise finds completed old jobs
                # and leaves the task silently stuck at voice_generating.
                from ..studio_workflow import init_run
                import copy
                previous=snapshot(state)
                inputs=copy.deepcopy(previous['inputs'])
                previous['status']='superseded'
                state.pop('run_id',None)
                run=init_run(state)
                inputs.pop('source_ids',None)
                inputs['script_text']=result['text']
                run.update(parent_id=previous['id'],inputs=inputs)
            state.update({k:v for k,v in result.items() if k != 'text'})
            if not state['scripts'] or enabled(state): self._script(state, result['text'], 'automatic_codex')
            if enabled(state): state['automation']['needs_top_pick'] = False
            if p.get('quality_rewrite'):
                context=state['daily_quality'].get('repair_context')
                if context:context['script_id']=state['script_id']
                state['daily_quality'].pop('pending',None)
                state['daily_quality'].pop('thumbnail_lines',None)
        elif kind == "proposal":
            if not any(r["id"] == result["id"] for r in state["proposals"]): state["proposals"].append(result)
        elif kind == "voice":
            if not any(v["id"] == result["id"] for v in state["voices"]): state["voices"].append(result)
            if state["approved_script_id"] == result["script_id"] and state.get("pending_voice_id") == result["id"]:
                state.update(voice_id=result["id"], status="voice_review", message="음성을 듣고 승인해 주세요", error="")
        elif kind in {"edit", "revision", "edit_request", "quality_reedit"}:
            from ..daily_quality import rewrite_repair_context
            context=rewrite_repair_context(state,p) if kind=='edit' else None
            if context and not p.get('quality_repair'):
                from ..scene_requirements import repair_render_signature,REPAIR_SIGNATURE_POLICY
                p={**p,'quality_repair':True,'parent_edit_id':context['parent_edit_id'],
                   'repair_input_signature':repair_render_signature(state),'repair_signature_policy':REPAIR_SIGNATURE_POLICY}
            fresh=not result.get("no_render") and not any(e["id"] == result["id"] for e in state["edits"])
            if not fresh and not result.get('no_render'):
                # Late completion of an old job cannot select an older edit or
                # move an already reviewed/completed task back to draft review.
                return
            if fresh:
                if kind=='quality_reedit' or p.get('quality_repair'):
                    from ..quality_progress import finish_attempt
                    finish_attempt(state,job,result)
                accounting=repair_render_accounting(state,job,result) if kind=='quality_reedit' or p.get('quality_repair') else None
                state["edits"].append(result)
                if kind=='quality_reedit' or p.get('quality_repair'):
                    quality=state['daily_quality']
                    quality['repair_round']=accounting['repair_round_after']
                    result['repair_accounting']=accounting
                    result['quality_repair_round']=accounting['repair_round_after']
                    quality.setdefault('render_accounting',[]).append(dict(accounting))
                    signature=result.get('repair_input_signature') or p.get('repair_input_signature')
                    if signature:quality.setdefault('rendered_input_signatures',[]).append(signature)
                    if p.get('quality_repair'):
                        result['parent_id']=p.get('parent_edit_id')
                        result['repair_input_signature']=signature
                        quality.setdefault('repair_context_history',[]).append(quality.pop('repair_context',{}))
            if state["approved_voice_id"] == p["voice_id"]:
                if not result.get("no_render"): state["edit_id"] = result["id"]
                state.update(status="draft_review", message=result.get("request_summary") or "초안을 확인해 주세요", error="",
                             candidate_requests=result.get("candidate_requests", []))
                if kind=='quality_reedit':state['daily_quality'].pop('pending',None)
        elif kind == "register":
            edit = next(e for e in state["edits"] if e["id"] == p["edit_id"])
            if result.get('registration_deferred'):
                edit.update(registration_deferred=True, registration_note=result['registration_note'])
                state.update(message=result['registration_note'], error='')
            else:
                edit.update(draft_path=result["draft_path"], draft_name=result["draft_name"])
                edit.pop('registration_deferred', None)
                edit.pop('registration_note', None)
                state.update(message="CapCut에서 초안을 열어 편집할 수 있습니다", error="")
        elif kind == 'export':
            edit = next(e for e in state['edits'] if e['id'] == p['edit_id'])
            edit.update(result)
        if enabled(state) and db is not None:
            snapshot(state)
            if state.get('pending_reproduction'):
                self.activate_reproduction(state, db)
                return
        if state.get('automation', {}).get('active') and db is not None:
            self._advance_auto(state, db)
        elif state.get('automation', {}).get('paused_by_user'):
            state.update(status='paused', message='단계 결과 저장 완료 · 자동 진행 중지')

    def _advance_auto(self, state, db):
        if enabled(state):
            return self.advance_workflow(state, db)
        auto = state['automation']
        if not auto.get('active') or not state.get('sources'): return
        script = selected(state, 'scripts', 'script_id')
        voice = selected(state, 'voices', 'voice_id')
        edit = selected(state, 'edits', 'edit_id')
        if not script:
            stage, status, message = 'rewrite', 'rewriting', 'Codex 대본 집필·검사 중'
            self.store.enqueue(db, state['id'], stage, {}, 'rewrite:'+state['id'])
        elif not voice or voice['script_id'] != script['id']:
            stage, status, message = 'voice', 'voice_generating', '자동 선택 대본으로 VoiceBench 음성 생성'
            voice_id = 'voice-auto-' + script['id']
            state.update(approved_script_id=script['id'], pending_voice_id=voice_id)
            auto['script_selection'] = {'mode':'automatic', 'script_id':script['id']}
            self.store.enqueue(db, state['id'], stage,
                               {'voice_id':voice_id, 'script_id':script['id'], 'speed':1.0}, voice_id)
        elif not edit or edit['voice_id'] != voice['id']:
            if digest(voice['path']) != voice['sha256']: raise Conflict('자동 선택 음성의 파일이 변경됐습니다.')
            stage, status, message = 'edit', 'editing', '장면·자막 편집 및 리뷰 영상 생성'
            state.update(approved_voice_id=voice['id'])
            auto['voice_selection'] = {'mode':'automatic', 'voice_id':voice['id']}
            self.store.enqueue(db, state['id'], stage,
                               {'voice_id':voice['id'], 'script_id':script['id']}, 'edit:'+voice['id'])
        elif not edit.get('draft_path'):
            stage, status, message = 'register', 'registering', '리뷰 영상 완료 · CapCut 프로젝트 등록 중'
            self.store.enqueue(db, state['id'], stage, {'edit_id':edit['id'], 'launch':False}, 'register:'+edit['id'])
        else:
            stage, status, message = 'completed', 'draft_review', '자동 제작 완료 · 영상과 CapCut 프로젝트를 검토해 주세요'
            auto['completed_at'] = time.time()
        if auto.get('stage') != stage:
            self.store.event(db, state['id'], 'automatic_stage', {'stage':stage, 'message':message})
        auto['stage'] = stage
        state.update(status=status, message=message, error='', progress=0)
