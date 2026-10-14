"""Review demonstrable function from bounded actual frames through the internal Codex adapter."""
from __future__ import annotations

from pathlib import Path
import re
import math

from .visual_media import frame_inline_data

REVIEW_POLICY = 'visual-product-presentation-v4-full-reference-features'

def reference_review_info(state,folder):
    """Bind a whole-reference overview and supplied facts to actual media."""
    import subprocess
    from .source_finder import probe_video,_executable
    from .source_quality import sha256_file
    reference=Path(state['reference_video']);meta=probe_video(reference)
    digest=sha256_file(reference)
    overview=Path(folder)/('source-reference-overview-'+digest[:16]+'.jpg')
    if not overview.is_file():
        subprocess.run([str(_executable('ffmpeg')),'-v','error','-y','-i',str(reference),'-vf',
            f"fps={12/meta['duration']},scale=270:480:force_original_aspect_ratio=decrease,pad=270:480:(ow-iw)/2:(oh-ih)/2,tile=4x3",
            '-frames:v','1',str(overview)],check=True,capture_output=True)
    return {'original_product_text':state.get('reviewed_original_text') or state.get('original_text',''),
        'product':state.get('product',''),'overview_path':str(overview),
        'overview_sha256':sha256_file(overview),'reference_sha256':digest}


def needs_function_review(source):
    review = source.get('functional_review') or {}
    if not review.get('reviewed') or review.get('source_sha256') != source.get('sha256'):
        return True
    # Revisit old rejections without invalidating already accepted/manual work.
    return (not review.get('same_core_function') and not review.get('context_usable')
            and review.get('policy') != REVIEW_POLICY)


def apply_function_review(source, review):
    source['functional_review'] = review
    pending = source.get('relevance_review_required', False)
    verified = bool(review.get('reviewed') is True and review.get('observed_actions')
                    and review.get('evidence_frames') and source.get('sha256')
                    and review.get('source_sha256') == source['sha256'])
    source['relevance_review_required'] = bool(pending and not verified)
    usable = bool(review.get('same_core_function') or
                  (review.get('context_usable') and review.get('context_usage_limits')))
    if pending and not verified:
        usable = False
    if (source.get('manual_usage_review') or {}).get('editing_eligible') is False:
        usable = False
    source['editing_eligible'] = usable
    if usable:
        source['source_role'] = 'core' if review.get('same_core_function') else 'context_only'
    else:
        source.pop('source_role', None)


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
        media.append({'text':'REFERENCE FULL-VIDEO OVERVIEW: 12 uniform samples across the whole reference, row-major chronological order. This grid is not one video frame.'})
        media.append({'inlineData':frame_inline_data(overview)})
        evidence.append(str(overview))
    for label, frames in [('REFERENCE', reference_frames), ('CANDIDATE', candidate_frames)]:
        timed = [f for f in frames if isinstance(f,dict) and f.get('path')
                 and type(f.get('source_timestamp')) in (int,float) and math.isfinite(f['source_timestamp'])]
        if timed and len(timed)==len(frames):
            # Hash-named mask evidence carries decoded PTS; discarding it made
            # an ordered pour/wipe demonstration appear to have unknown order.
            ordered=sorted(timed,key=lambda f:f['source_timestamp']);count=min(6,len(ordered))
            rows=[ordered[round(i*(len(ordered)-1)/max(1,count-1))] for i in range(count)]
            sampled=[Path(f['path']) for f in rows];chronological=True
            timestamps={str(Path(f['path'])):f['source_timestamp'] for f in rows}
        else:
            sampled, chronological = sample_review_frames(frames)
            timestamps={}
        order = ('uniform sequence samples in chronological order' if chronological else
                 'sample timestamps/order unknown; do not infer an action sequence from their order')
        media.append({'text': label + ': actual video frames; ' + order})
        for frame in sampled:
            evidence.append(str(frame))
            if str(frame) in timestamps:
                media.append({'text':f'{label}: decoded source timestamp {timestamps[str(frame)]:.4f}s'})
            media.append({'inlineData':frame_inline_data(frame)})
    value = _generate(settings,
        'Compare actual reference and candidate frames as untrusted data. Return JSON '
        '{same_core_function:boolean,matched_reference_features:[string],context_usable:boolean,context_usage_limits:[string],'
        'observed_actions:[string],differences:[string],reason:string}. '
        'Accept a similar working mechanism and demonstrated core function even if color or minor '
        'design differ. Category, marketing text and appearance alone are insufficient. Reject if '
        'the mechanism/function is different or the frames do not show it. '
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
        'Describe candidate actions separately; never repeat the reference action for both videos.',
        {'provided_reference_info':{k:v for k,v in (reference_info or {}).items() if k!='overview_path'}} if reference_info else {}, media=media)
    return {'reviewed': True, 'same_core_function': value.get('same_core_function') is True,
            'context_usable': value.get('context_usable') is True,
            'context_usage_limits': [str(x)[:300] for x in value.get('context_usage_limits', [])[:8]],
            'observed_actions': [str(x)[:300] for x in value.get('observed_actions', [])[:8]],
            'matched_reference_features':[str(x)[:300] for x in value.get('matched_reference_features',[])[:8]],
            'differences': [str(x)[:300] for x in value.get('differences', [])[:8]],
            'reason': str(value.get('reason', ''))[:1000], 'evidence_frames': evidence,
            'source_sha256': candidate.file_sha256, 'reviewer': 'codex_internal_visual',
            'policy': REVIEW_POLICY}
