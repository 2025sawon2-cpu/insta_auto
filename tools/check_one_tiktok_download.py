"""One observed candidate, one existing-tab load, no retry or alternate video."""
import json
import time
from hotpost.config import load_settings
from hotpost.source_finder import probe_video
from hotpost.tiktok_download import download


def main():
    settings = load_settings()
    root = settings.data_dir / 'tiktok-diagnostics-20261011'
    original = json.loads((root / 'browser-download-check.json').read_text(encoding='utf-8'))
    url = original['url']
    target = root / 'browser-videos' / ('one-check-' + str(time.time_ns()) + '.mp4')
    report = {'url': url, 'session': 'existing logged-in collector Chrome',
              'candidate_count': 1, 'attempt_count': 1, 'diagnostics': {}, 'path': None}
    try:
        path = download(settings, url, target, 80 * 1024 * 1024,
                        deadline=time.monotonic() + 180, diagnostics=report['diagnostics'])
        report.update(path=str(path), meta=probe_video(path))
    except Exception as exc:
        report['error'] = str(exc)[:1000]
    receipt = root / 'one-download-check.json'
    if receipt.exists():
        receipt.rename(root / ('one-download-check-before-' + str(time.time_ns()) + '.json'))
    receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
