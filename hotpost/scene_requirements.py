"""Match concrete repair requirements to current approved footage before rendering."""
import hashlib
import json
import math
from pathlib import Path

from .source_quality import editing_ready
from .quality_issue_scope import is_cover_scene_gap

POLICY='scene-coverage-v6-explicit-proof-mode'
REPAIR_SIGNATURE_POLICY='repair-render-v3-input-and-contracts'
WINDOW_FRAME_LIMIT=5
CANDIDATE_ATTACHMENT_BYTES=6*1024*1024


def _evidence_review(source):
    """Reuse independent five-frame approval on the same rendered crop, when available."""
    from .source_presentation import valid_review
    from .source_mask_review import GEOMETRY
    mask=source.get('mask_review') or {}
    if not valid_review(source):return mask
    presentation=source['presentation_review']
    geometry=(presentation.get('scope') or {}).get('geometry') or {}
    if (mask.get('source_sha256')==source.get('sha256') and mask.get('reviewer')
            and mask.get('proposal_sha256') and mask.get('geometry')==GEOMETRY
            and all(geometry.get(k)==v for k,v in GEOMETRY.items()) and mask.get('evidence_frames')):
        return mask
    return presentation


def _window_frames(frames,window):
    available=sorted((f for f in frames if window['source_start']<=f['source_timestamp']<=window['source_end']),
                     key=lambda f:(f['source_timestamp'],f['frame_id']))
    count=min(WINDOW_FRAME_LIMIT,len(available))
    if count<2:return available
    return [available[round(i*(len(available)-1)/(count-1))] for i in range(count)]


def _timing_for_source(state,source):
    review=_evidence_review(source)
    return (review.get('native_frame_timing') or state.get('daily_quality',{}).get('scene_requirements',{})
            .get('source_native_frame_timings',{}).get(source.get('sha256')))


def _match_render_end(state,source,match):
    """Only the visible coded frame's proven exposure can extend a sampled endpoint."""
    from .source_frame_timing import frame_exposure
    frames={f.get('frame_id'):f for f in _evidence_review(source).get('evidence_frames',[]) if isinstance(f,dict)}
    timing=_timing_for_source(state,source)
    end=match['source_end']
    for fid in match.get('evidence_frame_ids',[]):
        exposure=frame_exposure(frames.get(fid,{}),source.get('sha256'),timing)
        if exposure and any(w['source_start']<=match['source_start']<exposure['end']<=w['source_end']+1e-6
                            for w in source.get('reviewed_intervals',[])):
            end=max(end,exposure['end'])
    return end


def required_scenes(state):
    return [i for i in state.get('daily_quality',{}).get('feedback',[])
            if i.get('kind') in {'scene_gap','repetition','watermark'} and not is_cover_scene_gap(i)]


def _requires_native_proof(requirement):
    return requirement.get('kind') == 'scene_gap' or any(
        m.get('proof_mode') is not None or m.get('supporting_frame_ids')
        for m in requirement.get('matches', []))


def requirements_key(state):
    return hashlib.sha256(json.dumps(required_scenes(state),sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def coverage_current(state):
    expected=required_scenes(state)
    if not expected:return True
    receipt=state.get('daily_quality',{}).get('scene_requirements',{})
    current=bool(receipt.get('ready') and receipt.get('policy')==POLICY
                and receipt.get('signature')==input_signature(state)
                and receipt.get('requirements_key')==requirements_key(state)
                and len(receipt.get('requirements',[]))==len(expected)
                and all(row.get('covered') is True and row.get('matches')
                        and all(row.get(k)==v for k,v in original.items())
                        for original,row in zip(expected,receipt['requirements'])))
    if not current:return False
    from .scene_requirement_context import build_scene_requirement_context
    context=build_scene_requirement_context(state,expected)
    if not context['verified'] or receipt.get('context_signature')!=context['signature']:return False
    from .source_quality import sha256_file
    sources={s.get('id'):s for s in state.get('sources',[])}
    for requirement in receipt['requirements']:
        for match in requirement['matches']:
            source=sources.get(match.get('source_id'),{})
            path=Path(source.get('path',''))
            if (not editing_ready(source) or not path.is_file() or source.get('sha256')!=match.get('source_sha256')
                    or sha256_file(path)!=match.get('source_sha256')):return False
            review=_evidence_review(source)
            if review.get('source_sha256')!=source.get('sha256'):return False
            frames={f.get('frame_id'):f for f in review.get('evidence_frames',[]) if isinstance(f,dict)}
            for fid in match.get('evidence_frame_ids',[]):
                frame=frames.get(fid,{})
                frame_path=Path(frame.get('path',''))
                if not frame_path.is_file() or not frame.get('sha256') or sha256_file(frame_path)!=frame['sha256']:return False
            if _requires_native_proof(requirement) and _support_times(state,source,match) is None:return False
    return True


def clear_resolved_errors(target, incoming):
    """Keep historical diagnostics without a resolved error poisoning current eligibility."""
    import time
    for stage,receipt_key in (('overlay','mask_review'),('presentation','presentation_review')):
        error_key=stage+'_review_error'
        receipt=incoming.get(receipt_key) or {}
        if (target.get(error_key) and not incoming.get(error_key)
                and receipt.get('source_sha256')==incoming.get('sha256')):
            target.setdefault('review_error_history',[]).append({'stage':stage,'error':target[error_key],
                'source_sha256':incoming['sha256'],'resolved_at':time.time()})
            target.pop(error_key,None)


def clear_cached_review_errors(source):
    """A completed, current, hash-bound receipt can resolve its older transport error."""
    from .source_overlay_review import POLICY as overlay_policy
    from .source_presentation import valid_review
    stages=[]
    if (source.get('overlay_review_error') and source.get('overlay_review_policy')==overlay_policy
            and (source.get('mask_review') or {}).get('source_sha256')==source.get('sha256')
            and source.get('reviewed_intervals')):
        stages.append('overlay')
    if source.get('presentation_review_error') and valid_review(source):
        stages.append('presentation')
    for stage in stages:
        incoming=dict(source);incoming.pop(stage+'_review_error',None)
        clear_resolved_errors(source,incoming)
    return bool(stages)


def merge_sources(existing, incoming):
    import copy
    merged=copy.deepcopy(existing)
    for source in incoming:
        old=next((s for s in merged if s.get('sha256')==source.get('sha256')),None)
        if old is None:
            if source.get('origin_url') and not source.get('original_interval') and any(
                    s.get('origin_url')==source['origin_url'] for s in merged):
                continue
            merged.append(copy.deepcopy(source))
        else:
            identity=old.get('id')
            denial=copy.deepcopy(old.get('manual_usage_review'))
            denied=(denial or {}).get('editing_eligible') is False
            old.update(copy.deepcopy(source));old['id']=identity
            clear_resolved_errors(old,source)
            if denied:old.update(editing_eligible=False,manual_usage_review=denial)
    return merged


def input_signature(state):
    def fields(value,keys):return {k:value.get(k) for k in keys if k in value}
    sources=[]
    for source in state.get('sources',[]):
        if not editing_ready(source):continue
        row=fields(source,('sha256','original_sha256','original_interval','retiming','source_role'))
        row['reviewed_intervals']=[fields(v,('source_start','source_end')) for v in source.get('reviewed_intervals',[])]
        row['watermark_masks']=[fields(v,('source_start','source_end','rectangle','strength','expected_scale'))
                                for v in source.get('watermark_masks',[])]
        row['function_limits']=fields(source.get('functional_review') or {},
            ('same_core_function','context_usable','context_usage_limits'))
        row['presentation_scope']=(source.get('presentation_review') or {}).get('scope')
        sources.append(row)
    script=next((s for s in state.get('scripts',[]) if s.get('id')==state.get('script_id')),None)
    voice=next((v for v in state.get('voices',[]) if v.get('id')==state.get('voice_id')),None)
    value = {'sources':sorted(sources,key=lambda s:s.get('sha256') or ''),
             'script':hashlib.sha256(script['text'].encode()).hexdigest() if script else state.get('script_id'),
             'voice':voice.get('sha256') if voice else state.get('voice_id'),
             'thumbnail_lines':state.get('daily_quality',{}).get('thumbnail_lines'),
             'reviewed_scene_rules':[fields(r,('pattern','source_sha256','start','end','relation'))
                                     for r in state.get('reviewed_scene_rules',[])],
             'edit_changes':state.get('feedback',{}).get('changes')}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def render_contract_signature():
    """The currently loaded decision/raster contracts are concrete render inputs."""
    from . import scene_analysis,scene_requirement_context,cover_selection,cover_product_crop
    from .studio_runtime.editing import _loaded_code_projection
    def code(function):return _loaded_code_projection(function.__code__)
    contracts={'signature_policy':REPAIR_SIGNATURE_POLICY,
        'semantic':{'observe':scene_analysis.OBSERVE_INSTRUCTION,'rank':scene_analysis.RANK_INSTRUCTION,
            'limits':[scene_analysis.MAX_BATCH_SHOTS,scene_analysis.MAX_BATCH_IMAGES],
            'observe_code':code(scene_analysis._observe),'rank_code':code(scene_analysis.analyze_shots)},
        'scene':{'policy':POLICY,'context_policy':scene_requirement_context.POLICY,
            'context_instruction':scene_requirement_context.SCENE_CONTEXT_INSTRUCTION,
            'context_code':code(scene_requirement_context.build_scene_requirement_context),
            'assess_code':code(assess),'anchors_code':code(anchor_selected_scenes),
            'validate_code':code(validate_selected_scenes),'support_code':code(_support_times)},
        'cover':{'policy':cover_selection.POLICY,'instruction':cover_selection.INSTRUCTION,
            'select_code':code(cover_selection.select_cover),'crop_review_code':code(cover_selection._review_product_crop),
            'eligibility_code':code(cover_selection.eligible_frames),'transport_code':code(cover_selection._cover_inline)},
        'crop':{'policy':cover_product_crop.POLICY,'instruction':cover_product_crop.PROPOSAL_INSTRUCTION,
            'propose_code':code(cover_product_crop.product_crop_candidates),'raster_code':code(cover_product_crop.crop_image),
            'binding_code':code(cover_product_crop._bound_source),'validate_code':code(cover_product_crop.validate_crop_selection)}}
    return hashlib.sha256(json.dumps(contracts,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def repair_render_signature(state):
    """Actual inputs and loaded contracts count; review prose and timestamps do not."""
    constraints=[]
    for requirement in state.get('daily_quality',{}).get('scene_requirements',{}).get('requirements',[]):
        matches=[{k:m.get(k) for k in ('source_sha256','source_start','source_end')}
                 for m in requirement.get('matches',[])]
        for row,match in zip(matches,requirement.get('matches',[])):
            if match.get('supporting_frame_ids'):
                row['supporting_frame_ids']=sorted(match['supporting_frame_ids'])
        constraints.append({'kind':requirement.get('kind'),'beat_id':requirement.get('beat_id'),
                            'matches':sorted(matches,key=lambda m:json.dumps(m,sort_keys=True))})
    value={'base':input_signature(state),'contracts':render_contract_signature(),
           'constraints':sorted(constraints,key=lambda r:json.dumps(r,sort_keys=True))}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def evidence_signature(state):
    """Cache both approval and rejection only while actual files and cited evidence stay identical."""
    from .source_quality import sha256_file
    facts=[]
    for source in state.get('sources',[]):
        path=Path(source.get('path',''))
        facts.append({'source':source.get('sha256'),'actual':sha256_file(path) if path.is_file() else None,
                      'eligible':editing_ready(source)})
        for key in ('mask_review','presentation_review','functional_review'):
            review=source.get(key) or {}
            facts.append({'kind':key,'bound':review.get('source_sha256'),'policy':review.get('policy'),
                          'native_timing':(review.get('native_frame_timing') or {}).get('metadata_sha256')})
            for frame in review.get('evidence_frames',[]):
                if not isinstance(frame,dict):continue
                path=Path(frame.get('path',''))
                facts.append({'frame':frame.get('frame_id'),'timestamp':frame.get('source_timestamp'),
                              'hash':frame.get('sha256'),'actual':sha256_file(path) if path.is_file() else None,
                              'native_exposure':frame.get('native_frame_exposure')})
    return hashlib.sha256(json.dumps(facts,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def assess(settings, state, generate=None):
    requirements = required_scenes(state)
    signature = input_signature(state)
    required_key = requirements_key(state)
    previous = state.get('daily_quality',{}).get('scene_requirements', {})
    policy=POLICY
    evidence_key=evidence_signature(state)
    from .scene_requirement_context import build_scene_requirement_context, SCENE_CONTEXT_INSTRUCTION
    context=build_scene_requirement_context(state,requirements) if requirements else None
    context_key=context['signature'] if context else None
    if (previous.get('policy')==policy and previous.get('signature') == signature
            and previous.get('requirements_key') == required_key and previous.get('evidence_key')==evidence_key
            and previous.get('context_signature')==context_key
            and (not previous.get('ready') or coverage_current(state))):
        return previous
    receipt = {'policy':policy,'signature':signature,'requirements_key':required_key,
               'evidence_key':evidence_key,'context_signature':context_key,
               'narration_context':context,'ready':not requirements,'requirements':[],'assessments':[]}
    if not requirements:
        return receipt
    if not context['verified']:
        receipt['holds']=context['holds']
        receipt['requirements']=[{**r,'covered':False,'coverage_reason':'Actual narration/product context is not verified'} for r in requirements]
        return receipt
    sources = [s for s in state.get('sources',[]) if editing_ready(s)]
    evidence = []
    for source in sources:
        from .source_quality import sha256_file
        path=Path(source.get('path',''))
        if not path.is_file() or sha256_file(path)!=source.get('sha256'):continue
        function=source.get('functional_review') or {}
        if function.get('reviewed') is not True or function.get('source_sha256')!=source['sha256']:continue
        review=_evidence_review(source)
        if review.get('source_sha256')!=source['sha256']:continue
        if review is source.get('mask_review') and (not review.get('reviewer') or not review.get('proposal_sha256')):continue
        frames=review.get('evidence_frames',[])
        windows=source.get('reviewed_intervals',[])
        valid = [f for f in frames if isinstance(f,dict) and f.get('sha256') and f.get('frame_id')
                 and type(f.get('source_timestamp')) in (int,float)
                 and any(w['source_start']<=f['source_timestamp']<=w['source_end'] for w in windows)
                 and Path(f.get('path','')).is_file() and sha256_file(Path(f['path']))==f['sha256']]
        if valid:
            from .source_frame_timing import probe_native_timing, frame_exposure
            timing=review.get('native_frame_timing')
            if not timing:
                try:timing=probe_native_timing(path,source['sha256'])
                except (RuntimeError,ValueError):timing=None
            if timing:
                receipt.setdefault('source_native_frame_timings',{})[source['sha256']]=timing
                valid=[{**f,'native_frame_exposure':frame_exposure(f,source['sha256'],timing)} for f in valid]
            evidence.append((source,valid))
    if generate is None:
        from .script_rewriter import _generate
        generate = _generate
    from .visual_media import review_frame_data
    inline_cache={}
    def inline(frame):
        key=(str(frame['path']),frame['sha256'])
        if key not in inline_cache:inline_cache[key]=review_frame_data(frame['path'])
        return inline_cache[key]
    chunks=[]
    for source,frames in evidence:
        for window in source['reviewed_intervals']:
            chosen=_window_frames(frames,window)
            if len(chosen)<2:continue
            cost=sum(len(inline(f)['data'])+1024 for f in chosen)
            if cost>CANDIDATE_ATTACHMENT_BYTES:
                receipt['assessments'].append({'source_ids':[source['id']],
                    'reason':'approved_window_attachment_limit','frame_ids':[f['frame_id'] for f in chosen]})
                continue
            chunks.append((source,chosen,cost))
    batches=[];batch=[];batch_cost=0
    for source,frames,cost in chunks:
        if batch and (batch_cost+cost>CANDIDATE_ATTACHMENT_BYTES or len(batch)>=3):
            batches.append(batch);batch=[];batch_cost=0
        batch.append((source,frames));batch_cost+=cost
    if batch:batches.append(batch)
    covered = {}
    for batch in batches:
        media=[]; rows=[]
        frame_index={};frame_details={}
        for source,frames in batch:
            rows.append({'id':source['id'],'sha256':source['sha256'],
                         'functional_review':source.get('functional_review'),
                         'reviewed_intervals':source.get('reviewed_intervals'),
                         'source_role':source.get('source_role'),'watermark_masks':source.get('watermark_masks')})
            chosen=sorted({f['frame_id']:f for f in frames}.values(),
                          key=lambda f:(f['source_timestamp'],f['frame_id']))
            for f in chosen:
                frame_index[(source['id'],f['frame_id'])]=f['source_timestamp']
                frame_details[(source['id'],f['frame_id'])]=f
                media.extend([{'text':json.dumps({'source_id':source['id'],'frame_id':f['frame_id'],
                                                 'timestamp':f['source_timestamp'],
                                                 'native_frame_exposure':f.get('native_frame_exposure')})},
                              {'inlineData':inline(f)}])
        old_frames=[]
        previous_review=next((r for r in reversed(state.get('daily_quality',{}).get('reviews',[]))
                              if r.get('edit_id')==state.get('edit_id')), {})
        wanted={r.get('beat_id') for r in requirements if r.get('beat_id')}
        prior_candidates=[f for g in previous_review.get('groups',[]) for f in g.get('frames',[])
                          if not wanted or f.get('beat_id') in wanted]
        first_by_beat={}
        for frame in prior_candidates:first_by_beat.setdefault(frame.get('beat_id'),frame)
        prior_candidates=list(first_by_beat.values())+[f for f in prior_candidates if f not in first_by_beat.values()]
        previous_bytes=0
        for frame in prior_candidates:
                if wanted and frame.get('beat_id') not in wanted:continue
                path=Path(frame.get('path',''))
                if not path.is_file() or not frame.get('sha256') or sha256_file(path)!=frame['sha256']:continue
                data=inline(frame);cost=len(data['data'])+1024
                if previous_bytes+cost>4*1024*1024:continue
                previous_bytes+=cost
                old_frames.append({k:frame.get(k) for k in ('beat_id','timestamp','sha256')})
                media.extend([{'text':'PREVIOUS FAILED CUT: '+json.dumps(old_frames[-1])},
                              {'inlineData':data}])
                if len(old_frames)>=12:break
        value=generate(settings,
            'Check required missing scenes BEFORE editing. Use only the supplied approved source frames and '
            'hash-bound usage restrictions. Do not treat filenames, source count, brand similarity or prior '
            'editing success as proof. Return {requirements:[{index,covered,reason,matches:[{source_id,'
            'source_start,source_end,evidence_frame_ids:[string],proof_mode, '
            'supporting_frame_ids:[string],supporting_reason}]}]}. '
            'Index is the index in supplied requirements. A scene_gap needs actual relevant product/use/appeal '
            'footage that addresses the defect in the whole story. Missing literal story illustration alone '
            'is not a defect: honest supportive product footage can cover it without showing that story event. '
            'Only a candidate presented as a direct action demonstration must prove the matching action; '
            'opposite motion presented as that action cannot qualify. A repetition issue needs a distinct observed view/action. '
            'For watermark use only existing approved mask regions or clean footage. Do not require exact SKU '
            'or proof of invisible facts unless that concrete visual detail is the stated defect. '
            'Each approved source window includes up to five actual frames in chronological order. '
            'Inspect intermediate frames for short actions and compare their initial/completed states; '
            'extra samples do not prove motion between frames or permit extending their observed interval. '
            'Every match must be a bounded interval inside supplied reviewed_intervals, positively visible in '
            'at least two supplied candidate frames within that interval. Use exact supplied frame IDs. '
            'source_start and source_end must equal the earliest and latest cited frame timestamps; '
            'never extend coverage before/after actual observed frames. '
            'For each scene_gap explicitly choose proof_mode: product_support, direct_transition, '
            'direct_state, or structural_detail, according to the actual target narration and defect. '
            'Product-form correction for a noun fragment such as "there is a remover" needs a visibly '
            'correct product form, not an entire cloth-to-spray action, cleaning transition, or completed result. '
            'For product_support cite exactly ONE actual supporting frame that independently shows the '
            'relevant product/form in this context; the other evidence frames still establish the reviewed '
            'source window but are not mandatory action states. Explain that distinction in supporting_reason. '
            'Never choose product_support to evade a required direct action, opposite-motion defect, '
            'completed-state claim, or unproven whole/part structure. For direct_transition retain every '
            'required initial/action/final state (at least two distinct supporting frames). For direct_state '
            'or structural_detail retain all actual frames necessary to prove that narrated state/structure. '
            'For scene_gap, separately identify the smallest set of cited actual supporting_frame_ids that '
            'must remain visible in the final short cut to show the relevant product/use/appeal, '
            'or to prove a required directly-demonstrated action or completed state, '
            'with supporting_reason. A motion/transition requiring multiple states must retain all of '
            'those states; never call an arbitrary interval endpoint sufficient. Missing or uncertain '
            'supporting frames prevent rendering. '
            'For repetition compare candidate views/actions against PREVIOUS FAILED CUT frames; absent '
            'comparison evidence is not proof of a distinct replacement. Uncertain coverage is false. Never rewrite narration. '
            +SCENE_CONTEXT_INSTRUCTION,
            {'purpose':'source_requirement_coverage','policy':policy,'requirements':requirements,
             'sources':rows,'previous_failed_frames':old_frames,'narration_context':context},media=media)
        receipt['assessments'].append({'source_ids':[s['id'] for s,_ in batch],
                                       'decisions':value.get('requirements',[])})
        ids={s['id'] for s,_ in batch}
        for row in value.get('requirements',[]):
            index=row.get('index');matches=[]
            if not(type(index) is int and 0<=index<len(requirements) and row.get('covered') is True
                   and str(row.get('reason','')).strip()):continue
            if requirements[index]['kind']=='repetition' and not old_frames:continue
            for match in row.get('matches',[]):
                sid=match.get('source_id');a=match.get('source_start');b=match.get('source_end')
                source=next((s for s,_ in batch if s['id']==sid),{})
                if (sid not in ids or type(a) not in (int,float) or type(b) not in (int,float)
                        or not math.isfinite(a) or not math.isfinite(b) or not 0<=a<b
                        or not any(w['source_start']<=a<b<=w['source_end'] for w in source.get('reviewed_intervals',[]))):continue
                frame_ids=match.get('evidence_frame_ids',[])
                times={frame_index.get((sid,fid)) for fid in frame_ids}
                if (len(times)<2 or None in times or not all(a<=t<=b for t in times)
                        or abs(a-min(times))>.001 or abs(b-max(times))>.001):continue
                result={'source_id':sid,'source_sha256':source['sha256'],'source_start':a,
                        'source_end':b,'evidence_frame_ids':frame_ids}
                mode=match.get('proof_mode')
                if requirements[index]['kind']=='scene_gap' or mode is not None:
                    if not isinstance(mode,str) or mode not in {'product_support','direct_transition','direct_state','structural_detail'}:continue
                    result['proof_mode']=mode
                support=match.get('supporting_frame_ids')
                reason=match.get('supporting_reason')
                if (isinstance(support,list) and support and all(isinstance(fid,str) and fid in frame_ids for fid in support)
                        and isinstance(reason,str) and reason.strip()):
                    result.update(supporting_frame_ids=list(dict.fromkeys(support)),supporting_reason=reason)
                if requirements[index]['kind']=='scene_gap' or mode is not None:
                    if not result.get('supporting_frame_ids'):continue
                    count=len(result['supporting_frame_ids'])
                    if (mode=='product_support' and count!=1) or (mode=='direct_transition' and count<2):continue
                    exposures=[frame_details[(sid,fid)].get('native_frame_exposure') for fid in result['supporting_frame_ids']]
                    if not all(row and a<=row['start']<=b and any(
                        w['source_start']<=a<row['end']<=w['source_end']+1e-6
                        for w in source.get('reviewed_intervals',[])) for row in exposures):continue
                matches.append(result)
            if matches:
                old=covered.setdefault(index,{'source_ids':[],'matches':[],'coverage_reason':row['reason']})
                old['matches'].extend(matches)
                old['source_ids']=list(dict.fromkeys(m['source_id'] for m in old['matches']))
        if all(index in covered for index in range(len(requirements))):
            receipt['completion_reason']='all_required_scenes_have_validated_matches'
            break
    receipt['requirements']=[{**r,'covered':i in covered,**covered.get(i,{})} for i,r in enumerate(requirements)]
    receipt['ready']=all(r['covered'] for r in receipt['requirements'])
    return receipt


def constrain_plan(state, plan):
    """A covered requirement must actually select its approved source, not an older bad cut."""
    if not required_scenes(state):
        return
    receipt=state.get('daily_quality',{}).get('scene_requirements',{})
    if not receipt.get('ready') or receipt.get('signature')!=input_signature(state) or not coverage_current(state):
        return
    shots={s['id']:s for s in plan.get('shots',[])}
    for requirement in receipt.get('requirements',[]):
        allowed=set(requirement.get('source_ids',[]))
        beats=[b for b in plan.get('beats',[]) if not requirement.get('beat_id') or b['id']==requirement['beat_id']]
        for beat in beats:
            options=[]
            for option in beat.get('options',[]):
                shot=shots.get(option['shot_id'],{})
                if shot.get('source_id') not in allowed:continue
                matches=requirement.get('matches',[])
                if not matches:
                    options.append(option);continue
                for match in matches:
                    if (shot.get('source_id')!=match['source_id'] or shot.get('sha256')!=match['source_sha256']):continue
                    source=next((s for s in state.get('sources',[]) if s.get('id')==match['source_id']),{})
                    a=max(float(shot['start']),match['source_start']);b=min(float(shot['end']),_match_render_end(state,source,match))
                    if b-a<min(.1,max(0,float(beat['end'])-float(beat['start']))):continue
                    narrowed=dict(shot)
                    narrowed.update(start=a,end=b,id=shot['id']+'-required-'+hashlib.sha256(
                        json.dumps([requirement.get('beat_id'),a,b]).encode()).hexdigest()[:8])
                    if narrowed['id'] not in shots:
                        plan['shots'].append(narrowed);shots[narrowed['id']]=narrowed
                    options.append({**option,'shot_id':narrowed['id']})
            # Ranking may omit the independently reviewed repair window. Add
            # that exact window using its own coverage proof, never another
            # shot's semantic claims or the narrator's fictional event.
            if not options:
                for match in requirement.get('matches', []):
                    if not match.get('proof_mode') or not match.get('supporting_frame_ids'):continue
                    source=next((s for s in state.get('sources',[]) if s.get('id')==match['source_id']),{})
                    if _support_times(state,source,match) is None:continue
                    base=next((s for s in plan.get('shots',[]) if s.get('source_id')==source.get('id')
                        and s.get('sha256')==match['source_sha256']
                        and Path(s.get('path','')).resolve()==Path(source.get('path','')).resolve()
                        and float(s.get('start',0))<=match['source_start']
                        and float(s.get('end',0))>=_match_render_end(state,source,match)),None)
                    if base is None:continue
                    narrowed=dict(base)
                    for key in ('observation','tags','visual_type','selection_exclusion','evidence_status'):
                        narrowed.pop(key,None)
                    identity=hashlib.sha256(json.dumps([source['sha256'],match,beat['id']],
                        sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16]
                    narrowed.update(id='coverage-'+identity,start=match['source_start'],
                        end=_match_render_end(state,source,match),
                        frames=[f['path'] for f in _evidence_review(source).get('evidence_frames', [])
                            if f.get('frame_id') in match['evidence_frame_ids']],
                        required_scene_coverage={'proof_mode':match['proof_mode'],
                            'supporting_frame_ids':match['supporting_frame_ids'],
                            'source_sha256':match['source_sha256']})
                    if narrowed['id'] not in shots:
                        plan['shots'].append(narrowed);shots[narrowed['id']]=narrowed
                    support=match['proof_mode']=='product_support'
                    options.append({'shot_id':narrowed['id'],'relation':'context' if support else 'direct',
                        'action_match':'not_established' if support else 'supports',
                        'reason':match['supporting_reason'], 'coverage_proof':True})
            beat['options']=options
            if not any(o['shot_id']==beat.get('selected_shot_id') for o in options):
                beat.pop('selected_shot_id',None)
            if not options and not beat.get('selected_shot_id'):
                beat['visual_alignment_gap']='required_scene_not_in_edit_options'


def _support_times(state,source,match):
    """Only an explicitly reviewed semantic anchor can justify shifting a cut."""
    ids=match.get('supporting_frame_ids')
    if (not isinstance(ids,list) or not ids or not isinstance(match.get('supporting_reason'),str)
            or not match['supporting_reason'].strip()
            or any(not isinstance(fid,str) or fid not in match.get('evidence_frame_ids',[]) for fid in ids)):
        return None
    mode=match.get('proof_mode')
    if not isinstance(mode,str) or (mode not in {'product_support','direct_transition','direct_state','structural_detail'}
            or (mode=='product_support' and len(set(ids))!=1)
            or (mode=='direct_transition' and len(set(ids))<2)):
        return None
    frames={f.get('frame_id'):f for f in _evidence_review(source).get('evidence_frames',[]) if isinstance(f,dict)}
    from .source_frame_timing import frame_exposure
    windows=[frame_exposure(frames.get(fid,{}),source.get('sha256'),_timing_for_source(state,source)) for fid in ids]
    if not all(row and match['source_start']<=row['start']<=match['source_end']
               and row['end']<=_match_render_end(state,source,match)+1e-6 for row in windows):return None
    return [(row['start'],row['end']) for row in windows]


def _original_window(state,shot,start,end):
    from .source_coverage import footage_coordinates
    source=next((s for s in state.get('sources',[]) if s.get('id')==shot.get('source_id')), {})
    coordinates=footage_coordinates(source)
    if (source.get('retiming') or source.get('original_sha256')) and coordinates is None:
        from .daily_quality import QualitySceneGap
        raise QualitySceneGap([{'kind':'scene_gap','reason':'파생·속도 조정 소스의 원본 시간 기록이 불명확함'}])
    if coordinates:key,offset,scale=coordinates
    else:key,offset,scale=('footage',source.get('sha256') or shot.get('sha256')),0,1
    return key,offset+start*scale,offset+end*scale


def _selection_failure(requirement,failure_reason,beat_id=None):
    """Keep the original visual defect distinct from a failed timing selection."""
    original={k:v for k,v in requirement.items()
              if k not in {'covered','coverage_reason','source_ids','matches'}}
    return {**original,'beat_id':beat_id or requirement.get('beat_id',''),
            'failure_reason':failure_reason}


def _proof_compatible_with_option(match,option):
    if option.get('action_match')=='opposite':return False
    return not (match.get('proof_mode')=='product_support' and option.get('relation')=='direct'
                and option.get('action_match')=='supports')


def anchor_selected_scenes(state,plan):
    """Freeze unambiguous semantic anchors without changing narration, speed or reuse."""
    import copy
    from .daily_quality import QualitySceneGap
    required=[r for r in state.get('daily_quality',{}).get('scene_requirements',{}).get('requirements',[])
              if _requires_native_proof(r) and not is_cover_scene_gap(r)]
    if not required:return
    if not coverage_current(state):raise QualitySceneGap(required)
    working=copy.deepcopy(plan);shots={s['id']:s for s in working.get('shots',[])}
    originals={}
    for beat in working.get('beats',[]):
        shot=shots.get(beat.get('selected_shot_id'),{})
        if shot and type(beat.get('source_start')) in (int,float) and type(beat.get('source_end')) in (int,float):
            originals[beat['id']]=_original_window(state,shot,beat['source_start'],beat['source_end'])
        applicable=[r for r in required if not r.get('beat_id') or r['beat_id']==beat['id']]
        if not applicable:continue
        a=beat.get('source_start');b=beat.get('source_end')
        source=next((s for s in state.get('sources',[]) if s.get('id')==shot.get('source_id')), {})
        if not(type(a) in (int,float) and type(b) in (int,float) and math.isfinite(a) and math.isfinite(b) and a<b):
            raise QualitySceneGap([{'kind':'scene_gap','beat_id':beat['id'],'reason':'핵심 장면의 실제 선택 시간 기록이 없음'}])
        if not shot or not all(type(shot.get(k)) in (int,float) for k in ('start','end')):
            raise QualitySceneGap([{'kind':'scene_gap','beat_id':beat['id'],'reason':'핵심 장면의 실제 선택 소스가 확인되지 않음'}])
        length=b-a;lo=shot['start'];hi=shot['end'];times=[];ids=[]
        selected_option=next((o for o in beat.get('options',[]) if o['shot_id']==shot['id']),{})
        for requirement in applicable:
            candidates=[m for m in requirement.get('matches',[]) if m.get('source_id')==shot.get('source_id')
                        and m.get('source_sha256')==shot.get('sha256') and m['source_start']-.001<=a<b<=_match_render_end(state,source,m)+.001]
            anchored=[(m,_support_times(state,source,m)) for m in candidates]
            anchored=[(m,t) for m,t in anchored if t is not None
                      and _proof_compatible_with_option(m,selected_option) and _proof_compatible_with_option(m,beat)]
            if len(anchored)!=1:
                raise QualitySceneGap([_selection_failure(requirement,
                    '필요 시각 근거의 실제 프레임·증명 목적이 명시 검토되지 않았거나 선택 근거와 불일치함',beat['id'])])
            match,support=anchored[0];lo=max(lo,match['source_start']);hi=min(hi,_match_render_end(state,source,match))
            times.extend(support);ids.extend(match['supporting_frame_ids'])
        # The first anchor may be at cut start. Last-frame exposure comes only
        # from source-bound native decoded PTS/duration, never output/average FPS.
        lower=max(lo,max(t[1] for t in times)-length);upper=min(hi-length,min(t[0] for t in times))
        if lower>upper+1e-6:
            raise QualitySceneGap([_selection_failure(r,
                '대사 길이와 승인 범위를 유지하면서 검토된 필수 시각 근거를 실제 컷에 담을 수 없음',beat['id'])
                for r in applicable])
        start=min(max(a,lower),upper);end=start+length
        narrowed=dict(shot)
        narrowed.update(start=start,end=end,id=shot['id']+'-anchored-'+hashlib.sha256(
            json.dumps([start,end,sorted(set(ids))]).encode()).hexdigest()[:10])
        working['shots'].append(narrowed);shots[narrowed['id']]=narrowed
        chosen=next((o for o in beat.get('options',[]) if o['shot_id']==shot['id']),{})
        if not chosen:
            raise QualitySceneGap([{'kind':'scene_gap','beat_id':beat['id'],'reason':'핵심 장면이 정상 선택 영수증과 연결되지 않음'}])
        beat.update(selected_shot_id=narrowed['id'],source_start=start,source_end=end,
                    options=[{**chosen,'shot_id':narrowed['id']}],
                    required_scene_anchor={'policy':'actual-support-frames-v1','supporting_frame_ids':sorted(set(ids)),
                        'source_sha256':shot['sha256'],'previous_source_start':a,'previous_source_end':b})
    # Compare every pair in parent coordinates, including derivatives and retimed
    # files. Corrections cannot introduce additional reuse elsewhere in the plan.
    windows={b['id']:_original_window(state,shots[b['selected_shot_id']],b['source_start'],b['source_end'])
             for b in working.get('beats',[]) if b['id'] in originals}
    def overlap(x,y):return max(0,min(x[2],y[2])-max(x[1],y[1])) if x[0]==y[0] else 0
    keys=list(windows)
    for index,key in enumerate(keys):
        for other in keys[index+1:]:
            if overlap(windows[key],windows[other])>overlap(originals[key],originals[other])+1e-6:
                raise QualitySceneGap([{'kind':'scene_gap','beat_id':key,
                    'reason':'핵심 프레임 보정이 다른 컷과 동일 원본 시간을 추가 재사용하게 되어 중단'}])
    # Rendering calls selection again. Freeze all current windows, including
    # unaffected beats, so that second allocation cannot silently move another
    # cut into the newly anchored range or replace the already reviewed timing.
    for beat in working.get('beats',[]):
        if beat.get('required_scene_anchor'):continue
        shot=shots.get(beat.get('selected_shot_id'),{})
        if beat['id'] not in windows or not shot:
            raise QualitySceneGap([{'kind':'scene_gap','beat_id':beat['id'],'reason':'다른 컷의 실제 원본 구간을 고정할 수 없어 핵심 장면 보정 중단'}])
        selected=next((o for o in beat.get('options',[]) if o['shot_id']==shot['id']),None)
        if selected is None:
            raise QualitySceneGap([{'kind':'scene_gap','beat_id':beat['id'],'reason':'다른 컷의 정상 선택 근거가 없어 핵심 장면 보정 중단'}])
        narrowed={**shot,'start':beat['source_start'],'end':beat['source_end'],
                  'id':shot['id']+'-frozen-'+hashlib.sha256(json.dumps([beat['source_start'],beat['source_end']]).encode()).hexdigest()[:10]}
        working['shots'].append(narrowed)
        beat.update(selected_shot_id=narrowed['id'],options=[{**selected,'shot_id':narrowed['id']}])
    validate_selected_scenes(state,working)
    plan.clear();plan.update(working)


def validate_selected_scenes(state,plan):
    """Check final selected file and interval after changes/selection, before rendering."""
    requirements=required_scenes(state)
    if not requirements:return
    receipt=state.get('daily_quality',{}).get('scene_requirements',{})
    if not coverage_current(state):
        from .daily_quality import QualitySceneGap
        raise QualitySceneGap(requirements)
    from .scene_requirement_context import build_scene_requirement_context, _spoken_text
    context=build_scene_requirement_context(state,requirements)
    if (plan.get('script_text')!=context['selected_narration']['text']
            or any(not isinstance(b.get('text'),str) or not b['text'].strip() for b in plan.get('beats',[]))
            or _spoken_text(' '.join(b.get('text','') for b in plan.get('beats',[])))
               !=_spoken_text(context['selected_narration']['text'])):
        from .daily_quality import QualitySceneGap
        raise QualitySceneGap([{'kind':'scene_gap','reason':'최종 편집 대본이 장면 검토에 결속된 승인 대본과 다름'}])
    shots={s['id']:s for s in plan.get('shots',[])};issues=[]
    for index,requirement in enumerate(receipt.get('requirements',[])):
        target_narration={row['id']:row['text'] for row in context['requirement_contexts'][index]['target']}
        beats=[b for b in plan.get('beats',[]) if not requirement.get('beat_id') or b['id']==requirement['beat_id']]
        if not beats:
            issues.append(requirement);continue
        for beat in beats:
            reason='실제 편집 구간이 필요한 장면의 검토된 파일·시간 범위에 포함되지 않음'
            if requirement.get('kind')=='scene_gap' and beat.get('text')!=target_narration.get(beat['id']):
                issues.append({'kind':'scene_gap','beat_id':beat['id'],
                    'reason':'최종 컷의 실제 대사가 장면 검토 당시의 해당 대사와 다름','search_query':''})
                continue
            shot=shots.get(beat.get('selected_shot_id'),{})
            a=beat.get('source_start',shot.get('start'));b=beat.get('source_end',shot.get('end'))
            source=next((s for s in state.get('sources',[]) if s.get('id')==shot.get('source_id')), {})
            valid=type(a) in (int,float) and type(b) in (int,float) and any(
                shot.get('source_id')==m['source_id'] and shot.get('sha256')==m['source_sha256']
                and m['source_start']-.001<=a<b<=_match_render_end(state,source,m)+.001 for m in requirement.get('matches',[]))
            from .source_quality import sha256_file
            shot_path=Path(shot.get('path',''))
            source=next((s for s in state.get('sources',[]) if s.get('id')==shot.get('source_id')), {})
            valid=valid and shot_path.is_file() and sha256_file(shot_path)==shot.get('sha256') and (
                shot_path.resolve()==Path(source.get('path','')).resolve())
            if valid and _requires_native_proof(requirement):
                # Check what the actual short cut retains, not merely its parent
                # approved range. End is exclusive; the support frame needs dwell.
                selected_option=next((o for o in beat.get('options',[]) if o.get('shot_id')==shot.get('id')),None)
                valid=selected_option is not None and any((times:=_support_times(state,source,m)) is not None
                    and shot.get('source_id')==m['source_id'] and shot.get('sha256')==m['source_sha256']
                    and m['source_start']-.001<=a<b<=_match_render_end(state,source,m)+.001
                    and all(a<=t[0]+.000001 and t[1]<=b+.000001 for t in times)
                    and _proof_compatible_with_option(m,selected_option) and _proof_compatible_with_option(m,beat)
                    for m in requirement.get('matches',[]))
                if not valid:reason='필요 시각 근거를 증명한 실제 핵심 프레임이 최종 컷에 남지 않았거나 증명 목적·선택 근거가 불일치함'
            if not valid:
                issues.append(_selection_failure(requirement,reason,beat['id']))
    if issues:
        from .daily_quality import QualitySceneGap
        raise QualitySceneGap(issues)
