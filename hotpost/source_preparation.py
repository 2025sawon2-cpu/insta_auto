"""Immutable preparation bundles bound to real media and query evidence."""
import copy
import hashlib
import json
from pathlib import Path
from .source_access_preflight import SourceAccessWaiting

PREPARATION_POLICY = 'source-preparation-sha-v1'


class PreparationEvidenceWaiting(SourceAccessWaiting, ValueError):
    """Missing/changed evidence waits without retry or quality failure charging."""


def query_policy():
    from . import source_planning
    return getattr(source_planning, 'QUERY_PLAN_POLICY', 'legacy-query-plan')


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def evidence_key(caption, transcript):
    value={'caption':caption, **{k:transcript.get(k,'') for k in ('speech','screen_text','reference_kind')}}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def payload_key(value):
    body={k:v for k,v in value.items() if k!='payload_sha256'}
    return hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def bundle_paths(settings,shortcode,caption,transcript):
    # Compact filenames keep atomic-write temporary paths within Windows limits.
    key=evidence_key(caption,transcript)[:24]
    stamp=hashlib.sha256(query_policy().encode()).hexdigest()[:8]
    directory=Path(settings.data_dir)/'source-preparations'/shortcode
    return directory/(key+'.json'),directory/(key+'-'+stamp+'.json')


def acquisition_bundle_path(settings,shortcode,caption,transcript,policy,subject_hint=''):
    if not policy.get('search_minimums'):return None
    from .source_visual_queries import search_contract
    _,current=bundle_paths(settings,shortcode,caption,transcript)
    suffix=hashlib.sha256(json.dumps({'source_policy':policy,
        'visual_contract':search_contract(policy['search_minimums']),
        'subject_hint':subject_hint},sort_keys=True).encode()).hexdigest()[:10]
    return current.with_name(current.stem+'-acq-'+suffix+'.json')


def replanning_bundle_path(path, plan):
    """Keep an accepted acquisition receipt unchanged during replanning."""
    path=Path(path)
    stamp=payload_key({'query_plan':plan})[:16]
    return path.with_name(path.stem+'-replan-'+stamp+'.json')


def verify_acceptance(value,path,context=None,expected_reference=None):
    if expected_reference and digest(value['reference']) != expected_reference:
        raise PreparationEvidenceWaiting('저장된 준비 원본이 현재 작업의 기준 영상과 다릅니다.')
    for row in (context or {}).get('rounds',[]):
        manifest=Path(row.get('manifest_path') or '__missing__')
        if manifest.is_file():
            try:receipt=json.loads(manifest.read_text('utf-8'))
            except (ValueError,OSError) as exc:
                raise PreparationEvidenceWaiting('작업 수용 소스 영수증을 확인할 수 없습니다.') from exc
            if receipt.get('preparation_bundle_path')==str(Path(path).resolve()) and receipt.get('preparation_bundle_sha256') != digest(path):
                raise PreparationEvidenceWaiting('작업 수용 영수증의 소스 준비 SHA가 변경되었습니다.')


def save_bundle(path, caption, raw_transcript, reference, frames, sheet, **data):
    from .editing_adapter import _atomic_json
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    files=[reference,*frames,sheet]
    bundle={'policy':PREPARATION_POLICY,'query_policy':query_policy(),
            'evidence_key':evidence_key(caption,raw_transcript),
            'reference':str(Path(reference).resolve()), 'frames':[str(Path(f).resolve()) for f in frames],
            'sheet':str(Path(sheet).resolve()),
            'files':[{'path':str(Path(f).resolve()),'sha256':digest(f)} for f in files], **copy.deepcopy(data)}
    bundle['payload_sha256']=payload_key(bundle)
    _atomic_json(Path(path),bundle)
    return bundle


def load_bundle(path, caption, transcript):
    path=Path(path)
    try:
        value=json.loads(path.read_text('utf-8'))
    except (ValueError,OSError) as exc:
        raise PreparationEvidenceWaiting('저장된 소스 준비 영수증을 읽을 수 없습니다.') from exc
    if (not isinstance(value,dict) or not isinstance(value.get('frames'),list)
            or not isinstance(value.get('files'),list) or not value.get('reference') or not value.get('sheet')
            or any(not isinstance(row,dict) or not row.get('path') or not row.get('sha256') for row in value['files'])):
        raise PreparationEvidenceWaiting('저장된 소스 준비 영수증의 구조가 잘못되었습니다.')
    if value.get('payload_sha256') != payload_key(value):
        raise PreparationEvidenceWaiting('저장된 소스 준비 계획·전사 내용의 결속 SHA가 변경되었습니다.')
    if value.get('policy') != PREPARATION_POLICY or value.get('evidence_key') != evidence_key(caption,transcript):
        raise PreparationEvidenceWaiting('저장된 소스 준비 원문 근거가 변경되었습니다. 자동 재추출하지 않습니다.')
    required=[value['reference'],*value['frames'],value['sheet']]
    receipts={r['path']:r['sha256'] for r in value.get('files',[])}
    try:
        invalid=not value['frames'] or any(str(Path(p).resolve()) not in receipts or not Path(p).is_file()
            or digest(p)!=receipts[str(Path(p).resolve())] for p in required)
    except (OSError,TypeError,ValueError) as exc:
        raise PreparationEvidenceWaiting('저장된 소스 준비 영상·프레임을 확인할 수 없습니다.') from exc
    if invalid:
        raise PreparationEvidenceWaiting('저장된 소스 준비 영상·프레임 SHA가 변경되거나 소실되었습니다.')
    return value


def prior_bundle(settings, shortcode, caption, transcript, context=None):
    """Find bound preparation first; adopt legacy media with explicitly current hashes.

    Adoption does not claim historical integrity and never accepts a legacy plan
    as the current query policy. Original receipts remain unchanged.
    """
    base,current=bundle_paths(settings,shortcode,caption,transcript)
    expected_reference=(context or {}).get('expected_reference_sha256')
    older=sorted(base.parent.glob(base.stem+'-*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    for path in dict.fromkeys([current,base,*older,base.with_suffix('.media.json')]):
        if path.is_file():
            value=load_bundle(path,caption,transcript)
            verify_acceptance(value,path,context,expected_reference)
            return value,path
    paths=[r.get('manifest_path') for r in (context or {}).get('rounds',[]) if r.get('manifest_path')]
    for raw in reversed(paths):
        manifest=Path(raw)
        if not manifest.is_file():continue
        saved=json.loads(manifest.read_text('utf-8'))
        if saved.get('shortcode') != shortcode or saved.get('caption') != caption:continue
        reference=manifest.parent/'reference.mp4';sheet=manifest.parent/'reference_contact_sheet.jpg'
        frames=[manifest.parent/f for f in saved.get('reference_frames',[])]
        if not frames or not all(p.is_file() for p in [reference,sheet,*frames]):
            raise PreparationEvidenceWaiting('이전 소스 준비 자료가 소실되었습니다. 자동 재추출하지 않습니다.')
        if expected_reference and digest(reference)!=expected_reference:
            raise PreparationEvidenceWaiting('이전 소스 준비 원본이 현재 작업의 기준 영상 SHA와 다릅니다.')
        data={k:saved.get(k,[]) for k in ('visual_product_queries','google_vision_terms','openclip_product_evidence','subject_reference_indices')}
        data.update(transcript=copy.deepcopy(transcript),query_plan={**saved.get('product_evidence',{}),
            'query_details':saved.get('query_details',[])},legacy_adoption=True,
            integrity_basis='current_files_captured_not_retroactive',origin_manifest=str(manifest.resolve()))
        value=save_bundle(base,caption,transcript,reference,frames,sheet,**data)
        value['query_policy']='legacy-adopted-plan'
        value['payload_sha256']=payload_key(value)
        from .editing_adapter import _atomic_json
        _atomic_json(base,value)
        return value,base
    return None,current


def preflight_preparation(settings, state, job=None):
    """Read a current bundle for scope checks without adopting/writing legacy media."""
    from .source_finder import _post, _transcript_evidence
    post=_post(settings,state['shortcode']);transcript=_transcript_evidence(settings,state['shortcode'])
    base,current=bundle_paths(settings,state['shortcode'],post.caption,transcript)
    rounds=[*state.get('source_acquisition',{}).get('rounds',[]),
            *(job or {}).get('checkpoint',{}).get('refresh_wait_history',[])]
    if state.get('source_search_manifest_path'):
        rounds.append({'manifest_path':state['source_search_manifest_path']})
    context={'rounds':rounds}
    authoritative=state.get('reference_video')
    if authoritative and not Path(authoritative).is_file():
        raise PreparationEvidenceWaiting('현재 작업 기준 영상이 소실되었습니다.')
    expected=digest(authoritative) if authoritative else None
    from .source_policy import run_policy
    from .source_diversity import acquisition_policy
    from .source_visual_queries import search_contract
    policy=acquisition_policy(state,run_policy(state))
    hint=state.get('product','')
    acquisition=acquisition_bundle_path(settings,state['shortcode'],post.caption,transcript,policy,hint)
    selected=(job or {}).get('checkpoint',{}).get('planning_preparation')
    if selected is not None:
        from .source_coverage import search_scope_for_state
        wanted={'task_id':state['id'],'job_id':(job or {}).get('id'),
                'run_id':state.get('run_id'),'search_context':search_scope_for_state(state),
                'source_policy':policy}
        if (not isinstance(selected,dict) or not all(wanted.get(k) for k in ('task_id','job_id','run_id'))
                or (job or {}).get('task_id')!=state['id']
                or (job or {}).get('payload',{}).get('run_id')!=state.get('run_id')
                or any(selected.get(k)!=v for k,v in wanted.items())):
            raise PreparationEvidenceWaiting('재계획 준비 번들의 작업·실행 결속이 다릅니다.')
        try:
            selected_path=Path(selected['path']).resolve()
            if selected_path.parent!=base.parent.resolve() or digest(selected_path)!=selected['sha256']:
                raise PreparationEvidenceWaiting('재계획 준비 번들의 소유 경로·SHA가 다릅니다.')
            value=load_bundle(selected_path,post.caption,transcript)
            verify_acceptance(value,selected_path,context,expected)
        except (OSError,KeyError,TypeError) as exc:
            raise PreparationEvidenceWaiting('재계획 준비 번들의 실제 근거 확인 대기') from exc
        plan=value.get('query_plan')
        if (value.get('query_policy')!=query_policy() or not isinstance(plan,dict)
                or not reusable_query_contract(plan,policy,hint,wanted)):
            # Ownership, receipt and media integrity were checked above.
            # Reuse only those frames, just as for an unselected obsolete pool;
            # the normal preparation entry must obtain a fresh reviewed plan.
            # Keep the selected checkpoint and immutable bundle unchanged.
            return None,[Path(f) for f in value['frames']]
        return plan,[Path(f) for f in value['frames']]
    older=sorted(base.parent.glob(base.stem+'-*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    for path in dict.fromkeys([*([acquisition] if acquisition else []),current,base,*older,base.with_suffix('.media.json')]):
        if path.is_file():
            value=load_bundle(path,post.caption,transcript)
            verify_acceptance(value,path,context,expected)
            plan=value.get('query_plan') if value.get('query_policy')==query_policy() else None
            if plan is not None and policy.get('search_minimums'):
                contract=search_contract(policy['search_minimums'])
                evidence=(plan.get('visual_query_evidence') or {}).get('evidence') or {}
                from .source_coverage import search_scope_for_state
                if not reusable_query_contract(plan,policy,hint,
                        {'task_id':state['id'],
                         'job_id':(job or {}).get('id') if (job or {}).get('task_id')==state['id']
                             and (job or {}).get('payload',{}).get('run_id')==state.get('run_id') else None,
                         'run_id':state.get('run_id'),'search_context':search_scope_for_state(state)}):
                    # Media can be reused, but an obsolete query pool cannot
                    # establish exhaustion for a new policy/topic contract.
                    plan=None
            return plan,[Path(f) for f in value['frames']]
    # Legacy media can be checked before access, without writing an adoption receipt.
    for row in reversed(rounds):
        manifest=Path(row.get('manifest_path') or '__missing__')
        if not manifest.is_file():continue
        saved=json.loads(manifest.read_text('utf-8'))
        if saved.get('shortcode')!=state['shortcode'] or saved.get('caption')!=post.caption:continue
        reference=manifest.parent/'reference.mp4';sheet=manifest.parent/'reference_contact_sheet.jpg'
        frames=[manifest.parent/f for f in saved.get('reference_frames',[])]
        if not frames or not all(p.is_file() for p in [reference,sheet,*frames]):
            raise PreparationEvidenceWaiting('이전 소스 준비 자료가 소실되었습니다. 자동 재추출하지 않습니다.')
        if expected and digest(reference)!=expected:
            raise PreparationEvidenceWaiting('이전 소스 준비 원본이 현재 작업의 기준 영상 SHA와 다릅니다.')
        return None,frames
    return None,[]


def reusable_query_contract(plan, policy, hint, context, *, verify_files=True):
    """Retain an intact active v4/v5 plan across query-prompt clarifications.

    This is not a new approval: the original receipt is validated unchanged.
    New runs and changed media/topic/policy must use the current prompt.
    """
    from .source_visual_queries import search_contract,plan_queries,query_pool_report
    expected=search_contract(policy['search_minimums'])
    evidence=(plan.get('visual_query_evidence') or {}).get('evidence') or {}
    if plan.get('source_policy')!=policy or evidence.get('subject_hint')!=hint:
        return False
    from .source_topic_queries import POLICY as TOPIC_POLICY,plan_queries as topic_queries
    if (plan.get('visual_query_evidence') or {}).get('policy')==TOPIC_POLICY:
        owner={k:context.get(k) for k in ('task_id','job_id','run_id')}
        if (plan.get('query_owner')!=owner or plan.get('search_context')!=context.get('search_context')
                or plan.get('run_id')!=context.get('run_id')):
            return False
        try:
            rows=topic_queries(plan,verify_files=verify_files)
            # A grounded partial pool can start real discovery and learn from
            # results. Actual EN/ZH completion still requires submitted receipts.
            return bool(rows)
        except (ValueError,KeyError,TypeError,OSError):return False
    if plan.get('text_query_evidence'):
        from .source_text_query_receipts import plan_text_queries, pool_report
        owner={k:context.get(k) for k in ('task_id','job_id','run_id')}
        if (not all(isinstance(v,str) and v for v in owner.values())
                or not context.get('search_context')
                or plan.get('search_context')!=context['search_context']
                or plan.get('run_id')!=owner['run_id']
                or not context['search_context'].get('reference_sha256')
                or plan.get('query_reference_sha256')!=context['search_context']['reference_sha256']
                or any(evidence.get(k)!=v for k,v in expected.items())):
            return False
        try:
            rows=plan_text_queries(plan,owner=owner,verify_files=verify_files)
            return pool_report(rows,policy['search_minimums'],plan.get('search_identity'))['ready']
        except (ValueError,KeyError,TypeError,OSError):
            return False
    if all(evidence.get(k)==v for k,v in expected.items()):
        try:
            rows=plan_queries(plan) if verify_files else plan_queries(plan,verify_files=False)
            return query_pool_report(rows,policy['search_minimums'],
                plan.get('search_identity'))['ready']
        except (ValueError, KeyError, TypeError, OSError):
            return False
    revision='identity_prompt_revision'
    if (evidence.get(revision) not in {'reference-topic-and-scene-intent-v4',
                                      'reference-topic-and-scene-intent-v5'}
            or expected.get(revision)!='reference-topic-and-scene-intent-v6'
            or any(evidence.get(k)!=v for k,v in expected.items() if k!=revision)
            or not context.get('run_id') or plan.get('run_id')!=context['run_id']
            or not context.get('search_context') or plan.get('search_context')!=context['search_context']
            or not context['search_context'].get('reference_sha256')
            or plan.get('query_reference_sha256')!=context['search_context']['reference_sha256']):
        return False
    try:
        rows=plan_queries(plan) if verify_files else plan_queries(plan,verify_files=False)
        return query_pool_report(rows,policy['search_minimums'],
            plan.get('search_identity'))['ready']
    except (ValueError,KeyError,TypeError):
        return False
