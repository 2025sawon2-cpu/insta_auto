"""Explicit thumbnail replacement, independent of the retired production runner."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid

from PIL import Image, ImageDraw, ImageFilter, ImageFont
import psutil
from .post_media_rules import DISCLOSURE_VERSION, disclosure_layer, mark_cover
from .source_quality import sha256_file

_admission = threading.Lock()
_execution = threading.Lock()
ACTIVE = ('queued', 'running')


def active_assets(service, code, edit_id):
    path = service.root / 'post-preparations' / code / 'active.json'
    try:
        value = json.loads(path.read_text('utf8'))
        if value['source_edit_id'] != edit_id:
            return None
        if not all(service._file(value[k]) for k in ('final', 'cover')):
            return None
        return value
    except (OSError, ValueError, KeyError):
        return None


def job_status(service, code):
    with service.connect() as db:
        row = db.execute('SELECT * FROM thumbnail_jobs WHERE shortcode=? ORDER BY created DESC LIMIT 1', (code,)).fetchone()
        return _job_status(db, row)


def _job_status(db, row):
    if row is None:
        return {'status': 'idle', 'message': ''}
    row = dict(row)
    if row['status'] in ACTIVE:
        try:
            alive = abs(psutil.Process(row['owner_pid']).create_time() - row['owner_birth']) < .01
        except psutil.NoSuchProcess:
            alive = False
        except psutil.Error:
            # An inaccessible process is not evidence that its render stopped.
            alive = True
        if not alive:
            db.execute("UPDATE thumbnail_jobs SET status='failed',message=?,updated=? "
                       "WHERE id=? AND status IN ('queued','running')",
                       ('썸네일 반영이 중단됐어요. 현재 공개 결과를 확인한 뒤 다시 반영해 주세요.', time.time(), row['id']))
            row = dict(db.execute('SELECT * FROM thumbnail_jobs WHERE id=?', (row['id'],)).fetchone())
    return {key: row[key] for key in ('id', 'status', 'message', 'text', 'created', 'updated')}


def update(service, job, status, message):
    with service.connect() as db:
        db.execute('UPDATE thumbnail_jobs SET status=?,message=?,updated=? WHERE id=?', (status, message, time.time(), job))


def command(args, timeout=240):
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf8', errors='replace', timeout=timeout,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise RuntimeError(result.stderr[-1800:] or '영상 처리 명령이 실패했습니다.')
    return result.stdout


def probe(path):
    return json.loads(command([shutil.which('ffprobe') or 'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))


def paint_cover(background, font_path, text, output, style=None):
    image = Image.open(background).convert('RGB')
    width, height = image.size
    style = style or {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) == 1 and len(lines[0]) > 12:
        value = lines[0]
        breaks = [i for i, char in enumerate(value) if char == ' ']
        midpoint = min(breaks, key=lambda n: abs(n-len(value)/2)) if breaks else len(value)//2
        lines = [value[:midpoint].strip(), value[midpoint:].strip()]
    if len(lines) > 3:
        raise ValueError('썸네일 문구를 세 줄 이내로 정리해 주세요.')
    if not lines:
        raise ValueError('반영할 썸네일 문구를 입력해 주세요.')
    font_path = str(font_path)
    full = Image.new('RGBA', image.size)
    center = style.get('center', [width/2, height*.3125])
    gap = min(style.get('line_gap', 160), height*.09)
    for i, line in enumerate(lines):
        size = int((style.get('font_sizes') or [136,156])[min(i,1)])
        while size > 28 and ImageFont.truetype(font_path, size).getlength(line) > width*.82:
            size -= 1
        font = ImageFont.truetype(font_path, size)
        if font.getlength(line) > width*.82:
            raise ValueError('문구가 길어 화면에 들어가지 않아요. 짧게 줄이거나 줄을 나눠 주세요.')
        missing = font.getmask(chr(0x10ffff))
        for char in line:
            mask = font.getmask(char)
            if not char.isspace() and mask.size == missing.size and bytes(mask) == bytes(missing):
                raise ValueError(f'썸네일 폰트에서 표시할 수 없는 문자예요: {char}')
        row = Image.new('RGBA', image.size)
        draw = ImageDraw.Draw(row)
        y = center[1] + (i-(len(lines)-1)/2)*gap
        draw.text((center[0], y), line, font=font, anchor='mm', fill='white' if i == 0 else '#ffdf40',
                  stroke_width=int(style.get('outline', 5)), stroke_fill='black')
        shadow = Image.new('RGBA', image.size)
        alpha = row.getchannel('A').filter(ImageFilter.GaussianBlur(2))
        shadow.paste((0,0,0,200), (5,7), alpha)
        shadow.alpha_composite(row)
        full.alpha_composite(shadow)
    full = full.rotate(-float(style.get('rotation', -8)), Image.Resampling.BICUBIC, center=tuple(center))
    bounds = full.getbbox()
    if bounds and (bounds[0] < 8 or bounds[2] > width-8):
        raise ValueError('썸네일 문구가 화면 가장자리에 닿아요. 문구를 조금 줄여 주세요.')
    Image.alpha_composite(image.convert('RGBA'), full).convert('RGB').save(output)
    mark_cover(output, font_path)


def hashes(path, *, audio=False, crop=None):
    ffmpeg = shutil.which('ffmpeg') or 'ffmpeg'
    args = [ffmpeg, '-v', 'error', '-i', str(path)]
    if audio:
        return command(args + ['-map', '0:a:0', '-c', 'copy', '-f', 'hash', '-hash', 'sha256', '-']).strip()
    output = command(args + ['-map', '0:v:0', '-an'] + (['-vf', crop] if crop else []) +
                     ['-pix_fmt', 'yuv420p', '-f', 'framemd5', '-'])
    return [line.rsplit(',', 1)[-1].strip() for line in output.splitlines() if line and not line.startswith('#')]


def add_disclosure(original, output, font_path):
    info = probe(original)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    layer = disclosure_layer((video['width'], video['height']), font_path)
    overlay = output.with_suffix('.disclosure.png')
    layer.save(overlay)
    command([shutil.which('ffmpeg') or 'ffmpeg', '-v','error','-y','-i',str(original),'-i',str(overlay),
             '-filter_complex','[0:v][1:v]overlay=0:0:format=yuv420[v]', '-map','[v]','-map','0:a?',
             '-c:v','libx264','-preset','fast','-qp','0','-pix_fmt','yuv420p',
             '-fps_mode','passthrough','-c:a','copy','-movflags','+faststart',str(output)])
    # Decode exact pixels outside a conservative even-aligned disclosure rectangle.
    x0,y0,x1,y1 = layer.getbbox()
    left, bottom = x0//2*2, (y1+3)//2*2
    for crop in (f'crop={left}:ih:0:0', f'crop=iw:ih-{bottom}:0:{bottom}'):
        if hashes(original,crop=crop) != hashes(output,crop=crop):
            raise ValueError('광고 표기 영역 밖의 영상이 달라져 교체하지 않았습니다.')
    if any(s['codec_type']=='audio' for s in info['streams']) and hashes(original,audio=True)!=hashes(output,audio=True):
        raise ValueError('광고 표기 중 음성이 달라져 교체하지 않았습니다.')


def replace_first_frame(original, cover, output):
    info = probe(original)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    rate = video.get('avg_frame_rate', '30/1')
    numerator, denominator = map(int, rate.split('/'))
    if numerator <= 0 or denominator <= 0:
        raise ValueError('영상 프레임 속도를 확인할 수 없습니다.')
    threshold = denominator/numerator/2
    ffmpeg = shutil.which('ffmpeg') or 'ffmpeg'
    command([ffmpeg, '-v', 'error', '-y', '-i', str(original), '-i', str(cover),
             '-filter_complex', f"[1:v]format=yuv420p[c];[0:v][c]overlay=0:0:enable='lt(t,{threshold:.10f})':format=yuv420[v]",
             '-map', '[v]', '-map', '0:a?', '-map_metadata', '0', '-c:v', 'libx264', '-preset', 'fast',
             '-qp', '0', '-pix_fmt', 'yuv420p', '-fps_mode', 'passthrough', '-c:a', 'copy', '-movflags', '+faststart', str(output)])


def verify(original, updated):
    before, after = probe(original), probe(updated)
    first = next(s for s in before['streams'] if s['codec_type'] == 'video')
    second = next(s for s in after['streams'] if s['codec_type'] == 'video')
    if (first['width'], first['height']) != (second['width'], second['height']):
        raise ValueError('썸네일 반영 후 영상 크기가 달라졌습니다.')
    left, right = hashes(original), hashes(updated)
    if len(left) != len(right) or left[1:] != right[1:]:
        raise ValueError('첫 화면 외 영상 프레임이 달라져 교체하지 않았습니다.')
    if abs(float(before['format']['duration']) - float(after['format']['duration'])) > .05:
        raise ValueError('영상 길이가 달라져 교체하지 않았습니다.')
    audio = any(s['codec_type'] == 'audio' for s in before['streams'])
    if audio and hashes(original, audio=True) != hashes(updated, audio=True):
        raise ValueError('음성 데이터가 달라져 교체하지 않았습니다.')
    return {'frames': len(left), 'body_frames_identical': True, 'audio_identical': audio}


def encode_delivery(original, output):
    """Keep lossless editing masters private; deliver hardware-decodable AVC."""
    before = probe(original)
    audio = [s for s in before['streams'] if s['codec_type'] == 'audio']
    copy_audio = all(s['codec_name'] == 'aac' and s.get('profile') == 'LC'
                     and int(s['sample_rate']) <= 48000 and s['channels'] <= 2 for s in audio)
    audio_args = ['-c:a', 'copy'] if copy_audio else ['-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2']
    command([shutil.which('ffmpeg') or 'ffmpeg', '-v', 'error', '-y', '-i', str(original),
             '-map', '0:v:0', '-map', '0:a?', '-map_metadata', '0',
             '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-profile:v', 'main',
             '-level:v', '4.0', '-pix_fmt', 'yuv420p', '-maxrate', '12M', '-bufsize', '24M',
             '-fps_mode', 'passthrough', *audio_args, '-movflags', '+faststart', str(output)])
    after = probe(output)
    first = next(s for s in before['streams'] if s['codec_type'] == 'video')
    second = next(s for s in after['streams'] if s['codec_type'] == 'video')
    if (second['codec_name'], second.get('profile'), second.get('pix_fmt'), second.get('level')) != ('h264', 'Main', 'yuv420p', 40):
        raise ValueError('휴대폰 재생용 영상 코덱 검증에 실패했습니다.')
    for key in ('width', 'height', 'nb_frames', 'avg_frame_rate'):
        if first.get(key) != second.get(key) or first.get(key) is None:
            raise ValueError('휴대폰 재생용 변환 중 영상 크기·프레임이 달라졌습니다.')
    if abs(float(before['format']['duration']) - float(after['format']['duration'])) > .05:
        raise ValueError('휴대폰 재생용 변환 중 영상 길이가 달라졌습니다.')
    if audio and copy_audio and hashes(original, audio=True) != hashes(output, audio=True):
        raise ValueError('휴대폰 재생용 변환 중 음성이 달라졌습니다.')
    command([shutil.which('ffmpeg') or 'ffmpeg', '-v', 'error', '-xerror', '-i', str(output), '-f', 'null', '-'])
    return {'codec': 'h264', 'profile': 'Main', 'level': '4.0', 'pix_fmt': 'yuv420p',
            'frames': int(second['nb_frames']), 'duration': float(after['format']['duration']),
            'audio_bitstream_identical': bool(audio) and copy_audio, 'full_decode_passed': True,
            'lossy_video_delivery': True, 'phone_playback_verified': False}


def start(service, code, payload):
    from .post_preparation import DraftConflict
    if not isinstance(payload, dict) or set(payload) != {'revision'} or type(payload['revision']) is not int:
        raise ValueError('저장된 초안 버전을 확인해 주세요.')
    with _admission:
        previous = job_status(service, code)
        if previous['status'] in ACTIVE:
            return previous
        state = service.get(code)
        if payload['revision'] != state['revision']:
            raise DraftConflict('문구가 변경됐어요. 초안을 저장한 뒤 다시 반영해 주세요.')
        source = service.source(code)
        if not source.get('thumbnail_ready'):
            raise ValueError('완성 영상과 원본 썸네일 배경이 준비된 뒤 반영할 수 있어요.')
        draft = state['draft']
        text = draft['thumbnail_options'][draft['selected_thumbnail']].strip()
        if not text:
            raise ValueError('반영할 썸네일 문구를 입력해 주세요.')
        job = uuid.uuid4().hex
        now = time.time()
        with service.connect() as db:
            # Both publication servers share this DB. Process-local locks alone
            # allow duplicate renders and simultaneous work on different videos.
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute("SELECT * FROM thumbnail_jobs WHERE status IN ('queued','running')").fetchall():
                active = _job_status(db, row)
                if active['status'] in ACTIVE:
                    if row['shortcode'] == code:
                        return active
                    raise DraftConflict('다른 영상의 썸네일을 반영 중입니다. 완료 후 다시 반영해 주세요.')
            saved = db.execute('SELECT revision FROM drafts WHERE shortcode=?', (code,)).fetchone()
            if (saved['revision'] if saved else 0) != payload['revision']:
                raise DraftConflict('문구가 변경됐어요. 초안을 저장한 뒤 다시 반영해 주세요.')
            db.execute('INSERT INTO thumbnail_jobs VALUES (?,?,?,?,?,?,?,?,?)',
                       (job, code, 'queued', '새 썸네일을 준비하고 있어요…', text, now, now, os.getpid(), psutil.Process().create_time()))
        try:
            threading.Thread(target=_work, args=(service, code, job, text, source), daemon=True,
                             name='post-thumbnail-'+code).start()
        except Exception:
            update(service, job, 'failed', '썸네일 작업을 시작하지 못했습니다. 다시 반영해 주세요.')
            raise
        return job_status(service, code)


def _work(service, code, job, text, source):
    try:
        with _execution:
            update(service, job, 'running', '선택한 문구로 썸네일을 새로 만드는 중…')
            folder = service.root / 'post-preparations' / code
            output = folder / job
            output.mkdir(parents=True, exist_ok=False)
            cover, final, master = output/'cover.png', output/'final.mp4', output/'master.mp4'
            paint_cover(source['thumbnail_background'], source['thumbnail_font'], text, cover, source['thumbnail_style'])
            base = source['base_final']
            rules = dict(source.get('publication_rules', {}))
            if rules.get('advertising_disclosure') != DISCLOSURE_VERSION:
                update(service, job, 'running', '영상 전체에 우상단 광고 표시를 반영하고 있어요…')
                base = output/'disclosed-body.mp4'
                add_disclosure(source['base_final'], base, source['thumbnail_font'])
                rules['advertising_disclosure'] = DISCLOSURE_VERSION
            update(service, job, 'running', '새 썸네일을 완성 영상의 첫 화면에 반영하고 있어요…')
            replace_first_frame(base, cover, master)
            update(service, job, 'running', '영상과 음성이 그대로 유지됐는지 확인하고 있어요…')
            checks = verify(base, master)
            checks['verified_asset'] = 'master_final'
            update(service, job, 'running', '휴대폰에서 재생할 수 있는 다운로드 영상을 준비하고 있어요…')
            checks['delivery'] = encode_delivery(master, final)
            manifest = {'source_edit_id': source['edit_id'], 'text': text, 'cover': str(cover), 'final': str(final),
                        'body_final': str(base), 'master_final': str(master), 'rules': rules,
                        'spoken_text': source.get('spoken_text', ''),
                        'version': job, 'checks': checks, 'updated': time.time(),
                        'sha256': sha256_file(final)}
            temporary = folder / (job+'.json')
            temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), 'utf8')
            with service.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                current = service.source(code)
                if (current['edit_id'] != source['edit_id'] or current['base_final'] != source['base_final']
                        or current.get('media_version') != source.get('media_version')):
                    raise ValueError('작업 중 영상이 수정되어 교체하지 않았습니다. 다시 반영해 주세요.')
                os.replace(temporary, folder/'active.json')
                db.execute('UPDATE thumbnail_jobs SET status=?,message=?,updated=? WHERE id=?',
                           ('completed','반영 완료! 현재 썸네일과 완성 영상의 첫 화면을 교체했어요.',time.time(),job))
    except Exception as error:
        detail = str(error) if isinstance(error, ValueError) else '처리 중 오류가 발생했어요. 기존 영상은 유지됐습니다. 다시 반영해 주세요.'
        update(service, job, 'failed', detail)
        folder = service.root / 'post-preparations' / code / job
        folder.mkdir(parents=True, exist_ok=True)
        (folder/'error.txt').write_text(str(error), 'utf8')
