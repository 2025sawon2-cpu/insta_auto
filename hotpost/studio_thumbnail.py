"""First-frame-only revisions of an existing finished video; no writing or TTS."""
from __future__ import annotations

import copy
import json
import math
import shutil
import subprocess
import time
from functools import lru_cache
from pathlib import Path

from .editing_adapter import _atomic_json
from .remotion_editor import ROOT, node_binary, validate_document
from .thumbnail_mp4 import present_cover, video_timing


@lru_cache(maxsize=1)
def thumbnail_font():
    from PIL import ImageFont
    return ImageFont.truetype(str(ROOT.parent/'web/assets/fonts/DoHyeon-Regular.ttf'), 100)


def validate_thumbnail(document, duration):
    if not isinstance(document, dict) or set(document) != {'version', 'frame', 'elements'}:
        raise ValueError('올바르지 않은 썸네일 문서입니다.')
    frame = document['frame']
    if type(frame) is not int or not -1 <= frame < math.ceil(float(duration)*30):
        raise ValueError('영상 안의 썸네일 배경 장면을 선택하세요.')
    result = validate_document({'version': document['version'], 'elements': document['elements']}, 1/30)
    if len(result['elements']) > 20 or any(e['start'] != 0 or e['end'] != 1/30 for e in result['elements']):
        raise ValueError('썸네일 요소는 첫 한 프레임에만 표시됩니다. 최대 20개입니다.')
    font = thumbnail_font()
    def glyph(char):
        mask = font.getmask(char)
        return mask.size, bytes(mask), font.getlength(char)
    missing = glyph('\uffff')
    for element in result['elements']:
        if element['kind'] != 'text':
            raise ValueError('썸네일에는 문구만 추가할 수 있습니다.')
        for char in set(element['text']):
            if not char.isspace() and glyph(char) == missing:
                raise ValueError(f'도현 폰트에서 지원하지 않는 글자 {char} (U+{ord(char):04X})를 다른 표현으로 바꿔 주세요.')
    return {**result, 'frame': frame}


def verify_manual_thumbnail(state, edit, plan, video):
    """Bind manual typography to the actual render, and body to a reviewed parent."""
    from .daily_quality import verified_quality_export
    from .source_quality import sha256_file
    parent = next((e for e in state.get('edits', []) if e['id'] == edit.get('parent_id')), None)
    if not parent or not verified_quality_export(state, parent, historical=True):
        raise ValueError('수동 썸네일의 본문 승인 근거가 확인되지 않았습니다.')
    if any(edit.get(k) != parent.get(k) for k in ('script_id', 'voice_id', 'duration')):
        raise ValueError('수동 썸네일의 본문 버전이 변경되었습니다.')
    document = validate_thumbnail(plan['thumbnail_document'], edit['duration'])
    if parent.get('plan_path'):
        old_plan=json.loads(Path(parent['plan_path']).read_text('utf8'))
        body_keys=('script_text','duration','beats','shots','sources','cues','voice','voice_source',
            'pause_processing','narration_policy','alignment','caption_style','sound_effects',
            'sound_effect_policy','sfx_gain','audio_mix','remotion_document')
        if any(plan.get(k)!=old_plan.get(k) for k in body_keys):
            raise ValueError('수동 썸네일의 본문 편집 계획이 변경되었습니다.')
    folder = Path(edit['plan_path']).parent
    request = json.loads((folder/'thumbnail-request.json').read_text('utf8'))
    result = json.loads((folder/'thumbnail-result.json').read_text('utf8'))
    spec = plan['cover_spec']; source = spec.get('source', {})
    cover = Path(result['cover_path']); background = Path(request['background'])
    parent_video = Path(parent['export_path'])
    receipt = json.loads(Path(video).with_suffix('.cover-copy.json').read_text('utf8'))
    bundled_font = folder/'thumbnail-bundle/public/DoHyeon.ttf'
    font = ROOT.parent/'web/assets/fonts/DoHyeon-Regular.ttf'
    if (request['document'] != document or spec.get('lines') != [e['text'] for e in document['elements']]
            or source.get('rendered_cover_sha256') != sha256_file(cover)
            or source.get('frame_sha256') != sha256_file(background)
            or sha256_file(bundled_font) != sha256_file(font)
            or receipt.get('sha256') != sha256_file(Path(video))
            or receipt.get('inputs', {}).get(str(cover.resolve())) != sha256_file(cover)
            or receipt.get('inputs', {}).get(str(parent_video.resolve())) != sha256_file(parent_video)
            or not all(receipt.get('proof', {}).get(k) is True for k in ('body_frames_identical', 'audio_identical'))):
        raise ValueError('수동 썸네일의 문구·폰트·영상 보존 근거가 변경되었습니다.')


def queue_preserved_thumbnail(studio, state, db, run, edit):
    """A voice-only reproduction keeps the last manually edited cover."""
    if not edit or run.get('inputs', {}).get('thumbnail_only') or run.get('inputs', {}).get('remotion_only'):
        return False
    previous=next((r for r in state.get('runs', []) if r['id']==run.get('parent_id')), {})
    old=next((e for e in state.get('edits', []) if e['id']==previous.get('artifacts', {}).get('edit_id')), {})
    if not old or edit.get('voice_id')==old.get('voice_id') or edit.get('preserved_thumbnail_from')==old.get('id'):
        return False
    scripts={s['id']:s['text'] for s in state.get('scripts', [])}
    if (not scripts.get(edit.get('script_id')) or scripts.get(edit.get('script_id'))!=scripts.get(old.get('script_id'))
            or set(run.get('inputs', {}).get('source_ids', []))!=set(previous.get('inputs', {}).get('source_ids', []))):
        return False
    old_plan=json.loads(Path(old['plan_path']).read_text('utf8'))
    document=old_plan.get('thumbnail_document')
    if not document:return False
    from .daily_quality import verified_quality_export
    if not verified_quality_export(state, old, historical=True) or not verified_quality_export(state, edit):
        raise ValueError('목소리 변경 후 유지할 썸네일·본문의 승인 근거가 없습니다.')
    document=copy.deepcopy(document);document['frame']=-1
    studio.store.enqueue(db,state['id'],'revision',{'edit_id':edit['id'],'script_id':edit['script_id'],
        'voice_id':edit['voice_id'],'thumbnail_only':True,'thumbnail_document':document,
        'preserved_thumbnail_from':old['id']},'preserve-thumbnail:'+run['id']+':'+edit['id'])
    state['automation']['stage']='edit'
    state.update(status='editing',message='수정한 목소리에 기존 썸네일을 유지하는 중',error='')
    return True


def render_thumbnail(studio, state, job, edit, plan):
    document = validate_thumbnail(job['payload']['thumbnail_document'], edit['duration'])
    base = Path(edit.get('export_path') or '').resolve()
    data_root = studio.settings.data_dir.resolve()
    if not base.is_file() or not base.is_relative_to(data_root):
        raise ValueError('완성 영상이 준비된 뒤 썸네일을 반영하세요.')
    ffmpeg, probe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not probe:
        raise RuntimeError('썸네일 반영에는 FFmpeg와 ffprobe가 필요합니다.')
    # Repeated thumbnail revisions always copy the original finished body. In
    # particular, do not reuse the large legacy lossless thumbnail export.
    anchor = edit
    seen = set()
    while True:
        anchor_video=Path(anchor.get('export_path') or anchor.get('preview_path') or '').resolve()
        copy_receipt=anchor_video.with_suffix('.cover-copy.json')
        if not copy_receipt.is_file():
            if anchor.get('export_kind')=='thumbnail':raise ValueError('썸네일 원본 완성본의 본문 보존 영수증이 없습니다.')
            break
        if anchor.get('id') in seen:
            raise ValueError('썸네일 원본 연결이 순환하고 있습니다.')
        seen.add(anchor.get('id'))
        parent = next((e for e in state.get('edits', []) if e.get('id') == anchor.get('parent_id')), None)
        if not parent or any(parent.get(k) != anchor.get(k) for k in ('duration', 'script_id', 'voice_id')):
            raise ValueError('썸네일 원본 완성본을 찾을 수 없습니다.')
        from .source_quality import sha256_file
        receipt=json.loads(copy_receipt.read_text('utf8'))
        parent_video=Path(parent.get('export_path') or parent.get('preview_path') or '').resolve()
        if (receipt.get('sha256')!=sha256_file(anchor_video)
                or receipt.get('inputs',{}).get(str(parent_video))!=sha256_file(parent_video)
                or not all(receipt.get('proof',{}).get(k) is True for k in ('body_frames_identical','audio_identical'))):
            raise ValueError('썸네일 원본 본문·음성 보존 근거가 변경되었습니다.')
        anchor = parent
    source_video = Path(anchor.get('export_path') or anchor.get('preview_path') or '').resolve()
    if not source_video.is_file() or not source_video.is_relative_to(data_root):
        raise ValueError('썸네일 원본 완성본이 준비되지 않았습니다.')
    folder = studio.folder(state['id'])/job['id']
    folder.mkdir(exist_ok=True)
    background = folder/'thumbnail-background.png'
    preserved = Path(plan.get('cover_spec', {}).get('background_path') or '')
    if document['frame'] == -1 and preserved.is_file() and preserved.resolve().is_relative_to(data_root):
        shutil.copyfile(preserved, background)
    else:
        source = Path(edit.get('clean_preview_path') or str(base)).resolve()
        if not source.is_file() or not source.is_relative_to(data_root):
            raise ValueError('썸네일 배경 영상을 찾을 수 없습니다.')
        subprocess.run([ffmpeg, '-y', '-v', 'error', '-i', str(source), '-vf',
                        f"select=eq(n\\,{max(0,document['frame'])}),scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
                        '-frames:v', '1', str(background)], check=True, capture_output=True, timeout=120)
    request, receipt = folder/'thumbnail-request.json', folder/'thumbnail-result.json'
    _atomic_json(request, {'background': str(background), 'document': document, 'output_dir': str(folder.resolve())})
    with studio.render_lock:
        with (folder/'thumbnail.log').open('a', encoding='utf-8') as log:
            subprocess.run([node_binary(), str(ROOT/'render_thumbnail.mjs'), str(request), str(receipt)],
                           cwd=ROOT, stdout=log, stderr=log, check=True,
                           timeout=studio.settings.auto_capcut_timeout,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    result = json.loads(receipt.read_text(encoding='utf-8'))
    cover = Path(result['cover_path']).resolve(strict=True)
    if not cover.is_relative_to(folder.resolve()):
        raise ValueError('썸네일 렌더링 결과를 확인할 수 없습니다.')
    target = folder/'thumbnail-final.mp4'
    from .cover_frame_copy import replace_frame
    replace_frame(source_video,cover,target,studio.settings.auto_capcut_timeout,validation_base=base)
    revised = copy.deepcopy(plan)
    revised['thumbnail_document'] = document
    previous_cover=copy.deepcopy(revised.get('cover_spec',{}))
    # A manual cover is a new actual image/document, not the old source's approval.
    from .source_quality import sha256_file
    revised['cover_spec']={'lines':[e['text'] for e in document['elements']],
        'background_path':str(background),'copy_origin':'manual_thumbnail_document',
        'source':{'frame_path':str(background),'frame_sha256':sha256_file(background),
            'rendered_cover_path':str(cover),'rendered_cover_sha256':sha256_file(cover),
            'manual_background_frame':document['frame'],'parent_edit_id':edit['id']}}
    revised.setdefault('cover_revision_history',[]).append({'parent_edit_id':edit['id'],
        'previous_cover_spec':previous_cover,'reason':'manual_thumbnail_document'})
    revised['cover_path']=str(cover)
    revised['cover_text']='\n'.join(revised['cover_spec']['lines'])
    revised['cover_review_policy']='manual-thumbnail-awaiting-actual-qa'
    if revised.get('mask_application_clock'):
        revised['mask_application_clock']['final_render_sha256']=sha256_file(target)
    revised['cover_mode'] = 'replace_first_frame'
    timeline = folder/'thumbnail-timeline.json'
    _atomic_json(timeline, revised)
    return {'plan_path':str(timeline), 'preview_path':str(target), 'export_path':str(target),
            'cover_path':str(cover), 'export_kind':'thumbnail', 'thumbnail_encoding':'stream_copy', 'export_verified':True,
            'exported_at':time.time(), 'duration':edit['duration'], 'review_count':0,
            **({'clean_preview_path':edit['clean_preview_path']} if edit.get('clean_preview_path') else {})}
