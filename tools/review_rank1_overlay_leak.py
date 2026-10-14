"""One official targeted actual-render review; preserve the initial passed QA."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from hotpost.config import load_settings
from hotpost.daily_quality import REVIEW_INSTRUCTION, validate_report
from hotpost.script_rewriter import _generate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'data/rework-top-three-20261014'
TASK = 'work-1672e441725d4445'
EDIT = 'job-bebcd905471641e5'
RENDER_SHA = '857cde4309908b03fd8460a5bdb4dc173f5c7bc5c31b3c2f4205ed6d58e36972'
PLAN_SHA = '2672824be64bbfe6b411d1259e2849a3470773bb35f10ec6f1634c7ff23072bb'


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    dest = OUT/'rank1-official-overlay-confirmation.json'
    if dest.exists(): raise ValueError('Preserve the existing official confirmation.')
    with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        state = json.loads(db.execute('SELECT state FROM tasks WHERE id=?',(TASK,)).fetchone()[0])
    if not state['automation'].get('paused_by_user') or state['edit_id'] != EDIT:
        raise ValueError('Exact completed rank-one output must remain held.')
    edit = next(e for e in state['edits'] if e['id'] == EDIT)
    video = edit.get('export_path') or edit['preview_path']
    if sha(video) != RENDER_SHA or sha(edit['plan_path']) != PLAN_SHA: raise ValueError('Actual output changed.')
    original = json.loads(Path(edit['quality_review_path']).read_text('utf-8'))
    plan = json.loads(Path(edit['plan_path']).read_text('utf-8'))
    ids = {'beat-6','beat-10','beat-19'}
    frames = [f for g in original['groups'] for f in g['frames'] if f.get('beat_id') in ids]
    unique = {f['path']:f for f in frames}; frames = list(unique.values())
    if len(frames) != 9: raise ValueError('Nine exact actual QA frames are required.')
    media = []
    for frame in frames:
        if sha(frame['path']) != frame['sha256']: raise ValueError('Original QA frame changed.')
        media.extend([{'text':json.dumps({'actual_render_frame':frame},ensure_ascii=False)},
            {'inlineData':{'mimeType':'image/jpeg','data':base64.b64encode(Path(frame['path']).read_bytes()).decode()}}])
    evidence = {'purpose':'quality_disagreement_dense_confirmation', 'task_id':TASK,
        'actual_render_sha256':RENDER_SHA,'actual_plan_sha256':PLAN_SHA,
        'script':plan['script_text'],'original_text':state.get('reviewed_original_text') or state['original_text'],
        'previous_actual_review':{'passed':original['passed'],'issues':original['issues'],
            'review_path':edit['quality_review_path'],'sha256':sha(edit['quality_review_path'])},
        'beats':[b for b in plan['beats'] if b['id'] in ids],
        'independent_observations':[
            {'beat_id':'beat-6','inserted_source_text':'핫도그NO~밥도그!!','location':'lower pink strip'},
            {'beat_id':'beat-10','inserted_source_text':'Hot dog.','location':'left white source caption'},
            {'beat_id':'beat-19','inserted_source_text':'two Chinese lines','location':'lower source caption'}],
        'contract':'All inserted source text, subtitles and creator watermarks must be hidden by approved masks. '
            'The new Korean narration captions are our own. Physical object labels are not automatically overlays. '
            'Confirm only readable actual source overlays outside masks in these supplied rendered frames; '
            'do not change recipe/product claims or infer motion between stills.'}
    input_sha = hashlib.sha256(json.dumps(evidence,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    value = _generate(load_settings(), REVIEW_INSTRUCTION+'\n'+evidence['contract']+
        '\nResolve this specific initial-passed-QA disagreement using these exact actual rendered frames. '
        'If visible, classify as watermark and give exact supplied beat IDs and locations. '
        'Report only these three targeted beats, with no new collection requirement or invented source approval.',
        evidence,media=media)
    confirmation = validate_report(value,ids)
    if sha(video) != RENDER_SHA or sha(edit['plan_path']) != PLAN_SHA: raise ValueError('Output changed during review.')
    result = copy.deepcopy(original)
    result.update(passed=confirmation['passed'],issues=confirmation['issues'],checked_at=time.time(),
        evidence_recheck=True,recheck_key=input_sha,review_path=str(dest.resolve()))
    result['recheck_evidence']={'frames':frames,'render_sha256':RENDER_SHA,
        'receipt_path':str(dest.resolve()),'input_sha256':input_sha,'actual_calls':1,
        'previous_review_path':edit['quality_review_path'],'previous_review_sha256':sha(edit['quality_review_path'])}
    result['groups'].append({'review':confirmation,'frames':frames,'scope':'targeted_source_overlay_confirmation'})
    dest.write_text(json.dumps({'task_id':TASK,'production_mutation':False,'actual_calls':1,
        'input_sha256':input_sha,'confirmation':confirmation,'result':result},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':confirmation['passed'],'issues':confirmation['issues'],'actual_calls':1},ensure_ascii=False))


if __name__ == '__main__': main()
