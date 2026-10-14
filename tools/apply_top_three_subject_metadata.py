"""Correct only the three stopped subjects, retaining every production artifact."""
import argparse
import copy
import hashlib
import json
import sqlite3
import time
from pathlib import Path

from hotpost.source_planning import QUERY_PLAN_POLICY, primary_subject
from hotpost.studio_store import StudioStore, Conflict

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/rework-top-three-20261014'
IDS = ('work-1672e441725d4445','work-8013247e50624ae6','work-8b16890d03794af1')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    changes = []
    with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
        if db.execute("select 1 from jobs where status in ('queued','running')").fetchone():
            raise Conflict('Global queue must be idle before metadata repair')
        states = {task_id:json.loads(db.execute('select state from tasks where id=?',(task_id,)).fetchone()[0]) for task_id in IDS}
        for raw, in db.execute('select state from tasks'):
            auto=json.loads(raw).get('automation',{})
            if auto.get('selection_mode')=='automatic' and auto.get('protocol')!=2:
                raise Conflict('Store initialization would migrate another task')
    for task_id, before in states.items():
        plan_path=OUT/(task_id+'-corrected-query-plan.json')
        saved=json.loads(plan_path.read_text('utf-8'))
        old_manifest=json.loads(Path(saved['evidence_manifest']).read_text('utf-8'))
        if (saved['task_id']!=task_id or saved['evidence_manifest']!=before['source_search_manifest_path']
                or sha(saved['evidence_manifest'])!=saved['evidence_manifest_sha256']
                or sha(before['reference_video'])!=saved['reference_sha256']
                or saved['plan'].get('query_policy')!=QUERY_PLAN_POLICY):
            raise Conflict('Changed preparation evidence')
        if saved['plan']['query_evidence']!=old_manifest['product_evidence']['query_evidence']:
            raise Conflict('Corrected subject is not bound to the accepted source evidence')
        subject=primary_subject(saved['plan'].get('primary_subject'), saved['plan']['query_evidence'])
        if not subject or not before.get('automation',{}).get('paused_by_user'):
            raise Conflict('Repair requires a verified subject and the stopped target')
        detail={'before':before.get('product'),'after':subject['name'],**subject,
                'plan_sha256':sha(plan_path),'evidence_manifest_sha256':sha(saved['evidence_manifest']),
                'reference_sha256':saved['reference_sha256'],'policy':QUERY_PLAN_POLICY,'at':time.time()}
        if args.apply and before.get('product')!=subject['name']:
            store=StudioStore(ROOT/'data/studio')
            def repair(state,db):
                if db.execute("select 1 from jobs where status in ('queued','running')").fetchone():
                    raise Conflict('Queue became active')
                expected=copy.deepcopy(before)
                if state!=expected:raise Conflict('Target changed')
                state['product']=subject['name']
                state.setdefault('subject_metadata_repairs',[]).append(detail)
                store.event(db,task_id,'subject_metadata_grounded_repair',detail)
            after=store.change(task_id,repair,before['revision'])
            retained=copy.deepcopy(after)
            for field in ('product','subject_metadata_repairs','revision','updated'):retained.pop(field,None)
            original=copy.deepcopy(before)
            for field in ('product','subject_metadata_repairs','revision','updated'):original.pop(field,None)
            if retained!=original:raise AssertionError('Production state changed during metadata-only repair')
        changes.append({'task_id':task_id,**detail})
    receipt={'applied':args.apply,'changes':changes,'retained':'scripts, voices, sources, reference, runs, quality, acquisition, jobs'}
    if args.apply:(OUT/'subject-metadata-repair.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
