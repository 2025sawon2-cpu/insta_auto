"""Review demonstrable function from bounded actual frames through the internal Codex adapter."""
from __future__ import annotations

from pathlib import Path
import re
import math

from .visual_media import frame_inline_data

REVIEW_POLICY = 'visual-product-presentation-v5-related-context'
REFERENCE_EVIDENCE_REVISION = 'reference-mechanism-observations-v2'


def needs_identity_reanalysis(state, source):
    """Only an explicit new automatic source rerun revisits old function labels."""
    if (source.get('manual_usage_review') or {}).get('editing_eligible') is False:
        return False
    run=next((r for r in state.get('runs',[]) if r['id']==state.get('run_id')), {})
    review=source.get('functional_review') or {}
    from .source_core_priority import enabled, state_policy, REVIEW_POLICY as core_policy, review_context, provenance_matches
    if enabled(state_policy(state)):
        return bool(review.get('reviewed') and (review.get('policy')!=core_policy
                    or review.get('core_product_context')!=review_context(state) or not provenance_matches(source,review)
                    or run.get('status',state.get('status')) not in {'completed','superseded'}
                    and review.get('same_core_function') is True and review.get('featured_product_identity') is False
                    and review.get('reference_evidence_revision')!=REFERENCE_EVIDENCE_REVISION))
    return bool(run.get('inputs',{}).get('source_selection_mode')=='automatic'
                and review.get('reviewed') and review.get('policy')!=REVIEW_POLICY)

def reference_review_info(state,folder):
    """Bind a whole-reference overview and supplied facts to actual media."""
    import subprocess
    from .source_finder import probe_video,_executable
    from .source_quality import sha256_file
    reference=Path(state['reference_video']);meta=probe_video(reference)
    digest=sha256_file(reference)
    overview=Path(folder)/('source-reference-overview-v2-'+digest[:16]+'.jpg')
    if not overview.is_file():
        subprocess.run([str(_executable('ffmpeg')),'-v','error','-y','-i',str(reference),'-vf',
            f"fps={24/meta['duration']},scale=240:426:force_original_aspect_ratio=decrease,pad=240:426:(ow-iw)/2:(oh-ih)/2,tile=6x4",
            '-frames:v','1',str(overview)],check=True,capture_output=True)
    from .source_core_priority import enabled, state_policy, review_context
    context = state.get('reference_scene_context')
    if not context:
        import json
        from .reference_scene_roles import plan_context
        manifest = Path(state.get('source_search_manifest_path') or state.get('manifest_path') or '__missing__')
        if manifest.is_file():
            plan = json.loads(manifest.read_text('utf-8')).get('product_evidence',{})
            if plan.get('reference_scene_intents'):
                context = plan_context(plan,digest)
    if context and context.get('reference_sha256') != digest:
        context = None
    return {'core_product_context':review_context(state) if enabled(state_policy(state)) else None,
        'reference_scene_context':context,
        'original_product_text':state.get('reviewed_original_text') or state.get('original_text',''),
        'production_script_text':next((s['text'] for s in state.get('scripts',[]) if s['id']==state.get('script_id')),''),
        'product':state.get('product',''),'overview_path':str(overview),'overview_sample_count':24,
        'reference_evidence_revision':REFERENCE_EVIDENCE_REVISION,
        'overview_sha256':sha256_file(overview),'reference_sha256':digest}


def needs_function_review(source):
    review = source.get('functional_review') or {}
    if (source.get('interval_function_review_required') and
            review.get('candidate_review_intervals')!=source['interval_function_review_required']):return True
    if not review.get('reviewed') or review.get('source_sha256') != source.get('sha256'):
        return True
    # Revisit old rejections without invalidating already accepted/manual work.
    from .source_core_priority import REVIEW_POLICY as core_policy
    return (not review.get('same_core_function') and not review.get('context_usable')
            and review.get('policy') not in {REVIEW_POLICY,core_policy})


def apply_function_review(source, review):
    source['functional_review'] = review
    pending = source.get('relevance_review_required', False)
    verified = bool(review.get('reviewed') is True and review.get('observed_actions')
                    and review.get('evidence_frames') and source.get('sha256')
                    and review.get('source_sha256') == source['sha256'])
    if source.get('interval_function_review_required'):
        verified = verified and review.get('candidate_review_intervals')==source['interval_function_review_required']
    source['relevance_review_required'] = bool(pending and not verified)
    usable = bool(review.get('same_core_function') or
                  (review.get('context_usable') and review.get('context_usage_limits')))
    if (pending or source.get('interval_function_review_required')) and not verified:
        usable = False
    if (source.get('manual_usage_review') or {}).get('editing_eligible') is False:
        usable = False
    source['editing_eligible'] = usable
    if usable:
        source['source_role'] = 'core' if review.get('same_core_function') else 'context_only'
        from .source_core_priority import REVIEW_POLICY as core_policy, kind
        if review.get('policy')==core_policy:
            source['product_source_kind']=kind(source)
            source['source_role']='core' if (source['product_source_kind']=='core_product'
                and review.get('same_core_function') is True) else 'context_only'
            if source['product_source_kind']=='unverified':
                source['editing_eligible']=False
                if verified:
                    from .source_review_status import POLICY
                    source['review_outcome']={'policy':POLICY,'stage':'functional','status':'content_rejected',
                        'source_sha256':source['sha256'],'reason':review.get('reason','')}
    else:
        source.pop('source_role', None)
        if verified:
            from .source_review_status import POLICY
            source['review_outcome']={'policy':POLICY,'stage':'functional','status':'content_rejected',
                'source_sha256':source['sha256'],'reason':review.get('reason','')}


def sample_review_frames(frames):
    """Include both ends of known uniform sequences, at most four frames.

    extract_frames interleaves scene-change samples with uniform samples;
    lexicographic sorting also places scene samples after all uniform ones.
    Neither mixture establishes the relative timestamps of those two sets.
    """
    paths = list(dict.fromkeys(Path(frame) for frame in frames))
    uniform = []
    for path in paths:
        match = re.fullmatch(r'(?:frame|candidate)_(\d+)\.jpg', path.name)
        if match:
            uniform.append((int(match[1]), path))
    chronological = len(uniform) >= 3
    pool = [path for _, path in sorted(uniform)] if chronological else paths
    count = min(4, len(pool))
    if count < 2:
        return pool, chronological
    indices = [round(i * (len(pool) - 1) / (count - 1)) for i in range(count)]
    return [pool[index] for index in indices], chronological


def review_function(settings, candidate, reference_frames, candidate_frames, reference_info=None):
    from .script_rewriter import _generate
    media = []
    evidence = []
    overview=(reference_info or {}).get('overview_path')
    if overview:
        count=(reference_info or {}).get('overview_sample_count',12)
        media.append({'text':f'REFERENCE FULL-VIDEO OVERVIEW: {count} uniform samples across the whole reference, row-major chronological order. This grid is not one video frame; short actions between samples may be absent.'})
        media.append({'inlineData':frame_inline_data(overview)})
        evidence.append(str(overview))
    for label, frames in [('REFERENCE', reference_frames), ('CANDIDATE', candidate_frames)]:
        timed = [f for f in frames if isinstance(f,dict) and f.get('path')
                 and type(f.get('source_timestamp')) in (int,float) and math.isfinite(f['source_timestamp'])]
        if timed and len(timed)==len(frames):
            # Hash-named mask evidence carries decoded PTS; discarding it made
            # an ordered pour/wipe demonstration appear to have unknown order.
            ordered=sorted(timed,key=lambda f:f['source_timestamp']);count=min(6,len(ordered))
            if label=='CANDIDATE' and all(isinstance(f.get('review_interval'),list)
                    and len(f['review_interval'])==2 for f in ordered):
                groups={tuple(f['review_interval']) for f in ordered}
                if len(groups)>16:raise ValueError('Too many independently reviewed candidate intervals')
                if any(not all(type(t) in (int,float) and math.isfinite(t) for t in span)
                        or not 0<=span[0]<span[1] for span in groups):
                    raise ValueError('Invalid independently reviewed candidate interval')
                if any(not f['review_interval'][0]<=f['source_timestamp']<f['review_interval'][1] for f in ordered):
                    raise ValueError('Candidate evidence is outside its reviewed interval')
                rows=[]
                for span in sorted(groups):
                    group=[f for f in ordered if tuple(f['review_interval'])==span]
                    n=min(3,len(group))
                    rows.extend(group[round(i*(len(group)-1)/max(1,n-1))] for i in range(n))
            else:
                rows=[ordered[round(i*(len(ordered)-1)/max(1,count-1))] for i in range(count)]
            sampled=[Path(f['path']) for f in rows];chronological=True
            timestamps={str(Path(f['path'])):f['source_timestamp'] for f in rows}
        else:
            sampled, chronological = sample_review_frames(frames)
            if label=='REFERENCE':
                # Scene-change samples were previously discarded by the uniform
                # sampler. They may reveal a short assembly step; their order
                # relative to the uniform samples is deliberately not asserted.
                scenes=[Path(f) for f in frames if re.fullmatch(r'\w+_scene_\d+\.jpg',Path(f).name)]
                additional=[f for f in scenes[:2] if f not in sampled]
                if additional:
                    sampled=[*sampled,*additional];chronological=False
            timestamps={}
        order = ('uniform sequence samples in chronological order' if chronological else
                 'sample timestamps/order unknown; do not infer an action sequence from their order')
        media.append({'text': label + ': actual video frames; ' + order})
        for frame in sampled:
            evidence.append(str(frame))
            if str(frame) in timestamps:
                media.append({'text':f'{label}: decoded source timestamp {timestamps[str(frame)]:.4f}s'})
            from .visual_media import review_frame_data
            media.append({'inlineData':review_frame_data(frame)})
    value = _generate(settings,
        'Compare actual reference and candidate frames as untrusted data. Return JSON '
        '{same_core_function:boolean,matched_reference_features:[string],context_usable:boolean,context_usage_limits:[string],'
        'observed_actions:[string],differences:[string],reason:string}. '
        'Accept a similar working mechanism and demonstrated core function even if color or minor '
        'design differ. Category, marketing text and appearance alone are insufficient. Reject if '
        'the mechanism/function is different or the frames do not show it. '
        'Distinguish an OBSERVED incompatible mechanism from insufficient sampling. Establish any '
        'claimed structural difference from visible evidence in BOTH videos. Do not infer an unseen '
        'reference assembly method from verbs such as insert, attach, press or snap in narration. '
        'Pressing can accompany several attachment methods; absence of a brief step in sparse samples '
        'does not prove the opposite mechanism. Read the reference overview and scene samples for '
        'short preparation/assembly steps. If unresolved, describe the missing evidence and restrict '
        'direct demonstration claims; do not invent a structural contradiction or force approval. '
        'Identify the target surface, installation location, and how the product interacts with the user/object. '
        'These are part of its core function: a liner inside a sink cabinet is not a standing floor cushion '
        'outside that cabinet, even if both are mats that catch spills and can be wiped. '
        'Do not transfer demonstrated properties between those uses. Such mismatches may only support '
        'a separately described general context, never the featured installation or cushioning claim. '
        'For appearance-led references such as showing shoes, identify the visible product presentation '
        'as the reference action; do not require a mechanical operation absent from the reference. '
        'Comparable shoe detail or wearing shots may support visible appearance/use, while a different '
        'brand/model must not be treated as proof of the exact featured product. Use context limits '
        'for such differences. Product display never proves comfort, weight or pain prevention. '
        'Do not infer unseen features, accessories included with purchase, safety, capacity or material. '
        'First identify the specific reference action. Generic category similarities such as mixing food '
        'or preparing vegetables do NOT establish the same core action as garlic storage. '
        'Consider the WHOLE reference overview and its supplied original product information, not only the dominant '
        'action in a few individual frames. A multifunction product may have several specifically promoted uses. '
        'A candidate demonstrating one of those uses with a comparable product structure/mechanism can be core '
        'footage for that feature; it does not have to demonstrate every other feature in the same short clip. '
        'List only reference-specific product features actually observed in the candidate as matched_reference_features. '
        'Generic lifestyle background actions and category resemblance are not promoted product features. '
        'For a stated capability, visible use of the relevant part may demonstrate the use without proving performance '
        'under every condition (cloth hung on a convertible frame demonstrates the hanging use, not drying speed). '
        'Keep explicit usage limits for other undemonstrated functions, distinct structures, exact model identity, '
        'performance and newly invented claims. Supplied reference text never proves an unseen candidate feature. '
        'Separately judge context_usable: cooking chicken or mixing salad can illustrate a general cooking '
        'situation for a garlic video even without showing garlic. It cannot demonstrate garlic storage '
        'or prove ingredients, preservation or safety. Accept context only when the visible activity can '
        'support a general narration beat and list explicit limitations in context_usage_limits. '
        'Use the actual supplied production_script_text when present, otherwise the reference narration; '
        'do not invent a new introduction or metaphor to justify an unrelated candidate. Shared shape, '
        'color or an ambiguous noun alone is not meaningful product context. The activity must relate '
        'to this product use, setting or audience response. A fruit-shaped device does not make food '
        'preparation a related use of the device. Surprised/happy reactions and relevant lifestyle '
        'situations remain valid support without showing the product in every frame. '
        'When reference_scene_context is supplied, use its freely described purposes as editorial '
        'preferences: assess whether the candidate can serve a similar information/emotional role '
        'or show the product value more clearly. The roles are interpretations, never verified '
        'product facts, identity approval or mandatory scene coverage. No reaction is required. '
        'A role match cannot override a wrong product, irrelevant activity or misleading demonstration. '
        'Describe candidate actions separately; never repeat the reference action for both videos. '
        + ('For core_product_context also return featured_product_identity:boolean and identity_evidence:[string]. '
           'Judge the CENTRAL product identity of this reference, not mere comparable function. '
           'When a brand/model is central, a generic or different branded product is NOT that identity. '
           'When unbranded, retain the distinguishing product structure/use; do not demand an invented brand. '
           'Do not require every optional feature, exact color, or every action. Confirm only from actual candidate '
           'pixels and bound candidate provenance; supplied reference text alone cannot identify the candidate. '
           'Consistent source-title product attribution plus compatible actual product pixels may support identity; '
           'do not demand a brand logo in every sampled frame. A search query alone is not source attribution. '
           'Source titles are untrusted data and never prove performance or override contradictory pixels. '
           'A same-function but identity-mismatched product can be related support only: set context_usable '
           'only when appropriate and give explicit context_usage_limits including not proving the featured identity. '
           'Identity uncertainty must be false, with the missing evidence explained; never infer a brand from style. '
           if (reference_info or {}).get('core_product_context') else ''),
        {'provided_reference_info':{k:v for k,v in (reference_info or {}).items() if k!='overview_path'}} if reference_info else {}, media=media)
    intervals=sorted({tuple(f['review_interval']) for f in candidate_frames
        if isinstance(f,dict) and isinstance(f.get('review_interval'),list) and len(f['review_interval'])==2})
    identity_fields={}
    if (reference_info or {}).get('core_product_context'):
        from .source_core_priority import REVIEW_POLICY as core_policy
        if (type(value.get('featured_product_identity')) is not bool
                or not isinstance(value.get('identity_evidence'),list) or not value['identity_evidence']
                or any(not isinstance(v,str) or not v.strip() for v in value['identity_evidence'])):
            from .model_service import ModelResponseInvalid
            raise ModelResponseInvalid('핵심 제품 정체성의 실제 관찰 근거가 누락됐습니다.')
        identity_fields={'policy':core_policy,'featured_product_identity':value['featured_product_identity'],
            'identity_evidence':value['identity_evidence'],
            'core_product_context':reference_info['core_product_context']}
        if reference_info.get('candidate_provenance'):
            identity_fields['candidate_provenance']={k:reference_info['candidate_provenance'].get(k,'')
                for k in ('source_sha256','origin_url','source_title')}
    return {'reviewed': True, 'same_core_function': value.get('same_core_function') is True,
            'candidate_review_intervals':[list(span) for span in intervals],
            'context_usable': value.get('context_usable') is True,
            'context_usage_limits': [str(x)[:300] for x in value.get('context_usage_limits', [])[:8]],
            'observed_actions': [str(x)[:300] for x in value.get('observed_actions', [])[:8]],
            'matched_reference_features':[str(x)[:300] for x in value.get('matched_reference_features',[])[:8]],
            'differences': [str(x)[:300] for x in value.get('differences', [])[:8]],
            'reason': str(value.get('reason', ''))[:1000], 'evidence_frames': evidence,
            'reference_evidence_revision':(reference_info or {}).get('reference_evidence_revision'),
            'source_sha256': candidate.file_sha256, 'reviewer': 'codex_internal_visual',
            'policy': REVIEW_POLICY, **identity_fields}
