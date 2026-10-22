import copy

import pytest

from hotpost import source_visual_queries as visual
from hotpost.source_query_identity import matches_identity,query_identity,validate_identity
from hotpost.source_coverage import actual_search_coverage
from hotpost.source_search.strategy import minimum_search_queries,search_quota_needed
from test_source_visual_query_minima_v5 import setup,proposal,model,plan,WORDS


def photo_magnet(version='core-product-identity-v2'):
    return {'version':version, 'kind':'feature',
        'product_terms':{'en':['photo frame magnets'],'zh':['照片冰箱贴'],'ko':['사진 냉장고 자석']},
        'required_terms':[{'kind':'feature','terms':{'en':['DIY photo frame'],
            'zh':['自装照片'],'ko':['사진 삽입형 DIY']},'source':'caption','quote':'사진 삽입형 DIY'}]}


def test_reviewed_product_modifier_insertion_preserves_words_and_required_feature():
    identity=photo_magnet()
    assert matches_identity('사진 삽입형 DIY 냉장고 자석',identity)
    assert not matches_identity('사진 삽입형 DIY 냉장고',identity)
    assert not matches_identity('사진 냉장고 자석',identity)
    assert not matches_identity('사진 삽입형 DIY 냉장고 전자석',identity)
    assert not matches_identity('자석 사진 삽입형 DIY 냉장고',identity)
    assert not matches_identity('사진 삽입형 DIY 냉장고 자석',photo_magnet('core-product-identity-v1'))


def test_inserted_modifiers_and_overlapping_feature_do_not_pad_unique_search_count():
    identity=photo_magnet()
    queries=['사진 삽입형 DIY 사각 냉장고 자석','사각 사진 삽입형 DIY 냉장고 자석']
    assert {query_identity(q,identity) for q in queries}=={'ko:사각'}
    assert query_identity('사진 삽입형 DIY 냉장고 자석',identity)=='ko:'


def test_flexible_product_words_do_not_split_brand_or_model():
    identity=branded();identity['version']='core-product-identity-v2'
    identity['product_terms']['en']=['puffer jacket']
    identity['required_terms'].append({'kind':'model','terms':{
        'en':['EX 123'],'zh':['EX 123'],'ko':['EX 123']}})
    assert matches_identity('Montbell EX 123 puffer short jacket',identity)
    assert not matches_identity('Montbell EX short 123 puffer jacket',identity)
    assert not matches_identity('Mont bell EX 123 puffer jacket',identity)
    assert not matches_identity('Montbell EX 123 puffers jacket',identity)


def test_flexible_product_keeps_literal_punctuation_in_candidate_titles():
    identity=photo_magnet();identity.update(kind='category',required_terms=[])
    assert matches_identity('DIY photo frame magnets: square',identity)
    assert matches_identity('photo frame magnets, DIY',identity)
    assert not matches_identity('photo frame magnetship',identity)


def test_existing_rejected_korean_receipt_stays_valid_and_new_contract_can_accept(tmp_path):
    settings,reference,frames=setup(tmp_path)
    value=proposal();value['subject_identity']=photo_magnet('core-product-identity-v1')
    value['queries']=[{'id':'ko1','query':'사진 삽입형 DIY 냉장고 자석','language':'ko',
                      'observation_ids':['observed'],'frame_ids':['frame-1']}]
    old=visual.cached_visual_queries(settings,reference,frames,'사진 삽입형 DIY',{},
        model(value,[]),search_minimums={'en':5,'zh':5})
    before=copy.deepcopy(old)
    assert old['queries']==[] and visual.verify(old)==[] and old==before
    evidence=old['evidence'];value['subject_identity']['version']='core-product-identity-v2'
    review=model(value,[])(settings,'review',{'input_sha256':visual.digest(evidence),
                                            'proposal_sha256':visual.digest(value)})
    accepted=visual.validate(value,review,evidence)
    assert [r['query'] for r in accepted]==['사진 삽입형 DIY 냉장고 자석']
    assert not visual.query_pool_report(accepted,{'en':5,'zh':5},value['subject_identity'])['ready']


def branded():
    return {'version':'core-product-identity-v1','kind':'branded',
        'product_terms':{'en':['puffer jacket','quilted jacket','jacket'],'zh':['绗缝夹克','夹克'],'ko':['패딩','재킷']},
        'required_terms':[{'kind':'brand','terms':{'en':['Montbell','mont-bell'],
             'zh':['Montbell','mont-bell'],'ko':['몽벨']},'source':'speech','quote':'몽벨 패딩'}]}


def feature():
    return {'version':'core-product-identity-v1','kind':'feature',
        'product_terms':{'en':['ladle'],'zh':['汤勺'],'ko':['국자']},
        'required_terms':[{'kind':'feature','terms':{'en':['foldable'],'zh':['可折叠'],'ko':['접이식']},
                          'source':'visual','observation_ids':['observed']}]}


def history(queries,identity=None):
    return [{'provider':'tiktok','query':q,'status':'results','execution':{
        'query_submitted':True,'query_url_matched':True,'input_value':q},
        **({'search_identity':identity} if identity is not None else {})} for q in queries]


def test_montbell_must_survive_all_five_variants_in_both_languages(tmp_path):
    settings,reference,frames=setup(tmp_path);value=proposal();value['subject_identity']=branded()
    for row in value['queries']:row['query']='Montbell '+row['query']
    receipt=visual.cached_visual_queries(settings,reference,frames,'몽벨 패딩',{'speech':'몽벨 패딩'},
        model(value,[]),search_minimums={'en':5,'zh':5},subject_hint='몽벨 패딩')
    assert all(r['count']==5 and r['ready'] for r in receipt['approved_query_pool']['languages'].values())
    assert all(matches_identity(r['query'],branded()) for r in visual.plan_queries(plan(receipt)))


def test_previous_one_brand_four_generic_per_language_cannot_satisfy_minimum(tmp_path):
    settings,reference,frames=setup(tmp_path);value=proposal();value['subject_identity']=branded()
    for lang in ['en','zh']:
        next(r for r in value['queries'] if r['language']==lang)['query']='Montbell '+WORDS[lang][0]
    receipt=visual.cached_visual_queries(settings,reference,frames,'몽벨 패딩',{'speech':'몽벨 패딩'},
        model(value,[]),search_minimums={'en':5,'zh':5},subject_hint='몽벨 패딩')
    assert len(receipt['queries'])==2 and not receipt['approved_query_pool']['ready']
    assert all(r['count']==1 for r in receipt['approved_query_pool']['languages'].values())


def test_unbranded_topic_keeps_defining_feature_and_rejects_incidental_brand():
    identity=feature()
    assert matches_identity('foldable silicone ladle',identity)
    assert matches_identity('可折叠 硅胶汤勺',identity)
    assert not matches_identity('silicone ladle',identity)
    assert not matches_identity('Nike foldable ladle',identity)
    assert not matches_identity('foldable bowl',identity)


def test_unbranded_identity_can_be_independently_reviewed_without_brand():
    identity=feature()
    assert validate_identity(identity,{'subject_identity_supported':True,'core_identity_complete':True},
        {'text':{'caption':'국자','speech':'','screen_text':''},'subject_hint':'접이식 국자'},
        {'observed':{'text':'접히는 손잡이'}})==identity


def test_general_category_does_not_require_invented_feature_or_brand():
    identity=proposal()['subject_identity']
    assert matches_identity('jacket',identity)
    assert matches_identity('stand collar jacket',identity)
    assert not matches_identity('Nike jacket',identity)


def test_brand_hint_cannot_disappear_from_model_identity():
    with pytest.raises(ValueError,match='브랜드'):
        validate_identity(proposal()['subject_identity'],{'subject_identity_supported':True,'core_identity_complete':True},
            {'text':{'speech':'몽벨 패딩'},'subject_hint':'몽벨 패딩'},{})


def test_defining_unbranded_feature_cannot_disappear_from_model_identity():
    value=feature();value['kind']='category';value['required_terms']=[]
    with pytest.raises(ValueError,match='특징'):
        validate_identity(value,{'subject_identity_supported':True,'core_identity_complete':True},
            {'text':{'speech':'접이식 국자'},'subject_hint':'접이식 국자'},{})


@pytest.mark.parametrize('flag',['subject_identity_supported','core_identity_complete'])
def test_identity_independent_rejection_is_not_overridden(flag):
    review={'subject_identity_supported':True,'core_identity_complete':True};review[flag]=False
    with pytest.raises(ValueError,match='독립 검토'):
        validate_identity(branded(),review,{'text':{'speech':'몽벨 패딩'},'subject_hint':'몽벨 패딩'},{})


def test_brand_requires_literal_text_not_pixel_guess():
    identity=branded();identity['required_terms'][0]['source']='visual'
    identity['required_terms'][0]['observation_ids']=['observed']
    with pytest.raises(ValueError,match='관찰 근거'):
        validate_identity(identity,{'subject_identity_supported':True,'core_identity_complete':True},
            {'text':{},'subject_hint':'몽벨 패딩'},{'observed':{}})


def test_brand_aliases_synonyms_word_order_and_index_operators_do_not_pad_count():
    queries=['Montbell stand collar puffer jacket','stand collar mont-bell quilted jacket',
             'Montbell collar stand jacket','Montbell stand collar jacket site:tiktok.com/@ inurl:video']
    assert len({query_identity(q,branded()) for q in queries})==1
    report=actual_search_coverage(history(queries,branded()),{'en':5,'zh':5})
    assert report['en']['count']==1 and not report['en']['ready']


def test_identity_survives_manifest_merge_and_json_restart(tmp_path):
    import json
    from hotpost.source_search.strategy import merge_history,restore_history
    identity=branded()
    scope={'product':'padding','reference_sha256':'reference','reference_text_sha256':'text'}
    rows=history(['stand collar jacket','Montbell stand collar puffer jacket',
                  'stand collar mont-bell quilted jacket'],identity)
    for row in rows:row.update(run_id='current',search_context=scope)
    path=tmp_path/'manifest.json'
    path.write_text(json.dumps({'search_audit':rows,'run_id':'current','search_context':scope}),encoding='utf8')
    original=path.read_bytes()
    # Existing v2 ledgers lost identity while immutable manifests retained it.
    record={'strategy_version':2,'search_context_ledger_version':1,
            'queries':[{k:v for k,v in r.items() if k!='search_identity'} for r in rows],
            'rounds':[{'manifest_path':str(path),'run_id':'current','search_context':scope}]}
    restored=restore_history(record)
    assert all(r['search_identity']==identity for r in restored)
    merged=merge_history(restored)
    restored[0]['search_identity']['kind']='changed'
    assert merged[0]['search_identity']==identity
    restarted=json.loads(json.dumps({**record,'queries':merged}))
    report=actual_search_coverage(restore_history(restarted),{'en':5,'zh':5})
    assert report['en']['count']==1 and report['zh']['count']==0
    assert path.read_bytes()==original


def test_latest_identity_contract_does_not_relabel_old_search_or_count_captcha():
    from hotpost.source_search.strategy import merge_history
    old=branded();new=copy.deepcopy(old)
    new['required_terms'].append({'kind':'feature','terms':{'en':['foldable'],'zh':['可折叠'],'ko':['접이식']}})
    rows=history(['Montbell jacket'],old)
    captcha=history(['Montbell foldable jacket'],new)[0]
    captcha.update(status='captcha',requests=[{'url':'https://example.test/search'}])
    merged=merge_history(rows+[captcha])
    assert merged[0]['search_identity']==old
    assert actual_search_coverage(merged,{'en':5})['en']['count']==0


def test_old_generic_history_does_not_stop_new_branded_search_only_worker():
    old=history(WORDS['en']+WORDS['zh'])
    queries=['Montbell '+q for q in WORDS['en']+WORDS['zh']]
    # Real dispatch registers only the independently approved visual nouns.
    from hotpost.source_queries import register_tiktok_noun_head
    for query in queries:register_tiktok_noun_head(query)
    selected=minimum_search_queries(queries,'tiktok',old,{'en':5,'zh':5},10,
        search_only=True,search_identity=branded())
    assert len(selected)==10
    assert search_quota_needed(old,{'en':5,'zh':5},search_identity=branded())
    assert not search_quota_needed(old,{'en':5,'zh':5},'stand collar jacket',search_identity=branded())
    assert not search_quota_needed(old+history(selected,branded()),{'en':5,'zh':5},search_identity=branded())


def test_explicit_model_identifier_is_kept_in_every_query():
    identity=branded();identity['required_terms'].append({'kind':'model',
        'terms':{'en':['EX123'],'zh':['EX123'],'ko':['EX123']},'source':'caption','quote':'EX123'})
    assert matches_identity('Montbell EX123 puffer jacket',identity)
    assert not matches_identity('Montbell puffer jacket',identity)


def test_old_minimum_receipt_still_verifies_and_is_not_mutated(tmp_path):
    settings,reference,frames=setup(tmp_path)
    evidence=visual.binding(reference,frames,'재킷',{},search_minimums={'en':5,'zh':5})
    evidence.pop('subject_hint');evidence['policy']=visual.LEGACY_MINIMUM_POLICY
    value=proposal();value.pop('subject_identity')
    review=model(value,[])(settings,'review',{'input_sha256':visual.digest(evidence),
        'proposal_sha256':visual.digest(value)})
    rows=visual.validate(value,review,evidence)
    receipt={'policy':evidence['policy'],'evidence':evidence,'proposal':value,'review':review,
        'input_sha256':visual.digest(evidence),'queries':rows,
        'approved_query_pool':visual.query_pool_report(rows,evidence['search_minimums'])}
    before=copy.deepcopy(receipt)
    assert visual.verify(receipt)==rows and receipt==before


def test_tampering_plan_identity_cannot_reach_dispatch(tmp_path):
    settings,reference,frames=setup(tmp_path);value=proposal();value['subject_identity']=branded()
    for row in value['queries']:row['query']='Montbell '+row['query']
    receipt=visual.cached_visual_queries(settings,reference,frames,'몽벨 패딩',{'speech':'몽벨 패딩'},
        model(value,[]),search_minimums={'en':5,'zh':5},subject_hint='몽벨 패딩')
    document=plan(receipt);document['search_identity']=proposal()['subject_identity']
    with pytest.raises(ValueError,match='계약'):
        visual.plan_queries(document)


def test_identity_crosses_isolated_worker_payload(tmp_path,monkeypatch):
    from hotpost import source_browser_worker as worker
    from hotpost.config import Settings
    captured={}
    def run(command,payload,*args):captured.update(payload);return {'searches':[]}
    monkeypatch.setattr(worker,'run_bounded',run)
    worker.isolated_search(Settings(data_dir=tmp_path,source_browser_search=False),[],['Montbell puffer jacket'],
        10,tmp_path/'debug',search_minimums={'en':5,'zh':5},search_identity=branded())
    assert captured['search_identity']==branded()


def test_search_only_worker_does_not_stop_after_old_generic_quota(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from hotpost import browser_search as bs
    from hotpost.config import Settings
    monkeypatch.setattr(bs,'BROWSER_COOLDOWNS',{})
    from hotpost.source_queries import register_tiktok_noun_head
    queries=['Montbell '+q for q in WORDS['en']+WORDS['zh']]
    for q in queries:register_tiktok_noun_head(q)
    worker=bs.BrowserSearcher(Settings(data_dir=tmp_path),tmp_path/'debug')
    worker.search_only=True;worker.search_minimums={'en':5,'zh':5};worker.search_identity=branded()
    worker.previous_searches=history(WORDS['en']+WORDS['zh'])
    page=SimpleNamespace(wait_for_timeout=lambda *a:None,mouse=SimpleNamespace(wheel=lambda *a:None))
    monkeypatch.setattr(worker,'_pace',lambda *a,**k:None)
    monkeypatch.setattr(worker,'_page',lambda *a:page)
    monkeypatch.setattr(worker,'_check_block',lambda *a:False)
    monkeypatch.setattr(worker,'_cooling_down',lambda *a,**k:False)
    def submit(page,provider,q,audit):
        audit['execution']={'query_submitted':True,'query_url_matched':True,'input_value':q};return True
    monkeypatch.setattr(worker,'_submit_search',submit)
    monkeypatch.setattr(worker,'_wait_platform_results',lambda p,provider,q,audit,hits:[{'url':'https://www.tiktok.com/@a/video/123'}])
    worker._platforms(None,queries,100,providers={'tiktok'})
    assert len(worker.searches)==10 and all(r['search_identity']==branded() for r in worker.searches)
    assert all(v['ready'] for v in actual_search_coverage(worker.searches,worker.search_minimums).values())
