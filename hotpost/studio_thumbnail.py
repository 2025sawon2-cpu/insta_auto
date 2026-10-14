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
    while anchor.get('export_kind') == 'thumbnail':
        if anchor.get('id') in seen:
            raise ValueError('썸네일 원본 연결이 순환하고 있습니다.')
        seen.add(anchor.get('id'))
        parent = next((e for e in state.get('edits', []) if e.get('id') == anchor.get('parent_id')), None)
        if not parent or any(parent.get(k) != anchor.get(k) for k in ('duration', 'script_id', 'voice_id')):
            raise ValueError('썸네일 원본 완성본을 찾을 수 없습니다.')
        anchor = parent
    source_video = Path(anchor.get('export_path') or '').resolve()
    if not source_video.is_file() or not source_video.is_relative_to(data_root):
        raise ValueError('썸네일 원본 완성본이 준비되지 않았습니다.')
    def metadata(path):
        return json.loads(subprocess.run([probe, '-v', 'error', '-count_frames', '-show_streams',
            '-show_format', '-of', 'json', str(path)], check=True, capture_output=True, encoding='utf-8', timeout=120).stdout)
    original = metadata(base)
    a = next(s for s in original['streams'] if s['codec_type']=='video')
    if (a['width'], a['height'], a['r_frame_rate'], a['codec_name'], a['pix_fmt']) != (1080, 1920, '30/1', 'h264', 'yuv420p'):
        raise ValueError('첫 프레임 썸네일은 H.264 1080×1920, 30fps 완성 영상에서 지원합니다.')
    scale, deltas, _, _ = video_timing(source_video)
    if len(deltas) != int(a['nb_read_frames']):
        raise ValueError('썸네일 원본과 현재 완성본의 길이가 다릅니다.')
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
    prefix, joined = folder/'thumbnail-frame.mp4', folder/'thumbnail-joined.mp4'
    color = []
    for key, option in [('color_range','-color_range'), ('color_space','-colorspace'),
                        ('color_transfer','-color_trc'), ('color_primaries','-color_primaries')]:
        if a.get(key) and a[key] not in ('unknown', 'unspecified'):
            color += [option, a[key]]
    def encode(args):
        subprocess.run([ffmpeg, '-y', '-v', 'error', *map(str, args)], check=True,
            capture_output=True, timeout=studio.settings.auto_capcut_timeout)
    # Encode one cover sample; retain all original P/B reference samples.
    encode(['-i', cover, '-frames:v', '1', '-r', '30', '-c:v', 'libx264', '-crf', '18',
            '-preset', 'medium', '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-bf', '0',
            *color, '-video_track_timescale', scale, prefix])
    listing = folder/'thumbnail-concat.txt'
    def concat_path(path):
        return "file '"+path.as_posix().replace("'", "'\\''")+"'\n"
    listing.write_text(concat_path(prefix.resolve())+'duration 0.03333333333333333\n'+
                       concat_path(source_video), encoding='utf-8')
    encode(['-f', 'concat', '-safe', '0', '-i', listing, '-i', source_video,
            '-map', '0:v:0', '-map', '1:a?', '-c', 'copy', *color,
            '-video_track_timescale', scale, '-movie_timescale', scale, joined])
    present_cover(joined, source_video, target)
    if target.stat().st_size > source_video.stat().st_size+max(512*1024, source_video.stat().st_size//10):
        raise RuntimeError('썸네일 반영 후 파일 용량이 예상보다 크게 증가했습니다.')
    rendered = metadata(target)
    b = next(s for s in rendered['streams'] if s['codec_type']=='video')
    if any(a.get(k) != b.get(k) for k in ('width', 'height', 'r_frame_rate', 'nb_read_frames')):
        raise RuntimeError('썸네일 반영 후 영상 규격·프레임 수가 달라졌습니다.')
    if abs(float(original['format']['duration'])-float(rendered['format']['duration'])) > .04:
        raise RuntimeError('썸네일 반영 후 영상 길이가 달라졌습니다.')
    def frames(path):
        output = subprocess.run([ffmpeg, '-v', 'error', '-i', str(path), '-map', '0:v:0',
            '-pix_fmt', 'yuv420p', '-f', 'framemd5', '-'], check=True, capture_output=True,
            encoding='utf-8', timeout=studio.settings.auto_capcut_timeout).stdout
        return [r for r in output.splitlines() if r and not r.startswith('#')]
    before_frames, after_frames = frames(base), frames(target)
    if len(before_frames) != len(after_frames) or before_frames[1:] != after_frames[1:]:
        raise RuntimeError('썸네일 반영 후 본문 프레임·타이밍이 달라졌습니다.')
    if any(s['codec_type']=='audio' for s in original['streams']):
        def audio_hash(path):
            return subprocess.run([ffmpeg,'-v','error','-i',str(path),'-map','0:a','-c','copy','-f','hash','-'],
                capture_output=True, check=True, timeout=120).stdout
        if audio_hash(base) != audio_hash(target):
            raise RuntimeError('썸네일 반영 후 음성이 달라졌습니다.')
    joined.unlink()
    prefix.unlink()
    revised = copy.deepcopy(plan)
    revised['thumbnail_document'] = document
    revised.setdefault('cover_spec', {})['background_path'] = str(background)
    revised['cover_mode'] = 'replace_first_frame'
    timeline = folder/'thumbnail-timeline.json'
    _atomic_json(timeline, revised)
    return {'plan_path':str(timeline), 'preview_path':str(target), 'export_path':str(target),
            'cover_path':str(cover), 'export_kind':'thumbnail', 'thumbnail_encoding':'stream_copy', 'export_verified':True,
            'exported_at':time.time(), 'duration':edit['duration'], 'review_count':0,
            **({'clean_preview_path':edit['clean_preview_path']} if edit.get('clean_preview_path') else {})}
