"""Exact body-source requirements, separate from inventory and model opinion."""
from __future__ import annotations

import copy
import math
import hashlib
import json

VERSION = 'minimum-five-sources-v1'


def _merged_windows(windows):
    merged=[]
    for start,end in sorted(windows):
        if merged and start<=merged[-1][1]+.000001:merged[-1][1]=max(merged[-1][1],end)
        else:merged.append([start,end])
    return [[round(a,6),round(b,6)] for a,b in merged]


def inventory_material(state):
    """Only hash-verified, related, approved physical windows establish progress."""
    from .source_coverage import reviewed_related,usable_intervals,footage_coordinates
    material={}
    for source in state.get('sources',[]):
        if not reviewed_related(source):continue
        sha=source['sha256'];parent=source.get('original_sha256') or sha
        windows=usable_intervals(source)
        coordinates=footage_coordinates(source)
        if coordinates:
            _,offset,scale=coordinates
            parent_windows=[(offset+a*scale,offset+b*scale) for a,b in windows]
        elif parent==sha:parent_windows=windows
        else:parent_windows=[]  # Invalid lineage cannot invent reviewed parent time.
        key=(sha,parent)
        row=material.setdefault(key,{'sha256':sha,'parent_sha256':parent,
            'source_windows':[],'parent_windows':[]})
        row['source_windows']+=windows;row['parent_windows']+=parent_windows
    for row in material.values():
        row['source_windows']=_merged_windows(row['source_windows'])
        row['parent_windows']=_merged_windows(row['parent_windows'])
    return sorted(material.values(),key=lambda r:(r['sha256'],r['parent_sha256']))


def inventory_signature(state):
    """Review timestamps, prose, IDs and duplicate records do not change footage."""
    material=inventory_material(state)
    return hashlib.sha256(json.dumps(material,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def new_inventory_material(baseline,current):
    """Require a new related parent or positively larger reviewed window union."""
    if not isinstance(baseline,list) or not baseline:return False
    def valid(row):
        if not isinstance(row,dict) or not all(isinstance(row.get(k),str) and row[k]
                for k in ('sha256','parent_sha256')):return False
        for key in ('source_windows','parent_windows'):
            windows=row.get(key)
            if not isinstance(windows,list):return False
            for window in windows:
                if (not isinstance(window,(list,tuple)) or len(window)!=2
                        or not all(isinstance(n,(int,float)) and not isinstance(n,bool) and math.isfinite(n) for n in window)
                        or not 0<=window[0]<window[1]):return False
        return bool(row['source_windows'])
    if not all(valid(row) for row in baseline):return False
    def unseen(windows,old):
        old=_merged_windows(old)
        return any(not any(a-.000001<=start and end<=b+.000001 for a,b in old)
                   for start,end in windows)
    for row in current:
        same_file=[r for r in baseline if r['sha256']==row['sha256']]
        if same_file:
            if unseen(row['source_windows'],[w for r in same_file for w in r['source_windows']]):return True
            continue
        same_parent=[r for r in baseline if r['parent_sha256']==row['parent_sha256']
                     or r['sha256']==row['parent_sha256']]
        if not same_parent:return True
        if row['parent_windows'] and unseen(row['parent_windows'],[w for r in same_parent for w in r['parent_windows']]):
            return True
    return False


def acquisition_policy(state, policy):
    result=copy.deepcopy(policy)
    gap=state.get('source_diversity_gap') or {}
    if gap:
        result['acquisition_parent_target']=max(5,gap.get('baseline_parent_count',0)+1)
    return result


class SourceDiversityRequired(ValueError):
    def __init__(self, message, diagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics


def checked_policy(value):
    if value is None:return None
    if (not isinstance(value, dict) or value.get('version') != VERSION
            or type(value.get('minimum_parent_sources')) is not int
            or value['minimum_parent_sources'] < 5):
        raise ValueError('알 수 없거나 완화된 최소 원본 사용 정책입니다.')
    return copy.deepcopy(value)


def policy_for_state(state):
    # A selected saved run is authoritative, including the absence of a policy.
    run = next((r for r in state.get('runs', []) if r.get('id') == state.get('run_id')), None)
    source_policy = run.get('source_policy', {}) if run is not None else state.get('source_policy', {})
    if source_policy is None:
        raise ValueError('명시된 수집 정책이 비어 있습니다.')
    if 'source_diversity_policy' in source_policy and source_policy['source_diversity_policy'] is None:
        raise ValueError('명시된 최소 원본 사용 정책이 비어 있습니다.')
    return checked_policy((source_policy or {}).get('source_diversity_policy'))


def parent_identity(source):
    value = source.get('original_sha256') or source.get('sha256')
    return value.strip() if isinstance(value, str) and value.strip() else None


def parent_groups(sources):
    """Same actual bytes remain one source even with conflicting lineage tags."""
    aliases = {}
    def root(key):
        while aliases.get(key,key) != key:key=aliases[key]
        return key
    for source in sources:
        parent, actual = parent_identity(source), source.get('sha256')
        if not parent or not actual:continue
        a,b=root(parent),root(actual)
        if a!=b:aliases[max(a,b)] = min(a,b)
    return {s['id']:root(parent_identity(s)) for s in sources if parent_identity(s) and s.get('sha256')}


def body_usage_report(plan):
    if 'source_diversity_policy' in plan and plan['source_diversity_policy'] is None:
        raise ValueError('명시된 최소 원본 사용 정책이 비어 있습니다.')
    policy = checked_policy(plan.get('source_diversity_policy'))
    minimum = policy['minimum_parent_sources'] if policy else 0
    sources = {s['id']:s for s in plan.get('sources', [])}
    shots = {s['id']:s for s in plan.get('shots', [])}
    groups = parent_groups(list(sources.values()))
    fps = float(plan.get('fps', 30))
    if not math.isfinite(fps) or fps <= 0:raise ValueError('본문 프레임 속도가 올바르지 않습니다.')
    frames = {};used_source_ids=set()
    for beat in plan.get('visual_cuts') or plan.get('beats', []):
        shot = shots.get(beat.get('selected_shot_id'))
        source = sources.get(shot.get('source_id')) if shot else None
        key = groups.get(source['id']) if source else None
        if not key:continue
        try:
            a, b = float(beat['start']), float(beat['end'])
            x, z = float(beat['source_start']), float(beat['source_end'])
        except (KeyError, TypeError, ValueError):continue
        if not all(math.isfinite(v) for v in (a,b,x,z)) or not 0 <= a < b or not 0 <= x < z:continue
        # The first output frame is the cover, not an additional body source.
        start, end = max(1, round(a*fps)), round(b*fps)
        count = max(0, end-start)
        if count:
            frames[key] = frames.get(key, 0)+count
            used_source_ids.add(source['id'])
    total = sum(frames.values())
    report = {'policy':copy.deepcopy(policy), 'enforced':policy is not None,
            'minimum_parent_sources':minimum, 'used_parent_sources':len(frames),
            'parent_sha256s':sorted(frames), 'shortfall':max(0,minimum-len(frames)),
            'used_source_ids':sorted(used_source_ids),
            'source_frames':frames, 'source_seconds':{k:v/fps for k,v in frames.items()},
            'maximum_source_share':max(frames.values())/total if total else 0.0}
    from .source_core_priority import usage_report
    return usage_report(plan,report)


def require_body_minimum(plan, *, expected_policy=None):
    expected = checked_policy(expected_policy)
    report = body_usage_report(plan)
    if expected is not None and report['policy'] != expected:
        raise SourceDiversityRequired('현재 제작의 최소 원본 사용 정책이 편집 계획에 결속되지 않았습니다.',
                                      {**report, 'reason':'policy_mismatch', 'expected_policy':expected})
    if report['enforced'] and report['shortfall']:
        raise SourceDiversityRequired(
            f"본문 사용 원본 {report['used_parent_sources']}/{report['minimum_parent_sources']}개 · 적합한 다른 원본 장면이 필요합니다.",
            {**report, 'reason':'insufficient_selected_parents'})
    from .source_core_priority import require_usage
    require_usage(plan,report)
    return report
