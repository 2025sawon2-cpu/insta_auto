import copy

import pytest

from hotpost.studio_runtime.lifecycle import LifecycleMixin


def fixture(kind='quality_reedit',prior=None,round_number=0):
    state={'edits':copy.deepcopy(prior or []),'daily_quality':{
        'repair_round':round_number,'max_repairs':3,'scene_no_progress':2,
        'collection_attempt':4,'pending':'reedit'},
        'approved_voice_id':'voice','automation':{'active':False,'paused_by_user':True},'runs':[]}
    job={'id':'render-job','kind':kind,'payload':{'voice_id':'voice','edit_id':None,
        'repair_input_signature':'actual-input'}}
    if kind=='edit':job['payload'].update(quality_repair=True,parent_edit_id='old')
    result={'id':'actual-render','voice_id':'voice','script_id':'script','preview_path':'durable-preview.mp4',
        'quality_repair_round':round_number+1} # The producer's provisional estimate precedes actual accounting.
    return state,job,result


@pytest.mark.parametrize('kind',['quality_reedit','edit'])
@pytest.mark.parametrize('round_number',[0,2])
def test_first_actual_render_after_pre_render_failures_is_baseline_not_repair(kind,round_number):
    state,job,result=fixture(kind,round_number=round_number)
    if kind=='edit':state['daily_quality']['repair_context']={'parent_edit_id':'old','reason':'quality_feedback_rewrite'}
    mixin=LifecycleMixin();mixin._accept(state,job,result)
    assert state['daily_quality']['repair_round']==round_number
    audit=result['repair_accounting']
    assert audit['classification']=='initial_baseline' and audit['repair_charge']==0
    assert audit['prior_edit_ids']==[] and audit['job_id']==job['id'] and audit['edit_id']==result['id']
    assert audit['repair_round_before']==audit['repair_round_after']==round_number
    assert state['edits'][0]['quality_repair_round']==result['quality_repair_round']==round_number
    assert state['daily_quality']['render_accounting']==[audit]
    assert state['daily_quality']['max_repairs']==3 and state['daily_quality']['scene_no_progress']==2
    assert state['daily_quality']['collection_attempt']==4 and state['automation']['paused_by_user']
    snapshot=copy.deepcopy(state)
    mixin._accept(state,job,result)
    assert state==snapshot # Replay cannot charge or append another accounting receipt.
    restarted=copy.deepcopy(state);LifecycleMixin()._accept(restarted,copy.deepcopy(job),copy.deepcopy(result))
    assert restarted==snapshot


@pytest.mark.parametrize('kind',['quality_reedit','edit'])
def test_new_actual_render_after_prior_draft_consumes_one_cumulative_repair(kind):
    prior={'id':'old','preview_path':'previously-rendered.mp4'}
    state,job,result=fixture(kind,prior=[prior],round_number=2)
    LifecycleMixin()._accept(state,job,result)
    assert state['daily_quality']['repair_round']==3 and len(state['edits'])==2
    audit=result['repair_accounting']
    assert audit['classification']=='quality_repair' and audit['repair_charge']==1
    assert audit['prior_edit_ids']==['old'] and audit['repair_round_before']==2 and audit['repair_round_after']==3
    assert state['edits'][-1]['quality_repair_round']==result['quality_repair_round']==3
    assert state['daily_quality']['rendered_input_signatures']==['actual-input']
    after=copy.deepcopy(state);LifecycleMixin()._accept(state,job,result)
    assert state==after


def test_no_render_result_never_charges_or_creates_baseline_receipt():
    state,job,_=fixture(round_number=2);before=copy.deepcopy(state)
    LifecycleMixin()._accept(state,job,{'no_render':True})
    assert state['daily_quality']['repair_round']==2 and state['edits']==[]
    assert 'render_accounting' not in state['daily_quality']
    assert state['daily_quality']['scene_no_progress']==before['daily_quality']['scene_no_progress']


def test_no_render_history_entry_does_not_turn_first_real_render_into_repair():
    state,job,result=fixture(prior=[{'id':'never-rendered','no_render':True}],round_number=0)
    LifecycleMixin()._accept(state,job,result)
    assert state['daily_quality']['repair_round']==0
    assert result['repair_accounting']['prior_edit_ids']==[]


@pytest.mark.parametrize('prior',[False,True])
def test_quality_reedit_execution_estimate_is_corrected_by_final_acceptance_and_replay(prior):
    from hotpost.daily_quality import DailyQualityMixin
    class Producer(DailyQualityMixin,LifecycleMixin):
        def _edit(self,state,job):
            return {'id':'actual-render','voice_id':'voice','script_id':'script','preview_path':'completed.mp4'}
    state,job,_=fixture(prior=[{'id':'old','preview_path':'old-completed.mp4'}] if prior else [],round_number=2)
    producer=Producer();result=producer._quality_reedit(state,job)
    assert result['quality_repair_round']==3 # Execution has not committed the final classification yet.
    producer._accept(state,job,result)
    expected=3 if prior else 2
    assert result['quality_repair_round']==result['repair_accounting']['repair_round_after']==expected
    assert state['edits'][-1]['quality_repair_round']==state['daily_quality']['repair_round']==expected
    saved=copy.deepcopy(state);producer._accept(state,job,copy.deepcopy(result))
    assert state==saved and len(state['daily_quality']['render_accounting'])==1
