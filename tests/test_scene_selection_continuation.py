"""Short scene repairs use real longer footage, independent of subtitle cuts."""
import copy
import json
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.daily_quality import QualitySceneGap
from hotpost.editorial_policy import policy
from hotpost.scene_requirements import (
    assess, constrain_plan, anchor_selected_scenes, validate_selected_scenes,
)
from hotpost.source_frame_timing import timing_from_probe
from test_scene_requirement_intervals import approved, coverage
from test_scene_requirement_anchors import setup
from test_editorial_pipeline_20261018 import continuation


def captured_shape(tmp_path):
    state=approved(tmp_path);source=state['sources'][0]
    text='연결되는 느낌이에요'
    state['scripts'][0]['text']=text
    Path(state['edits'][0]['plan_path']).write_text(json.dumps({
        'script_text':text,'beats':[{'id':'b1','text':text}]}),encoding='utf8')
    stamps=(2.466666666666667,4.433333333333334,6.4)
    for frame,stamp in zip(source['mask_review']['evidence_frames'],stamps):
        frame['source_timestamp']=stamp
    source['reviewed_intervals']=[{'source_start':0.,'source_end':8.9}]
    source['mask_review']['native_frame_timing']=timing_from_probe({
        'streams':[{'duration':8.9}], 'frames':[
            {'best_effort_timestamp_time':t,'pkt_duration_time':1/30}
            for stamp in stamps for t in (stamp,stamp+1/30)]},source['sha256'])
    value=coverage(source,stamps[0],stamps[-1])
    value['requirements'][0]['matches'][0].update(proof_mode='product_support')
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,
        generate=lambda *a,**k:value)
    assert state['daily_quality']['scene_requirements']['ready']
    shot={'id':'ranked','source_id':source['id'],'sha256':source['sha256'],
          'path':source['path'],'start':0.,'end':4.}
    plan={'duration':.953333333333333,'fps':30,'editorial_policy':policy(),
        'script_text':text,'voice':{'sha256':'same-personal-voice'},'sources':[source],
        'shots':[shot,{**shot,'id':'longer','start':2.45,'end':6.45}],
        'beats':[{'id':'b1','text':text,'start':0.,'end':.953333333333333,
                  'options':[{'shot_id':'ranked','relation':'context','reason':'Product appearance'}]}]}
    return state,plan


@pytest.mark.parametrize('has_longer_catalog',[False,True])
def test_required_frame_beyond_ranked_catalog_edge_uses_reviewed_original(tmp_path,has_longer_catalog):
    state,plan=captured_shape(tmp_path)
    if not has_longer_catalog:plan['shots']=plan['shots'][:1]
    original=copy.deepcopy(plan)
    constrain_plan(state,plan)
    beat=plan['beats'][0];shots={s['id']:s for s in plan['shots']}
    assert beat['options']
    assert all(shots[o['shot_id']]['end']>4.433333333333334 for o in beat['options'])
    shot=shots[beat['options'][0]['shot_id']]
    beat.update(selected_shot_id=shot['id'],source_start=shot['start'],
                source_end=shot['start']+29/30)
    anchor_selected_scenes(state,plan);validate_selected_scenes(state,plan)
    assert beat is not plan['beats'][0]  # Atomic validated replacement.
    final=plan['beats'][0]
    assert final['source_start']<=4.433333333333334<final['source_end']
    assert final['source_end']-final['source_start']==pytest.approx(29/30)
    assert plan['script_text']==original['script_text'] and plan['voice']==original['voice']
    assert plan['scene_selection_adjustments'][0]['method']=='reviewed_source_window'


def test_bad_first_window_does_not_hide_another_approved_window(tmp_path):
    state,plan=captured_shape(tmp_path)
    matches=state['daily_quality']['scene_requirements']['requirements'][0]['matches']
    # Both are genuine proof-containing subranges; the first is too short.
    matches.insert(0,{**matches[0],'source_start':4.4,'source_end':4.47,
                      'evidence_frame_ids':['1']})
    # Retain the independently reviewed receipt binding by assessing both ranges.
    source=state['sources'][0]
    result={'requirements':[{'index':0,'covered':True,'reason':'Two reviewed alternatives',
        'matches':[{k:v for k,v in m.items() if k!='source_sha256'} for m in matches]}]}
    state['daily_quality'].pop('scene_requirements')
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,
        generate=lambda *a,**k:result)
    constrain_plan(state,plan)
    shots={s['id']:s for s in plan['shots']}
    assert plan['beats'][0]['options']
    assert all(shots[o['shot_id']]['end']-shots[o['shot_id']]['start']>=29/30
               for o in plan['beats'][0]['options'])


def adjacent_case(tmp_path):
    state,plan=setup(tmp_path);source=state['sources'][0]
    plan.update(editorial_policy=policy(),sources=[source],duration=1.2,
                script_text='Before the action. Observed action.',cues=[{'id':'same-cues'}])
    target=plan['beats'][0];target.update(start=.6,end=1.2)
    before={**copy.deepcopy(target),'id':'before','text':'Before the action.',
            'start':0.,'end':.6,'source_start':1.2,'source_end':1.8}
    plan['beats']=[before,target]
    state['scripts'][0]['text']=plan['script_text']
    Path(state['edits'][0]['plan_path']).write_text(json.dumps({'script_text':plan['script_text'],
        'beats':[{'id':b['id'],'text':b['text']} for b in plan['beats']]}),encoding='utf8')
    state['daily_quality'].pop('scene_requirements')
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,
        generate=lambda *a,**k:coverage(source))
    return state,plan


def test_previous_product_shot_continues_across_subtitle_boundary(tmp_path):
    state,plan=adjacent_case(tmp_path)
    original=copy.deepcopy(plan)
    anchor_selected_scenes(state,plan);validate_selected_scenes(state,plan)
    a,b=plan['beats']
    assert a['source_end']==pytest.approx(b['source_start'])
    assert (b['source_start'],b['source_end'])==pytest.approx((1.8,2.4))
    assert plan['script_text']==original['script_text'] and plan['voice']==original['voice']
    assert plan['cues']==original['cues']
    assert [(b['id'],b['text'],b['start'],b['end']) for b in plan['beats']]==[
        (b['id'],b['text'],b['start'],b['end']) for b in original['beats']]
    assert any(a['method']=='continue_neighbor_at_normal_speed' for a in plan['scene_selection_adjustments'])


@pytest.mark.parametrize('wider_option',[False,True])
def test_continuation_uses_a_real_covering_presentation_receipt(tmp_path,wider_option):
    state,plan=adjacent_case(tmp_path)
    plan['footage_selection_policy']='product-story-global-v3'
    base=plan['shots'][0];target=plan['beats'][1]
    narrow={**copy.deepcopy(base),'id':'narrow','start':2.,'end':2.8,
        'shot_presentation':{'source_sha256':base['sha256'],'source_window':[2.,2.8]}}
    plan['shots'].append(narrow)
    target.update(selected_shot_id='narrow',source_start=2.,source_end=2.6,
                  options=[{'shot_id':'narrow','relation':'direct','reason':'Observed action'}])
    if wider_option:
        plan['shots'].append({**copy.deepcopy(base),'id':'wide',
            'shot_presentation':{'source_sha256':base['sha256'],'source_window':[1.,4.]}})
        target['options'].append({'shot_id':'wide','relation':'direct','reason':'Same approved action'})
    anchor_selected_scenes(state,plan);validate_selected_scenes(state,plan)
    b=plan['beats'][1];shots={s['id']:s for s in plan['shots']};p=shots[b['selected_shot_id']]['shot_presentation']
    assert p['source_window'][0]<=b['source_start']<b['source_end']<=p['source_window'][1]
    assert b['source_start']==pytest.approx(1.8 if wider_option else 2.)


def test_continuation_cannot_relabel_direct_action_as_product_support(tmp_path):
    state,plan=adjacent_case(tmp_path);target=plan['beats'][1]
    value=coverage(state['sources'][0])
    value['requirements'][0]['matches'][0]['proof_mode']='product_support'
    state['daily_quality'].pop('scene_requirements')
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,
        generate=lambda *a,**k:value)
    target.update(relation='direct',action_match='supports')
    target['options'][0].update(relation='context',action_match='not_established')
    original=copy.deepcopy(plan)
    with pytest.raises(QualitySceneGap):anchor_selected_scenes(state,plan)
    assert plan==original


def test_unknown_or_unfittable_proof_still_holds_without_changing_selected_plan(tmp_path):
    state,plan=setup(tmp_path);plan['editorial_policy']=policy()
    match=state['daily_quality']['scene_requirements']['requirements'][0]['matches'][0]
    match.update(proof_mode='direct_transition',supporting_frame_ids=['0','2'])
    original=copy.deepcopy(plan)
    with pytest.raises(QualitySceneGap):anchor_selected_scenes(state,plan)
    assert plan==original


def test_short_approved_range_requests_existing_adjacent_review_instead_of_new_collection(tmp_path):
    from hotpost.editorial_policy import EditorialWindowGap
    state,plan=setup(tmp_path);source=state['sources'][0]
    plan.update(editorial_policy=policy(),fps=30,duration=3.2)
    plan['beats'][0].update(end=3.2)
    source['video_meta']={'duration':4.}
    with pytest.raises(EditorialWindowGap) as caught:constrain_plan(state,plan)
    requests=caught.value.diagnostics['window_requests']
    assert len(requests)==1 and requests[0]['source_id']==source['id']
    assert requests[0]['extension_source_window']==pytest.approx([1.,3.04])
    assert requests[0]['required_duration']==pytest.approx(3.2)
    assert requests[0]['normal_speed_only']


def test_adjacent_scope_reassesses_current_scene_and_preserves_original_failure(continuation,monkeypatch):
    from hotpost.scene_requirements import input_signature
    f=continuation
    prior={'ready':True,'signature':'old-scope','requirements':[{'kind':'watermark'}]}
    quality={'feedback':[{'kind':'watermark','beat_id':'beat','reason':'Actual overlay'}],
             'reviews':[{'passed':False,'issues':['actual prior failure']}],'scene_requirements':prior}
    f.state['daily_quality']=copy.deepcopy(quality)
    f.editor.store.state['daily_quality']=copy.deepcopy(quality)
    # The real window exception decoder, extension review/claim/save and edit
    # re-entry run. Only the independent scene-review model port is synthetic.
    seen=[]
    def scene_review(settings,state):
        seen.append(copy.deepcopy(state))
        return {'ready':True,'signature':input_signature(state),'requirements':[]}
    monkeypatch.setattr('hotpost.scene_requirements.assess',scene_review)
    f.diagnostics['window_requests'][0]['extension_source_window']=[2.,2.8]
    result=f.editor._render_editorial_feedback(f.state,f.job,f.plan)
    assert result=={'reentered_same_job':f.job['id']} and len(seen)==1
    current=f.editor.store.get('task')
    assert current['daily_quality']['reviews']==quality['reviews']
    assert current['daily_quality']['feedback']==quality['feedback']
    assert current['daily_quality']['scene_requirement_review_history'][0]['previous']==prior
    assert current['daily_quality']['scene_requirements']['signature']==input_signature(current)
    assert current['scripts']==f.state['scripts'] and current['voices']==f.state['voices']


def test_montage_reuse_is_recorded_for_final_qa_instead_of_blanket_rejection(tmp_path):
    state,plan=setup(tmp_path);plan.update(editorial_policy=policy(),duration=1.2)
    other=copy.deepcopy(plan['beats'][0]);other.update(id='after',text='After the action.',
        start=.6,end=1.2,source_start=1.9,source_end=2.5)
    plan['beats'].append(other)
    plan['script_text']=state['scripts'][0]['text']='Observed action. After the action.'
    Path(state['edits'][0]['plan_path']).write_text(json.dumps({'script_text':plan['script_text'],
        'beats':[{'id':b['id'],'text':b['text']} for b in plan['beats']]}),encoding='utf8')
    state['daily_quality'].pop('scene_requirements')
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,
        generate=lambda *a,**k:coverage(state['sources'][0]))
    anchor_selected_scenes(state,plan);validate_selected_scenes(state,plan)
    assert any(a['method']=='reviewed_source_reuse' and a['final_flow_qa_required']
               for a in plan['scene_selection_adjustments'])
