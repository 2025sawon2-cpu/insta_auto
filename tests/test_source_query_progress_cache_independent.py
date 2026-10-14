"""A grounded query pool cannot be reopened by run/code/model prose metadata."""
import copy

from hotpost.config import Settings
from hotpost import source_planning as planning


def base_plan():
    return {'products':[{'ko':'은색 거울','en':'silver mirror','zh':'银色镜子'}],
            'brands':[],'features':[],'models':[],
            'query_details':[{'query':'silver mirror','language':'en','intent':'product','confidence':'observed'}]}


def test_same_grounded_query_pool_survives_restart_and_code_callable_changes(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path);calls=[]
    def enrich(*args):
        calls.append(True)
        return {**copy.deepcopy(args[1]),'query_details':[{'query':'silver mirror product','language':'en'}]}
    monkeypatch.setattr(planning,'enrich_plan',enrich)
    original=planning.cached_enrich_plan(settings,base_plan(),'은색 거울',{'speech':'거울을 엽니다','screen_text':'제품'})
    monkeypatch.setattr(planning,'enrich_plan',lambda *args: (_ for _ in ()).throw(AssertionError('No model replay')))
    restarted=planning.cached_enrich_plan(Settings(data_dir=tmp_path),base_plan(),'은색 거울',
                                        {'speech':'거울을 엽니다','screen_text':'제품','job_id':'new','model_revision':'new-code'})
    assert original==restarted and calls==[True]


def test_round_policy_and_planning_prose_cannot_create_a_new_query_pool(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path);calls=[]
    def enrich(*args):
        calls.append(True)
        return copy.deepcopy(args[1])
    monkeypatch.setattr(planning,'enrich_plan',enrich)
    original=planning.cached_enrich_plan(settings,base_plan(),'은색 거울',{'speech':'거울을 엽니다'})
    later=base_plan()
    later.update(search_round=99,policy='new-executable-hash',job_id='new-job',
                 checked_at=999,planning_notes=['New wording for unchanged evidence'])
    cached=planning.cached_enrich_plan(settings,later,'은색 거울',{'speech':'거울을 엽니다'})
    assert len(calls)==1 and cached==original


def test_new_visual_query_wording_without_new_observation_does_not_reopen_pool(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path);calls=[]
    def enrich(*args):
        calls.append(True)
        return copy.deepcopy(args[1])
    monkeypatch.setattr(planning,'enrich_plan',enrich)
    original=planning.cached_enrich_plan(settings,base_plan(),'은색 거울',{'speech':'거울을 엽니다'})
    later=base_plan()
    later['query_details'].append({'query':'silver reflecting mirror product','language':'en',
                                  'intent':'appearance','confidence':'visual_inferred'})
    cached=planning.cached_enrich_plan(settings,later,'은색 거울',{'speech':'거울을 엽니다'})
    assert len(calls)==1 and cached==original


def test_changed_actual_reference_text_creates_a_new_grounded_pool(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path);calls=[]
    def enrich(*args):
        calls.append(args[2])
        return copy.deepcopy(args[1])
    monkeypatch.setattr(planning,'enrich_plan',enrich)
    planning.cached_enrich_plan(settings,base_plan(),'은색 거울',{'speech':'거울을 엽니다'})
    planning.cached_enrich_plan(settings,base_plan(),'은색 거울, 접이식 구조',{'speech':'거울을 엽니다'})
    assert len(calls)==2


def test_actual_reference_sha_changes_pool_and_same_sha_preserves_it(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path);calls=[]
    def enrich(*args):
        calls.append(True)
        return copy.deepcopy(args[1])
    monkeypatch.setattr(planning,'enrich_plan',enrich)
    first=planning.cached_enrich_plan(settings,base_plan(),'거울',{},reference_sha256='actual-reference-one')
    later=base_plan();later.update(search_round=9,policy='new-code')
    assert planning.cached_enrich_plan(settings,later,'거울',{},reference_sha256='actual-reference-one')==first
    assert len(calls)==1
    planning.cached_enrich_plan(settings,base_plan(),'거울',{},reference_sha256='actual-reference-two')
    assert len(calls)==2
