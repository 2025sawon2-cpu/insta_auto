"""Download one already observed TikTok candidate, then decode and sample it."""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from PIL import Image, ImageDraw
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file
from hotpost.tikvideo_download import with_fallback


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--code', required=True)
    parser.add_argument('--video', required=True)
    args = parser.parse_args()
    if not args.video.isdigit():
        raise ValueError('A numeric, previously observed TikTok video ID is required.')
    root = Path('data/daily-rework-20261011') / args.code
    ledger = root / 'discovery.json'
    data = json.loads(ledger.read_text('utf-8'))
    rows = [r for r in data['candidates'] if r['url'].endswith('/' + args.video)]
    if len(rows) != 1:
        raise ValueError('Exactly one existing ledger candidate is required.')
    row = rows[0]
    settings = load_settings()
    if row.get('download_attempted') and not row.get('path'):
        raise RuntimeError('Previous failure retained; do not silently retry this candidate.')
    if not row.get('path'):
        diagnostics = {}
        row.update(selected=True, download_attempted=True, attempted_at=time.time(),
                   visual_review_pending=True)
        _atomic_json(ledger, data)
        target = root / 'videos' / (args.video + '.mp4')
        try:
            received = with_fallback(settings, row['url'], target, 80 * 1024 * 1024,
                                     deadline=time.monotonic() + 330, diagnostics=diagnostics)
            row.update(path=str(received.resolve()), video_meta=probe_video(received),
                       acquisition=diagnostics.get('method'), file_sha256=sha256_file(received))
        except Exception as exc:
            row['download_error'] = str(exc)[:1000]
            raise
        finally:
            row['download_diagnostics'] = diagnostics
            _atomic_json(ledger, data)
    path = Path(row['path'])
    bins = next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']
    decoded = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'null', '-'],
                             capture_output=True, timeout=120)
    if decoded.returncode:
        raise RuntimeError('Full-video decode failed: ' + decoded.stderr.decode('utf-8', 'replace')[:500])
    folder = root / 'review' / args.video
    folder.mkdir(parents=True, exist_ok=True)
    duration = row['video_meta']['duration']
    sheet = Image.new('RGB', (800, 1512), '#222')
    draw = ImageDraw.Draw(sheet)
    frames = []
    for i in range(16):
        second = min(duration - .1, duration * i / 15)
        frame = folder / f'{i:02}.jpg'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(second), '-i', str(path),
                        '-frames:v', '1', '-vf', 'scale=200:356:force_original_aspect_ratio=decrease',
                        str(frame)], check=True, capture_output=True, timeout=30)
        with Image.open(frame) as im:
            sheet.paste(im, ((i % 4) * 200, (i // 4) * 378))
        draw.text(((i % 4) * 200 + 3, (i // 4) * 378 + 358), f'{second:.2f}s', fill='white')
        frames.append({'path': str(frame.resolve()), 'timestamp': second, 'sha256': sha256_file(frame)})
    sheet.save(folder / 'contact.jpg', quality=92)
    _atomic_json(folder / 'decode-sampling.json', {'url': row['url'], 'path': str(path.resolve()),
        'sha256': sha256_file(path), 'meta': row['video_meta'], 'full_decode': True,
        'frames': frames, 'visual_review_pending': True, 'rights': row.get('rights', 'unknown-check-before-reuse')})
    print(json.dumps({'code': args.code, 'video': args.video, 'meta': row['video_meta'],
                      'full_decode': True, 'contact': str(folder / 'contact.jpg'),
                      'visual_review_pending': True}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
