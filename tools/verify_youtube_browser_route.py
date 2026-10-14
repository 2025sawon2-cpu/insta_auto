"""One end-to-end candidate download of the already inspected YouTube result."""
import json
import os
from pathlib import Path
from hotpost.editing_adapter import _atomic_json as save
from hotpost.source_finder import Candidate, download_candidate, probe_video
from hotpost.source_quality import sha256_file


def main():
    root = Path('data/download-range-integration-20261011/youtube-production-route').resolve()
    receipt = root/'verification.json'
    if receipt.exists():
        print(receipt.read_text('utf-8'), flush=True)
        return
    bins = next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']
    out = root/'videos'; out.mkdir(parents=True, exist_ok=True)
    candidate = Candidate('https://www.youtube.com/shorts/E2vmIs5gmTc', 'youtube',
        title='파우치 하나로 가방 정리 끝! | 지갑으로 가방정리하기', query='영수증 파우치 가방 정리')
    path = download_candidate(candidate, out, 1, 80)
    result = {'completed': bool(path), 'error': candidate.error,
              'acquisition': candidate.acquisition, 'url':candidate.url,
              'scope':'one previously inspected actual source through general candidate route'}
    if path:
        browser = json.loads(path.with_suffix('.reception.json').read_text('utf-8'))
        previous = Path('data/daily-rework-20261011/DeRFXHpEwck/youtube-observed-E2vmIs5gmTc/itag-398-clear.mp4')
        result.update(path=str(path), sha256=sha256_file(path), video_meta=probe_video(path),
            previous_sha256=sha256_file(previous), matches_prior_actual_reception=sha256_file(path)==sha256_file(previous),
            reception=browser, editing_eligible=False)
    save(receipt, result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not path:
        raise RuntimeError('Actual general-route reception failed; inspect saved evidence.')


if __name__ == '__main__':
    main()
