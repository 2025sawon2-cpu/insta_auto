"""Bind the required disclosure to real web renders before their final QA."""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

from .editing_adapter import _atomic_json
from .post_media_rules import DISCLOSURE_VERSION, mark_cover
from .post_thumbnail import add_disclosure
from .source_quality import sha256_file


def frame_clock(path):
    completed = subprocess.run([shutil.which('ffprobe') or 'ffprobe', '-v','error',
        '-select_streams','v:0','-show_entries','frame=best_effort_timestamp_time',
        '-of','json',str(path)], capture_output=True, check=True, encoding='utf-8', timeout=120)
    return [frame['best_effort_timestamp_time'] for frame in json.loads(completed.stdout)['frames']]


def apply_render_disclosure(result, folder):
    """Preserve the renderer's original files and return a new, reviewable output.

    This is media processing, never a quality approval. The normal Studio worker
    accepts this result and reviews the resulting video and plan hashes.
    """
    original = Path(result.get('export_path') or result['preview_path'])
    original_plan = Path(result['plan_path'])
    plan = json.loads(original_plan.read_text('utf-8'))
    font = Path(plan['cover_spec']['font']['font_path'])
    if not font.is_file():
        raise ValueError('광고 표시용 검증된 썸네일 폰트가 없습니다.')
    root = Path(folder) / 'publication-disclosure'
    root.mkdir(exist_ok=True)
    # A failed processing attempt never replaces the original renderer output.
    before = {'video': sha256_file(original), 'plan': sha256_file(original_plan),
              'cover': sha256_file(Path(result['cover_path'])), 'font': sha256_file(font)}
    _atomic_json(root / 'source-result.json', copy.deepcopy(result))
    video, cover, timeline = root / 'final.mp4', root / 'cover.png', root / 'timeline.json'
    add_disclosure(original, video, font)
    before_clock, after_clock = frame_clock(original), frame_clock(video)
    if not before_clock or before_clock != after_clock:
        raise ValueError('광고 표시 후 실제 프레임 시간축이 달라져 결과를 수용하지 않았습니다.')
    shutil.copy2(result['cover_path'], cover)
    mark_cover(cover, font)
    if before != {'video': sha256_file(original), 'plan': sha256_file(original_plan),
                  'cover': sha256_file(Path(result['cover_path'])), 'font': sha256_file(font)}:
        raise ValueError('광고 표시 중 원본 영상·계획·표지·폰트가 변경되었습니다.')
    plan.setdefault('publication_rules', {})['advertising_disclosure'] = DISCLOSURE_VERSION
    plan['cover_path'] = str(cover)
    if plan.get('mask_application_clock'):
        plan['mask_application_clock']['final_render_sha256'] = sha256_file(video)
    receipt = root / 'receipt.json'
    plan['publication_disclosure_receipt'] = str(receipt)
    _atomic_json(timeline, plan)
    _atomic_json(receipt, {'version': DISCLOSURE_VERSION, 'source': before,
        'video_sha256': sha256_file(video), 'cover_sha256': sha256_file(cover),
        'plan_sha256': sha256_file(timeline),
        'checks': {'outside_disclosure_pixels_identical': True, 'audio_packets_identical': True,
                   'frame_clock_identical': True, 'frames': len(after_clock)},
        'quality_approval': False})
    updated = copy.deepcopy(result)
    updated.pop('_artifact_hashes', None)
    updated.update(preview_path=str(video), cover_path=str(cover), plan_path=str(timeline),
                   publication_disclosure_receipt=str(receipt))
    if result.get('export_path'):
        updated['export_path'] = str(video)
    return updated


def queue_disclosure(studio, task_id, data):
    from .studio_store import Conflict
    def queue(state, db):
        edit = next((e for e in state['edits'] if e['id'] == state.get('edit_id')), None)
        if not edit or edit['id'] != data.get('edit_id'):
            raise Conflict('현재 광고 표시 대상 편집본이 변경되었습니다.')
        if edit['voice_id'] != state.get('approved_voice_id'):
            raise Conflict('현재 승인 음성과 다른 편집본입니다.')
        if edit['script_id'] != state.get('script_id') or edit['script_id'] != state.get('approved_script_id'):
            raise Conflict('현재 승인 대본과 다른 편집본입니다.')
        video = edit.get('export_path') or edit['preview_path']
        binding = {'render_sha256': sha256_file(Path(video)),
                   'plan_sha256': sha256_file(Path(edit['plan_path']))}
        if any(data.get(k) != v for k, v in binding.items()):
            raise Conflict('광고 표시 요청 이후 실제 영상·계획이 변경되었습니다.')
        current_plan = json.loads(Path(edit['plan_path']).read_text('utf-8'))
        receipt_path = current_plan.get('publication_disclosure_receipt')
        if receipt_path and Path(receipt_path).is_file():
            prior_receipt = json.loads(Path(receipt_path).read_text('utf-8'))
            if (prior_receipt.get('version') == DISCLOSURE_VERSION
                    and prior_receipt.get('video_sha256') == binding['render_sha256']
                    and prior_receipt.get('plan_sha256') == binding['plan_sha256']):
                raise Conflict('현재 영상에는 이미 검증된 광고 표시가 반영되어 있습니다.')
        if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('queued','running')", (task_id,)).fetchone():
            raise Conflict('진행 중인 작업이 끝난 뒤 광고 표시를 반영하세요.')
        auto = state.setdefault('automation', {})
        if auto.get('paused_by_user') and (data.get('resume_pause_token') is None
                or data.get('resume_pause_token') != auto.get('paused_at')):
            raise Conflict('사용자 중지 보존 · 해당 중지 이후 명시 재개가 필요합니다.')
        from .production_control import hold
        if hold(db, task_id):
            raise Conflict('영속 보류의 원인 해결 후 정상 재개가 필요합니다.')
        quality = state.setdefault('daily_quality', {})
        if (state.get('editorial_content_hold') or quality.get('narration_context_hold')
                or quality.get('feedback')
                or quality.get('pending') not in {None, '', 'failed', 'quality_review'}):
            raise Conflict('실제 콘텐츠·품질 보류를 광고 표시로 해제할 수 없습니다.')
        key = 'disclosure:' + edit['id'] + ':' + binding['render_sha256']
        if db.execute('SELECT 1 FROM jobs WHERE key=?', (key,)).fetchone():
            raise Conflict('같은 영상의 광고 표시 시도 이력이 있습니다. 기존 결과를 확인하세요.')
        quality.setdefault('disclosure_history', []).append({'parent_edit_id': edit['id'],
            'prior': {k: quality.get(k) for k in ('status','pending','failed_job_id','failed_job_kind')}, **binding})
        quality.update(status='pending', pending='quality_review')
        auto.update(active=True, paused_by_user=False, stage='edit')
        studio.store.enqueue(db, task_id, 'revision', {'edit_id': edit['id'],
            'voice_id': edit['voice_id'], 'script_id': edit['script_id'],
            'disclosure_only': True, **binding}, key)
        state.update(status='editing', message='기존 영상·음성 보존 · 광고 표시 반영 후 새 파일 검수', error='')
        studio.store.event(db, task_id, 'advertising_disclosure_requested', binding)
    return studio.public(studio.store.change(task_id, queue, data.get('revision')))
