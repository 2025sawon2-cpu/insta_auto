"""Attach the actual approved initial cover, preserving the failed preparation."""
import argparse
import copy
import json
from pathlib import Path
import sqlite3
import time
from hotpost.initial_prepared_render import checked_plan, sha
from hotpost.studio_store import StudioStore, Conflict

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/rework-top-three-20261014/rank2-initial-cover-preparation-v2-copy'
TASK='work-8013247e50624ae6'
OP='initial-cover-canvas-and-copy-preparation-20261014'
RECEIPT_SHA='f05b352436abf809bad3e94853104888fd9c283c6f63e5d165f6a374ecc05295'


def evidence():
    path=OUT/'prepared-render-receipt.json'
    if sha(path)!=RECEIPT_SHA:raise Conflict('The actual approved initial preparation changed')
    receipt=json.loads(path.read_text('utf-8'))
    return receipt,{'path':str(path.resolve()),'sha256':RECEIPT_SHA,'material_key':receipt['material_key']}


def prepare(state,receipt,record):
    if any(r.get('operation')==OP for r in state.get('initial_prepare_admissions',[])):return None
    before=copy.deepcopy(state);q=state['daily_quality']
    if (state['id']!=TASK or not state['automation'].get('paused_by_user') or state['automation'].get('active')
            or state['edits'] or len(state['voices'])!=1 or len(state['sources'])!=35
            or q.get('pending')!='scene_wait' or q['status']!='needs_attention' or q['repair_round']!=0
            or len(q.get('preparation_failures',[]))!=1 or not state['source_goal']['ready']):
        raise Conflict('Exact held initial no-render task changed')
    plan=json.loads(Path(receipt['prepared_plan']['path']).read_text('utf-8'))
    q['thumbnail_lines']=copy.deepcopy(plan['cover_spec']['lines'])
    checked_plan(state,receipt)
    state['initial_render_preparation']=copy.deepcopy(record)
    detail={'operation':OP,'accepted_receipt':record,'at':time.time(),
        'previous_quality':{k:copy.deepcopy(before['daily_quality'].get(k)) for k in ('status','pending','thumbnail_lines')},
        'previous_message':before['message'],'preparation_failure_identity':receipt['preparation_failure_identity'],
        'body_selected_result':receipt['selected_result'],'actual_render_count':0,'automatic_resume':False,
        'voice_regenerations':0,'source_downloads':0,'analysis_replays':0,'selector_replays':0}
    state.setdefault('initial_prepare_admissions',[]).append(detail)
    q.setdefault('preparation_diagnostics',[]).append({'operation':OP,
        'original_failure_identity':receipt['preparation_failure_identity'],
        'diagnosis':'Original raw core cover had hook true and unreadable-mask false; mixed context hook failure produced the representative copy reason. '
            'New full canvas has mask/face/product approval and a separately observed hook rejection; new two-line copy passed batch and solo.',
        'raw_failure_preserved':True,'approved_preparation_sha256':RECEIPT_SHA,'at':time.time()})
    q.update(status='pending',pending=None)
    state['message']='새 표지 픽셀·문구 검토 완료 · 동결한 기존 장면과 음성으로 첫 렌더 재개 대기'
    for k in before:
        if k not in {'daily_quality','initial_render_preparation','initial_prepare_admissions','message'} and state[k]!=before[k]:
            raise AssertionError('Unrelated task field changed: '+k)
    for k in before['daily_quality']:
        if k not in {'status','pending','thumbnail_lines','preparation_diagnostics'} and q[k]!=before['daily_quality'][k]:
            raise AssertionError('Historical quality field changed: '+k)
    return detail


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    receipt,record=evidence()
    with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        before=json.loads(db.execute('select state from tasks where id=?',(TASK,)).fetchone()[0])
    candidate=copy.deepcopy(before);detail=prepare(candidate,receipt,record)
    if args.apply and detail:
        dest=OUT/'binding-applied.json'
        if dest.exists():raise Conflict('Preserve the original acceptance receipt')
        store=StudioStore(ROOT/'data/studio')
        def change(state,db):
            if state!=before or db.execute("select 1 from jobs where task_id=? and status in ('queued','running')",(TASK,)).fetchone():
                raise Conflict('Held initial task changed or is busy')
            fresh_receipt,fresh_record=evidence();fresh=copy.deepcopy(state)
            committed=prepare(fresh,fresh_receipt,fresh_record)
            state.clear();state.update(fresh)
            store.event(db,TASK,'initial_cover_preparation_admitted',committed)
        after=store.change(TASK,change,before['revision'])
        dest.write_text(json.dumps({'detail':detail,'revision_before':before['revision'],'revision_after':after['revision']},
            ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'apply':args.apply,'already_bound':detail is None,'automatic_resume':False}))

if __name__=='__main__':main()
