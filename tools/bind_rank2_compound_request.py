"""Bind reviewed new query evidence to the same unstarted paused rank-two job."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from hotpost.source_queries import feedback_queries
from hotpost.source_search.strategy import fresh_queries
from hotpost.studio_store import Conflict, StudioStore

ROOT = Path(__file__).resolve().parents[1]
TASK = 'work-8013247e50624ae6'
JOB = 'job-971786ebe61546f6'
OP = 'rank2-observed-core-gap-compound-request-20261014-v1'
PROOFS = {
    'rank2-compound-action-query-proposal.json':'1528a4277121856160432cc279c22738d43a1f2d8761ae19425c51f24fd0a255',
    'rank2-compound-action-independent.json':'331bcab5b36b0bf39801f40775e3119938cd15650c0ebefebb2ca5969f180c4a',
    'rank2-compound-tiktok-boundary-independent.json':'13f2a62fca1ab9615b206c4f3b3a5269374edbdd2289d98bcf6c7a2c757bec7d',
    'watch-connected-rank2-23-accepted.json':'82636f67aaf1f03546afa42df68bd0cb7f9deadd4c1f5686179548500c7fcea0'}


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(state, job, proofs):
    if any(r.get('operation') == OP for r in state.get('source_request_bindings', [])): return None
    before = copy.deepcopy(state); previous_payload = copy.deepcopy(job['payload'])
    if (state['id'] != TASK or not state['automation'].get('paused_by_user')
            or state['run_id'] != 'run-a6a8cb83ae52430f' or len(state['sources']) != 23
            or state['edits'] or state['source_goal']['core_ready'] or state['source_goal']['core_seconds'] != 0
            or job['id'] != JOB or job['status'] != 'paused' or job['payload']['round'] != 9
            or job['payload']['run_id'] != state['run_id'] or job['payload'].get('request')
            or set(job['checkpoint']) != {'not_before'}):
        raise Conflict('Exact paused unstarted rank-two job or observed core gap changed.')
    proposal = proofs['rank2-compound-action-query-proposal.json']
    independent = proofs['rank2-compound-action-independent.json']
    boundary = proofs['rank2-compound-tiktok-boundary-independent.json']
    if not all(independent[k] for k in ('original_text_sha_matches','exact_quotes_present','reference_sha_matches','pan_frame_sha_matches','history_equal_proposal')):
        raise Conflict('Independent reference proof is not verified.')
    if not boundary['original_plan_unchanged'] or not boundary['only_original_nouns']:
        raise Conflict('TikTok boundary was not independently verified.')
    original = state.get('reviewed_original_text') or state['original_text']
    if (hashlib.sha256(original.encode()).hexdigest() != proposal['original_text_sha256']
            or not all(q in original for q in proposal['exact_original_quotes'])
            or sha(state['reference_video']) != proposal['reference_video_sha256']
            or sha(proposal['pan_grounding']['reviewed_frame']) != proposal['pan_grounding']['frame_sha256']):
        raise Conflict('Literal or visible input proof changed.')
    for source in state['sources']:
        if sha(source['path']) != source['sha256']: raise Conflict('Received source bytes changed.')
    for voice in state['voices']:
        if sha(voice['path']) != voice['sha256']: raise Conflict('Saved voice changed.')
    queries = [r['query'] for r in proposal['proposed_queries']]
    history = state['source_acquisition']['queries']
    if history != proposal['preserved_scope_history_at_plan'] or fresh_queries(queries,'youtube',history) != queries:
        raise Conflict('Actual consumed/pending query history changed.')
    request = '\n'.join([*queries,'사과','apple','苹果'])
    if request != boundary['request'] or feedback_queries(request) != [*queries,'사과','apple','苹果']:
        raise Conflict('Exact independently reviewed request changed.')
    job['payload']['request'] = request
    state['source_search_brief'] = request
    detail = {'operation':OP,'job_id':JOB,'request':request,'proof_sha256':PROOFS,
        'previous_brief':before.get('source_search_brief'),'previous_payload':previous_payload,
        'previous_checkpoint':copy.deepcopy(job['checkpoint']),
        'actual_core_gap':{'core_seconds':0,'source_count':23},'at':time.time(),
        'consumed_history_reset':False,'automatic_resume':False}
    state.setdefault('source_request_bindings', []).append(detail)
    for key in before:
        if key not in {'source_search_brief','source_request_bindings'} and state[key] != before[key]:
            raise AssertionError('Unrelated task state changed: '+key)
    return detail


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    out=ROOT/'data/rework-top-three-20261014';proofs={}
    for name,expected in PROOFS.items():
        path=out/name
        if sha(path)!=expected:raise Conflict('Independent query evidence changed: '+name)
        proofs[name]=json.loads(path.read_text('utf-8'))
    with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        before=json.loads(db.execute('SELECT state FROM tasks WHERE id=?',(TASK,)).fetchone()[0])
        row=db.execute('SELECT payload,checkpoint,status FROM jobs WHERE id=? AND task_id=?',(JOB,TASK)).fetchone()
    if not row:raise Conflict('Target queue item missing.')
    job={'id':JOB,'payload':json.loads(row[0]),'checkpoint':json.loads(row[1]),'status':row[2]}
    candidate=copy.deepcopy(before);detail=prepare(candidate,job,proofs)
    if args.apply and detail:
        dest=out/'rank2-compound-binding-applied.json'
        if dest.exists():raise Conflict('Preserve the original operation report.')
        store=StudioStore(ROOT/'data/studio')
        def change(state,db):
            if state!=before or db.execute("SELECT 1 FROM jobs WHERE status IN ('running','queued')").fetchone():
                raise Conflict('State changed or queue is not idle.')
            if tuple(db.execute('SELECT payload,checkpoint,status FROM jobs WHERE id=?',(JOB,)).fetchone())!=row:
                raise Conflict('Unstarted queue item changed.')
            for name,expected in PROOFS.items():
                if sha(out/name)!=expected:raise Conflict('Evidence changed before commit.')
            fresh=copy.deepcopy(state);bound_job={'id':JOB,'payload':json.loads(row[0]),'checkpoint':json.loads(row[1]),'status':row[2]}
            committed=prepare(fresh,bound_job,proofs)
            state.clear();state.update(fresh)
            db.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps(bound_job['payload'],ensure_ascii=False),JOB))
            store.event(db,TASK,'reviewed_compound_request_bound_to_unstarted_job',committed)
        after=store.change(TASK,change,before['revision'])
        dest.write_text(json.dumps({'detail':detail,'revision_before':before['revision'],'revision_after':after['revision']},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'apply':args.apply,'already_bound':detail is None,'job_id':JOB,'actual_queries_sent':0,'automatic_resume':False},ensure_ascii=False))


if __name__=='__main__':main()
