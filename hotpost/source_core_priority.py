"""New-run core-product priority; scarcity requires current finite search evidence."""
import copy
import hashlib
import json
from pathlib import Path

VERSION = 'core-product-first-v1'
REVIEW_POLICY = 'visual-product-identity-v6'


def enabled(policy):
    return (policy or {}).get('version')==6 and (policy or {}).get('core_product_priority', {}).get('version') == VERSION


def state_policy(state):
    from .source_policy import run_policy
    return run_policy(state)


def context(state):
    from .source_coverage import search_scope_for_state
    return {'run_id':state.get('run_id'), **search_scope_for_state(state)}


def review_context(state):
    """Pixel identity review may survive a new run of the identical product/reference."""
    return {k:v for k,v in context(state).items() if k!='run_id'}


def recording_duplicate(left,right):
    """Near-identical sampled sequences + duration, not two similar product stills."""
    import math
    a=left.get('frame_hashes') or [];b=right.get('frame_hashes') or []
    x=(left.get('video_meta') or {}).get('duration');y=(right.get('video_meta') or {}).get('duration')
    if (len(a)<4 or len(a)!=len(b) or type(x) not in (int,float) or type(y) not in (int,float)
            or not all(math.isfinite(v) and v>0 for v in (x,y)) or abs(x-y)>max(.1,min(x,y)*.01)):
        return False
    try:matches=sum((int(i,16)^int(j,16)).bit_count()<=4 for i,j in zip(a,b))
    except (TypeError,ValueError):return False
    return matches>=math.ceil(.9*len(a))


def kind(source, state=None):
    review=source.get('functional_review') or {}
    if (review.get('policy') != REVIEW_POLICY or review.get('source_sha256') != source.get('sha256')
            or review.get('reviewed') is not True or not review.get('evidence_frames')
            or not review.get('observed_actions')):
        return 'unverified'
    if state is not None and review.get('core_product_context') != review_context(state):return 'unverified'
    if not provenance_matches(source,review):return 'unverified'
    # Product identity and proof of a particular narrated action are independent.
    # Reviewed views of the actual featured object/food count as that identity,
    # while context-only footage keeps its restrictions at scene allocation.
    if review.get('featured_product_identity') is True and (
            review.get('same_core_function') is True or
            review.get('context_usable') is True and review.get('context_usage_limits')):
        return 'core_product'
    if review.get('context_usable') is True and review.get('context_usage_limits'):
        return 'related_product' if review.get('same_core_function') is True else 'context'
    return 'unverified'


def provenance_matches(source,review):
    bound=review.get('candidate_provenance')
    return bound is None or all(bound.get(k,'')==source.get(k,'') for k in ('origin_url','source_title'))


def priority_goal(sources, state, policy, goal):
    from .source_coverage import parent_aliases, parent_identity
    aliases=parent_aliases(sources)
    core={aliases[parent_identity(s)] for s in sources if kind(s,state)=='core_product'}
    target=policy['core_product_priority']['target_parent_sources']
    fallback=(state.get('source_acquisition') or {}).get('core_fallback') or {}
    finite=(state.get('source_acquisition') or {}).get('core_search_plan') or {}
    fallback_valid=(fallback.get('context')==context(state) and fallback.get('reason')=='finite_core_search_exhausted'
                    and bool(fallback.get('exhausted_routes')) and bool(fallback.get('plan_sha256'))
                    and finite.get('sha256')==fallback['plan_sha256'])
    goal.update(core_parent_count=len(core),core_parent_sha256=sorted(core),core_target=target,
        core_target_met=len(core)>=target,core_ready=bool(core),
        core_priority_ready=len(core)>=target or fallback_valid,
        core_fallback=copy.deepcopy(fallback) if fallback_valid else None,
        completion_mode='core_target_met' if len(core)>=target else 'core_shortfall_fallback' if fallback_valid else 'core_search',
        core_shortfall=max(0,target-len(core)))
    goal['ready']=bool(goal['ready'] and goal['core_ready'] and goal['core_priority_ready'])
    return goal


def finite_search_plan(state, plan, frames, observations, history):
    """Freeze only currently accessible or genuinely searched routes, never auth waits.

    All independently approved product noun variations and all supported available
    providers form the finite extension. No invented pagination or generic queries.
    """
    from .source_search.strategy import consumed_scope
    from .source_search.planner import round_queries, TEXT_ROUTES, IMAGE_ROUTES
    from .source_query_identity import matches_identity
    from .source_visual_queries import digest
    identity=plan.get('search_identity')
    if not identity or not plan.get('visual_query_evidence'):return None
    words=list(dict.fromkeys(r['query'] for r in round_queries(plan,{'phase':'core_action'})
                            if matches_identity(r['query'],identity)))
    if not words:return None
    supported={*TEXT_ROUTES,*IMAGE_ROUTES}
    executed={r.get('provider') for r in history if consumed_scope(r)}
    routes=[r['provider'] for r in observations if r.get('provider') in supported
            and (r.get('status')=='ready' or r.get('status')=='query_exhausted' and r['provider'] in executed)]
    if not routes:return None
    material={'context':context(state),'identity':identity,'queries':words,
              'frame_sha256':[hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in frames],
              'routes':sorted(set(routes))}
    return {**material,'sha256':digest(material),
            'excluded_routes':[{k:r.get(k) for k in ('provider','status','reason')} for r in observations if r['provider'] not in routes]}


def support_search(state):
    if not enabled(state_policy(state)):return False
    from .source_coverage import coverage_goal
    from .source_quality import editing_ready
    sources=[s for s in state.get('sources',[]) if editing_ready(s)]
    goal=coverage_goal(sources,state,state_policy(state))
    return bool(goal.get('core_fallback') and not goal['core_target_met'])


def support_plan(plan):
    """Broaden only to already approved product nouns, in a visibly separate stage."""
    from .source_query_identity import checked_identity
    identity=checked_identity(plan['search_identity'])
    result=copy.deepcopy(plan)
    result.update(core_search_identity=identity,search_identity=None,search_minimums={},
                  search_purpose='support',query_details=[
        {'query':word,'language':lang,'intent':'product','role':'support_product',
         'origin':'independently_approved_product_noun'}
        for lang,words in identity['product_terms'].items() for word in words[:3]])
    result.pop('visual_query_evidence',None)
    result.pop('tiktok_queries',None)
    return result


def exhausted_fallback(state, plan, observations):
    """Access/model waits, unreviewed bytes and missing quotas never prove scarcity."""
    from .source_coverage import actual_search_coverage, current_search_rows
    policy=state_policy(state)
    if not enabled(policy) or not plan or plan.get('context')!=context(state):return None
    rows=current_search_rows(state)
    from .source_search.strategy import search_execution
    if any(search_execution(r)['pending'] for r in rows if r.get('provider') in plan['routes']):return None
    searches=actual_search_coverage(rows,policy['search_minimums'],plan['identity'])
    if not all(r['ready'] for r in searches.values()):return None
    by_provider={r['provider']:r for r in observations}
    if not plan['routes'] or any(by_provider.get(p,{}).get('status')!='query_exhausted' for p in plan['routes']):return None
    # Every received source must have a settled task-scoped content review.
    from .source_quality import editing_ready
    for source in state.get('sources',[]):
        if (source.get('manual_usage_review') or {}).get('editing_eligible') is False:continue
        outcome=source.get('review_outcome') or {}
        if (not editing_ready(source) and outcome.get('policy')=='source-review-outcome-v1'
                and outcome.get('source_sha256')==source.get('sha256')
                and outcome.get('status') in {'content_rejected','no_usable_intervals'}):
            continue  # A settled visual rejection is not an unreviewed download.
        review=source.get('functional_review') or {}
        if (review.get('reviewed') is not True or review.get('core_product_context')!=review_context(state)):
            return None
        if editing_ready(source) and kind(source,state)=='unverified':return None
    core=[s for s in state.get('sources',[]) if editing_ready(s) and kind(s,state)=='core_product']
    if not core:return None
    return {'version':VERSION,'context':context(state),'reason':'finite_core_search_exhausted',
        'plan_sha256':plan['sha256'],'exhausted_routes':copy.deepcopy(observations),
        'search_coverage':searches,'scope':'frozen_accessible_routes_only',
        'excluded_routes':copy.deepcopy(plan.get('excluded_routes',[])),
        'core_source_ids':[s['id'] for s in core],
        'core_shortfall':max(0,policy['core_product_priority']['target_parent_sources']-len(core))}


def bind_plan(state, plan, sources):
    """Exact reviewed roles cross the renderer process boundary explicitly."""
    policy=state_policy(state)
    if not enabled(policy):return
    roles={s['id']:kind(s,state) for s in sources}
    if 'unverified' in roles.values():raise ValueError('핵심 제품 정체성 검토가 현재 제작에 결속되지 않았습니다.')
    goal=priority_goal(sources,state,policy,{'ready':True})
    if not goal['core_priority_ready'] or not goal['core_ready']:
        raise ValueError('핵심 제품 소스 추가 탐색 또는 실제 부족 근거가 필요합니다.')
    plan['core_source_policy']={'version':VERSION,'target_parent_sources':policy['core_product_priority']['target_parent_sources'],
        'context':context(state),'source_kinds':roles,'source_sha256s':{s['id']:s['sha256'] for s in sources},
        'fallback':goal['core_fallback']}
    for shot in plan['shots']:
        shot['product_source_kind']=roles.get(shot['source_id'],'unverified')
        shot['featured_subject']=state.get('product','')


def usage_report(plan, report):
    policy=plan.get('core_source_policy')
    if not policy:return report
    from .source_diversity import parent_groups
    groups=parent_groups(plan.get('sources',[]));roles=policy['source_kinds']
    core={groups[sid] for sid in groups if roles.get(sid)=='core_product'}
    used=set(report['parent_sha256s']);total=sum(report['source_frames'].values())
    shots={s['id']:s for s in plan.get('shots',[])};core_frames=0;shown=set();fps=float(plan.get('fps',30))
    for beat in plan.get('visual_cuts') or plan.get('beats',[]):
        shot=shots.get(beat.get('selected_shot_id'),{});p=shot.get('shot_presentation') or {}
        if (roles.get(shot.get('source_id'))=='core_product' and p.get('product_visible') is True
                and p.get('product_role') in {'promoted_product','related_product'}):
            n=max(0,round(beat['end']*fps)-max(1,round(beat['start']*fps)))
            if n:core_frames+=n;shown.add(groups[shot['source_id']])
    report.update(core_product_available=len(core),core_product_used=len(shown),
        core_originals_used_including_context=len(used&core),
        support_product_used=len(used-core),core_product_share=core_frames/total if total else 0,
        core_target=policy['target_parent_sources'],core_fallback=policy.get('fallback'),
        core_placement=copy.deepcopy(plan.get('core_placement_diagnostics')),
        unused_core_parents=sorted(core-shown))
    return report


def require_usage(plan, report):
    expected=(plan.get('source_diversity_policy') or {}).get('core_product_priority_version')
    policy=plan.get('core_source_policy')
    if expected==VERSION and not policy:raise ValueError('최종 계획에서 핵심 제품 우선 정책이 누락됐습니다.')
    if not policy:return
    if policy.get('version')!=VERSION:raise ValueError('알 수 없는 핵심 제품 우선 정책입니다.')
    for source in plan.get('sources',[]):
        if (policy.get('source_kinds',{}).get(source['id']) not in {'core_product','related_product','context'}
                or policy.get('source_sha256s',{}).get(source['id'])!=source.get('sha256')):
            raise ValueError('최종 핵심 제품 분류가 실제 원본과 다릅니다.')
    required=plan.get('visual_cut_layout',{}).get('minimum_core_parent_sources')
    if type(required) is not int or report.get('core_product_used',0)<max(1,required):
        raise ValueError('배치 가능한 핵심 제품 원본이 최종 영상에서 누락됐습니다.')
    if report['core_product_available']<5 and not policy.get('fallback'):
        raise ValueError('핵심 제품 원본 부족의 실제 탐색 근거가 없습니다.')
