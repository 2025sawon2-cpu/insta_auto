"""Actual title ordering is advisory; query and media contracts stay exact."""
import copy
import json
from dataclasses import fields
from pathlib import Path

import pytest

from hotpost.source_search.models import Candidate
from hotpost.source_search import triage as staged
from hotpost.source_queries import tiktok_product_queries
from hotpost.source_coverage import actual_search_coverage
from test_source_topic_queries import topic_case

FIXTURE=Path(__file__).resolve().parent/'fixtures/topic_title_spark_candidates.json'


def candidate(title,url='https://www.bilibili.com/video/BV1Hp4y187tH/'):
    return Candidate(url=url,provider='playwright-bilibili',title=title)


def unchanged_fields(before,after):
    allowed={'discovery_score','discovery_reasons'}
    return all(getattr(before,f.name)==getattr(after,f.name) for f in fields(Candidate) if f.name not in allowed)


def test_captured_twelve_put_supported_category_before_printer_game_news():
    document=json.loads(FIXTURE.read_text('utf8'))
    allowed={f.name for f in fields(Candidate)}
    candidates=[candidate(row['title'],f'https://www.bilibili.com/video/captured-{i}/')
        for i,row in enumerate(document['candidates'],1)]
    original=copy.deepcopy(candidates);plan=copy.deepcopy(document['product_evidence'])
    plan_before=copy.deepcopy(plan)
    staged.rank_candidates(candidates,plan)
    assert [i+1 for i,c in enumerate(candidates) if c.discovery_score>0]==[1,2,4,5,6,7]
    assert all(candidates[i-1].discovery_score==0 for i in (3,8,9,10,11,12))
    assert all(unchanged_fields(a,b) for a,b in zip(original,candidates))
    assert plan==plan_before
    from hotpost.source_targets import candidate_batch
    ordered=candidate_batch(candidates,len(candidates),0,core_priority=True)
    assert [candidates.index(c)+1 for c in ordered[:6]]==[1,2,4,5,6,7]


@pytest.mark.parametrize('title,score',[
    ('Dior perfume',8),('Han So Hee perfume interview',2),('花香 香水 展示',2),
    ('迪奥 香水 展示',8),('Han So Hee fan concert',0),('手持喷墨打印机mbrush的介绍',0)])
def test_perfume_identity_and_related_person_context_are_priority_only(topic_case,title,score):
    plan=topic_case.make();plan['source_policy']['core_product_priority']={'version':'core-product-first-v1'}
    c=candidate(title);old=copy.deepcopy(c)
    staged.rank_candidates([c],plan)
    assert c.discovery_score==score
    assert unchanged_fields(old,c)


def test_longest_approved_shared_product_phrase_does_not_promote_machine_fragment():
    document=json.loads(FIXTURE.read_text('utf8'))
    identity=document['product_evidence']['search_identity']
    assert staged._topic_title_priority('professional spark machine display',identity)[0]==2
    assert staged._topic_title_priority('sewing machine maintenance',identity)[0]==0
    assert staged._topic_title_priority('handheld inkjet printer introduction',identity)[0]==0
    assert staged._topic_title_priority('handheld spark machine demonstration',identity)[0]==2
    assert staged._topic_title_priority('handheld spark fountain demonstration',identity)[0]==8


def test_partial_evidence_requires_two_distinct_approved_intents_and_identity_fragment(topic_case):
    plan=topic_case.make();identity=plan['search_identity']
    identity['approved_queries']=[identity['approved_queries'][0]]
    assert staged._topic_title_priority('perfume interview',identity)[0]==0
    assert staged._topic_title_priority('celebrity fan video',topic_case.make()['search_identity'])[0]==0


@pytest.mark.parametrize('version',['core-product-identity-v1','core-product-identity-v2'])
def test_legacy_rank_is_identical_to_existing_rank(version):
    from test_source_query_identity import photo_magnet
    identity=photo_magnet();identity['version']=version
    plan={'source_policy':{'core_product_priority':{}},'search_identity':identity,'products':[]}
    # Truthy policy tests the existing identity bonus path too.
    plan['source_policy']['core_product_priority']={'version':'core-product-first-v1'}
    originals=[candidate(t) for t in ['사진 삽입형 DIY 냉장고 자석','냉장고 자석','다른 물건','']]
    result=staged.rank_candidates(copy.deepcopy(originals),copy.deepcopy(plan))
    assert [c.discovery_score for c in result]==([0,0,0,0] if version=='core-product-identity-v1' else [8,0,0,0])
    assert result[-1].discovery_reasons==['제목 없음 · 영상 검사로 판단']
    assert all(unchanged_fields(a,b) for a,b in zip(originals,result))


def test_title_order_never_expands_transport_pool_or_actual_search_count(topic_case):
    plan=topic_case.make();plan['source_policy']['core_product_priority']={'version':'core-product-first-v1'}
    before=copy.deepcopy(plan);queries=tiktok_product_queries(plan)
    receipt={'provider':'tiktok','query':queries[0],'status':'results','candidates':1,
        'execution':{'query_submitted':True,'query_url_matched':True},'search_identity':plan['search_identity']}
    coverage=actual_search_coverage([receipt],{'en':5,'zh':5},plan['search_identity'])
    staged.rank_candidates([candidate('Han So Hee perfume'),candidate('random game')],plan)
    assert plan==before and tiktok_product_queries(plan)==queries
    assert actual_search_coverage([receipt],{'en':5,'zh':5},plan['search_identity'])==coverage
    assert coverage['en']['count']==1 and coverage['zh']['count']==0
    assert all(row['count']==0 for row in actual_search_coverage([],{'en':5,'zh':5},plan['search_identity']).values())
