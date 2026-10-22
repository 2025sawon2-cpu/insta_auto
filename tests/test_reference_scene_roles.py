import copy
import pytest

from hotpost import source_visual_queries as visual
from hotpost.reference_scene_roles import approved_scenes, diverse_query_order, plan_context
from hotpost.source_search.planner import round_queries
from hotpost.source_queries import tiktok_product_queries
from test_source_visual_query_minima_v5 import setup, proposal, model, plan


def scene(key, frame='frame-1'):
    return {'id':key,'frame_ids':[frame], 'visible_content':'주머니를 보여주는 제품 컷',
            'information_or_emotion':'수납 형태의 이해', 'persuasive_role':'사용 편의 전달',
            'alternative_visuals':'같은 구조의 실제 제품 수납 컷'}


def receipt(tmp_path, *, invalid_scene=False):
    settings, reference, frames = setup(tmp_path)
    value = proposal()
    value['reference_scenes'] = [scene('detail'),scene('use','nonexistent' if invalid_scene else 'frame-1')]
    for index,q in enumerate(value['queries']):
        q['scene_ids'] = ['use' if index%5==4 else 'detail']
    calls=[]
    base=model(value,calls)
    def generate(settings,instruction,data,**kwargs):
        result=base(settings,instruction,data,**kwargs)
        if 'proposal_sha256' in data:
            result['scene_checks']=[{'scene_id':s['id'],'visible_content_supported':True,
                'role_plausible':True,'alternatives_relevant':True} for s in value['reference_scenes']]
            for check in result['checks']:check['scene_ids_supported']=True
        return result
    return visual.cached_visual_queries(settings,reference,frames,'재킷',{},generate,
                                         search_minimums={'en':5,'zh':5}),calls


def test_scene_intent_reaches_both_dispatch_paths_without_changing_identity_or_minima(tmp_path):
    result,calls=receipt(tmp_path)
    document=plan(result)
    assert len(document['reference_scene_intents'])==2
    assert document['minimum_query_plan_ready']
    normal=round_queries(document,{'phase':'core_action'})
    tiktok=tiktok_product_queries(document)
    assert [r['query'] for r in normal]==tiktok
    assert [r['scene_ids'] for r in normal[:3]]==[['detail'],['use'],['detail']]
    assert {r['query'] for r in normal}=={r['query'] for r in result['queries']}
    assert all(len(r['query'].split())<=6 for r in normal)
    context=plan_context(document,result['evidence']['reference_sha256'])
    assert len(context['scenes'])==2 and 'not_identity' in context['usage']
    assert plan_context(document,'wrong-reference') is None
    assert 'topic hint actually makes it essential' not in ' '.join(calls)
    assert 'Do not impose a fixed taxonomy' in calls[0]


def test_bad_scene_evidence_drops_only_advisory_link_not_valid_product_query(tmp_path):
    result,_=receipt(tmp_path,invalid_scene=True)
    assert len(result['queries'])==10
    assert all('use' not in q.get('scene_ids',[]) for q in result['queries'])
    assert plan(result)['minimum_query_plan_ready']


def test_missing_advisory_fields_preserves_legacy_receipt(tmp_path):
    settings,reference,frames=setup(tmp_path)
    result=visual.cached_visual_queries(settings,reference,frames,'재킷',{},model(proposal(),[]),
                                        search_minimums={'en':5,'zh':5})
    before=copy.deepcopy(result)
    assert visual.verify(result)==result['queries']
    assert plan_context(plan(result),result['evidence']['reference_sha256']) is None
    assert result==before


def test_scene_tampering_cannot_transfer_an_unreviewed_plan(tmp_path):
    result,_=receipt(tmp_path)
    document=plan(result)
    document['visual_query_evidence']['proposal']['reference_scenes'][0]['visible_content']='다른 제품'
    with pytest.raises(ValueError,match='SHA'):
        plan_context(document,result['evidence']['reference_sha256'])


def test_no_scene_order_is_invented_and_missing_roles_keep_stable_order():
    rows=[{'query':'a','language':'en'},{'query':'b','language':'en'},{'query':'c','language':'zh'}]
    assert diverse_query_order(rows)==rows
    assert approved_scenes({'reference_scenes':[scene('x')]},{'scene_checks':[]},
                           {'frames':[{'id':'frame-1'}]})==[]


def test_batch_context_is_bound_to_current_run_and_reaches_function_review(tmp_path,monkeypatch):
    from hotpost.source_batches import state_with_search_audit
    from hotpost.source_functional import reference_review_info
    from hotpost.source_coverage import search_scope_for_state
    result,_=receipt(tmp_path)
    document=plan(result)
    state={'id':'test','run_id':'run-new','product':'재킷','reference_video':result['evidence']['reference_path']}
    manifest={'run_id':'run-new','search_context':search_scope_for_state(state),'product_evidence':document}
    enriched=state_with_search_audit(state,manifest)
    assert len(enriched['reference_scene_context']['scenes'])==2
    assert 'reference_scene_context' not in state
    wrong=state_with_search_audit(state,{**manifest,'run_id':'old'})
    assert 'reference_scene_context' not in wrong
    monkeypatch.setattr('hotpost.source_finder.probe_video',lambda p:{'duration':10})
    digest=result['evidence']['reference_sha256']
    (tmp_path/f'source-reference-overview-v2-{digest[:16]}.jpg').write_bytes(b'overview')
    assert reference_review_info(enriched,tmp_path)['reference_scene_context']==enriched['reference_scene_context']
    import json
    manifest_path=tmp_path/'manifest.json'
    manifest_path.write_text(json.dumps(manifest),encoding='utf8')
    state['source_search_manifest_path']=str(manifest_path)
    assert reference_review_info(state,tmp_path)['reference_scene_context']==enriched['reference_scene_context']


def test_conflicting_duplicate_scene_ids_are_not_admitted():
    check={'scene_id':'x','visible_content_supported':True,'role_plausible':True,'alternatives_relevant':True}
    assert approved_scenes({'reference_scenes':[scene('x'),scene('x')]},{'scene_checks':[check]},
                           {'frames':[{'id':'frame-1'}]})==[]
