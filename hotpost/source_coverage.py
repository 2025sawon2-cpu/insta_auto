"""Count actual usable time and reviewed core footage, independently of file count."""
import math


def positive_seconds(value):
    try:
        seconds = float(value)
        return seconds if math.isfinite(seconds) and seconds > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def usable_intervals(source):
    duration = positive_seconds((source.get('video_meta') or {}).get('duration') or source.get('duration'))
    if not duration:
        return []
    if 'reviewed_intervals' not in source:
        # Unapproved overlay footage cannot contribute its full duration.
        return [] if source.get('blur_required') else [(0.0, duration)]
    spans = []
    for row in source.get('reviewed_intervals') or []:
        try:
            start, end = float(row['source_start']), float(row['source_end'])
        except (TypeError, ValueError, KeyError):
            continue
        if math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration + .001:
            spans.append((start, min(end, duration)))
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def usable_seconds(source):
    return sum(end - start for start, end in usable_intervals(source))


def footage_coordinates(source):
    """Map reviewed derivative time to its parent; filenames are not identity."""
    interval = source.get('original_interval') or {}
    duration = positive_seconds((source.get('video_meta') or {}).get('duration') or source.get('duration'))
    try:
        start, end = float(interval['start']), float(interval['end'])
    except (KeyError, ValueError, TypeError):
        return None
    if not (source.get('original_sha256') and duration and math.isfinite(start)
            and math.isfinite(end) and 0 <= start < end):
        return None
    # Deliberate retiming needs a hash-bound recipe, not a guessed duration map.
    retiming=source.get('retiming') or {}
    rate=positive_seconds(retiming.get('playback_rate')) if retiming else 1
    if retiming and not (source.get('sha256') and .25<=rate<=2 and retiming.get('method')=='ffmpeg-setpts'
            and retiming.get('source_sha256')==source.get('sha256')
            and retiming.get('original_sha256')==source.get('original_sha256')
            and retiming.get('full_decode_passed') is True):
        return None
    if abs(end - start - duration*rate) > max(.1, (end-start) * .01):
        return None
    return ('footage', source['original_sha256']), start, (end - start) / duration


def distinct_seconds(sources):
    groups = {}
    for i, source in enumerate(sources):
        coordinates = footage_coordinates(source)
        if coordinates:
            key, offset, scale = coordinates
        else:
            key, offset, scale = ('footage', source.get('sha256') or ('missing', i)), 0, 1
        groups.setdefault(key, []).extend((offset + start * scale, offset + end * scale)
                                         for start, end in usable_intervals(source))
    total = 0.0
    for spans in groups.values():
        merged = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        total += sum(end - start for start, end in merged)
    return total


def reviewed_core(source):
    review = source.get('functional_review') or {}
    return bool(source.get('source_role') != 'context_only' and review.get('reviewed') is True
                and review.get('same_core_function') is True and review.get('observed_actions')
                and review.get('evidence_frames') and review.get('source_sha256') == source.get('sha256'))


def output_duration(state, policy):
    voice = next((v for v in state.get('voices', []) if v.get('id') == state.get('voice_id')
                  and v.get('script_id') == state.get('script_id')), {})
    duration = positive_seconds(voice.get('duration'))
    if duration:
        return duration, 'voice'
    duration = positive_seconds(state.get('reference_duration') or (state.get('reference_meta') or {}).get('duration'))
    if duration:
        return duration, 'reference'
    return positive_seconds(policy.get('fallback_output_seconds')) or 30.0, 'fallback'


def coverage_goal(sources, state, policy):
    duration, basis = output_duration(state, policy)
    required = duration * (positive_seconds(policy.get('coverage_ratio')) or 1.25)
    seconds = distinct_seconds(sources)
    core_seconds = distinct_seconds([s for s in sources if reviewed_core(s)])
    core_required = min(duration, positive_seconds(policy.get('core_min_seconds')) or 4.0)
    return {'usable_seconds': round(seconds, 2), 'required_seconds': round(required, 2),
            'output_seconds': round(duration, 2), 'duration_basis': basis,
            'duration_ready': seconds + .001 >= required,
            'core_seconds': round(core_seconds, 2), 'core_required_seconds': round(core_required, 2),
            'core_ready': core_seconds + .001 >= core_required,
            'time_identity_basis': 'parent_sha256_intervals_or_file_sha256',
            'visual_repeat_detection_complete': False,
            'scene_coverage': {'core': core_seconds + .001 >= core_required,
                               'context_sources': sum(s.get('source_role') == 'context_only' for s in sources)}}
