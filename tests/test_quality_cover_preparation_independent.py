"""Independent boundaries for preparing actual cover evidence without rendering."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.daily_quality import DailyQualityMixin, POLICY, QualitySceneGap
from hotpost.model_service import ModelServiceUnavailable
from hotpost.quality_progress import QualityProgressHold,valid_cover_evidence
from hotpost.studio_runtime.generation import GenerationMixin
from hotpost.studio_store import StudioStore
from hotpost.studio_workflow import WorkflowMixin


def fixture(tmp_path,monkeypatch):
    from test_scene_requirement_intervals import approved
    state=approved(tmp_path)
    source=state['sources'][0];source['video_meta']={'duration':4,'width':720,'height':1280}
    frame=source['mask_review']['evidence_frames'][0]
    selected={'source_id':source['id'],'source_sha256':source['sha256'],'timestamp':1,
        'frame_path':frame['path'],'frame_sha256':frame['sha256'],
        'single_frame_confirmation':{'reviews':[{'eligible':True,'faces_present':False,'face_blur_used':False}]}}
    voice_path=tmp_path/'approved-voice.wav';voice_path.write_bytes(b'approved voice bytes')
    state.update(voice_id='voice',approved_voice_id='voice',voices=[{'id':'voice','script_id':'script',
        'path':str(voice_path),'sha256':hashlib.sha256(voice_path.read_bytes()).hexdigest()}],
        automation={'active':False},shortcode='cover-product',source_acquisition={})
    state['daily_quality'].update(policy=POLICY,repair_round=3,max_repairs=3,
        feedback=[{'kind':'scene_gap','scope':'cover','reason':'얼굴 없는 실제 제품 표지 미확보'}],
        thumbnail_lines=['제품의 숨은 장점','어떤 촉감일까요?'],scene_requirements={'ready':True,'requirements':[]})
    document={'script_text':state['scripts'][0]['text'],'voice':state['voices'][0],
        'sources':[source],'shots':[{'id':'shot','source_id':source['id'],'start':0,'end':4}],
        'beats':[{'id':'b1','text':state['scripts'][0]['text'],'selected_shot_id':'shot',
                  'source_start':0,'source_end':4,'start':0,'end':4}],
        'cover_spec':{'lines':state['daily_quality']['thumbnail_lines'],'source':selected}}
    Path(state['edits'][0]['plan_path']).write_text(json.dumps(document),encoding='utf-8')

    class Worker(DailyQualityMixin,WorkflowMixin,GenerationMixin):
        def folder(self,task):
            path=self.store.root/task;path.mkdir(exist_ok=True);return path
        def _edit(self,state,job):
            self.edits.append(copy.deepcopy(job['payload']))
            return self._render_reviewed_cover(state,job,copy.deepcopy(document))
        def _process(self,state,job,stage,payload):
            self.stages.append(stage)
            if stage=='select-shots':return {'plan':payload['plan']}
            if stage=='cover-candidates':return {'candidates':[selected]}
            pytest.fail('Prepare-only must not call renderer: '+stage)

    worker=Worker();worker.settings=Settings(data_dir=tmp_path,source_min_usable=1)
    worker.store=StudioStore(tmp_path/'prepared-cover-store');worker.stages=[];worker.edits=[]
    made,_=worker.store.create('cover-preparation','제품',prepare=False,initial=state)
    state=worker.store.get(made['id'])
    monkeypatch.setattr('hotpost.cover_selection.select_cover',lambda settings,plan,*a,**k:plan)
    job={'id':'local-prepare','task_id':state['id'],'kind':'refresh_sources','payload':{'daily_quality_repair':True},'checkpoint':{}}
    return worker,state,job,document


def test_normal_prepare_boundary_produces_signed_actual_cover_without_render(tmp_path,monkeypatch):
    worker,state,job,_=fixture(tmp_path,monkeypatch)
    evidence=worker.prepare_quality_cover_evidence(state,job)
    assert evidence and valid_cover_evidence(state,evidence)
    assert worker.stages==['select-shots','cover-candidates']
    assert worker.edits[0]['quality_prepare_only']
    before=copy.deepcopy(worker.store.get(state['id'])['daily_quality'])
    assert before['repair_round']==3 and not before.get('render_accounting')
    assert evidence['prepared_plan']['plan_sha256']==hashlib.sha256(Path(evidence['prepared_plan']['path']).read_bytes()).hexdigest()
    again=worker.prepare_quality_cover_evidence(state,job)
    assert again==evidence and len(worker.edits)==1
    assert worker.store.get(state['id'])['daily_quality']==before


@pytest.mark.parametrize('change',['path','sha','bytes','unused-time'])
def test_changed_signed_prepared_plan_is_held_before_reanalysis_or_render(tmp_path,monkeypatch,change):
    worker,state,job,_=fixture(tmp_path,monkeypatch)
    evidence=worker.prepare_quality_cover_evidence(state,job)
    state['daily_quality']['cover_repair_evidence']=copy.deepcopy(evidence)
    prepared=state['daily_quality']['cover_repair_evidence']['prepared_plan']
    if change=='path':prepared['path']=str(tmp_path/'missing.json')
    elif change=='sha':prepared['plan_sha256']='wrong-sha'
    else:
        path=Path(prepared['path'])
        document=json.loads(path.read_text('utf-8'))
        if change=='unused-time':document['beats'][0].update(source_start=2,source_end=4)
        else:document['cover_spec']['source']['frame_sha256']='wrong-frame'
        path.write_text(json.dumps(document),encoding='utf-8')
        if change=='unused-time':prepared['plan_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    assert not valid_cover_evidence(state,state['daily_quality']['cover_repair_evidence'])
    worker._edit=lambda *a:pytest.fail('Invalid signed prepared plan must hold instead of reanalysis')
    render_job={'id':'render-after-prepare','kind':'quality_reedit','payload':{'edit_id':state['edit_id']}}
    with pytest.raises(QualityProgressHold):worker._quality_reedit(state,render_job)


def test_same_failed_cover_review_method_is_not_requestioned_by_new_job_or_code(tmp_path,monkeypatch):
    worker,state,job,_=fixture(tmp_path,monkeypatch)
    calls=[]
    def failed(*a):
        calls.append(1)
        raise QualitySceneGap([{'kind':'scene_gap','scope':'cover','reason':'실제 프레임에 얼굴 존재'}])
    worker._edit=failed
    assert worker.prepare_quality_cover_evidence(state,job) is None
    from hotpost import cover_selection
    monkeypatch.setattr(cover_selection,'INSTRUCTION',cover_selection.INSTRUCTION+' metadata contract change')
    new_job={**job,'id':'new-job-id','checkpoint':{}}
    assert worker.prepare_quality_cover_evidence(state,new_job) is None
    assert len(calls)==1
    quality=worker.store.get(state['id'])['daily_quality']
    assert quality['repair_round']==3
    assert len(quality['progress_policy']['attempts'])==1
    assert quality['progress_policy']['attempts'][0]['status']=='failed'


def test_model_capacity_wait_does_not_record_failed_cover_method_or_charge(tmp_path,monkeypatch):
    worker,state,job,_=fixture(tmp_path,monkeypatch)
    normal=worker._edit
    worker._edit=lambda *a:(_ for _ in ()).throw(ModelServiceUnavailable(attempted=False))
    with pytest.raises(ModelServiceUnavailable):worker.prepare_quality_cover_evidence(state,job)
    quality=worker.store.get(state['id'])['daily_quality']
    assert quality['repair_round']==3 and not quality.get('render_accounting')
    assert not quality.get('progress_policy',{}).get('attempts')
    worker._edit=normal
    assert worker.prepare_quality_cover_evidence(state,job)


def test_deterministic_cover_preflight_failure_is_preserved_across_new_queue_id(tmp_path,monkeypatch):
    worker,state,job,_=fixture(tmp_path,monkeypatch)
    calls=[]
    def invalid_binding(*a):
        calls.append(1)
        raise ValueError('Approved source hash and actual source file disagree')
    worker._edit=invalid_binding
    try:
        assert worker.prepare_quality_cover_evidence(state,job) is None
    except ValueError:
        pass  # Propagating the original failure is compatible with preserving its method.
    next_job={**job,'id':'different-job','checkpoint':{}}
    assert worker.prepare_quality_cover_evidence(state,next_job) is None
    assert len(calls)==1
    quality=worker.store.get(state['id'])['daily_quality']
    assert quality['repair_round']==3
    assert quality['progress_policy']['attempts'][0]['status']=='failed'


@pytest.mark.parametrize('route',['deferred','received'])
def test_body_ready_context_still_reviews_received_cover_and_returns_intake_evidence(tmp_path,monkeypatch,route):
    worker,state,job,document=fixture(tmp_path,monkeypatch)
    state['scene_narration_plan']={'old_edit_id':state['edit_id'],'plan_path':state['edits'][0]['plan_path']}
    state['source_acquisition']['rounds']=([{'review_completion':{'deferred_sources':1}}] if route=='deferred' else [])
    worker.store.change(state['id'],lambda current,db:current.update(scene_narration_plan=state['scene_narration_plan']))
    monkeypatch.setattr('hotpost.scene_narration_prepare.prepare_narration_context',lambda *a:None)
    monkeypatch.setattr('hotpost.scene_requirements.assess',lambda *a,**k:{'ready':True,'requirements':[]})
    worker._review_deferred_downloads=lambda *a:{'sources':[copy.deepcopy(state['sources'][0])],
        'scene_requirements':{'ready':True,'requirements':[]},'local_deferred_review':True,
        'source_search_manifest_path':'local-manifest.json','searches':[]}
    discovery=[]
    if route=='deferred':
        monkeypatch.setattr('hotpost.source_finder.find_sources',lambda *a,**k:pytest.fail('Received source must be reviewed before external search'))
    else:
        received=tmp_path/'received';received.mkdir()
        (received/'manifest.json').write_text('{}',encoding='utf-8')
        worker._source_records=lambda *a:[copy.deepcopy(state['sources'][0])]
        worker._review_source_records=lambda current,job,records,*a:(records,None)
        monkeypatch.setattr('hotpost.source_finder.find_sources',lambda *a,**k:discovery.append(1) or {
            'zip_path':str(received/'sources.zip'),'candidates':[],'search_audit':[]})
        monkeypatch.setattr('hotpost.source_audit.reviewed_platform_outcomes',lambda *a,**k:{})
    output=worker._refresh_sources(state,job)
    assert output['cover_repair_evidence']
    if route=='deferred':assert output['local_deferred_review']
    else:assert discovery==[1] and job['checkpoint']['refresh_discovery']['sha256']
    assert output['sources'] and worker.stages==['select-shots','cover-candidates']
    candidate=copy.deepcopy(state)
    from hotpost.scene_requirements import merge_sources
    candidate['sources']=merge_sources(state['sources'],output['sources'])
    assert valid_cover_evidence(candidate,output['cover_repair_evidence'])


def test_signed_preparation_is_reused_but_normal_cover_guard_and_render_still_run(tmp_path,monkeypatch):
    worker,state,job,document=fixture(tmp_path,monkeypatch)
    old=copy.deepcopy(document)
    frame=state['sources'][0]['mask_review']['evidence_frames'][1]
    old['cover_spec']['source'].update(timestamp=2,frame_path=frame['path'],frame_sha256=frame['sha256'])
    Path(state['edits'][0]['plan_path']).write_text(json.dumps(old),encoding='utf-8')
    evidence=worker.prepare_quality_cover_evidence(state,job)
    state['daily_quality']['cover_repair_evidence']=evidence
    worker.store.change(state['id'],lambda current,db:current['daily_quality'].update(cover_repair_evidence=evidence))
    normal_process=worker._process
    def process(state,job,stage,payload):
        if stage=='render':
            worker.stages.append(stage)
            assert payload['plan']['cover_spec']['source']['frame_sha256']==evidence['image_sha256']
            return {'preview_path':'new-verified-input-render.mp4'}
        return normal_process(state,job,stage,payload)
    worker._process=process
    worker._edit=lambda *a:pytest.fail('Signed preparation should reuse selected plan rather than run full analysis')
    result=worker._quality_reedit(state,{'id':'normal-reedit','task_id':state['id'],'kind':'quality_reedit',
        'payload':{'edit_id':state['edit_id']}})
    assert worker.stages==['select-shots','cover-candidates','select-shots','cover-candidates','render']
    assert result['parent_id']==state['edit_id'] and result['quality_repair_round']==4
    quality=worker.store.get(state['id'])['daily_quality']
    assert quality['repair_round']==3 and quality.get('status')!='passed'
    assert quality['progress_policy']['attempts'][-1]['stage']=='render'
    assert quality['progress_policy']['attempts'][-1]['status']=='running'
