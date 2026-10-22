"""Count actual usable time and reviewed core footage, independently of file count."""
import math


def diversity_required(policy):
    return (policy.get('version') in (5,6) and
            (policy.get('source_diversity_policy') or {}).get('version')=='minimum-five-sources-v1')


def query_receipts_only(state,job,goal):
    """An already usable inventory only needs its outstanding text receipts."""
    from .scene_requirements import required_scenes
    quality=state.get('daily_quality') or {}
    scenes=quality.get('scene_requirements') or {}
    policy=(job.get('payload') or {}).get('source_policy') or state.get('source_policy') or {}
    return bool(policy.get('search_minimums') and state.get('automation',{}).get('active')
        and job.get('kind')=='collect_sources' and not job.get('payload',{}).get('daily_quality_repair')
        and not str(state.get('source_search_brief') or '').strip()
        and not state.get('source_diversity_gap') and not required_scenes(state)
        and not (scenes and not scenes.get('ready'))
        and goal.get('source_diversity_ready') and goal.get('core_ready')
        and goal.get('core_priority_ready',True)
        and not goal.get('selection_recovery_required'))


def parent_identity(source):
    """A malformed trim must not manufacture extra originals either."""
    return source.get('original_sha256') or source.get('sha256')


def parent_aliases(sources):
    """Union actual-file aliases before counting declared parent originals."""
    roots={}
    def find(value):
        roots.setdefault(value,value)
        if roots[value]!=value:roots[value]=find(roots[value])
        return roots[value]
    for source in sources:
        sha=source.get('sha256');parent=parent_identity(source)
        if not sha or not parent:continue
        a,b=find(sha),find(parent)
        roots[max(a,b)]=min(a,b)
    return {sha:find(sha) for sha in roots}


def search_query_identity(query):
    from .source_search.strategy import normalize_query, query_fingerprint
    import re
    # Index operators and platform repetition do not create a new subject query.
    body=re.sub(r'(?:site:|inurl:)\S+','',normalize_query(query))
    return re.sub(r'\s+','',query_fingerprint(body))


def actual_search_coverage(rows, minimums,search_identity=None):
    """Only explicit submitted/matching content evidence counts for the new run."""
    from .source_queries import language
    from .source_attempts import search_execution
    from .source_query_identity import query_identity
    # New worker receipts carry the independently reviewed identity. Old saved
    # runs without it retain their historical counting contract.
    if search_identity is None:
        search_identity=next((r['search_identity'] for r in reversed(rows or [])
            if isinstance(r,dict) and r.get('search_identity') is not None),None)
    seen=set();topic_surfaces=set();queries={lang:[] for lang in minimums}
    for row in rows or []:
        if isinstance(row,dict) and row.get('search_purpose')=='support':continue
        if not isinstance(row,dict) or row.get('language')=='image' or row.get('status') not in {'results','no_results'}:continue
        execution=search_execution(row)
        if not (execution['query_submitted'] and execution['query_url_matched'] and execution['consumed']):continue
        query=str(row.get('query') or '');lang=language(query);profile=search_identity
        # Different collection rounds may have distinct independently reviewed
        # pools. Keep genuine earlier topic intents only for the SAME original
        # media/text, never by accepting a broad unreviewed query today.
        previous=row.get('search_identity')
        if (isinstance(profile,dict) and profile.get('version')=='reviewed-topic-discovery-v1'
                and isinstance(previous,dict) and previous.get('version')==profile['version']):
            if not all(previous.get(k)==profile.get(k) for k in ('topic_reference_sha256','topic_text_sha256')):
                continue
            from .source_query_identity import checked_identity
            try:profile=checked_identity(previous)
            except (ValueError,TypeError,KeyError):continue
        identity=query_identity(query,profile)
        if lang not in queries or not identity or identity in seen:continue
        if isinstance(profile,dict) and profile.get('version')=='reviewed-topic-discovery-v1':
            import re
            compact=''.join(re.findall(r'[a-z0-9\u3400-\u9fff가-힣]',query.casefold()))
            tokens='|'.join(sorted(set(re.findall(r'[a-z0-9]+|[\u3400-\u9fff]+|[가-힣]+',query.casefold()))))
            keys={(lang,'compact',compact),(lang,'tokens',tokens)}
            if topic_surfaces.intersection(keys):continue
            topic_surfaces.update(keys)
        queries[lang].append({'query':query,'identity':identity,'provider':row.get('provider'),
                             'status':row['status'],'execution_basis':execution['basis']})
        seen.add(identity)
    return {lang:{'minimum':minimum,'count':len(queries[lang]),
                  'ready':len(queries[lang])>=minimum,'queries':queries[lang]}
            for lang,minimum in minimums.items()}


def current_search_rows(state):
    rows=(state.get('source_acquisition') or {}).get('queries',[])
    run_id=state.get('run_id')
    scope=search_scope_for_state(state)
    return [r for r in rows if isinstance(r,dict) and (not run_id or r.get('run_id')==run_id)
            and r.get('search_context')==scope]


def bind_search_rows(rows, run_id, search_context):
    """Bind newly observed rows; explicit historical provenance is immutable."""
    import copy
    result=copy.deepcopy(rows or [])
    if not isinstance(search_context,dict) or not search_context:return result
    for row in result:
        if isinstance(row,dict) and 'run_id' not in row and 'search_context' not in row:
            row.update(run_id=run_id,search_context=copy.deepcopy(search_context))
    return result


def search_scope_for_state(state):
    import hashlib
    from pathlib import Path
    from .source_quality import sha256_file
    from .source_search.strategy import normalize_query
    path=Path(state.get('reference_video') or '__missing__')
    return {'reference_sha256':sha256_file(path) if path.is_file() else state.get('reference_sha256'),
            'product':normalize_query(state.get('product') or ''),
            'reference_text_sha256':hashlib.sha256((state.get('reviewed_original_text') or state.get('original_text') or '').encode()).hexdigest()}


def reviewed_related(source):
    from .source_quality import editing_ready,sha256_file
    from pathlib import Path
    review=source.get('functional_review') or {}
    valid=bool(parent_identity(source) and editing_ready(source) and usable_seconds(source)>0
        and review.get('reviewed') is True and review.get('source_sha256')==source.get('sha256')
        and review.get('observed_actions') and review.get('evidence_frames')
        and (review.get('same_core_function') is True or
             review.get('context_usable') is True and review.get('context_usage_limits')))
    if not valid:return False
    try:return sha256_file(Path(source.get('path') or '__missing__'))==source['sha256']
    except OSError:return False


def diversity_goal(sources,state,policy):
    from .source_core_priority import enabled, kind, priority_goal
    relevant=[s for s in sources if reviewed_related(s)]
    aliases=parent_aliases(relevant)
    parents={aliases[parent_identity(s)] for s in relevant}
    core={aliases[parent_identity(s)] for s in relevant
          if (kind(s,state)=='core_product' if enabled(policy) else reviewed_core(s))}
    minimum=max(5,(policy['source_diversity_policy']).get('minimum_parent_sources',5),
                policy.get('acquisition_parent_target',5))
    configured=policy.get('search_minimums') or {}
    search=actual_search_coverage(current_search_rows(state),{lang:max(5,configured.get(lang,5)) for lang in ('en','zh')})
    searches_ready=all(row['ready'] for row in search.values())
    result = {'related_parent_count':len(parents),'required_parent_sources':minimum,
            'related_source_ids':[s.get('id') for s in relevant],
            'related_parent_sha256':sorted(parents),'core_parent_count':len(core),
            'core_ready':len(core)>=policy.get('minimum_core_parent_sources',1),
            'source_diversity_ready':len(parents)>=minimum,'search_coverage':search,
            'search_ready':searches_ready,'ready':len(parents)>=minimum and bool(core) and searches_ready,
            'search_identity_scope':'unique_query_across_platforms_current_run_explicit_matching_result'}
    if enabled(policy):priority_goal(relevant,state,policy,result)
    return result


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
    result = {'usable_seconds': round(seconds, 2), 'required_seconds': round(required, 2),
            'output_seconds': round(duration, 2), 'duration_basis': basis,
            'duration_ready': seconds + .001 >= required,
            'core_seconds': round(core_seconds, 2), 'core_required_seconds': round(core_required, 2),
            'core_ready': core_seconds + .001 >= core_required,
            'time_identity_basis': 'parent_sha256_intervals_or_file_sha256',
            'visual_repeat_detection_complete': False,
            'scene_coverage': {'core': core_seconds + .001 >= core_required,
                               'context_sources': sum(s.get('source_role') == 'context_only' for s in sources)}}
    if (policy.get('editorial_policy') == 'normal-speed-editorial-v1'
            and policy.get('allow_source_reuse') is True):
        result.update(duration_requirement='preference', core_duration_requirement='preference',
                      duration_target_met=result['duration_ready'],
                      core_duration_target_met=result['core_ready'],
                      duration_ready=seconds > 0, core_ready=core_seconds > 0,
                      readiness_scope='reviewed_inventory_not_final_video_quality')
        result['scene_coverage']['core'] = core_seconds > 0
    if diversity_required(policy):
        result.update(diversity_goal(sources,state,policy))
        result['scene_coverage']['core']=result['core_ready']
    return result
