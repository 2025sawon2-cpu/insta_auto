"""Offline assembly of the one observed player's saved clear UMP responses."""
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
from hotpost.youtube_ump import BrowserUmpMedia
from hotpost.tiktok_download import publish_video
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file
from hotpost.editing_adapter import _atomic_json as save

ROOT = Path('data/daily-rework-20261011/DeRFXHpEwck/youtube-photo-case-xxQiZmoYNTE').resolve()


def assemble(root=ROOT):
    receipt = json.loads((root / 'reception.json').read_text('utf-8'))
    video_id = receipt.get('video_id', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id) or receipt.get('url') != 'https://www.youtube.com/shorts/' + video_id:
        raise ValueError('Expected the already inspected player only.')
    bins = next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']
    media = BrowserUmpMedia(receipt['video_id'])
    for packet in receipt.get('ump_bodies', []):
        path = Path(packet['path']).resolve()
        if path.parent != root / 'ump-responses' or sha256_file(path) != packet['sha256']:
            raise ValueError('Saved browser response identity changed.')
        media.add(path.read_bytes())
    rows = []
    for track in media.contiguous_tracks():
        entry = {k:v for k,v in track.items() if k != 'body'}
        entry['bytes'] = len(track['body'])
        target = root / f'itag-{track["itag"]}-clear.mp4'
        if not track['gap_free']:
            rows.append(entry)
            continue
        if target.exists():
            if sha256_file(target) != hashlib.sha256(track['body']).hexdigest():
                raise ValueError('Existing analysis original must be preserved.')
            published = True
        else:
            published = publish_video(track['body'], target, receipt['visible_player']['duration'])
        if published:
            meta = probe_video(target)
            if abs(meta['duration'] - receipt['visible_player']['duration']) > 1:
                raise ValueError('Saved video duration does not match the visible player.')
            subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(target), '-f', 'null', '-'],
                           check=True, capture_output=True)
            entry.update(path=str(target), sha256=sha256_file(target), video_meta=meta,
                         full_decode_passed=True, editing_eligible=False)
        rows.append(entry)
    report = {'video_id': receipt['video_id'], 'source': 'actual completed browser UMP responses',
              'completed': any(t.get('full_decode_passed') for t in rows),
              'ignored_other_video_headers': media.ignored_other_video_headers, 'tracks': rows,
              'rights': 'unknown-check-before-reuse', 'analysis_only': True,
              'source_references': ['https://github.com/LuanRT/googlevideo/blob/main/src/core/UmpReader.ts',
                                    'https://github.com/LuanRT/googlevideo/blob/main/protos/video_streaming/media_header.proto']}
    save(root / 'ump-reassembly.json', report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


if __name__ == '__main__':
    assemble()
