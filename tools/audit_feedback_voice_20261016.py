"""Read existing synthesis receipts and acoustic proxies; never synthesize."""
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from scipy.signal import correlate, find_peaks


def measurements(path, text):
    result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', '1', '-ar', '16000',
        '-f', 'f32le', 'pipe:1'], check=True, capture_output=True)
    audio = np.frombuffer(result.stdout, dtype='<f4')
    size = 160
    frames = audio[:len(audio)//size*size].reshape(-1, size)
    rms = np.sqrt(np.mean(frames.astype(float)**2, axis=1))
    threshold = max(float(np.percentile(rms, 95))*10**(-35/20), 1e-5)
    quiet = rms < threshold
    changes = np.diff(np.r_[False, quiet, False].astype(int))
    pauses = [(int(a)*.01, int(b)*.01) for a, b in zip(np.where(changes == 1)[0], np.where(changes == -1)[0]) if b-a >= 20]
    pitches = []
    for start in range(0, len(audio)-640, 320):
        frame = audio[start:start+640].astype(float)
        if np.sqrt(np.mean(frame**2)) < threshold: continue
        frame = (frame-frame.mean())*np.hanning(len(frame))
        ac = correlate(frame, frame, mode='full', method='fft')[len(frame)-1:]
        if ac[0] <= 0: continue
        peaks, _ = find_peaks(ac[36:229])
        if not len(peaks): continue
        lags = peaks+36
        lag = int(lags[np.argmax(ac[lags])])
        if ac[lag]/ac[0] >= .55: pitches.append(16000/lag)
    duration = len(audio)/16000
    return {'duration':duration, 'hangul_syllables_per_second':len(re.findall('[가-힣]',text))/duration,
        'quiet_threshold_db_below_p95':35, 'quiet_fraction':float(quiet.mean()), 'pauses_at_least_200ms':pauses,
        'f0_hz_p10_p50_p90':list(np.percentile(pitches,[10,50,90])) if pitches else None,
        'caveat':'Energy-based silence and autocorrelation pitch estimates; not perceptual tone or emotion judgments.'}


def main():
    out = ROOT/'data/feedback-title-voice-20261016'
    out.mkdir(exist_ok=True)
    db_path = ROOT.parent/'VoiceBench/data/voicebench.sqlite3'
    records = []
    with closing(sqlite3.connect(db_path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory = sqlite3.Row
        for request in (168,230,231):
            rows = db.execute('SELECT q.*,p.reference_sha256,r.manifest_json,r.metrics_json FROM studio_requests q '
                'JOIN projects p ON p.id=q.project_id JOIN studio_segments s ON s.request_id=q.id '
                'JOIN runs r ON r.job_id=s.job_id WHERE q.id=?', (request,)).fetchall()
            if not rows: continue
            first = dict(rows[0]); runs = []
            for row in rows:
                manifest = json.loads(row['manifest_json']); metrics = json.loads(row['metrics_json'])
                engine = manifest['engine']
                runs.append({'engine':{key:engine.get(key) for key in ('slug','version')},
                    'requested_seed':row['seed'],'selected_seed':manifest.get('selected_seed'),
                    'quality_mode':row['quality_mode'],'reference_sha256':row['reference_sha256'],
                    'synthesis':metrics.get('synthesis'), 'reference_hash_from_manifest':manifest.get('reference_sha256')})
            path = Path(first['output_path'])
            records.append({'request_id':request,'text':first['original_text'],'audio_path':str(path),
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'actual_runs':runs,
                'measurements':measurements(path,first['original_text'])})
        active = db.execute("SELECT count(*) FROM studio_requests WHERE status IN ('queued','running')").fetchone()[0]
    baseline = records[0]['actual_runs']
    for record in records: record['same_effective_configuration_as_168'] = record['actual_runs'] == baseline
    report = {'prior_comparison_baseline_request':168,'owner_confirmation_this_turn':False,
        'actual_requests_inspected':records,'active_voice_requests':active,'new_synthesis_requests':0,
        'auditory_review_performed':False,'reference_selection_changed':False,'global_settings_changed':False}
    (out/'voice-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps([{'request':r['request_id'],'same_configuration':r['same_effective_configuration_as_168'],
        'measurements':r['measurements']} for r in records],ensure_ascii=False))


if __name__ == '__main__': main()
