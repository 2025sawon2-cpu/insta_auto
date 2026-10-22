"""New acquisition minima use real execution evidence and preserve old contracts."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost.source_policy import adopt_policy
from source_policy_fixtures import saved_v5 as montage_policy
from hotpost.source_coverage import (actual_search_coverage, coverage_goal, current_search_rows,
                                    search_scope_for_state, parent_aliases)
from hotpost.source_batches import state_with_search_audit
from hotpost.source_queries import platform_queries, language


WORDS={'en':['hand warmer','red hand warmer','black hand warmer','portable hand warmer','electric hand warmer'],
       'zh':['暖手宝','红色暖手宝','黑色暖手宝','便携暖手宝','电动暖手宝']}


def receipts():
    return [{'provider':'tiktok','query':q,'language':lang,'status':'results' if i else 'no_results',
             'execution':{'query_submitted':True,'query_url_matched':True,'input_value':q}}
            for lang,words in WORDS.items() for i,q in enumerate(words)]


def state_with_receipts():
    state={'id':'task','run_id':'new','runs':[], 'product':'손난로','original_text':'빨간 휴대용 전기 손난로',
           'sources':[],'source_policy':montage_policy()}
    return state_with_search_audit(state,{'search_audit':receipts()},verified_current_manifest=True)


def source(tmp_path,index,core=False,parent=None,sha=None):
    path=tmp_path/f'{index}.mp4';path.write_bytes(str(sha).encode() if sha else f'actual received bytes {index}'.encode())
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    item={'id':str(index),'path':str(path),'sha256':sha,'source_quality':'clean-source',
          'video_meta':{'duration':2},'reviewed_intervals':[{'source_start':0,'source_end':2}],
          'functional_review':{'reviewed':True,'same_core_function':core,'context_usable':True,
              'context_usage_limits':['general use context only'],'observed_actions':['actual product use'],
              'evidence_frames':['actual observed frame'],'source_sha256':sha}}
    if parent:item['original_sha256']=parent
    return item


def test_only_submitted_matching_unique_queries_count_and_zero_results_are_valid():
    rows=receipts()
    rows += [{**rows[0],'provider':'youtube','query':' HAND  WARMER ','execution':{
        'query_submitted':True,'query_url_matched':True,'input_value':' HAND  WARMER '}},
        {**rows[5],'query':'暖 手 宝','execution':{'query_submitted':True,'query_url_matched':True,'input_value':'暖 手 宝'}}]
    legacy={'provider':'youtube','query':'extra warmer','status':'results'}
    for variant in [legacy,{**legacy,'execution':{'query_submitted':False,'query_url_matched':True}},
        {**legacy,'execution':{'query_submitted':True,'query_url_matched':False}},
        {**legacy,'execution':{'query_submitted':True,'query_url_matched':True,'input_value':'wrong query'}},
        {**rows[0],'query':'yellow hand warmer','status':'captcha'},
        {**rows[0],'query':'silver hand warmer','status':'query_restricted'}]:rows.append(variant)
    result=actual_search_coverage(rows,{'en':5,'zh':5})
    assert {lang:r['count'] for lang,r in result.items()}=={'en':5,'zh':5}
    assert all(r['ready'] for r in result.values())


def test_current_run_and_product_reference_scope_are_required_without_mutating_old_history():
    state=state_with_receipts();old=copy.deepcopy(state)
    assert len(current_search_rows(state))==10
    for change in ({'run_id':'different-run'},{'product':'재킷'},{'original_text':'다른 원문'}):
        changed={**state,**change}
        assert current_search_rows(changed)==[]
    assert state==old
    assert current_search_rows({**state,'source_acquisition':{'queries':receipts()}})==[]


def test_old_or_unbound_manifest_cannot_be_relabelled_as_current_searches():
    state=state_with_receipts();state['source_acquisition']['queries']=[]
    old=[{**row,'run_id':'old','search_context':{**search_scope_for_state(state),'product':'different'}} for row in receipts()]
    copied=state_with_search_audit(state,{'search_audit':old},verified_current_manifest=True)
    assert not current_search_rows(copied)
    assert all(row['run_id']=='old' for row in copied['source_acquisition']['queries'])
    assert not current_search_rows(state_with_search_audit(state,{'search_audit':receipts()}))
    assert not current_search_rows(state_with_search_audit(state,{'run_id':'old',
        'search_context':search_scope_for_state(state),'search_audit':receipts()},verified_current_manifest=True))


def test_five_reviewed_parents_core_one_and_both_search_minima_are_independent(tmp_path):
    state=state_with_receipts();items=[source(tmp_path,i,core=i==0) for i in range(5)]
    goal=coverage_goal(items,state,state['source_policy'])
    assert goal['ready'] and goal['related_parent_count']==5 and goal['core_parent_count']==1
    assert not coverage_goal(items[:4],state,state['source_policy'])['ready']
    assert not coverage_goal(items,{**state,'source_acquisition':{}},state['source_policy'])['ready']
    context=copy.deepcopy(items)
    context[0]['functional_review']['same_core_function']=False
    assert not coverage_goal(context,state,state['source_policy'])['ready']
    context[0]['functional_review']={}
    assert coverage_goal(context,state,state['source_policy'])['related_parent_count']==4


def test_allocation_gap_runtime_target_requests_another_parent_without_mutating_saved_minimum(tmp_path):
    state=state_with_receipts();before=copy.deepcopy(state['source_policy'])
    items=[source(tmp_path,i,core=i==0) for i in range(5)]
    runtime={**state['source_policy'],'acquisition_parent_target':6}
    temporary=state_with_search_audit(state,{'run_id':state['run_id'],
        'search_context':search_scope_for_state(state),'source_policy':runtime,'search_audit':[]})
    goal=coverage_goal(items,temporary,temporary['source_policy'])
    assert goal['required_parent_sources']==6 and not goal['ready']
    assert state['source_policy']==before and before['source_diversity_policy']['minimum_parent_sources']==5
    assert coverage_goal([*items,source(tmp_path,5)],temporary,runtime)['ready']


def test_interrupted_search_receipt_keeps_verified_scope_without_retagging_old_rows(tmp_path):
    from hotpost.source_pause_receipts import binding,snapshot,merge_receipt,SourceReceiptWaiting
    state=state_with_receipts();job={'id':'job','payload':{'run_id':state['run_id']}}
    root=tmp_path/'post-123';root.mkdir();state['shortcode']='post'
    old={**receipts()[0],'run_id':'old','search_context':{'product':'other'}}
    manifest=root/'manifest.json';manifest.write_text(json.dumps({'shortcode':'post','job_id':root.name,
        'search_audit':[*receipts(),old],'candidates':[]}),encoding='utf-8')
    descriptor={**binding(state,job),'manifest_path':str(manifest),'workers':[]}
    receipt=snapshot(tmp_path,descriptor,state,job);record={};merge_receipt(record,receipt)
    restored={**state,'source_acquisition':record}
    assert len(current_search_rows(restored))==10
    assert any(r.get('run_id')=='old' for r in record['queries'])
    with pytest.raises(SourceReceiptWaiting):snapshot(tmp_path,descriptor,{**state,'product':'other'},job)
    assert 'run_id' not in json.loads(manifest.read_text('utf-8'))['search_audit'][0]


def test_v5_refresh_passes_only_current_scope_and_keeps_run_policy(tmp_path,monkeypatch):
    from hotpost.studio_runtime.generation import GenerationMixin
    state=state_with_receipts();state['shortcode']='post'
    state['source_acquisition']['queries'] += [{**r,'run_id':'old'} for r in receipts()]
    state['source_acquisition']['rounds']=[]
    manifest=tmp_path/'manifest.json';manifest.write_text('{}',encoding='utf-8')
    calls=[]
    def finder(*args,**kwargs):
        calls.append(kwargs)
        return {'zip_path':str(tmp_path/'sources.zip'),'candidates':[],'search_audit':[],
                'source_policy':kwargs['search_context']['source_policy']}
    monkeypatch.setattr('hotpost.source_finder.find_sources',finder)
    monkeypatch.setattr('hotpost.source_audit.reviewed_platform_outcomes',lambda *a:{})
    worker=GenerationMixin();worker.settings=SimpleNamespace()
    worker.store=SimpleNamespace(get=lambda *a:state,change=lambda *a:None,checkpoint=lambda *a:None)
    worker._source_records=lambda *a:[]
    worker._review_source_records=lambda *a:([],None)
    result=worker._refresh_sources(state,{'id':'refresh','payload':{},'checkpoint':{}})
    assert len(calls)==1 and len(calls[0]['previous_searches'])==10
    context=calls[0]['search_context']
    assert context['run_id']=='new' and context['search_context']==search_scope_for_state(state)
    assert context['source_policy']==state['source_policy']==result['source_policy']
    assert len(state['source_acquisition']['queries'])==20


def test_finder_registers_current_scope_in_manifest_before_any_external_work(tmp_path,monkeypatch):
    from hotpost import source_finder as finder
    state=state_with_receipts();scope=search_scope_for_state(state);seen=[]
    def internal(*args,**kwargs):
        seen.append(json.loads((kwargs['root']/'manifest.json').read_text('utf-8')))
        return seen[-1]
    monkeypatch.setattr(finder,'_find_sources',internal)
    result=finder.find_sources(Settings(data_dir=tmp_path),'post',search_context={
        'run_id':'new','search_context':scope,'source_policy':state['source_policy']})
    assert result['run_id']=='new' and result['search_context']==scope
    assert result['source_policy']['search_minimums']=={'en':5,'zh':5} and result['search_audit']==[]


def test_parent_aliases_and_same_actual_sha_do_not_manufacture_five_sources(tmp_path):
    state=state_with_receipts()
    items=[source(tmp_path,i,core=True,parent='same-original') for i in range(5)]
    assert coverage_goal(items,state,state['source_policy'])['related_parent_count']==1
    aliases=[source(tmp_path,10+i,core=True,parent=f'claimed-parent-{i}',sha='same-actual-file') for i in range(5)]
    assert coverage_goal(aliases,state,state['source_policy'])['related_parent_count']==1
    assert len(set(parent_aliases(aliases).values()))==1


@pytest.mark.parametrize('defect',['missing','changed_bytes','unreviewed','denied','different_function'])
def test_v5_never_counts_unreviewed_changed_or_unrelated_received_files(tmp_path,defect):
    state=state_with_receipts();items=[source(tmp_path,i,core=i==0) for i in range(5)];bad=items[-1]
    if defect=='missing':Path(bad['path']).unlink()
    elif defect=='changed_bytes':Path(bad['path']).write_bytes(b'changed source pixels')
    elif defect=='unreviewed':bad['functional_review']['reviewed']=False
    elif defect=='denied':bad['manual_usage_review']={'editing_eligible':False}
    else:bad['functional_review'].update(same_core_function=False,context_usable=False)
    goal=coverage_goal(items,state,state['source_policy'])
    assert goal['related_parent_count']==4 and not goal['ready']


def test_completed_v4_policy_is_not_migrated_when_read_or_adopted():
    historical=montage_policy();historical.update(version=4,minimum_total=1)
    historical.pop('source_diversity_policy');historical.pop('search_minimums')
    state={'run_id':'old','source_policy':copy.deepcopy(historical),
           'runs':[{'id':'old','status':'completed','source_policy':copy.deepcopy(historical)}]}
    before=copy.deepcopy(state)
    assert adopt_policy(state)==historical and state==before
    assert montage_policy()['version']==5


def test_minimum_search_language_priority_precedes_korean_supplements():
    words=[*WORDS['en'],'손난로',*WORDS['zh']]
    assert [language(q) for q in platform_queries(words,'youtube',10,search_minimums={'en':5,'zh':5})]==['en','zh']*5
    assert len(platform_queries(words,'bilibili',10,search_minimums={'en':5,'zh':5}))==5


def test_twelve_cached_candidates_cannot_skip_actual_search_minima(tmp_path,monkeypatch):
    from hotpost.source_finder import Candidate
    from hotpost.source_search.discovery import discover
    cached=[Candidate(f'https://www.youtube.com/watch?v=cache{i:06d}','local-cache') for i in range(12)]
    calls=[]
    def browser(*args,**kwargs):
        calls.append(kwargs)
        return {'candidates':[],'terms':[],'notes':[],'searches':receipts()}
    monkeypatch.setattr('hotpost.browser_search.browser_search',browser)
    monkeypatch.setattr('hotpost.source_search.library.discover',lambda *a:[])
    services=SimpleNamespace(search_local_cache=lambda *a:cached,search_local_hints=lambda *a:[],Candidate=Candidate)
    found,_,_,audit,_=discover(Settings(data_dir=tmp_path),'post',[],[*WORDS['en'],*WORDS['zh']],
        {'search_minimums':{'en':5,'zh':5}},[],tmp_path,[],[],lambda *a:None,services)
    assert len(found)==12 and len(calls)==1 and calls[0]['search_minimums']=={'en':5,'zh':5}
    assert all(r['ready'] for r in actual_search_coverage(audit,{'en':5,'zh':5}).values())


def test_v5_query_plan_is_evidence_grounded_and_cached_separately(tmp_path):
    from hotpost.source_planning import cached_enrich_plan
    caption='손난로 '+ ' / '.join([*WORDS['en'],*WORDS['zh']])
    base={'query_details':[],'products':[{'ko':'손난로','en':'hand warmer','zh':'暖手宝'}]}
    calls=[]
    def generate(settings,instruction,evidence):
        calls.append(instruction)
        rows=[{'query':q,'language':l,'intent':'product','source':'caption','quote':caption}
              for l,words in {**WORDS,'ko':['손난로']}.items() for q in words]
        return {'subject_kind':'product','primary_subject':{'name':'손난로','source':'caption','quote':caption},
                'queries':rows,'tiktok_queries':rows}
    settings=Settings(data_dir=tmp_path)
    legacy=cached_enrich_plan(settings,base,caption,{},generate)
    current=cached_enrich_plan(settings,base,caption,{},generate,acquisition_policy=montage_policy())
    again=cached_enrich_plan(settings,base,caption,{},generate,acquisition_policy=montage_policy())
    assert len(calls)==2 and 'FIVE' in calls[1]
    assert current['minimum_query_plan_ready'] and current==again
    assert 'minimum_query_plan' not in legacy
    assert len(list((tmp_path/'source-query-plans').glob('*.json')))==2


def test_v5_browser_does_not_stop_after_one_candidate_per_language(tmp_path,monkeypatch):
    from hotpost import browser_search as bs
    monkeypatch.setattr(bs,'BROWSER_COOLDOWNS',{})
    page=SimpleNamespace(route=lambda *a:None,wait_for_timeout=lambda *a:None,
                         mouse=SimpleNamespace(wheel=lambda *a:None),close=lambda:None)
    worker=bs.BrowserSearcher(Settings(data_dir=tmp_path,source_queries_per_platform=1),tmp_path/'debug')
    worker.search_minimums={'en':5,'zh':5}
    monkeypatch.setattr(worker,'_pace',lambda *a,**k:None)
    monkeypatch.setattr(worker,'_page',lambda *a:page)
    monkeypatch.setattr(worker,'_check_block',lambda *a:False)
    monkeypatch.setattr(worker,'_cooling_down',lambda *a,**k:False)
    def submit(p,provider,query,audit):
        audit['execution']={'query_submitted':True,'query_url_matched':True,'input_value':query};return True
    monkeypatch.setattr(worker,'_submit_search',submit)
    monkeypatch.setattr(worker,'_wait_platform_results',lambda p,provider,q,audit,hits:[{'url':f'https://www.tiktok.com/@a/video/{q}'}])
    worker._platforms(SimpleNamespace(),[*WORDS['en'],*WORDS['zh']],1,providers={'tiktok'})
    assert len(worker.searches)==10 and len(worker.candidates)==1
    assert all(r['ready'] for r in actual_search_coverage(worker.searches,worker.search_minimums).values())


def test_merge_and_restore_keep_same_query_in_different_runs_and_product_scopes(tmp_path):
    from hotpost.source_search.strategy import merge_history,restore_history
    state=state_with_receipts();current=current_search_rows(state)
    old=[{**r,'run_id':'old'} for r in current]
    other=[{**r,'search_context':{**r['search_context'],'product':'other'}} for r in current]
    merged=merge_history(old,current,other)
    assert len(merged)==30
    record={'queries':merged,'rounds':[],'strategy_version':2}
    restored=restore_history(record)
    assert len(restored)==30 and len(current_search_rows({**state,'source_acquisition':record}))==10
    assert restore_history(record)==restored
    manifest=tmp_path/'bound.json';manifest.write_text(json.dumps({'search_audit':receipts()}),'utf-8')
    binding={'queries':[],'rounds':[{'manifest_path':str(manifest),'run_id':state['run_id'],
                                  'search_context':search_scope_for_state(state)}]}
    assert len(current_search_rows({**state,'source_acquisition':{'queries':restore_history(binding)}}))==10
    unrelated={'queries':[],'rounds':[{'manifest_path':str(manifest)}]}
    assert current_search_rows({**state,'source_acquisition':{'queries':restore_history(unrelated)}})==[]
    manifest.write_text(json.dumps({'run_id':'old','search_context':search_scope_for_state(state),
                                   'search_audit':receipts()}),'utf-8')
    conflicting={'queries':[],'rounds':[{'manifest_path':str(manifest),'run_id':state['run_id'],
                                       'search_context':search_scope_for_state(state)}]}
    assert current_search_rows({**state,'source_acquisition':{'queries':restore_history(conflicting)}})==[]
