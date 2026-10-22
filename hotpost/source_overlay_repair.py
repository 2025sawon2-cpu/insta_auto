"""One evidence-bound re-review for copied frame identifiers, never guessed approval."""
import json
from pathlib import Path

from .editing_adapter import _atomic_json
from .source_mask_review import _fingerprint
from .source_review_status import ReviewResponseInvalid


def _preserve_denials(corrected, original, accepted):
    if not isinstance(corrected, dict) or not isinstance(corrected.get('intervals'), list):
        raise ReviewResponseInvalid('형식 재검토 응답 형식이 다릅니다.')
    if any(not isinstance(w, dict) or (w.get('source_start'),w.get('source_end')) not in accepted
           for w in corrected['intervals']):
        raise ReviewResponseInvalid('형식 재검토가 기존 미승인 구간을 새로 승인했습니다.')
    rejected = corrected.get('rejected_intervals', [])
    prior = original.get('rejected_intervals', [])
    if (not isinstance(rejected, list) or not isinstance(prior, list)
            or any(not isinstance(w,dict) for w in [*rejected,*prior])):
        raise ReviewResponseInvalid('형식 재검토의 거절 구간 형식이 다릅니다.')
    result = dict(corrected)
    prior_spans = {(w.get('source_start'),w.get('source_end')) for w in prior if isinstance(w,dict)}
    result['rejected_intervals'] = [*prior, *[w for w in rejected if isinstance(w,dict)
        and (w.get('source_start'),w.get('source_end')) not in prior_spans]]
    return result


def repair_frame_ids(generate, settings, instruction, data, media, review, output, index):
    proposal = data['proposal']
    evidence = proposal['evidence']
    # Foreign identity, geometry, new intervals and substantive denials are not
    # transport mistakes. Let the ordinary strict validator reject them.
    if (not isinstance(review, dict)
            or review.get('proposal_sha256') != proposal['proposal_sha256']
            or review.get('source_sha256') != evidence['source_sha256']
            or review.get('geometry') != evidence['geometry']
            or not isinstance(review.get('intervals'), list)):
        return review
    allowed = {(w['source_start'], w['source_end']) for w in data['review_scope']}
    seen, errors = set(), []
    for row in review['intervals']:
        if not isinstance(row, dict):return review
        span = (row.get('source_start'), row.get('source_end'))
        if span not in allowed or span in seen:return review
        seen.add(span)
        window = next(w for w in evidence['intervals'] if (w['source_start'], w['source_end']) == span)
        ids = [f['frame_id'] for f in evidence['frames'] if f['interval_index'] == window['index']]
        masks = [i for i, m in enumerate(proposal['watermark_masks']) if m['interval_index'] == window['index']]
        actual = row.get('frame_ids')
        if (row.get('coverage_confirmed') is not True or row.get('subject_visible') is not True
                or not masks and row.get('no_overlays_confirmed') is not True
                or row.get('mask_indices') != masks
                or not isinstance(actual, list) or len(actual) != len(ids)
                or not all(isinstance(i, str) for i in actual)):
            return review
        if sorted(actual) != sorted(ids):
            errors.append({'source_start':span[0], 'source_end':span[1],
                           'expected_frame_ids':ids, 'received_frame_ids':actual})
    if not errors:return review
    binding = {'proposal_sha256':proposal['proposal_sha256'],
               'original_response_sha256':_fingerprint(review), 'review_scope':data['review_scope'],
               'attached_frame_ids':data['attached_frame_ids']}
    root = Path(output)
    path = root/f'overlay-review-repair-{index+1:02}.json'
    marker = root/f'overlay-review-repair-{index+1:02}-attempt.json'
    if path.is_file():
        saved = json.loads(path.read_text('utf-8'))
        attempt = json.loads(marker.read_text('utf-8')) if marker.is_file() else {}
        if (saved.get('binding') != binding or attempt.get('binding') != binding
                or _fingerprint(saved.get('original_response')) != binding['original_response_sha256']
                or attempt.get('response_sha256') != _fingerprint(saved.get('review'))):
            raise ReviewResponseInvalid('형식 재검토 결속이 변경됐습니다.')
        return _preserve_denials(saved['review'],review,seen)
    if marker.is_file():
        saved = json.loads(marker.read_text('utf-8'))
        if saved.get('binding') != binding or saved.get('status') != 'service_wait':
            raise ReviewResponseInvalid('같은 근거의 형식 재검토가 이미 실행됐거나 응답이 미확정입니다.')
    _atomic_json(marker, {'binding':binding, 'status':'started', 'errors':errors})
    scope = [w for w in data['review_scope'] if (w['source_start'],w['source_end']) in seen]
    indices = {w['index'] for w in evidence['intervals'] if (w['source_start'],w['source_end']) in seen}
    frame_ids = [f['frame_id'] for f in evidence['frames'] if f['interval_index'] in indices]
    parts = [part for i in range(0,len(media),2)
             if json.loads(media[i]['text']).get('frame_id') in frame_ids for part in media[i:i+2]]
    try:
        corrected = generate(settings, instruction+
            ' The prior response copied frame identifiers incorrectly. Independently inspect the SAME '
            'attached images again; approval is NOT required. Preserve the exact source/proposal/geometry '
            'binding and return only exact identifiers from the supplied evidence. You may reject intervals. '
            'Review ONLY review_scope and attached_frame_ids. Previously rejected/unaccepted intervals '
            'must not be reconsidered or approved. Do not infer image content from the prior answer.',
            {**data, 'review_scope':scope, 'attached_frame_ids':frame_ids,
             'prior_response':review, 'identifier_errors':errors}, media=parts)
    except Exception as exc:
        from .model_service import ModelServiceUnavailable
        _atomic_json(marker, {'binding':binding, 'status':'service_wait' if isinstance(exc, ModelServiceUnavailable)
                             else 'failed', 'errors':errors, 'error':str(exc)[:1000]})
        raise
    _atomic_json(path, {'binding':binding, 'original_response':review, 'review':corrected})
    _atomic_json(marker, {'binding':binding, 'status':'received', 'errors':errors,
                         'response_sha256':_fingerprint(corrected)})
    return _preserve_denials(corrected,review,seen)
