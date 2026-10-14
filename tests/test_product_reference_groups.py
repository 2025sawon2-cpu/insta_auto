"""Independent negative propagation tests; no operating artifacts are used."""
import pytest

from hotpost.scene_analysis import analyze_shots
from hotpost.model_service import ModelResponseInvalid, ModelServiceUnavailable
from test_scene_analysis import catalog, beat


def narration():
    return [
        {**beat('story'), 'text':'외출 준비하다 옷에 뭐가 묻었어요'},
        {**beat('intro'), 'text':'이런 스프레이는'},
        {**beat('use'), 'text':'하나 두면 편하겠어요'},
        {**beat('closing'), 'text':'댓글에 나도 남겨주세요'},
    ]


def observe(ids):
    descriptions={'s0':'빨간 접촉식 도포 용기로 옷을 관리하는 모습',
                  's1':'색상과 모델이 다른 파란 에어로졸 스프레이 캔과 의류'}
    return {'shots':[{'id':sid,'observation':descriptions[sid]} for sid in ids]}


@pytest.mark.parametrize('closing_options',[
    [{'shot_id':'s0','relation':'context','reason':'잘못된 도포기를 context라고 제안'}],
    [],
])
def test_intro_negative_applies_to_all_flagged_fragments_and_fallback_but_not_story(tmp_path,closing_options):
    shots=catalog(tmp_path,2);calls=[]
    def generate(settings,instruction,evidence,*,media):
        calls.append(evidence)
        if media:return observe(evidence['shot_ids'])
        assert 'promoted_subject_reference' in instruction
        assert evidence['narration_text']==' '.join(b['text'] for b in narration())
        return {'beats':[
            {'id':'story','promoted_subject_reference':False,
             'options':[{'shot_id':'s0','relation':'context','reason':'옷 관리 이야기 보조'}]},
            {'id':'intro','promoted_subject_reference':True,'incompatible_subject_shot_ids':['s0','invented'],
             'options':[{'shot_id':'s1','relation':'context','reason':'같은 스프레이 제품 형태'}]},
            {'id':'use','promoted_subject_reference':True,
             'options':[{'shot_id':'s0','relation':'illustration','reason':'소개한 제품처럼 잘못 사용'}]},
            {'id':'closing','promoted_subject_reference':True,'options':closing_options},
        ]}
    _,choices=analyze_shots(None,shots,narration(),generate)
    assert len(calls)==2 and choices['story']['options'][0]['shot_id']=='s0'
    assert choices['story']['promoted_subject_reference'] is False
    for identity in ('intro','use','closing'):
        assert choices[identity]['promoted_subject_reference'] is True
        assert [o['shot_id'] for o in choices[identity]['options']]==['s1']
        assert choices[identity]['incompatible_subject_shot_ids']==['s0']


def test_minor_color_model_variant_and_unwitnessed_action_remain_usable_context(tmp_path):
    shots=catalog(tmp_path,2)
    shots[1]['context_usage_limits']=['색상/모델 차이; 정확한 SKU나 보이지 않는 성능을 입증하지 않음']
    def generate(settings,instruction,evidence,*,media):
        if media:return observe(evidence['shot_ids'])
        assert 'Minor color/model differences remain allowed' in instruction
        assert evidence['shots'][1]['context_usage_limits']==shots[1]['context_usage_limits']
        return {'beats':[
            {'id':'story','promoted_subject_reference':False,
             'options':[{'shot_id':'s0','relation':'context','reason':'일상 보조 장면'}]},
            {'id':'intro','promoted_subject_reference':True,'incompatible_subject_shot_ids':['s0'],
             'options':[{'shot_id':'s1','relation':'direct','action_match':'not_established',
                         'reason':'다른 색상의 같은 스프레이 형식이며 동작 자체는 미관찰'}]},
            {'id':'use','promoted_subject_reference':True,
             'options':[{'shot_id':'s1','relation':'context','reason':'제품 모습으로 사용 맥락을 보조'}]},
            {'id':'closing','promoted_subject_reference':True,
             'options':[{'shot_id':'s1','relation':'context','reason':'마무리 제품 모습'}]},
        ]}
    _,choices=analyze_shots(None,shots,narration(),generate)
    assert choices['intro']['options'][0]['shot_id']=='s1'
    assert choices['intro']['options'][0]['relation']=='context'
    assert choices['intro']['options'][0]['action_match']=='not_established'
    assert choices['story']['options'][0]['shot_id']=='s0'


@pytest.mark.parametrize('stage',['observe','rank'])
@pytest.mark.parametrize('error_type',[ModelServiceUnavailable,ModelResponseInvalid])
def test_typed_capacity_or_invalid_rpc_propagates_without_fabricating_fallback(tmp_path,stage,error_type):
    shots=catalog(tmp_path,2);calls=[];failure=error_type('typed RPC failure')
    def generate(settings,instruction,evidence,*,media):
        calls.append('observe' if media else 'rank')
        if (bool(media) and stage=='observe') or (not media and stage=='rank'):
            raise failure
        return observe(evidence['shot_ids'])
    with pytest.raises(error_type) as caught:
        analyze_shots(None,shots,narration(),generate)
    assert caught.value is failure
    assert calls==(['observe'] if stage=='observe' else ['observe','rank'])


def test_unknown_legacy_fragment_is_not_guessed_into_global_product_scope(tmp_path):
    shots=catalog(tmp_path,2)
    def generate(settings,instruction,evidence,*,media):
        if media:return observe(evidence['shot_ids'])
        return {'beats':[
            {'id':'intro','promoted_subject_reference':True,'incompatible_subject_shot_ids':['s0'],
             'options':[{'shot_id':'s1','relation':'context'}]},
            {'id':'story','options':[{'shot_id':'s0','relation':'context'}]},
        ]}
    _,choices=analyze_shots(None,shots,narration()[:2],generate)
    assert choices['intro']['incompatible_subject_shot_ids']==['s0']
    assert choices['story']['options'][0]['shot_id']=='s0'


def test_invented_beat_negative_cannot_poison_real_promoted_reference_group(tmp_path):
    shots=catalog(tmp_path,2)
    def generate(settings,instruction,evidence,*,media):
        if media:return observe(evidence['shot_ids'])
        return {'beats':[
            {'id':'story','promoted_subject_reference':False,
             'options':[{'shot_id':'s0','relation':'context'}]},
            {'id':'intro','promoted_subject_reference':True,'incompatible_subject_shot_ids':['s0'],
             'options':[{'shot_id':'s1','relation':'context'}]},
            {'id':'invented-beat','promoted_subject_reference':True,'incompatible_subject_shot_ids':['s1']},
        ]}
    _,choices=analyze_shots(None,shots,narration()[:2],generate)
    assert choices['intro']['incompatible_subject_shot_ids']==['s0']
    assert [o['shot_id'] for o in choices['intro']['options']]==['s1']
    assert choices['story']['options'][0]['shot_id']=='s0'


def test_duplicate_known_beat_cannot_drop_an_earlier_negative_by_last_positive_row(tmp_path):
    shots=catalog(tmp_path,2);calls=[]
    def generate(settings,instruction,evidence,*,media):
        calls.append('observe' if media else 'rank')
        if media:return observe(evidence['shot_ids'])
        return {'beats':[
            {'id':'intro','promoted_subject_reference':True,'incompatible_subject_shot_ids':['s0'],
             'options':[]},
            {'id':'intro','promoted_subject_reference':True,
             'options':[{'shot_id':'s0','relation':'context','reason':'Later unsafe positive row'}]},
        ]}
    with pytest.raises(ModelResponseInvalid):
        analyze_shots(None,shots,[{**beat('intro'),'text':'이 스프레이 하나 두고 싶네요'}],generate)
    assert calls==['observe','rank']
