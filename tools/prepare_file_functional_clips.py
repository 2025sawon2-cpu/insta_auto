"""Reviewable, nonrepeating file-holder derivatives; no production worker."""
import json
import os
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw
from hotpost.editing_adapter import _atomic_json as save
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file

ROOT = Path('data/file-functional-quality-20261011-v3/DeRFXHpEwck/final').resolve()
PINK = Path('data/tiktok-rework-20261011/DeRFXHpEwck/videos/7626973899581885714.mp4').resolve()
GREEN = Path('data/selected-three-quality/DeRFXHpEwck/supplemental/videos/02_youtube_-ndxbCX_YyM.mp4').resolve()
RED = Path('data/selected-three-quality/DeRFXHpEwck/supplemental/videos/04_youtube_34PkoszxGeI.mp4').resolve()
DEFINITIONS = [
    ('pink-display', PINK, 32.5, 35.9, None, 'context', '분홍색 미니 봉투 홀더를 들어 보여줌'),
    ('pink-use', PINK, 35.9, 40.55, None, 'core', '벨크로 덮개를 열고 카드형 종이와 작은 포장 소품을 넣은 뒤 닫음'),
    ('green-fastener', GREEN, 14.3, 17.4, [.42, 0, 1, 1], 'context', '큰 봉투 홀더의 흰 벨크로 패치를 떼어 여는 구조 설명 예시'),
    ('red-fastener', RED, 17.4, 21.6, [.07, 0, .72, 1], 'context', '큰 빨간 봉투 홀더의 원형 벨크로를 눌러 붙이는 구조 설명 예시'),
]


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    if (ROOT / 'proposed-sources.json').exists():
        print('Existing review derivatives retained.', flush=True)
        return
    bins = next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']
    sheet = Image.new('RGB', (720, 345 * len(DEFINITIONS)), '#222')
    draw = ImageDraw.Draw(sheet)
    rows = []
    for j, (name, original, start, end, crop, role, observation) in enumerate(DEFINITIONS):
        target = ROOT / 'clips' / (name + '.mp4')
        target.parent.mkdir(exist_ok=True)
        original_meta = probe_video(original)
        vf = ''
        if crop:
            w, h = original_meta['width'], original_meta['height']
            x, y, x2, y2 = crop
            vf = f'crop={int(w*(x2-x))//2*2}:{int(h*(y2-y))//2*2}:{int(w*x)//2*2}:{int(h*y)//2*2},'
        vf += 'scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=30'
        # Keep product action visible; a small observed mark is the only mask.
        masks = []
        if original == PINK:
            vf += ',split[base][mark];[mark]crop=110:44:85:617,boxblur=10:2[blur];[base][blur]overlay=85:617'
            masks.append([85, 617, 110, 44])
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-t', str(end-start),
                        '-i', str(original), '-an', '-vf', vf, '-c:v', 'libx264', '-preset', 'veryfast',
                        '-crf', '18', str(target)], check=True, capture_output=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(target), '-f', 'null', '-'],
                       check=True, capture_output=True)
        meta = probe_video(target)
        frames = []
        for i, fraction in enumerate((.05, .35, .65, .95)):
            timestamp = (meta['duration'] - .05) * fraction
            frame = target.with_name(name + f'-{i}.jpg')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(timestamp), '-i', str(target),
                            '-frames:v', '1', str(frame)], check=True, capture_output=True)
            frames.append({'path': str(frame), 'timestamp': timestamp, 'sha256': sha256_file(frame)})
            with Image.open(frame) as im:
                im.thumbnail((180, 320)); sheet.paste(im, (i*180, j*345+25))
            draw.text((i*180+3, j*345+3), f'{name} {timestamp:.2f}', fill='white')
        vid = '7626973899581885714' if original == PINK else ('-ndxbCX_YyM' if original == GREEN else '34PkoszxGeI')
        url = 'https://www.tiktok.com/@inbin.asmr/video/' + vid if original == PINK else 'https://www.youtube.com/watch?v=' + vid
        rows.append({'id': 'file-functional-v3-' + name, 'name': name, 'path': str(target),
                     'sha256': sha256_file(target), 'video_meta': meta, 'url': url, 'origin_url': url,
                     'original_path': str(original), 'original_sha256': sha256_file(original),
                     'original_interval': {'start': start, 'end': end}, 'source_role': role,
                     'provider': 'tiktok' if original == PINK else 'youtube', 'rights': 'unknown-check-before-reuse',
                     'proposed_observation': observation, 'evidence_frames': frames, 'crop': crop,
                     'preprocessed_blur_regions_px': masks, 'full_decode_passed': True,
                     'pending_visual_review': True, 'editing_eligible': False,
                     'exact_reference_sku_confirmed': False,
                     'internal_repeat_rule': 'Pink preview3–10s excluded; later32.5–40.55s used once only.'})
    sheet.save(ROOT / 'clip-review.jpg', quality=94)
    save(ROOT / 'proposed-sources.json', rows)
    print('Four new bounded portrait clips decoded; actual visual review required.', flush=True)


if __name__ == '__main__':
    main()
