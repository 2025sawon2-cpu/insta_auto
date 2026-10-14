"""One-shot Windows ASR process; no browser, OCR or CLIP model is loaded."""
import argparse
import json
from pathlib import Path

from .config import Settings
from .transcript import _speech


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--result', required=True, type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding='utf-8'))
    notes = []
    partial = []
    def progress(segment):
        from .editing_adapter import _atomic_json
        # A CPU fallback starts a fresh hypothesis; preserve only increasing
        # decoded timestamps and never promote this receipt to completion.
        if partial and segment['end'] <= partial[-1]['end']:
            return
        partial.append(segment)
        _atomic_json(Path(request['audio']).parent / 'speech-partial.json',
            {'status':'partial', 'audio':request['audio'], 'speech':partial})
        print(f"out_time_us={int(segment['end'] * 1_000_000)}", flush=True)
    try:
        settings = Settings(data_dir=Path(request['data_dir']),
                            transcript_faster_whisper_model=request['model'])
        speech, language, method = _speech(settings, Path(request['audio']), notes, progress=progress)
        value = {'speech': speech, 'language': language, 'method': method, 'notes': notes}
        code = 0
    except Exception as error:
        value = {'error': type(error).__name__ + ': ' + str(error)[:180]}
        code = 1
    args.result.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
