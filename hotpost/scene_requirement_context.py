"""Bind scene requirements to the selected narration and its actual saved plan.

This reads local artifacts only. It neither invents beat text nor promotes a
generic functional approval into proof of a particular narrated product part.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .source_quality import sha256_file
from .product_appeal_review import PRODUCT_APPEAL_INSTRUCTION


POLICY = 'selected-narration-product-context-v3-proof-mode'
SCENE_CONTEXT_INSTRUCTION = (
    'Read narration_context.selected_narration.text and each requirement_contexts '
    'target/before/after as one connected narration, not an isolated issue phrase. '
    'Resolve ownership, pronouns, whole versus part, object type, and the narrated '
    'problem/action/result from the approved script and original_product_evidence. '
    'A scene showing a separate accessory beside a product does not establish that '
    'accessory is the narrated product\'s own edge or part. For example, when the '
    'script says this MAT has an L-shaped end, a separate narrow transparent gap '
    'strip next to a wide mat cannot be labelled that mat\'s end without visible '
    'or reference-grounded evidence of their actual structural connection. '
    'An installation or cleaning cut of the actual relevant product may support '
    'a narrated falling-seed problem; it need not literally depict falling seeds. '
    'Compare its contribution to product appeal in the connected narration and '
    'the supplied source_function_limits, without claiming unseen seeds or motion. '
    'same_core_function=true is broad prior review, not proof of this particular '
    'part, installation relationship, or action; preserve context-only usage limits '
    'and inspect stated differences and observations. Treat the selected edit or fresh '
    'analysis and its existing shot choices as context, not proof that they are correct. '
    'Accept a similar working mechanism with minor color/material/design variations '
    'when the narrated structure and action remain consistent; do not require exact '
    'SKU, brand, or identity. Do not demand independent proof of ordinary reference '
    'features already supplied, and do not rewrite narration to fit available footage. '
    'If narration_context.verified is false, hold rather than infer missing context. '
    'An unclear whole/part relationship cannot be approved as a direct demonstration '
    'of that part, but can be honest supportive context if its use limits allow it. '
    'Determine the visual proof obligation of the actual target beat, not all actions '
    'that happen elsewhere in the source or neighboring narration. A noun introduction '
    'or product-form correction can use a reviewed product_support appearance frame; '
    'do not turn it into a required full action or completed-state sequence. In contrast, '
    'a directly demonstrated transition, result, or structural claim must retain every '
    'critical state needed to prove it. Existing ranked context is not a direct-action claim. '
    + PRODUCT_APPEAL_INSTRUCTION
)


def _text_sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _spoken_text(text):
    # Beat segmentation may omit punctuation and spacing, never spoken words.
    return ''.join(char for char in str(text or '') if char.isalnum()).casefold()


def _expected_spoken_text(state, text):
    run = next((r for r in state.get('runs', []) if r.get('id') == state.get('run_id')), {})
    for pair in run.get('inputs', {}).get('pronunciations', []):
        if isinstance(pair.get('from'), str) and isinstance(pair.get('to'), str):
            text = text.replace(pair['from'], pair['to'])
    return text


def _record(rows, identity):
    return next((row for row in rows or [] if isinstance(row, dict) and row.get('id') == identity), {})


def _beat_row(beat, shots):
    shot = shots.get(beat.get('selected_shot_id'), {})
    return {**{key:beat.get(key) for key in ('id', 'text', 'start', 'end')},
        'selected_shot_id':beat.get('selected_shot_id'),
        'selected_source_id':shot.get('source_id'),
        'selected_source_sha256':shot.get('sha256'),
        'failed_cut_source_start':beat.get('source_start'),
        'failed_cut_source_end':beat.get('source_end')}


def build_scene_requirement_context(state, requirements):
    """Return hash-bound, explicit missing/mismatched context without model calls."""
    holds = []
    script_id = state.get('script_id')
    script = _record(state.get('scripts'), script_id)
    text = script.get('text')
    text = text if isinstance(text, str) else ''
    text_sha = _text_sha(text)
    if not script_id or not text.strip():
        holds.append('selected_script_missing')
    if state.get('approved_script_id') != script_id or not script_id:
        holds.append('selected_script_not_approved')
    for key in ('sha256', 'script_sha256'):
        if script.get(key) and script[key] != text_sha:
            holds.append('selected_script_hash_mismatch')

    edit = _record(state.get('edits'), state.get('edit_id'))
    original_edit_id = state.get('edit_id')
    prepared = state.get('scene_narration_plan') or {}
    preparation_used = bool(edit.get('script_id') != script_id and prepared)
    if preparation_used:
        from .scene_narration_prepare import POLICY as PREPARATION_POLICY
        voice = _record(state.get('voices'), state.get('voice_id'))
        parent_path = Path(edit.get('plan_path') or '')
        voice_path = Path(voice.get('path') or '')
        if (prepared.get('policy') != PREPARATION_POLICY or prepared.get('script_id') != script_id
                or prepared.get('old_edit_id') != original_edit_id
                or not parent_path.is_file() or prepared.get('old_plan_sha256') != sha256_file(parent_path)
                or prepared.get('script_sha256') != text_sha
                or prepared.get('voice_id') != state.get('voice_id')
                or prepared.get('voice_sha256') != voice.get('sha256')
                or not voice_path.is_file() or sha256_file(voice_path) != voice.get('sha256')
                or voice.get('script_id') != script_id
                or (voice.get('spoken_text') is not None and _spoken_text(voice['spoken_text'])
                    != _spoken_text(_expected_spoken_text(state, text)))):
            holds.append('prepared_narration_identity_mismatch')
        edit = prepared
    path = Path(edit.get('plan_path') or '')
    plan, plan_sha = {}, None
    if not edit:
        holds.append('selected_edit_missing')
    if path.is_file():
        try:
            raw = path.read_bytes()
            plan_sha = hashlib.sha256(raw).hexdigest()
            parsed = json.loads(raw.decode('utf-8'))
            if isinstance(parsed, dict):
                plan = parsed
            else:
                holds.append('selected_plan_invalid')
        except (OSError, UnicodeError, ValueError):
            holds.append('selected_plan_unreadable')
    else:
        holds.append('selected_plan_missing')
    if edit.get('plan_sha256') and edit['plan_sha256'] != plan_sha:
        holds.append('selected_plan_hash_mismatch')
    if edit.get('script_id') != script_id or plan.get('script_text') != text:
        holds.append('selected_plan_narration_mismatch')
    priority = plan.get('narration_priority') or {}
    if priority.get('script_id') and priority['script_id'] != script_id:
        holds.append('selected_plan_script_id_mismatch')
    if priority.get('script_sha256') and priority['script_sha256'] != text_sha:
        holds.append('selected_plan_script_hash_mismatch')
    for voice_key in ('voice_source', 'voice'):
        voice = plan.get(voice_key) or {}
        if voice.get('script_id') and voice['script_id'] != script_id:
            holds.append('selected_plan_voice_script_mismatch')

    beats = [beat for beat in plan.get('beats', []) if isinstance(beat, dict)]
    if not beats:
        holds.append('selected_plan_beats_missing')
    if len({beat.get('id') for beat in beats}) != len(beats):
        holds.append('selected_plan_beat_ids_ambiguous')
    if any(not isinstance(beat.get('text'), str) or not beat['text'].strip() for beat in beats):
        holds.append('selected_plan_beat_narration_missing')
    if _spoken_text(' '.join(str(beat.get('text') or '') for beat in beats)) != _spoken_text(text):
        holds.append('selected_plan_beat_narration_mismatch')
    shots = {shot.get('id'):shot for shot in plan.get('shots', []) if isinstance(shot, dict)}
    rows = [_beat_row(beat, shots) for beat in beats]
    contexts = []
    for index, requirement in enumerate(requirements):
        beat_id = requirement.get('beat_id')
        positions = [i for i, row in enumerate(rows) if row['id'] == beat_id] if beat_id else list(range(len(rows)))
        if beat_id and len(positions) != 1:
            holds.append('required_beat_not_in_selected_plan:' + str(beat_id))
        target = [rows[i] for i in positions]
        before = rows[max(0, positions[0] - 2):positions[0]] if positions else []
        after = rows[positions[-1] + 1:positions[-1] + 3] if positions else []
        connected = ' '.join(str(row.get('text') or '') for row in [*before, *target, *after])
        contexts.append({'index':index, 'kind':requirement.get('kind'), 'beat_id':beat_id,
            'issue':requirement.get('reason'), 'narration':' '.join(str(row.get('text') or '') for row in target),
            'before':before, 'target':target, 'after':after,
            'context_text':connected, 'context_sha256':_text_sha(connected),
            'source':'actual_selected_edit_plan'})

    original = state.get('reviewed_original_text') or state.get('original_text') or ''
    original = original if isinstance(original, str) else ''
    if not original.strip():
        holds.append('original_product_evidence_missing')
    reference_path = Path(state.get('reference_video') or '')
    reference_sha = sha256_file(reference_path) if reference_path.is_file() else None
    function_limits = []
    for source in state.get('sources', []):
        review = source.get('functional_review') or {}
        function_limits.append({'source_id':source.get('id'), 'source_sha256':source.get('sha256'),
            'source_role':source.get('source_role'),
            'review_hash_bound':bool(review.get('reviewed') is True and source.get('sha256')
                                     and review.get('source_sha256') == source['sha256']),
            **{key:review.get(key) for key in ('same_core_function', 'context_usable', 'observed_actions',
                'matched_reference_features', 'differences', 'context_usage_limits', 'usage_limits', 'reason')},
            'source_usage_limits':source.get('usage_limits')})

    holds = list(dict.fromkeys(holds))
    value = {'policy':POLICY, 'verified':not holds, 'holds':holds,
        'selected_narration':{'script_id':script_id, 'approved_script_id':state.get('approved_script_id'),
                              'text':text, 'sha256':text_sha},
        'selected_edit':{'id':edit.get('id') or state.get('edit_id'), 'plan_path':str(path) if edit.get('plan_path') else None,
            'plan_sha256':plan_sha, 'script_binding_verified':not any('plan_' in reason or 'script_' in reason or 'prepared_' in reason for reason in holds),
            'existing_selection_role':'fresh_analysis_not_candidate_approval' if preparation_used else 'failed_context_not_candidate_approval',
            'original_failed_edit_id':original_edit_id if preparation_used else None},
        'original_product_evidence':{'text':original, 'text_sha256':_text_sha(original),
            'product_label':state.get('product'), 'title':state.get('title'),
            'reference_video_sha256':reference_sha},
        'requirement_contexts':contexts, 'source_function_limits':function_limits}
    value['signature'] = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    return value
