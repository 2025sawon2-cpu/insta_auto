"""Initial render admission from frozen selections and newly reviewed cover pixels."""
import copy
import hashlib
import json
import math
import unicodedata
from pathlib import Path
from PIL import Image
from .scene_requirements import input_signature, validate_selected_scenes
from .source_quality import editing_ready, sha256_file
from .studio_store import Conflict

POLICY='initial-frozen-native-cover-render-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def sha(path):return sha256_file(Path(path))


def canonical_lines(lines):
    return [unicodedata.normalize('NFC',''.join(line.split())) for line in lines]


def without_cover(plan):
    return {k:v for k,v in plan.items() if k not in {'cover_spec','cover_review_policy'}}


def checked_cover(plan, candidate, *, require_approval=True, require_mask_change=True):
    binding=candidate.get('cover_pixel_binding') or {}
    if (binding.get('policy')!='reviewed-native-cover-canvas-v1'
            or binding.get('binding_sha256')!=digest({k:v for k,v in binding.items() if k!='binding_sha256'})
            or candidate.get('crop')):
        raise Conflict('Initial cover needs an exact approved full canvas')
    source=next((s for s in plan['sources'] if s['id']==candidate['source_id']),None)
    shot=next((s for s in plan['shots'] if s['id']==candidate['shot_id']),None)
    if (not source or not shot or shot['source_id']!=source['id'] or sha(source['path'])!=source['sha256']
            or shot['sha256']!=source['sha256'] or Path(shot['path']).resolve()!=Path(source['path']).resolve()
            or candidate['source_sha256']!=source['sha256']):
        raise Conflict('Initial cover source identity changed')
    for k,v in {'source_id':source['id'],'source_sha256':source['sha256'],
            'shot_id':shot['id'],'timestamp':float(candidate['timestamp']),
            'geometry':{'width':1080,'height':1920,'fit':'static-center-fill'},
            'mask_review_sha256':digest(source.get('mask_review'))}.items():
        if binding.get(k)!=v:raise Conflict('Initial cover mask/source context changed')
    clock=Path(binding['source_clock_path'])
    if sha(clock)!=binding['source_clock_sha256']:raise Conflict('Native cover clock changed')
    rows=json.loads(clock.read_text('utf-8'));times=[float(r['best_effort_timestamp_time']) for r in rows]
    if not times or not all(math.isfinite(t) for t in times) or any(b<=a for a,b in zip(times,times[1:])):
        raise Conflict('Native cover clock is invalid')
    index=next((i for i,t in enumerate(times) if t>=candidate['timestamp']-1e-9),None)
    if index is None or index+1>=len(times):raise Conflict('Native cover exposure is unverified')
    native={'ordinal':index,'start':times[index],'end':times[index+1],'end_basis':'next_decoded_pts'}
    if native!=binding['native_frame']:raise Conflict('Native cover frame identity changed')
    windows=source.get('reviewed_intervals')
    if ((require_mask_change and not windows)
            or (windows is not None and not any(w['source_start']<=native['start']<native['end']<=w['source_end'] for w in windows))
            or (windows is None and source.get('mask_review'))
            or not any(b.get('selected_shot_id')==shot['id'] and b['source_start']<=native['start']<native['end']<=b['source_end']
                for b in plan['beats'])):
        raise Conflict('The full native cover frame is outside the frozen used interval')
    active=[]
    for mask in source.get('watermark_masks',[]):
        if mask['source_start']<native['end'] and mask['source_end']>native['start']:
            if not mask['source_start']<=native['start']<native['end']<=mask['source_end'] or mask.get('reviewed') is not True:
                raise Conflict('Cover mask cuts the native exposure')
            active.append(mask)
    if binding['active_masks']!=active or (require_mask_change and not active):raise Conflict('Approved cover masks changed')
    for prefix in ('raw_canvas','canvas'):
        if sha(binding[prefix+'_path'])!=binding[prefix+'_sha256']:raise Conflict('Bound cover canvas changed')
        with Image.open(binding[prefix+'_path']) as image:
            if image.size!=(1080,1920) or hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()!=binding[prefix+'_rgb_sha256']:
                raise Conflict('Actual cover RGB pixels changed')
    if ((require_mask_change and binding['canvas_rgb_sha256']==binding['raw_canvas_rgb_sha256'])
            or candidate['frame_path']!=binding['canvas_path']
            or binding['review_frame_path']!=binding['canvas_path']
            or binding['review_frame_sha256']!=binding['canvas_sha256']):
        raise Conflict('Cover review does not use the changed actual full canvas')
    confirmation=candidate.get('single_frame_confirmation') or {}
    if require_approval and (confirmation.get('candidate_id')!=candidate.get('review_frame_id')
            or len(confirmation.get('reviews',[]))!=1 or not any(r.get('id')=='0'
            and r.get('eligible') is True and r.get('faces_present') is False and r.get('face_blur_used') is False
            and all(r.get(k) is True for k in ('hook_unresolved','overlays_acceptable','mask_coverage_valid','product_view_preserved'))
            for r in confirmation.get('reviews',[]))):
        raise Conflict('An independent final full-canvas cover approval is required')
    return {'source_sha256':source['sha256'],'native_frame':native,'active_masks':active,
        'raw_rgb_sha256':binding['raw_canvas_rgb_sha256'],'masked_rgb_sha256':binding['canvas_rgb_sha256']}


def checked_plan(state, receipt):
    if (receipt.get('policy')!=POLICY or receipt.get('task_id')!=state['id']
            or receipt.get('run_id')!=state['run_id'] or receipt.get('input_signature')!=input_signature(state)
            or state.get('edit_id') or state.get('edits') or state['daily_quality'].get('repair_round',0)!=0
            or state['daily_quality'].get('repair_context') or state['daily_quality'].get('feedback')
            or receipt.get('script_id')!=state['script_id'] or receipt.get('voice_id')!=state['voice_id']):
        raise Conflict('Initial prepared render no longer belongs to this empty edit run')
    for key in ('prepared_plan','selected_result','cover_review','independent_review','pixel_candidates','pixel_proof',
            'batch_submission','solo_submission'):
        value=receipt[key]
        if sha(value['path'])!=value['sha256']:raise Conflict('Prepared '+key+' evidence changed')
    frozen=json.loads(Path(receipt['selected_result']['path']).read_text('utf-8'))['plan']
    plan=json.loads(Path(receipt['prepared_plan']['path']).read_text('utf-8'))
    if without_cover(plan)!=without_cover(frozen):raise Conflict('Frozen body, cuts, voice, cues or sources changed')
    allowed={'source','selection_note','selection_policy'}
    if receipt.get('copy_revision'):
        revision=receipt['copy_revision']
        if sha(revision['path'])!=revision['sha256']:raise Conflict('Cover copy proposal changed')
        proposal=json.loads(Path(revision['path']).read_text('utf-8'))
        for field in ('task_id','run_id','script_id','voice_id'):
            if proposal['binding'].get(field)!=receipt[field]:raise Conflict('Cover copy proposal belongs to a different selection')
        if (proposal['binding']['selected_sha256']!=receipt['selected_result']['sha256']
                or proposal['binding']['candidates_sha256']!=receipt['pixel_candidates']['sha256']
                or proposal['binding']['previous_lines']!=frozen['cover_spec']['lines']
                or proposal['thumbnail_lines']!=plan['cover_spec']['lines']
                or state['daily_quality'].get('thumbnail_lines')!=proposal['thumbnail_lines']
                or canonical_lines(proposal['thumbnail_lines'])==canonical_lines(frozen['cover_spec']['lines'])
                or proposal['approved'] is not False or proposal['task_mutations']!=0):
            raise Conflict('Copy revision is not tied to the preserved actual failure')
        marker=json.loads(Path(proposal['official_proposal_path']).read_text('utf-8'))
        if sha(proposal['official_proposal_path'])!=proposal['official_proposal_sha256']:
            raise Conflict('Official copy proposal result changed')
        if (marker.get('state')!='completed' or type(marker.get('actual_calls')) is not int or marker['actual_calls']!=1
                or marker['binding']!=proposal['binding'] or marker['result']['thumbnail_lines']!=proposal['thumbnail_lines']):
            raise Conflict('Copy proposal is not a completed normal model result')
        result_file=marker['writing_result']
        if sha(result_file['path'])!=result_file['sha256']:raise Conflict('Copy writer result changed')
        actual_copy=json.loads(Path(result_file['path']).read_text('utf-8'))
        if actual_copy['value']!=marker['result']:raise Conflict('Copy writer result does not match the actual proposal')
        calls=actual_copy.get('inference',{}).get('calls',[])
        if (len(calls)!=1 or calls[0].get('status')!='completed'
                or not isinstance(marker.get('call_id'),str) or not marker['call_id']
                or calls[0].get('call_id')!=marker['call_id']):
            raise Conflict('Copy proposal is not bound to its actual completed model call')
        previous=proposal['binding']
        if sha(previous['failed_fullcanvas_review_path'])!=previous['failed_fullcanvas_review_sha256']:
            raise Conflict('Actual prior copy rejection changed')
        failed_rows=json.loads(Path(previous['failed_fullcanvas_review_path']).read_text('utf-8'))['reviews']
        if not failed_rows or any(r.get('hook_unresolved') is not False for r in failed_rows):
            raise Conflict('The copy change lacks an actual rejected-hook observation')
        allowed.update({'lines','copy_origin'})
    cover_fields=lambda spec:{k:v for k,v in spec.items() if k not in allowed}
    if cover_fields(plan['cover_spec'])!=cover_fields(frozen['cover_spec']):
        raise Conflict('The approved thumbnail copy or style changed')
    script=next(s for s in state['scripts'] if s['id']==state['script_id'])
    voice=next(v for v in state['voices'] if v['id']==state['voice_id'])
    if plan['script_text']!=script['text'] or sha(voice['path'])!=voice['sha256']:
        raise Conflict('Approved narration input changed')
    if plan['narration_priority']['script_id']!=script['id'] or plan['voice_source'].get('id')!=voice['id']:
        raise Conflict('Frozen script or personal voice identity changed')
    for field in ('voice','voice_source'):
        if plan.get(field) and sha(plan[field]['path'])!=plan[field]['sha256']:
            raise Conflict('Frozen rendered audio input changed')
    current={s['id']:s for s in state['sources']}
    for source in plan['sources']:
        if (not editing_ready(current.get(source['id'],{})) or source['sha256']!=current[source['id']]['sha256']
                or sha(source['path'])!=source['sha256']
                or source.get('reviewed_intervals')!=current[source['id']].get('reviewed_intervals')
                or source.get('watermark_masks')!=current[source['id']].get('watermark_masks')):
            raise Conflict('Frozen source approvals or media changed')
    candidate=plan['cover_spec']['source']
    material=checked_cover(plan,candidate)
    material['thumbnail_lines']=canonical_lines(plan['cover_spec']['lines'])
    if material!=receipt['material'] or digest(material)!=receipt['material_key']:
        raise Conflict('Actual initial cover material changed')
    if candidate['cover_pixel_binding']['binding_sha256']!=receipt['accepted_cover_binding_sha256']:
        raise Conflict('The accepted cover pixel binding changed')
    candidates=json.loads(Path(receipt['pixel_candidates']['path']).read_text('utf-8'))
    if not any(c['cover_pixel_binding']==candidate['cover_pixel_binding'] and c['frame_path']==candidate['frame_path'] for c in candidates):
        raise Conflict('Cover pixels are not among the independently verified candidates')
    review=json.loads(Path(receipt['cover_review']['path']).read_text('utf-8'))
    if candidate['single_frame_confirmation'] not in review.get('confirmations',[]):
        raise Conflict('The final independent cover confirmation changed')
    key_candidate=candidate['review_frame_id']
    rows=[r for r in review['reviews'] if r.get('id')==key_candidate]
    from .cover_selection import eligible_frames
    if len(rows)!=1 or not eligible_frames([candidate],[{**rows[0],'id':'0'}]):
        raise Conflict('The selected candidate lacks a positive exact batch approval')
    independent=json.loads(Path(receipt['independent_review']['path']).read_text('utf-8'))
    if (independent.get('status')!='PASS' or independent.get('task_id')!=state['id']
            or independent.get('candidates_sha256')!=receipt['pixel_candidates']['sha256']
            or independent.get('selected_plan_sha256')!=receipt['selected_result']['sha256']
            or independent.get('source_sha256')!=candidate['source_sha256']):
        raise Conflict('Independent actual candidate verification is incomplete')
    if independent.get('pixel_proof_sha256')!=receipt['pixel_proof']['sha256']:
        raise Conflict('Independent native pixel preparation proof changed')
    expected_binding={k:receipt[k] for k in ('task_id','run_id','script_id','voice_id','input_signature',
        'pixel_proof_sha256','candidates_sha256','independent_sha256')}
    expected_binding['selected_plan_sha256']=receipt['selected_result']['sha256']
    if receipt.get('copy_revision'):expected_binding['copy_revision_sha256']=receipt['copy_revision']['sha256']
    for purpose,key in [('cover_selection','batch_submission'),('cover_single_frame_confirmation','solo_submission')]:
        submission=json.loads(Path(receipt[key]['path']).read_text('utf-8'))
        if (submission.get('state')!='completed' or type(submission.get('actual_calls')) is not int or submission.get('actual_calls')!=1
                or submission.get('binding')!=expected_binding or submission.get('purpose')!=purpose):
            raise Conflict('Official cover model submission is incomplete')
        job_result=submission['writing_result']
        if sha(job_result['path'])!=job_result['sha256']:raise Conflict('Official writing result changed')
        actual=json.loads(Path(job_result['path']).read_text('utf-8'))
        if actual.get('value')!=submission['result'] or len(actual.get('inference',{}).get('calls',[]))!=1:
            raise Conflict('Official model result provenance changed')
        call=actual['inference']['calls'][0]
        if (call.get('status')!='completed' or not isinstance(submission.get('call_id'),str) or not submission['call_id']
                or call.get('call_id')!=submission['call_id']):
            raise Conflict('Official model completion changed')
        if key=='batch_submission':
            if submission['frame_ids']!=[str(i) for i in range(len(candidates))] or submission['result']['frames']!=review['reviews']:
                raise Conflict('Batch approval is not bound to the actual candidate set')
        elif (submission['frame_ids']!=['0'] or submission['candidate_id']!=key_candidate
                or submission['result']['frames']!=candidate['single_frame_confirmation']['reviews']):
            raise Conflict('Solo approval is not bound to the actual selected candidate')
    prior=next((p for p in state['daily_quality'].get('preparation_failures',[]) if p['identity']==receipt['preparation_failure_identity']),None)
    if not prior or not prior.get('no_render') or prior.get('actual_edit_id'):
        raise Conflict('Initial no-render failure provenance changed')
    validate_selected_scenes(state,plan)
    return plan


def from_state(state, expected_key=None):
    record=state.get('initial_render_preparation')
    if not record:return None
    if sha(record['path'])!=record['sha256']:raise Conflict('Accepted initial preparation receipt changed')
    receipt=json.loads(Path(record['path']).read_text('utf-8'))
    if expected_key is not None and expected_key!=receipt['material_key']:raise Conflict('Queued initial render material changed')
    return receipt,checked_plan(state,receipt)
