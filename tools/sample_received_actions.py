"""Save dense decoded evidence from a completed browser receipt, without approval."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw
from hotpost.editing_adapter import _atomic_json
from hotpost.source_quality import sha256_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--start', type=float, required=True)
    parser.add_argument('--end', type=float, required=True)
    args = parser.parse_args()
    receipt = json.loads((args.root / 'source-reception.json').read_text('utf-8'))
    assert receipt['completed'] and receipt['browser_reception']['full_decode_passed']
    raw = Path(receipt['path'])
    assert sha256_file(raw) == receipt['sha256']
    assert 0 <= args.start < args.end < receipt['video_meta']['duration']
    folder = args.root / f'dense-{args.start:g}-{args.end:g}'
    folder.mkdir(exist_ok=True)
    bins = next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']
    sheet = Image.new('RGB', (960, 1808), '#222')
    draw = ImageDraw.Draw(sheet)
    frames = []
    for i in range(16):
        second = args.start + (args.end - args.start) * i / 15
        frame = folder / f'{i:02d}.jpg'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(second), '-i', str(raw),
                        '-frames:v', '1', '-vf', 'scale=240:426', str(frame)],
                       check=True, capture_output=True, timeout=30)
        with Image.open(frame) as im:
            sheet.paste(im, (i % 4 * 240, i // 4 * 452 + 24))
        draw.text((i % 4 * 240 + 3, i // 4 * 452 + 3), f'{second:.3f}s', fill='white')
        frames.append({'path': str(frame.resolve()), 'timestamp': second, 'sha256': sha256_file(frame)})
    sheet.save(folder / 'contact.jpg', quality=94)
    _atomic_json(folder / 'sampling.json', {'source_sha256': receipt['sha256'],
        'source': str(raw.resolve()), 'url': receipt['url'], 'frames': frames,
        'actual_visual_review_pending': True, 'new_download_in_this_sampling': False})
    print(str(folder / 'contact.jpg'), flush=True)


if __name__ == '__main__':
    main()
