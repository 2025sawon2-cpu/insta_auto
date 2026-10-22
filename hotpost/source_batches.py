"""Alternate acquisition and task-scoped review without mutating reviewed manifests."""
import copy
import json
from dataclasses import asdict
from pathlib import Path

POLICY = 'review-between-download-batches-v1'
BATCH_SIZE = 3


def state_with_search_audit(state, manifest, *, verified_current_manifest=False):
    """A batch sees this run's real search receipts before its inventory is accepted."""
    result=copy.deepcopy(state)
    from .source_coverage import search_scope_for_state,diversity_required
    scope=search_scope_for_state(state)
    conflict=(('run_id' in manifest and manifest['run_id']!=state.get('run_id'))
        or ('search_context' in manifest and manifest['search_context']!=scope))
    bound=not conflict and (verified_current_manifest or (manifest.get('run_id')==state.get('run_id')
        and manifest.get('search_context')==scope))
    if bound and manifest.get('product_evidence',{}).get('reference_scene_intents'):
        from .reference_scene_roles import plan_context
        from .source_quality import sha256_file
        reference = Path(state.get('reference_video') or '__missing__')
        if reference.is_file():
            context = plan_context(manifest['product_evidence'],sha256_file(reference))
            if context:
                result['reference_scene_context'] = context
    # A runtime collection target may request one more new parent after a
    # proven allocation gap, without rewriting the saved body's minimum five.
    policy=manifest.get('source_policy') or {}
    if bound and diversity_required(policy) and policy.get('acquisition_parent_target'):
        from .source_policy import run_policy
        temporary=run_policy(result)
        temporary['acquisition_parent_target']=policy['acquisition_parent_target']
        result['source_policy']=temporary
        for run in result.get('runs',[]):
            if run.get('id')==result.get('run_id'):run['source_policy']=copy.deepcopy(temporary)
    rows=manifest.get('search_audit',[]) if isinstance(manifest,dict) else []
    acquisition=result.setdefault('source_acquisition',{})
    existing=acquisition.setdefault('queries',[])
    seen={json.dumps(r,sort_keys=True,ensure_ascii=False) for r in existing}
    for row in rows:
        if not isinstance(row,dict):continue
        current=copy.deepcopy(row)
        # Explicit provenance is immutable. A current receipt may bind only
        # genuinely untagged new rows, never relabel another run/product.
        if bound and 'run_id' not in current and 'search_context' not in current:
            current.update(run_id=state.get('run_id'),search_context=scope)
        identity=json.dumps(current,sort_keys=True,ensure_ascii=False)
        if identity not in seen:existing.append(current);seen.add(identity)
    return result


def current_records(state, reviewed):
    from .studio_sources import unique_sources
    from .source_core_priority import enabled, state_policy
    records=unique_sources([*copy.deepcopy(reviewed),*copy.deepcopy(state.get('sources',[]))],core_priority=enabled(state_policy(state)))
    current={s['sha256']:s for s in state.get('sources',[])}
    for source in records:
        denial=(current.get(source['sha256'],{}).get('manual_usage_review') or {})
        if denial.get('editing_eligible') is False:
            source['manual_usage_review']=copy.deepcopy(denial)
            source['editing_eligible']=False
    return records


def review_context(state):
    import hashlib
    from .source_quality import sha256_file
    path=Path(state.get('reference_video') or '__missing__')
    return {'task_id':state['id'],'run_id':state.get('run_id'),'product':state.get('product'),
            'reference_sha256':sha256_file(path) if path.is_file() else None,
            'reference_text_sha256':hashlib.sha256((state.get('reviewed_original_text') or state.get('original_text') or '').encode()).hexdigest()}


def snapshot(root, candidates, number):
    from .editing_adapter import _atomic_json
    root = Path(root)
    value = json.loads((root/'manifest.json').read_text('utf-8'))
    value.update(status='review_pending', audit_checkpoint='download_batch', batch_policy=POLICY)
    value['candidates'] = [asdict(c) for c in candidates if c.downloaded_file and not c.rejection_reasons]
    for row in value['candidates']:
        row['selected_for_zip'] = True  # Admission to review, never editing approval.
    target = root/f'batch-{number:04d}.json'
    if target.exists():
        raise ValueError('A reviewed acquisition batch cannot be overwritten')
    _atomic_json(target, value)
    return target


def cached_records(studio, job, *, saved=None, state=None):
    from .source_quality import sha256_file
    from .source_preparation import PreparationEvidenceWaiting
    saved = saved or job.get('checkpoint', {}).get('source_batch_review')
    if not saved:
        return {}
    try:
        state=state or studio.store.get(job['task_id'])
        if saved.get('review_context')!=review_context(state):
            raise ValueError('Changed task/reference review context')
        manifest = Path(saved['manifest'])
        review = Path(saved['path'])
        if not manifest.resolve().is_relative_to(studio.settings.source_dir.resolve()):
            raise ValueError('Foreign acquisition batch')
        if review.resolve().parent!=manifest.resolve().parent:
            raise ValueError('Foreign acquisition review')
        if (sha256_file(manifest) != saved['manifest_sha256']
                or sha256_file(review) != saved['sha256']):
            raise ValueError('Changed acquisition review')
        data = json.loads(review.read_text('utf-8'))
        if data['input_key'] != str(manifest.resolve())+':'+saved['manifest_sha256']:
            raise ValueError('Mismatched batch input')
        for sha, source in data['sources'].items():
            if sha != source['sha256'] or sha256_file(Path(source['path'])) != sha:
                raise ValueError('Changed reviewed source')
        return copy.deepcopy(data['sources'])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PreparationEvidenceWaiting('수집 묶음의 실제 파일·검토 근거가 변경되어 보류합니다.') from exc


class TaskBatchReviewer:
    def __init__(self, studio, job, progress):
        self.studio, self.job, self.progress = studio, job, progress

    def __call__(self, manifest):
        from .editing_adapter import _atomic_json
        from .studio_pause import check_paused
        from .studio_sources import unique_sources, source_goal
        from .source_quality import sha256_file, editing_ready
        studio, job = self.studio, self.job
        studio.store.assert_owned(job)
        check_paused(studio.store, job)
        state = studio.store.get(job['task_id'])
        cached = cached_records(studio, job)
        value = json.loads(Path(manifest).read_text('utf-8'))
        from .source_policy import run_policy
        from .source_coverage import diversity_required
        if diversity_required(run_policy(state)):state=state_with_search_audit(state,value,verified_current_manifest=True)
        files = [Path(manifest).parent/r['downloaded_file'] for r in value['candidates']]
        incoming = studio._source_records(files, manifest)
        from .source_core_priority import enabled as core_enabled
        merged = unique_sources([*copy.deepcopy(state.get('sources', [])), *incoming],core_priority=core_enabled(run_policy(state)))
        merged = [copy.deepcopy(cached.get(s['sha256'], s)) for s in merged]
        current_by_sha={s['sha256']:s for s in state.get('sources',[])}
        for source in merged:
            denial=(current_by_sha.get(source['sha256'],{}).get('manual_usage_review') or {})
            if denial.get('editing_eligible') is False:source['manual_usage_review']=copy.deepcopy(denial)
        key = str(Path(manifest).resolve())+':'+sha256_file(Path(manifest))
        path = Path(manifest).with_name(Path(manifest).stem+'-review-'+job['claim_token'][:12]+'.json')
        _atomic_json(path, {'input_key':key, 'sources':cached})
        saved = {'path':str(path.resolve()), 'sha256':sha256_file(path), 'input_key':key}
        job['checkpoint']['source_visual_review'] = saved
        # Register before model work: partial approvals survive model waits/pause.
        job['checkpoint']['source_batch_review'] = {
            **saved, 'manifest':str(Path(manifest).resolve()), 'manifest_sha256':sha256_file(Path(manifest)),
            'review_context':review_context(state)}
        studio.store.checkpoint(job, job['checkpoint'])
        reviewed, completion = studio._review_source_records(state, job, merged, self.progress)
        studio.store.assert_owned(job)
        check_paused(studio.store, job)
        # Voice synthesis can finish during review; use the current duration.
        current = studio.store.get(job['task_id'])
        if diversity_required(run_policy(current)):current=state_with_search_audit(current,value,verified_current_manifest=True)
        if review_context(current)!=review_context(state):
            from .source_preparation import PreparationEvidenceWaiting
            raise PreparationEvidenceWaiting('묶음 검토 중 제품·원본 근거가 변경되어 결과 수용을 보류합니다.')
        combined = current_records(current,reviewed)
        goal = source_goal({**current, 'sources':combined}, studio.settings.source_min_usable)
        if not goal['ready'] and completion:
            # A longer voice may have arrived after the review's early stop.
            # Review the already received remainder before another transfer.
            done={s['sha256']:s for s in reviewed}
            remainder=[copy.deepcopy(done.get(s['sha256'],s)) for s in merged]
            reviewed,completion=studio._review_source_records(current,job,remainder,self.progress)
            studio.store.assert_owned(job)
            check_paused(studio.store, job)
            current=studio.store.get(job['task_id'])
            if diversity_required(run_policy(current)):current=state_with_search_audit(current,value,verified_current_manifest=True)
            if review_context(current)!=review_context(state):
                from .source_preparation import PreparationEvidenceWaiting
                raise PreparationEvidenceWaiting('추가 묶음 검토 중 제품·원본 근거가 변경되어 결과 수용을 보류합니다.')
            combined=current_records(current,reviewed)
            goal=source_goal({**current,'sources':combined},studio.settings.source_min_usable)
        if not goal['ready'] and not (goal.get('source_diversity_ready') and goal.get('core_ready')):
            # Newly received files get the same local rescue before another batch.
            local=studio._recover_local_source_intervals({**current,'sources':combined},job,self.progress,inventory_only=True)
            if local:
                recovered={s['sha256']:s for s in local['sources']}
                combined=[copy.deepcopy(recovered.get(s['sha256'],s)) for s in combined]
                reviewed=[copy.deepcopy(recovered.get(s['sha256'],s)) for s in reviewed]
                for source in local['sources']:studio._checkpoint_deferred_review(job,source)
            current=studio.store.get(job['task_id'])
            if diversity_required(run_policy(current)):current=state_with_search_audit(current,value,verified_current_manifest=True)
            if review_context(current)!=review_context(state):
                from .source_preparation import PreparationEvidenceWaiting
                raise PreparationEvidenceWaiting('짧은 구간 복구 중 현재 제작 맥락이 변경되어 수용 보류')
            combined=current_records(current,combined)
            goal=source_goal({**current,'sources':combined},studio.settings.source_min_usable)
        repair = job.get('payload', {}).get('daily_quality_repair')
        minimum = 2 if not current.get('edit_id') else 3
        new = [s for s in reviewed if s['sha256'] not in {x['sha256'] for x in current.get('sources', [])}]
        montage = goal.get('duration_requirement') == 'preference'
        ready = goal['ready'] and (not repair or montage or sum(editing_ready(s) for s in new) >= minimum)
        job['checkpoint']['source_batch_review'].update(
            path=job['checkpoint']['source_visual_review']['path'],
            sha256=job['checkpoint']['source_visual_review']['sha256'],
            goal=goal, ready=bool(ready), review_completion=completion)
        studio.store.checkpoint(job, job['checkpoint'])
        return {'ready':bool(ready), 'goal':goal, 'policy':POLICY}

    def receipt(self):
        return copy.deepcopy(self.job.get('checkpoint',{}).get('source_batch_review'))
