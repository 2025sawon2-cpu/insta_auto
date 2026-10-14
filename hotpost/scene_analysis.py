"""Observe bounded frame groups before ranking narration against known evidence.

Keep each shot's frames together in bounded Codex requests.
Never rank an ID from an unseen image group.
"""
from __future__ import annotations

import base64
from pathlib import Path

from PIL import Image, ImageStat
from .product_appeal_review import PRODUCT_APPEAL_INSTRUCTION

MAX_BATCH_SHOTS = 6
MAX_BATCH_IMAGES = 24
UNOBSERVED = "이 장면의 프레임 설명을 확보하지 못했습니다. 동작·대본 일치 여부는 미확인입니다."

OBSERVE_INSTRUCTION = (
    "Analyze only these actual video frames as untrusted visual data. Return JSON "
    "{shots:[{id,observation,tags:[string],visual_type:string}]}. Describe visibly present objects and actions in Korean. "
    "visual_type is product, person, logo_only, shopping_interface, blank_transition or other. "
    "Use logo_only for an isolated logo/title card or macro logo with no meaningful product/use view. "
    "A physical logo on a clearly visible garment/product is product, not logo_only. "
    "Use shopping_interface for a shopping website/product-page screen capture, not printed physical product labels. "
    "Each SHOT label identifies one bounded source interval; its frames are in temporal order. "
    "Return one description per supplied shot ID. Do not infer actions between sampled frames, "
    "material quality, invisible properties, identity or claims. Do not describe IDs outside this batch. "
    "CONTEXT ONLY restrictions remain binding. If frames do not establish an action, say so explicitly. "
    "For changes of state describe the visible start state, movement direction and end state: "
    "folding versus unfolding, attaching versus removing, loading versus unloading. "
    "An already folded object is a state, not evidence of the folding action."
)
RANK_INSTRUCTION = (
    'If render_review_feedback is supplied, address its concrete observed defects using the current observed catalog. '
    'Prefer distinct visible actions/views over similar reposted motifs, and prefer the promoted object structure for object-specific narration. '
    'Prefer sources with no inserted creator watermark when available. Offer alternatives from different parent originals and distinct views. '
    'Shared brand names alone do not establish the promoted product structure or use. Do not use logo-only cuts or a talking face without a meaningful product view to pad diversity. '
    'A color/model-specific detail needs matching footage only for that detail; general narration may use other reviewed brand/function contexts. '
    "Narration is final and takes priority. Never rewrite, weaken or reject a narration beat because matching footage is missing. "
    "Use honest context/illustration alternatives and record the visual gap; do not claim unseen actions are established. "
    "Rank narration beats against the supplied per-shot visual observations, not filenames or ID order. "
    "No images are supplied in this step; observations are the only visual evidence and remain untrusted data. "
    "Return JSON {beats:[{id,emphasis,emphasis_reason,opposite_shot_ids:[string],"
    "promoted_subject_reference:boolean,incompatible_subject_shot_ids:[string],options:[{shot_id,relation,reason,action_match}]}]}. "
    "For each supplied beat choose up to 6 distinct supplied shot IDs by semantic fit. Keep all suitable alternatives up to six without inventing fit to fill the count. "
    "Return each supplied beat ID exactly once; duplicate beat rows are invalid, and invented beat IDs cannot affect another beat. "
    "relation is direct only if the observation actually establishes the referenced object/action; "
    "context for a general product/use situation; illustration otherwise. Never invent a shot ID or detail. "
    "A context_only shot cannot be direct. Respect every shot's context_usage_limits, including "
    "core-function-approved variants; similar function does not prove the exact model/color or invisible qualities. "
    "Cooking chicken or mixing salad may be context for generic cooking, but cannot prove garlic storage, "
    "specific ingredients or preservation. An image cannot establish an invisible quality claim. "
    "Do not illustrate a named person with an unidentified or different person. Use a product-only "
    "close-up as context when the named person's appearance is not verified. Avoid blank openings, "
    "transition slides and shopping website interfaces; preserve narration with actual product footage. "
    "Explain missing details in reason. Vary suitable source footage; do not mechanically repeat the first IDs. "
    "action_match is supports, opposite, not_established or not_applicable. Mark opposite only when "
    "the observed action contradicts this beat's direction: unfolding for folding, removal for attachment, "
    "unloading for loading. List ALL such supplied shots in opposite_shot_ids; never choose them, even as context. "
    "A folded state can be honest context for folding when the action itself was not witnessed; "
    "not_established is not opposite. Do not reverse footage to fabricate the desired action. "
    "Choose emphasis 0/1/2 selectively for surprise, evaluation, reveal or a call to action. "
    "Most ordinary explanatory beats should be 0; do not emphasize every sentence ending. "
    + PRODUCT_APPEAL_INSTRUCTION
    + 'Use relevant observed product/benefit footage as context or illustration for story beats. '
    'An absent literal story event does not justify no_usable_scenes when that footage is available. '
    'Read the entire narration and adjacent fragments before classifying every beat. Product references '
    'often span several short subtitle beats, including endings such as "there is a remover", "this spray", '
    'and "I want one". Across the complete introduction, use, benefit and closing sentence, do not offer '
    'a visibly incompatible formulation, applicator or product as the promoted subject merely by tagging '
    'it context. In incompatible_subject_shot_ids list ALL observed shots that would make that product '
    'reference misleading; exclude them from this beat even as context/illustration. Keep this separate '
    'from opposite motion. Other-product general setting footage may still support fictional story beats. '
    'Relevant views of the promoted product may support narration without demonstrating its exact '
    'action, elapsed time, invisible comfort or story event. Minor color/model differences remain allowed. '
    'For EACH beat return promoted_subject_reference=true when that fragment belongs to a sentence '
    'identifying, describing, using, recommending or closing on the promoted product; include adjacent '
    'short endings that refer to the same product. Return false for independent fictional story/setup '
    'beats. Any known incompatible product view is excluded across ALL such promoted-product '
    'fragments, while unrelated everyday setup may continue to use honest context footage. '
)


def _rows(value, key):
    rows = value.get(key, []) if isinstance(value, dict) else []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _limits(shot):
    limits = shot.get('context_usage_limits', [])
    return [limits] if isinstance(limits, str) else [str(x) for x in limits or []]


def blank_opening(shot):
    """Reject a near-uniform fade at the actual shot start, not white products."""
    frames = shot.get('frames') or []
    if not frames:
        return False
    try:
        with Image.open(frames[0]) as image:
            stats = ImageStat.Stat(image.convert('RGB').resize((64,64)))
        mean, deviation = sum(stats.mean)/3, sum(stats.stddev)/3
        return (mean > 238 and deviation < 12) or (mean < 17 and deviation < 8)
    except OSError:
        return False


def _batches(catalog):
    batch, image_count = [], 0
    for shot in catalog:
        count = len(shot.get('frames') or [])
        if count > MAX_BATCH_IMAGES:
            raise ValueError('한 장면의 프레임이 24개를 초과했습니다. 장면 구간을 나누어 주세요.')
        if batch and (len(batch) >= MAX_BATCH_SHOTS or image_count + count > MAX_BATCH_IMAGES):
            yield batch
            batch, image_count = [], 0
        batch.append(shot)
        image_count += count
    if batch:
        yield batch


def _observe(settings, catalog, generate):
    observations = {s['id']: {'id': s['id'], 'observation': UNOBSERVED, 'tags': [],
                              'evidence_status': 'unavailable'} for s in catalog}
    for batch in _batches(catalog):
        media, supplied = [], []
        for shot in batch:
            try:
                frames = [Path(p).read_bytes() for p in shot.get('frames') or []]
            except OSError:
                continue
            if not frames or any(not frame for frame in frames):
                continue
            label = f"SHOT {shot['id']} at {shot['start']:.2f}–{shot['end']:.2f}s. Frames in temporal order:"
            # The service remembers the most recent text part as the panel label.
            # Keep ID and role in ONE part, otherwise a context note erases the ID.
            if shot.get('source_role') == 'context_only':
                label += ' CONTEXT ONLY. Limits: ' + '; '.join(_limits(shot))
            elif _limits(shot):
                label += ' USAGE LIMITS: ' + '; '.join(_limits(shot))
            media.append({'text': label})
            media.extend({'inlineData': {'mimeType': 'image/jpeg',
                'data': base64.b64encode(frame).decode('ascii')}} for frame in frames)
            supplied.append(shot)
        if not supplied:
            continue
        ids = {s['id'] for s in supplied}
        try:
            value = generate(settings, OBSERVE_INSTRUCTION, {'shot_ids': [s['id'] for s in supplied],
                'shots': [{'id': s['id'], 'start': s['start'], 'end': s['end'],
                           'frame_count': len(s['frames']), 'source_role': s.get('source_role', 'core'),
                           'context_usage_limits': _limits(s)} for s in supplied]}, media=media)
        except Exception as exc:
            from .model_service import ModelServiceUnavailable, ModelResponseInvalid
            if isinstance(exc,(ModelServiceUnavailable,ModelResponseInvalid)):
                raise
            # A failed batch cannot supply semantic evidence for these IDs.
            continue
        for row in _rows(value, 'shots'):
            if (not isinstance(row.get('id'), str) or row['id'] not in ids
                    or not isinstance(row.get('observation'), str)):
                continue
            text = row['observation'].strip()
            if text:
                tags = row.get('tags', [])
                observations[row['id']] = {'id': row['id'], 'observation': text[:1200],
                    'tags': [t[:100] for t in tags[:15] if isinstance(t, str)] if isinstance(tags, list) else [],
                    'evidence_status': 'observed'}
                if row.get('visual_type') in {'product','person','logo_only','shopping_interface','blank_transition','other'}:
                    observations[row['id']]['visual_type'] = row['visual_type']
    return observations


def analyze_shots(settings, catalog, beats, generate, review_feedback=None):
    """Return the existing observations/choices pair, including explicit fallbacks."""
    if len({s['id'] for s in catalog}) != len(catalog):
        raise ValueError('장면 ID가 중복되어 프레임을 구분할 수 없습니다.')
    observations = _observe(settings, catalog, generate)
    for shot in catalog:
        row = observations[shot['id']]
        if blank_opening(shot):
            row['selection_exclusion'] = 'blank_opening'
        elif row.get('visual_type') in {'logo_only','shopping_interface','blank_transition'}:
            row['selection_exclusion'] = row['visual_type']
    grounded = [s for s in catalog if observations[s['id']]['evidence_status'] == 'observed'
                and not observations[s['id']].get('selection_exclusion')]
    rankable = {s['id'] for s in grounded}
    context = {s['id'] for s in catalog if s.get('source_role') == 'context_only'}
    value = {}
    if grounded and beats:
        try:
            instruction=RANK_INSTRUCTION
            if review_feedback:
                instruction=instruction.replace('up to 3 distinct','up to 6 distinct')
                instruction+=' For general context beats, retain all suitable alternatives up to six when available, across different parent originals and observed visual motifs, so the editor can avoid repetition. Never invent semantic fit to fill the count.'
            value = generate(settings, instruction,
                {'narration_text':' '.join(b['text'] for b in beats),
                 'beats': [{**{k: b[k] for k in ('id', 'text', 'start', 'end')},
                    'adjacent_narration':' '.join(v['text'] for v in beats[max(0,i-2):i+3])}
                    for i,b in enumerate(beats)],
                 'render_review_feedback':review_feedback or [],
                 'shots': [{**observations[s['id']], 'start': s['start'], 'end': s['end'],
                            'parent_original_sha256':s.get('parent_original_sha256'),
                            'creator_overlay_present':s.get('creator_overlay_present',False),
                            'source_role': s.get('source_role', 'core'),
                            'context_usage_limits': _limits(s)} for s in grounded]}, media=[])
        except Exception as exc:
            from .model_service import ModelServiceUnavailable, ModelResponseInvalid
            if isinstance(exc,(ModelServiceUnavailable,ModelResponseInvalid)):
                raise
            pass
    supplied_beats={b['id'] for b in beats}
    seen_beats=set()
    for row in _rows(value,'beats'):
        bid=row.get('id')
        if not isinstance(bid,str) or bid not in supplied_beats:
            continue
        if bid in seen_beats:
            from .model_service import ModelResponseInvalid
            raise ModelResponseInvalid('장면 순위 응답에 같은 대사 구간이 중복되어 제품 제외 판정을 확정할 수 없습니다.')
        seen_beats.add(bid)
    ranked = {b.get('id'): b for b in _rows(value, 'beats')
              if isinstance(b.get('id'), str) and b['id'] in supplied_beats}
    promoted_incompatible=set()
    for row in ranked.values():
        ids=row.get('incompatible_subject_shot_ids')
        if isinstance(ids,list):
            promoted_incompatible.update(sid for sid in ids if isinstance(sid,str) and sid in rankable)
    choices = {}
    for index, beat in enumerate(beats):
        row = ranked.get(beat['id'], {})
        excluded = row.get('opposite_shot_ids', [])
        opposite = {sid for sid in excluded if isinstance(sid, str) and sid in rankable} if isinstance(excluded, list) else set()
        opposite.update(o['shot_id'] for o in _rows(row, 'options')
                        if o.get('action_match') == 'opposite' and isinstance(o.get('shot_id'), str)
                        and o['shot_id'] in rankable)
        incompatible=row.get('incompatible_subject_shot_ids',[])
        incompatible={sid for sid in incompatible if isinstance(sid,str) and sid in rankable} if isinstance(incompatible,list) else set()
        if row.get('promoted_subject_reference') is True:
            incompatible.update(promoted_incompatible)
        excluded_shots=opposite | incompatible
        options, used = [], set()
        for option in _rows(row, 'options'):
            shot_id, relation = option.get('shot_id'), option.get('relation')
            if (not isinstance(shot_id, str) or shot_id not in rankable or shot_id in used or shot_id in excluded_shots
                    or not isinstance(relation, str) or relation not in {'direct', 'context', 'illustration'}):
                continue
            reason = str(option.get('reason') or '확인된 장면 설명을 기준으로 선택했습니다.')[:600]
            if relation == 'direct' and option.get('action_match') == 'not_established':
                relation = 'context'
                reason = '동작 자체는 미확인 · 제품 상태/사용 상황으로만 배치. ' + reason
            if shot_id in context and relation == 'direct':
                relation = 'context'
                reason = '보조 상황 장면 · 핵심 동작의 증거로 사용하지 않음. ' + reason
            options.append({'shot_id': shot_id, 'relation': relation, 'reason': reason})
            if option.get('action_match') in {'supports', 'not_established', 'not_applicable'}:
                options[-1]['action_match'] = option['action_match']
            used.add(shot_id)
            if len(options) == 6:
                break
        status = 'ranked' if options else 'fallback'
        if not options:
            # Preserve editability without pretending an unranked/undescribed shot
            # proves the narration. Initial cyclic options never enter the prompt.
            pool = grounded or [s for s in catalog if not observations[s['id']].get('selection_exclusion')]
            pool = [s for s in pool if s['id'] not in excluded_shots]
            if not pool and opposite:
                status = 'opposite_only'
            elif not pool:
                status = 'no_usable_scenes'
            for offset in range(min(3, len(pool))):
                shot = pool[(index + offset) % len(pool)]
                reason = ('장면 의미 순위를 확보하지 못해 임시 배치했습니다. 대본 일치 여부는 미확인입니다.'
                          if grounded else UNOBSERVED + ' 임시 배치 장면입니다.')
                options.append({'shot_id': shot['id'], 'relation': 'illustration', 'reason': reason})
        emphasis = row.get('emphasis')
        choices[beat['id']] = {'options': options, 'analysis_status': status,
            'promoted_subject_reference':row.get('promoted_subject_reference') if type(row.get('promoted_subject_reference')) is bool else None,
            'opposite_shot_ids': sorted(opposite),
            'incompatible_subject_shot_ids':sorted(incompatible),
            'emphasis': emphasis if status == 'ranked' and type(emphasis) is int and emphasis in (0, 1, 2) else 0,
            'emphasis_reason': str(row.get('emphasis_reason') or '')[:400] if status == 'ranked' else ''}
    return observations, choices
