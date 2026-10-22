"""Read-only API projections and task-scoped media access."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from ..studio_sources import source_goal
from .common import digest


class MediaMixin:
    def _collection_projection(self, state):
        collected_at, detected_at = state.get('collected_at'), state.get('hot_detected_at')
        if state.get('creation_mode') != 'self_shot' and self.settings.db_path.is_file():
            import sqlite3
            from contextlib import closing
            try:
                with closing(sqlite3.connect(self.settings.db_path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                    row = db.execute('SELECT first_seen FROM posts WHERE shortcode=?', (state.get('shortcode'),)).fetchone()
                    collected_at = collected_at or (row[0] if row else None)
                    from ..studio_titles import caption_title, missing_title
                    if missing_title(state.get('title'), state.get('shortcode'), state.get('id')):
                        caption = db.execute('SELECT caption FROM posts WHERE shortcode=?', (state.get('shortcode'),)).fetchone()
                        restored = caption_title(caption[0]) if caption else ''
                        if restored:
                            state['title'] = restored
                    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hot_detections'").fetchone():
                        hot = db.execute('SELECT detected_at FROM hot_detections WHERE shortcode=?', (state.get('shortcode'),)).fetchone()
                        detected_at = hot[0] if hot else detected_at
            except sqlite3.OperationalError:
                pass
        from ..collection_dates import post_collection_dates
        state.update(post_collection_dates(collected_at, detected_at))
        if state.get('creation_mode') == 'self_shot':
            from ..daily_hot import date_key
            state.update(collection_date_at=state['created'], collection_date_kst=date_key(state['created']),
                         collection_date_basis='self_shot')
        return state

    def brief(self, state):
        """Board polling never reads every historical timeline or sends its frames."""
        keys=('id','shortcode','title','revision','status','message','error','progress','created','updated',
            'creation_mode','collected_at','hot_detected_at','script_id','voice_id','edit_id',
            'approved_script_id','approved_voice_id','run_id','latest_completed_run_id','production_blockers')
        result={k:copy.deepcopy(state[k]) for k in keys if k in state}
        result['_summary']=True
        result['automation']={k:v for k,v in state.get('automation',{}).items()
            if k in {'protocol','stage','active','paused_by_user','consumed_by_daily_policy'}}
        result['self_shot']={'started':state.get('self_shot',{}).get('started')}
        result['source_search']={k:v for k,v in state.get('source_search',{}).items() if k in {'status','message','hold'}}
        result['source_acquisition']={'hold':state.get('source_acquisition',{}).get('hold')}
        result['source_goal']={'ready':state.get('source_goal',{}).get('ready',False)}
        result['original_text']='ready' if state.get('original_text') else ''
        for key in ('sources','scripts','voices'):
            result[key]=[{'id':row.get('id')} for row in state.get(key,[])]
        result['jobs']=self.store.jobs(state['id'])
        if getattr(self,'video_agents',None):result['video_agent']=self.video_agents.summary(state['id'])
        if getattr(self, 'supervisor', None):
            result['supervision'] = self.supervisor.summary(state['id'])
        edits={e['id']:e for e in state.get('edits',[])}
        current=edits.get(state.get('edit_id'),{})
        result['completed_video_ready']=bool(state.get('status')=='completed' and current.get('export_verified'))
        if current.get('cover_path'):result['thumbnail_url']=self.media_url(state['id'],current['cover_path'])
        result['pipeline']=[]
        from ..studio_workflow import STEPS
        for run in state.get('runs',[]):
            a=run.get('artifacts',{});edit=edits.get(a.get('edit_id'),{})
            ready={'sources':bool(a.get('sources')),'transcript':bool(a.get('original_text')),
                'script':bool(a.get('script_id')),'voice':bool(a.get('voice_id')),
                'project':bool(edit.get('portable_draft_path')),
                'export':bool(run.get('status')=='completed' and edit.get('export_verified'))}
            result['pipeline'].append({'id':run['id'],'number':run.get('number'), 'status':run.get('status'),
                'steps':[{'key':k,'status':'completed' if ready[k] else 'pending'} for k,_ in STEPS]})
        return self._collection_projection(result)

    def public(self, state):
        state = self._collection_projection(copy.deepcopy(state))
        if getattr(self,'video_agents',None):state['video_agent']=self.video_agents.summary(state['id'])
        state['source_search_retry_supported'] = True
        state['caption_editor_supported'] = True
        from ..remotion_editor import available
        state['remotion_editor_supported'] = available() and state.get('automation', {}).get('protocol') == 2
        state['thumbnail_editor_supported'] = state['remotion_editor_supported']
        if state.get("manifest_path"):
            state["sources"] = self._source_records([s["path"] for s in state["sources"]], state["manifest_path"], state["sources"])
            from ..source_audit import summarize
            state['source_audit'] = summarize(state.get('source_search_manifest_path') or state['manifest_path'],
                                               reviewed_sources=state['sources'])
        for collection in ("scripts", "voices", "edits"):
            for item in state[collection]:
                for field in ("path", "preview_path", "cover_path", "clean_preview_path", "export_path"):
                    if item.get(field):
                        item[field.replace("_path", "") + "_url"] = self.media_url(state["id"], item[field])
                if collection == "edits" and item.get("plan_path"):
                    plan = json.loads(Path(item["plan_path"]).read_text(encoding="utf-8"))
                    for shot in plan.get("shots", []):
                        frames=shot.get('frames') or []
                        shot["thumbnail_url"] = self.media_url(state["id"], frames[1 if len(frames)>1 else 0]) if frames else ''
                        shot["video_url"] = self.media_url(state["id"], shot["path"])
                    item["plan"] = plan
                    from ..source_diversity import body_usage_report
                    try:item['source_usage']=body_usage_report(plan)
                    except ValueError:item['source_usage_error']='원본 사용 정책 확인 필요'
                    background = plan.get('cover_spec', {}).get('background_path')
                    if background and Path(background).is_file() and Path(background).resolve().is_relative_to(self.settings.data_dir.resolve()):
                        item['thumbnail_background_url'] = self.media_url(state['id'], background)
        for source in state["sources"]:
            source["url"] = self.media_url(state["id"], source["path"])
        state['original_evidence'] = {'speech': [], 'screen_text': []}
        if state.get('transcript_path'):
            try:
                transcript = json.loads(Path(state['transcript_path']).read_text(encoding='utf-8'))
                state['original_evidence'] = {key: transcript.get(key, []) for key in ('speech', 'screen_text')}
                state['original_evidence']['speech_unavailable'] = transcript.get('methods', {}).get('speech') == 'unavailable'
            except (OSError, ValueError):
                pass
        reference = Path(state.get('reference_video') or '')
        if reference.is_file() and reference.is_relative_to(self.settings.data_dir.resolve()):
            state['reference_url'] = self.media_url(state['id'], reference)
        state["jobs"] = self.store.jobs(state["id"])
        state['source_goal'] = source_goal(state, self.settings.source_min_usable)
        state['events'] = self.store.events(state['id'])
        state['pipeline'] = self.pipeline(state)
        return state

    @staticmethod
    def _source_records(videos, manifest, existing=None):
        from urllib.parse import urlparse
        try:
            data = json.loads(Path(manifest).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            if existing is not None: return existing
            raise
        records = []
        for i, raw in enumerate(videos):
            path = Path(raw)
            record = dict(existing[i]) if existing else {"id": f"source-{i}", "path": str(path), "sha256": digest(path)}
            candidates = data.get('candidates', [])
            candidate = next((c for c in candidates if c.get('file_sha256') == record['sha256']), None)
            if candidate is None:
                candidate = next((c for c in candidates if c.get('downloaded_file')
                                  and (Path(manifest).parent / c['downloaded_file']).resolve() == path.resolve()), {})
            if not candidate and existing:
                records.append(record)
                continue
            url = candidate.get("original_url") or candidate.get("url", "")
            record.update(origin_url=url if urlparse(url).scheme in {"http", "https"} else "",
                          rights=candidate.get("rights", "unknown"), manifest_path=str(manifest))
            if candidate.get('title'):
                record['source_title']=str(candidate['title'])[:1000]
            for key in ('source_quality', 'functional_review', 'blur_required', 'watermark_masks', 'frame_hashes', 'editing_eligible',
                        'video_meta', 'reviewed_intervals', 'mask_review', 'relevance_review_required', 'similarity_warnings',
                        'format_warnings', 'portrait_geometry', 'presentation_review_required', 'presentation_review',
                        'presentation_rejection_reasons', 'source_role'):
                if key in candidate and key not in record:
                    record[key] = candidate[key]
            records.append(record)
        return records

    def media_url(self, task_id, raw):
        from urllib.parse import quote
        relative = Path(raw).resolve().relative_to(self.settings.data_dir.resolve()).as_posix()
        return f"/api/studio/{task_id}/media?file={quote(relative)}"

    def media(self, task_id, relative):
        state = self.store.get(task_id)
        path = (self.settings.data_dir / relative).resolve()
        own = self.folder(task_id).resolve()
        sources = {Path(s["path"]).resolve() for s in state["sources"]}
        # Registered finished versions and their background images belong to this
        # task even when a manually attached revision uses a separate data folder.
        for edit in state['edits']:
            for field in ('preview_path', 'export_path', 'clean_preview_path', 'cover_path'):
                if edit.get(field): sources.add(Path(edit[field]).resolve())
            if edit.get('plan_path') and Path(edit['plan_path']).is_file():
                plan = json.loads(Path(edit['plan_path']).read_text(encoding='utf-8'))
                background = plan.get('cover_spec', {}).get('background_path')
                if background: sources.add(Path(background).resolve())
        if state.get('reference_video'):
            sources.add(Path(state['reference_video']).resolve())
        if not path.is_file() or not path.is_relative_to(self.settings.data_dir.resolve()):
            raise ValueError("미디어 파일을 찾을 수 없습니다.")
        if not path.is_relative_to(own) and path not in sources:
            raise ValueError("이 작업의 미디어 파일이 아닙니다.")
        if path.suffix.lower() not in {".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".wav", ".txt", ".srt"}:
            raise ValueError("지원하지 않는 미디어 형식")
        return path
