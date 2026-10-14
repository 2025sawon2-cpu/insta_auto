"""CapCut process boundary and editable video generation jobs."""
from __future__ import annotations

from ..studio_store import change_claimed

import json
import hashlib
import subprocess
import time
from pathlib import Path

from ..editing_adapter import _atomic_json
from ..studio_store import Conflict
from .common import digest


SEMANTIC_CACHE_POLICY='semantic-actual-input-contract-v1'


def _semantic_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def _loaded_code_projection(code):
    """Describe loaded executable code without marshal's reference-count flags."""
    from types import CodeType
    def constant(value):
        if isinstance(value,CodeType):return {'code':_loaded_code_projection(value)}
        if value is None or isinstance(value,(str,bool,int)):return value
        if isinstance(value,bytes):return {'bytes':value.hex()}
        if isinstance(value,float):return {'float':value.hex()}
        if isinstance(value,complex):return {'complex':[value.real.hex(),value.imag.hex()]}
        if value is Ellipsis:return {'ellipsis':True}
        if isinstance(value,tuple):return {'tuple':[constant(v) for v in value]}
        if isinstance(value,frozenset):
            return {'frozenset':sorted((constant(v) for v in value),
                key=lambda v:json.dumps(v,sort_keys=True,ensure_ascii=False))}
        raise TypeError('Unsupported executable constant: '+type(value).__name__)
    return {'bytecode':code.co_code.hex(),'constants':[constant(v) for v in code.co_consts],
        'names':code.co_names,'varnames':code.co_varnames,'freevars':code.co_freevars,
        'cellvars':code.co_cellvars,'argcount':code.co_argcount,
        'posonlyargcount':code.co_posonlyargcount,'kwonlyargcount':code.co_kwonlyargcount,
        'nlocals':code.co_nlocals,'stacksize':code.co_stacksize,'flags':code.co_flags,
        'exceptiontable':getattr(code,'co_exceptiontable',b'').hex()}


def _semantic_binding(state,script,voice,sources,plan):
    """Fingerprint the loaded analysis contract and actual evidence, not cache age."""
    from .. import scene_analysis
    contract={'observe':scene_analysis.OBSERVE_INSTRUCTION,'rank':scene_analysis.RANK_INSTRUCTION,
        'limits':[scene_analysis.MAX_BATCH_SHOTS,scene_analysis.MAX_BATCH_IMAGES],
        'observe_code':_semantic_hash(_loaded_code_projection(scene_analysis._observe.__code__)),
        'rank_code':_semantic_hash(_loaded_code_projection(scene_analysis.analyze_shots.__code__))}
    def fields(record,keys):return {k:record.get(k) for k in keys}
    identities=[]
    for source in sources:
        path=Path(source['path'])
        actual=digest(path)
        if actual!=source.get('sha256'):raise Conflict('의미 분석에 연결된 실제 소스 파일이 변경되었습니다.')
        row=fields(source,('id','sha256','rights','source_role','source_quality','editing_eligible',
            'manual_usage_review','original_sha256','original_interval','source_interval','retiming',
            'reviewed_intervals','watermark_masks','portrait_geometry','usage_limits'))
        row.update(path=str(path.resolve()),actual_sha256=actual,
            video_meta=fields(source.get('video_meta') or {},('width','height','duration')),
            functional_limits=fields(source.get('functional_review') or {},('policy','source_sha256',
                'same_core_function','context_usable','context_usage_limits','usage_limits','observed_actions',
                'matched_reference_features','differences')),
            portrait_scope=(source.get('presentation_review') or {}).get('scope'),
            mask_geometry=(source.get('mask_review') or {}).get('geometry'))
        identities.append(row)
    shots=[];complete=True
    for shot in plan.get('shots',[]):
        frames=[]
        for raw in shot.get('frames',[]):
            path=Path(raw)
            actual=digest(path) if path.is_file() else None
            if actual is None:complete=False
            frames.append({'path':str(path.resolve()),'sha256':actual})
        if not frames:complete=False
        shots.append({**fields(shot,('id','source_id','sha256','start','end','source_role',
            'context_usage_limits','parent_original_sha256','creator_overlay_present')),'frames':frames})
    actual_voice=digest(voice['path'])
    if actual_voice!=voice.get('sha256'):raise Conflict('의미 분석에 연결된 승인 음성이 변경되었습니다.')
    inputs={'script':{'id':script['id'],'text':script['text'],
            'text_sha256':hashlib.sha256(script['text'].encode()).hexdigest(),
            'file_sha256':digest(script['path']) if script.get('path') and Path(script['path']).is_file() else None},
        'voice':{**fields(voice,('id','script_id','sha256','spoken_text','script_sha256')),
                 'actual_sha256':actual_voice},
        'approval':fields(state,('approved_script_id','approved_voice_id')),
        'sources':identities,'shots':shots,
        'beats':[fields(b,('id','text','start','end')) for b in plan.get('beats',[])],
        'geometry':fields(plan,('width','height','canvas','fps','duration','footage_policy','footage_selection_policy')),
        'review_feedback':state.get('daily_quality',{}).get('feedback',[])}
    return {'policy':SEMANTIC_CACHE_POLICY,'contract_sha256':_semantic_hash(contract),
            'input_sha256':_semantic_hash(inputs),'evidence_complete':complete}


def _semantic_plan_hash(plan):
    return _semantic_hash({k:v for k,v in plan.items() if k!='semantic_cache'})


def _preserve_semantic_history(path,raw):
    history=path.parent/'semantic-history'/('semantic-plan-'+hashlib.sha256(raw).hexdigest()+'.json')
    history.parent.mkdir(parents=True,exist_ok=True)
    if history.is_file():
        if history.read_bytes()!=raw:raise Conflict('보존한 이전 의미 분석 이력 파일이 변경되었습니다.')
    else:history.write_bytes(raw)


class EditingMixin:
    @staticmethod
    def _process_artifacts(data):
        paths = []
        for key in ('plan_path', 'preview_path', 'export_path'):
            if data.get(key): paths.append(Path(data[key]))
        if data.get('portable_draft_path'):
            paths.append(Path(data['portable_draft_path'])/'draft_content.json')
        if data.get('draft_path'):
            paths.append(Path(data['draft_path'])/'draft_content.json')
        for shot in (data.get('plan') or data).get('shots', []):
            paths.extend(Path(p) for p in shot.get('frames', []))
        for candidate in data.get('candidates', []):
            if candidate.get('path'): paths.append(Path(candidate['path']))
        actual = {}
        for path in paths:
            if not path.is_file() or not path.stat().st_size:
                raise Conflict('편집 실행기 결과 파일이 소실되었습니다: '+path.name)
            actual[str(path)] = digest(path)
        if data.get('_artifact_hashes') and data['_artifact_hashes'] != actual:
            raise Conflict('편집 실행기 결과 파일이 저장 이후 변경되었습니다.')
        return actual

    def _process(self, state, job, action, payload):
        if job.get('claim_token'):
            self.store.assert_owned(job)
        if 'plan' in payload:
            from ..source_review_withdrawals import validate_plan
            from ..source_presentation import protect_automatic_crop
            protect_automatic_crop(payload['plan'], payload.get('changes', ()))
            validate_plan(self.settings, payload['plan'], payload.get('changes', ()))
        folder = self.folder(state["id"]) / job["id"]
        folder.mkdir(exist_ok=True)
        request, result = folder / f"{action}-request.json", folder / f"{action}-result.json"
        signature=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        full_request = {"action": action, "output_dir": str(folder), **payload}
        request_sha256 = hashlib.sha256(json.dumps(full_request, sort_keys=True).encode()).hexdigest()
        if job['checkpoint'].get(action+'_input')==signature and result.is_file():
            saved=json.loads(result.read_text('utf-8'))
            if saved.get('status')=='completed':
                if saved.get('request_sha256') != request_sha256:
                    raise Conflict('편집 실행기 저장 응답이 현재 요청에 결속하지 않습니다. 기존 파일을 보존합니다.')
                self._process_artifacts(saved)
                return saved
        if job.get('claim_token'):
            self.store.assert_owned(job)
        _atomic_json(request, full_request)
        with self.render_lock:
            with (folder / f"{action}.log").open("a", encoding="utf-8") as log:
                import psutil
                from types import SimpleNamespace
                proc=None
                if job['checkpoint'].get(action+'_input')==signature:
                    try:
                        running=psutil.Process(job['checkpoint'].get(action+'_pid',-1))
                        args=running.cmdline()
                        created=job['checkpoint'].get(action+'_process_created')
                        if (created is not None and abs(running.create_time()-created)<1
                                and 'auto_capcut.studio_runner' in args and str(request) in args):
                            proc=SimpleNamespace(pid=running.pid,
                                poll=lambda:None if running.is_running() else 0,
                                wait=lambda timeout:running.wait(timeout=timeout))
                    except (psutil.Error,ValueError):pass
                if proc is None:
                    if job.get('claim_token'):
                        self.store.assert_owned(job)
                    if result.is_file():
                        import uuid
                        result.replace(folder/(result.stem+'-previous-'+uuid.uuid4().hex+'.json'))
                    proc = subprocess.Popen([str(self.settings.auto_capcut_python), "-X", "utf8", "-m", "auto_capcut.studio_runner",
                                   "--request", str(request), "--result", str(result)],
                                  cwd=self.settings.auto_capcut_root, stdout=log, stderr=log,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                # The runner owns an OS lock and a result receipt. A server restart can
                # reconnect without executing the same render concurrently or twice.
                job["checkpoint"][action + "_pid"] = proc.pid
                try: job['checkpoint'][action+'_process_created'] = psutil.Process(proc.pid).create_time()
                except psutil.Error: pass
                job['checkpoint'][action+'_input']=signature
                self.store.checkpoint(job, job["checkpoint"])
                from ..operation_progress import ProgressWatch
                watch=ProgressWatch(self.settings.auto_capcut_timeout,'편집 실행기 응답')
                # Ignore pre-existing assets and administrative JSON/log writes.
                # Only new/growing media bytes from this runner are progress.
                for path in folder.rglob('*'):
                    if path.is_file() and path.suffix.lower() in {'.mp4','.wav','.jpg','.png'}:
                        watch.high_water[str(path)] = path.stat().st_size
                while proc.poll() is None:
                    for path in folder.rglob('*'):
                        if path.is_file() and path.suffix.lower() in {'.mp4','.wav','.jpg','.png'}:
                            watch.observe(str(path),path.stat().st_size)
                    try:
                        watch.check()
                    except TimeoutError:
                        from ..writing.codex_writer import stop_owned
                        stop_owned(proc)
                        raise
                    time.sleep(.25)
        if not result.is_file(): raise RuntimeError("편집 실행기가 결과를 반환하지 않았습니다. 작업 로그를 확인하세요.")
        data = json.loads(result.read_text(encoding="utf-8"))
        if data.get('request_sha256') != request_sha256:
            raise Conflict('편집 실행기의 늦은 결과 또는 다른 요청 응답을 적용하지 않습니다.')
        if data.get("status") != "completed": raise RuntimeError(data.get("error", "편집 실행 실패"))
        data['_artifact_hashes'] = self._process_artifacts(data)
        _atomic_json(result, data)
        return data

    def _edit(self, state, job):
        if job['payload'].get('initial_render_preparation_key'):
            if (job.get('kind') != 'edit' or any(job['payload'].get(key)
                    for key in ('quality_repair', 'quality_method', 'parent_edit_id'))):
                raise Conflict('Initial prepared render cannot enter a repair route')
            from ..initial_prepared_render import from_state
            _,plan=from_state(state,job['payload']['initial_render_preparation_key'])
            blocked=[]
            def before_initial_render(current,db):
                if current.get('automation',{}).get('paused_by_user'):
                    blocked.append(True);return
                from_state(current,job['payload']['initial_render_preparation_key'])
                blocked.append(False)
            change_claimed(self.store,job,before_initial_render)
            if blocked[0]:
                from ..quality_progress import QualityProgressHold
                raise QualityProgressHold('사용자 중지 유지',waiting=True)
            result=self._process(state,job,'render',{'plan':plan})
            return {'id':job['id'],'script_id':state['script_id'],'voice_id':state['voice_id'],
                    'created':time.time(),**result}
        from ..scene_requirements import required_scenes,coverage_current
        if required_scenes(state):
            from ..scene_narration_prepare import prepare_narration_context
            prepare_narration_context(self, state, job)
            if ((state.get('scene_narration_plan') or {}).get('old_edit_id')==state.get('edit_id')
                    and state.get('scene_narration_plan') and not coverage_current(state)):
                from ..scene_requirements import assess
                from ..scene_narration_prepare import _save, commit_identity
                expected_identity=commit_identity(state)
                receipt=assess(self.settings,state)
                _save(self,state,{'daily_quality':{'scene_requirements':receipt}},expected_identity,job=job)
        if required_scenes(state) and not coverage_current(state):
            from ..daily_quality import QualitySceneGap
            raise QualitySceneGap(required_scenes(state))
        from ..studio_ai import describe_shots, restrict_context_shots
        p = job["payload"]
        voice = next(v for v in state["voices"] if v["id"] == p["voice_id"])
        script = next(s for s in state["scripts"] if s["id"] == p["script_id"])
        if digest(voice["path"]) != voice["sha256"]: raise Conflict("승인한 음성이 변경되었습니다.")
        records = [s for s in state['sources'] if p.get('source_ids') is None or s['id'] in p['source_ids']]
        if not records: raise ValueError('사용 가능한 소스가 없습니다.')
        sources = self._source_records([s["path"] for s in records], state.get("manifest_path", ''), records)
        from ..source_review_withdrawals import apply_withdrawals
        from ..source_quality import editing_ready
        sources = [apply_withdrawals(self.settings, source) for source in sources]
        sources = [source for source in sources if not source.get('relevance_review_required')
                   and not source.get('presentation_review_required')
                   and source.get('editing_eligible', True)
                   and ((not source.get('source_interval_withdrawal') and not source.get('presentation_review'))
                        or editing_ready(source))]
        if not sources:
            raise ValueError('출력 검토 후 사용할 수 있는 소스 장면이 없습니다.')
        if state.get('creation_mode') == 'self_shot' and any(s.get('rights') != 'user_supplied' for s in sources):
            raise ValueError('내 촬영 영상 제작에는 직접 업로드한 영상만 사용할 수 있습니다.')
        base = self._process(state, job, "analyze", {"sources": sources, "voice": voice, "script": script})
        plan = base["plan"]
        from ..daily_quality import enabled as daily_quality_enabled
        if daily_quality_enabled(state):self.apply_daily_render_style(state,plan)
        plan['narration_priority'] = {'policy':'script-first-20261006-v2', 'script_id':script['id'],
                                    'script_sha256':hashlib.sha256(script['text'].encode()).hexdigest(),
                                    'footage_role':'adapt_to_selected_narration'}
        restrict_context_shots(plan, sources)
        by_source={s['id']:s for s in sources}
        for shot in plan['shots']:
            source=by_source.get(shot.get('source_id'),{})
            shot['parent_original_sha256']=source.get('original_sha256') or source.get('sha256')
            shot['creator_overlay_present']=bool(source.get('blur_required') or source.get('watermark_masks'))
        if state.get('reviewed_scene_rules'):
            from ..studio_reviewed_scenes import apply_reviewed_scenes
            plan=apply_reviewed_scenes(plan,state['reviewed_scene_rules'])
            result=self.render_feedback(state,job,plan)
            return {"id":job["id"],"script_id":script["id"],"voice_id":voice["id"],"created":time.time(),**result}
        semantic = self.folder(state["id"]) / job["id"] / "semantic-plan.json"
        binding=_semantic_binding(state,script,voice,sources,plan)
        if semantic.is_file():
            raw=semantic.read_bytes()
            try:cached=json.loads(raw.decode('utf-8'))
            except (ValueError,UnicodeError):cached={}
            marker=cached.get('semantic_cache',{}) if isinstance(cached,dict) else {}
            if not isinstance(marker,dict):marker={}
            if (binding['evidence_complete'] and marker.get('analysis_complete') is True
                    and all(marker.get(k)==v for k,v in binding.items())
                    and marker.get('plan_sha256')==_semantic_plan_hash(cached)):
                fresh_cover=plan.get('cover_spec')
                plan=cached
                if fresh_cover is not None:
                    plan['cover_spec']=fresh_cover
                    plan['semantic_cache']['plan_sha256']=_semantic_plan_hash(plan)
                restrict_context_shots(plan,sources)
                result=self.render_feedback(state,job,plan)
                return {'id':job['id'],'script_id':script['id'],'voice_id':voice['id'],'created':time.time(),**result}
            _preserve_semantic_history(semantic,raw)
        analysis_complete=False
        try:
            if state.get('daily_quality',{}).get('feedback'):
                observations, choices = describe_shots(self.settings, plan["shots"], plan["beats"],
                    review_feedback=state['daily_quality']['feedback'])
            else:
                observations, choices = describe_shots(self.settings, plan["shots"], plan["beats"])
            for shot in plan["shots"]:
                observation = observations.get(shot["id"], {})
                if observation.get("observation"):
                    shot["observation"] = str(observation["observation"])[:1200]
                    shot["tags"] = [str(t)[:100] for t in observation.get("tags", [])[:15]]
                for field in ('visual_type', 'selection_exclusion', 'evidence_status'):
                    if field in observation:
                        shot[field] = observation[field]
            for beat in plan["beats"]:
                choice = choices.get(beat["id"], {})
                beat['semantic_analysis_status']=choice.get('analysis_status')
                if choice.get('analysis_status') == 'opposite_only':
                    beat.update(options=[], needs_review=True, visual_alignment_gap='opposite_action_only')
                elif choice.get('analysis_status')=='no_usable_scenes':
                    beat.update(options=[],needs_review=True,visual_alignment_gap='no_usable_scenes')
                if choice.get('opposite_shot_ids'):
                    beat['opposite_shot_ids'] = choice['opposite_shot_ids']
                for field in ('incompatible_subject_shot_ids','promoted_subject_reference'):
                    if field in choice:beat[field]=choice[field]
                if choice.get("options"):
                    beat["options"] = choice["options"][:6]
                    if daily_quality_enabled(state):beat.pop('selected_shot_id',None)
                if type(choice.get("emphasis")) is int and choice["emphasis"] in (0, 1, 2):
                    beat["emphasis"] = choice["emphasis"]
                    beat["emphasis_reason"] = choice["emphasis_reason"]
            plan["semantic_provider"] = "codex_internal"
            analysis_complete=bool(plan['shots'] and plan['beats']) and all(
                s.get('evidence_status')=='observed' for s in plan['shots']) and all(
                b.get('semantic_analysis_status')=='ranked' for b in plan['beats'])
        except Exception as exc:
            from ..model_service import ModelServiceUnavailable,ModelResponseInvalid
            if isinstance(exc,(ModelServiceUnavailable,ModelResponseInvalid)):raise
            plan["warnings"].append("장면 의미 분석을 완료하지 못해 대체 후보를 사용했습니다: " + str(exc)[:200])
        if any(b.get('visual_alignment_gap') in {'opposite_action_only','no_usable_scenes'} for b in plan['beats']):
            from ..daily_quality import enabled as daily_quality_enabled, QualitySceneGap
            if daily_quality_enabled(state):
                raise QualitySceneGap([{'kind':'scene_gap','beat_id':b['id'],
                    'reason':'대사와 반대 동작만 확인됨' if b['visual_alignment_gap']=='opposite_action_only' else '제품 장면 없이 로고·전환 등 제외할 소스만 확인됨',
                    'search_query':(state.get('product') or state['title'])+' '+b['text']}
                    for b in plan['beats'] if b.get('visual_alignment_gap') in {'opposite_action_only','no_usable_scenes'}])
            raise ValueError('해당 대사와 반대 동작이거나 사용할 수 없는 소스만 확인됐습니다. 대본은 보존하고 다른 제품 장면을 확보해 주세요.')
        restrict_context_shots(plan, sources)
        # Verify files did not change while the semantic model was running.
        if _semantic_binding(state,script,voice,sources,base['plan'])!=binding:
            raise Conflict('의미 분석 중 실제 대본·음성·소스 또는 프레임 입력이 변경되었습니다.')
        plan['semantic_cache']={**binding,'analysis_complete':analysis_complete,
                                'plan_sha256':_semantic_plan_hash(plan)}
        _atomic_json(semantic, plan)
        result = self.render_feedback(state, job, plan)
        return {"id": job["id"], "script_id": script["id"], "voice_id": voice["id"], "created": time.time(), **result}

    def _revision(self, state, job):
        edit = next(e for e in state["edits"] if e["id"] == job["payload"]["edit_id"])
        plan = json.loads(Path(edit["plan_path"]).read_text(encoding="utf-8"))
        if job['payload'].get('thumbnail_only'):
            from ..studio_thumbnail import render_thumbnail
            result = render_thumbnail(self, state, job, edit, plan)
            return {"id": job["id"], "script_id": edit["script_id"], "voice_id": edit["voice_id"],
                    "parent_id": edit["id"], "created": time.time(), **result}
        if job['payload'].get('remotion_only'):
            from ..remotion_editor import render_overlays
            result = render_overlays(self, state, job, edit, plan)
            return {"id": job["id"], "script_id": edit["script_id"], "voice_id": edit["voice_id"],
                    "parent_id": edit["id"], "created": time.time(), **result}
        action = 'caption-export' if job['payload'].get('caption_only') else 'revise'
        result = self._process(state, job, action, {"plan": plan, "changes": job["payload"]["changes"]})
        return {"id": job["id"], "script_id": edit["script_id"], "voice_id": edit["voice_id"],
                "parent_id": edit["id"], "created": time.time(), **result}

    def _edit_request(self, state, job):
        from ..studio_ai import plan_revision
        p = job["payload"]
        edit = next(e for e in state["edits"] if e["id"] == p["edit_id"])
        plan = json.loads(Path(edit["plan_path"]).read_text(encoding="utf-8"))
        start, end = float(p["start"]), float(p["end"] or plan["duration"])
        if not 0 <= start < end <= plan["duration"] + .1: raise ValueError("수정할 구간을 확인하세요.")
        result = job["checkpoint"].get("interpretation")
        if result is None:
            result = plan_revision(self.settings, plan, p["request"], start, end)
            job["checkpoint"]["interpretation"] = result
            self.store.checkpoint(job, job["checkpoint"])
        job["payload"]["changes"] = [{"beat_id": c["beat_id"], "emphasis": c["emphasis"]} for c in result["changes"] if "emphasis" in c]
        candidates = [c["beat_id"] for c in result["changes"] if c.get("choose_candidates")]
        if job["payload"]["changes"]:
            output = self._revision(state, job)
        else:
            output = {"no_render": True}
        return {**output, "candidate_requests": candidates, "request_summary": result["summary"]}

    def _register(self, state, job):
        edit = next(e for e in state["edits"] if e["id"] == job["payload"]["edit_id"])
        return self._process(state, job, "register", {"plan_path": edit["plan_path"], "edit_id": edit["id"], "launch": job['payload'].get('launch', True)})
