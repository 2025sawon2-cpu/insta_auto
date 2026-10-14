"""Inspect the previously unused final cart action at half-second spacing."""
import json
import argparse
import os
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw
from hotpost.editing_adapter import _atomic_json
from hotpost.source_quality import sha256_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--video', default='7633755703873817877')
    parser.add_argument('--start', type=float, default=50)
    parser.add_argument('--step', type=float, default=.5)
    args = parser.parse_args()
    root = Path('data/daily-rework-20261011/DeTJ6HbKCdF')
    ledger = json.loads((root / 'discovery.json').read_text('utf-8'))
    row = next(r for r in ledger['candidates'] if r['url'].endswith('/' + args.video))
    path = Path(row['path'])
    folder = root / 'cart-motion-review' / f'{args.video}-{args.start:g}-{args.step:g}'
    folder.mkdir(parents=True, exist_ok=True)
    bins = next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']
    sheet = Image.new('RGB', (800, 1512), '#222')
    draw = ImageDraw.Draw(sheet)
    frames = []
    for i in range(16):
        second = args.start + i * args.step
        frame = folder / f'{second:.1f}.jpg'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(second), '-i', str(path),
                        '-frames:v', '1', '-vf', 'scale=200:356', str(frame)],
                       check=True, capture_output=True, timeout=30)
        with Image.open(frame) as im:
            sheet.paste(im, ((i % 4) * 200, (i // 4) * 378))
        draw.text(((i % 4) * 200 + 3, (i // 4) * 378 + 358), f'{second:.1f}s', fill='white')
        frames.append({'path': str(frame.resolve()), 'timestamp': second, 'sha256': sha256_file(frame)})
    sheet.save(folder / 'contact.jpg', quality=93)
    _atomic_json(folder / 'sampling.json', {'url': row['url'], 'source': str(path.resolve()),
        'source_sha256': sha256_file(path), 'frames': frames, 'actual_review_pending': True,
        'new_download': args.video == '7668652651189439764'})
    print(str(folder / 'contact.jpg'), flush=True)


if __name__ == '__main__':
    main()
