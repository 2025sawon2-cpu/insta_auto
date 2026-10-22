"""Core-first acquisition must not regress into quotas, auth fallback or wrong identity."""
import copy
import pytest

from hotpost.source_core_priority import (VERSION,REVIEW_POLICY,review_context,kind,context,
    finite_search_plan,exhausted_fallback,bind_plan)
from hotpost.source_policy import montage_policy,adopt_policy
from hotpost.source_coverage import coverage_goal,query_receipts_only
from hotpost.source_functional import apply_function_review,needs_identity_reanalysis,needs_function_review
from test_source_diversity_acquisition_v5 import source,receipts
from hotpost.source_batches import state_with_search_audit


def state():
    s={'id':'task','run_id':'new','runs':[],'product':'손난로','original_text':'휴대용 손난로',
       'sources':[],'source_policy':montage_policy(),'automation':{'active':True}}
    return state_with_search_audit(s,{'search_audit':receipts()},verified_current_manifest=True)


def asset(tmp_path,index,s,core=True):
    item=source(tmp_path,index,core=core)
    item['functional_review'].update(policy=REVIEW_POLICY,featured_product_identity=core,
        identity_evidence=['observed reference product shape'],core_product_context=review_context(s))
    apply_function_review(item,item['functional_review'])
    return item


def test_core_one_context_four_cannot_finish_or_take_receipts_only_shortcut(tmp_path):
    s=state();items=[asset(tmp_path,i,s,core=i==0) for i in range(5)]
    goal=coverage_goal(items,s,s['source_policy'])
    assert goal['source_diversity_ready'] and goal['search_ready']
    assert goal['core_parent_count']==1 and not goal['ready'] and goal['core_shortfall']==4
    assert not query_receipts_only(s,{'kind':'collect_sources'},goal)
    assert coverage_goal([asset(tmp_path,i+10,s) for i in range(5)],s,s['source_policy'])['ready']


def test_same_function_wrong_central_product_is_support_not_core(tmp_path):
    s=state();item=asset(tmp_path,0,s)
    item['functional_review']['featured_product_identity']=False
    apply_function_review(item,item['functional_review'])
    assert kind(item,s)=='related_product' and item['source_role']=='context_only'
    assert coverage_goal([item],s,s['source_policy'])['core_parent_count']==0
    item['functional_review'].update(context_usable=False,context_usage_limits=[])
    apply_function_review(item,item['functional_review'])
    assert not item['editing_eligible']


def test_featured_food_identity_counts_without_fabricating_recipe_demonstration(tmp_path):
    s=state();items=[asset(tmp_path,i,s) for i in range(5)]
    for item in items:
        review=item['functional_review']
        review.update(same_core_function=False,context_usable=True,
            context_usage_limits=['Shows the featured soup; does not demonstrate its soaking additive.'])
        apply_function_review(item,review)
        assert item['editing_eligible'] and kind(item,s)=='core_product'
        assert item['source_role']=='context_only'
        assert item['functional_review']['same_core_function'] is False
        assert 'does not demonstrate' in item['functional_review']['context_usage_limits'][0]
    goal=coverage_goal(items,s,s['source_policy'])
    assert goal['core_parent_count']==5 and goal['ready']
    plan={'shots':[{'source_id':x['id']} for x in items]}
    bind_plan(s,plan,items)
    assert all(x=='core_product' for x in plan['core_source_policy']['source_kinds'].values())
    for item in items:
        item['functional_review'].update(context_usable=False,context_usage_limits=[])
        apply_function_review(item,item['functional_review'])
        assert not item['editing_eligible'] and kind(item,s)=='unverified'


def test_old_and_changed_reference_review_needs_real_reanalysis_but_identical_new_run_reuses(tmp_path):
    s=state();item=asset(tmp_path,0,s)
    assert not needs_identity_reanalysis(s,item)
    assert not needs_identity_reanalysis({**s,'run_id':'another-run'},item)
    assert needs_identity_reanalysis({**s,'original_text':'different product'},item)
    item['functional_review']['policy']='visual-product-presentation-v5-related-context'
    assert needs_identity_reanalysis(s,item)


def test_rejected_v6_receipt_is_not_endlessly_rereviewed(tmp_path):
    s=state();item=asset(tmp_path,0,s,False)
    item['functional_review']['context_usable']=False
    assert not needs_function_review(item)


def finite(s):
    return {'context':context(s),'sha256':'frozen-plan','routes':['tiktok'],
        'identity':None,'queries':[], 'excluded_routes':[{'provider':'youtube','status':'login_required'}]}


@pytest.mark.parametrize('status',['ready','captcha','captcha_review_pending','login_required','cooldown',
    'readiness_blocked','not_attempted','unavailable'])
def test_wait_or_unused_scope_never_authorizes_support_fallback(tmp_path,status):
    s=state();s['sources']=[asset(tmp_path,0,s)]
    assert exhausted_fallback(s,finite(s),[{'provider':'tiktok','status':status}]) is None


def test_only_current_real_search_exhaustion_can_finish_with_support(tmp_path):
    s=state();s['sources']=[asset(tmp_path,i,s,i==0) for i in range(5)]
    p=finite(s);obs=[{'provider':'tiktok','status':'query_exhausted'}]
    receipt=exhausted_fallback(s,p,obs)
    assert receipt and receipt['scope']=='frozen_accessible_routes_only'
    s['source_acquisition'].update(core_search_plan=p,core_fallback=receipt)
    assert coverage_goal(s['sources'],s,s['source_policy'])['ready']
    changed={**s,'run_id':'other'}
    assert not coverage_goal(s['sources'],changed,s['source_policy'])['ready']
    altered=copy.deepcopy(s);altered['source_acquisition']['core_search_plan']['sha256']='new pool'
    assert not coverage_goal(altered['sources'],altered,s['source_policy'])['ready']
    no_search={**s,'source_acquisition':{}}
    assert exhausted_fallback(no_search,p,obs) is None


def test_actual_parent_not_file_count_and_render_boundary_roles(tmp_path):
    s=state();s['sources']=[asset(tmp_path,i,s) for i in range(5)]
    duplicate=copy.deepcopy(s['sources'][0]);duplicate['id']='copy'
    assert coverage_goal([*s['sources'],duplicate],s,s['source_policy'])['core_parent_count']==5
    p={'shots':[{'source_id':v['id']} for v in s['sources']]}
    bind_plan(s,p,s['sources'])
    assert all(v['product_source_kind']=='core_product' for v in p['shots'])
    assert len(p['core_source_policy']['source_sha256s'])==5


def test_similar_product_stills_do_not_erase_distinct_recordings_but_reencoded_sequence_does(tmp_path):
    from hotpost.studio_sources import unique_sources
    from hotpost.source_core_priority import recording_duplicate
    s=state();a=asset(tmp_path,0,s);b=asset(tmp_path,1,s)
    a['frame_hashes']=['0','1','f'*64,'e'*64,'d'*64,'c'*64]
    b['frame_hashes']=['0','1','a'*64,'b'*64,'9'*64,'8'*64]
    assert not recording_duplicate(a,b)
    assert len(unique_sources([a,b],core_priority=True))==2
    b['frame_hashes']=a['frame_hashes'][:]
    assert recording_duplicate(a,b)
    assert len(unique_sources([a,b],core_priority=True))==1
    b['video_meta']['duration']=10
    assert not recording_duplicate(a,b)


def test_saved_v5_is_unchanged_and_explicit_new_run_uses_v6():
    from source_policy_fixtures import saved_v5
    s={'source_policy':saved_v5()};before=copy.deepcopy(s)
    assert adopt_policy(s)['version']==5 and s==before
    assert adopt_policy(s,new_run=True)['version']==6


def test_renderer_json_and_hotpost_final_usage_agree_on_actual_product_exposure(tmp_path):
    import subprocess,sys,json
    from pathlib import Path
    from hotpost.source_diversity import require_body_minimum
    renderer=Path(__file__).resolve().parents[2]/'auto_capcut'
    interpreter=renderer/'.venv/Scripts/python.exe'
    if not interpreter.is_file():pytest.skip('separate renderer runtime not installed')
    script='''import sys,json,copy
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tests'))
from test_core_product_priority import core_plan
from auto_capcut.core.studio_story_selection import select
folder=Path(sys.argv[1]);p=core_plan(folder,core=5,context=0,beats=6)
shot=copy.deepcopy(p['shots'][0]);shot['id']='reaction'
shot['shot_presentation'].update(product_visible=False,product_role='general_context',visual_cluster='reaction')
p['shots'].append(shot)
p['beats'][0]['options']=[dict(shot_id='reaction',relation='context',reason='actual reaction',reviewed=True)]
result=select(p,beam_width=1)
(folder/'exchange.json').write_text(json.dumps(result),encoding='utf8')
'''
    subprocess.run([str(interpreter),'-X','utf8','-c',script,str(tmp_path)],cwd=renderer,check=True,capture_output=True)
    plan=json.loads((tmp_path/'exchange.json').read_text('utf8'))
    report=require_body_minimum(plan,expected_policy=plan['source_diversity_policy'])
    assert report['core_product_used']==5 and report['used_parent_sources']==5
    assert report['core_product_share']==pytest.approx(plan['core_placement_diagnostics']['core_product_share'])
    assert .8<report['core_product_share']<.9


def test_finite_extension_preserves_core_queries_and_other_available_routes(tmp_path):
    from test_source_visual_query_minima_v5 import setup,proposal,model,plan
    from hotpost.source_visual_queries import cached_visual_queries
    settings,reference,frames=setup(tmp_path)
    receipt=cached_visual_queries(settings,reference,frames,'재킷',{},model(proposal(),[]),search_minimums={'en':5,'zh':5})
    document=plan(receipt);s=state()
    history=[{'provider':'tiktok','query':'stand collar jacket','status':'no_results',
        'execution':{'query_submitted':True,'query_url_matched':True,'input_value':'stand collar jacket'}}]
    finite=finite_search_plan(s,document,frames,[{'provider':'tiktok','status':'query_exhausted'},
        {'provider':'youtube','status':'ready'},{'provider':'douyin','status':'login_required'}],history)
    assert finite['routes']==['tiktok','youtube'] and len(finite['queries'])==10
    assert finite['excluded_routes'][0]['provider']=='douyin'


def test_support_search_is_separate_and_never_pads_core_search_minima(tmp_path):
    from test_source_query_identity import branded
    from hotpost.source_core_priority import support_plan
    from hotpost.source_queries import tiktok_product_queries
    from hotpost.source_coverage import actual_search_coverage
    from hotpost.source_search.strategy import merge_history
    document=support_plan({'search_identity':branded(),'visual_query_evidence':{'old':'preserve'},'query_details':[]})
    assert document['search_identity'] is None and not document['search_minimums']
    assert 'puffer jacket' in tiktok_product_queries(document)
    assert not any('Montbell' in r['query'] for r in document['query_details'])
    rows=[{**r,'search_purpose':'support'} for r in receipts()]
    history=merge_history(rows)
    assert all(r['search_purpose']=='support' for r in history)
    assert all(r['count']==0 for r in actual_search_coverage(history,{'en':5,'zh':5}).values())


def test_unreviewed_received_original_prevents_scarcity_claim(tmp_path):
    s=state();s['sources']=[asset(tmp_path,0,s),source(tmp_path,1)]
    assert exhausted_fallback(s,finite(s),[{'provider':'tiktok','status':'query_exhausted'}]) is None


@pytest.mark.parametrize('status,allowed',[('content_rejected',True),('no_usable_intervals',True),
    ('response_error',False),('service_wait',False),('unconfirmed',False)])
def test_actual_rejection_is_settled_but_review_errors_are_not_scarcity(tmp_path,status,allowed):
    s=state();bad=source(tmp_path,1);bad.update(editing_eligible=False,review_outcome={
        'policy':'source-review-outcome-v1','source_sha256':bad['sha256'],'status':status})
    s['sources']=[asset(tmp_path,0,s),bad]
    receipt=exhausted_fallback(s,finite(s),[{'provider':'tiktok','status':'query_exhausted'}])
    assert bool(receipt)==allowed


def test_actual_function_review_requires_identity_evidence_without_inventing_brand(tmp_path,monkeypatch):
    from PIL import Image
    from types import SimpleNamespace
    from hotpost.source_functional import review_function
    from hotpost.model_service import ModelResponseInvalid
    image=tmp_path/'frame.jpg';Image.new('RGB',(24,24),'red').save(image)
    s=state();calls=[]
    value={'same_core_function':True,'featured_product_identity':False,'identity_evidence':['Different central brand visible'],
           'context_usable':True,'context_usage_limits':['Generic warmth only; not featured brand'],
           'observed_actions':['wearing a jacket']}
    def generate(settings,instruction,data,media):
        calls.append(instruction);return value
    monkeypatch.setattr('hotpost.script_rewriter._generate',generate)
    result=review_function(None,SimpleNamespace(file_sha256='actual-sha'),[image],[image],
        {'core_product_context':review_context(s),'product':'몽벨 패딩'})
    assert result['policy']==REVIEW_POLICY and not result['featured_product_identity']
    assert 'never infer a brand from style' in calls[0]
    value.pop('identity_evidence')
    with pytest.raises(ModelResponseInvalid):
        review_function(None,SimpleNamespace(file_sha256='actual-sha'),[image],[image],
            {'core_product_context':review_context(s)})


@pytest.mark.parametrize('status',['query_exhausted','captcha','captcha_review_pending'])
def test_claimed_runtime_gate_saves_scarcity_only_after_real_exhaustion(tmp_path,monkeypatch,status):
    from hotpost.studio import Studio
    from hotpost.config import Settings
    from hotpost.source_access_preflight import SourceAccessWaiting
    from hotpost.source_coverage import search_scope_for_state
    from test_source_visual_query_minima_v5 import setup,proposal,model,plan,WORDS
    from hotpost.source_visual_queries import cached_visual_queries
    settings,reference,frames=setup(tmp_path)
    document=plan(cached_visual_queries(settings,reference,frames,'재킷',{},model(proposal(),[]),search_minimums={'en':5,'zh':5}))
    studio=Studio(Settings(data_dir=tmp_path/'runtime'),workers=False)
    saved,_=studio.store.create('core-gate','재킷',{'protocol':2,'active':True},prepare=False)
    def seed(s,db):
        s.update(original_text='재킷',product='재킷',reference_video=str(reference),product_override=True)
        s['sources']=[asset(tmp_path,i+20,s,i==0) for i in range(5)]
        rows=[{'provider':'tiktok','query':q,'language':lang,'status':'no_results','run_id':s['run_id'],
            'search_context':search_scope_for_state(s),'search_identity':document['search_identity'],
            'execution':{'query_submitted':True,'query_url_matched':True,'input_value':q}}
            for lang,words in WORDS.items() for q in words]
        s['source_acquisition']={'queries':rows,'rounds':[]}
        studio.ensure_source_collection(s,db)
    studio.store.change(saved['id'],seed)
    job=studio.store.claim('sources',task_id=saved['id']);assert job
    monkeypatch.setattr('hotpost.source_preparation.preflight_preparation',lambda *args:(document,frames))
    def check(settings,state,job,**kwargs):
        obs=[{'provider':'tiktok','status':status}]
        job.setdefault('checkpoint',{})['source_access_preflight']={'observations':obs,'ready_routes':[]}
        raise SourceAccessWaiting('observed',observations=obs)
    monkeypatch.setattr('hotpost.source_access_preflight.check_access',check)
    current=studio.store.get(saved['id'])
    if status=='query_exhausted':
        assert studio._source_access_gate(current,job)==[]
        current=studio.store.get(saved['id'])
        assert current['source_acquisition']['core_fallback']['core_shortfall']==4
        from hotpost.studio_sources import source_goal
        assert source_goal(current)['ready']
    else:
        with pytest.raises(SourceAccessWaiting):studio._source_access_gate(current,job)
        assert not studio.store.get(saved['id'])['source_acquisition'].get('core_fallback')
    studio.close()
