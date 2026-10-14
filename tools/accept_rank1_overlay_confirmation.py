"""Append official targeted actual QA; keep prior QA and the rendered asset."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from hotpost.daily_quality import DailyQualityMixin, verified_quality_export
from hotpost.studio_store import Conflict, StudioStore

ROOT=Path(__file__).resolve().parents[1]
TASK='work-1672e441725d4445'
EDIT='job-bebcd905471641e5'
OP='rank1-official-overlay-recheck-20261014-v1'
OFFICIAL_SHA='ed86d21697a6615e0e3f154ff51307c32f430cd2557265a2fa05ba0d168c5d66'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class HeldAcceptance(DailyQualityMixin):
    def advance_workflow(self,state,db):
        if not state['automation'].get('paused_by_user'):raise Conflict('Hold changed during review acceptance.')


def prepare(state,result,proof_sha):
    if any(r.get('operation')==OP for r in state.get('post_render_review_amendments',[])):return None
    before=copy.deepcopy(state);q=state['daily_quality']
    if (not state['automation'].get('paused_by_user') or state['edit_id']!=EDIT
            or state['status']!='completed' or q['status']!='passed' or result['passed']
            or not result.get('evidence_recheck') or result['recheck_evidence']['actual_calls']!=1
            or {i['beat_id'] for i in result['issues']}!={'beat-6','beat-10','beat-19'}
            or any(i['kind']!='watermark' for i in result['issues'])):
        raise Conflict('Exact held output or targeted official findings changed.')
    edit=next(e for e in state['edits'] if e['id']==EDIT)
    if (sha(edit.get('export_path') or edit['preview_path'])!=result['render_sha256']
            or sha(edit['plan_path'])!=result['plan_sha256']):raise Conflict('Actual rendered output changed.')
    for frame in result['recheck_evidence']['frames']:
        if sha(frame['path'])!=frame['sha256']:raise Conflict('Actual QA frame changed.')
    HeldAcceptance().accept_daily_quality(state,{'id':OP,'kind':'quality_review'},copy.deepcopy(result),None)
    if q['status']!='repair' or len(q['reviews'])!=len(before['daily_quality']['reviews'])+1:
        raise AssertionError('Normal actual QA acceptance did not append the failed recheck.')
    if q['progress_policy']['best']!=before['daily_quality']['progress_policy']['best']:
        raise AssertionError('Preserved previous best changed.')
    if q['progress_policy']['reviews'][:-1]!=before['daily_quality']['progress_policy']['reviews']:
        raise AssertionError('Raw ledger reviews changed.')
    last=q['progress_policy']['reviews'][-1]
    if last['conflict'] or last['resolved'] or len(last['introduced'])!=3:
        raise AssertionError('Targeted actual defects were not classified correctly.')
    state.update(status='source_wait',message='완성본 추가 검수에서 원본 삽입 자막 마스크 누출 확인 · 기존 결과 보존·수복 근거 준비')
    detail={'operation':OP,'edit_id':EDIT,'official_confirmation_sha256':proof_sha,
        'render_sha256':result['render_sha256'],'plan_sha256':result['plan_sha256'],
        'actual_calls':1,'previous_status':before['status'],'previous_quality_status':before['daily_quality']['status'],
        'changed_attempt_statuses':[{'key':a['key'],'previous_status':a.get('status'),'previous_review':a.get('review')}
            for a in before['daily_quality']['progress_policy']['attempts']
            if any(b['key']==a['key'] and b!=a for b in q['progress_policy']['attempts'])],
        'previous_review_path':edit['quality_review_path'],'targeted_review_path':result['review_path'],
        'no_new_render':True,'automatic_resume':False,'at':time.time()}
    state.setdefault('post_render_review_amendments',[]).append(detail)
    for key in before:
        if key not in {'daily_quality','status','message','post_render_review_amendments'} and state[key]!=before[key]:
            raise AssertionError('Unrelated task field changed: '+key)
    if verified_quality_export(state,edit):raise AssertionError('The newly failed output remains share-approved.')
    return detail


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    out=ROOT/'data/rework-top-three-20261014';path=out/'rank1-official-overlay-confirmation.json'
    proof_sha=sha(path);proof=json.loads(path.read_text('utf-8'))
    if proof_sha!=OFFICIAL_SHA:raise Conflict('Exact official confirmation bytes changed.')
    if proof['actual_calls']!=1 or proof.get('production_mutation') is not False:raise Conflict('Official confirmation provenance changed.')
    result=copy.deepcopy(proof['result']);result_path=out/'rank1-official-overlay-quality-result.json'
    result['review_path']=str(result_path.resolve())
    with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        before=json.loads(db.execute('SELECT state FROM tasks WHERE id=?',(TASK,)).fetchone()[0])
    candidate=copy.deepcopy(before);detail=prepare(candidate,result,proof_sha)
    if args.apply and detail:
        dest=out/'rank1-overlay-confirmation-applied.json'
        if dest.exists():raise Conflict('Preserve the existing acceptance receipt.')
        data=json.dumps(result,ensure_ascii=False,indent=2)
        if result_path.exists() and result_path.read_text('utf-8')!=data:raise Conflict('Targeted QA receipt changed.')
        store=StudioStore(ROOT/'data/studio')
        def change(state,db):
            if state!=before or db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('running','queued')",(TASK,)).fetchone():
                raise Conflict('Exact task changed or its queue is not idle.')
            if sha(path)!=proof_sha:raise Conflict('Official confirmation changed before commit.')
            if not result_path.exists():result_path.write_text(data,encoding='utf-8')
            fresh=copy.deepcopy(state);committed=prepare(fresh,result,proof_sha)
            state.clear();state.update(fresh);store.event(db,TASK,'targeted_actual_overlay_recheck_accepted',committed)
        after=store.change(TASK,change,before['revision'])
        dest.write_text(json.dumps({'detail':detail,'revision_before':before['revision'],'revision_after':after['revision']},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'apply':args.apply,'already_accepted':detail is None,'actual_render_count':0,'automatic_resume':False},ensure_ascii=False))


if __name__=='__main__':main()
