import copy
import hashlib
import json
import time

import pytest
from PIL import Image

from hotpost.config import Settings
from hotpost.daily_quality import QualitySceneGap
from hotpost.scene_requirements import assess, input_signature, constrain_plan, validate_selected_scenes


def approved(tmp_path):
    video=tmp_path/'source.mp4';video.write_bytes(b'actual source bytes')
    frames=[]
    for index in range(3):
        path=tmp_path/f'frame-{index}.jpg';Image.new('RGB',(32,32),(index*50,10,10)).save(path)
        frames.append({'frame_id':str(index),'source_timestamp':index+1,'path':str(path),
                       'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    sha=hashlib.sha256(video.read_bytes()).hexdigest()
    source={'id':'source','path':str(video),'sha256':sha,'source_quality':'clean-source','editing_eligible':True,
            'reviewed_intervals':[{'source_start':0,'source_end':4}],
            'functional_review':{'reviewed':True,'source_sha256':sha,'same_core_function':True},
            'mask_review':{'source_sha256':sha,'reviewer':'independent','proposal_sha256':'proposal',
                           'evidence_frames':frames}}
    from hotpost.source_frame_timing import timing_from_probe
    source['mask_review']['native_frame_timing']=timing_from_probe({'streams':[{'duration':4,'start_time':0}],
        'frames':[{'best_effort_timestamp_time':t,'pkt_duration_time':.04} for t in (1,1.04,2,2.04,3,3.04)]},sha)
    narration='Before the action. Observed action. Completed shape. After the action.'
    plan_path=tmp_path/'selected-plan.json'
    plan_path.write_text(json.dumps({'script_text':narration,'beats':[
        {'id':'before','text':'Before the action.'},{'id':'b1','text':'Observed action.'},
        {'id':'second','text':'Completed shape.'},{'id':'after','text':'After the action.'}]}),encoding='utf-8')
    return {'sources':[source],'original_text':'Original product shows the required real action and completed shape.',
            'script_id':'script','approved_script_id':'script','scripts':[{'id':'script','text':narration}],
            'edit_id':'edit','edits':[{'id':'edit','script_id':'script','plan_path':str(plan_path)}],
            'daily_quality':{'feedback':[{'kind':'scene_gap','beat_id':'b1','reason':'missing action'}]}}


def coverage(source,start=1,end=3):
    return {'requirements':[{'index':0,'covered':True,'reason':'Matching action visible in both frames',
            'matches':[{'source_id':'source','source_start':start,'source_end':end,'evidence_frame_ids':['0','1','2'],
                        'proof_mode':'direct_state',
                        'supporting_frame_ids':['1'],'supporting_reason':'Required action visible in middle frame'}]}]}


def test_coverage_requires_exact_bound_source_and_approved_time_window(tmp_path):
    state=approved(tmp_path)
    result=assess(Settings(data_dir=tmp_path),state,generate=lambda *a,**k:coverage(state['sources'][0]))
    assert result['ready']
    assert result['requirements'][0]['matches'][0]['source_sha256']==state['sources'][0]['sha256']
    result=assess(Settings(data_dir=tmp_path),state,generate=lambda *a,**k:coverage(state['sources'][0],0,5))
    assert not result['ready']


def test_edit_selection_cannot_use_other_interval_of_approved_source(tmp_path):
    state=approved(tmp_path)
    state['scripts'][0]['text']='Observed action.'
    from pathlib import Path
    Path(state['edits'][0]['plan_path']).write_text(json.dumps({'script_text':'Observed action.',
        'beats':[{'id':'b1','text':'Observed action.'}]}),encoding='utf-8')
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,
                                                     generate=lambda *a,**k:coverage(state['sources'][0]))
    source=state['sources'][0]
    plan={'script_text':state['scripts'][0]['text'],
          'shots':[{'id':'shot','source_id':'source','sha256':source['sha256'],'path':source['path'],'start':0,'end':4}],
          'beats':[{'id':'b1','text':'Observed action.','start':0,'end':1,'options':[{'shot_id':'shot'}],'selected_shot_id':'shot'}]}
    constrain_plan(state,plan)
    option=plan['beats'][0]['options'][0]['shot_id']
    narrowed=next(s for s in plan['shots'] if s['id']==option)
    assert (narrowed['start'],narrowed['end'])==pytest.approx((1,3.04))
    plan['beats'][0].update(selected_shot_id=option,source_start=1.2,source_end=2.2)
    validate_selected_scenes(state,plan)
    plan['beats'][0].update(source_start=3.2,source_end=3.9)
    with pytest.raises(QualitySceneGap):validate_selected_scenes(state,plan)


def test_global_requirement_restricts_every_beat(tmp_path):
    state=approved(tmp_path);state['daily_quality']['feedback'][0]['beat_id']=''
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,
                                                     generate=lambda *a,**k:coverage(state['sources'][0]))
    plan={'shots':[{'id':'old','source_id':'not-approved','sha256':'other','start':0,'end':4}],
          'beats':[{'id':bid,'start':0,'end':1,'options':[{'shot_id':'old'}],'selected_shot_id':'old'}
                   for bid in ('b1','b2')]}
    constrain_plan(state,plan)
    assert all(b.get('visual_alignment_gap') for b in plan['beats'])
    with pytest.raises(QualitySceneGap):validate_selected_scenes(state,plan)


def test_changed_requirements_invalidate_same_input_coverage(tmp_path):
    state=approved(tmp_path)
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,
                                                     generate=lambda *a,**k:coverage(state['sources'][0]))
    state['daily_quality']['feedback'].append({'kind':'scene_gap','beat_id':'b2','reason':'new missing action'})
    plan={'shots':[],'beats':[]}
    with pytest.raises(QualitySceneGap):validate_selected_scenes(state,plan)


def test_actual_file_replacement_invalidates_cached_approval(tmp_path):
    from pathlib import Path
    from hotpost.scene_requirements import coverage_current
    state=approved(tmp_path)
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,
                                                     generate=lambda *a,**k:coverage(state['sources'][0]))
    assert coverage_current(state)
    Path(state['sources'][0]['path']).write_bytes(b'replaced bytes')
    assert not coverage_current(state)
    result=assess(Settings(data_dir=tmp_path),state,generate=lambda *a,**k:pytest.fail('Changed source must be excluded'))
    assert not result['ready']


def test_same_rejected_input_is_not_reviewed_repeatedly(tmp_path):
    state=approved(tmp_path)
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,
        generate=lambda *a,**k:{'requirements':[{'index':0,'covered':False,'reason':'Not visible'}]})
    result=assess(Settings(data_dir=tmp_path),state,generate=lambda *a,**k:pytest.fail('Same rejection is durable'))
    assert not result['ready']


def test_render_identity_counts_real_interval_change_but_ignores_review_prose(tmp_path):
    from hotpost.scene_requirements import repair_render_signature
    state=approved(tmp_path)
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,
                                                     generate=lambda *a,**k:coverage(state['sources'][0]))
    original=repair_render_signature(state);later=copy.deepcopy(state)
    later['daily_quality']['scene_requirements']['requirements'][0]['coverage_reason']='Same facts restated'
    assert repair_render_signature(later)==original
    later['daily_quality']['scene_requirements']['requirements'][0]['matches'][0]['source_start']=2
    assert repair_render_signature(later)!=original


def test_parent_model_wait_observes_actual_child_content_progress(tmp_path):
    from hotpost.studio_adapter import StudioAdapter
    from hotpost.writing.jobs import Jobs
    from hotpost.editing_adapter import _atomic_json
    adapter=StudioAdapter(Settings(data_dir=tmp_path,studio_timeout=1))
    adapter._jobs=Jobs(tmp_path/'writing')
    job=adapter.jobs.create('editorial',{})
    folder=adapter.jobs.root/job['id']/'codex-child';folder.mkdir(parents=True)
    started=time.monotonic();count=[0]
    def get(_):
        count[0]+=1
        _atomic_json(folder/'progress.json',{'kind':'model_items','call_id':folder.name,'sequence':count[0]})
        return {**job,'state':'completed' if time.monotonic()-started>=2 else 'running','progress':.2,'result':{}}
    adapter.get=get
    assert adapter._wait(job)['state']=='completed'
    assert time.monotonic()-started>=2


def test_parent_model_wait_does_not_accept_duplicate_progress_receipt(tmp_path):
    from hotpost.studio_adapter import StudioAdapter
    from hotpost.writing.jobs import Jobs
    from hotpost.editing_adapter import _atomic_json
    from hotpost.operation_progress import NoProgressTimeout
    adapter=StudioAdapter(Settings(data_dir=tmp_path,studio_timeout=1));adapter._jobs=Jobs(tmp_path/'writing')
    job=adapter.jobs.create('editorial',{});folder=adapter.jobs.root/job['id']/'codex-child';folder.mkdir(parents=True)
    _atomic_json(folder/'progress.json',{'kind':'model_items','call_id':folder.name,'sequence':1})
    adapter.get=lambda _:{**job,'state':'running','progress':.2}
    with pytest.raises(NoProgressTimeout):adapter._wait(job)
