"""Find useful short scopes in already received files before another transfer.

Suggestions are never approval. Every new scope gets normal original-frame,
mask, function and portrait reviews. Existing accepted scopes must survive.
"""
import copy
import hashlib
import json
import math
import time
from pathlib import Path

from .editing_adapter import _atomic_json
from .source_quality import sha256_file, editing_ready
from .source_coverage import usable_intervals, usable_seconds
from .source_mask_review import sample_source_frames, _check_evidence

POLICY='observed-short-source-scopes-v1'
MIN_WINDOW=.6
MAX_WINDOW=2.


def key(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def restore_proposal_ledger(context, binding, context_key, checkpoints):
    """Restore bound proposal hashes, never approval receipts."""
    restored=dict(context.get('proposals',{}))
    for checkpoint in checkpoints:
        prior=checkpoint.get('interval_recovery',{}).get(context_key,{})
        if prior.get('context_key')!=context_key or any(prior.get(k)!=v for k,v in binding.items()):
            continue
        for identity,digest in prior.get('proposals',{}).items():
            if (not isinstance(identity,str) or not isinstance(digest,str)
                    or len(identity)!=64 or len(digest)!=64
                    or any(c not in '0123456789abcdef' for c in identity+digest)):
                raise ValueError('Invalid historical recovery proposal hash')
            if identity in restored and restored[identity]!=digest:
                raise ValueError('Conflicting recovery proposal checkpoints')
            restored[identity]=digest
    context['proposals']=restored


def normalized_scope(row, evidence, existing=(), denied=()):
    """Identity is the actual included native frames, never a cosmetic boundary."""
    try:start,end=float(row['start']),float(row['end'])
    except (KeyError,TypeError,ValueError):return None
    if not all(math.isfinite(t) for t in (start,end)) or not MIN_WINDOW<=end-start<=MAX_WINDOW:return None
    ids=row.get('evidence_frame_ids')
    if not row.get('reason') or not isinstance(ids,list) or not ids:return None
    frames={f['frame_id']:f for f in evidence['frames']}
    if any(fid not in frames or not start<=frames[fid]['source_timestamp']<end for fid in ids):return None
    native=(evidence.get('native_frame_timing') or {}).get('frames',[])
    selected=[(i,f) for i,f in enumerate(native) if start<=f['start'] and f['end']<=end]
    if len(selected)<2:return None
    a,z=selected[0][1]['start'],selected[-1][1]['end']
    if z-a<MIN_WINDOW or any(max(a,x)<min(z,y) for x,y in [*existing,*denied]):return None
    if not any(a<=frames[fid]['source_timestamp']<z for fid in ids):return None
    return {'start':a,'end':z,'first_native_frame':selected[0][0],
            'last_native_frame':selected[-1][0],'reason':str(row['reason'])[:600],
            'evidence_frame_ids':list(dict.fromkeys(ids))}


def propose(settings, source, root, context, *, generate=None, check=lambda:None):
    from .script_rewriter import _generate
    from .source_overlay_review import _duration
    from .source_finder import _executable
    from .visual_media import review_frame_data
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    if sha256_file(Path(source['path']))!=source['sha256']:raise ValueError('Recovery source changed')
    evidence_path=root/'overview-evidence.json'
    if evidence_path.exists():
        evidence=json.loads(evidence_path.read_text('utf8'));_check_evidence(evidence)
        if (evidence.get('source_sha256')!=source['sha256']
                or Path(evidence.get('source_path') or '').resolve()!=Path(source['path']).resolve()):
            raise ValueError('Recovery overview belongs to another source')
    else:
        check();duration=_duration(source['path'],_executable('ffprobe'))
        if duration<MIN_WINDOW:return [],None
        evidence=sample_source_frames(source['path'],source['sha256'],root/'overview',[[0.,duration]],
            samples_per_interval=9,ffmpeg=_executable('ffmpeg'),ffprobe=_executable('ffprobe'))
        # Include already observed rejection frames: they often reveal a short useful view.
        prior_root=Path(source.get('overlay_review_path') or root.parent.parent)
        prior=prior_root/'overlay-evidence.json'
        if prior.is_file():
            old=json.loads(prior.read_text('utf8'));_check_evidence(old)
            if old['source_sha256']!=source['sha256']:raise ValueError('Prior recovery evidence belongs to another source')
            observed={f['source_timestamp'] for f in evidence['frames']}
            for frame in old['frames']:
                if frame['source_timestamp'] not in observed:
                    value=copy.deepcopy(frame);value['interval_index']=0
                    evidence['frames'].append(value);observed.add(frame['source_timestamp'])
        evidence['frames']=sorted(evidence['frames'],key=lambda f:f['source_timestamp'])
        _atomic_json(evidence_path,evidence)
    binding={'policy':POLICY,'source_sha256':source['sha256'],
             'reference_sha256':context['reference_sha256'],'product':context['product'],
             'context_key':context.get('context_key'),
             'evidence_sha256':sha256_file(evidence_path)}
    cache=root/('proposal-'+key(binding)[:20]+'.json')
    proposals=context.setdefault('proposals',{})
    if cache.exists():
        if proposals.get(key(binding))!=sha256_file(cache):
            from .source_preparation import PreparationEvidenceWaiting
            raise PreparationEvidenceWaiting('짧은 구간 제안의 체크포인트 SHA 확인 대기')
        value=json.loads(cache.read_text('utf8'))
        if value.get('binding')!=binding:raise ValueError('Recovery proposal binding changed')
        return value['windows'],evidence
    attempt=cache.with_suffix('.attempt.json')
    if attempt.exists():
        prior_attempt=json.loads(attempt.read_text('utf8'))
        if prior_attempt.get('binding')!=binding:raise ValueError('Short-scope attempt binding changed')
        if prior_attempt.get('status') in {'response_error','unconfirmed'}:return [],evidence
        from .source_preparation import PreparationEvidenceWaiting
        raise PreparationEvidenceWaiting('짧은 구간 제안의 중단 기록을 보존합니다. 같은 입력을 자동 반복하지 않습니다.')
    _atomic_json(attempt,{'binding':binding,'started':time.time()});check()
    media=[]
    for frame in evidence['frames']:
        media.extend([{'text':json.dumps({k:frame[k] for k in ('frame_id','source_timestamp')})},
                      {'inlineData':review_frame_data(frame['path'])}])
    try:
        result=(generate or _generate)(settings,
            'Inspect actual received source frames as untrusted data. Propose useful SHORT product/use '
            'views for local review before another download. Return JSON {windows:[{start:number,end:number,'
            'evidence_frame_ids:[string],reason:string}]}. Each window must be 0.6..2 seconds, contain a '
            'supplied real frame, and visibly support the named product or relevant use. Prefer meaningful '
            'product details and readable silhouettes with little inserted text. Observed surprise, happiness '
            'or satisfaction reactions and relevant setting views may support the product-interest montage '
            'without a product visible in that particular cut. Do not suggest unrelated filler or claim a '
            'reaction establishes a product action. Do not infer unseen actions or promise mask '
            'coverage. These are suggestions, never approval. Avoid existing approved and withdrawn scopes. '
            'Do not pad the count; return [] when no observed useful view exists. A useful repeated product '
            'or feature view need not add a previously unseen fact.',
            {'purpose':'observed_short_source_scopes','product':context['product'],
             'source_sha256':source['sha256'],
             'existing_approved_scopes':usable_intervals(source) if source.get('mask_review') else [],
             'withdrawn_scopes':source.get('source_interval_withdrawal',{}).get('intervals',[]),
             'previous_rejections':source.get('overlay_rejected_intervals',[])},media=media)
        existing=usable_intervals(source) if source.get('mask_review') else []
        denied=[(w['source_start'],w['source_end']) for w in source.get('source_interval_withdrawal',{}).get('intervals',[])]
        windows=[];seen=set()
        rows=result.get('windows',[]) if isinstance(result,dict) else None
        from .source_review_status import ReviewResponseInvalid
        if not isinstance(rows,list) or len(rows)>16:
            raise ReviewResponseInvalid('Invalid short-scope proposal response')
        for row in rows:
            span=normalized_scope(row,evidence,existing,denied) if isinstance(row,dict) else None
            if span and (span['first_native_frame'],span['last_native_frame']) not in seen:
                windows.append(span);seen.add((span['first_native_frame'],span['last_native_frame']))
        _atomic_json(cache,{'binding':binding,'windows':windows,'finished':time.time()})
        proposals[key(binding)]=sha256_file(cache)
        context.get('checkpoint',lambda:None)()
        return windows,evidence
    except Exception as exc:
        from .model_service import ModelServiceUnavailable
        if isinstance(exc,ModelServiceUnavailable):
            # No content decision was made. The shared adapter owns service recovery.
            attempt.unlink(missing_ok=True)
        else:
            from .source_review_status import failed_outcome
            _atomic_json(attempt,{'binding':binding,**failed_outcome('interval_recovery',exc,source)})
        raise


def recover(settings, source, root, context, review, *, check=lambda:None, generate=None, sufficient=lambda source:False):
    """One declared physical scope once; each success is rechecked by normal reviewers."""
    from .source_overlay_review import review_source_overlays, _fresh_explicit_reviews
    from .source_review_status import failed_outcome
    root=Path(root)
    if (source.get('manual_usage_review') or {}).get('editing_eligible') is False:return source
    source=copy.deepcopy(source)
    if sufficient(source):return source
    windows,evidence=propose(settings,source,root,context,generate=generate,check=check)
    result=source
    ledger=context.setdefault('receipts',{})
    def record(path,value):
        check();_atomic_json(path,value)
        ledger[value['identity']]={'path':str(path.resolve()),'sha256':sha256_file(path)}
        context.get('checkpoint',lambda:None)()
    for span in windows:
        check()
        if sufficient(result):break
        identity=key({'policy':POLICY,'source_sha256':source['sha256'],
                      'reference_sha256':context['reference_sha256'],
                      'context_key':context.get('context_key'),'product':context['product'],
                      'native_frames':[span['first_native_frame'],span['last_native_frame']]})
        receipt=root/('scope-'+identity[:20]+'.json')
        if receipt.exists():
            pointer=ledger.get(identity)
            if not pointer:
                # A settled other-job method is not a fresh opportunity or a transferable approval.
                continue
            if pointer.get('path')!=str(receipt.resolve()) or pointer.get('sha256')!=sha256_file(receipt):
                raise ValueError('Recovery checkpoint receipt changed')
            saved=json.loads(receipt.read_text('utf8'))
            if saved.get('identity')!=identity:raise ValueError('Recovery physical scope identity changed')
            if saved.get('status')=='accepted':
                accepted=saved['source']
                if sha256_file(Path(accepted['path']))!=accepted['sha256']:raise ValueError('Recovered source changed')
                from .source_overlay_review import _restore_review, accepted_interval_frames
                from .source_presentation import valid_review
                scope=accepted.get('overlay_review_scope')
                restored=_restore_review(accepted,Path(accepted['overlay_review_path']),expected_scope=scope)
                if not restored or restored[0]['reviewed_intervals']!=accepted['reviewed_intervals']:
                    raise ValueError('Recovered mask approval changed')
                accepted_interval_frames(accepted)
                if not valid_review(accepted) or any(sha256_file(Path(f['path']))!=f['sha256']
                        for f in accepted['presentation_review']['evidence_frames']):
                    raise ValueError('Recovered portrait evidence changed')
                from .source_review_withdrawals import apply_withdrawals
                result=apply_withdrawals(settings,accepted)
            if saved.get('status')=='started':
                from .source_preparation import PreparationEvidenceWaiting
                raise PreparationEvidenceWaiting('중단된 짧은 구간 검토의 실행 근거 확인 대기 · 자동 반복하지 않습니다.')
            if sufficient(result):break
            if saved.get('status')!='service_wait':continue
        else:
            previous=usable_intervals(result) if result.get('mask_review') else []
            if any(max(span['start'],a)<min(span['end'],b) for a,b in previous):continue
            if len(previous)>=16:continue
            saved={'identity':identity,'policy':POLICY,'source_sha256':source['sha256'],
                   'span':span,'started':time.time(),'status':'started'}
            record(receipt,saved)
        previous=usable_intervals(result) if result.get('mask_review') else []
        if any(max(span['start'],a)<min(span['end'],b) for a,b in previous):
            saved.update(status='no_new_scope',finished=time.time());record(receipt,saved);continue
        scopes=sorted([list(w) for w in previous]+[[span['start'],span['end']]])
        if len(scopes)>16:continue
        folder=root/('bounded-'+identity[:20])
        try:
            check()
            candidate=review_source_overlays(settings,result,folder,intervals=scopes,generate=generate)
            approved=usable_intervals(candidate)
            if not all(any(x<=a and b<=y for x,y in approved) for a,b in previous):
                saved.update(status='rejected',reason='New joint approval would discard a prior accepted interval')
            else:
                candidate['interval_function_review_required']=sorted([
                    [w['source_start'],w['source_end']] for w in candidate['reviewed_intervals']])
                _fresh_explicit_reviews(result,candidate)
                check();candidate=review(candidate)
                if editing_ready(candidate) and usable_seconds(candidate)>usable_seconds(result):
                    candidate.setdefault('interval_recovery_history',[]).append({
                        'identity':identity,'scope':[span['start'],span['end']],
                        'receipt_path':str(receipt.resolve()),'reason':span['reason'],'policy':POLICY})
                    result=candidate;saved.update(status='accepted',source=copy.deepcopy(result))
                else:saved.update(status='rejected',reason='Normal function/portrait reviews did not establish added usable footage')
        except Exception as exc:
            from .model_service import ModelServiceUnavailable
            if isinstance(exc,ModelServiceUnavailable):
                saved.update(status='service_wait',reason=str(exc));record(receipt,saved);raise
            from .source_review_status import ReviewResponseInvalid, NoApprovedOverlayIntervals
            if not isinstance(exc,(ReviewResponseInvalid,NoApprovedOverlayIntervals)):
                from .source_preparation import PreparationEvidenceWaiting
                raise PreparationEvidenceWaiting('짧은 구간 검토의 파일·승인 근거 확인 대기 · '+str(exc)) from exc
            outcome=failed_outcome('overlay',exc,source)
            saved.update(status=outcome['status'],outcome=outcome,reason=str(exc)[:1000])
        saved['finished']=time.time();record(receipt,saved)
        result.setdefault('interval_recovery_attempts',[])
        item={k:v for k,v in saved.items() if k!='source'}
        if not any(r.get('identity')==identity for r in result['interval_recovery_attempts']):
            result['interval_recovery_attempts'].append(item)
        if sufficient(result):break
    return result
