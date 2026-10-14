import copy
import json
import sys
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.daily_quality import QualitySceneGap
from hotpost.scene_requirements import assess, anchor_selected_scenes, validate_selected_scenes
from test_scene_requirement_intervals import approved, coverage


def setup(tmp_path):
    state=approved(tmp_path)
    state['scripts'][0]['text']='Observed action.'
    Path(state['edits'][0]['plan_path']).write_text(json.dumps({'script_text':'Observed action.',
        'beats':[{'id':'b1','text':'Observed action.'}]}),encoding='utf-8')
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,
        generate=lambda *a,**k:coverage(state['sources'][0]))
    source=state['sources'][0]
    shot={'id':'shot','source_id':'source','sha256':source['sha256'],'path':source['path'],'start':1,'end':4}
    plan={'duration':.6,'script_text':state['scripts'][0]['text'],'voice':{'sha256':'voice'},
          'sources':copy.deepcopy(state['sources']),'shots':[shot],
          'footage_selection_policy':'diverse-sequential-v2-semantic-first',
          'beats':[{'id':'b1','text':'Observed action.','start':0,'end':.6,'source_start':1,'source_end':1.6,
                    'options':[{'shot_id':'shot','relation':'direct','reason':'Actual approved scene'}],
                    'selected_shot_id':'shot'}]}
    return state,plan


def test_bounded_head_cut_missing_critical_frame_is_held_then_shifted_without_rewrite(tmp_path):
    state,plan=setup(tmp_path);original=copy.deepcopy(plan)
    with pytest.raises(QualitySceneGap):validate_selected_scenes(state,plan)
    anchor_selected_scenes(state,plan);validate_selected_scenes(state,plan)
    beat=plan['beats'][0]
    assert beat['source_start']<=2 and beat['source_end']>=2.04-1e-6
    assert beat['source_end']-beat['source_start']==pytest.approx(.6)
    assert (beat['start'],beat['end'],beat['text'])==(0,.6,'Observed action.')
    assert plan['script_text']==original['script_text'] and plan['voice']==original['voice']
    assert beat['required_scene_anchor']['supporting_frame_ids']==['1']


def test_renderer_reselection_keeps_frozen_actual_support_window(tmp_path):
    state,plan=setup(tmp_path);anchor_selected_scenes(state,plan)
    expected=(plan['beats'][0]['source_start'],plan['beats'][0]['source_end'])
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'auto_capcut'))
    from auto_capcut.core.studio_timeline import select_shots
    from auto_capcut.core.studio_diversity import render_window
    result=select_shots(copy.deepcopy(plan));beat=result['beats'][0]
    shot=next(s for s in result['shots'] if s['id']==beat['selected_shot_id'])
    assert render_window(result,beat,shot)==pytest.approx(expected)
    validate_selected_scenes(state,result)


def test_renderer_reselection_preserves_unaffected_cut_too(tmp_path):
    state,plan=setup(tmp_path)
    plan['shots'].append({**plan['shots'][0],'id':'other','start':2.4,'end':3})
    plan['beats'].append({'id':'b2','text':'Other narration','start':.6,'end':1.2,
        'source_start':2.4,'source_end':3,'selected_shot_id':'other',
        'options':[{'shot_id':'other','relation':'direct','reason':'Other approved scene'}]})
    plan['duration']=1.2
    state['scripts'][0]['text']=plan['script_text']='Observed action. Other narration'
    Path(state['edits'][0]['plan_path']).write_text(json.dumps({'script_text':plan['script_text'],
        'beats':[{'id':b['id'],'text':b['text']} for b in plan['beats']]}),encoding='utf-8')
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,
        generate=lambda *a,**k:coverage(state['sources'][0]))
    anchor_selected_scenes(state,plan)
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'auto_capcut'))
    from auto_capcut.core.studio_timeline import select_shots
    result=select_shots(copy.deepcopy(plan))
    assert (result['beats'][1]['source_start'],result['beats'][1]['source_end'])==pytest.approx((2.4,3))
    assert result['beats'][1]['text']=='Other narration'


@pytest.mark.parametrize('case',['legacy_without_anchors','transition_too_long','unknown_native_exposure'])
def test_uncertain_or_unfittable_support_is_held_without_mutating_plan(tmp_path,case):
    state,plan=setup(tmp_path)
    match=state['daily_quality']['scene_requirements']['requirements'][0]['matches'][0]
    if case=='legacy_without_anchors':
        match.pop('supporting_frame_ids');match.pop('supporting_reason')
    elif case=='transition_too_long':match['supporting_frame_ids']=['0','2']
    else:
        from hotpost.source_frame_timing import timing_from_probe
        state['sources'][0]['mask_review']['native_frame_timing']=timing_from_probe({},state['sources'][0]['sha256'])
        match['supporting_frame_ids']=['2']
    original=copy.deepcopy(plan)
    with pytest.raises(QualitySceneGap):anchor_selected_scenes(state,plan)
    assert plan==original


def test_known_native_last_frame_extends_only_its_actual_exposure(tmp_path):
    state,plan=setup(tmp_path)
    match=state['daily_quality']['scene_requirements']['requirements'][0]['matches'][0]
    match['supporting_frame_ids']=['2']
    anchor_selected_scenes(state,plan);beat=plan['beats'][0]
    assert (beat['source_start'],beat['source_end'])==pytest.approx((2.44,3.04))
    validate_selected_scenes(state,plan)
    assert beat['source_end']>match['source_end'] # Proven same-frame exposure, not unseen continuation.


def test_first_support_frame_at_cut_start_needs_no_invented_padding(tmp_path):
    state,plan=setup(tmp_path)
    match=state['daily_quality']['scene_requirements']['requirements'][0]['matches'][0]
    match['supporting_frame_ids']=['0']
    anchor_selected_scenes(state,plan)
    assert plan['beats'][0]['source_start']==1
    validate_selected_scenes(state,plan)


@pytest.mark.parametrize('final_state',[False,True])
def test_actual_native_boundary_support_fits_without_output_fps_padding(tmp_path,final_state):
    from hotpost.source_frame_timing import timing_from_probe
    from hotpost.scene_requirements import constrain_plan
    state,plan=setup(tmp_path);source=state['sources'][0]
    timestamps=(.833333,1.633333,3.266667 if final_state else 2.466667)
    for frame,timestamp in zip(source['mask_review']['evidence_frames'],timestamps):frame['source_timestamp']=timestamp
    source['reviewed_intervals']=[{'source_start':0,'source_end':3.3}]
    source['mask_review']['native_frame_timing']=timing_from_probe({'streams':[{'duration':3.3}],
        'frames':[{'best_effort_timestamp_time':t,'pkt_duration_time':1/30}
                  for t in (*timestamps,3.3)]},source['sha256'])
    # Intermediate decoded PTS are supplied by the native metadata as well.
    native_pts=sorted({*timestamps,*(t+1/30 for t in timestamps if t+1/30<3.3)})
    source['mask_review']['native_frame_timing']=timing_from_probe({'streams':[{'duration':3.3}],
        'frames':[{'best_effort_timestamp_time':t,'pkt_duration_time':1/30} for t in native_pts]},source['sha256'])
    value=coverage(source,timestamps[0],timestamps[-1])
    value['requirements'][0]['matches'][0]['supporting_frame_ids']=['2'] if final_state else ['1','2']
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,
        generate=lambda *a,**k:value)
    assert state['daily_quality']['scene_requirements']['ready']
    length=.793333 if final_state else .88
    plan['duration']=length;plan['shots'][0].update(start=0,end=3.3)
    plan['beats'][0].update(start=0,end=length,source_start=timestamps[0],source_end=timestamps[0]+length)
    constrain_plan(state,plan)
    plan['beats'][0]['selected_shot_id']=plan['beats'][0]['options'][0]['shot_id']
    anchor_selected_scenes(state,plan);beat=plan['beats'][0]
    assert beat['source_end']-beat['source_start']==pytest.approx(length)
    assert beat['source_start']<=timestamps[-1] and beat['source_end']>=min(3.3,timestamps[-1]+1/30)-1e-6
    validate_selected_scenes(state,plan)


def test_anchor_cannot_introduce_overlap_with_same_parent_other_file(tmp_path):
    state,plan=setup(tmp_path);source=state['sources'][0]
    raw=copy.deepcopy(source);raw['id']='raw'
    source.update(original_sha256=source['sha256'],original_interval={'start':1,'end':5},
                  video_meta={'duration':4})
    state['sources'].append(raw)
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,
        generate=lambda *a,**k:coverage(source))
    plan['sources']=copy.deepcopy(state['sources'])
    plan['shots'].append({'id':'raw-shot','source_id':'raw','sha256':raw['sha256'],
        'path':raw['path'],'start':2.8,'end':3.2})
    plan['beats'].append({'id':'b2','start':.6,'end':1.,'source_start':2.8,'source_end':3.2,
        'selected_shot_id':'raw-shot','options':[{'shot_id':'raw-shot'}]})
    original=copy.deepcopy(plan)
    with pytest.raises(QualitySceneGap):anchor_selected_scenes(state,plan)
    assert plan==original


def test_workflow_holds_missing_support_before_cover_or_render(tmp_path,monkeypatch):
    from hotpost.studio_workflow import WorkflowMixin
    from hotpost.daily_quality import POLICY
    state,plan=setup(tmp_path);state['id']='work'
    state['daily_quality']['policy']=POLICY
    match=state['daily_quality']['scene_requirements']['requirements'][0]['matches'][0]
    match.pop('supporting_frame_ids');match.pop('supporting_reason')
    calls=[]
    class Editor(WorkflowMixin):
        settings=None
        def _process(self,state,job,action,payload):
            calls.append(action)
            if action=='select-shots':
                selected=payload['plan'];selected['beats'][0]['selected_shot_id']=selected['beats'][0]['options'][0]['shot_id']
                return {'plan':selected}
            pytest.fail('No cover or render before actual supporting frame proof')
    with pytest.raises(QualitySceneGap):Editor()._render_reviewed_cover(state,{'id':'job'},plan)
    assert calls==['select-shots']


def test_workflow_checks_actual_support_again_after_cover_before_render(tmp_path,monkeypatch):
    from hotpost.studio_workflow import WorkflowMixin
    from hotpost.daily_quality import POLICY
    from hotpost import cover_selection
    state,plan=setup(tmp_path);state['id']='work';state['daily_quality']['policy']=POLICY
    calls=[]
    class Editor(WorkflowMixin):
        settings=None
        def folder(self,*args):return tmp_path
        def _process(self,state,job,action,payload):
            calls.append(action)
            if action=='select-shots':
                selected=payload['plan'];selected['beats'][0]['selected_shot_id']=selected['beats'][0]['options'][0]['shot_id']
                return {'plan':selected}
            if action=='cover-candidates':return {'candidates':[]}
            pytest.fail('Cover-side corruption must be held before render')
    def corrupt(settings,selected,*args,**kwargs):
        selected['beats'][0].update(source_start=1,source_end=1.6)
        return selected
    monkeypatch.setattr(cover_selection,'select_cover',corrupt)
    with pytest.raises(QualitySceneGap):Editor()._render_reviewed_cover(state,{'id':'job'},plan)
    assert calls==['select-shots','cover-candidates']
