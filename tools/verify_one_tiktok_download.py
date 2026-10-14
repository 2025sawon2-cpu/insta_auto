"""Local full decode and spaced frame inspection; no browser/network activity."""
import json
from pathlib import Path
import shutil
import subprocess
from PIL import Image, ImageDraw
from hotpost.config import load_settings


root = load_settings().data_dir / 'tiktok-diagnostics-20261011'
receipt = root / 'one-download-check.json'
report = json.loads(receipt.read_text(encoding='utf-8'))
path = Path(report['path'])
ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
decode = subprocess.run([ffmpeg, '-hide_banner', '-v', 'error', '-xerror', '-i', str(path),
    '-map', '0:v:0', '-map', '0:a?', '-f', 'null', '-'], capture_output=True, text=True, timeout=120)
streams = subprocess.run([ffprobe, '-v', 'error', '-show_entries',
    'stream=codec_type,codec_name,width,height,sample_rate,channels,duration:format=duration',
    '-of', 'json', str(path)], capture_output=True, text=True, timeout=30)
qa = path.parent / (path.stem + '-qa')
qa.mkdir(exist_ok=True)
sheet = Image.new('RGB', (720, 896), '#202020')
draw = ImageDraw.Draw(sheet)
times = [0, 17, 35, 53, 71, 87.3]
for i, seconds in enumerate(times):
    frame = qa / f'frame-{i}.jpg'
    subprocess.run([ffmpeg, '-hide_banner', '-v', 'error', '-y', '-ss', str(seconds),
        '-i', str(path), '-frames:v', '1', '-vf', 'scale=240:426', str(frame)], check=True, capture_output=True, timeout=30)
    with Image.open(frame) as img:
        x, y = (i % 3)*240, (i // 3)*448
        sheet.paste(img, (x,y))
        draw.text((x+5,y+429), f'{seconds}s', fill='white')
contact = qa / 'contact.jpg'
sheet.save(contact, quality=90)
report['verification'] = {'full_decode_ok': decode.returncode == 0, 'decode_errors': decode.stderr[:1000],
    'streams':json.loads(streams.stdout), 'contact_sheet':str(contact)}
receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report['verification'], ensure_ascii=False))
