"""Compare actual synthesis runs with the previously approved personal voice."""
import json,sqlite3
from pathlib import Path
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.source_quality import sha256_file
from hotpost.editing_adapter import _atomic_json

s=Studio(load_settings(),workers=False)
db=sqlite3.connect('file:../VoiceBench/data/voicebench.sqlite3?mode=ro',uri=True);db.row_factory=sqlite3.Row
query=('SELECT q.id request_id,q.original_text,q.seed,q.quality_mode,q.generation_json,q.output_sha256,'
    'p.reference_sha256,r.manifest_json,r.metrics_json FROM studio_requests q JOIN projects p ON p.id=q.project_id '
    'JOIN studio_segments s ON s.request_id=q.id JOIN runs r ON r.job_id=s.job_id WHERE q.id=?')
def rows(request):
    values=[]
    for r in db.execute(query,(request,)).fetchall():
        v=dict(r);m=json.loads(v.pop('manifest_json'));metrics=json.loads(v.pop('metrics_json'))
        v.update(engine=m.get('engine'),synthesis=metrics.get('synthesis'),
            selected_seed=m.get('selected_seed'),engine_input_text=m.get('original_text'));values.append(v)
    return values
preferred=rows(168);assert len(preferred)==1;preferred=preferred[0]
result=[]
for t in sorted([t for t in s.store.list() if t.get('automation',{}).get('selection_date_kst')=='2026-10-12'],key=lambda t:t['automation']['rank']):
    voice=next((v for v in t['voices'] if v['id']==t.get('voice_id')),None)
    pending=voice is None
    if pending:voice=t['voices'][-1]  # Audit saved synthesis, explicitly not a selected new voice.
    script=next(v for v in t['scripts'] if v['id']==t['script_id'])
    actual=rows(voice['request_id'])
    matches=bool(actual) and all(all(v[k]==preferred[k] for k in ('seed','selected_seed','reference_sha256','engine','generation_json','quality_mode'))
        and v.get('synthesis',{}).get('generation')==preferred.get('synthesis',{}).get('generation') for v in actual)
    whole=(len(actual)==1 and actual[0].get('engine_input_text')==voice.get('spoken_text'))
    synthesis_text_matches=bool(actual) and all(v['original_text']==voice.get('spoken_text') for v in actual)
    unchanged=sha256_file(Path(voice['path']))==voice['sha256']
    entry={'rank':t['automation']['rank'],'shortcode':t['shortcode'],'voice_id':voice['id'],'request_id':voice['request_id'],
        'actual_runs':len(actual),'same_approved_configuration':matches,'single_actual_synthesis':whole,
        'synthesis_text_matches':synthesis_text_matches,'voice_file_unchanged':unchanged,
        'current_script_matches_voice':not pending and script['text']==voice.get('spoken_text'),
        'voice_selection_pending':pending,
        'seed':actual[0]['seed'] if actual else None,'reference_sha256':actual[0]['reference_sha256'] if actual else None,
        'actual_selected_seed':actual[0].get('selected_seed') if actual else None,
        'synthesis':actual[0].get('synthesis') if actual else None,'auditory_naturalness_reviewed':False}
    result.append(entry)
    print(entry['rank'],entry['shortcode'],'config',matches,'whole',whole,'synthesis_text',synthesis_text_matches,'file',unchanged,'current_script',entry['current_script_matches_voice'])
_atomic_json(Path('data/source-recovery-20261012-v1/effective-voice-audit.json'),{'preferred_request_id':168,'voices':result,'final_completion_claim':False})
