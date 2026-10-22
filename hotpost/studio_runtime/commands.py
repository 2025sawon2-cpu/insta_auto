"""User commands and atomic edits to Studio state."""
from __future__ import annotations

import copy
import json
import subprocess
import time
from pathlib import Path

from ..editing_adapter import _atomic_json
from ..studio_store import Conflict, uid
from ..studio_workflow import enabled, init_run
from .common import digest, selected


class CommandsMixin:
    def _command_recheck_quality(self, task_id, data):
        """Re-evaluate an immutable edit without reviving a failed job/search."""
        import hashlib
        from ..daily_quality import enabled as quality_enabled, REVIEW_INSTRUCTION
        contract = hashlib.sha256(REVIEW_INSTRUCTION.encode()).hexdigest()
        reason = str(data.get('reason') or '').strip()
        if not reason:raise ValueError('실제 재검토 사유가 필요합니다.')
        def queue(state, db):
            if not quality_enabled(state):raise ValueError('품질 검토 대상 작업이 아닙니다.')
            edit = selected(state, 'edits', 'edit_id')
            if not edit or edit['id'] != data.get('edit_id'):
                raise Conflict('재검토할 편집본이 변경되었습니다.')
            video = edit.get('export_path') or edit.get('preview_path')
            render_sha, plan_sha = digest(video), digest(edit['plan_path'])
            if (render_sha != data.get('render_sha256') or plan_sha != data.get('plan_sha256')):
                raise Conflict('재검토 요청 이후 실제 영상·계획이 변경되었습니다.')
            if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('queued','running')",
                          (task_id,)).fetchone():
                raise Conflict('진행 중인 작업이 끝난 뒤 재검토하세요.')
            auto = state.setdefault('automation', {})
            if auto.get('paused_by_user'):
                token = data.get('resume_pause_token')
                if token is None or token != auto.get('paused_at'):
                    raise Conflict('사용자 중지 보존 · 해당 중지 이후 명시 재개가 필요합니다.')
            key = 'quality-policy-recheck:' + edit['id'] + ':' + render_sha + ':' + contract
            if db.execute('SELECT 1 FROM jobs WHERE key=?', (key,)).fetchone():
                raise Conflict('동일 영상·검토 기준의 재검토 이력이 있어 같은 방법을 반복하지 않습니다.')
            quality = state['daily_quality']
            quality.setdefault('recheck_history', []).append({
                'at': time.time(), 'reason': reason, 'edit_id': edit['id'],
                'render_sha256': render_sha, 'plan_sha256': plan_sha,
                'review_contract_sha256': contract,
                'prior': {k: copy.deepcopy(quality.get(k)) for k in
                          ('status','pending','error','failed_job_id','failed_job_kind')}})
            for name in ('pending','error','failed_job_id','failed_job_kind'):
                quality.pop(name, None)
            quality['status'] = 'pending'
            auto.update(active=True, paused_by_user=False, stage='quality_review')
            auto.pop('pause_reason', None)
            jid = self.store.enqueue(db, task_id, 'quality_review',
                {'edit_id': edit['id'], 'explicit_policy_recheck': True,
                 'render_sha256': render_sha, 'plan_sha256': plan_sha,
                 'review_contract_sha256': contract, 'reason': reason}, key)
            state.update(status='quality_review', error='', progress=0,
                         message='기존 영상 보존 · 현재 기준으로 실제 프레임 재검토')
            self.store.event(db, task_id, 'quality_policy_recheck_requested',
                             {'job_id': jid, 'edit_id': edit['id'], 'reason': reason,
                              'render_sha256': render_sha, 'review_contract_sha256': contract,
                              'source_jobs_resumed': False})
        return self.public(self.store.change(task_id, queue, data.get('revision')))

    def _script(self, state, text, origin, restored_from=None):
        text = str(text).strip()
        if not text or len(text) > 3000:
            raise ValueError("대본은 1~3000자로 입력하세요.")
        current = selected(state, "scripts", "script_id")
        if current and current["text"] == text:
            return current
        revision = dict(id=uid("script-"), text=text, origin=origin, created=time.time(), restored_from=restored_from)
        path = self.folder(state["id"]) / (revision["id"] + ".txt")
        path.write_text(text + "\n", encoding="utf-8")
        revision["path"] = str(path)
        state["scripts"].append(revision)
        state.update(script_id=revision["id"], approved_script_id=None, voice_id=None,
                     approved_voice_id=None, edit_id=None, status="script_review", error="", message="대본을 검토해 주세요")
        return revision

    def _command_regenerate_script(self, task_id, data):
        action = 'regenerate-script'
        product = str(data.get('product','')).strip()
        instructions = str(data.get('instructions','')).strip()
        product_url = str(data.get('product_url','')).strip()
        evidence_mode = data.get('evidence_mode','research')
        if evidence_mode not in {'research','reference'}:
            raise ValueError('상품 조사 또는 원본 영상 관찰 모드를 선택하세요.')
        from urllib.parse import urlparse
        if not product or len(product)>300 or len(instructions)>1500:
            raise ValueError('대상 상품은 1~300자, 수정 지침은 1500자 이하로 입력하세요.')
        if product_url and (len(product_url)>2000 or urlparse(product_url).scheme not in {'http','https'} or not urlparse(product_url).hostname):
            raise ValueError('상품 링크는 올바른 http 또는 https 주소로 입력하세요.')
        def regenerate(s, db):
            if not s.get('original_text') or not s.get('reference_video') or not s.get('sources'):
                raise ValueError('원본 영상·발화·사용 소스를 먼저 확보하세요.')
            if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('queued','running')", (task_id,)).fetchone():
                raise Conflict('진행 중인 작업이 끝난 뒤 새 대본을 생성하세요.')
            # A completed version remains untouched; this action recovers
            # failed rewrite steps, not an alternate edit-version path.
            if s.get('script_id') or s.get('edit_id'):
                raise Conflict('이미 제작한 대본이 있습니다. 대본 수정 기능으로 새 버전을 만드세요.')
            attempt = uid('rewrite-')
            s.setdefault('rewrite_history', []).append({'studio_job_id':s.get('studio_job_id'),
                'product':s.get('product'), 'product_url':s.get('product_url_override',''),
                'script_candidates':copy.deepcopy(s.get('script_candidates',[])),
                'error':s.get('error'), 'at':time.time()})
            s.update(product=product, product_override=product, rewrite_instructions=instructions,
                     product_url_override=product_url, evidence_mode=evidence_mode, script_candidates=[], top_pick=None, selected_candidate=None,
                     studio_job_id=None, status='rewriting', error='', progress=0,
                     message='바로잡은 상품과 근거로 새 대본 생성 대기')
            s.setdefault('automation', {}).update(protocol=2,active=True,paused_by_user=False,stage='rewrite',needs_top_pick=False)
            init_run(s)
            # Older attempts remain auditable but cannot be revived by
            # retry/resume while the corrected request is being processed.
            db.execute("UPDATE jobs SET status='superseded' WHERE task_id=? AND kind='rewrite' AND status IN ('failed','paused')", (task_id,))
            self.store.enqueue(db, task_id, 'rewrite', {}, attempt)
            db.execute('UPDATE jobs SET checkpoint=? WHERE key=?',
                       (json.dumps({'generation_key':attempt}),attempt))
            self.store.event(db, task_id, action, {'product':product,'attempt':attempt})
        return self.public(self.store.change(task_id,regenerate,data.get('revision')))

    def _command_caption_preview(self, task_id, data):
        state = self.store.get(task_id)
        edit = next((e for e in state['edits'] if e['id']==data.get('edit_id')), None)
        if not edit or edit['id'] != state.get('edit_id'):
            raise Conflict('새 편집 영상이 준비되었습니다. 새로고침해 주세요.')
        if edit.get('clean_preview_path') and Path(edit['clean_preview_path']).is_file():
            return self.public(state)
        folder = self.folder(task_id)/('caption-preview-'+edit['id']); folder.mkdir(exist_ok=True)
        request, result = folder/'request.json', folder/'result.json'
        _atomic_json(request, {'action':'caption-preview','output_dir':str(folder),
                              'plan':json.loads(Path(edit['plan_path']).read_text(encoding='utf-8'))})
        process = subprocess.run([str(self.settings.auto_capcut_python),'-X','utf8','-m','auto_capcut.studio_runner',
                                  '--request',str(request),'--result',str(result)],cwd=self.settings.auto_capcut_root,
                                 capture_output=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        output = json.loads(result.read_text(encoding='utf-8')) if result.is_file() else {}
        if process.returncode or output.get('status') != 'completed':
            raise ValueError(output.get('error','편집 미리보기를 준비하지 못했습니다. 다시 시도하거나 CapCut에서 편집하세요.'))
        def accept(s, db):
            next(e for e in s['edits'] if e['id']==edit['id'])['clean_preview_path']=output['clean_preview_path']
        return self.public(self.store.change(task_id,accept))

    def _command_check_script(self, task_id, data):
        # A read-only request; never hold the task DB lock across HTTP or
        # save/approve text merely because the user asked to inspect it.
        from ..studio_adapter import StudioAdapter
        text = str(data.get('text', ''))
        if not text.strip() or len(text) > 3000:
            raise ValueError('대본은 1~3000자로 입력하세요.')
        state = self.store.get(task_id)
        try:
            return StudioAdapter(self.settings).review(text, state.get('reviewed_original_text', state['original_text']),
                evidence_mode='self_shot' if state.get('creation_mode') == 'self_shot' else
                    'benchmark' if state.get('benchmark_analysis') else 'research')
        except (RuntimeError, OSError) as exc:
            raise ValueError('내장 대본 검사를 완료하지 못했습니다. 입력 내용은 그대로 유지됩니다.') from exc

    def action(self, task_id, action, data):
        if action == 'resume-held-attempt':
            from ..video_agent_actions import execute
            from ..video_agents import get_agent
            from ..video_agent_context import semantic_fingerprint
            state=self.store.get(task_id)
            owner=get_agent(self.store,task_id) or {}
            incident=owner.get('no_progress_hold') or (owner.get('held_method_incidents') or {}).get(data.get('job_id')) or {}
            if not incident or data.get('hold_id')!=incident.get('id'):
                raise ValueError('현재 보류 ID와 원인 해결 근거가 필요합니다.')
            if data.get('kind','retry') not in {'retry','retry_repaired','continue_repaired'}:
                raise ValueError('검증된 입력 변경 또는 수리 후 재개만 가능합니다.')
            tool={k:data[k] for k in ('job_id','repair_id','hold_id','evidence','hypothesis') if k in data}
            tool.update(kind=data.get('kind','retry'),_agent_epoch=owner['epoch'],
                        _expected_revision=data.get('revision',state['revision']))
            result=execute(self,task_id,tool,'attempt-resume:'+str(data.get('decision_id') or incident['id']),
                           semantic_fingerprint(state))
            if result.get('status')!='queued':
                raise ValueError(result.get('reason') or '원인 해결 근거가 부족해 보류를 유지합니다.')
            return self.public(self.store.get(task_id))
        # Revoke a pending agent decision BEFORE a user command can mutate its
        # inputs. This separate transaction changes no task revision, so the
        # command's own optimistic revision check still sees the user's version.
        # Even a rejected command cancels stale background intent conservatively.
        from ..video_agents import enroll
        with self.store.transaction() as db:
            enroll(db, self.store.get(task_id, db), 'user_command', renew=True)
        try:
            return self._action(task_id, action, data)
        finally:
            # Only the command itself grants resume authority. Synchronizing a
            # dormant/paused owner must never activate production on its own.
            with self.store.transaction() as db:
                enroll(db, self.store.get(task_id, db), 'user_command')

    def _action(self, task_id, action, data):
        own = self.store.get(task_id)
        if action == 'attach-agent':
            return self.public(own)  # Wrapper enrolls; production state/approvals stay authoritative.
        if action == 'recheck-quality':
            return self._command_recheck_quality(task_id, data)
        if (own.get('creation_mode') == 'photo_post' and not self.settings.photo_production_enabled
                and action in {'start-auto', 'resume-auto', 'retry', 'reproduce', 'make-video',
                               'revise-edit', 'request-edit', 'export-edit', 'export-overlays', 'export-thumbnail', 'approve-voice'}):
            raise ValueError('사진·캐러셀 게시물의 영상 제작은 비활성화되어 있습니다.')
        if own.get('creation_mode') == 'self_shot':
            if action == 'save-self-shot-brief':
                return self.save_self_shot_brief(task_id, data)
            if action in {'refresh-sources', 'retry-automatic-sources'}:
                raise ValueError('내 촬영 영상 작업은 직접 추가한 영상만 사용합니다.')
            if action in {'start-auto', 'resume-auto'} and own.get('self_shot', {}).get('started') is not True:
                return self.start_self_shot(task_id, data)
        if action == 'add-script-candidate':
            from ..script_candidate_versions import add_candidate
            return self.public(add_candidate(self.store, task_id, data))
        if action == 'regenerate-script':
            return self._command_regenerate_script(task_id, data)
        if action == 'prepare-caption-preview':
            return self._command_caption_preview(task_id, data)
        if action == 'check-script':
            return self._command_check_script(task_id, data)
        handled = self.workflow_action(task_id, action, data)
        if handled is not None:
            return handled
        def change(state, db):
            if action == 'save-original':
                if data.get('base_text', state.get('reviewed_original_text', state['original_text'])) != state.get('reviewed_original_text', state['original_text']):
                    raise Conflict('다른 화면에서 원본 발화가 바뀌었습니다. 최신 교정본을 확인하세요.')
                text = str(data.get('text', '')).strip()
                if not text or len(text) > 12000:
                    raise ValueError('원본 발화는 1~12000자로 입력하세요.')
                state.setdefault('original_reviews', []).append({'text': text, 'created': time.time()})
                state['reviewed_original_text'] = text
                self.store.event(db, task_id, action, {})
                return
            if action == 'review-result':
                run = next(r for r in self.pipeline(state) if r['id'] == data.get('run_id'))
                if not run.get('video_url') or run['status'] != 'completed':
                    raise ValueError('최종 영상이 완성된 뒤 확인할 수 있습니다.')
                checks = data.get('checks', [])
                if not isinstance(checks, list) or set(checks) != {'speech', 'captions', 'scenes'}:
                    raise ValueError('발음·자막·장면을 모두 확인해 주세요.')
                state.setdefault('result_reviews', {})[run['id']] = {'created': time.time(), 'checks': checks}
                self.store.event(db, task_id, action, {'run_id': run['id']})
                return
            if action in {'save-script', 'restore-script', 'apply-proposal', 'pause-auto'} and state.get('automation'):
                state['automation']['active'] = False
                state['automation']['paused_at'] = time.time()
                state['automation']['pause_reason'] = action
                if action != 'pause-auto':
                    state['automation']['stage'] = 'manual_review'
                    state['automation'].pop('completed_at', None)
            if action == 'pause-auto':
                if not state.get('automation'): raise ValueError('자동 제작 대상이 아닙니다.')
                state['automation']['paused_by_user'] = True
                if enabled(state):
                    db.execute("UPDATE jobs SET status='paused' WHERE task_id=? AND status='queued' AND kind NOT IN ('proposal','suggest_edit') AND COALESCE(json_extract(payload,'$.launch'),0)<>1", (task_id,))
                state.update(message='자동 진행 중지 · 진행 중인 단계의 결과를 보존합니다')
                self.store.event(db, task_id, action, {})
                return
            if action == 'resume-auto':
                if not state.get('automation'): raise ValueError('자동 제작 대상이 아닙니다.')
                from ..production_control import hold as attempt_hold
                if attempt_hold(db,task_id):
                    # Explicit user resume revokes only the user pause. The
                    # independent technical hold requires its guarded resolution.
                    state['automation'].update(active=True,selection_mode='manual_resume')
                    for field in ('paused_by_user','pause_reason','consumed_by_daily_policy'):
                        state['automation'].pop(field,None)
                    state['message']='사용자 중지 해제 · 기록된 원인의 검증된 해결 후 같은 영상 이어 제작 대기'
                    self.store.event(db,task_id,action,{'technical_hold_retained':True})
                    return
                if state.get('daily_quality',{}).get('pending') in {'exhausted','failed','scene_wait'}:
                    from ..quality_progress import resume_assessment
                    if not resume_assessment(state):
                        state['message']='이전 품질 중단 유지 · 실제 새로운 수정 근거 대기'
                        return
                self.release_source_hold(state)
                hold = state.pop('editorial_content_hold', None)
                if hold:
                    state.setdefault('editorial_review_history', []).append(hold)
                    self.store.event(db, task_id, 'editorial_hold_released', hold)
                state['error'] = ''
                if not state.get('product_override') and state.get('product') in {None, '', '원작 중심 대상 미확인'} and state.get('source_search_manifest_path'):
                    from ..studio_automation import identify_subject
                    from ..reference_context import post_caption
                    manifest_file = Path(state.get('source_search_manifest_path') or '')
                    manifest_data = json.loads(manifest_file.read_text(encoding='utf-8')) if manifest_file.is_file() else {}
                    manifest_data = {**manifest_data, 'caption': post_caption(self.settings, state) or manifest_data.get('caption', '')}
                    resolved_product = identify_subject(manifest_data, state.get('original_text', ''), state.get('product') or state.get('title', ''))
                    if resolved_product and resolved_product != '원작 중심 대상 미확인':
                        state['product'] = resolved_product
                state['automation']['active'] = True
                from ..studio_supervision import StudioSupervisor
                StudioSupervisor.release(db, task_id)
                state['automation'].pop('consumed_by_daily_policy', None)
                state['automation']['selection_mode'] = 'manual_resume'
                state['automation'].pop('paused_by_user', None)
                state['automation'].pop('pause_reason', None)
                if enabled(state):
                    db.execute("UPDATE jobs SET status='queued' WHERE task_id=? AND status='paused'", (task_id,))
                if not state.get('original_text') or (not state.get('reference_video') and state.get('creation_mode') != 'self_shot'):
                    self.store.enqueue(db, task_id, 'prepare', {}, 'prepare:'+task_id)
                    state.update(status='preparing', message='자료 준비 재개', error='')
                pending_prepare = db.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind='prepare' AND status IN ('queued','running','paused')", (task_id,)).fetchone()
                if pending_prepare:
                    state.update(status='preparing', message='자료 준비 대기', error='')
                else:
                    self._advance_auto(state, db)
                self.store.event(db, task_id, action, {})
                return
            if action == 'refresh-sources':
                if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind IN ('prepare','refresh_sources','collect_sources') AND status IN ('queued','running')", (task_id,)).fetchone():
                    raise Conflict('자료 수집이 이미 대기 중이거나 실행 중입니다.')
                request = str(data.get('request', ''))[:1000]
                self.release_source_hold(state)
                if data.get('retry_job_id'):
                    failed = db.execute("SELECT payload FROM jobs WHERE id=? AND task_id=? AND kind='refresh_sources' AND status='failed'",
                                        (data['retry_job_id'], task_id)).fetchone()
                    if not failed:
                        raise Conflict('재시도할 소스 검색이 변경되었습니다. 최신 상태를 확인하세요.')
                    request = json.loads(failed['payload']).get('request', '')
                from ..source_policy import adopt_policy
                policy = adopt_policy(state, self.settings)
                payload = {'request':request, 'source_policy':policy, 'run_id':state.get('run_id')}
                if data.get('search_before_saved_reviews') is True:
                    # Explicit new-search evaluation preserves saved files and
                    # consumed scopes, while giving the new grounded plan priority.
                    payload['search_before_saved_reviews'] = True
                if state.get('automation', {}).get('paused_by_user'):
                    pause_token = state['automation'].setdefault('paused_at', time.time())
                    payload.update(manual_source_request=True, pause_token=pause_token)
                self.store.enqueue(db, task_id, 'refresh_sources', payload, uid('sources:'))
                state['source_search'] = {'status': 'queued', 'message': '다국어 추가 수집 대기', 'progress': 0}
            elif action == "save-script":
                self._script(state, data.get("text", ""), "manual")
            elif action == "restore-script":
                old = next(s for s in state["scripts"] if s["id"] == data["script_id"])
                self._script(state, old["text"], "restored", old["id"])
            elif action == "propose-script":
                script = selected(state, "scripts", "script_id")
                if not script: raise ValueError("수정할 대본이 없습니다.")
                if any(j["kind"] == "proposal" and j["status"] in {"running", "queued"} for j in self.store.jobs(task_id)):
                    raise Conflict("AI 수정안을 준비하고 있습니다. 완료 후 다시 요청하세요.")
                request = str(data.get("request", "")).strip()[:2000]
                if not request: raise ValueError("수정 요청을 입력하세요.")
                base_text = str(data.get('base_text', state.get('feedback', {}).get('script_text', script['text']))).strip()
                if not base_text or len(base_text) > 3000:
                    raise ValueError('대본은 1~3000자로 입력하세요.')
                self.store.enqueue(db, task_id, "proposal", {"script_id": script["id"], "request": request,
                    'base_text':base_text, 'original_text':state.get('reviewed_original_text', state['original_text'])}, uid("proposal:"))
            elif action == "apply-proposal":
                proposal = next(p for p in state["proposals"] if p["id"] == data["proposal_id"])
                if proposal["script_id"] != state["script_id"]:
                    raise Conflict("수정안 생성 후 대본이 바뀌었습니다. 현재 대본으로 다시 요청하세요.")
                if proposal.get('original_text', state.get('reviewed_original_text', state['original_text'])) != state.get('reviewed_original_text', state['original_text']):
                    raise Conflict('원본 발화가 교정되었습니다. 수정안을 다시 요청하세요.')
                self._script(state, proposal["text"], "ai_proposal")
            elif action in {"approve-script", "regenerate-voice"}:
                script = selected(state, "scripts", "script_id")
                if not script: raise ValueError("승인할 대본이 없습니다.")
                if data.get("script_id") != script["id"]: raise Conflict("대본 버전이 바뀌었습니다.")
                if action == "regenerate-voice" and state["approved_script_id"] != script["id"]:
                    raise Conflict("현재 대본을 먼저 승인하세요.")
                if action == "approve-script" and state["approved_script_id"] == script["id"]: return
                if state["status"] == "voice_generating": return
                state.update(approved_script_id=script["id"], voice_id=None, approved_voice_id=None, edit_id=None,
                             status="voice_generating", message="음성 생성 대기", error="")
                speed = float(data.get("speed", 1))
                if not .8 <= speed <= 1.25: raise ValueError("음성 속도는 0.8~1.25배입니다.")
                voice_id = uid("voice-")
                self.store.enqueue(db, task_id, "voice", {"script_id": script["id"], "voice_id": voice_id, "speed": speed}, voice_id)
                state["pending_voice_id"] = voice_id
            elif action == "approve-voice":
                voice = selected(state, "voices", "voice_id")
                if not voice or data.get("voice_id") != voice["id"]: raise Conflict("음성 버전을 확인하세요.")
                if state.get("pending_voice_id") != voice["id"]: raise Conflict("새로 생성 중인 음성을 확인한 뒤 승인하세요.")
                if voice["script_id"] != state["approved_script_id"]: raise Conflict("현재 승인 대본과 다른 음성입니다.")
                if state["approved_voice_id"] == voice["id"]: return
                if digest(voice["path"]) != voice["sha256"]: raise Conflict("음성 파일이 변경되었습니다.")
                state.update(approved_voice_id=voice["id"], status="editing", message="장면·자막 편집 대기", error="")
                self.store.enqueue(db, task_id, "edit", {"voice_id": voice["id"], "script_id": voice["script_id"]}, "edit:" + voice["id"])
            elif action == "retry":
                row = (db.execute("SELECT * FROM jobs WHERE task_id=? AND id=? AND status='failed'", (task_id,data['job_id'])).fetchone()
                       if data.get('job_id') else db.execute("SELECT * FROM jobs WHERE task_id=? AND status='failed' ORDER BY updated DESC LIMIT 1", (task_id,)).fetchone())
                if not row: return
                from ..studio_supervision import StudioSupervisor
                StudioSupervisor.release(db, task_id, row['id'])
                if row['kind'] == 'collect_sources':
                    self.release_source_hold(state)
                    checkpoint=json.loads(row['checkpoint'])
                    checkpoint.update(auto_retries=0,not_before=0)
                    db.execute("UPDATE jobs SET status='queued',error='',checkpoint=? WHERE id=?",(json.dumps(checkpoint),row['id']))
                    state['source_search']={'status':'queued','message':'소스 수집 재시도 대기','progress':0}
                    self.store.event(db,task_id,'retry_sources',{'job_id':row['id']})
                    return  # A source retry must not erase an independent TTS failure.
                if enabled(state):
                    checkpoint = json.loads(row['checkpoint'])
                    checkpoint.pop('not_before',None)
                    checkpoint['auto_retries'] = 0
                    db.execute('UPDATE jobs SET checkpoint=? WHERE id=?',(json.dumps(checkpoint),row['id']))
                payload = json.loads(row["payload"])
                if row['kind'] in {'quality_review', 'quality_reedit'}:
                    if (payload.get('edit_id') != state.get('edit_id')
                            or payload.get('voice_id') != state.get('approved_voice_id')):
                        raise Conflict('이전 영상·음성의 품질 작업입니다. 현재 제작 버전에서 다시 요청하세요.')
                if payload.get("script_id", state["script_id"]) != state["script_id"]:
                    raise Conflict("이전 대본의 작업입니다. 현재 대본을 승인해 주세요.")
                if row["kind"] == "voice" and payload.get("voice_id") != state.get("pending_voice_id"):
                    raise Conflict("이전 음성의 작업입니다. 현재 음성을 확인하세요.")
                if row["kind"] in {"edit", "revision", "edit_request"} and payload.get("voice_id") != state.get("approved_voice_id"):
                    raise Conflict("이전 음성의 편집입니다. 현재 음성을 먼저 승인하세요.")
                if row['kind'] in {'rewrite', 'voice'}:
                    checkpoint = json.loads(row['checkpoint'])
                    if row['kind']=='rewrite':
                        previous=checkpoint.pop('studio_job_id',None)
                        if previous:
                            checkpoint.setdefault('previous_studio_job_ids',[]).append(previous)
                        # The remote generation may have completed while all
                        # candidates failed Hotpost's review. Reusing that
                        # completed response can never repair the script.
                        checkpoint['generation_key']=uid('rewrite-retry-')
                    checkpoint['retry_requested'] = True
                    db.execute('UPDATE jobs SET checkpoint=? WHERE id=?', (json.dumps(checkpoint), row['id']))
                db.execute("UPDATE jobs SET status='queued',error='' WHERE id=?", (row["id"],))
                state.update(error="", message="중단 단계부터 재시도 중")
                state["status"] = {"prepare":"preparing", "rewrite":"rewriting", "voice":"voice_generating", "edit":"editing", "revision":"editing", "register":"registering"}.get(row["kind"], state["status"])
                if row['kind'] in {'quality_review', 'quality_reedit'}:
                    state['status'] = 'quality_review' if row['kind']=='quality_review' else 'editing'
                    state.setdefault('daily_quality', {}).update(pending=row['kind'],status='pending')
                    automatic=state.get('automation', {})
                    if automatic.get('protocol')==2 and not automatic.get('paused_by_user'):
                        automatic['active']=True
            elif action in {"revise-edit", "request-edit"}:
                edit = selected(state, "edits", "edit_id")
                if not edit or data.get("edit_id") != edit["id"]: raise Conflict("현재 편집 버전을 확인하세요.")
                if edit["voice_id"] != state["approved_voice_id"]: raise Conflict("현재 승인 음성과 다른 편집입니다.")
                if any(r["status"] in {"queued", "running"} and r["kind"] in {"edit", "revision", "edit_request"} for r in self.store.jobs(task_id)):
                    raise Conflict("진행 중인 편집이 완료된 후 요청하세요.")
                kind = "edit_request" if action == "request-edit" else "revision"
                self.store.enqueue(db, task_id, kind, {"edit_id": edit["id"], "voice_id": edit["voice_id"],
                                   "script_id": edit["script_id"], "changes": data.get("changes", []),
                                   "request": str(data.get("request", ""))[:2000], "start": data.get("start", 0), "end": data.get("end")}, uid("edit:"))
                state.update(status="editing", message="선택 구간 수정 중", error="")
            elif action == "open-capcut":
                edit = next((e for e in state["edits"] if e["id"] == data.get("edit_id")), None)
                if not edit: raise ValueError("초안 생성 후 이용할 수 있습니다.")
                self.store.enqueue(db, task_id, "register", {"edit_id": edit["id"]}, "register:" + edit["id"])
                db.execute("UPDATE jobs SET status='queued',payload=? WHERE key=? AND status IN ('done','queued','failed')",
                           (json.dumps({'edit_id':edit['id'], 'launch':True}), "register:" + edit["id"]))
                state.update(message="CapCut 초안 준비 중", error="")
            else:
                raise ValueError("지원하지 않는 작업입니다.")
            self.store.event(db, task_id, action, {k: v for k, v in data.items() if k not in {"text"}})
        return self.public(self.store.change(task_id, change, data.get("revision")))
