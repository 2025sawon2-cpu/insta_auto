"""Bind explicitly reviewed narration clauses to bounded, hashed source scenes."""
from __future__ import annotations

import copy
import math
import re
import json
from pathlib import Path


def approved_voice_scenes(state, plan):
    """Keep approved visual decisions when only narration settings change."""
    from .daily_quality import verified_quality_export
    from .source_quality import sha256_file
    run=next((r for r in state.get('runs',[]) if r['id']==state.get('run_id')), {})
    if run.get('inputs',{}).get('changes'):return None
    parent=next((r for r in state.get('runs',[]) if r['id']==run.get('parent_id')), {})
    edit=next((e for e in state.get('edits',[]) if e['id']==parent.get('artifacts',{}).get('edit_id')), {})
    if not edit or edit.get('voice_id')==state.get('voice_id') or not verified_quality_export(state,edit,historical=True):return None
    old=json.loads(Path(edit['plan_path']).read_text('utf8'))
    if old.get('visual_cuts'):return None
    if (old.get('script_text')!=plan.get('script_text') or not plan.get('script_text')
            or {s['sha256'] for s in old.get('sources',[])}!={s['sha256'] for s in plan.get('sources',[])}
            or [b['text'] for b in old.get('beats',[])]!=[b['text'] for b in plan.get('beats',[])]):return None
    sources={s['sha256']:s for s in plan['sources']}
    old_sources={s['sha256']:s for s in old['sources']}
    context_keys=('source_role','source_quality','editing_eligible','manual_usage_review','original_sha256',
        'original_interval','source_interval','retiming','reviewed_intervals','watermark_masks','portrait_geometry','usage_limits')
    for digest,source in sources.items():
        prior=old_sources[digest]
        if any(source.get(k)!=prior.get(k) for k in context_keys):return None
        for review,keys in [('functional_review',('policy','source_sha256','same_core_function','context_usable','context_usage_limits','usage_limits','differences')),
                            ('presentation_review',('scope',)),('mask_review',('geometry',))]:
            if any((source.get(review) or {}).get(k)!=(prior.get(review) or {}).get(k) for k in keys):return None
    shots={s['id']:s for s in old['shots']}
    selected=[];checked=set();result=copy.deepcopy(plan)
    for beat,previous in zip(result['beats'],old['beats']):
        shot=copy.deepcopy(shots[previous['selected_shot_id']])
        source=sources[shot['sha256']]
        if (beat['end']-beat['start'] > previous.get('source_end',shot['end'])-previous.get('source_start',shot['start'])+1e-7):return None
        if source['sha256'] not in checked:
            if sha256_file(Path(source['path']))!=source['sha256']:raise ValueError('재사용할 승인 장면 원본이 변경되었습니다.')
            checked.add(source['sha256'])
        shot.update(id='voice-preserved-'+beat['id'],source_id=source['id'],path=source['path'],
                    start=previous.get('source_start',shot['start']),end=previous.get('source_end',shot['end']))
        selected.append(shot)
        reason='목소리 설정만 변경하여 직전 통과 영상의 실제 사용 장면 유지'
        beat.update(selected_shot_id=shot['id'],options=[{'shot_id':shot['id'],
            'relation':previous.get('relation','context'),'reason':reason}],reason=reason,
            semantic_analysis_status='ranked')
    result['shots']=selected
    result['semantic_provider']='approved-voice-only-scenes'
    result['footage_selection_policy']=old.get('footage_selection_policy','product-story-global-v3')
    result['approved_voice_scene_binding']={'edit_id':edit['id'],'plan_sha256':sha256_file(Path(edit['plan_path']))}
    return result


def apply_reviewed_scenes(plan, rules):
    if not isinstance(rules,list) or not rules or len(rules)>100:
        raise ValueError('검토한 장면 규칙을 확인하세요.')
    plan=copy.deepcopy(plan)
    sources={s['sha256']:s for s in plan['sources']}
    original_shots=list(plan['shots'])
    templates=[]
    for rule in rules:
        if rule.get('reviewed') is not True or rule.get('source_sha256') not in sources:
            raise ValueError('검토한 장면과 현재 소스의 해시가 다릅니다.')
        start,end=rule.get('start'),rule.get('end')
        if (type(start) not in (int,float) or type(end) not in (int,float)
            or not math.isfinite(start) or not math.isfinite(end)
            or not 0<=start<end):
            raise ValueError('검토한 장면 구간이 실제 소스 범위를 벗어났습니다.')
        template=next((x for x in original_shots if x['sha256']==rule['source_sha256']
            and x['start']<=start<end<=x['end']+.001 and not x.get('selection_exclusion')),None)
        if template is None:
            raise ValueError('검토한 장면 구간이 실제 승인 구간을 벗어났습니다.')
        templates.append(template)
        if rule.get('relation') not in ('direct','context') or not rule.get('evidence_frames'):
            raise ValueError('장면 검토 근거가 없습니다.')
        re.compile(rule['pattern'])
    for beat in plan['beats']:
        index=next((i for i,r in enumerate(rules) if re.search(r['pattern'],beat['text'])),None)
        if index is None:raise ValueError('검토한 장면이 연결되지 않은 발화 구간: '+beat['text'])
        rule=rules[index]
        source=sources[rule['source_sha256']];sid='reviewed-'+beat['id']
        # Keep task-scoped function limits, parent identity and overlay evidence.
        # A narrower manual selection must not silently discard those contracts.
        shot=copy.deepcopy(templates[index])
        shot.update({'id':sid,'source_id':source['id'],'path':source['path'],
            'sha256':source['sha256'],'start':rule['start'],'end':rule['end'],
            'frames':list(rule['evidence_frames']),'observation':rule['reason'],
            'reviewed_by':'agent_actual_source_frames'})
        plan['shots'].append(shot)
        beat.update(options=[{'shot_id':sid,'relation':rule['relation'],'reason':rule['reason'],
                              'reviewed':True}],selected_shot_id=sid)
    plan['semantic_provider']='agent_actual_source_frames'
    plan['reviewed_scene_rules']=copy.deepcopy(rules)
    return plan
