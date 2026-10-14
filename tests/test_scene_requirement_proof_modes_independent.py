"""Independent contract checks; image interpretation remains a normal model review."""
import copy
import json
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.daily_quality import QualitySceneGap
from hotpost.scene_requirements import (
    POLICY, anchor_selected_scenes, assess, coverage_current, validate_selected_scenes,
)
from test_scene_requirement_intervals import approved, coverage


def scenario(tmp_path, text='제거제가 있어요', reason='제품 소개에 다른 도포구가 선택됨'):
    state=approved(tmp_path)
    state['original_text']='소개 제품은 에어로졸 제거제이며 별도의 도포구와 구분한다.'
    state['scripts'][0]['text']=text
    Path(state['edits'][0]['plan_path']).write_text(json.dumps({
        'script_text':text,'beats':[{'id':'b1','text':text}]}),encoding='utf-8')
    state['daily_quality']['feedback'][0]['reason']=reason
    source=state['sources'][0]
    plan={'duration':.946,'script_text':text,'sources':copy.deepcopy(state['sources']),
          'shots':[{'id':'shot','source_id':source['id'],'path':source['path'],
                    'sha256':source['sha256'],'start':1,'end':3.04}],
          'beats':[{'id':'b1','text':text,'start':0,'end':.946,
                    'source_start':1,'source_end':1.946,'selected_shot_id':'shot',
                    'options':[{'shot_id':'shot','relation':'context','reason':'Actual product support'}]}]}
    return state,plan


def response(state, mode='product_support', support=('0',)):
    value=coverage(state['sources'][0])
    match=value['requirements'][0]['matches'][0]
    match.update(proof_mode=mode,supporting_frame_ids=list(support),
                 supporting_reason='The cited frame independently shows the introduced product form; '
                                   'other evidence samples delimit the approved window, not an action sequence.')
    return value


def review(tmp_path,state,value):
    receipt=assess(Settings(data_dir=tmp_path),state,generate=lambda *a,**k:value)
    state['daily_quality']['scene_requirements']=receipt
    return receipt


def test_noun_product_support_short_cut_preserves_single_actual_frame_not_entire_window(tmp_path):
    state,plan=scenario(tmp_path)
    receipt=review(tmp_path,state,response(state))
    assert receipt['ready'] and coverage_current(state)
    match=receipt['requirements'][0]['matches'][0]
    assert match['evidence_frame_ids']==['0','1','2']
    assert match['supporting_frame_ids']==['0'] and match['proof_mode']=='product_support'
    old=copy.deepcopy(plan)
    anchor_selected_scenes(state,plan)
    validate_selected_scenes(state,plan)
    beat=plan['beats'][0]
    assert (beat['source_start'],beat['source_end'])==pytest.approx((1,1.946))
    assert beat['source_end']<match['source_end']
    assert (beat['start'],beat['end'],beat['text'])==(0,.946,old['beats'][0]['text'])
    assert receipt['requirements'][0]['matches'][0]==match


@pytest.mark.parametrize('mode',['direct_transition','structural_detail','direct_state'])
def test_required_multi_frame_proof_cannot_be_shrunk_to_fit_noun_sized_cut(tmp_path,mode):
    state,plan=scenario(tmp_path,'붙이기 전과 붙인 다음을 보여줘요','직접 동작·구조 증거 누락')
    receipt=review(tmp_path,state,response(state,mode,('0','1')))
    assert receipt['ready']
    old=copy.deepcopy(plan)
    with pytest.raises(QualitySceneGap):anchor_selected_scenes(state,plan)
    assert plan==old
    with pytest.raises(QualitySceneGap):validate_selected_scenes(state,plan)


@pytest.mark.parametrize('mode,support',[
    ('product_support',('0','1')),
    ('direct_transition',('0',)),
    ('direct_transition',('0','0')),
    ('invented_mode',('0',)),
    (None,('0',)),
    ([],('0',)),
    ({},('0',)),
])
def test_missing_malformed_or_mode_inconsistent_new_proof_is_not_approved(tmp_path,mode,support):
    state,_=scenario(tmp_path)
    receipt=review(tmp_path,state,response(state,mode,support))
    assert not receipt['ready']
    assert not receipt['requirements'][0].get('matches')
    assert not coverage_current(state)


def test_product_support_requires_its_actual_frame_to_remain_in_rendered_cut(tmp_path):
    state,plan=scenario(tmp_path)
    receipt=review(tmp_path,state,response(state,'product_support',('2',)))
    assert receipt['ready']
    with pytest.raises(QualitySceneGap):validate_selected_scenes(state,plan)
    anchor_selected_scenes(state,plan)
    validate_selected_scenes(state,plan)
    assert (plan['beats'][0]['source_start'],plan['beats'][0]['source_end'])==pytest.approx((2.094,3.04))
    assert plan['beats'][0]['required_scene_anchor']['supporting_frame_ids']==['2']


def test_new_policy_reviews_old_rejection_once_without_rewriting_old_receipt(tmp_path):
    state,_=scenario(tmp_path)
    old=assess(Settings(data_dir=tmp_path),state,generate=lambda *a,**k:{
        'requirements':[{'index':0,'covered':False,'reason':'Previous transition too long'}]})
    old['policy']='scene-coverage-v5-before-explicit-proof-mode'
    state['daily_quality']['scene_requirements']=copy.deepcopy(old)
    calls=[]
    def model(*args,**kwargs):
        calls.append(args)
        assert 'direct_transition' in args[1] and 'opposite-motion' in args[1]
        assert args[2]['narration_context']['selected_narration']['text']=='제거제가 있어요'
        return response(state)
    new=assess(Settings(data_dir=tmp_path),state,generate=model)
    assert len(calls)==1 and new['ready'] and new['policy']==POLICY
    assert state['daily_quality']['scene_requirements']==old
    state['daily_quality']['scene_requirements']=new
    reused=assess(Settings(data_dir=tmp_path),state,generate=lambda *a,**k:pytest.fail('No unchanged replay'))
    assert reused is new


def test_opposite_motion_negative_is_not_automatically_reinterpreted_as_product_support(tmp_path):
    state,plan=scenario(tmp_path,'끝을 세워 붙이면 돼요','반대인 제거 동작을 부착 동작으로 제시함')
    receipt=review(tmp_path,state,{'requirements':[
        {'index':0,'covered':False,'reason':'Observed removing motion contradicts direct attachment.',
         'matches':response(state)['requirements'][0]['matches']}]})
    assert not receipt['ready']
    with pytest.raises(QualitySceneGap):anchor_selected_scenes(state,plan)
    cached=assess(Settings(data_dir=tmp_path),state,
                  generate=lambda *a,**k:pytest.fail('Same confirmed opposite motion cannot replay'))
    assert cached is receipt


@pytest.mark.parametrize('relation,action',[('direct','supports'),('context','opposite')])
def test_explicit_selected_action_contract_cannot_be_bypassed_by_product_support(tmp_path,relation,action):
    state,plan=scenario(tmp_path)
    review(tmp_path,state,response(state))
    plan['beats'][0]['options'][0].update(relation=relation,action_match=action)
    original=copy.deepcopy(plan)
    with pytest.raises(QualitySceneGap):anchor_selected_scenes(state,plan)
    with pytest.raises(QualitySceneGap):validate_selected_scenes(state,plan)
    assert plan==original


def test_post_selection_lost_option_cannot_erase_product_proof_compatibility_check(tmp_path):
    state,plan=scenario(tmp_path)
    review(tmp_path,state,response(state))
    anchor_selected_scenes(state,plan)
    plan['beats'][0].update(relation='direct',action_match='supports',options=[])
    with pytest.raises(QualitySceneGap):validate_selected_scenes(state,plan)


@pytest.mark.parametrize('relation,action',[('direct','supports'),('context','opposite')])
def test_selected_beat_semantic_drift_cannot_hide_behind_old_context_option(tmp_path,relation,action):
    state,plan=scenario(tmp_path)
    review(tmp_path,state,response(state))
    anchor_selected_scenes(state,plan)
    assert plan['beats'][0]['options'][0]['relation']=='context'
    plan['beats'][0].update(relation=relation,action_match=action)
    before=copy.deepcopy(plan)
    with pytest.raises(QualitySceneGap):validate_selected_scenes(state,plan)
    with pytest.raises(QualitySceneGap):anchor_selected_scenes(state,plan)
    assert plan==before
