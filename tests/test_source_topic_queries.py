import copy
from types import SimpleNamespace
import pytest
from PIL import Image
from hotpost import source_topic_queries as topic
from hotpost.source_visual_queries import digest,apply_visual_queries,plan_queries
from hotpost.source_queries import tiktok_product_queries,platform_queries
from hotpost.source_query_identity import matches_identity,query_identity
from hotpost.source_search.planner import round_queries
from hotpost.source_search.strategy import minimum_search_queries
from hotpost.source_coverage import actual_search_coverage


@pytest.fixture
def topic_case(tmp_path):
    reference=tmp_path/'reference.mp4';reference.write_bytes(b'contract-test-not-a-real-video')
    frame=tmp_path/'frame.jpg';Image.new('RGB',(24,32),'gray').save(frame)
    caption='한소희 디올 향수 꽃향기'
    owner={'task_id':'task','job_id':'job','run_id':'run'}
    evidence=topic.binding(reference,[frame],caption,{},search_minimums={'en':5,'zh':5},subject_hint='향수',owner_binding=owner)
    identity={'version':'core-product-identity-v2','kind':'branded',
        'product_terms':{'en':['perfume'],'zh':['香水'],'ko':['향수']},
        'required_terms':[{'kind':'brand','terms':{'en':['Dior'],'zh':['迪奥'],'ko':['디올']},
            'source':'caption','quote':'디올 향수'}]}
    values=[('Han So Hee perfume','en','person','person'),('Dior perfume','en','brand','brand'),
        ('floral perfume','en','appeal','floral'),('celebrity perfume','en','context','celebrity'),
        ('popular perfume','en','purpose','popular'),('韩素希 香水','zh','person','person'),
        ('迪奥 香水','zh','brand','brand'),('花香 香水','zh','appeal','floral'),
        ('明星 香水','zh','context','celebrity'),('热门 香水','zh','purpose','popular')]
    proposal={'subject_identity':identity,'observations':[],
        'queries':[{'id':str(i),'query':q,'language':lang,'viewpoint':view,'semantic_key':key,
            'text_quotes':[{'source':'caption','quote':caption}],'frame_ids':[]} for i,(q,lang,view,key) in enumerate(values)]}
    review={'input_sha256':digest(evidence),'proposal_sha256':digest(proposal),'search_only':True,
        'subject_identity_supported':True,'core_identity_complete':True,'known_subject_identity_complete':True,
        'checks':[{'query_id':q['id'],**dict.fromkeys(topic.FLAGS,True)} for q in proposal['queries']]}
    calls=[]
    def generate(settings,instruction,data,**kwargs):
        calls.append((instruction,data,kwargs))
        return copy.deepcopy(proposal if 'proposal_sha256' not in data else review)
    def make():
        receipt=topic.cached_topic_queries(SimpleNamespace(data_dir=tmp_path),reference,[frame],caption,{},generate,
            search_minimums={'en':5,'zh':5},subject_hint='향수',owner_binding=owner)
        plan={'query_details':[],'query_evidence':evidence['text'],'search_minimums':{'en':5,'zh':5},
            'source_policy':{'search_minimums':{'en':5,'zh':5}},'run_id':'run',
            'search_context':{'reference_sha256':evidence['reference_sha256']},'products':[]}
        return apply_visual_queries(plan,receipt,reference_sha256=evidence['reference_sha256'])
    return SimpleNamespace(**locals())


def test_reviewed_topic_reaches_real_pool_dispatch_and_quota_without_brand_in_each_query(topic_case):
    c=topic_case;plan=c.make();rows=round_queries(plan,{'phase':'core_action'})
    assert len(rows)==10 and all('Dior' not in r['query'] for r in rows if r['semantic_key']=='person')
    assert plan['search_identity']['required_terms']==c.identity['required_terms']
    assert plan['products']==[]  # searching never promotes a product fact
    assert tiktok_product_queries(plan)==[r['query'] for r in rows]
    assert platform_queries(tiktok_product_queries(plan),'bilibili',20)==[r['query'] for r in rows if r['language']=='zh']
    assert minimum_search_queries([r['query'] for r in rows],'tiktok',[],{'en':5,'zh':5},20,
        search_identity=plan['search_identity'])
    coverage=actual_search_coverage([],{'en':5,'zh':5},plan['search_identity'])
    assert coverage['en']['count']==coverage['zh']['count']==0  # generated is not executed
    assert not matches_identity('unreviewed perfume',plan['search_identity'])
    assert query_identity('Han So Hee perfume',plan['search_identity'])=='en:topic:person'
    assert len(c.calls)==2 and all(x[2]['media'][1]['inlineData']['data'] for x in c.calls)
    assert all(set((x[1].get('evidence') or x[1])['text'])=={'caption','speech','screen_text'} for x in c.calls)
    assert plan_queries(plan)==rows


@pytest.mark.parametrize('flag',topic.FLAGS)
def test_independent_search_value_rejection_is_never_dispatched(topic_case,flag):
    c=topic_case;c.review['checks'][0][flag]=False
    plan=c.make()
    assert 'Han So Hee perfume' not in tiktok_product_queries(plan)
    assert not plan['minimum_query_plan_ready']


def test_discovery_keeps_unknown_sku_and_caption_notes_without_visual_promotion(topic_case):
    c=topic_case
    c.proposal['observations']=[{'id':'caption-note','text':'Dior in caption; model unknown','frame_ids':[]}]
    c.review['core_identity_complete']=False
    c.review['proposal_sha256']=digest(c.proposal)
    plan=c.make()
    assert len(plan_queries(plan))==10
    assert plan['visual_query_evidence']['review']['core_identity_complete'] is False
    assert plan['products']==[]
    assert not actual_search_coverage([],{'en':5,'zh':5},plan['search_identity'])['en']['count']


def test_discovery_still_requires_independent_known_identity_support(topic_case):
    c=topic_case;c.review['subject_identity_supported']=False
    with pytest.raises(ValueError):c.make()


def test_partial_comparison_identity_does_not_veto_independently_supported_searches(topic_case):
    c=topic_case;c.review.update(core_identity_complete=False,known_subject_identity_complete=False)
    plan=c.make()
    assert len(plan_queries(plan))==10 and plan['products']==[]
    assert plan['visual_query_evidence']['review']['known_subject_identity_complete'] is False
    assert not actual_search_coverage([],{'en':5,'zh':5},plan['search_identity'])['en']['count']


def test_old_r2_receipt_still_requires_its_original_known_completeness_flag(topic_case):
    c=topic_case;evidence=copy.deepcopy(c.evidence)
    evidence.update(discovery_contract_version=2,identity_prompt_revision=topic.POLICY+'-discovery-r2')
    review=copy.deepcopy(c.review);review.update(input_sha256=digest(evidence),known_subject_identity_complete=False)
    with pytest.raises(ValueError,match='known subject identity'):topic._validate(c.proposal,review,evidence)


def ocr_case(c):
    frame_id=c.evidence['frames'][0]['id'];quote='최근에는 꽃 향기라고 해야 할까요?'
    c.evidence['text']['screen_text']='최근예는 꽃 향기라고 해야 함까요?'
    c.proposal['observations']=[{'id':'visible-text','text':quote,'frame_ids':[frame_id]}]
    c.proposal['subject_identity']['required_terms'].append({'kind':'feature',
        'terms':{'en':['floral'],'zh':['花香'],'ko':['꽃향기']},'source':'screen_text',
        'quote':quote,'observation_ids':['visible-text']})
    q=c.proposal['queries'][2];q['text_quotes']=[{'source':'screen_text','quote':quote}];q['frame_ids']=[frame_id]
    c.review.update(input_sha256=digest(c.evidence),proposal_sha256=digest(c.proposal))


def test_actual_pixel_evidence_survives_ocr_typo_without_rewriting_original(topic_case):
    c=topic_case;ocr_case(c);before=copy.deepcopy((c.evidence,c.proposal,c.review))
    rows,identity=topic._validate(c.proposal,c.review,c.evidence)
    assert len(rows)==10
    assert rows[2]['screen_text_visual_evidence']['ocr_quote_literal_match'] is False
    assert identity['required_terms'][1]['source_evidence']['frame_ids']==c.proposal['queries'][2]['frame_ids']
    assert (c.evidence,c.proposal,c.review)==before


@pytest.mark.parametrize('fault',['no_visual_observation','no_query_frame','wrong_source','rejected_review','legacy_r3','disjoint_frame','no_observed_quote'])
def test_ocr_normalization_never_invents_unbound_evidence(topic_case,fault):
    c=topic_case;ocr_case(c)
    if fault=='no_visual_observation':c.proposal['observations'][0]['frame_ids']=[]
    if fault=='no_query_frame':c.proposal['queries'][2]['frame_ids']=[]
    if fault=='wrong_source':c.proposal['queries'][2]['text_quotes'][0]['source']='caption'
    if fault=='rejected_review':c.review['checks'][2]['supported']=False
    if fault=='legacy_r3':c.evidence.update(discovery_contract_version=3,identity_prompt_revision=topic.POLICY+'-discovery-r3')
    if fault=='no_observed_quote':c.proposal['observations'][0]['text']='unrelated visual observation'
    if fault=='disjoint_frame':
        second=copy.deepcopy(c.evidence['frames'][0]);second['id']='other-actual-frame'
        c.evidence['frames'].append(second);c.proposal['queries'][2]['frame_ids']=[second['id']]
    c.review.update(input_sha256=digest(c.evidence),proposal_sha256=digest(c.proposal))
    if fault=='rejected_review':assert len(topic._validate(c.proposal,c.review,c.evidence)[0])==9
    else:
        with pytest.raises(ValueError):topic._validate(c.proposal,c.review,c.evidence)


def test_discovery_records_exact_product_completeness_honestly(topic_case):
    c=topic_case;c.review.pop('core_identity_complete')
    with pytest.raises(ValueError):c.make()


def test_caption_note_cannot_be_used_as_actual_visual_identity_evidence(topic_case):
    c=topic_case
    c.proposal['observations']=[{'id':'text-only','text':'No actual visual support','frame_ids':[]}]
    c.proposal['subject_identity']['required_terms'].append({'kind':'feature',
        'terms':{'en':['ribbon'],'zh':['丝带'],'ko':['리본']},'source':'visual','observation_ids':['text-only']})
    c.review['proposal_sha256']=digest(c.proposal)
    with pytest.raises(ValueError,match='시각 고정 조건'):c.make()


def test_old_discovery_receipts_keep_complete_identity_requirement(topic_case):
    c=topic_case;evidence=copy.deepcopy(c.evidence)
    evidence.pop('discovery_contract_version');evidence['identity_prompt_revision']=topic.POLICY
    review=copy.deepcopy(c.review);review['input_sha256']=digest(evidence)
    review.pop('known_subject_identity_complete')
    assert len(topic._validate(c.proposal,review,evidence)[0])==10
    review['core_identity_complete']=False
    with pytest.raises(ValueError,match='핵심 제품 정체성'):topic._validate(c.proposal,review,evidence)


@pytest.mark.parametrize('fault',['owner','reference','frame','text','approved_query','review','unreviewed_query','run','coherent_owner'])
def test_changed_owner_or_original_evidence_cannot_reach_transport(topic_case,fault):
    c=topic_case;plan=c.make()
    if fault=='owner':plan['query_owner']['task_id']='other'
    if fault=='reference':c.reference.write_bytes(b'changed')
    if fault=='frame':c.frame.write_bytes(b'changed')
    if fault=='text':plan['query_evidence']['caption']='other'
    if fault=='approved_query':plan['visual_query_evidence']['queries'][0]['query']='other perfume'
    if fault=='review':plan['visual_query_evidence']['review']['proposal_sha256']='other'
    if fault=='unreviewed_query':plan['search_identity']['approved_queries'][0]['query']='other perfume'
    if fault=='run':plan['run_id']='other'
    if fault=='coherent_owner':
        other={'task_id':'other','job_id':'other-job','run_id':'other-run'}
        plan['query_owner']=other;plan['run_id']='other-run';plan['visual_query_evidence']['owner']=other
    with pytest.raises(ValueError):tiktok_product_queries(plan)


def test_semantic_duplicates_do_not_pad_language_minimum(topic_case):
    c=topic_case
    c.proposal['queries'][1]['semantic_key']='person'
    c.review['proposal_sha256']=digest(c.proposal)
    plan=c.make()
    assert plan['minimum_query_plan']['en']['count']==4


def test_chinese_spacing_changes_do_not_pad_search_count(topic_case):
    c=topic_case
    duplicate=copy.deepcopy(c.proposal['queries'][6]);duplicate.update(id='spacing',query='迪奥香水',semantic_key='different_key')
    c.proposal['queries'].append(duplicate)
    c.review['checks'].append({'query_id':'spacing',**dict.fromkeys(topic.FLAGS,True)})
    c.review['proposal_sha256']=digest(c.proposal)
    plan=c.make()
    assert plan['minimum_query_plan']['zh']['count']==5


def test_prior_reviewed_round_counts_only_for_same_original_media_and_text(topic_case):
    c=topic_case;plan=c.make();old=copy.deepcopy(plan['search_identity'])
    row={'provider':'bilibili','query':'迪奥 香水','status':'results','candidates':1,
        'execution':{'query_submitted':True,'query_url_matched':True},'search_identity':old}
    current=copy.deepcopy(old);current['approved_queries']=[r for r in current['approved_queries'] if r['query']!='迪奥 香水']
    assert actual_search_coverage([row],{'zh':5},current)['zh']['count']==1
    for field in ('topic_reference_sha256','topic_text_sha256'):
        other=copy.deepcopy(current);other[field]='0'*64
        assert actual_search_coverage([row],{'zh':5},other)['zh']['count']==0


@pytest.mark.parametrize('second',['Dior perfume','perfume Dior'])
def test_round_intent_key_changes_do_not_count_the_same_query_twice(topic_case,second):
    c=topic_case;plan=c.make();old=copy.deepcopy(plan['search_identity']);current=copy.deepcopy(old)
    for approved in current['approved_queries']:
        if approved['query']=='Dior perfume':approved.update(query=second,semantic_key='new_brand_key')
    def row(query,profile):
        return {'provider':'tiktok','query':query,'status':'results','candidates':1,
            'execution':{'query_submitted':True,'query_url_matched':True},'search_identity':profile}
    coverage=actual_search_coverage([row('Dior perfume',old),row(second,current)],{'en':5},current)
    assert coverage['en']['count']==1
    foreign=copy.deepcopy(old);foreign['topic_reference_sha256']='0'*64
    assert actual_search_coverage([row('Dior perfume',foreign)],{'en':5},old)['en']['count']==0


@pytest.mark.parametrize('state',['ready','blocked','not_ready','consumed'])
def test_new_reviewed_scope_uses_current_ready_route_without_replaying_consumed_queries(topic_case,tmp_path,state):
    import json
    from hotpost.source_search.planner import choose_strategy
    c=topic_case;plan=c.make()
    manifest=tmp_path/'old-manifest.json'
    manifest.write_text(json.dumps({'platform_outcomes':{'bilibili':{'usable':0,'reasons':{'download_failed':4}}},
        'search_audit':[]}),encoding='utf8')
    context={'rounds':[{'manifest_path':str(manifest)}],
        'ready_routes':[] if state=='not_ready' else ['bilibili'],
        'blocked_routes':['bilibili'] if state=='blocked' else []}
    history=[]
    if state=='consumed':
        history=[{'provider':'bilibili','query':r['query'],'status':'results','candidates':1,
            'execution':{'query_submitted':True,'query_url_matched':True}}
            for r in plan_queries(plan) if r['language']=='zh']
    strategy=choose_strategy(plan,context,history)
    assert ('bilibili' in strategy['routes'])==(state=='ready')


def test_legacy_receipt_is_not_migrated_or_reinterpreted(tmp_path):
    from test_source_query_identity import photo_magnet
    identity=photo_magnet();before=copy.deepcopy(identity)
    assert not matches_identity('냉장고 자석',identity)
    assert matches_identity('사진 삽입형 DIY 냉장고 자석',identity)
    assert identity==before
