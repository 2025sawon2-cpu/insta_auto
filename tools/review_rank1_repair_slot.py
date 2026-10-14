"""One official review of a wider existing window; no production state write."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3

from hotpost.config import load_settings
from hotpost.scene_requirements import assess, coverage_current, input_signature
from hotpost.script_rewriter import _generate

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/rework-top-three-20261014'
TASK='work-1672e441725d4445'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    destination=OUT/'rank1-official-slot-review.json'
    if destination.exists():raise ValueError('Existing official review must be preserved.')
    settings=load_settings()
    proof_path=OUT/'rank1-repair-slot-review-input.json'
    proof=json.loads(proof_path.read_text('utf-8'))
    with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        original=json.loads(db.execute('SELECT state FROM tasks WHERE id=?',(TASK,)).fetchone()[0])
    if not original.get('automation',{}).get('paused_by_user'):raise ValueError('Rank one must remain paused.')
    assert digest(proof['path'])==proof['source_sha256']==proof['actual_sha256']
    assert digest(proof['selected_edit_plan_path'])==proof['selected_edit_plan_sha256']
    for frame in proof['available_approved_frames']:assert digest(frame['path'])==frame['sha256']
    state=copy.deepcopy(original)
    quality=state['daily_quality']
    # Effective actual reviews in this local snapshot; originals remain intact.
    actual=[r for r in quality['reviews'] if not r.get('pre_render_scene_gap')]
    baseline=next(r for r in reversed(actual) if r['edit_id']==state['edit_id'])
    quality['feedback']=copy.deepcopy(baseline['issues'])
    quality['reviews']=actual
    previous=quality.pop('scene_requirements',None)
    calls=[];skipped=[]
    def official(s,instruction,data,*,media=None,**kwargs):
        if not any(r['id']==proof['source_id'] for r in data['sources']):
            skipped.append([r['id'] for r in data['sources']])
            return {'requirements':[]}
        if calls:raise ValueError('A second actual review is prohibited; preserve the first result.')
        narrowed=copy.deepcopy(data)
        narrowed['sources']=[r for r in data['sources'] if r['id']==proof['source_id']]
        narrowed['actual_slot_review']=proof
        narrowed['actual_slot_review_input_sha256']=digest(proof_path)
        selected=[]
        for offset in range(0,len(media or []),2):
            pair=media[offset:offset+2]
            label=pair[0].get('text','')
            if label.startswith('PREVIOUS FAILED CUT:') or json.loads(label).get('source_id')==proof['source_id']:
                selected.extend(pair)
        payload_sha=hashlib.sha256(json.dumps(narrowed,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        calls.append({'payload_sha256':payload_sha,'source_id':proof['source_id'],'image_count':len(selected)//2})
        return _generate(s,instruction+'\n'+proof['instruction']+
            '\nReview only the supplied target source window 0~4 for this new match. '
            'Do not reuse its previous failed folding window. Return uncertain if the actual '
            'slot length and complete native supporting-frame exposure cannot both fit.',
            narrowed,media=selected,**kwargs)
    receipt=assess(settings,state,generate=official)
    state['daily_quality']['scene_requirements']=receipt
    result={'task_id':TASK,'production_mutation':False,'slot_review_input_sha256':digest(proof_path),
            'original_revision':original['revision'],'actual_calls':calls,'unassessed_batches':skipped,
            'previous_coverage':previous,'effective_feedback':quality['feedback'],
            'receipt':receipt,'coverage_current':coverage_current(state),'input_signature':input_signature(state)}
    if destination.exists():raise ValueError('Existing official review must be preserved.')
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ready':receipt['ready'],'coverage_current':result['coverage_current'],
                      'actual_calls':len(calls),'requirements':len(receipt['requirements'])}))


if __name__=='__main__':main()
