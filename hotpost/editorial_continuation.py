"""Extend a real source cut at normal speed after an explicit duration gap.

An editorial cut boundary is not the end of its original file. The adjacent
frames are reviewed once and accepted through the normal source reviewers;
old scopes and failure receipts remain intact.
"""
import copy
import hashlib
import json
import math
import time
from pathlib import Path

from .editing_adapter import _atomic_json
from .source_coverage import usable_intervals
from .source_quality import editing_ready, sha256_file

POLICY = 'normal-speed-adjacent-source-v1'


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def extension_scope(source, shot, seconds, fps=30):
    """Use subsequent real frames, shifting earlier only at the file's end."""
    if (source.get('manual_usage_review') or {}).get('editing_eligible') is False:
        return None
    duration = (source.get('video_meta') or {}).get('duration', source.get('duration'))
    if not all(type(v) in (int, float) and math.isfinite(v)
               for v in (duration, seconds, fps)) or duration <= 0 or seconds <= 0 or fps <= 0:
        return None
    # One extra decoded frame protects independently rounded render boundaries.
    required = math.ceil(seconds * fps - 1e-8) / fps
    needed = min(duration, required + 1 / fps)
    start, end = float(shot['start']), float(shot['end'])
    if needed <= end - start + 1e-8:
        return None
    if required > duration + 1e-8:
        return None  # The caller must connect a different real cut.
    end = min(duration, max(end, start + needed))
    start = max(0., min(start, end - needed))
    denied = (source.get('source_interval_withdrawal') or {}).get('intervals', [])
    if any(max(start, w['source_start']) < min(end, w['source_end']) for w in denied):
        return None
    spans = sorted([list(w) for w in usable_intervals(source)] + [[start, end]])
    merged = []
    for a, z in spans:
        if merged and a <= merged[-1][1] + 1e-8:
            merged[-1][1] = max(merged[-1][1], z)
        else:
            merged.append([a, z])
    return {'start': start, 'end': end, 'intervals': merged,
            'requested_duration': seconds, 'normal_speed': True}


def review_extension(settings, source, scope, root, review, *, check=lambda: None,
                     generate=None):
    """No same-scope content retries; service waits retain their own semantics."""
    from .source_overlay_review import review_source_overlays, _fresh_explicit_reviews
    from .model_service import ModelServiceUnavailable
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    binding = {'policy': POLICY, 'source_sha256': source['sha256'], 'scope': scope,
               'prior_source_review_sha256': identity(source)}
    receipt = root / ('extension-' + identity(binding) + '.json')
    if sha256_file(Path(source['path'])) != source['sha256']:
        raise ValueError('Adjacent source file changed')
    if receipt.exists():
        saved = json.loads(receipt.read_text('utf8'))
        if saved.get('binding') != binding:
            raise ValueError('Adjacent source review binding changed')
        if saved.get('status') == 'accepted':
            candidate = saved['source']
            if sha256_file(Path(candidate['path'])) != candidate['sha256']:
                raise ValueError('Accepted adjacent source file changed')
            from .source_overlay_review import accepted_interval_frames
            from .source_presentation import valid_review
            accepted_interval_frames(candidate)
            if not editing_ready(candidate) or not valid_review(candidate):
                raise ValueError('Accepted adjacent source evidence no longer valid')
            for frame in candidate['presentation_review']['evidence_frames']:
                if sha256_file(Path(frame['path'])) != frame['sha256']:
                    raise ValueError('Accepted adjacent portrait evidence changed')
            return copy.deepcopy(candidate)
        if saved.get('status') != 'service_wait':
            return None
    saved = {'binding': binding, 'status': 'started', 'started': time.time()}
    check()
    _atomic_json(receipt, saved)
    try:
        candidate = review_source_overlays(settings, source, root / identity(binding),
                                          intervals=scope['intervals'], generate=generate)
        approved = usable_intervals(candidate)
        previous = usable_intervals(source)
        if not all(any(a <= x and z <= b for a, b in approved) for x, z in previous):
            saved.update(status='rejected', reason='Prior approved scope would be lost')
        elif not any(a <= scope['start'] and scope['end'] <= b for a, b in approved):
            saved.update(status='rejected', reason='Actual adjacent scope was not approved')
        else:
            _fresh_explicit_reviews(source, candidate)
            candidate['interval_function_review_required'] = sorted([
                [w['source_start'], w['source_end']] for w in candidate['reviewed_intervals']])
            check()
            candidate = review(candidate)
            if sha256_file(Path(candidate['path'])) != candidate['sha256']:
                raise ValueError('Adjacent source changed during visual review')
            if editing_ready(candidate):
                from .source_overlay_review import accepted_interval_frames
                from .source_presentation import valid_review
                accepted_interval_frames(candidate)
                if not valid_review(candidate):
                    raise ValueError('Adjacent portrait evidence does not match accepted scope')
                for frame in candidate['presentation_review']['evidence_frames']:
                    if sha256_file(Path(frame['path'])) != frame['sha256']:
                        raise ValueError('Adjacent portrait evidence changed during review')
                candidate.setdefault('editorial_extension_history', []).append({
                    **binding, 'receipt_path': str(receipt.resolve())})
                saved.update(status='accepted', source=copy.deepcopy(candidate))
            else:
                saved.update(status='rejected', reason='Normal function/portrait review did not accept continuation')
    except ModelServiceUnavailable:
        saved.update(status='service_wait', finished=time.time())
        _atomic_json(receipt, saved)
        raise
    except Exception as exc:
        saved.update(status='failed', reason=str(exc), finished=time.time())
        _atomic_json(receipt, saved)
        raise
    saved['finished'] = time.time()
    _atomic_json(receipt, saved)
    return copy.deepcopy(saved['source']) if saved['status'] == 'accepted' else None
