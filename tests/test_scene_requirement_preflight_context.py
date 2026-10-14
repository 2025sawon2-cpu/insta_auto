import copy
import json
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.daily_quality import QualitySceneGap
from hotpost.scene_requirements import assess, coverage_current, input_signature, validate_selected_scenes
from test_scene_requirement_intervals import approved, coverage
from test_scene_requirement_anchors import setup


def test_preflight_supplies_actual_connected_narration_and_whole_part_limits(tmp_path):
    state=approved(tmp_path);source=state['sources'][0]
    source['functional_review'].update(observed_actions=['Separate narrow transparent L strip installed'],
        usage_limits='Narrow gap blocker only; not the wide mat own edge')
    calls=[]
    def generate(settings,instruction,evidence,media):
        calls.append((instruction,evidence))
        return {'requirements':[{'index':0,'covered':False,'reason':'Separate strip does not prove mat own edge'}]}
    result=assess(Settings(data_dir=tmp_path),state,generate=generate)
    instruction,evidence=calls[0];context=evidence['narration_context']
    assert context['verified']
    assert context['selected_narration']['text']==state['scripts'][0]['text']
    assert context['requirement_contexts'][0]['narration']=='Observed action.'
    assert context['requirement_contexts'][0]['before'][0]['text']=='Before the action.'
    assert context['requirement_contexts'][0]['after'][0]['text']=='Completed shape.'
    assert context['original_product_evidence']['text']==state['original_text']
    assert context['source_function_limits'][0]['usage_limits']==source['functional_review']['usage_limits']
    assert 'whole versus part' in instruction and 'supporting_frame_ids' in instruction
    assert not result['ready'] and result['context_signature']==context['signature']
    state['daily_quality']['scene_requirements']=result
    assess(Settings(data_dir=tmp_path),state,generate=lambda *a,**k:pytest.fail('Same context rejection must stay cached'))


@pytest.mark.parametrize('missing',['approved_script_id','original_text','selected_plan'])
def test_unverified_context_holds_without_model_call(tmp_path,missing):
    state=approved(tmp_path)
    if missing=='selected_plan':Path(state['edits'][0]['plan_path']).unlink()
    else:state.pop(missing)
    result=assess(Settings(data_dir=tmp_path),state,generate=lambda *a,**k:pytest.fail('No model without actual bound context'))
    assert not result['ready'] and result['holds']
    assert not result['narration_context']['verified']


def test_changed_whole_part_limits_invalidate_old_approval_even_with_same_render_input(tmp_path):
    state=approved(tmp_path)
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,
        generate=lambda *a,**k:coverage(state['sources'][0]))
    assert coverage_current(state)
    prior=input_signature(state)
    state['sources'][0]['functional_review']['usage_limits']='Separate strip, not mat own edge'
    assert input_signature(state)==prior
    assert not coverage_current(state)
    calls=[]
    def reject(*args,**kwargs):
        calls.append(args[2]);return {'requirements':[{'index':0,'covered':False,'reason':'Actual structure differs'}]}
    result=assess(Settings(data_dir=tmp_path),state,generate=reject)
    assert len(calls)==1 and not result['ready']


@pytest.mark.parametrize('change',['script','beat'])
def test_final_cut_cannot_change_narration_after_context_review(tmp_path,change):
    state,plan=setup(tmp_path)
    plan['beats'][0].update(source_start=1.5,source_end=2.1)
    if change=='script':plan['script_text']='Other product narration'
    else:plan['beats'][0]['text']='The wide mat own edge is inserted'
    with pytest.raises(QualitySceneGap):validate_selected_scenes(state,plan)
