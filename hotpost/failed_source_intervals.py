"""Keep proven overlay defects attached to footage, even when a cut moves."""
import hashlib
import json
from pathlib import Path

POLICY = 'failed-overlay-source-interval-v1'


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _coordinates(source):
    from .source_coverage import footage_coordinates
    value = footage_coordinates(source)
    if value:
        key, offset, scale = value
        return key[1], offset, scale
    if source.get('original_sha256') or source.get('retiming'):
        raise ValueError('실패 구간의 파생 원본 시간 증거를 확인할 수 없습니다.')
    return source['sha256'], 0, 1


def _masks(source, start, end):
    return [{k:m.get(k) for k in ('rectangle','strength','expected_scale')}
            for m in source.get('watermark_masks', [])
            if max(start, m.get('source_start', 0)) < min(end, m.get('source_end', 0))]


def _new_approval(source, old_source, start, end):
    """A changed box alone is not repair; revalidate its independent receipt."""
    review = source.get('mask_review') or {}
    old = old_source.get('mask_review') or {}
    if (not review.get('proposal_sha256') or review.get('proposal_sha256') == old.get('proposal_sha256')
            or _hash(_masks(source,start,end)) == _hash(_masks(old_source,start,end))):
        return False
    try:
        from .source_overlay_review import _restore_review
        restored = _restore_review(source, Path(source.get('overlay_review_path') or '__missing__'),
                                 expected_scope=source.get('overlay_review_scope'))
        if not restored:
            return False
        approved = restored[0]
        return (approved.get('mask_review',{}).get('proposal_sha256') == review['proposal_sha256']
                and _hash(_masks(approved,start,end)) == _hash(_masks(source,start,end))
                and any(w['source_start'] <= start < end <= w['source_end']
                        for w in approved.get('reviewed_intervals',[])))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def attach(state, plan):
    """Export hash-bound rejected intervals to the selector; preserve all history."""
    from .source_quality import sha256_file
    edits = {e['id']: e for e in state.get('edits', [])}
    failures = []
    for review in state.get('daily_quality',{}).get('reviews',[]):
        issues = [i for i in review.get('issues',[]) if i.get('kind') == 'watermark']
        if review.get('passed') is not False or not issues:
            continue
        edit = edits.get(review.get('edit_id'), {})
        path = Path(edit.get('plan_path') or '__missing__')
        if not path.is_file() or sha256_file(path) != review.get('plan_sha256'):
            raise ValueError('실패 워터마크 검토와 실제 편집 계획 SHA가 다릅니다.')
        old_plan = json.loads(path.read_text('utf-8'))
        old_sources = {s['id']:s for s in old_plan.get('sources',[])}
        old_shots = {s['id']:s for s in old_plan.get('shots',[])}
        old_beats = {b['id']:b for b in [*old_plan.get('beats',[]),*old_plan.get('visual_cuts',[])]}
        for issue in issues:
            matches = [c for c in old_plan.get('rendered_clips',[])
                       if c.get('beat_id') == issue.get('beat_id') or
                       old_beats.get(c.get('beat_id'),{}).get('parent_beat_id') == issue.get('beat_id')]
            if not issue.get('beat_id') or not matches:
                raise ValueError('실패 워터마크의 실제 렌더 원본 구간 증거가 없습니다.')
            for clip in matches:
                old_source = old_sources[old_shots[clip['selected_shot_id']]['source_id']]
                start, end = clip['selected_source_window']
                if clip.get('source_sha256') != old_source['sha256'] or not 0 <= start < end:
                    raise ValueError('실패 워터마크의 실제 원본 SHA·구간이 다릅니다.')
                parent, offset, scale = _coordinates(old_source)
                failures.append(dict(source=old_source, source_sha256=parent,
                    start=offset+start*scale, end=offset+end*scale,
                    edit_id=edit['id'], plan_sha256=review['plan_sha256'], reason=issue['reason']))
    if not failures:
        return
    sources = {s['id']:s for s in plan.get('sources',[])}
    diagnostics = []
    for shot in plan.get('shots',[]):
        source = sources[shot['source_id']]
        parent, offset, scale = _coordinates(source)
        blocked = []
        for failure in failures:
            if parent != failure['source_sha256']:
                continue
            start, end = (failure['start']-offset)/scale, (failure['end']-offset)/scale
            if max(start,shot['start']) >= min(end,shot['end']):
                continue
            # Different derivatives cannot inherit another file's mask approval.
            if source['sha256'] == failure['source']['sha256'] and _new_approval(source,failure['source'],start,end):
                continue
            blocked.append({'start':start,'end':end,'edit_id':failure['edit_id'],
                            'plan_sha256':failure['plan_sha256'],'reason':failure['reason']})
        shot['failed_source_intervals'] = blocked
        if blocked:
            diagnostics.append({'shot_id':shot['id'],'source_sha256':parent,'intervals':blocked})
    plan['failed_source_interval_guard'] = {'policy':POLICY,'blocked':diagnostics}
