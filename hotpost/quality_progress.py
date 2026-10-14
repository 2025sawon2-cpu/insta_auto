"""Evidence-bound quality decisions, separate from cumulative render usage.

The ledger is part of the task's transactional JSON. Identity excludes queue IDs,
review prose, scores, filenames and executable contract hashes. Render contracts
still govern cache compatibility; they cannot reopen a failed quality method.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
from pathlib import Path

POLICY = 'quality-progress-20261013-v1'
VISUAL = {'scene_gap', 'repetition', 'watermark'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def text(value):
    return re.sub(r'\W+', '', str(value or '').casefold())


def load_plan(state, edit_id=None):
    edit = next((e for e in state.get('edits', []) if e.get('id') == (edit_id or state.get('edit_id'))), {})
    try:
        return json.loads(Path(edit['plan_path']).read_text('utf-8'))
    except (OSError, ValueError, KeyError):
        return {}


def origin(source):
    # A known parent hash outranks a derivative hash. A canonical origin URL
    # also keeps re-encoded downloads with new IDs in the same source lineage.
    if source.get('original_sha256'):
        return ['sha', source['original_sha256']]
    url = source.get('origin_url') or source.get('original_url') or source.get('url')
    if url:
        from .source_urls import canonical_video_key
        return ['url', canonical_video_key(url)]
    return ['sha', source.get('original_sha256') or source.get('sha256')]


def window(source, start, end):
    interval = source.get('original_interval') or {}
    rate = (source.get('retiming') or {}).get('playback_rate', 1) or 1
    offset = interval.get('start', 0) or 0
    local_start, local_end = float(start or 0), float(end or 0)
    exposure = None
    if source.get('path') and source.get('sha256') and Path(source['path']).is_file():
        try:
            from .source_frame_timing import probe_native_timing
            timing = probe_native_timing(source['path'], source['sha256'])
            # Studio renders 30 fps. Compare the actual decoded images exposed
            # at those output ticks, rather than subframe timestamp spellings.
            frames = timing.get('frames', [])
            count = max(0, round((local_end-local_start)*30))
            shown = []
            for index in range(count):
                stamp = local_start+index/30
                frame = next((f for f in frames if f['start'] <= stamp < f['end']), None)
                if frame is None: break
                shown.append(round(offset+frame['start']*rate, 6))
            if count and len(shown) == count:
                exposure = digest(shown)
        except (OSError, ValueError, RuntimeError):
            pass  # Missing native evidence is never presented as a new frame.
    return {'origin': origin(source), 'start': round(offset + local_start*rate, 3),
            'end': round(offset + float(end or 0)*rate, 3),
            'parent_sha256':source.get('original_sha256') or source.get('sha256'),
            'origin_url':canonical_origin_url(source),
            'source_fps': (source.get('video_meta') or {}).get('fps') or 30,
            'native_render_exposure': exposure,
            'masks': [{k:m.get(k) for k in ('source_start', 'source_end', 'rectangle', 'strength', 'expected_scale')}
                      for m in source.get('watermark_masks', [])],
            'geometry': source.get('portrait_geometry')}


def canonical_origin_url(source):
    from .source_urls import canonical_video_key
    url=source.get('origin_url') or source.get('original_url') or source.get('url')
    return canonical_video_key(url) if url else None


def same_window(a,b):
    if not a or not b:return a==b
    lineage=(a.get('origin')==b.get('origin') or
             a.get('parent_sha256') and a.get('parent_sha256')==b.get('parent_sha256') or
             a.get('origin_url') and a.get('origin_url')==b.get('origin_url'))
    def frames(value):
        try:
            rate = float(value.get('source_fps') or 30)
            if not math.isfinite(rate) or rate <= 0: return None
            return tuple(math.floor(float(value[k])*rate+1e-8) for k in ('start','end'))
        except (TypeError, ValueError, KeyError): return None
    native = a.get('native_render_exposure') and b.get('native_render_exposure')
    same_time = (a['native_render_exposure']==b['native_render_exposure'] if native else
        all(a.get(k)==b.get(k) for k in ('start','end')) or (frames(a) is not None and frames(a)==frames(b)))
    return bool(lineage and same_time and all(a.get(k)==b.get(k) for k in ('masks','geometry','mask_application')))


def same_body(a,b):
    return len(a)==len(b) and all(same_window(x.get('view'),y.get('view')) for x,y in zip(a,b))


def same_output(a,b):
    caption_same = (a.get('caption_timeline') or []) == (b.get('caption_timeline') or [])
    return caption_same and all(a.get(k)==b.get(k) for k in ('script','voice','cover','audio_repair')) and same_body(a['body'],b['body'])


def same_method(a,b):
    if a.get('stage')!=b.get('stage') or a.get('defects')!=b.get('defects'):return False
    left=a.get('facts',[]);right=b.get('facts',[])
    if len(left)!=len(right):return False
    def same_fact(x,y):
        ignore={'replacement','reason','frame_ids','proof_mode'}
        return ({k:v for k,v in x.items() if k not in ignore}=={k:v for k,v in y.items() if k not in ignore}
                and same_window(x.get('replacement'),y.get('replacement')))
    return all(any(same_fact(x,y) for y in right) for x in left)


def beat_view(plan, beat):
    shot = next((s for s in plan.get('shots', []) if s.get('id') == beat.get('selected_shot_id')), {})
    source = next((s for s in plan.get('sources', []) if s.get('id') == shot.get('source_id')), {})
    if not source:
        return None
    result=window(source, beat.get('source_start', shot.get('start')), beat.get('source_end', shot.get('end')))
    application=next((row for row in (plan.get('quality_mask_application') or {}).get('material',[])
                      if row.get('beat_id')==beat.get('id')),None)
    if application:result['mask_application']=copy.deepcopy(application)
    return result


def cover_view(plan):
    spec = plan.get('cover_spec') or {}
    source = spec.get('source') or {}
    actual = {k:source.get(k) for k in
        ('source_sha256', 'timestamp', 'source_timestamp', 'crop', 'frame_sha256') if k in source}
    crop = source.get('cover_crop_evidence') or {}
    if crop:
        actual['crop_evidence']={k:crop.get(k) for k in
            ('source_sha256','timestamp','native_frame_sha256','original_frame_sha256',
             'image_sha256','crop','canvas','fit','watermark_masks') if k in crop}
    return {'lines': spec.get('lines'), 'source': actual}


def target(issue, plan):
    from .quality_issue_scope import is_cover_scene_gap
    if issue.get('kind') == 'cover' or is_cover_scene_gap(issue):
        return 'cover'
    beat = next((b for b in plan.get('beats', []) if b.get('id') == issue.get('beat_id')), {})
    # Narration is a stable target when beat numbering or timeline positions move.
    # Unbound global findings retain a conservative whole-body identity.
    return text(beat.get('text')) or 'body'


def finding(issue, plan):
    anchor = target(issue, plan)
    kind = 'cover' if anchor == 'cover' else issue.get('kind')
    return {'id': digest([kind, anchor]), 'kind': kind, 'target': anchor,
            'observation': copy.deepcopy(issue), 'blocking': True,
            'lineage':beat_view(plan,next((b for b in plan.get('beats',[]) if b.get('id')==issue.get('beat_id')),{}))}


def linked_finding(issue,plan,ledger):
    from difflib import SequenceMatcher
    row=finding(issue,plan)
    if row['id'] in ledger['defects']:return row
    candidates=[d for d in ledger['defects'].values() if d['kind']==row['kind'] and d['target'] not in {'body','cover'}
        and (d.get('lineage') and same_window(d['lineage'],row.get('lineage')) or
             SequenceMatcher(None,d['target'],row['target']).ratio()>=.8)]
    if len(candidates)==1:
        row['id']=candidates[0]['id']
    return row


def projection(plan):
    return {'script': text(plan.get('script_text')),
            'voice': (plan.get('voice') or {}).get('sha256'),
            'body': [{'text': text(b.get('text')), 'view': beat_view(plan, b)} for b in plan.get('beats', [])],
            'cover': cover_view(plan), 'audio_repair':plan.get('quality_audio_repair'),
            'caption_timeline': [{'text':text(c.get('text')),
                'start':c.get('start'), 'end':c.get('end')}
                for c in plan.get('cues', [])]}


def ensure(state):
    quality = state.setdefault('daily_quality', {})
    ledger = quality.setdefault('progress_policy', {'policy': POLICY, 'defects': {}, 'reviews': [],
        'attempts': [], 'decisions': [], 'best': None, 'legacy': {
            'pending': quality.get('pending'), 'repair_round': quality.get('repair_round', 0),
            'max_repairs': quality.get('max_repairs'), 'render_accounting': copy.deepcopy(quality.get('render_accounting', []))}})
    # Import immutable history without changing selected output, stop flags or
    # accounting. Missing historical evidence never implies a quality pass.
    for review in quality.get('reviews', []):
        observe(state, review, ledger=ledger, historical=True)
    for entry in [*ledger['reviews'], *ledger['attempts']]:
        output=entry.get('output')
        if output is not None and 'caption_timeline' not in output:
            plan=load_plan(state,entry.get('edit_id')) if entry.get('edit_id') else {}
            if plan:
                output['caption_timeline']=projection(plan)['caption_timeline']
    return ledger


def decide(state, action, reason, **details):
    ledger = state['daily_quality']['progress_policy']
    value = {'action': action, 'reason': reason, **details}
    if not ledger['decisions'] or any(ledger['decisions'][-1].get(k) != v for k,v in value.items()):
        ledger['decisions'].append({**value, 'at': time.time()})
    ledger['decision'] = value
    return value


def actual_review_rows(ledger):
    """Preserve corrected raw observations while excluding preparation from QA."""
    excluded = {row.get('review_identity') for row in ledger.get('observation_corrections', [])
                if row.get('classification') == 'preparation_only' and row.get('review_identity')}
    return [row for row in ledger.get('reviews', [])
            if row.get('identity') not in excluded and not row.get('pre_render_scene_gap')]


def observe(state, result, *, ledger=None, historical=False):
    ledger = ledger if ledger is not None else ensure(state)
    if result.get('pre_render_scene_gap'):
        # A failed selection is not a review of any newly rendered output.
        # Keep legacy reports verbatim, but never import their omitted defects
        # as resolutions of the last actual render.
        return {'preparation_failure': True, 'passed': False, 'resolved': [],
                'introduced': [], 'conflict': False}
    plan = load_plan(state, result.get('edit_id'))
    output = projection(plan)
    identity = digest([result.get('render_sha256') or result.get('edit_id'), output,
                       result.get('pre_render_scene_gap', False), result.get('evidence_recheck',False)])
    actual_reviews = actual_review_rows(ledger)
    previous = next((r for r in actual_reviews if r['identity'] == identity), None)
    issues = [linked_finding(i, plan,ledger) for i in result.get('issues', [])]
    ids = sorted({i['id'] for i in issues})
    if previous:
        if previous['defect_ids'] != ids:
            if not historical:
                decide(state, 'recheck', '동일 출력의 검토 판정 상충 · 해당 실제 근거 확인 필요',
                       review_identity=identity, previous_defects=previous['defect_ids'], current_defects=ids)
            return {'duplicate': True, 'conflict': True}
        return {'duplicate': True, 'conflict': False}
    if not plan and not result.get('pre_render_scene_gap'):
        if not historical:decide(state,'wait','검토 계획 파일 소실 · 과거 품질과 최선 결과 보존')
        return {'conflict':True,'passed':False,'missing_evidence':True}
    confirmed=next((r for r in reversed(actual_reviews) if not r.get('conflict')), None)
    old_ids = set(confirmed['defect_ids']) if confirmed else set()
    current_ids = set(ids)
    resolved = old_ids-current_ids
    introduced = current_ids-old_ids if actual_reviews else set()
    # Count resolution only on an actually changed, reviewed output. Merely
    # omitting a finding on identical inputs is a disagreement, not progress.
    prior_output = confirmed['output'] if confirmed else None
    def target_changed(did):
        defect = ledger['defects'][did]
        if not prior_output:return False
        if defect['kind'] == 'cover':return output['cover'] != prior_output['cover']
        if defect['kind'] in {'script_fact','script_clarity','voice_consistency','caption_sync'}:
            return output['script'] != prior_output['script'] or output['voice'] != prior_output['voice'] or (
                defect['kind'] == 'caption_sync' and (output.get('caption_timeline') != prior_output.get('caption_timeline')
                    or result.get('audio_timing_audit',{}).get('passed') is True))
        anchor = defect['target']
        old=[b for b in prior_output['body'] if anchor=='body' or b['text']==anchor]
        new=[b for b in output['body'] if anchor=='body' or b['text']==anchor]
        if not new:
            # Renaming/paraphrasing a target cannot erase unchanged bad footage.
            return bool(old) and not all(any(same_window(b['view'],v['view']) for v in output['body']) for b in old)
        return not same_body(old,new)
    confirmed_recheck=bool(result.get('evidence_recheck') and result.get('recheck_evidence'))
    conflict = bool(any(not target_changed(did) for did in resolved) and not result.get('pre_render_scene_gap') and not confirmed_recheck)
    if conflict:
        resolved = set()
    for item in issues:
        entry = ledger['defects'].setdefault(item['id'], {**item, 'first_seen': identity, 'history': []})
        status = 'recurred' if entry.get('status') == 'resolved' else 'unresolved'
        entry.update(status=status, observation=item['observation'],target=item['target'],lineage=item['lineage'])
        entry['history'].append({'review': identity, 'status': status,
            'render_sha256': result.get('render_sha256'), 'plan_sha256': result.get('plan_sha256'),
            'evidence': [f for g in result.get('groups', []) for f in g.get('frames', [])
                         if f.get('beat_id') == item['observation'].get('beat_id')],
            'observation': item['observation']})
    for did in resolved:
        ledger['defects'][did]['status'] = 'resolved'
        ledger['defects'][did]['history'].append({'review': identity, 'status': 'resolved'})
    row = {'identity': identity, 'edit_id': result.get('edit_id'), 'defect_ids': ids, 'output': output,
           'resolved': sorted(resolved), 'introduced': sorted(introduced), 'conflict': conflict,
           'improved': bool(resolved) and not introduced and not conflict,
           'passed': bool(result.get('passed')) and not conflict,
           'audio_timing_audit':copy.deepcopy(result.get('audio_timing_audit'))}
    ledger['reviews'].append(row)
    best = ledger.get('best')
    if not result.get('pre_render_scene_gap') and not conflict and (best is None or row['passed'] or
            (row['improved'] and set(ids) < set(best['defect_ids']))):
        ledger['best'] = copy.deepcopy(row)
    # Record prior failed render methods for cycle detection even after migration.
    if issues and plan:
        key = digest(['render', output])
        if not any(a['key'] == key for a in ledger['attempts']):
            ledger['attempts'].append({'key': key, 'stage': 'render', 'status': 'failed',
                'defects': ids, 'output': output, 'edit_id': result.get('edit_id')})
    for attempt in ledger['attempts']:
        if attempt.get('edit_id') == result.get('edit_id'):
            attempt.update(status='passed' if row['passed'] else 'failed', review=identity)
    if not historical:
        decide(state, 'recheck' if conflict else 'complete' if row['passed'] else
               'continue' if row['improved'] else 'switch',
               '동일 출력 판정 상충' if conflict else '실제 품질 기준 충족' if row['passed'] else
               '실제 결함 해결 · 잔존 결함의 새 방법 검토' if row['improved'] else '잔존 결함 · 다른 근거 있는 방법 필요',
               resolved=row['resolved'], remaining=ids, regressions=row['introduced'])
    return row


def unresolved(state):
    ledger = ensure(state)
    plan = load_plan(state)
    rows = [linked_finding(i,plan,ledger) for i in state['daily_quality'].get('feedback', [])]
    for row in rows:
        ledger['defects'].setdefault(row['id'], {**row, 'status': 'unresolved', 'history': []})
    return rows


def hypothesis(state, stage):
    """Propose a method from defect-bound facts, never the whole file inventory."""
    quality = state['daily_quality']
    defects = unresolved(state)
    plan = load_plan(state)
    sources = {s.get('id'): s for s in state.get('sources', [])}
    facts = []
    targets = {d['id'] for d in defects}
    if stage == 'rewrite':
        facts = [{'target': d['id'], 'original': text(state.get('reviewed_original_text') or state.get('original_text')),
                  'method': 'contract_bound_narration_correction'}
                 for d in defects if d['kind'] in {'script_fact', 'script_clarity', 'voice_consistency'}]
    else:
        from .mask_application_evidence import approved_material
        for material in approved_material(state):
            defect=next((d for d in defects if d['kind']=='watermark' and d['target']==material['target']),None)
            if defect:
                facts.append({'target':defect['id'],'method':'approved_mask_application_pixels',
                              'mask_application':material})
        for requirement in quality.get('scene_requirements', {}).get('requirements', []):
            did = linked_finding(requirement,plan,state['daily_quality']['progress_policy'])['id']
            if did not in targets or not requirement.get('covered'):
                continue
            for match in requirement.get('matches', []):
                source = sources.get(match.get('source_id'))
                if source:
                    replacement=window(source,match.get('source_start'),match.get('source_end'))
                    anchor=next((d['target'] for d in defects if d['id']==did),None)
                    used=[beat_view(plan,b) for b in plan.get('beats',[]) if anchor=='body' or text(b.get('text'))==anchor]
                    if any(same_window(replacement,v) for v in used):continue
                    facts.append({'target': did, 'replacement': replacement,
                        'proof_mode': match.get('proof_mode'),
                        'reason': match.get('supporting_reason') or requirement.get('coverage_reason'),
                        'frame_ids': match.get('supporting_frame_ids') or match.get('evidence_frame_ids')})
        for d in defects:
            if d['kind'] == 'cover':
                lines = quality.get('thumbnail_lines')
                if lines and lines != (plan.get('cover_spec') or {}).get('lines'):
                    facts.append({'target': d['id'], 'lines': lines, 'method': 'cover_copy'})
                # Explicit raster crop receipt must be approved in normal cover
                # selection. Code version/metadata alone is not a replacement.
                crop = quality.get('cover_repair_evidence') or {}
                if valid_cover_evidence(state,crop):
                    facts.append({'target': d['id'], 'crop': {k:crop.get(k) for k in
                        ('image_sha256', 'source_sha256', 'source_timestamp', 'rectangle')}, 'method': 'cover_pixels'})
            elif d['kind'] == 'caption_sync':
                facts.append({'target': d['id'], 'method': 'pcm_clock_repair',
                              'voice': next((v.get('sha256') for v in state.get('voices', []) if v.get('id') == state.get('voice_id')), None),
                              'audit':audio_repair_evidence(state)})
            elif d['kind'] in {'script_fact','script_clarity','voice_consistency'}:
                script = next((s.get('text') for s in state.get('scripts',[]) if s.get('id') == state.get('script_id')), '')
                voice = next((v.get('sha256') for v in state.get('voices',[]) if v.get('id') == state.get('voice_id')), None)
                if text(script) != text(plan.get('script_text')) or voice != (plan.get('voice') or {}).get('sha256'):
                    facts.append({'target': d['id'], 'method':'reviewed_narration_repair',
                                  'script':text(script), 'voice':voice})
    # Evidence descriptions and frame IDs do not make a new method.
    material = [{k:v for k,v in f.items() if k not in {'reason', 'frame_ids'}} for f in facts]
    material = sorted({json.dumps(f, sort_keys=True, ensure_ascii=False) for f in material})
    return {'stage': stage, 'defects': sorted(targets), 'facts': facts,
            'key': digest([stage, material]), 'grounded': bool(facts),
            'why': '실제 결함에 연결된 승인 구간·표지 문구·음성 시간축 또는 사실 보완'}


def hold(state, reason, action='wait'):
    ensure(state)
    decide(state, action, reason)
    state['daily_quality'].update(status='needs_attention', pending='scene_wait')
    state.update(status='source_wait', message=reason)


def permit(state, stage, *, reserve=False, job_id=None):
    ledger = ensure(state)
    if state.get('automation', {}).get('paused_by_user'):
        decide(state, 'wait', '사용자 중지 유지')
        return None
    if state['daily_quality'].get('pending') in {'exhausted', 'failed'}:
        decide(state, 'wait', '과거 중단 유지 · 실제 새로운 수정 근거의 별도 평가 필요')
        return None
    method = hypothesis(state, stage)
    if not method['grounded']:
        hold(state, '잔존 결함에 사용할 새 수정 근거 대기')
        return None
    previous = next((a for a in ledger['attempts'] if a['key'] == method['key'] or same_method(a,method)), None)
    if previous and (previous.get('job_id') != job_id or not job_id or previous.get('status') not in {'planned','running'}):
        hold(state, '동일·동등한 실패 방법 또는 순환 차단 · 다른 수정 근거 대기', 'stop_method')
        return None
    if reserve and not previous:
        ledger['attempts'].append({**copy.deepcopy(method), 'job_id': job_id, 'status': 'planned'})
    decide(state, 'continue', method['why'], method_key=method['key'], targets=method['defects'])
    return method


def guard_render(state, plan, job_id):
    ledger = ensure(state)
    application=plan.get('quality_mask_application')
    if application:
        from .mask_application_evidence import approved_material, frozen_selection, preserves_render_inputs
        material=approved_material(state,application.get('receipt'))
        if (not material or material!=application.get('material') or
                frozen_selection(plan)!=application['receipt'].get('selection_binding') or
                not preserves_render_inputs(plan,load_plan(state))):
            return '동일 native 영상·승인 마스크·실제 ROI 픽셀 변화의 공식 적용 검수 근거 불일치'
    candidate = projection(plan)
    if plan.get('quality_audio_repair') and not valid_audio_repair(state,plan):
        return '해당 출력·승인 음성에 결속한 실제 오디오 시간축 오류 근거 없음'
    key = digest(['render', candidate])
    if any((a['key'] == key or a.get('output') and same_output(a['output'],candidate))
           and (a.get('job_id') != job_id or a.get('status') not in {'planned','running'})
           for a in ledger['attempts']):
        return '실제 선택 소스·구간·순서·표지가 이전 실패 편집과 동일 · 순환 차단'
    before = projection(load_plan(state))
    defects = unresolved(state)
    relevant = False
    for d in defects:
        if d['kind'] == 'cover':
            relevant |= candidate['cover'] != before['cover']
        elif d['kind'] in {'script_fact', 'script_clarity', 'voice_consistency', 'caption_sync'}:
            relevant |= candidate['script'] != before['script'] or candidate['voice'] != before['voice']
            if d['kind'] == 'caption_sync':
                relevant |= bool(plan.get('audio_timing_repair')) or candidate.get('caption_timeline') != before.get('caption_timeline')
        else:
            old = [b for b in before['body'] if d['target'] == 'body' or b['text'] == d['target']]
            new = [b for b in candidate['body'] if d['target'] == 'body' or b['text'] == d['target']]
            relevant |= not same_body(old,new)
    if defects and not relevant:
        return '잔존 결함의 실제 출력 입력이 바뀌지 않음 · 무관한 소스 추가는 보완 근거가 아님'
    if not any(a['key'] == key for a in ledger['attempts']):
        ledger['attempts'].append({'key': key, 'stage': 'render', 'status': 'running',
            'job_id': job_id, 'edit_id': job_id, 'defects': [d['id'] for d in defects], 'output': candidate})
    return None


class QualityProgressHold(ValueError):
    def __init__(self,message,*,waiting=False):
        super().__init__(message)
        self.waiting=waiting


def finish_attempt(state, job, result=None, *, failed=False):
    ledger=ensure(state)
    for attempt in ledger['attempts']:
        if attempt.get('job_id') == job.get('id'):
            if attempt.get('status') not in {'planned','running'}:continue
            attempt['status']='failed' if failed else 'rendered' if attempt.get('stage')=='render' else 'completed'
            if result and result.get('id'):attempt['edit_id']=result['id']


def record_preparation_failure(state, job, issues, *, thumbnail_lines=None):
    """Append a claim-bound selection failure without changing output reviews."""
    ledger = ensure(state)
    quality = state['daily_quality']
    key = digest([job.get('id'), job.get('payload', {}).get('quality_method', {}).get('key'), issues, thumbnail_lines])
    rows = quality.setdefault('preparation_failures', [])
    if not any(row.get('identity') == key for row in rows):
        rows.append({'identity': key, 'job_id': job.get('id'), 'at': time.time(),
                     'stage': 'selection', 'no_render': True,
                     'failure_reason': copy.deepcopy(issues),
                     'thumbnail_proposal': copy.deepcopy(thumbnail_lines),
                     'actual_edit_id': state.get('edit_id'),
                     'quality_method': copy.deepcopy(job.get('payload', {}).get('quality_method')),
                     'checkpoint': copy.deepcopy(job.get('checkpoint', {}))})
    for attempt in ledger['attempts']:
        if attempt.get('job_id') == job.get('id') and attempt.get('status') in {'planned', 'running'}:
            attempt['status'] = 'preparation_failed'
            attempt['preparation_failure_identity'] = key
    hold(state, '렌더 전 장면 선택 근거 부족 · 기존 실제 검수와 영상 보존 · 새 승인 구간 대기')
    return key


def relevant_coverage_gain(state, previous):
    """Only an unused method linked to an outstanding defect can release editing."""
    ledger=ensure(state)
    method=hypothesis(state,'reedit')
    if not method['grounded']:return False
    if any(a['key']==method['key'] or same_method(a,method) for a in ledger['attempts']):return False
    before=copy.deepcopy(state)
    before['daily_quality']['scene_requirements']=previous
    prior_method=hypothesis(before,'reedit')
    crop=state['daily_quality'].get('cover_repair_evidence') or {}
    old_cover=cover_view(load_plan(state))['source']
    if valid_cover_evidence(state,crop) and crop['image_sha256']!=old_cover.get('frame_sha256'):
        return True
    if method['key']==prior_method['key'] or same_method(method,prior_method):return False
    # A new file/approval that is unrelated to any requirement is absent from
    # the method. Existing ready matches are useful once, regardless of count.
    return any(f.get('replacement') for f in method['facts'])


def queue_method(state, db, stage):
    ledger=ensure(state)
    method=hypothesis(state,stage)
    attempt=next((a for a in ledger['attempts'] if a['key']==method['key'] or same_method(a,method)),None)
    if db is not None and attempt and attempt.get('job_id'):
        row=db.execute('SELECT status FROM jobs WHERE id=?',(attempt['job_id'],)).fetchone()
        if row and row['status'] in {'queued','running'}:
            return permit(state,stage,job_id=attempt['job_id'])
        if row:
            state['daily_quality']['repair_queue_hold']={'job_id':attempt['job_id'],'job_status':row['status'],
                                                         'method_key':method['key']}
    return permit(state,stage)


def resume_assessment(state):
    """Explicit resume may propose new evidence, preserving the former stop."""
    ledger=ensure(state)
    method=hypothesis(state,'reedit')
    from .scene_requirements import coverage_current
    valid=(method['grounded'] and coverage_current(state)
           and not any(a['key']==method['key'] or same_method(a,method) for a in ledger['attempts']))
    if not valid:
        decide(state,'wait','과거 중단 유지 · 잔존 결함을 해결할 새로운 실제 근거 없음')
        return False
    quality=state['daily_quality']
    quality.setdefault('stop_history',[]).append({'pending':quality.get('pending'),
        'status':quality.get('status'),'repair_round':quality.get('repair_round',0),'at':time.time()})
    quality.update(pending='reedit',status='repair')
    decide(state,'continue','새 실제 수정 근거를 별도 평가하여 명시 재개',method_key=method['key'])
    return True


def audio_repair_evidence(state):
    audit=next((r.get('audio_timing_audit') for r in reversed(state['daily_quality'].get('reviews',[]))
                if not r.get('pre_render_scene_gap') and r.get('edit_id')==state.get('edit_id')
                    and r.get('audio_timing_audit')), {})
    if not audit:
        audit=next((r.get('audio_timing_audit') for r in reversed(actual_review_rows(state['daily_quality'].get('progress_policy',{})))
                    if r.get('edit_id')==state.get('edit_id') and r.get('audio_timing_audit')), {})
    return {k:audit.get(k) for k in ('method','duration_delta_seconds','anchors')}


def valid_audio_repair(state,plan):
    import math
    receipt=plan.get('quality_audio_repair') or {}
    audit=audio_repair_evidence(state)
    delta=audit.get('duration_delta_seconds')
    return bool(receipt.get('method')=='approved-voice-pcm-clock'
        and receipt.get('voice_sha256')==(load_plan(state).get('voice') or {}).get('sha256')
        and receipt.get('voice_sha256')==(plan.get('voice') or {}).get('sha256')
        and receipt.get('audit')==audit and audit.get('method')
        and isinstance(delta,(int,float)) and math.isfinite(delta)
        and (abs(delta)>.12 or any(isinstance(a.get('offset_seconds'),(int,float))
             and abs(a['offset_seconds'])>.15 for a in audit.get('anchors') or [])))


def valid_cover_evidence(state, receipt):
    if receipt.get('reviewed') is not True:return False
    from .source_quality import sha256_file, editing_ready
    source=next((s for s in state.get('sources',[]) if s.get('sha256')==receipt.get('source_sha256')),None)
    try:
        if not source or not editing_ready(source) or sha256_file(Path(source['path']))!=source['sha256']:return False
        if sha256_file(Path(receipt['image_path']))!=receipt['image_sha256']:return False
        selected=receipt['selection']
        plan=load_plan(state)
        prepared=receipt.get('prepared_plan') or {}
        if prepared:
            from .scene_requirements import input_signature
            if prepared.get('scope')!=input_signature(state) or sha256_file(Path(prepared['path']))!=prepared.get('plan_sha256'):return False
            plan=json.loads(Path(prepared['path']).read_text('utf-8'))
        if selected.get('source_sha256')!=source['sha256'] or selected.get('timestamp')!=receipt.get('source_timestamp'):return False
        stamp=receipt.get('source_timestamp')
        if not isinstance(stamp,(int,float)) or not 0<=stamp<float(source.get('video_meta',{}).get('duration',0)):return False
        if not any(w['source_start']<=stamp<=w['source_end'] for w in source.get('reviewed_intervals',[])):return False
        if receipt.get('watermark_masks',[])!=source.get('watermark_masks',[]):return False
        if plan.get('sources'):
            planned=next((s for s in plan['sources'] if s.get('id')==selected.get('source_id')),None)
            if not planned or planned.get('sha256')!=source['sha256']:return False
            by_shot={s['id']:s for s in plan.get('shots',[])}
            if not any(by_shot.get(b.get('selected_shot_id'),{}).get('source_id')==selected.get('source_id')
                       and b.get('source_start',0)<=stamp<=b.get('source_end',0) for b in plan.get('beats',[])):return False
        confirmation=selected.get('single_frame_confirmation') or {}
        rows=confirmation.get('reviews') or [confirmation]
        if not any(r.get('eligible') is True and r.get('faces_present') is False
                   and r.get('face_blur_used') is False for r in rows):return False
        if selected.get('crop'):
            from .cover_product_crop import validate_crop_selection
            validate_crop_selection(plan,selected)
        return selected.get('frame_sha256')==receipt['image_sha256']
    except (OSError,ValueError,KeyError,TypeError):return False
