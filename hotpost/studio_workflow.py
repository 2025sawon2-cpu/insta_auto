"""Versioned automatic production. Feedback is staged, never a live input mutation."""
from __future__ import annotations

from .studio_store import change_claimed

import copy
import hashlib
import json
import math
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from .studio_store import Conflict, uid
from .source_quality import sha256_file

STEPS = [('sources', '소스 확보'), ('transcript', '원본 대본 추출'),
         ('script', 'Top Pick 대본'), ('voice', 'TTS'), ('project', 'CapCut 프로젝트'), ('export', 'MP4 내보내기')]


def enabled(state):
    return state.get('automation', {}).get('protocol') == 2


def current_run(state):
    return next((r for r in state.get('runs', []) if r['id'] == state.get('run_id')), None)


def init_run(state):
    if current_run(state):
        return current_run(state)
    run = dict(id=uid('run-'), number=len(state.setdefault('runs', []))+1,
               created=time.time(), status='running', inputs={}, artifacts={})
    if state.get('source_policy'):
        run['source_policy'] = copy.deepcopy(state['source_policy'])
    state['runs'].append(run)
    state['run_id'] = run['id']
    return run


def snapshot(state):
    run = init_run(state)
    run['artifacts'].update({k: copy.deepcopy(state.get(k)) for k in
        ('script_id', 'voice_id', 'edit_id', 'transcript_path', 'original_text', 'manifest_path',
         'reference_kind', 'reference_speech_text', 'reference_text_evidence')})
    ids = run['inputs'].get('source_ids')
    run['artifacts']['sources'] = copy.deepcopy([s for s in state['sources'] if ids is None or s['id'] in ids])
    script = next((s for s in state['scripts'] if s['id']==state.get('script_id')), {})
    pick = state.get('selected_candidate')
    candidates = state.get('script_candidates', [])
    if isinstance(pick,int) and 0<=pick<len(candidates) and candidates[pick].get('text')==script.get('text'):
        run['artifacts']['top_pick'] = copy.deepcopy(state.get('top_pick'))
    return run


def transient(exc):
    from .retry_policy import classify_failure
    return classify_failure(exc)['retryable']


def validate_edit_feedback(edit, changes):
    """Reject invalid editor input before it replaces a usable production run."""
    plan = json.loads(Path(edit['plan_path']).read_text(encoding='utf-8'))
    beats = {b['id']: b for b in plan['beats']}
    cues = {c['id']: dict(c) for c in plan['cues']}
    for change in changes:
        beat = beats.get(change['beat_id'])
        if beat is None:
            raise ValueError('존재하지 않는 구간입니다.')
        if 'shot_id' in change and change['shot_id'] not in {o['shot_id'] for o in beat['options']}:
            raise ValueError('제안된 장면 후보에서 선택하세요.')
        if 'emphasis' in change and (type(change['emphasis']) is not int or change['emphasis'] not in (0, 1, 2)):
            raise ValueError('잘못된 강조 강도')
        if 'text' in change:
            text = change['text']
            if not isinstance(text, str) or not text.strip() or '\n' in text.strip() or len(text.strip()) > 100:
                raise ValueError('자막은 비어 있지 않은 한 줄로 입력하세요.')
        cue = cues[beat['cue_id']]
        for key in ('start', 'end'):
            if key in change:
                value = float(change[key])
                if not math.isfinite(value):
                    raise ValueError('자막 시간은 숫자로 입력하세요.')
                cue[key] = value
    previous = 0
    for cue in cues.values():
        if not previous <= cue['start'] < cue['end'] <= plan['duration'] + .001:
            raise ValueError('자막 시간이 겹치거나 음성 범위를 벗어났습니다.')
        previous = cue['end']


def capcut_running():
    if os.name == 'nt':
        p = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq CapCut.exe', '/FO', 'CSV', '/NH'],
                           capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        return b'capcut.exe' in p.stdout.lower()
    p = subprocess.run(['pgrep', '-ix', 'CapCut'], capture_output=True, timeout=15)
    return p.returncode == 0


class WorkflowMixin:
    def upload_source(self, task_id, stream, length, name):
        from .source_finder import probe_video
        self.store.get(task_id)
        suffix = Path(name).suffix.lower()
        if suffix not in {'.mp4','.mov','.webm'}: raise ValueError('MP4, MOV, WEBM 영상을 선택하세요.')
        path = self.folder(task_id)/'uploads'/(uid('source-')+suffix)
        path.parent.mkdir(exist_ok=True)
        try:
            with path.open('wb') as out:
                remaining = length
                while remaining:
                    chunk = stream.read(min(1024*1024,remaining))
                    if not chunk: raise ValueError('업로드가 중단되었습니다.')
                    out.write(chunk)
                    remaining -= len(chunk)
            info = probe_video(path)
            if not info or float(info.get('duration') or 0) <= 0 or not info.get('width'): raise ValueError('재생 가능한 영상이 아닙니다.')
            sha = sha256_file(path)
            def add(s, db):
                if not any(v['sha256']==sha for v in s['sources']):
                    if s.get('creation_mode') == 'self_shot' and len(s['sources']) >= 20:
                        raise ValueError('내 촬영 영상은 작업 하나에 최대 20개까지 추가할 수 있습니다.')
                    s['sources'].append(dict(id=path.stem,path=str(path),sha256=sha,origin_url='',rights='user_supplied',original_name=Path(name).name))
                self.store.event(db, task_id, 'source_uploaded', {'name':Path(name).name})
            saved = self.store.change(task_id,add)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        if not any(v['path']==str(path) for v in saved['sources']): path.unlink(missing_ok=True)
        return self.public(saved)

    def workflow_action(self, task_id, action, data):
        state = self.store.get(task_id)
        if state.get('creation_mode') == 'self_shot' and action == 'use-sources':
            return self.start_self_shot(task_id, data)
        if action in {'make-video','save-feedback','regenerate-voice'} and 'voice_profile_id' in data:
            profile = data['voice_profile_id']
            if not isinstance(profile,str) or len(profile)>100: raise ValueError('목소리 목록에서 선택하세요.')
            if profile:
                from .voicebench_adapter import VoiceBenchAdapter
                voices=VoiceBenchAdapter(self.settings).voices().get('voices',[])
                if not any(v['id']==profile and v.get('available') for v in voices):
                    raise ValueError('이 목소리는 아직 준비되지 않았어요. 사용 가능한 목소리를 선택하세요.')
        if action == 'use-sources':
            def continue_with_sources(s, db):
                ids = data.get('source_ids')
                available = {v['id']: v for v in s['sources']}
                if not isinstance(ids, list) or not ids or any(not isinstance(v, str) or v not in available for v in ids):
                    raise ValueError('제작에 사용할 영상을 한 개 이상 선택하세요.')
                if any(not Path(available[v]['path']).is_file() for v in ids):
                    raise ValueError('선택한 영상 파일이 없습니다. 영상을 다시 업로드하세요.')
                if s.get('automation', {}).get('stage', 'prepare') != 'prepare':
                    raise Conflict('이미 다음 제작 단계입니다. 소스 선택을 저장한 뒤 변경사항을 반영해 주세요.')
                if not s.get('automation') and s['status'] != 'preparing' and not (
                    s['status'] == 'attention' and db.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind='prepare' AND status='failed'", (task_id,)).fetchone()
                ):
                    raise Conflict('이미 대본 검토를 시작한 영상입니다. 현재 제작 단계를 먼저 마무리하세요.')
                if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status='running' AND kind NOT IN ('proposal','suggest_edit')", (task_id,)).fetchone():
                    raise Conflict('자료 작업이 실행 중입니다. 업로드한 영상은 보관되며, 현재 작업이 끝난 뒤 이어갈 수 있습니다.')
                db.execute("UPDATE jobs SET status='done' WHERE task_id=? AND kind='prepare' AND status IN ('queued','paused','failed')", (task_id,))
                if s.get('automation'):
                    s['automation'].update(active=True, paused_by_user=False, stage='prepare')
                if enabled(s):
                    run = snapshot(s)
                    run['status'] = 'running'
                    run['inputs']['source_ids'] = list(dict.fromkeys(ids))
                self.store.enqueue(db, task_id, 'prepare', {'source_ids': list(dict.fromkeys(ids))}, uid('manual-sources:'))
                s.update(status='preparing', error='', progress=0, message='선택한 영상으로 자료 준비를 이어갑니다')
                self.store.event(db, task_id, action, {'count': len(set(ids))})
            return self.public(self.store.change(task_id, continue_with_sources, data.get('revision')))
        if action == 'start-auto':
            def start(s, db):
                if s.get('automation') and not s.get('top_pick') and s.get('script_candidates'):
                    s['automation']['needs_top_pick'] = True
                auto = s.setdefault('automation', {})
                self.release_source_hold(s)
                auto.update(protocol=2, active=True, paused_by_user=False, selection_mode='manual_resume')
                auto.pop('consumed_by_daily_policy', None)
                auto.pop('pause_reason', None)
                db.execute("UPDATE jobs SET status='queued' WHERE task_id=? AND status='paused'", (task_id,))
                init_run(s)
                # Existing manual work and its assets become the first version.
                if s.get('sources') and s.get('original_text'):
                    self._advance_auto(s, db)
                else:
                    self.store.enqueue(db, task_id, 'prepare', {}, 'prepare:'+task_id)
                self.store.event(db, task_id, 'start-auto', {})
            return self.public(self.store.change(task_id, start, data.get('revision')))
        if not enabled(state):
            return None
        actions = {'save-feedback', 'save-script', 'restore-script', 'apply-proposal', 'regenerate-voice',
                   'revise-edit', 'request-edit', 'reproduce', 'discard-feedback', 'select-candidate', 'discard-edit-feedback',
                   'save-captions', 'export-edit', 'make-video', 'save-overlays', 'export-overlays', 'save-thumbnail', 'export-thumbnail'}
        if action not in actions:
            return None
        def change(s, db):
            if data.get('feedback_revision') is not None and data['feedback_revision'] != s.get('feedback_revision',0):
                raise Conflict('다른 화면에서 피드백이 변경되었습니다. 최신 내용을 확인한 뒤 다시 저장하세요.')
            feedback = s.setdefault('feedback', {})
            if action in {'save-thumbnail', 'export-thumbnail'}:
                from .studio_thumbnail import validate_thumbnail
                from .remotion_editor import available
                if not available():
                    raise RuntimeError('Remotion 연결이 준비되지 않았습니다.')
                edit = next((e for e in s['edits'] if e['id'] == data.get('edit_id')), None)
                if not edit or edit['id'] != s.get('edit_id'):
                    raise Conflict('새 편집 영상이 준비되었습니다. 이전 썸네일을 보관한 뒤 새 영상을 확인하세요.')
                if set(feedback)-{'thumbnail_document', 'base_edit_id', 'thumbnail_only'}:
                    raise Conflict('다른 편집 수정사항을 먼저 반영하거나 취소한 뒤 썸네일을 저장하세요.')
                if feedback.get('base_edit_id', edit['id']) != edit['id']:
                    raise Conflict('이전 편집 버전에 저장한 썸네일 수정이 있습니다.')
                if s.get('pending_reproduction') or db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('queued','running') AND kind NOT IN ('collect_sources','refresh_sources','proposal','suggest_edit')", (task_id,)).fetchone():
                    raise Conflict('진행 중인 영상 제작이 끝난 뒤 썸네일을 저장하세요.')
                if not Path(edit.get('export_path') or '').is_file():
                    raise ValueError('완성 영상이 준비된 뒤 썸네일을 반영하세요.')
                document = validate_thumbnail(data.get('document'), edit['duration'])
                feedback.update(thumbnail_document=document, base_edit_id=edit['id'], thumbnail_only=True)
                if action == 'save-thumbnail':
                    s['feedback_revision'] = s.get('feedback_revision', 0)+1
                    self.store.event(db, task_id, action, {})
                    return
            if action in {'save-overlays', 'export-overlays'}:
                from .remotion_editor import validate_document, available
                if not available():
                    raise RuntimeError('Remotion 연결이 준비되지 않았습니다.')
                edit = next((e for e in s['edits'] if e['id'] == data.get('edit_id')), None)
                if not edit or edit['id'] != s.get('edit_id'):
                    raise Conflict('새 편집 영상이 준비되었습니다. 이전 편집을 보관한 뒤 새 영상을 확인하세요.')
                if set(feedback)-{'overlay_document', 'base_edit_id', 'remotion_only'}:
                    raise Conflict('대본·음성·소스 또는 기존 자막 수정사항을 먼저 반영하거나 취소하세요.')
                if feedback.get('base_edit_id', edit['id']) != edit['id']:
                    raise Conflict('다른 편집 버전에 저장한 꾸미기가 있습니다.')
                if s.get('pending_reproduction') or db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('queued','running') AND kind NOT IN ('collect_sources','refresh_sources','proposal','suggest_edit')", (task_id,)).fetchone():
                    raise Conflict('진행 중인 영상 제작이 끝난 뒤 편집을 저장하세요.')
                document = validate_document(data.get('document'), edit['duration'])
                feedback.update(overlay_document=document, base_edit_id=edit['id'], remotion_only=True)
                if action == 'save-overlays':
                    s['feedback_revision'] = s.get('feedback_revision', 0)+1
                    self.store.event(db, task_id, action, {})
                    return
            if action == 'make-video':
                if 'text' in data:
                    text = str(data['text']).strip()
                    if not text or len(text) > 3000: raise ValueError('대본은 1~3000자로 입력하세요.')
                    feedback['script_text'] = text
            if action in {'save-captions','export-edit'}:
                edit = next((e for e in s['edits'] if e['id']==data.get('edit_id')), None)
                if not edit or edit['id'] != s.get('edit_id'):
                    raise Conflict('새 편집 영상이 준비되었습니다. 이전 영상의 수정 내용을 보관한 뒤 새 영상을 확인하세요.')
                if set(feedback)-{'changes','base_edit_id','caption_only'}:
                    raise Conflict('소스·대본·음성의 저장된 변경사항을 먼저 반영하거나 초기화한 뒤 자막을 편집하세요.')
                if feedback.get('base_edit_id',edit['id']) != edit['id']:
                    raise Conflict('이전 버전에 저장한 자막 수정이 있습니다. 보관 내용을 확인하고 구간 수정을 초기화한 뒤 새 영상을 편집하세요.')
                if any(set(c)-{'beat_id','text','start','end'} for c in feedback.get('changes',[])):
                    raise Conflict('저장된 장면·강조 수정이 있습니다. 먼저 반영하거나 구간 수정을 초기화하세요.')
                changes = data.get('changes')
                if not isinstance(changes,list) or any(not isinstance(c,dict) or not isinstance(c.get('beat_id'),str) or set(c)-{'beat_id','text','start','end'} for c in changes):
                    raise ValueError('자막 문구와 시간만 수정할 수 있습니다.')
                if len({c['beat_id'] for c in changes}) != len(changes): raise ValueError('중복된 자막 구간입니다.')
                validate_edit_feedback(edit,changes)
                plan=json.loads(Path(edit['plan_path']).read_text(encoding='utf-8'))
                cues={c['id']:c for c in plan['cues']}; beats={b['id']:b for b in plan['beats']}
                changes=[c for c in changes if any(c[k]!=cues[beats[c['beat_id']]['cue_id']][k] for k in ('text','start','end') if k in c)]
                if action=='export-edit':
                    if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('queued','running') AND kind NOT IN ('collect_sources','refresh_sources','proposal','suggest_edit')",(task_id,)).fetchone():
                        raise Conflict('현재 제작 또는 내보내기가 끝나면 다시 내보낼 수 있습니다.')
                    if not changes and not edit.get('export_path'):
                        changes=[{'beat_id':b['id'],**{k:cues[b['cue_id']][k] for k in ('text','start','end')}} for b in plan['beats']]
                for k in ('changes','base_edit_id','caption_only'): feedback.pop(k,None)
                if changes: feedback.update(changes=copy.deepcopy(changes),base_edit_id=edit['id'],caption_only=True)
                if action=='save-captions' or not changes:
                    s['feedback_revision']=s.get('feedback_revision',0)+1
                    self.store.event(db,task_id,action,{})
                    return
            if action == 'discard-feedback':
                s['feedback'] = {}
            elif action == 'discard-edit-feedback':
                feedback.pop('changes', None)
                feedback.pop('base_edit_id', None)
                feedback.pop('caption_only', None)
                feedback.pop('overlay_document', None)
                feedback.pop('remotion_only', None)
                feedback.pop('thumbnail_document', None)
                feedback.pop('thumbnail_only', None)
            elif action in {'save-script', 'restore-script', 'apply-proposal', 'select-candidate'}:
                if action == 'save-script': text = str(data.get('text', '')).strip()
                elif action == 'restore-script': text = next(v['text'] for v in s['scripts'] if v['id'] == data['script_id'])
                elif action == 'select-candidate': text = s['script_candidates'][int(data['index'])]['text']
                else:
                    proposal = next(p for p in s['proposals'] if p['id'] == data['proposal_id'])
                    base = str(data.get('base_text', feedback.get('script_text') or next(v['text'] for v in s['scripts'] if v['id'] == s['script_id']))).strip()
                    if proposal.get('base_hash') and proposal['base_hash'] != hashlib.sha256(base.encode()).hexdigest():
                        raise Conflict('수정안 생성 후 대본이 바뀌었습니다. 다시 요청하세요.')
                    if proposal.get('original_text', s.get('reviewed_original_text', s['original_text'])) != s.get('reviewed_original_text', s['original_text']):
                        raise Conflict('원본 발화가 교정되었습니다. 교정한 발화를 기준으로 수정안을 다시 요청하세요.')
                    text = proposal['text']
                if not text or len(text) > 3000: raise ValueError('대본은 1~3000자로 입력하세요.')
                feedback['script_text'] = text
            elif action in {'save-feedback', 'regenerate-voice', 'make-video'}:
                if 'voice_profile_id' in data:
                    feedback['voice_profile_id'] = data['voice_profile_id']
                    feedback['voice_selection_mode'] = 'manual' if data['voice_profile_id'] else 'personal_default'
                if 'speed' in data:
                    speed = float(data['speed'])
                    if not math.isfinite(speed) or not .8 <= speed <= 1.25: raise ValueError('속도는 0.8~1.25배입니다.')
                    feedback['speed'] = speed
                if 'pronunciations' in data:
                    pairs = data['pronunciations']
                    if not isinstance(pairs, list) or len(pairs) > 50: raise ValueError('발음 교정 목록을 확인하세요.')
                    for pair in pairs:
                        if not isinstance(pair, dict) or not all(isinstance(pair.get(k), str) and 0 < len(pair[k]) <= 100 for k in ('from', 'to')):
                            raise ValueError('발음 교정은 원문과 읽을 발음을 입력하세요.')
                    feedback['pronunciations'] = pairs
                if 'source_ids' in data:
                    if data.get('source_selection_mode') == 'automatic':
                        raise ValueError('자동 소스 재선정과 직접 소스 선택을 동시에 요청할 수 없습니다.')
                    ids = data['source_ids']
                    if not isinstance(ids, list) or not set(ids) <= {v['id'] for v in s['sources']}:
                        raise ValueError('보유한 소스에서 선택하세요.')
                    feedback['source_ids'] = list(dict.fromkeys(ids))
                    feedback['source_selection_mode'] = 'manual'
                if 'source_selection_mode' in data:
                    if data['source_selection_mode'] != 'automatic' or 'source_ids' in data:
                        raise ValueError('자동 소스 재선정 요청을 확인하세요.')
                    feedback.pop('source_ids', None)
                    feedback['source_selection_mode'] = 'automatic'
                if action == 'regenerate-voice': feedback['regenerate_voice'] = True
            elif action == 'revise-edit':
                feedback.pop('caption_only', None)
                edit = next(e for e in s['edits'] if e['id'] == data['edit_id'])
                if s.get('edit_id') and edit['id'] != s['edit_id']:
                    raise Conflict('새 편집 영상이 준비되었습니다. 입력 내용을 보관한 뒤 새로고침하여 새 영상의 구간을 확인하세요.')
                changes = data.get('changes', [])
                if not isinstance(changes, list) or not changes: raise ValueError('수정할 구간을 선택하세요.')
                if feedback.get('base_edit_id', edit['id']) != edit['id']: raise Conflict('다른 편집 버전의 수정이 저장되어 있습니다.')
                feedback['base_edit_id'] = edit['id']
                by_id = {c['beat_id']: c for c in feedback.get('changes', [])}
                for c in changes:
                    if not isinstance(c, dict) or not isinstance(c.get('beat_id'), str): raise ValueError('올바르지 않은 구간')
                    by_id.setdefault(c['beat_id'], {}).update(c)
                validate_edit_feedback(edit, list(by_id.values()))
                feedback['changes'] = list(by_id.values())
            elif action == 'request-edit':
                if data.get('edit_id') != s.get('edit_id'):
                    raise Conflict('새 편집 영상이 준비되었습니다. 새로고침하여 수정할 구간을 확인하세요.')
                request = str(data.get('request', '')).strip()
                if not request: raise ValueError('수정 요청을 입력하세요.')
                self.store.enqueue(db, task_id, 'suggest_edit', {**data, 'feedback_hash': self.feedback_hash(feedback)}, uid('suggest:'))
            if action in {'reproduce','export-edit','make-video','export-overlays','export-thumbnail'}:
                if s.get('pending_reproduction'): raise Conflict('이미 재제작이 대기 중입니다.')
                if not feedback: raise ValueError('반영할 변경사항을 먼저 저장하세요.')
                if (feedback.get('changes') or 'overlay_document' in feedback or 'thumbnail_document' in feedback) and any(k in feedback for k in ('script_text', 'speed', 'pronunciations', 'regenerate_voice', 'source_ids', 'source_selection_mode', 'voice_profile_id')):
                    raise Conflict('대본·음성·소스를 바꾸면 장면 구성이 달라집니다. 구간 수정만 초기화한 뒤 재제작하고, 새 영상에서 장면·자막을 조정하세요. 기존 완성본은 보존됩니다.')
                ids = feedback.get('source_ids', [v['id'] for v in s['sources']])
                if not ids and not feedback.get('thumbnail_only'): raise ValueError('사용할 소스를 한 개 이상 선택하세요.')
                snapshot(s)
                # Reproduce is an explicit start request. A later pause must
                # remain authoritative when the running step eventually ends.
                s['automation'].update(active=True, paused_by_user=False, selection_mode='manual_resume')
                s['automation'].pop('consumed_by_daily_policy', None)
                s['automation'].pop('pause_reason', None)
                s['pending_reproduction'] = copy.deepcopy(feedback)
                s['feedback'] = {}
                db.execute("UPDATE jobs SET status='superseded' WHERE task_id=? AND status IN ('queued','paused') AND kind NOT IN ('collect_sources','refresh_sources','proposal','suggest_edit')", (task_id,))
                if not db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status='running' AND kind NOT IN ('collect_sources','refresh_sources','proposal','suggest_edit')", (task_id,)).fetchone():
                    self.activate_reproduction(s, db)
                else:
                    s['message'] = '현재 단계 결과 저장 후 수정본 제작으로 전환합니다'
            self.store.event(db, task_id, action, {})
            s['feedback_revision'] = s.get('feedback_revision',0)+1
        return self.public(self.store.change(task_id, change, None if 'feedback_revision' in data else data.get('revision')))

    @staticmethod
    def feedback_hash(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def activate_reproduction(self, s, db):
        if s.get('automation', {}).get('paused_by_user'):
            return
        feedback = s.pop('pending_reproduction')
        old = snapshot(s)
        old_script = next((x['text'] for x in s['scripts'] if x['id']==s.get('script_id')), '')
        old_sources = old['inputs'].get('source_ids') or [x['id'] for x in s['sources']]
        changed_narration = 'script_text' in feedback and feedback['script_text'] != old_script
        automatic_sources = feedback.get('source_selection_mode') == 'automatic'
        changed_sources = automatic_sources or ('source_ids' in feedback and set(feedback['source_ids']) != set(old_sources))
        if s.get('reviewed_scene_rules') and (changed_narration or changed_sources):
            # Bounded manual review belongs to those exact narration/source
            # inputs. New user edits return to normal actual-frame selection.
            rules = s.pop('reviewed_scene_rules')
            self.store.event(db,s['id'],'reviewed_scenes_invalidated',
                             {'rules':rules,'changed_narration':changed_narration,'changed_sources':changed_sources})
        if old['status'] != 'completed': old['status'] = 'superseded'
        old_inputs = copy.deepcopy(old['inputs'])
        old_inputs.pop('changes', None)
        old_inputs.pop('regenerate_voice', None)
        old_inputs.pop('overlay_document', None)
        old_inputs.pop('remotion_only', None)
        old_inputs.pop('thumbnail_document', None)
        old_inputs.pop('thumbnail_only', None)
        if automatic_sources:
            # A new automatic source analysis must include inventory acquired
            # later, rather than pinning the previous run's small selection.
            # The completed parent's selection and artifacts remain immutable.
            old_inputs.pop('source_ids', None)
        old_inputs.update(feedback)
        s.pop('run_id', None)
        from .source_policy import adopt_policy
        if not feedback.get('remotion_only') and not feedback.get('thumbnail_only'):
            adopt_policy(s, self.settings, new_run=True)
        run = init_run(s)
        run.update(inputs=old_inputs, parent_id=old['id'])
        if 'script_text' in feedback:
            self._script(s, feedback['script_text'], 'manual')
            s['automation']['needs_top_pick'] = False
        if any(k in feedback for k in ('script_text', 'pronunciations', 'speed', 'regenerate_voice', 'voice_profile_id')):
            s.update(voice_id=None, approved_voice_id=None, edit_id=None)
        elif 'source_ids' in feedback or automatic_sources:
            s['edit_id'] = None
        s['automation'].update(active=True, paused_by_user=False)
        s.update(error='', progress=0)
        if (feedback.get('changes') or 'overlay_document' in feedback or 'thumbnail_document' in feedback) and not any(k in feedback for k in ('script_text','pronunciations','speed','regenerate_voice','source_ids','source_selection_mode','voice_profile_id')):
            edit = next(e for e in s['edits'] if e['id'] == feedback['base_edit_id'])
            self.store.enqueue(db, s['id'], 'revision', {'edit_id':edit['id'], 'script_id':edit['script_id'],
                'voice_id':edit['voice_id'], 'changes':feedback.get('changes', []), 'caption_only':bool(feedback.get('caption_only')),
                **({'remotion_only':True, 'overlay_document':feedback['overlay_document']} if 'overlay_document' in feedback else {}),
                **({'thumbnail_only':True, 'thumbnail_document':feedback['thumbnail_document']} if 'thumbnail_document' in feedback else {})}, 'revision:'+run['id'])
            s.update(status='editing', message='첫 프레임 썸네일을 반영한 새 버전 제작 중' if feedback.get('thumbnail_only') else '수정한 자막으로 MP4 내보내기 중' if feedback.get('caption_only') else '저장한 장면·자막 수정으로 새 버전 제작 중')
        else:
            if s.get('daily_quality', {}).get('pending') == 'failed' and not s.get('edit_id'):
                # An explicit new reproduction uses the same technical-recovery
                # assessment as resume, without requeuing old paused collectors.
                from .quality_progress import resume_assessment
                resume_assessment(s)
            self._advance_auto(s, db)

    def advance_workflow(self, s, db):
        from .studio import selected, digest
        run = snapshot(s)
        if s.get('pending_reproduction'):
            self.activate_reproduction(s, db)
            return
        if not s['automation'].get('active') or not s.get('original_text'): return
        script, voice, edit = (selected(s, c, k) for c, k in [('scripts','script_id'), ('voices','voice_id'), ('edits','edit_id')])
        if self.advance_daily_quality(s, db, script, voice, edit):
            return
        from .studio_thumbnail import queue_preserved_thumbnail
        if queue_preserved_thumbnail(self,s,db,run,edit):
            return
        if run['inputs'].get('photo_story'):
            # Explicit still-image production is a separate editing contract.
            # It never promotes analysis slides or still holds to video coverage.
            if s.get('creation_mode') != 'photo_post':
                raise ValueError('사진 영상 제작은 사진 게시물에만 사용할 수 있습니다.')
            if (edit and voice and script and edit.get('export_kind') == 'photo_story' and
                    edit.get('voice_id') == voice.get('id') and edit.get('script_id') == script.get('id') and edit.get('export_verified') is True
                    and Path(edit.get('export_path') or '').is_file() and edit.get('photo_assets')):
                run.update(status='completed', completed=time.time())
                run['artifacts']['photo_assets'] = copy.deepcopy(edit['photo_assets'])
                s['latest_completed_run_id'] = run['id']
                s['automation'].update(stage='completed', completed_at=time.time())
                s.update(status='completed', message='원본 사진·음성·자막으로 만든 영상 내보내기 완료', progress=100, error='')
            return
        if run['inputs'].get('remotion_only') or run['inputs'].get('thumbnail_only'):
            # This revision uses an already rendered, immutable picture/audio base.
            # Do not recollect footage or reconsider the previously chosen narration.
            if edit and edit.get('parent_id') == run['inputs'].get('base_edit_id') and edit.get('export_verified') and Path(edit.get('export_path', '')).is_file():
                from .source_diversity import require_body_minimum, policy_for_state
                require_body_minimum(json.loads(Path(edit['plan_path']).read_text(encoding='utf-8')),
                                     expected_policy=policy_for_state(s))
                run.update(status='completed', completed=time.time())
                s['latest_completed_run_id'] = run['id']
                s['automation'].update(stage='completed', completed_at=time.time())
                s.update(status='completed', message='첫 프레임 썸네일 반영 완료' if run['inputs'].get('thumbnail_only') else '자막·꾸미기를 반영한 MP4 내보내기 완료', progress=100, error='')
            return
        self.ensure_source_collection(s, db)
        key = run['id']
        wrong_automatic_voice = bool(voice and voice.get('voice_profile_id') and run['inputs'].get('voice_selection_mode') != 'manual')
        if not script or s['automation'].get('needs_top_pick'):
            stage, status, message, payload = 'rewrite', 'rewriting', '후보 대본 비교 · Top Pick 선정 대기', {}
        elif not voice or voice['script_id'] != script['id'] or wrong_automatic_voice:
            stage, status, message = 'voice', 'voice_generating', '선정 대본으로 TTS 생성 대기'
            voice_id = ('voice-personal-' if wrong_automatic_voice else 'voice-')+key
            s.update(approved_script_id=script['id'], pending_voice_id=voice_id)
            text = script['text']
            for pair in run['inputs'].get('pronunciations', []): text = text.replace(pair['from'], pair['to'])
            payload = dict(script_id=script['id'], voice_id=voice_id, speed=run['inputs'].get('speed',1), spoken_text=text)
            # Automatic intake never inherits a legacy named-voice workaround.
            # A voice explicitly selected in the Studio is a manual experiment.
            manual_voice = run['inputs'].get('voice_selection_mode') == 'manual'
            if manual_voice and run['inputs'].get('voice_profile_id'):
                payload['voice_profile_id'] = run['inputs']['voice_profile_id']
            payload['voice_mode'] = 'manual' if payload.get('voice_profile_id') else 'personal_clone'
            if run['inputs'].get('regenerate_voice'):
                payload['generation_key'] = key
            s['automation']['script_selection'] = {'mode':'automatic','script_id':script['id']}
        elif not edit or edit['voice_id'] != voice['id']:
            from .studio_sources import source_goal
            goal = source_goal(s, self.settings.source_min_usable)
            if not goal['ready']:
                from .source_policy import goal_message
                s.update(status='source_wait', message=('사용할 촬영 영상을 추가하거나 다시 선택해 주세요.'
                    if s.get('creation_mode') == 'self_shot' else s.get('source_search', {}).get('message', '')
                    if s.get('source_acquisition', {}).get('hold') else '소스 자동 추가 수집 대기 · '+goal_message(goal)), progress=0)
                s['automation']['stage'] = 'sources'
                return
            if digest(voice['path']) != voice['sha256']: raise Conflict('음성 파일이 변경되었습니다.')
            stage, status, message = 'edit', 'editing', '장면·자막 구성 및 프로젝트 생성 대기'
            if s.get('source_diversity_generation'):
                key+=':source-diversity:'+str(s['source_diversity_generation'])
            s['approved_voice_id'] = voice['id']
            s['automation']['voice_selection'] = {'mode':'automatic','voice_id':voice['id']}
            # Freeze the exact validated inventory used by this edit, including
            # sources acquired while script and voice were already in flight.
            # Acquisition coverage is a pool goal. A manual Studio selection may
            # use fewer clips and must never silently include excluded footage.
            source_ids = run['inputs'].get('source_ids', goal['source_ids'])
            run['inputs']['source_ids'] = source_ids
            payload = dict(script_id=script['id'], voice_id=voice['id'], source_ids=source_ids,
                           changes=run['inputs'].get('changes',[]), base_edit_id=run['inputs'].get('base_edit_id'))
            if s.get('initial_render_preparation'):
                from .initial_prepared_render import from_state
                prepared,_=from_state(s)
                key+=':prepared-cover:'+prepared['material_key']
                payload['initial_render_preparation_key']=prepared['material_key']
            quality=s.get('daily_quality',{})
            if quality.get('repair_context'):
                from .quality_progress import permit, queue_method
                method=queue_method(s,db,'reedit')
                if not method:return
                from .scene_requirements import repair_render_signature,REPAIR_SIGNATURE_POLICY
                signature=repair_render_signature(s)
                quality['repair_signature_policy']=REPAIR_SIGNATURE_POLICY
                payload.update(quality_repair=True,repair_input_signature=signature,
                               repair_signature_policy=REPAIR_SIGNATURE_POLICY,
                               parent_edit_id=quality['repair_context'].get('parent_edit_id'),quality_method=method)
        elif not edit.get('draft_path') and not edit.get('export_verified') and not edit.get('registration_deferred'):
            stage, status, message, payload = 'register', 'registering', 'CapCut 프로젝트 등록 대기', {'edit_id':edit['id'], 'launch':False}
        elif not edit.get('export_path'):
            stage, status, message, payload = 'export', 'exporting', 'CapCut 최종 MP4 내보내기 대기', {'edit_id':edit['id']}
        else:
            if edit.get('export_verified') is not True or not Path(edit.get('export_path') or '__missing__').is_file():
                raise ValueError('완료 영상 파일이 소실되었거나 검증되지 않았습니다. 기존 결과를 보존하고 확인이 필요합니다.')
            from .daily_quality import verified_quality_export
            if not verified_quality_export(s,edit):
                raise ValueError('현재 완성 영상·편집 계획에 결속한 품질 검수 근거가 없습니다.')
            from .studio_sources import sync_ready_source_status
            sync_ready_source_status(s, db, self.settings.source_min_usable)
            run.update(status='completed', completed=time.time())
            s['latest_completed_run_id'] = run['id']
            s['automation'].update(stage='completed', completed_at=time.time())
            message = {'remotion':'자막·꾸미기를 반영한 MP4 내보내기 완료', 'web_captions':'수정한 자막으로 MP4 내보내기 완료',
                       'web_render':'최종 MP4 내보내기 완료 · 웹 렌더링으로 복구'}.get(edit.get('export_kind'), 'CapCut 최종 영상 내보내기 완료')
            s.update(status='completed', message=message, progress=100, error='')
            return
        retry_count = int((s.get('daily_quality') or {}).get('resume_retry_count', 0) or 0)
        queue_key = stage+':'+key+(':personal' if stage=='voice' and wrong_automatic_voice else '')+(':retry:'+str(retry_count) if stage=='edit' and retry_count>0 else '')
        existing = db.execute('SELECT status FROM jobs WHERE key=?', (queue_key,)).fetchone()
        if existing and existing['status'] == 'failed' and s.get('error'):
            return
        identity=self.store.enqueue(db, s['id'], stage, payload, queue_key)
        if payload.get('quality_repair'):
            permit(s,'reedit',reserve=True,job_id=identity)
        if s['automation'].get('stage') != stage:
            self.store.event(db, s['id'], 'automatic_stage', {'stage':stage, 'message':message})
        s['automation']['stage'] = stage
        s.update(status=status, message=message, progress=0, error='')

    def _export(self, state, job):
        job = {**job, 'task_id': state['id']}
        from .editing_adapter import AutoCapcutAdapter, NativeExportUnavailable
        edit = next(e for e in state['edits'] if e['id'] == job['payload']['edit_id'])
        hold = self.settings.editing_dir / job['id'] / 'export-hold.json'
        if hold.is_file():
            reason = json.loads(hold.read_text(encoding='utf-8')).get('reason', '소스 검증 미완료')
            raise RuntimeError('편집 소스 재검토 필요: ' + str(reason)[:400])
        checkpoint = job['checkpoint']
        if edit.get('registration_deferred') and not edit.get('draft_path'):
            checkpoint.setdefault('native_export_unavailable', edit.get('registration_note', 'CapCut 프로젝트 등록 대기'))
            self.store.checkpoint(job, checkpoint)
        if not checkpoint.get('native_export_unavailable'):
            try:
                result = AutoCapcutAdapter(self.settings).export(job_id=job['id'], draft_name=edit['draft_name'], draft_path=Path(edit['draft_path']))
            except NativeExportUnavailable as exc:
                checkpoint['native_export_unavailable'] = str(exc)
                self.store.checkpoint(job, checkpoint)
        if checkpoint.get('native_export_unavailable'):
            # Keep the registered draft and its existing edit identity. The
            # renderer reuses this exact picture/audio/cue plan and verifies
            # the final media. Content holds and verification errors never
            # enter this fallback; no native editor is killed or modified.
            change_claimed(self.store, job, lambda s, db: s.update(
                message='CapCut 창 연결 실패 · 같은 장면·음성·자막으로 웹 내보내기 중', progress=50))
            plan = json.loads(Path(edit['plan_path']).read_text(encoding='utf-8'))
            rendered = self._process(state, job, 'caption-export', {'plan':plan, 'changes':[]})
            target = Path(rendered.get('export_path', ''))
            if rendered.get('export_verified') is not True or not target.is_file() or target.stat().st_size < 1024:
                raise ValueError('웹 내보내기의 최종 영상 검증을 완료하지 못했습니다.')
            return {'export_path':str(target), 'export_verified':True, 'exported_at':time.time(),
                    'export_kind':'web_render', 'native_export_error':checkpoint['native_export_unavailable']}
        if result.get('verified') is not True or result.get('width')!=1080 or result.get('height')!=1920 or abs(result.get('fps',0)-30)>.01:
            raise ValueError('최종 영상이 1080×1920 · 30fps 규격과 다릅니다. CapCut 내보내기 설정을 확인하세요.')
        target = self.folder(state['id']) / job['id'] / 'final.mp4'
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(result['video_path'], target)
        return {'export_path':str(target), 'export_verified':result['verified'], 'exported_at':time.time()}

    def render_feedback(self, state, job, plan):
        """Rebind scene IDs by source identity and narration, never by list position."""
        import difflib
        if state.get('creation_mode') == 'self_shot':
            # Select within the existing process boundary, then publish evidence
            # of reuse in the common saved plan and resulting detail screen.
            plan['footage_policy'] = 'owned-only-reuse-v1'
        changes = copy.deepcopy(job['payload'].get('changes', []))
        if not changes: return self._render_reviewed_cover(state, job, plan)
        base = next(e for e in state['edits'] if e['id']==job['payload']['base_edit_id'])
        old = json.loads(Path(base['plan_path']).read_text(encoding='utf-8'))
        used = set()
        for change in changes:
            beat = next(b for b in old['beats'] if b['id']==change['beat_id'])
            matches = sorted([(difflib.SequenceMatcher(None,beat['text'],b['text']).ratio(),b) for b in plan['beats'] if b['id'] not in used],key=lambda v:v[0],reverse=True)
            if not matches or matches[0][0]<.65 or len(matches)>1 and matches[0][0]==matches[1][0]:
                raise ValueError('대본 변경으로 수정 구간을 확실히 연결하지 못했습니다. 구간 피드백을 조정해 주세요.')
            target = matches[0][1]; used.add(target['id']); change['beat_id']=target['id']
            if 'shot_id' in change:
                shot = next(v for v in old['shots'] if v['id']==change['shot_id'])
                replacement = next((v for v in plan['shots'] if v['sha256']==shot['sha256'] and abs(v['start']-shot['start'])<.01),None)
                if not replacement: raise ValueError('선택했던 장면이 새 소스 구성에 없습니다. 장면 피드백을 조정해 주세요.')
                change['shot_id']=replacement['id']
                if not any(o['shot_id']==replacement['id'] for o in target['options']):
                    target['options'].append({'shot_id':replacement['id'],'relation':'illustration','reason':'사용자가 선택한 장면'})
        return self._render_reviewed_cover(state,job,plan,changes)

    def _render_reviewed_cover(self,state,job,plan,changes=None):
        from .cover_selection import select_cover
        # Keep the editor process boundary: select windows before reviewing
        # cover candidates, then freeze these actual choices for rendering.
        from .daily_quality import enabled as daily_enabled, QualitySceneGap
        if daily_enabled(state):
            from .scene_requirements import constrain_plan
            constrain_plan(state,plan)
            missing=[b for b in plan.get('beats',[]) if b.get('visual_alignment_gap')]
            if missing:
                raise QualitySceneGap([{'kind':'scene_gap','beat_id':b['id'],
                    'reason':'필요한 검토 장면이 실제 편집 선택지에 연결되지 않음',
                    'search_query':state.get('product') or state.get('title','')} for b in missing])
        selected=self._process(state,job,'select-shots',{'plan':plan,'changes':changes or []})['plan']
        if daily_enabled(state):
            from .scene_requirements import anchor_selected_scenes, validate_selected_scenes
            anchor_selected_scenes(state,selected)
            validate_selected_scenes(state,selected)
            missing=[b for b in selected.get('beats',[]) if b.get('visual_alignment_gap') or not b.get('selected_shot_id')]
            if missing:
                raise QualitySceneGap([{'kind':'scene_gap','beat_id':b['id'],
                    'reason':'편집 전 필요한 사용 장면의 연결이 확인되지 않음',
                    'search_query':state.get('product') or state.get('title','')} for b in missing])
        if selected.get('footage_selection_policy')=='product-story-global-v3':
            # Required native evidence may have narrowed windows after global
            # selection. Freeze that validated final plan without reallocating.
            selected.pop('selection_frozen',None)
            selected=self._process(state,job,'freeze-selection',{'plan':selected})['plan']
        candidates=self._process(state,job,'cover-candidates',{'plan':selected})['candidates']
        if daily_enabled(state) and state.get('edit_id') and getattr(select_cover,'__module__','')=='hotpost.cover_selection':
            from .quality_issue_scope import is_cover_scene_gap
            from .cover_selection import POLICY as cover_policy
            from .editing_adapter import _atomic_json
            feedback=state.get('daily_quality',{}).get('feedback',[])
            has_cover_defect=any(i.get('kind')=='cover' or is_cover_scene_gap(i) for i in feedback)
            prepared_src=(plan.get('cover_spec') or {}).get('source') or {}
            parent_edit=next((e for e in state.get('edits',[]) if e.get('id')==state.get('edit_id')),None)
            parent_path=Path((parent_edit or {}).get('plan_path',''))
            if has_cover_defect and parent_path.is_file() and not prepared_src.get('single_frame_confirmation'):
                try:
                    old_plan=json.loads(parent_path.read_text('utf-8'))
                    old_src=(old_plan.get('cover_spec') or {}).get('source') or {}
                    old_sha=old_src.get('source_sha256')
                    old_ts=old_src.get('timestamp')
                    cover_beats={i.get('beat_id') for i in feedback if (i.get('kind')=='cover' or is_cover_scene_gap(i)) and i.get('beat_id')}
                    rejected_shots={b.get('selected_shot_id') for b in selected.get('beats',[]) if b.get('id') in cover_beats and b.get('selected_shot_id')}
                    filtered=[c for c in candidates if not (
                        (c.get('shot_id') and c.get('shot_id') in rejected_shots)
                        or (old_sha and c.get('source_sha256')==old_sha and isinstance(old_ts,(int,float))
                            and isinstance(c.get('timestamp'),(int,float)) and abs(float(c['timestamp'])-float(old_ts))<1.5)
                    )]
                    if filtered:
                        candidates=filtered
                except (OSError,ValueError,KeyError,TypeError):pass
            cover_sel_path=self.folder(state['id'])/job['id']/'cover-selection.json'
            seed_plan=plan if (prepared_src.get('review_policy')==cover_policy and prepared_src.get('single_frame_confirmation')) else (
                json.loads(parent_path.read_text('utf-8')) if (feedback and not has_cover_defect and parent_path.is_file()) else None)
            if seed_plan is not None and not cover_sel_path.exists():
                try:
                    old_src=(seed_plan.get('cover_spec') or {}).get('source') or {}
                    old_rgb=(old_src.get('cover_pixel_binding') or {}).get('canvas_rgb_sha256')
                    if (old_src.get('review_policy')==cover_policy and old_rgb
                            and seed_plan.get('script_text')==selected.get('script_text')
                            and (seed_plan.get('cover_spec') or {}).get('lines')==(selected.get('cover_spec') or {}).get('lines')):
                        match_idx=next((i for i,c in enumerate(candidates)
                            if c.get('source_id')==old_src.get('source_id')
                            and c.get('source_sha256')==old_src.get('source_sha256')
                            and (c.get('cover_pixel_binding') or {}).get('canvas_rgb_sha256')==old_rgb),None)
                        if match_idx is not None:
                            fp=hashlib.sha256(json.dumps({'policy':cover_policy,'lines':selected['cover_spec']['lines'],
                                'script':selected['script_text'],'candidates':[{**c,'frame_sha256':sha256_file(Path(c['frame_path']))} for c in candidates]},
                                ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                            reason_txt=str(old_src.get('visual_observation') or '이전 검수 통과 표지 프레임 보존')
                            conf_reviews=(old_src.get('single_frame_confirmation') or {}).get('reviews') or [{
                                'id':'0','eligible':True,'faces_present':False,'face_blur_used':False,
                                'hook_unresolved':True,'overlays_acceptable':True,'mask_coverage_valid':True,
                                'product_view_preserved':True,'reason':reason_txt}]
                            _atomic_json(cover_sel_path,{'fingerprint':fp,'policy':cover_policy,
                                'reviews':[{'id':str(match_idx),'eligible':True,'faces_present':False,'face_blur_used':False,
                                    'hook_unresolved':True,'overlays_acceptable':True,'mask_coverage_valid':True,
                                    'product_view_preserved':True,'reason':reason_txt}],
                                'confirmations':[{'candidate_id':str(match_idx),'reviews':conf_reviews}]})
                except (OSError,ValueError,KeyError,TypeError):pass
        selected=select_cover(self.settings,selected,candidates,self.folder(state['id'])/job['id'],
            search_context=state.get('product') or state.get('title',''))
        cover_src=(selected.get('cover_spec') or {}).get('source') or {}
        if cover_src.get('frame_path') and 'frame_sha256' not in cover_src and Path(cover_src['frame_path']).is_file():
            cover_src['frame_sha256']=sha256_file(Path(cover_src['frame_path']))
        if daily_enabled(state):
            validate_selected_scenes(state,selected)
            if job['payload'].get('quality_prepare_only'):
                return {'no_render':True,'prepared_plan':selected}
            if job['kind']=='quality_reedit' or job['payload'].get('quality_repair'):
                from .quality_progress import guard_render, QualityProgressHold, hold
                if any(i.get('kind')=='caption_sync' for i in state['daily_quality'].get('feedback',[])):
                    selected['audio_timing_repair']=True
                    from .quality_progress import audio_repair_evidence
                    selected['quality_audio_repair']={'method':'approved-voice-pcm-clock',
                        'voice_sha256':selected['voice']['sha256'],'audit':audio_repair_evidence(state)}
                blocked=[]
                def before_render(current,db):
                    if current.get('automation',{}).get('paused_by_user'):
                        blocked.append('사용자 중지 유지');return
                    reason=guard_render(current,selected,job['id'])
                    blocked.append(reason)
                    if reason:hold(current,reason,'stop_method')
                change_claimed(self.store, job,before_render)
                if blocked[0]:raise QualityProgressHold(blocked[0],waiting=blocked[0]=='사용자 중지 유지')
        if daily_enabled(state) and job['kind']=='quality_reedit':
            from .cover_frame_copy import render_if_cover_only
            copied=render_if_cover_only(self,state,job,selected)
            if copied is not None:return copied
        return self._process(state,job,'render',{'plan':selected})

    def _suggest_edit(self, state, job):
        from .studio_ai import plan_revision
        p = job['payload']
        edit = next(e for e in state['edits'] if e['id'] == p['edit_id'])
        plan = json.loads(Path(edit['plan_path']).read_text(encoding='utf-8'))
        start, end = float(p.get('start',0)), float(p.get('end') or plan['duration'])
        if not 0 <= start < end <= plan['duration']+.001: raise ValueError('수정 구간을 확인하세요.')
        return {**plan_revision(self.settings, plan, p['request'], start, end), 'base_edit_id':edit['id'], 'feedback_hash':p['feedback_hash']}

    def pipeline(self, state):
        jobs = state.get('jobs')
        if jobs is None:
            jobs = self.store.jobs(state['id'])
        production_jobs = [j for j in jobs if j['kind'] in {
            'prepare', 'collect_sources', 'refresh_sources', 'rewrite', 'voice', 'edit', 'revision', 'revise',
            'edit_request', 'register', 'export','quality_review','quality_reedit'}]
        # A saved stage is a checkpoint, not evidence that a worker is running.
        execution = ('running' if any(j['status']=='running' for j in production_jobs)
                     else 'queued' if any(j['status']=='queued' for j in production_jobs)
                     else 'failed' if state.get('error')
                     else 'blocked' if state.get('production_blockers') or state.get('source_acquisition', {}).get('hold')
                     else 'paused' if state.get('automation', {}).get('paused_by_user')
                     else 'waiting')
        runs = copy.deepcopy(state.get('runs', []))
        if not runs:
            runs = [dict(id='legacy', number=1, status='legacy', artifacts={
                **{k:state.get(k) for k in ('script_id','voice_id','edit_id','original_text','transcript_path')}, 'sources':state['sources']})]
        for run in runs:
            if run['id']==state.get('run_id') and run['status'] not in {'completed','superseded'}:
                run['status'] = execution
            a = run['artifacts']
            script = next((v for v in state['scripts'] if v['id']==a.get('script_id')), {})
            voice = next((v for v in state['voices'] if v['id']==a.get('voice_id')), {})
            edit = next((v for v in state['edits'] if v['id']==a.get('edit_id')), {})
            available = {'sources':any(Path(v['path']).is_file() for v in a.get('sources', [])),
                'transcript':bool(a.get('original_text')), 'script':bool(script.get('path') and Path(script['path']).is_file()),
                'voice':bool(voice.get('path') and Path(voice['path']).is_file()),
                'project':bool(edit.get('portable_draft_path') and Path(edit['portable_draft_path']).is_dir()),
                'export':bool(edit.get('export_verified') and edit.get('export_path') and Path(edit['export_path']).is_file())}
            if available['export']:
                from .daily_quality import verified_quality_export
                available['export']=verified_quality_export(state,edit,historical=True)
            stage = state.get('automation', {}).get('stage', 'prepare')
            active_key = {'prepare':'sources','rewrite':'script','voice':'voice','edit':'project','register':'project','export':'export',
                          'quality_review':'project','quality_reedit':'project','refresh_sources':'sources'}.get(stage)
            run['steps'] = []
            for key, label in STEPS:
                status = 'completed' if available[key] else 'pending'
                current = run['id'] == state.get('run_id') and not run.get('video_url') and run.get('status') != 'completed'
                if current and key == 'sources':
                    from .studio_sources import source_goal
                    status = 'completed' if source_goal(state,self.settings.source_min_usable)['ready'] else 'pending'
                if current and status != 'completed':
                    stage_kinds = {'sources':{'collect_sources','refresh_sources'}, 'transcript':{'prepare'}, 'script':{'prepare','rewrite'}, 'voice':{'voice'},
                                   'project':{'edit','revision','revise','edit_request','register','quality_review','quality_reedit'}, 'export':{'export'}}
                    step_jobs = [j for j in production_jobs if j['kind'] in stage_kinds.get(key, set())]
                    status = ('running' if any(j['status']=='running' for j in step_jobs)
                              else 'queued' if any(j['status']=='queued' for j in step_jobs)
                              else 'failed' if step_jobs and step_jobs[0]['status']=='failed'
                              else execution if key==active_key and execution not in {'running','queued'} else 'pending')
                    if key == 'sources' and state.get('source_acquisition', {}).get('hold') and status not in {'running','queued'}:
                        status = 'blocked'
                if run['status']=='superseded' and status=='pending': status='superseded'
                run['steps'].append(dict(key=key,label=label,status=status,
                    download_url=f"/api/studio/{state['id']}/download?run={run['id']}&asset={key}" if available[key] else None))
            if not a.get('top_pick'):
                run['steps'][2]['label'] = '제작 대본 · 기존 선택'
            if state.get('creation_mode') == 'self_shot':
                run['steps'][0]['label'] = '내 촬영 영상'
                run['steps'][1]['label'] = '제작 정보 준비'
                run['steps'][2]['label'] = '직접 입력 대본' if state['self_shot']['script_mode'] == 'manual' else '자동 집필 대본'
            run['preview_url'] = self.media_url(state['id'], edit['preview_path']) if edit.get('preview_path') and Path(edit['preview_path']).is_file() else None
            run['video_url'] = self.media_url(state['id'], edit['export_path']) if available['export'] else None
        return runs

    def download(self, task_id, run_id, asset):
        state = self.store.get(task_id)
        run = next((r for r in self.pipeline(state) if r['id']==run_id), None)
        if not run or not any(s['key']==asset and s['download_url'] for s in run['steps']): raise ValueError('완료된 결과물이 없습니다.')
        a = run['artifacts']
        target_dir = self.folder(task_id) / 'downloads' / run_id
        target_dir.mkdir(parents=True, exist_ok=True)
        if asset == 'transcript':
            target = target_dir/'original.txt'
            target.write_text(a['original_text'], encoding='utf-8')
            return target
        collection, key, field = {'script':('scripts','script_id','path'), 'voice':('voices','voice_id','path'),
                                  'export':('edits','edit_id','export_path'), 'project':('edits','edit_id','portable_draft_path')}.get(asset, ('','',''))
        if collection:
            item = next(v for v in state[collection] if v['id']==a[key])
            if asset != 'project': return Path(item[field])
        target = target_dir / (asset+'.zip')
        # Atomic replacement supports simultaneous downloads without partial ZIPs.
        temp = target.with_name(uid('bundle-')+'.zip')
        with zipfile.ZipFile(temp, 'w', zipfile.ZIP_STORED) as archive:
            if asset == 'sources':
                for i, source in enumerate(a.get('sources', [])):
                    path = Path(source['path'])
                    if path.is_file(): archive.write(path, f"{i+1:02}-{path.name}")
                archive.writestr('provenance.json', json.dumps(a['sources'], ensure_ascii=False, indent=2))
            else:
                root = Path(item[field])
                for path in root.rglob('*'):
                    if path.is_file(): archive.write(path, (Path(root.name)/path.relative_to(root)).as_posix())
                archive.writestr('README.txt', 'CapCut 프로젝트와 studio-assets 미디어입니다. 다른 PC에서는 미디어 위치를 다시 연결해야 할 수 있습니다.')
        os.replace(temp, target)
        return target
