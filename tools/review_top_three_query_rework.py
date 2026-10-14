"""Prepare the corrected fixed query pool from saved evidence, without resuming tasks."""
import hashlib
import json
import sqlite3
from pathlib import Path

from hotpost.config import load_settings
from hotpost.reference_context import post_caption
from hotpost.source_planning import cached_enrich_plan
from hotpost.source_queries import product_query_plan, tiktok_product_queries
from hotpost.source_search.planner import grounded_actions

ROOT = Path(__file__).resolve().parents[1]
IDS = ('work-1672e441725d4445','work-8013247e50624ae6','work-8b16890d03794af1')


def main():
    settings = load_settings()
    output = ROOT / 'data/rework-top-three-20261014'
    for task_id in IDS:
        target = output / (task_id + '-corrected-query-plan.json')
        with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
            state = json.loads(db.execute('select state from tasks where id=?',(task_id,)).fetchone()[0])
        old = json.loads(Path(state['source_search_manifest_path']).read_text('utf-8'))
        evidence = old['product_evidence']['query_evidence']
        caption = post_caption(settings,state)
        reference_sha = hashlib.sha256(Path(state['reference_video']).read_bytes()).hexdigest()
        transcript = {'speech':evidence['speech'],'screen_text':evidence['screen_text']}
        base = product_query_plan(caption,old.get('visual_product_queries',[]),[],transcript,[])
        print('Planning '+task_id,flush=True)
        plan = cached_enrich_plan(settings,base,caption,transcript,reference_sha256=reference_sha)
        result = {'task_id':task_id,'reference_sha256':reference_sha,'evidence_manifest':state['source_search_manifest_path'],
                  'evidence_manifest_sha256':hashlib.sha256(Path(state['source_search_manifest_path']).read_bytes()).hexdigest(),
                  'plan':plan,'tiktok_queries':tiktok_product_queries(plan),
                  'grounded_actions':grounded_actions(plan,plan['query_evidence'])}
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'task_id':task_id,'primary_subject':plan.get('primary_subject'),
                          'products':plan['products'],'tiktok_queries':result['tiktok_queries'],
                          'queries': [r['query'] for r in plan['query_details']],
                          'planning_notes':plan.get('planning_notes')},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
