"""Recover today's failed ASR from preserved media; never repeat account collection."""
import json
import shutil
import time
from pathlib import Path

from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json
from hotpost.storage import Storage
from hotpost.transcript import _isolated_speech
from hotpost.source_quality import sha256_file

CODES = ('DeTaESASnr_', 'DeSvpmAsWgZ', 'DeTJ6HbKCdF', 'DeSoiZvyyqj', 'DeSngDcTAUJ')
ROOT = Path(__file__).resolve().parents[1] / 'data/daily-rework-20261011'


def main():
    settings = load_settings()
    ROOT.mkdir(parents=True, exist_ok=True)
    store = Storage(settings.db_path)
    try:
        for code in CODES:
            receipt = ROOT / code / 'transcript-recovery.json'
            if receipt.exists() and json.loads(receipt.read_text('utf-8')).get('status') == 'done':
                continue
            old = max((p for p in settings.transcript_dir.glob(code+'-*')
                       if 'recovery' not in p.name and (p/'transcript.json').exists()),
                      key=lambda p: p.stat().st_mtime)
            source = json.loads((old/'transcript.json').read_text('utf-8'))
            output = settings.transcript_dir / (code+'-recovery-'+str(time.time_ns()))
            output.mkdir()
            for name in ('reference.mp4', 'audio.wav'):
                shutil.copy2(old/name, output/name)
            identity = sha256_file(output/'reference.mp4')
            assert identity == sha256_file(old/'reference.mp4')
            job, created = store.create_job('recover-asr-'+code+'-'+str(time.time_ns()), 'transcript', code)
            if not created:
                raise RuntimeError(code+': existing live transcript job; do not duplicate')
            store.update_job(job['id'], status='running', started_at=int(time.time()), message='보존 오디오 재전사')
            _atomic_json(receipt, {'status':'running', 'job_id':job['id'], 'directory':str(output),
                                  'previous':str(old), 'video_sha256':identity})
            print(code+' actual ASR started', flush=True)
            try:
                notes = []
                speech, language, method = _isolated_speech(settings, output/'audio.wav', notes)
                if not speech:
                    raise ValueError('호환 오류 보완 후에도 실제 발화를 인식하지 못했습니다.')
                result = {**source, 'speech':speech, 'language':language,
                          'lines':sorted([*speech, *source['screen_text']], key=lambda r:(r['start'],r['source']!='speech')),
                          'methods':{**source['methods'], 'speech':method},
                          'notes':['재전사: 보존된 실제 오디오를 사용했습니다. 화면 글자는 음성으로 승격하지 않았습니다.', *notes],
                          'created_at':int(time.time()), 'recovered_from':str(old),
                          'json_path':str(output/'transcript.json'), 'text_path':str(output/'transcript.txt')}
                _atomic_json(output/'transcript.json', result)
                (output/'transcript.txt').write_text('\n'.join('[음성] '+r['text'] for r in speech)+'\n\n'+
                    '\n'.join('[화면 글자] '+r['text'] for r in source['screen_text'])+'\n', 'utf-8')
                store.update_job(job['id'], status='done', progress=100, message='실제 음성 재전사 완료',
                    result_json=json.dumps(result,ensure_ascii=False), result_path=result['json_path'], finished_at=int(time.time()))
                _atomic_json(receipt, {'status':'done', 'job_id':job['id'], 'directory':str(output),
                    'previous':str(old), 'video_sha256':identity, 'speech_segments':len(speech), 'method':method})
                print(code+' actual ASR recovered '+str(len(speech))+' segments', flush=True)
            except Exception as exc:
                store.update_job(job['id'], status='error', error=str(exc)[:600], finished_at=int(time.time()))
                _atomic_json(receipt, {'status':'error', 'job_id':job['id'], 'directory':str(output), 'error':str(exc)})
                print(code+' recovery error: '+str(exc), flush=True)
    finally:
        store.close()

if __name__ == '__main__':
    main()
