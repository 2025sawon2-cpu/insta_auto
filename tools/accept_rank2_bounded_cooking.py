"""Accept only the complete official four-second review into held rank two."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from hotpost.config import load_settings
from hotpost.source_overlay_review import accepted_interval_frames, _create_proposal
from hotpost.source_mask_review import approve_masks
from hotpost.source_functional import REVIEW_POLICY
from hotpost.source_presentation import valid_review, review_scope
from hotpost.studio_sources import source_goal, sync_ready_source_status
from hotpost.studio_store import StudioStore, Conflict

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/rework-top-three-20261014/rank2-bounded-cooking-v1'
TASK='work-8013247e50624ae6'
SOURCE='source-a56be5436e7f48e1'
OP='rank2-existing-apple-egg-pan-bounded-official-v1'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def prepare(state, proof, proof_sha):
    if any(r.get('operation')==OP for r in state.get('bounded_source_acceptances',[])):return None
    before=copy.deepcopy(state);binding=proof['binding'];source=copy.deepcopy(proof['source'])
    if (state['id']!=TASK or not state['automation'].get('paused_by_user') or state['automation'].get('active')
            or len(state['sources'])!=35 or state['run_id']!='run-a6a8cb83ae52430f'
            or state['edits'] or state['source_goal']['core_seconds']!=0):
        raise Conflict('Exact held rank-two inventory changed')
    index=next(i for i,s in enumerate(state['sources']) if s['id']==SOURCE)
    prior=state['sources'][index]
    allowed={'reviewed_intervals','watermark_masks','mask_review','overlay_review_policy',
        'overlay_classification_before_review','blur_required','source_quality','functional_review',
        'editing_eligible','source_role','relevance_review_required','presentation_review_required',
        'presentation_review','presentation_rejection_reasons','overlay_review_scope','interval_review_history',
        'presentation_review_error','presentation_review_error_policy','presentation_review_error_scope',
        'presentation_review_error_sha256','overlay_review_error'}
    if any(prior.get(k)!=source.get(k) for k in set(prior)|set(source) if k not in allowed):
        raise Conflict('Non-review source identity, origin, rights or preserved metadata changed')
    if canonical(prior)!=binding['source_state_sha256'] or source['id']!=SOURCE or source['sha256']!=prior['sha256']:
        raise Conflict('Exact prior source object changed')
    if (sha(prior['path'])!=binding['source_sha256'] or sha(state['reference_video'])!=binding['reference_sha256']
            or source['reviewed_intervals']!=[{'source_start':22.0,'source_end':26.0}]
            or source['source_role']!='core' or not source['editing_eligible']):
        raise Conflict('Official core source identity or interval is invalid')
    frames=accepted_interval_frames(source)
    if len(frames)!=5:raise Conflict('Exactly five newly accepted native frames are required')
    function=source['functional_review']
    if (function['source_sha256']!=source['sha256'] or function['policy']!=REVIEW_POLICY
            or function['same_core_function'] is not True or not function['observed_actions']
            or not function['matched_reference_features'] or not valid_review(source)
            or source['presentation_review']['usable'] is not True):
        raise Conflict('Fresh official function or portrait review is incomplete')
    if not all(f['path'] in function['evidence_frames'] for f in frames):
        raise Conflict('Function review is not bound to the new accepted native frames')
    history=source.get('interval_review_history') or []
    if not any(h['prior_reviews'].get('reviewed_intervals')==prior['reviewed_intervals']
            and h['prior_reviews'].get('functional_review')==prior['functional_review']
            and h['prior_reviews'].get('presentation_review')==prior['presentation_review'] for h in history):
        raise Conflict('Prior prep, function and portrait facts were not preserved')
    for s in state['sources']:
        if sha(s['path'])!=s['sha256']:raise Conflict('Received media bytes changed')
    for v in state['voices']:
        if sha(v['path'])!=v['sha256']:raise Conflict('Approved voice bytes changed')
    state['sources'][index]=source
    goal=source_goal(state,load_settings().source_min_usable)
    if not goal['ready'] or not goal['core_ready'] or goal['core_seconds']!=4.0 or goal!=proof['goal']:
        raise Conflict('Normal source goal is not satisfied by the exact four-second core scope')
    state['source_goal']=goal
    detail={'operation':OP,'proof_path':str((OUT/'official-result.json').resolve()),'proof_sha256':proof_sha,
        'binding':binding,'previous_source':copy.deepcopy(prior),'previous_source_goal':before['source_goal'],
        'previous_source_search':before.get('source_search'),'at':time.time(),
        'actual_current_core_seconds':4.0,'automatic_resume':False,'source_downloads':0,'query_resets':0}
    state.setdefault('bounded_source_acceptances',[]).append(detail)
    for k in before:
        if k not in {'sources','source_goal','bounded_source_acceptances'} and before[k]!=state[k]:
            raise AssertionError('Unrelated state field changed: '+k)
    if any(a!=b for i,(a,b) in enumerate(zip(before['sources'],state['sources'])) if i!=index):
        raise AssertionError('An unrelated source changed')
    return detail


def validate_result():
    path=OUT/'official-result.json';proof=json.loads(path.read_text('utf-8'));digest=sha(path)
    binding=json.loads((OUT/'input-binding.json').read_text('utf-8'))
    if proof['binding']!=binding or proof['task_mutations']!=0:raise Conflict('Official input binding changed')
    if (binding['task_id']!=TASK or binding['source_id']!=SOURCE or binding['intervals']!=[[22.0,26.0]]):
        raise Conflict('Official physical task/source/window differs from the frozen request')
    pending=ROOT/'data/rework-top-three-20261014/rank2-LyV-bounded-official-pending-input.json'
    if sha(pending)!=binding['request_sha256']:raise Conflict('Explicit request changed')
    for p,value in binding['reference_frames_sha256'].items():
        if sha(p)!=value:raise Conflict('Reference frame changed')
    stages={}
    for name in ['overlay_region_proposal','independent_overlay_review']:
        stage=json.loads((OUT/('model-'+name+'.json')).read_text('utf-8'))
        if stage['state']!='completed' or stage['binding']!=binding or stage['purpose']!=name:
            raise Conflict('Completed official mask stage changed')
        stages[name]=stage['result']
    proposal=json.loads((OUT/'mask/overlay-proposal.json').read_text('utf-8'))
    evidence=json.loads((OUT/'mask/overlay-evidence.json').read_text('utf-8'))
    rebuilt=_create_proposal(load_settings(),lambda *args,**kwargs:stages['overlay_region_proposal'],evidence,[])
    receipt=json.loads((OUT/'mask/overlay-receipt.json').read_text('utf-8'))
    if rebuilt!=proposal or receipt!=stages['independent_overlay_review']:
        raise Conflict('Official mask regions or independent decision changed')
    approved=approve_masks(proposal,receipt)
    for key in ('watermark_masks','reviewed_intervals','mask_review'):
        if approved[key]!=proof['source'][key]:raise Conflict('Accepted source '+key+' differs from the official mask approval')
    for name,key in [('function','functional_review'),('portrait','presentation_review')]:
        result_path=OUT/(name+'.json');gate=json.loads((OUT/(name+'-submission.json')).read_text('utf-8'))
        if (gate.get('state')!='completed' or gate.get('binding')!=binding or gate.get('result_sha256')!=sha(result_path)
                or json.loads(result_path.read_text('utf-8'))!=proof['source'][key]):
            raise Conflict('Completed '+name+' provenance changed')
    return proof,digest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    proof,digest=validate_result()
    with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        before=json.loads(db.execute('select state from tasks where id=?',(TASK,)).fetchone()[0])
    candidate=copy.deepcopy(before);detail=prepare(candidate,proof,digest)
    if args.apply and detail:
        dest=OUT/'acceptance-applied.json'
        if dest.exists():raise Conflict('Preserve the original acceptance receipt')
        store=StudioStore(ROOT/'data/studio')
        def change(state,db):
            if state!=before or db.execute("select 1 from jobs where task_id=? and status in ('queued','running')",(TASK,)).fetchone():
                raise Conflict('Target source task changed or is busy')
            fresh_proof,fresh_sha=validate_result()
            if fresh_sha!=digest:raise Conflict('Official result changed before commit')
            fresh=copy.deepcopy(state);committed=prepare(fresh,fresh_proof,fresh_sha)
            state.clear();state.update(fresh)
            sync_ready_source_status(state,db,load_settings().source_min_usable)
            store.event(db,TASK,'existing_bounded_cooking_source_review_accepted',committed)
        after=store.change(TASK,change,before['revision'])
        dest.write_text(json.dumps({'detail':detail,'revision_before':before['revision'],'revision_after':after['revision'],
            'automatic_resume':False},ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'apply':args.apply,'already_accepted':detail is None,'automatic_resume':False}))

if __name__=='__main__':main()
