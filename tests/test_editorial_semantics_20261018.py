"""Whole-montage permission must not turn a wrong demonstration into evidence."""
import pytest

from hotpost.scene_analysis import analyze_shots, RANK_INSTRUCTION
from hotpost.product_appeal_review import PRODUCT_APPEAL_INSTRUCTION, POLICY
from test_scene_analysis import catalog, beat


def observation(shot_id, frame_count, product=True):
    return {'id':shot_id,'observation':('다리로 띄운 텐트 바닥' if product else '편안하게 웃으며 고개를 끄덕이는 사람'),
        'visual_type':'product' if product else 'person',
        'presentation':{'product_visible':product,'product_role':'related_product' if product else 'general_context',
            'frame_product_visibility':[product]*frame_count,'visible_information':['raised floor'] if product else [],
            'visual_cluster':shot_id,'composition':.8,'clarity':.8,'product_coverage':.6 if product else 0,
            'mask_product_overlap':0,'uncertainty':'Only supplied actual frames establish this view'}}


@pytest.mark.parametrize('requirement,expected',[('montage_support','s1'),(None,'s1'),('product','s0'),('direct_action','s0')])
def test_observed_reaction_during_benefit_is_not_a_product_visibility_failure(tmp_path,requirement,expected):
    shots=catalog(tmp_path,2)
    for shot in shots:shot.update(sha256=shot['id'],interval_presentation_required=True)
    def generate(settings,instruction,evidence,*,media):
        if media:return {'shots':[observation(s['id'],len(s['frames']),s['id']=='s0') for s in shots]}
        row={'id':'benefit','promoted_subject_reference':True,
             'options':[{'shot_id':'s1','relation':'context','reason':'전체 제품 소개 중 편안한 반응을 지원',
                         'action_match':'not_applicable'}]}
        if requirement is not None:row['visual_requirement']=requirement
        return {'beats':[row]}
    observations,choices=analyze_shots(None,shots,[{**beat('benefit'),'text':'습기랑 냉기가 덜해요'}],generate)
    assert observations['s1']['shot_presentation']['product_visible'] is False
    assert choices['benefit']['options'][0]['shot_id']==expected
    assert choices['benefit']['visual_requirement']==(requirement or 'montage_support')
    assert choices['benefit']['analysis_status']==('ranked' if expected=='s1' else 'fallback')


def test_vehicle_feature_negative_does_not_ban_shared_floor_benefit_or_closing(tmp_path):
    shots=catalog(tmp_path,2)
    beats=[{**beat('mount'),'text':'차 뒤에서 펼쳐요'},
           {**beat('floor'),'text':'바닥이 땅에서 떠 있어요'},
           {**beat('closing'),'text':'댓글에 나도 남겨주세요'}]
    def generate(settings,instruction,evidence,*,media):
        if media:return {'shots':[observation(s['id'],len(s['frames'])) for s in shots]}
        return {'beats':[
            {'id':'mount','promoted_subject_reference':True,'feature_incompatible_shot_ids':['s1','invented'],
             'options':[{'shot_id':'s1','relation':'context','reason':'차량 장착은 보여주지 않음'},
                        {'shot_id':'s0','relation':'context','reason':'차량형 제품 모습'}]},
            {'id':'floor','promoted_subject_reference':True,'options':[
                {'shot_id':'s1','relation':'direct','reason':'다리로 지면과 떨어진 바닥 구조를 실제 보여줌','action_match':'supports'}]},
            {'id':'closing','promoted_subject_reference':True,'options':[
                {'shot_id':'s1','relation':'context','reason':'앞에서 소개한 공통 특장점 장면을 다시 보여줌'}]}]}
    _,choices=analyze_shots(None,shots,beats,generate)
    assert [o['shot_id'] for o in choices['mount']['options']]==['s0']
    assert choices['mount']['feature_incompatible_shot_ids']==['s1']
    assert choices['mount']['incompatible_subject_shot_ids']==[]
    for identity in ('floor','closing'):
        assert [o['shot_id'] for o in choices[identity]['options']]==['s1']
        assert choices[identity]['feature_incompatible_shot_ids']==[]


def test_feature_support_cannot_resurrect_actual_wrong_product_or_opposite(tmp_path):
    shots=catalog(tmp_path,3)
    beats=[beat('identity'),beat('feature')]
    def generate(settings,instruction,evidence,*,media):
        if media:return {'shots':[observation(s['id'],len(s['frames'])) for s in shots]}
        return {'beats':[
            {'id':'identity','promoted_subject_reference':True,'incompatible_subject_shot_ids':['s0'],
             'options':[{'shot_id':'s2','relation':'context'}]},
            {'id':'feature','promoted_subject_reference':True,'feature_incompatible_shot_ids':[],
             'opposite_shot_ids':['s1'],'options':[{'shot_id':'s0','relation':'context'},
                {'shot_id':'s1','relation':'illustration','action_match':'opposite'},
                {'shot_id':'s2','relation':'context','reason':'실제 관련 제품 상태'}]}]}
    _,choices=analyze_shots(None,shots,beats,generate)
    assert [o['shot_id'] for o in choices['feature']['options']]==['s2']
    assert choices['feature']['incompatible_subject_shot_ids']==['s0']
    assert choices['feature']['opposite_shot_ids']==['s1']


@pytest.mark.parametrize('requirement,expected',[('montage_support',['s0']),('direct_action',['s1']),(None,['s1'])])
def test_nonliteral_support_is_not_changed_to_opposite_by_a_legacy_reason_phrase(tmp_path,requirement,expected):
    shots=catalog(tmp_path,2)
    def generate(settings,instruction,evidence,*,media):
        if media:return {'shots':[observation(s['id'],len(s['frames'])) for s in shots]}
        row={'id':'b1','options':[{'shot_id':'s0','relation':'context','action_match':'not_established',
              'reason':'다른 사용 순서여서 직접 시연으로 쓸 수 없지만 일반 혜택을 지원'}]}
        if requirement is not None:row['visual_requirement']=requirement
        return {'beats':[row]}
    _,choices=analyze_shots(None,shots,[beat()],generate)
    assert [o['shot_id'] for o in choices['b1']['options']]==expected
    assert choices['b1']['opposite_shot_ids']==([] if requirement=='montage_support' else ['s0'])


def test_ranking_and_final_qa_use_the_same_current_whole_montage_contract():
    from hotpost.daily_quality import REVIEW_INSTRUCTION
    assert POLICY=='product-appeal-first-20261018-v3'
    assert PRODUCT_APPEAL_INSTRUCTION in RANK_INSTRUCTION
    assert PRODUCT_APPEAL_INSTRUCTION in REVIEW_INSTRUCTION


@pytest.mark.parametrize('case,expected',[
    ('same_bag_color_transition',['s0','s1']),
    ('different_structure_direct_demo',['s1']),
    ('contradicted_exclusive_specification',['s1']),
])
def test_color_montage_permission_preserves_actual_identity_and_specification_negatives(tmp_path,case,expected):
    shots=catalog(tmp_path,2)
    descriptions={'s0':'같은 가방의 네이비 색상' if case=='same_bag_color_transition' else
                  '다른 구조의 원통형 기기' if case=='different_structure_direct_demo' else '주장한 전용 잠금 부품이 없는 일반 모델',
                  's1':'소개한 주황색 가방 또는 해당 부품이 실제 확인된 제품'}
    def generate(settings,instruction,evidence,*,media):
        if media:return {'shots':[{'id':sid,'observation':descriptions[sid]} for sid in evidence['shot_ids']]}
        row={'id':'b1','promoted_subject_reference':True,'visual_requirement':'montage_support',
             'options':[{'shot_id':'s0','relation':'context','reason':'앞선 관련 제품 모습'},
                        {'shot_id':'s1','relation':'context','reason':'대사 중간에 이어지는 해당 색상/제품 모습'}]}
        if case=='different_structure_direct_demo':row['incompatible_subject_shot_ids']=['s0']
        if case=='contradicted_exclusive_specification':row['feature_incompatible_shot_ids']=['s0']
        return {'beats':[row]}
    _,choices=analyze_shots(None,shots,[{**beat(),'text':'이 주황색 가방은요'}],generate)
    assert [o['shot_id'] for o in choices['b1']['options']]==expected
    assert choices['b1']['analysis_status']=='ranked'
