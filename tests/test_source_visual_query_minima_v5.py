"""Approved dispatch-pool minima, immutable visual caches, and actual scope reuse."""
import copy
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from hotpost import source_visual_queries as visual
from hotpost.source_queries import tiktok_product_queries,platform_queries
from hotpost.source_search.planner import round_queries,grounded_actions
from hotpost.source_search.strategy import minimum_search_queries


WORDS={'en':['stand collar jacket','horizontal quilted jacket','front zip jacket','zip pocket jacket','short hem jacket'],
       'zh':['立领夹克','横向绗缝夹克','前拉链夹克','拉链口袋夹克','短下摆夹克']}


def setup(tmp_path):
    reference=tmp_path/'reference.mp4';reference.write_bytes(b'fixed actual original')
    frame=tmp_path/'native.jpg';Image.new('RGB',(12,12),'gray').save(frame)
    return SimpleNamespace(data_dir=tmp_path),reference,[frame]


def proposal(extra=False):
    rows=[{'id':f'{lang}-{i}','query':query,'language':lang,
           'observation_ids':['observed'],'frame_ids':['frame-1']}
          for lang,words in WORDS.items() for i,query in enumerate(words)]
    if extra:
        rows += [{'id':f'unsupported-{i}','query':query,'language':'zh',
                  'observation_ids':['observed'],'frame_ids':['frame-1']}
                 for i,query in enumerate(['棉服','羽绒服'])]
    return {'subject_identity':{'version':'core-product-identity-v1','kind':'category',
                'product_terms':{'en':['jacket'],'zh':['夹克'],'ko':['재킷']},'required_terms':[]},
        'observations':[{'id':'observed','text':'세워진 칼라, 가로 퀼팅, 앞 지퍼, 지퍼 주머니와 짧은 밑단',
                             'frame_ids':['frame-1']}],'queries':rows}


def model(value,calls,reject=()):
    def generate(settings,instruction,data,**kwargs):
        calls.append(instruction)
        if 'proposal_sha256' not in data:return copy.deepcopy(value)
        return {'input_sha256':data['input_sha256'],'proposal_sha256':data['proposal_sha256'],
                'subject_identity_supported':True,'core_identity_complete':True,
                'checks':[{'query_id':q['id'],'supported':q['id'] not in reject,'central_product':True,
                           'short_noun_phrase':True,'no_unobserved_claims':q['id'] not in reject,
                           'core_identity_preserved':True}
                          for q in value['queries']]}
    return generate


def plan(receipt):
    return visual.apply_visual_queries({'search_minimums':{'en':5,'zh':5},
        'minimum_query_plan':{'en':{'minimum':5,'count':11},'zh':{'minimum':5,'count':11}},
        'minimum_query_plan_ready':True,'products':[],
        'query_evidence':receipt['evidence']['text'],'query_details':[
            {'query':'unsupported material jacket storage','language':'en','intent':'technique',
             'role':'subject_action','evidence_quote':'저장해두세요'}]},receipt,
        reference_sha256=receipt['evidence']['reference_sha256'])


def test_v5_approved_more_than_nine_queries_survive_actual_round_and_tiktok_dispatch(tmp_path):
    settings,reference,frames=setup(tmp_path);calls=[]
    receipt=visual.cached_visual_queries(settings,reference,frames,'재킷',{},model(proposal(),calls),
                                         search_minimums={'en':5,'zh':5})
    assert len(calls)==2 and 'FIVE' in calls[0]
    assert receipt['policy']==visual.MINIMUM_POLICY and len(receipt['queries'])==10
    document=plan(receipt)
    assert document['generated_query_pool']['en']['count']==11
    assert document['minimum_query_plan_ready'] and document['minimum_query_plan']['zh']['count']==5
    for phase in ['core_action','clean_action','scene_discovery']:
        dispatched=round_queries(document,{'phase':phase})
        assert {r['query'] for r in dispatched}=={q for words in WORDS.values() for q in words}
        assert len(dispatched)==10 and all(not r.get('search_condition') for r in dispatched)
        tiktok=tiktok_product_queries(document)
        assert len(platform_queries(tiktok,'tiktok',10,search_minimums={'en':5,'zh':5}))==10
    assert 'storage' not in ' '.join(r['query'] for r in dispatched)


def test_old_visual_receipt_cache_is_preserved_and_cannot_satisfy_new_v5_contract(tmp_path):
    settings,reference,frames=setup(tmp_path);value=proposal();calls=[]
    old=visual.cached_visual_queries(settings,reference,frames,'재킷',{},model(value,calls))
    old_path=tmp_path/'source-visual-queries'/old['input_sha256']/'receipt.json';old_bytes=old_path.read_bytes()
    assert len(old['queries'])==9
    with pytest.raises(ValueError,match='최소 검색 계획'):plan(old)
    new=visual.cached_visual_queries(settings,reference,frames,'재킷',{},model(value,calls),
                                     search_minimums={'en':5,'zh':5})
    assert old['input_sha256']!=new['input_sha256'] and len(calls)==4
    assert old_path.read_bytes()==old_bytes
    again=visual.cached_visual_queries(settings,reference,frames,'재킷',{},
        lambda *a,**k:pytest.fail('same completed v5 evidence cannot call model again'),search_minimums={'en':5,'zh':5})
    assert again==new


def test_independently_rejected_materials_never_return_to_fill_a_shortfall(tmp_path):
    settings,reference,frames=setup(tmp_path);calls=[];value=proposal(extra=True)
    receipt=visual.cached_visual_queries(settings,reference,frames,'재킷',{},
        model(value,calls,reject={'zh-4','unsupported-0','unsupported-1'}),search_minimums={'en':5,'zh':5})
    document=plan(receipt)
    assert document['minimum_query_plan']['zh']['count']==4 and not document['minimum_query_plan_ready']
    dispatched=round_queries(document,{'phase':'scene_discovery'})
    assert len(dispatched)==9 and not any(r['query'] in {'棉服','羽绒服'} for r in dispatched)
    assert document['generated_query_pool']['zh']['count']==11
    assert any('미충족' in note for note in document['planning_notes'])


def test_even_positive_visual_flags_cannot_infer_filling_from_generic_padding_text(tmp_path):
    settings,reference,frames=setup(tmp_path);calls=[]
    receipt=visual.cached_visual_queries(settings,reference,frames,'경량 패딩',{},
        model(proposal(extra=True),calls),search_minimums={'en':5,'zh':5})
    assert {r['query'] for r in receipt['queries']}=={q for words in WORDS.values() for q in words}


def test_accepted_query_pool_deduplicates_spacing_and_does_not_trust_old_generated_count(tmp_path):
    settings,reference,frames=setup(tmp_path);calls=[];value=proposal()
    for i,row in enumerate(value['queries']):
        if row['language']=='zh':row['query']='立 领 夹 克' if i%2 else '立领夹克'
    receipt=visual.cached_visual_queries(settings,reference,frames,'재킷',{},model(value,calls),search_minimums={'en':5,'zh':5})
    document=plan(receipt)
    assert document['minimum_query_plan']['zh']['count']==1 and not document['minimum_query_plan_ready']
    assert len([r for r in round_queries(document,{'phase':'clean_action'}) if r['language']=='zh'])==1


def test_existing_three_actual_queries_are_not_retransmitted_to_same_platform_after_new_plan(tmp_path):
    settings,reference,frames=setup(tmp_path);calls=[]
    receipt=visual.cached_visual_queries(settings,reference,frames,'재킷',{},model(proposal(),calls),search_minimums={'en':5,'zh':5})
    queries=tiktok_product_queries(plan(receipt));old=[WORDS['en'][0],WORDS['en'][1],WORDS['zh'][0]]
    history=[{'provider':'tiktok','query':q,'status':'results','execution':{
        'query_submitted':True,'query_url_matched':True,'input_value':q}} for q in old]
    remaining=minimum_search_queries(queries,'tiktok',history,{'en':5,'zh':5},10)
    assert len(remaining)==7 and not set(old)&set(remaining)
    assert len(history)==3


def test_v5_accepts_seven_nouns_per_priority_language_and_dispatch_limit_keeps_five_each(tmp_path):
    settings,reference,frames=setup(tmp_path);calls=[];value=proposal()
    for lang,phrases in {'en':['quilted collar jacket','horizontal seam jacket'],
                         'zh':['绗缝立领夹克','横缝夹克'],'ko':['스탠드칼라 재킷','가로 퀼팅 재킷']}.items():
        value['queries'] += [{'id':f'extra-{lang}-{i}','query':q,'language':lang,
            'observation_ids':['observed'],'frame_ids':['frame-1']} for i,q in enumerate(phrases)]
    receipt=visual.cached_visual_queries(settings,reference,frames,'재킷',{},model(value,calls),search_minimums={'en':5,'zh':5})
    assert len(receipt['queries'])==16
    dispatched=platform_queries(tiktok_product_queries(plan(receipt)),'tiktok',10,search_minimums={'en':5,'zh':5})
    from hotpost.source_queries import language
    assert [language(q) for q in dispatched]==['en','zh']*5


def test_old_v5_preparation_uses_natural_topic_contract_once_without_rebuilding_media(tmp_path,monkeypatch):
    from pathlib import Path
    from test_source_preparation_reuse import finder_fixture
    from hotpost import source_finder as finder,source_preparation as preparation
    from hotpost.source_policy import montage_policy
    real_cached=visual.cached_visual_queries
    settings,counters=finder_fixture(tmp_path,monkeypatch)
    first=finder.find_sources(settings,'reused-reference')
    old_path=Path(first['preparation_bundle_path']);value=json.loads(old_path.read_text('utf-8'))
    calls=[];empty={'observations':[],'queries':[]}
    legacy_visual=real_cached(settings,Path(value['reference']),[Path(x) for x in value['frames']],
        '은색 거울',value['transcript'],model(empty,calls))
    old_plan={**value['query_plan'],'source_policy':montage_policy(),'search_minimums':{'en':5,'zh':5},
              'visual_query_evidence':legacy_visual,'query_reference_sha256':legacy_visual['evidence']['reference_sha256']}
    preparation.save_bundle(old_path,'은색 거울',value['transcript'],Path(value['reference']),
        [Path(x) for x in value['frames']],Path(value['sheet']),transcript=value['transcript'],query_plan=old_plan)
    old_bytes=old_path.read_bytes();media_before={k:counters[k] for k in ('download','frames','sheet','visual_queries')}
    settings.source_query_model_enabled=True;expanded=[]
    monkeypatch.setattr('hotpost.source_planning.cached_enrich_plan',lambda settings,base,*a,**kw:expanded.append(1) or base)
    from hotpost import source_topic_queries as topic
    actual_topic=topic.cached_topic_queries
    def current_cached(settings,reference,frames,caption,transcript,**kwargs):
        value={'observations':[],'subject_identity':{'version':'core-product-identity-v2','kind':'category',
            'product_terms':{'en':['mirror'],'zh':['镜子'],'ko':['거울']},'required_terms':[]},
            'queries':[{'id':lang,'query':query,'language':lang,'viewpoint':'product','semantic_key':'product',
                'text_quotes':[{'source':'caption','quote':'은색 거울'}],'frame_ids':[]}
                for lang,query in [('en','silver mirror'),('zh','银色 镜子')]]}
        def generate(s,instruction,data,**kw):
            calls.append(1)
            if 'proposal_sha256' not in data:return value
            return {'input_sha256':data['input_sha256'],'proposal_sha256':data['proposal_sha256'],
                'search_only':True,'subject_identity_supported':True,'core_identity_complete':True,
                'known_subject_identity_complete':True,
                'checks':[{'query_id':q['id'],**dict.fromkeys(topic.FLAGS,True)} for q in value['queries']]}
        return actual_topic(settings,reference,frames,caption,transcript,generate,**kwargs)
    monkeypatch.setattr(topic,'cached_topic_queries',current_cached)
    owner={'task_id':'task','job_id':'job','run_id':'run'}
    context={'source_policy':montage_policy(),**owner,
        'search_context':{'reference_sha256':value['files'][0]['sha256']}}
    def progress(*a):pass
    progress.visual_query_input=lambda key:dict(owner)
    second=finder.find_sources(settings,'reused-reference',progress,search_context=context)
    assert second['preparation_bundle_path']!=str(old_path.resolve()) and old_path.read_bytes()==old_bytes
    # A grounded partial pool may search; actual language minima remain unmet.
    assert not second['product_evidence']['minimum_query_plan_ready'] and len(second['query_details'])==2
    assert second['product_evidence']['query_selection_policy']==topic.POLICY
    newer=Path(second['preparation_bundle_path']);new_bytes=newer.read_bytes()
    third=finder.find_sources(settings,'reused-reference',progress,search_context=context)
    assert third['preparation_bundle_path']==second['preparation_bundle_path'] and newer.read_bytes()==new_bytes
    assert len(expanded)==1 and len(calls)==4  # old pair + one new v5 pair only
    assert {k:counters[k] for k in media_before}==media_before


@pytest.mark.parametrize('text',['저장해 두고 쇼핑할 때 꺼내 보기','이 영상 저장해두세요','저장해 주세요',
                                 '保存这条视频以后看'])
def test_bookmark_cta_does_not_invent_physical_storage_action(text):
    product={'products':[{'ko':'패딩','en':'puffer jacket','zh':'夹克'}]}
    assert not any('storage' in r['query'] or '보관' in r['query'] or '保存' in r['query']
                   for r in grounded_actions(product,{'caption':text}))


@pytest.mark.parametrize('text',['보관 용기에 넣어 저장해두세요','밀폐 용기에 담아 저장합니다','용기에 넣어 저장'])
def test_actual_physical_storage_action_remains_supported(text):
    product={'products':[{'ko':'마늘','en':'garlic','zh':'大蒜'}]}
    assert any('storage' in r['query'] for r in grounded_actions(product,{'caption':text}))


def test_search_only_worker_uses_current_run_two_en_one_zh_and_submits_only_missing_three_four(tmp_path,monkeypatch):
    from hotpost import browser_search as bs
    monkeypatch.setattr(bs,'BROWSER_COOLDOWNS',{})
    from hotpost.config import Settings
    from hotpost.source_coverage import actual_search_coverage
    from hotpost.source_queries import language
    words={**WORDS,'en':[*WORDS['en'],'quilted collar jacket','horizontal seam jacket'],
           'zh':[*WORDS['zh'],'绗缝立领夹克','横缝夹克']}
    from hotpost.source_queries import register_tiktok_noun_head
    for queries in words.values():
        for query in queries:register_tiktok_noun_head(query)
    previous=[{'provider':'tiktok','query':q,'language':language(q),'status':'results',
        'execution':{'query_submitted':True,'query_url_matched':True,'input_value':q}}
        for q in [WORDS['en'][0],WORDS['en'][1],WORDS['zh'][0]]]
    page=SimpleNamespace(wait_for_timeout=lambda *a:None,mouse=SimpleNamespace(wheel=lambda *a:None))
    worker=bs.BrowserSearcher(Settings(data_dir=tmp_path,source_queries_per_platform=1),tmp_path/'debug')
    worker.search_only=True;worker.search_minimums={'en':5,'zh':5};worker.previous_searches=copy.deepcopy(previous)
    monkeypatch.setattr(worker,'_pace',lambda *a,**kw:None)
    monkeypatch.setattr(worker,'_page',lambda *a:page)
    monkeypatch.setattr(worker,'_check_block',lambda *a:False)
    monkeypatch.setattr(worker,'_cooling_down',lambda *a,**kw:False)
    def submit(page,provider,query,audit):
        audit['execution']={'query_submitted':True,'query_url_matched':True,'input_value':query};return True
    monkeypatch.setattr(worker,'_submit_search',submit)
    monkeypatch.setattr(worker,'_wait_platform_results',lambda p,provider,q,audit,hits:[{'url':f'https://www.tiktok.com/@a/video/{q}'}])
    worker._platforms(None,[*words['en'],*words['zh']],100,providers={'tiktok'})
    assert len(worker.searches)==7
    assert [r['language'] for r in worker.searches].count('en')==3
    assert [r['language'] for r in worker.searches].count('zh')==4
    assert not {r['query'] for r in previous}&{r['query'] for r in worker.searches}
    assert all(r['ready'] for r in actual_search_coverage([*previous,*worker.searches],worker.search_minimums).values())
    assert worker.previous_searches==previous


@pytest.mark.parametrize('case',['approved_inventory','missing_inventory','manual_request','caller_boolean',
                                'quality_repair','unresolved_scene','different_scope'])
def test_zero_received_review_gates_search_only_and_avoids_unneeded_downloads(tmp_path,monkeypatch,case):
    from pathlib import Path
    from test_source_preparation_reuse import finder_fixture
    from test_source_diversity_completion_recovery import setup as studio_fixture
    from hotpost import source_finder as finder
    from hotpost.source_policy import montage_policy
    from hotpost.source_coverage import search_scope_for_state
    from hotpost.source_batches import TaskBatchReviewer
    studio,task,_,old_edit=studio_fixture(tmp_path/'studio-fixture')
    studio.store.finish(old_edit,{},lambda *a:None)
    def pending(s,db):
        s['source_acquisition']['queries']=[]
        if case=='missing_inventory':s['sources'].pop()
        if case=='unresolved_scene':s['daily_quality']={'scene_requirements':{'ready':False}}
        studio.ensure_source_collection(s,db)
    studio.store.change(task,pending)
    job=studio.store.claim('sources',task_id=task)
    if case=='quality_repair':job['payload']['daily_quality_repair']=True
    state=studio.store.get(task)
    studio._source_records=lambda *a:[]
    studio._review_source_records=lambda state,job,rows,*a:(rows,None)
    studio._recover_local_source_intervals=lambda *a:None
    review=TaskBatchReviewer(studio,job,lambda *a:None)
    settings,_=finder_fixture(studio.settings.data_dir,monkeypatch);settings.source_browser_search=True
    dispatched=[];downloaded=[]
    if case=='caller_boolean':review=lambda *a:{'ready':True,'goal':{'source_diversity_ready':True,'core_ready':True}}
    monkeypatch.setattr(finder,'_download_reference',lambda *a:Path(state['reference_video']))
    def discover(settings,code,frames,queries,document,vision,root,*args,**kwargs):
        dispatched.append(document.get('search_only',False))
        candidate=finder.Candidate('https://www.youtube.com/watch?v=newvideo001','youtube')
        receipts=[{'provider':'tiktok','query':q,'language':lang,'status':'results',
                   'execution':{'query_submitted':True,'query_url_matched':True,'input_value':q}}
                  for lang,words in WORDS.items() for q in words]
        return [candidate],queries,{'notes':[]},receipts,0
    monkeypatch.setattr('hotpost.source_search.discovery.discover',discover)
    monkeypatch.setattr(finder,'download_candidate',lambda *a,**kw:downloaded.append(1))
    result=finder.find_sources(settings,'reused-reference',review_batch=review,
        search_request='명시적 새 소스 요청' if case=='manual_request' else '',
        search_context={'source_policy':montage_policy(),'query_only':True,'run_id':state['run_id'],
                        'search_context':{} if case=='different_scope' else search_scope_for_state(state)})
    if case=='approved_inventory':
        assert dispatched==[True] and not downloaded
        assert (Path(result['zip_path']).parent/'batch-0000.json').is_file()
        assert (Path(result['zip_path']).parent/'batch-0001.json').is_file()
        assert result['probe_attempts']==0 and result['batch_review']['ready']
        assert result['budget_stop']=='search_receipts_only_existing_reviewed_inventory'
    else:
        assert dispatched==[False] and downloaded
