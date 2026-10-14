import copy
import json
import pytest

from hotpost.writing import pipeline
from hotpost.writing.contract import snapshot
from hotpost.writing.variants import validate_triplet


def triplet():
    return {'original_category':'관심·기억','original_mechanisms':['정보 격차'],
        'original_hook_analysis':'모습과 용도의 차이로 궁금증을 만듭니다.',
        'variants':[{'number':i,'variant_type':kind,'bias':bias,'category':'관심·기억',
            'changes':'새 갈등을 구성한 연출입니다.','surface_changes':['장소 변경','계기 변경'] if i==3 else [],
            'mechanism_application':'구체적인 문구와 갈등에 적용합니다.',
            'text':f'{i}안 제품이 필요한 상황에서 새 기능을 보여줘요. 댓글에 나도 남겨주세요.',
            'thumbnail_lines':['첫 줄','둘째 줄'],'thumbnail_mechanism':'호기심의 적용 차이'}
            for i,kind,bias in [(1,'transformation_a','자기참조 효과'),(2,'transformation_b','고립 효과'),
                                (3,'surface_substitution','정보 격차')]]}


def test_public_pipeline_generates_three_and_reviews_each_with_peer_context(tmp_path,monkeypatch):
    calls=[]
    def chat(instruction,data,schema,check,state):
        value=json.loads(data);calls.append(value)
        if len(calls)==1:return triplet()
        context=value['variant_context']
        assert len(context['other_variants'])==2
        assert context['selected_variant']['number']==len(calls)-1
        return {'issues':[]}
    def local(text,*a,**kw):
        return {'text':text,'integrity_review':{'issues':[]},'naturalness_review':{'issues':[]},
                'quality_summary':{'issues':[]}}
    monkeypatch.setattr(pipeline.codex_writer,'chat',chat)
    monkeypatch.setattr(pipeline,'review',local)
    result=pipeline.generate({'reference_script':'원작의 제품 기능. 댓글에 거울 남겨주세요.',
                             'reference_caption':'댓글에 테이블 남겨주세요.',
                             'comment_keyword':'옛키워드','writing_contract':snapshot()},
                             tmp_path,lambda:None,lambda *a:None)
    assert result['flow']=='three-variants-v1'
    assert [s['variant_number'] for s in result['scripts']]==[1,2,3]
    assert [s['bias'] for s in result['scripts']]==['자기참조 효과','고립 효과','정보 격차']
    assert all(s['thumbnail_lines']==['첫 줄','둘째 줄'] for s in result['scripts'])
    assert len(calls)==4 and 'sources' not in calls[0]
    assert all(c['comment_keyword']=='나도' for c in calls)
    assert result['benchmark']['analysis']['comment_keyword']=='나도'
    audit=json.loads((tmp_path/'writing-audit.json').read_text('utf-8'))
    assert len(audit['variant_reviews'])==3
    assert all((tmp_path/f'variant-{i}'/'writing-audit.json').is_file() for i in (1,2,3))


@pytest.mark.parametrize('defect',['same_bias','original_bias','wrong_category','missing_surface','duplicate_number'])
def test_invalid_type_contract_cannot_silently_become_one_draft(defect):
    v=copy.deepcopy(triplet())
    if defect=='same_bias':v['variants'][1]['bias']=v['variants'][0]['bias']
    if defect=='original_bias':v['variants'][0]['bias']='정보 격차'
    if defect=='wrong_category':v['variants'][1]['category']='가격·가치 판단'
    if defect=='missing_surface':v['variants'][2]['surface_changes']=['장소 변경']
    if defect=='duplicate_number':v['variants'][2]['number']=2
    with pytest.raises(ValueError):validate_triplet(v)


@pytest.mark.parametrize('original,chosen',[
    ('정보 격차', '정보 격차에 의한 호기심'),
    ('소유효과', '보유 효과 (제품 선택 후의 가치 평가)'),
    ('손실 회피', 'Loss-aversion effect'),
    ('가격 앵커링', '정박 효과'),
    ('self_reference_effect', '자기참조 효과'),
])
def test_original_mechanism_cannot_return_under_an_alias(original,chosen):
    v=triplet();v['original_mechanisms']=[original];v['variants'][0]['bias']=chosen
    with pytest.raises(ValueError,match='원작이 쓰지 않은'):validate_triplet(v)


def test_two_transformations_cannot_use_korean_and_english_of_same_effect():
    v=triplet();v['variants'][0]['bias']='단순 노출 효과';v['variants'][1]['bias']='Mere-exposure effect'
    with pytest.raises(ValueError,match='서로 다른'):validate_triplet(v)


def test_combining_original_effect_with_a_new_one_is_not_a_transformation():
    v=triplet();v['variants'][0]['bias']='자기참조 효과 + 정보 격차'
    with pytest.raises(ValueError):validate_triplet(v)


def test_distinct_unlisted_mechanisms_are_not_forced_into_the_starter_catalogue():
    v=triplet();v['variants'][0]['bias']='심적 시뮬레이션';v['variants'][1]['bias']='처리 유창성 효과'
    validate_triplet(v)


def test_related_but_different_mechanisms_are_not_collapsed():
    v=triplet();v['variants'][0]['bias']='현상유지 편향';v['variants'][1]['bias']='기본값 효과'
    validate_triplet(v)


def test_public_pipeline_repairs_alias_collision_once_and_preserves_failed_draft(tmp_path,monkeypatch):
    bad=triplet();bad['variants'][0]['bias']='정보 격차에 의한 호기심'
    calls=[]
    def chat(instruction,data,schema,check,state):
        value=json.loads(data);calls.append(value)
        if len(calls)==1:return bad
        if len(calls)==2:
            assert value['failed_triplet']['value']==bad
            assert '원작이 쓰지 않은' in value['failed_triplet']['error']
            assert '별칭으로 바꾸지 말고' in instruction
            return triplet()
        return {'issues':[]}
    def local(text,*a,**kw):
        return {'text':text,'integrity_review':{'issues':[]},'naturalness_review':{'issues':[]},
                'quality_summary':{'issues':[]}}
    monkeypatch.setattr(pipeline.codex_writer,'chat',chat);monkeypatch.setattr(pipeline,'review',local)
    result=pipeline.generate({'reference_script':'원작 제품 기능','writing_contract':snapshot()},
                             tmp_path,lambda:None,lambda *a:None)
    assert len(calls)==5 and len(result['scripts'])==3
    assert json.loads((tmp_path/'variant-contract-initial.json').read_text('utf-8'))['value']==bad
    audit=json.loads((tmp_path/'writing-audit.json').read_text('utf-8'))
    assert audit['contract_attempts'][1]['status']=='repaired'


def test_contract_repair_is_bounded_and_never_accepts_the_same_collision(tmp_path,monkeypatch):
    bad=triplet();bad['variants'][0]['bias']='정보 격차에 의한 호기심';calls=[]
    def chat(*args):calls.append(args);return bad
    monkeypatch.setattr(pipeline.codex_writer,'chat',chat)
    with pytest.raises(ValueError):
        pipeline.generate({'reference_script':'원작 제품 기능','writing_contract':snapshot()},
                          tmp_path,lambda:None,lambda *a:None)
    assert len(calls)==2
    assert (tmp_path/'variant-contract-initial.json').is_file()
