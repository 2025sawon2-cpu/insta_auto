"""Verify new WAVs and immutable source records, without claiming tone approval."""
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.audit_feedback_voice_20261016 import measurements


def main():
    root=ROOT/'data/approved-mirror-tone-20261016'
    baseline=json.loads((root/'approved-baseline.json').read_text('utf-8'))
    old=json.loads((ROOT/'data/feedback-title-voice-20261016/voice-audit.json').read_text('utf-8'))
    preserved=[];voices=[]
    for record in old['actual_requests_inspected']:
        actual=hashlib.sha256(Path(record['audio_path']).read_bytes()).hexdigest()
        assert actual==record['sha256']
        preserved.append({'request_id':record['request_id'],'sha256':actual,'unchanged':True})
    with closing(sqlite3.connect((ROOT.parent/'VoiceBench/data/voicebench.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)) as db:
        baseline_manifest=json.loads(db.execute('SELECT r.manifest_json FROM studio_segments s JOIN runs r ON r.job_id=s.job_id '
            'WHERE s.request_id=168').fetchone()[0])
        folders=['Dec5bcqyffk','Dec8wlLhu9N']
        if (root/'Dec8wlLhu9N-v2/voice.json').is_file(): folders.append('Dec8wlLhu9N-v2')
        for code in folders:
            record=json.loads((root/code/'voice.json').read_text('utf-8'))
            request=record['voicebench_request_id']
            rows=db.execute('SELECT r.manifest_json,r.metrics_json,q.original_text,q.status FROM studio_segments s '
                'JOIN runs r ON r.job_id=s.job_id JOIN studio_requests q ON q.id=s.request_id WHERE s.request_id=?',(request,)).fetchall()
            assert len(rows)==1
            manifest,metrics,text,status=rows[0]
            manifest=json.loads(manifest);metrics=json.loads(metrics)
            assert status=='succeeded' and text==record['script']
            assert manifest['original_text']==record['script']
            assert manifest['reference_sha256']==baseline_manifest['reference_sha256']
            assert manifest['engine']==baseline_manifest['engine']
            assert manifest['synthesis']==baseline_manifest['synthesis']
            assert manifest['selected_seed']==13
            quality=metrics['quality_control']
            assert quality['status']=='passed' and quality['attempt_count']==1
            path=Path(record['output_path'])
            assert hashlib.sha256(path.read_bytes()).hexdigest()==record['audio_sha256']
            voices.append({'shortcode':code,'request_id':request,'audio_path':str(path),
                'audio_sha256':record['audio_sha256'],'script':record['script'],
                'single_actual_synthesis':True,'same_approved_settings':True,'selected_seed':13,
                'quality_control':{k:quality.get(k) for k in ('status','attempt_count','fallback_selected')},
                'measurements':measurements(path,record['script']),'auditory_tone_approved':False})
        active=db.execute("SELECT count(*) FROM studio_requests WHERE status IN ('queued','running')").fetchone()[0]
    receipt={'baseline':baseline,'new_voices':voices,'preserved_old_audio':preserved,
        'active_voice_requests':active,'reference_or_global_settings_changed':False,
        'technical_verification_passed':True,'auditory_match_to_baseline_verified':False,
        'scope':'Preserved narration revisions; existing operational scripts, voices and completed videos were not replaced.'}
    target='verification-final.json' if len(folders)>2 else 'verification.json'
    (root/target).write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'voices':voices,'old_audio_unchanged':True,'active_requests':active},ensure_ascii=False))


if __name__=='__main__':main()
