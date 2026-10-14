"""Attach exact, independently checked mask pixels to held rank one."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from hotpost.mask_application_evidence import approved_material, input_binding_sha256, render_evidence
from hotpost import quality_progress as progress
from hotpost.studio_store import Conflict, StudioStore

ROOT=Path(__file__).resolve().parents[1]
TASK='work-1672e441725d4445'
EDIT='job-bebcd905471641e5'
OP='rank1-native-frame-clock-mask-pixels-v2-20261014'
TYPED_SHA='f0b5b38d9092bf9cafc4b2b9e3386fe805d31453fbcb9b5a87d3379949157a4c'
OFFICIAL_SHA='dc91b1551a481e113ef335ac94d6ab83bf5f1eccf19b164b67251f9f083d8d87'
BINDING='4132b26618fa97e974e496e719fb9b2d2a4d51020a6f111e624d5977d50a2d50'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evidence():
    out=ROOT/'data/rework-top-three-20261014/mask-boundary-v2'
    typed=out/'typed-pending-receipt.json';official=out/'official-first-frame-review.json'
    if sha(typed)!=TYPED_SHA or sha(official)!=OFFICIAL_SHA:raise Conflict('Exact native/pixel confirmation changed.')
    receipt=json.loads(typed.read_text('utf-8'))
    if input_binding_sha256(receipt)!=BINDING:raise Conflict('Native/frame-clock binding changed.')
    receipt['official_review']={'path':str(official.resolve()),'sha256':OFFICIAL_SHA,'typed_receipt_path':str(typed.resolve())}
    return receipt


def prepare(state,receipt):
    if any(r.get('operation')==OP for r in state.get('mask_repair_bindings',[])):return None
    before=copy.deepcopy(state);q=state['daily_quality']
    if (state['id']!=TASK or state['edit_id']!=EDIT or not state['automation'].get('paused_by_user')
            or q['status']!='repair' or q.get('pending')!='recollect' or len(state['edits'])!=2
            or len(state['sources'])!=18 or len(state['voices'])!=1
            or {i['beat_id'] for i in q['feedback']}!={'beat-6','beat-10','beat-19'}
            or any(i['kind']!='watermark' for i in q['feedback'])):
        raise Conflict('Exact held rank-one watermark repair changed.')
    q['mask_application_repair_evidence']=copy.deepcopy(receipt)
    material=approved_material(state)
    if len(material)!=3:raise Conflict('Actual officially confirmed mask material is invalid.')
    method=progress.hypothesis(state,'reedit')
    if not method['grounded'] or len(method['facts'])!=3 or any(f.get('method')!='approved_mask_application_pixels' for f in method['facts']):
        raise Conflict('New method is not bound exclusively to the three actual watermark defects.')
    probe=copy.deepcopy(state);probe['automation']['paused_by_user']=False;probe['daily_quality']['pending']='reedit'
    if not progress.permit(probe,'reedit'):raise Conflict('Same failed method or other quality hold persists.')
    frozen=progress.load_plan(probe);frozen['quality_mask_application']=render_evidence(probe)
    if progress.guard_render(probe,frozen,'mask-pixel-binding-preflight') is not None:
        raise Conflict('Frozen render/native input or repeated output guard failed.')
    q.setdefault('stop_history',[]).append({'pending':q.get('pending'),'status':q['status'],
        'repair_round':q.get('repair_round',0),'reason':'New native-bound mask application pixels confirmed','at':time.time()})
    q.update(pending='reedit',status='repair')
    detail={'operation':OP,'edit_id':EDIT,'input_binding_sha256':BINDING,'official_sha256':OFFICIAL_SHA,
        'method_key':method['key'],'material':material,'previous_pending':before['daily_quality'].get('pending'),
        'actual_render_count':0,'automatic_resume':False,'at':time.time()}
    state.setdefault('mask_repair_bindings',[]).append(detail)
    for key in before:
        if key not in {'daily_quality','mask_repair_bindings'} and state[key]!=before[key]:raise AssertionError('Unrelated task field changed: '+key)
    oldq=before['daily_quality']
    for key in oldq:
        if key not in {'pending','status','stop_history','mask_application_repair_evidence'} and q[key]!=oldq[key]:
            raise AssertionError('Historical quality field changed: '+key)
    return detail


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    receipt=evidence()
    with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        before=json.loads(db.execute('SELECT state FROM tasks WHERE id=?',(TASK,)).fetchone()[0])
    candidate=copy.deepcopy(before);detail=prepare(candidate,receipt)
    if args.apply and detail:
        destination=ROOT/'data/rework-top-three-20261014/mask-boundary-v2/binding-applied.json'
        if destination.exists():raise Conflict('Preserve existing mask operation report.')
        store=StudioStore(ROOT/'data/studio')
        def change(state,db):
            if state!=before or db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('running','queued')",(TASK,)).fetchone():
                raise Conflict('Exact task changed or target is busy.')
            fresh=copy.deepcopy(state);committed=prepare(fresh,evidence())
            state.clear();state.update(fresh);store.event(db,TASK,'native_clock_mask_pixel_evidence_bound',committed)
        after=store.change(TASK,change,before['revision'])
        destination.write_text(json.dumps({'detail':detail,'revision_before':before['revision'],'revision_after':after['revision']},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'apply':args.apply,'already_bound':detail is None,'method_key':detail['method_key'] if detail else None,'automatic_resume':False}))


if __name__=='__main__':main()
