"""Download one recorded visible result in the existing collector, then sample it."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from PIL import Image, ImageDraw
from hotpost.editing_adapter import _atomic_json as save
from hotpost.source_finder import Candidate, download_candidate, probe_video
from hotpost.source_quality import sha256_file
from hotpost.youtube_download import video_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--code', required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--attempt', default='', help='Separate evidence directory for a justified retry.')
    parser.add_argument('--visible-quality', choices=('360p', '720p', '1080p HD'),
                        help='Recover through an already open quality menu on this exact video.')
    args = parser.parse_args()
    identity = video_id(args.url)
    if (not identity or not re.fullmatch(r'[A-Za-z0-9_-]+', args.code)
            or (args.attempt and not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', args.attempt))):
        raise ValueError('Recorded product code and YouTube detail URL required.')
    product = Path('data/daily-rework-20261011') / args.code
    observed = []
    for path in (product / 'youtube-exact-product').glob('*/visible-results.json'):
        record = json.loads(path.read_text('utf-8'))
        if not record.get('blocked'):
            observed += [(path, row, record) for row in record.get('links', []) if video_id(row['url']) == identity]
    if not observed:
        raise ValueError('This source must first appear in a recorded visible search result.')
    evidence, row, search = max(observed, key=lambda item: item[2].get('time', 0))
    root = (product / ('youtube-observed-' + identity + ('-' + args.attempt if args.attempt else ''))).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'source-reception.json').exists():
        print('Existing source reception retained; no new request.', flush=True)
        return
    bins = next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']
    out = root / 'videos'; out.mkdir(exist_ok=True)
    candidate = Candidate(row['url'], 'youtube', title=row.get('text') or row.get('title') or '', query=search['query'])
    if args.visible_quality:
        from hotpost.config import load_settings
        from hotpost.youtube_download import download
        candidate.acquisition = 'existing-browser-playback'
        try:
            path = download(load_settings(), row['url'], out / f'01_youtube_{identity}.mp4',
                            80 * 1024 * 1024, visible_quality=args.visible_quality)
        except Exception as exc:
            path, candidate.error = None, str(exc)
    else:
        path = download_candidate(candidate, out, 1, 80)
    record = {'url': row['url'], 'title':candidate.title, 'query':candidate.query,
        'search_evidence':str(evidence.resolve()), 'completed':bool(path), 'error':candidate.error,
        'acquisition':candidate.acquisition, 'rights':'unknown-check-before-reuse', 'editing_eligible':False}
    if not path:
        save(root / 'source-reception.json', record)
        raise RuntimeError(candidate.error)
    meta = probe_video(path)
    record.update(path=str(path), sha256=sha256_file(path), video_meta=meta)
    reception = path.with_suffix('.reception.json')
    if reception.exists(): record['browser_reception'] = json.loads(reception.read_text('utf-8'))
    sheet = Image.new('RGB', (960, 4*455), '#222')
    draw = ImageDraw.Draw(sheet)
    frames = []
    for i in range(16):
        timestamp = (meta['duration'] - .1) * (i+.5) / 16
        frame = root / f'decoded-{i:02}.jpg'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(timestamp), '-i', str(path),
            '-frames:v', '1', str(frame)], check=True, capture_output=True)
        frames.append({'path':str(frame), 'timestamp':timestamp, 'sha256':sha256_file(frame)})
        with Image.open(frame) as im:
            im.thumbnail((240, 425)); sheet.paste(im, (i%4*240, i//4*455+25))
        draw.text((i%4*240+3, i//4*455+3), f'{timestamp:.2f}s', fill='white')
    sheet.save(root / 'decoded-review.jpg', quality=94)
    record.update(evidence_frames=frames, actual_visual_review_pending=True)
    save(root / 'source-reception.json', record)
    print(json.dumps({k:v for k,v in record.items() if k!='evidence_frames'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
