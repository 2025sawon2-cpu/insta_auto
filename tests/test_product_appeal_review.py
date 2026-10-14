import copy

import pytest

from hotpost.config import Settings
from hotpost.daily_quality import validate_report,repetition_metrics,visual_metric_advisories
from hotpost.product_appeal_review import PRODUCT_APPEAL_INSTRUCTION
from hotpost.scene_requirements import assess, coverage_current
from test_daily_quality import ready, finish, issue
from test_scene_requirement_intervals import approved, coverage


def test_optional_literal_story_improvement_does_not_collect_or_consume_repairs(ready):
    studio,task=ready
    opinion={'kind':'scene_gap','beat_id':'b1','reason':'정확한 일상 이야기 장면을 넣으면 더 직접적일 수 있음','search_query':''}
    value=validate_report({'passed':True,'issues':[],'advisories':[opinion]}, {'b1'})
    finish(studio,task,{'edit_id':'old-edit','review_path':'review.json',**value})
    state=studio.store.get(task)
    assert state['status']=='completed' and state['edits'][0]['quality_verified']
    assert state['daily_quality']['repair_round']==0 and not state['daily_quality']['feedback']
    assert state['daily_quality']['reviews'][-1]['advisories']==[opinion]
    assert not any(j['kind'] in ('refresh_sources','quality_reedit','rewrite') for j in studio.store.jobs(task))


def test_actual_opposite_demonstration_still_requests_new_evidence(ready):
    studio,task=ready
    value=issue('old-edit');value['advisories']=[{'kind':'scene_gap','beat_id':'b1','reason':'정확한 주변 상황은 선택 개선'}]
    finish(studio,task,value)
    state=studio.store.get(task)
    assert not state['edits'][0].get('quality_verified')
    assert state['daily_quality']['feedback'][0]['reason']=='실제 접는 동작이 아닌 펼치는 장면'
    assert any(j['kind']=='refresh_sources' for j in studio.store.jobs(task))
    assert state['daily_quality']['repair_round']==0


def repeated_product_plan():
    return {'duration':4,'sources':[
        {'id':'a','sha256':'one','original_sha256':'parent','original_interval':{'start':10}},
        {'id':'b','sha256':'two','original_sha256':'parent','original_interval':{'start':11}}],
        'shots':[{'id':'s1','source_id':'a'},{'id':'s2','source_id':'b'}],
        'beats':[{'id':'b1','selected_shot_id':'s1','source_start':0,'source_end':2,'start':0,'end':2},
                 {'id':'b2','selected_shot_id':'s2','source_start':0,'source_end':2,'start':2,'end':4}],
        'footage_diversity':{'frozen_beats':['b2']}}


def test_real_parent_replay_and_static_detail_diagnostics_do_not_override_clean_visual_review():
    plan=repeated_product_plan();metrics=repetition_metrics(plan)
    assert metrics['same_source_time_replay_seconds']==1
    opinion=visual_metric_advisories(plan,metrics)
    value=validate_report({'passed':True,'issues':[],'advisories':opinion},{'b1','b2'})
    assert value['passed'] and not value['issues'] and len(value['advisories'])==2


def test_actual_visual_redundancy_is_still_blocking_with_same_metric_advisories():
    plan=repeated_product_plan();opinion=visual_metric_advisories(plan,repetition_metrics(plan))
    defect={'kind':'repetition','beat_id':'b2','reason':'같은 확대 구도가 새 기능·디테일 없이 세 번 연속 반복됨'}
    value=validate_report({'passed':False,'issues':[defect],'advisories':opinion},{'b1','b2'})
    assert not value['passed'] and value['issues'][0]['reason']==defect['reason']


@pytest.mark.parametrize('advisories',[
    'not a list', [{'reason':'','beat_id':'b1'}], [{'reason':'literal matching preference','beat_id':'unknown'}]])
def test_unbound_optional_findings_cannot_be_silently_recorded(advisories):
    with pytest.raises(ValueError):validate_report({'passed':True,'issues':[],'advisories':advisories},{'b1'})


def test_an_actual_failed_review_is_not_promoted_by_an_advisory():
    with pytest.raises(ValueError):
        validate_report({'passed':False,'issues':[],'advisories':[{'reason':'optional matching'}]}, {'b1'})


def test_old_literal_scene_policy_is_reassessed_with_real_product_context(tmp_path):
    state=approved(tmp_path);settings=Settings(data_dir=tmp_path);calls=[]
    state['daily_quality']['feedback'][0]['reason']='일상 이야기의 구체적인 사건이 화면에 없음'
    def model(settings,instruction,evidence,**kwargs):
        calls.append(evidence)
        assert PRODUCT_APPEAL_INSTRUCTION in instruction
        assert evidence['narration_context']['verified']
        row=coverage(state['sources'][0])
        row['requirements'][0]['matches'][0]['supporting_reason']='실제 제품과 사용 상태가 전체 이야기의 매력을 보여주는 지원 장면'
        return row
    prior=assess(settings,state,generate=model)
    state['daily_quality']['scene_requirements']=copy.deepcopy(prior)
    state['daily_quality']['scene_requirements']['policy']='scene-coverage-v4-narration-product-support'
    assert not coverage_current(state)
    updated=assess(settings,state,generate=model)
    assert len(calls)==2 and updated['ready']
    state['daily_quality']['scene_requirements']=updated
    assert coverage_current(state)
