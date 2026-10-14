"""Reference preparation, source refresh, script generation, and personal voice jobs."""
from __future__ import annotations

from ..studio_store import change_claimed

import hashlib
import copy
import json
import time
from pathlib import Path

from ..editing_adapter import _atomic_json, selected_source_videos
from ..local_compute import release_idle_voice, serialized_compute
from ..source_quality import editing_ready
from ..studio_store import uid
from ..studio_workflow import enabled, snapshot
from .common import digest


class GenerationMixin:
    def _prepare(self, state, job):
        job.setdefault('task_id', state['id'])
        if state.get('creation_mode') == 'photo_post':
            from ..photo_reference import prepare_studio, assert_creation_enabled
            assert_creation_enabled(self.settings,state,'prepare')
            return prepare_studio(self, state, job)
        if state.get('creation_mode') == 'self_shot':
            return self.prepare_self_shot(state, job)
        from ..source_finder import find_sources, probe_video
        from ..transcript import extract_transcript
        from ..script_rewriter import rewrite
        def progress(message, pct):
            change_claimed(self.store, job, lambda s, db: s.update(message=str(message)[:300], progress=pct))
        code = state["shortcode"]
        from ..reference_cache import reusable_reference
        # Search must see actual speech/OCR from this reference on the first run.
        transcripts = sorted(self.settings.transcript_dir.glob(f"{code}-*/transcript.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        transcript = None
        for path in transcripts:
            if not (reusable_reference(self.settings, code, path)
                    and reusable_reference(self.settings, code, path.parent/'reference.mp4')):
                continue
            try:
                cached = json.loads(path.read_text(encoding='utf-8'))
                if cached.get('speech') or cached.get('screen_text'):
                    transcript = path; break
            except (OSError, ValueError):
                continue
        if transcript is None:
            transcript = Path(extract_transcript(self.settings, code, progress)["json_path"])
        # Preserve acquired evidence even when the separate visual reading fails.
        change_claimed(self.store, job, lambda s, db: s.update(
            transcript_path=str(transcript), reference_video=str(transcript.parent/'reference.mp4'),
            reference_speech_text='\n'.join(str(r.get('text','')) for r in
                json.loads(transcript.read_text('utf-8')).get('speech',[]))))
        from ..reference_narrative import reference_text
        progress('원본의 음성·화면 참고 내용을 구분하는 중', 85)
        narrative = reference_text(self.settings, transcript)
        original = narrative['text']
        reference_path = transcript.parent/'reference.mp4'
        reference_duration = probe_video(reference_path).get('duration') if reference_path.is_file() else None
        def record_transcript(s, db):
            s.update(original_text=original, transcript_path=str(transcript), reference_video=str(transcript.parent / 'reference.mp4'))
            s['reference_duration'] = reference_duration
            s.update(reference_kind=narrative['kind'], reference_speech_text=narrative['speech_text'],
                     reference_text_evidence=narrative if narrative['kind'] in {'screen_text','mixed'} else None)
            if enabled(s):
                snapshot(s)
        change_claimed(self.store, job, record_transcript)
        if not original.strip():
            raise ValueError('집필할 원본 참고 내용이 없습니다.')
        if enabled(state):
            reference = transcript.parent / 'reference.mp4'
            if not reference.is_file():
                raise ValueError('대본 재가공에 필요한 기준 영상이 없습니다.')
            ids = job.get('payload', {}).get('source_ids')
            sources = [v for v in state['sources'] if ids is None or v['id'] in ids]
            manifest = self.folder(state['id'])/(job['id']+'-reference.json')
            _atomic_json(manifest, {'caption':state['title'], 'user_supplied':bool(ids),
                'downloaded':len(sources), 'candidates':[{'title':v.get('original_name',''),
                    'file_sha256':v['sha256'], 'original_url':v.get('origin_url',''),
                    'rights':v.get('rights','unknown'), 'selected_for_zip':True} for v in sources]})
            return {'original_text':original, 'reference_video':str(reference), 'transcript_path':str(transcript),
                    'sources':sources, 'manifest_path':str(manifest)}
        manifests = sorted(self.settings.source_dir.glob(f"{code}-*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        # User uploads are production assets, not another search request. Keep
        # their IDs/provenance so selected sources remain selected downstream.
        chosen_ids = job.get('payload', {}).get('source_ids')
        supplied = [v for v in state['sources'] if (chosen_ids is None or v['id'] in chosen_ids) and Path(v['path']).is_file()]
        if chosen_ids is not None and len(supplied) != len(set(chosen_ids)):
            raise ValueError('선택한 영상 파일이 없습니다. 영상을 다시 업로드하세요.')
        videos, manifest = [Path(v['path']) for v in supplied], None
        for candidate in ([] if supplied else manifests):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                data["candidates"] = [c for c in data.get("candidates", []) if editing_ready(c) or c.get('relevance_review_required') or c.get('presentation_review_required')]
                filtered = candidate.parent / "studio-selected.json"
                _atomic_json(filtered, data)
                videos = selected_source_videos(filtered)
                manifest = candidate
                break
            except (ValueError, OSError): continue
        if not videos:
            result = find_sources(self.settings, code, progress)
            manifest = Path(result["zip_path"]).parent / "manifest.json"
            data = json.loads(manifest.read_text(encoding='utf-8'))
            data['candidates'] = [c for c in data.get('candidates', []) if editing_ready(c) or c.get('relevance_review_required') or c.get('presentation_review_required')]
            filtered = manifest.parent / 'studio-selected.json'
            _atomic_json(filtered, data)
            videos = selected_source_videos(filtered)
        if not videos:
            raise ValueError('제작에 사용할 소스 영상이 없습니다. 자료를 확인하고 재시도하세요.')
        original = narrative['text']
        if not original.strip():
            raise ValueError('실제 발화 대본을 확보하지 못했습니다. OCR을 음성 대본으로 대체하지 않습니다.')
        if supplied:
            manifest = self.folder(state['id']) / (job['id']+'-user-sources.json')
            _atomic_json(manifest, {'caption': state['title'], 'user_supplied': True, 'downloaded': len(supplied), 'candidates': [
                {'title': v.get('original_name', ''), 'file_sha256': v['sha256'],
                 'original_url': v.get('origin_url', ''), 'rights': v.get('rights', 'unknown'),
                 'selected_for_zip': True} for v in supplied]})
        if state.get('automation'):
            reference = transcript.parent / 'reference.mp4'
            if not reference.is_file():
                raise ValueError('대본 재가공에 필요한 기준 영상이 없습니다.')
            products = json.loads(manifest.read_text(encoding='utf-8')).get('product_evidence', {}).get('products', []) if manifest else []
            product = next((p.get('ko') or p.get('en') for p in products if isinstance(p, dict)), '')
            return {'original_text':original, 'reference_video':str(reference), 'transcript_path':str(transcript),
                    'product':product or state['title'], 'sources':supplied or self._source_records(videos, manifest),
                    'manifest_path':str(manifest) if manifest else ''}
        acquired = supplied or self._source_records(videos, manifest)
        if not supplied:
            acquired, _ = self._review_source_records({**state, 'reference_video':str(transcript.parent/'reference.mp4')}, job, acquired, progress)
        existing = sorted((self.settings.data_dir / "productions" / code).glob("scripts-v*/scripts.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        script = json.loads(existing[0].read_text(encoding="utf-8")) if existing else rewrite(
            self.settings, transcript, manifest, self.folder(state["id"]) / "research", lambda *_: None)
        return {"text": script["variants"][0]["text"], "original_text": original,
                "sources": acquired,
                "manifest_path": str(manifest)}

    def _refresh_sources(self, state, job):
        try:
            return self._refresh_source_attempt(state,job)
        except Exception:
            self._preserve_source_attempt_history(state,job)
            raise

    def _refresh_source_attempt(self, state, job):
        job.setdefault('task_id', state['id'])
        if state.get('creation_mode') == 'self_shot':
            raise ValueError('내 촬영 영상 작업에는 외부 영상을 수집하지 않습니다.')
        job.setdefault('checkpoint', {})  # Legacy direct manual callers have no queue checkpoint yet.
        if job['payload'].get('daily_quality_repair'):
            from ..scene_narration_prepare import prepare_narration_context
            prepare_narration_context(self, state, job)
            if (state.get('scene_narration_plan')
                    and state['scene_narration_plan'].get('old_edit_id')==state.get('edit_id')):
                from ..scene_requirements import assess
                from ..scene_narration_prepare import _save, commit_identity
                expected_identity=commit_identity(state)
                coverage=assess(self.settings,state)
                _save(self,state,{'daily_quality':{'scene_requirements':coverage}},expected_identity)
                from ..quality_issue_scope import is_cover_scene_gap
                cover_gap=any(i.get('kind')=='cover' or is_cover_scene_gap(i) for i in state.get('daily_quality',{}).get('feedback',[]))
                if coverage.get('ready') and not cover_gap:
                    return {'sources':[], 'scene_requirements':coverage, 'searches':[], 'attempted_urls':[],
                        'source_search_manifest_path':state.get('source_search_manifest_path') or state.get('manifest_path')
                            or state['scene_narration_plan']['plan_path'],
                        'local_narration_preparation':True}
        from ..source_finder import find_sources
        from ..studio_pause import check_paused
        def progress(message, pct):
            check_paused(self.store, job)
            def update(s, db):
                old = s.get('source_search', {})
                strategy_message = str(message) if str(message).startswith('검색 전략 · ') else old.get('strategy_message', '')
                s['source_search'] = {'status':'running', 'message':str(message)[:300], 'progress':pct,
                                      'strategy_message':strategy_message[:400]}
            change_claimed(self.store, job, update)
        progress.check_cancel = lambda: check_paused(self.store, job)
        state = self._restore_source_attempt_history(state,job)
        self._bind_source_attempt_progress(state,job,progress)
        progress.check_cancel()
        deferred=(self._review_deferred_downloads(state,job,progress)
                  if not job.get('checkpoint',{}).get('refresh_discovery') and (
                      state.get('source_acquisition',{}).get('interrupted_attempts')
                      or any((r.get('review_completion') or {}).get('deferred_sources',0)
                         for r in state.get('source_acquisition',{}).get('rounds',[]))) else None)
        if deferred is None and state.get('sources') and not job.get('checkpoint',{}).get('refresh_discovery'):
            deferred=self._review_pending_local_sources(state,job,progress)
        if deferred is not None:
            for source in deferred['sources']:source['id']=uid('source-')
            from ..scene_requirements import assess, merge_sources
            deferred['scene_requirements']=assess(self.settings,{**state,
                'sources':merge_sources(state.get('sources',[]),deferred['sources'])}) if job['payload'].get('daily_quality_repair') else None
            if job['payload'].get('daily_quality_repair') and (deferred.get('scene_requirements') or {}).get('ready'):
                candidate=copy.deepcopy(state);candidate['sources']=merge_sources(state.get('sources',[]),deferred['sources'])
                candidate['daily_quality']['scene_requirements']=deferred['scene_requirements']
                deferred['cover_repair_evidence']=self.prepare_quality_cover_evidence(candidate,job)
            return deferred
        from ..source_search.strategy import restore_history
        acquisition = state.setdefault('source_acquisition', {})
        history = restore_history(acquisition)
        from ..source_search.strategy import merge_history, ACCESS_WAITS
        wait_receipts = job['checkpoint'].get('refresh_wait_history', [])
        for receipt in wait_receipts:
            history = merge_history(history, receipt.get('searches', []))
        excluded = list(dict.fromkeys([*acquisition.get('urls', []), *acquisition.get('inspected_urls', []),
            *(url for receipt in wait_receipts for key in ('attempted_urls','inspected_urls') for url in receipt.get(key, []))]))
        request=job['payload'].get('request', '')
        request_key=hashlib.sha256((state['shortcode']+'\n'+request).encode()).hexdigest()
        saved=job['checkpoint'].get('refresh_discovery')
        if saved:
            # A service wait during visual review resumes the received files.
            # It must not issue the same external search/download again.
            from ..source_quality import sha256_file
            receipt_path=Path(saved['path'])
            if saved['request_key']!=request_key or not receipt_path.is_file() or sha256_file(receipt_path)!=saved['sha256']:
                raise ValueError('저장된 추가 수집 입력·파일이 변경되었습니다. 같은 검색을 자동 반복하지 않습니다.')
            result=json.loads(receipt_path.read_text('utf-8'))
        else:
            ready_routes=(self._source_access_gate(state,job,history)
                          if wait_receipts or acquisition.get('waiting') or acquisition.get('rounds') else None)
            from ..source_quality import sha256_file
            result = find_sources(self.settings, state['shortcode'], progress, search_request=request,
                                  search_round=max(1, acquisition.get('round', 0)), previous_searches=history,
                                  exclude_urls=excluded,
                                  search_context={'completed_rounds':acquisition.get('bounded_rounds',0),
                                                  'ready_routes':ready_routes,
                                                  'expected_reference_sha256':(sha256_file(Path(state['reference_video']))
                                                      if state.get('reference_video') and Path(state['reference_video']).is_file() else None),
                                                  'rounds':[*acquisition.get('rounds',[]),
                                                      *[{'manifest_path':r['manifest_path']} for r in wait_receipts]]})
            from ..source_quality import sha256_file
            receipt_path=Path(result['zip_path']).parent/'refresh-result.json'
            _atomic_json(receipt_path,result)
            job['checkpoint']['refresh_discovery']={'path':str(receipt_path.resolve()),
                'sha256':sha256_file(receipt_path),'request_key':request_key}
            self.store.checkpoint(job,job['checkpoint'])
            self._preserve_source_attempt_history(state,job)
        manifest = Path(result['zip_path']).parent / 'manifest.json'
        videos = [manifest.parent / c['downloaded_file'] for c in result['candidates']
                  if c.get('selected_for_zip') and (editing_ready(c) or c.get('relevance_review_required') or c.get('presentation_review_required'))]
        records = self._source_records(videos, manifest)
        visual = job['checkpoint'].get('source_visual_review')
        visual_key = request_key + ':' + job['checkpoint']['refresh_discovery']['sha256']
        if visual:
            path = Path(visual['path'])
            if visual['input_key'] != visual_key or not path.is_file() or sha256_file(path) != visual['sha256']:
                raise ValueError('추가 수집의 저장된 시각 검토 근거가 변경되었습니다.')
            cached = json.loads(path.read_text('utf-8'))['sources']
            records = [copy.deepcopy(cached.get(s['sha256'], s)) for s in records]
        else:
            path = manifest.parent / ('source-review-' + (job.get('claim_token') or job['id']) + '.json')
            _atomic_json(path, {'input_key':visual_key, 'sources':{}})
            job['checkpoint']['source_visual_review']={'path':str(path.resolve()),
                'sha256':sha256_file(path), 'input_key':visual_key}
            self.store.checkpoint(job, job['checkpoint'])
        records, _ = self._review_source_records(state, job, records, progress)
        from ..source_audit import reviewed_platform_outcomes
        outcomes = reviewed_platform_outcomes(manifest, result, records)
        for record in records:
            record['id'] = uid('source-')
        from ..scene_requirements import assess, merge_sources
        coverage = assess(self.settings,{**state,'sources':merge_sources(state.get('sources',[]),records)}) if job['payload'].get('daily_quality_repair') else None
        cover_evidence=None
        if job['payload'].get('daily_quality_repair') and coverage and coverage.get('ready'):
            from ..quality_issue_scope import is_cover_scene_gap
            if any(i.get('kind')=='cover' or is_cover_scene_gap(i) for i in state.get('daily_quality',{}).get('feedback',[])):
                candidate=copy.deepcopy(state);candidate['sources']=merge_sources(state.get('sources',[]),records)
                candidate['daily_quality']['scene_requirements']=coverage
                cover_evidence=self.prepare_quality_cover_evidence(candidate,job)
        from ..source_search.strategy import candidate_ledgers
        ledgers=candidate_ledgers(result.get('candidates', []))
        waits=[s for s in result.get('search_audit', []) if s.get('status') in ACCESS_WAITS]
        waits += ledgers['access_waits']
        if waits:
            job['checkpoint'].setdefault('refresh_wait_history', []).append({
                **job['checkpoint'].pop('refresh_discovery'), 'manifest_path':str(manifest),
                'visual_review':job['checkpoint'].pop('source_visual_review'),
                'searches':result.get('search_audit', []), **ledgers})
            self.store.checkpoint(job, job['checkpoint'])
        return {'source_search_manifest_path': str(manifest), 'sources': records, 'scene_requirements':coverage,
                'cover_repair_evidence':cover_evidence,
                'source_policy':result.get('source_policy'), 'platform_outcomes':outcomes,
                'platform_targets': result.get('platform_targets', {}), 'searches':result.get('search_audit', []),
                **ledgers, 'access_waits':waits}

    def _rewrite(self, state, job):
        if state.get('creation_mode') == 'self_shot':
            return self.write_self_shot(state, job)
        from ..studio_services import ensure_local
        from ..studio_automation import rewrite
        if state.get('automation', {}).get('needs_top_pick') and state.get('script_candidates') and not job['payload'].get('quality_rewrite'):
            from ..studio_top_pick import choose
            candidates = state['script_candidates']
            index, result = choose(self.settings, state, list(enumerate(candidates)))
            return {'text':candidates[index]['text'], 'top_pick':result, 'selected_candidate':index,
                    'selection_reason':result['reason']}
        ensure_local(self.settings, 'script')
        return rewrite(self, state, job)

    def _proposal(self, state, job):
        from ..studio_ai import propose_script
        script = next(s for s in state["scripts"] if s["id"] == job["payload"]["script_id"])
        text = job['payload'].get('base_text', script['text'])
        evidence = {**state, 'original_text':job['payload'].get('original_text', state.get('reviewed_original_text', state['original_text']))}
        return {**propose_script(self.settings, evidence, text, job["payload"]["request"]),
                'base_text':text, 'original_text':evidence['original_text'],
                'base_hash':hashlib.sha256(text.encode()).hexdigest(),
                "id": job["id"], "script_id": script["id"], "created": time.time()}

    @serialized_compute('voice')
    def _voice(self, state, job):
        from ..voicebench_adapter import VoiceBenchAdapter, verify_wav
        p = job["payload"]
        manual_voice = p.get('voice_mode') == 'manual' and bool(p.get('voice_profile_id'))
        voice_profile = p.get('voice_profile_id') if manual_voice else None
        script = next(s for s in state["scripts"] if s["id"] == p["script_id"])
        folder = self.folder(state["id"]) / p["voice_id"]
        folder.mkdir(exist_ok=True)
        voice = folder / "original.wav"
        metadata = folder / "tts.json"
        if metadata.is_file() and not manual_voice:
            cached = json.loads(metadata.read_text(encoding='utf-8'))
            if cached.get('voice_profile_id'):
                raise ValueError('저장된 음성은 다른 목소리입니다. 본인 복제 음성으로 새 버전을 만들어야 합니다.')
        if not (voice.is_file() and metadata.is_file()):
            if state.get('automation'):
                from ..studio_services import ensure_local
                ensure_local(self.settings, 'voice')
            def checkpoint(request_id):
                job["checkpoint"]["request_id"] = request_id
                job['checkpoint'].pop('retry_requested', None)
                self.store.checkpoint(job, job["checkpoint"])
            result = VoiceBenchAdapter(self.settings).synthesize(p.get('spoken_text', script["text"]), voice,
                progress=lambda message, pct: change_claimed(self.store, job, lambda s, db: s.update(message=message, progress=pct)),
                request_id=job["checkpoint"].get("request_id"), on_submitted=checkpoint,
                retry_failed=bool(job['checkpoint'].get('retry_requested')), generation_key=p.get('generation_key'),
                require_personal_clone=not manual_voice,
                **({'before_save':lambda:self.store.assert_owned(job)} if job.get('claim_token') else {}),
                **({'voice_profile_id':voice_profile} if voice_profile else {}))
            _atomic_json(metadata, result)
            release_idle_voice(self.settings, best_effort=True)
        result = json.loads(metadata.read_text(encoding="utf-8"))
        from ..daily_quality import enabled as daily_quality_enabled, QualitySceneGap
        if daily_quality_enabled(state) and (result.get('speech_plan') or {}).get('segment_count',1)>1:
            raise QualitySceneGap([{'kind':'voice_consistency','beat_id':'',
                'reason':'쇼츠 대본이 여러 번의 합성으로 나뉘어 톤이 바뀔 위험이 있음. 전체를 한 번에 생성하도록 자연스럽게 간결하게 재작성.',
                'search_query':''}])
        if p["speed"] != 1:
            voice = folder / "approved-listening.wav"
            self._process(state, job, "audio", {"input": str(folder / "original.wav"), "output": str(voice), "speed": p["speed"]})
        info = verify_wav(voice.read_bytes())
        return {"id": p["voice_id"], "script_id": script["id"], "path": str(voice), "sha256": digest(voice),
                "script_sha256": hashlib.sha256(script['text'].encode()).hexdigest(),
                "created": time.time(), "speed": p["speed"], "duration": info["duration"],
                "spoken_text": p.get('spoken_text', script['text']),
                "voice_profile_id": result.get('voice_profile_id') or '',
                "request_id": result["voicebench_request_id"], "quality_control": result.get("quality_control"),
                "speech_plan":result.get("speech_plan")}
