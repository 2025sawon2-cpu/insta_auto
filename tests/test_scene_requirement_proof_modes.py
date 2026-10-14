import copy
import json
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.daily_quality import QualitySceneGap
from hotpost.scene_requirements import assess, anchor_selected_scenes, validate_selected_scenes
from hotpost.source_frame_timing import timing_from_probe
from test_scene_requirement_intervals import approved


def fixture(tmp_path,mode='product_support',support=('0',)):
    state=approved(tmp_path);source=state['sources'][0]
    text='제거제가 있어요'
    state['scripts'][0]['text']=text
    state['original_text']='옷의 얼룩에 쓰는 에어로졸 스프레이 제거제입니다.'
    state['daily_quality']['feedback']=[{'kind':'scene_gap','beat_id':'b1',
        'reason':'소개하는 스프레이 제거제 대신 접촉식 도포 용기가 보임','scope':'body',
        'search_query':'에어로졸 제거제'}]
    Path(state['edits'][0]['plan_path']).write_text(json.dumps({'script_text':text,
        'beats':[{'id':'b1','text':text,'start':0,'end':.946667}]}),encoding='utf-8')
    for frame,timestamp in zip(source['mask_review']['evidence_frames'],(0,1,2)):
        frame['source_timestamp']=timestamp
    pts=(0,1/30,1,1+1/30,2,2+1/30)
    source['mask_review']['native_frame_timing']=timing_from_probe({'streams':[{'duration':4}],
        'frames':[{'best_effort_timestamp_time':t,'pkt_duration_time':1/30} for t in pts]},source['sha256'])
    value={'requirements':[{'index':0,'covered':True,'reason':'Correct aerosol form is visibly present',
        'matches':[{'source_id':'source','source_start':0,'source_end':1,'evidence_frame_ids':['0','1'],
            'proof_mode':mode,'supporting_frame_ids':list(support),
            'supporting_reason':'The cited appearance frame independently shows the actual aerosol can'}]}]}
    seen=[]
    def model(settings,instruction,evidence,media):
        seen.append((instruction,evidence));return copy.deepcopy(value)
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,generate=model)
    shot={'id':'shot','source_id':source['id'],'sha256':source['sha256'],'path':source['path'],'start':0,'end':1+1/30}
    plan={'script_text':text,'duration':.946667,'voice':{'sha256':'unchanged'},'shots':[shot],
        'beats':[{'id':'b1','text':text,'start':0,'end':.946667,'source_start':0,'source_end':.946667,
            'selected_shot_id':'shot','options':[{'shot_id':'shot','relation':'context','action_match':'not_established'}]}]}
    return state,plan,seen


@pytest.mark.parametrize('frame_id',['0','1'])
def test_noun_fragment_needs_actual_product_appearance_not_full_spray_transition(tmp_path,frame_id):
    state,plan,seen=fixture(tmp_path,support=(frame_id,));before=copy.deepcopy(plan)
    assert state['daily_quality']['scene_requirements']['ready']
    assert 'not an entire cloth-to-spray action' in seen[0][0]
    anchor_selected_scenes(state,plan);validate_selected_scenes(state,plan)
    beat=plan['beats'][0]
    assert beat['source_end']-beat['source_start']==pytest.approx(.946667)
    assert beat['required_scene_anchor']['supporting_frame_ids']==[frame_id]
    assert plan['script_text']==before['script_text'] and plan['voice']==before['voice']
    assert beat['text']==before['beats'][0]['text']


def test_product_support_cannot_silently_drop_model_required_second_state(tmp_path):
    state,plan,_=fixture(tmp_path,support=('0','1'))
    assert not state['daily_quality']['scene_requirements']['ready']
    with pytest.raises(QualitySceneGap):anchor_selected_scenes(state,plan)


def test_direct_transition_keeps_all_critical_states_and_original_defect_scope(tmp_path):
    state,plan,_=fixture(tmp_path,mode='direct_transition',support=('0','1'))
    assert state['daily_quality']['scene_requirements']['ready']
    before=copy.deepcopy(plan)
    with pytest.raises(QualitySceneGap) as caught:anchor_selected_scenes(state,plan)
    issue=caught.value.issues[0];original=state['daily_quality']['feedback'][0]
    assert issue['reason']==original['reason'] and issue['scope']==original['scope']
    assert issue['search_query']==original['search_query']
    assert '대사 길이' in issue['failure_reason'] and plan==before


@pytest.mark.parametrize('action_match',['supports','opposite'])
def test_product_support_cannot_override_direct_action_or_opposite_selection(tmp_path,action_match):
    state,plan,_=fixture(tmp_path)
    plan['beats'][0]['options'][0].update(relation='direct',action_match=action_match)
    before=copy.deepcopy(plan)
    with pytest.raises(QualitySceneGap):anchor_selected_scenes(state,plan)
    with pytest.raises(QualitySceneGap):validate_selected_scenes(state,plan)
    assert plan==before


def test_prior_policy_receipt_requires_real_new_mode_review_and_does_not_mutate_history(tmp_path):
    state,plan,_=fixture(tmp_path)
    old=copy.deepcopy(state['daily_quality']['scene_requirements']);old['policy']='scene-coverage-v5-product-appeal-support'
    state['daily_quality']['scene_requirements']=old
    with pytest.raises(QualitySceneGap):anchor_selected_scenes(state,plan)
    assert state['daily_quality']['scene_requirements']==old
