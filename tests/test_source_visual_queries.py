import copy
from pathlib import Path
from types import SimpleNamespace
import pytest
from hotpost.source_visual_queries import binding, digest, cached_visual_queries, apply_visual_queries, plan_queries
from hotpost.source_queries import tiktok_product_queries


@pytest.fixture
def actual(tmp_path):
    reference=tmp_path/'original.mp4'; reference.write_bytes(b'reference fixture')
    from PIL import Image
    frame=tmp_path/'frame.jpg';Image.new('RGB',(12,12),'silver').save(frame)
    evidence=binding(reference,[frame],'반려동물용품',{})
    proposal={'observations':[{'id':'o1','text':'망형 지지면과 다리 구멍이 있는 목욕 받침대', 'frame_ids':['frame-1']}],
        'queries':[{'id':'q1','query':'망형 반려동물 목욕 받침대','language':'ko','observation_ids':['o1'],'frame_ids':['frame-1']}]}
    review={'input_sha256':digest(evidence),'proposal_sha256':digest(proposal),
        'checks':[{'query_id':'q1','supported':True,'central_product':True,'short_noun_phrase':True,'no_unobserved_claims':True}]}
    return SimpleNamespace(data_dir=tmp_path),reference,frame,evidence,proposal,review


def generate_pair(proposal,review):
    calls=[]
    def generate(settings,instruction,data,**kwargs):
        calls.append((data,kwargs))
        return copy.deepcopy(proposal if len(calls)==1 else review)
    return generate,calls


def test_pixels_reach_both_calls_and_final_tiktok_dispatch_without_promoting_products(actual):
    settings,reference,frame,evidence,proposal,review=actual
    generate,calls=generate_pair(proposal,review)
    receipt=cached_visual_queries(settings,reference,[frame],'반려동물용품',{},generate)
    assert len(calls)==2 and all(len(c[1]['media'])==2 and c[1]['media'][1]['inlineData']['data'] for c in calls)
    base={'products':[],'inferred_products':[{'en':'dryer','sources':['openclip']}],
          'query_details':[],'query_evidence':evidence['text']}
    plan=apply_visual_queries(base,receipt,reference_sha256=evidence['reference_sha256'])
    assert tiktok_product_queries(plan)[0]=='망형 반려동물 목욕 받침대'
    assert plan['products']==[] and plan['inferred_products']==base['inferred_products']
    again=cached_visual_queries(settings,reference,[frame],'반려동물용품',{},lambda *a,**k:pytest.fail('cached model call'))
    assert again==receipt and base.get('visual_query_evidence') is None


@pytest.mark.parametrize('fault',['frame','source','plan_reference','plan_text','query','review_hash','frame_id'])
def test_altered_provenance_never_reaches_search(actual,fault):
    settings,reference,frame,evidence,proposal,review=actual
    generate,_=generate_pair(proposal,review)
    receipt=cached_visual_queries(settings,reference,[frame],'반려동물용품',{},generate)
    plan=apply_visual_queries({'query_details':[],'query_evidence':evidence['text']},receipt,
        reference_sha256=evidence['reference_sha256'])
    if fault=='frame': frame.write_bytes(b'changed')
    elif fault=='source':reference.write_bytes(b'changed')
    elif fault=='plan_reference':plan['query_reference_sha256']='other'
    elif fault=='plan_text':plan['query_evidence']['caption']='other'
    elif fault=='query':plan['visual_query_evidence']['queries'][0]['query']='없는 재질 받침대'
    elif fault=='review_hash':plan['visual_query_evidence']['review']['proposal_sha256']='wrong'
    elif fault=='frame_id':plan['visual_query_evidence']['proposal']['queries'][0]['frame_ids']=['missing']
    with pytest.raises(ValueError):tiktok_product_queries(plan)


@pytest.mark.parametrize('flag',['supported','central_product','short_noun_phrase','no_unobserved_claims'])
def test_independent_rejection_is_not_replaced_by_a_guess(actual,flag):
    settings,reference,frame,evidence,proposal,review=actual
    review['checks'][0][flag]=False
    generate,calls=generate_pair(proposal,review)
    receipt=cached_visual_queries(settings,reference,[frame],'반려동물용품',{},generate)
    assert receipt['queries']==[] and len(calls)==2


def test_completed_proposal_reused_after_review_capacity_wait(actual):
    from hotpost.model_service import ModelServiceUnavailable
    settings,reference,frame,evidence,proposal,review=actual
    n=[]
    def generate(*args,**kwargs):
        n.append(1)
        if len(n)==1:return proposal
        raise ModelServiceUnavailable('wait',retry_at=1)
    with pytest.raises(ModelServiceUnavailable):
        cached_visual_queries(settings,reference,[frame],'반려동물용품',{},generate)
    calls=[]
    def recovered(*args,**kwargs):calls.append(1);return review
    receipt=cached_visual_queries(settings,reference,[frame],'반려동물용품',{},recovered)
    assert len(calls)==1 and receipt['queries']
