"""Independent cover/body scope review; fixtures never touch operating state."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from hotpost import scene_requirements as scenes
from hotpost.config import Settings
from hotpost.cover_selection import select_cover
from hotpost.daily_quality import QualitySceneGap
from hotpost.source_quality import editing_ready
from hotpost.studio_runtime.lifecycle import LifecycleMixin
from test_scene_requirement_intervals import approved, coverage

LEGACY_REASON = '실제 사용 구간에서 얼굴 없이 제품 호기심을 남기는 썸네일을 확보하지 못함'


def cover_issue(**overrides):
    return {'kind':'scene_gap','beat_id':'','reason':LEGACY_REASON,
        'search_query':'재킷 제품 단독 사용 디테일 얼굴 없는 장면',**overrides}


def cover_fixture(tmp_path):
    path=tmp_path/'actual-cover.jpg';path.write_bytes(b'actual candidate frame fixture')
    return {'script_text':'실제 재킷 착장 대본','cover_spec':{'lines':['이 재킷','어떻게 쓰지?']}},[
        {'source_id':'wearing','timestamp':1,'frame_path':str(path),'score':1}]


def test_normal_cover_failure_remains_recollection_issue_with_explicit_cover_scope(tmp_path):
    plan,candidates=cover_fixture(tmp_path)
    with pytest.raises(QualitySceneGap) as caught:
        select_cover(None,plan,candidates,tmp_path,generate=lambda *a,**k:{'frames':[
            {'id':'0','eligible':False,'faces_present':True,'face_blur_used':False,
             'hook_unresolved':True,'reason':'제품 착장과 함께 얼굴이 보임'}]},search_context='재킷')
    issue=caught.value.issues[0]
    assert issue['scope']=='cover' and issue['kind']=='scene_gap' and issue['search_query']
    assert scenes.required_scenes({'daily_quality':{'feedback':[issue]}})==[]


@pytest.mark.parametrize('issue,body_expected',[
    (cover_issue(scope='cover'),False),
    (cover_issue(),False),
    (cover_issue(scope='body'),True),
    (cover_issue(beat_id='body-1'),True),
    (cover_issue(reason='얼굴 가까이의 재킷 지퍼 기능이 필요한 본문 장면'),True),
    (cover_issue(reason='제품 기능의 전체 사용 모습이 없음'),True),
])
def test_scope_classifier_keeps_explicit_body_real_global_and_noncanonical_issues(issue,body_expected):
    requirements=scenes.required_scenes({'daily_quality':{'feedback':[issue]}})
    assert bool(requirements)==body_expected


def test_stale_saved_global_cover_receipt_cannot_constrain_or_anchor_body(tmp_path):
    state=approved(tmp_path);issue=cover_issue()
    state['daily_quality']['feedback']=[issue]
    state['daily_quality']['scene_requirements']={'ready':True,'policy':scenes.POLICY,
        'signature':scenes.input_signature(state),'requirements_key':'legacy-cover-only-key',
        'requirements':[{**issue,'covered':True,'source_ids':['cover-only-source'],
            'matches':[{'source_id':'cover-only-source','source_sha256':'cover-sha','source_start':1,'source_end':3}]}]}
    plan={'script_text':'Body narration remains unchanged','shots':[
        {'id':'body-shot','source_id':'body-source','sha256':'body-sha','start':0,'end':4}],
        'beats':[{'id':str(i),'text':'본문 착장','start':i,'end':i+1,
            'source_start':0,'source_end':1,'selected_shot_id':'body-shot','options':[{'shot_id':'body-shot'}]} for i in range(2)]}
    before=copy.deepcopy(plan)
    scenes.constrain_plan(state,plan)
    scenes.anchor_selected_scenes(state,plan)
    scenes.validate_selected_scenes(state,plan)
    assert plan==before and state['daily_quality']['scene_requirements']['requirements'][0]['reason']==LEGACY_REASON


def test_mixed_cover_and_real_body_gap_still_requires_actual_body_evidence(tmp_path):
    state=approved(tmp_path);body=copy.deepcopy(state['daily_quality']['feedback'][0])
    state['daily_quality']['feedback']=[cover_issue(scope='cover'),body]
    assert scenes.required_scenes(state)==[body]
    result=scenes.assess(Settings(data_dir=tmp_path),state,generate=lambda *a,**k:coverage(state['sources'][0]))
    assert result['ready'] and len(result['requirements'])==1
    assert result['requirements'][0]['beat_id']=='b1'
    state['daily_quality']['scene_requirements']=result
    actual_beats=json.loads(Path(state['edits'][0]['plan_path']).read_text(encoding='utf-8'))['beats']
    plan={'script_text':state['scripts'][0]['text'],'shots':[
        {'id':'body','source_id':'source','sha256':state['sources'][0]['sha256'],'path':state['sources'][0]['path'],'start':0,'end':4}],
        'beats':actual_beats}
    next(b for b in plan['beats'] if b['id']=='b1').update(start=0,end=1,selected_shot_id='body',
                  options=[{'shot_id':'body'}],source_start=0,source_end=1)
    scenes.constrain_plan(state,plan)
    with pytest.raises(QualitySceneGap):scenes.validate_selected_scenes(state,plan)


class Acceptance(LifecycleMixin):
    def __init__(self,tmp_path):
        self.settings=Settings(data_dir=tmp_path,source_min_usable=1,source_no_progress_rounds=3)
        self.advanced=[];self.stopped=[]
    def advance_workflow(self,state,db):self.advanced.append(state['daily_quality']['pending'])
    def _stop_source_collection(self,state,db,reason,diagnostics):
        self.stopped.append(reason);state['automation']['active']=False


def recollection_state(tmp_path):
    state=approved(tmp_path);source=state['sources'][0]
    source['functional_review'].update(observed_actions=['실제 재킷 착장'],evidence_frames=['actual fixture frame'])
    source['video_meta']={'duration':4,'width':720,'height':1280}
    source['faces_present']=True # Allowed in body wearing shots, separately reviewed for cover.
    state.update(id='work',source_policy={'version':1,'minimum_total':1,'platform_minimums':{}},
                 source_acquisition={'rounds':[],'strategy_version':2,'queries':[],'urls':[]},automation={'active':True})
    state['daily_quality'].update(feedback=[cover_issue(scope='cover')],repair_round=0,max_repairs=3,
        scene_no_progress=0,pending='recollecting')
    state['daily_quality']['scene_requirements']={'ready':True,'requirements':[]}
    return state


def refresh_result(sources):
    return {'sources':sources,'source_search_manifest_path':'isolated-fixture-manifest.json',
        'searches':[{'provider':'tiktok','query':'재킷','status':'no_results','requests':1}],
        'attempted_urls':[],'scene_requirements':{'ready':True,'requirements':[]}}


def accept(studio,state,sources,identity='collect'):
    studio._accept(state,{'id':identity,'kind':'refresh_sources','payload':{'daily_quality_repair':True}},refresh_result(sources))


def test_cover_only_body_ready_does_not_treat_three_attempts_as_a_quality_stop(tmp_path):
    state=recollection_state(tmp_path);studio=Acceptance(tmp_path)
    for index in range(3):
        same=copy.deepcopy(state['sources'][0])
        same['functional_review']['checked_at']=100+index # Prose/heartbeat metadata is not new footage.
        accept(studio,state,[same],str(index))
        assert state['daily_quality']['scene_no_progress']==index+1
    assert state['daily_quality']['pending']=='recollect' and not studio.stopped
    assert state['automation']['active'] and state['daily_quality']['repair_round']==0
    assert state['daily_quality']['progress_policy']['decision']['action']=='switch'
    assert 'reedit' not in studio.advanced


def test_unusable_new_file_is_not_cover_progress(tmp_path):
    state=recollection_state(tmp_path);studio=Acceptance(tmp_path)
    source=copy.deepcopy(state['sources'][0]);path=tmp_path/'unusable.mp4';path.write_bytes(b'unusable new bytes')
    source.update(id='unusable',path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),editing_eligible=False)
    source['functional_review']['source_sha256']=source['sha256']
    accept(studio,state,[source])
    assert state['daily_quality']['scene_no_progress']==1
    assert state['daily_quality']['pending']=='recollect' and state['daily_quality']['repair_round']==0


@pytest.mark.parametrize('change',['new-file','approved-window'])
def test_new_usable_content_without_cover_pixel_evidence_does_not_release_retry(tmp_path,change):
    state=recollection_state(tmp_path);studio=Acceptance(tmp_path)
    state['daily_quality']['scene_no_progress']=2
    source=copy.deepcopy(state['sources'][0])
    if change=='new-file':
        path=tmp_path/'new-usable.mp4';path.write_bytes(b'new actual usable file')
        source.update(id='new',path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        source['functional_review']['source_sha256']=source['sha256']
        source['mask_review']['source_sha256']=source['sha256']
    else:
        state['sources'][0]['reviewed_intervals']=[{'source_start':0,'source_end':2}]
        source['reviewed_intervals']=[{'source_start':0,'source_end':4}]
    assert source['faces_present'] and editing_ready(source)
    accept(studio,state,[source])
    assert state['daily_quality']['scene_no_progress']==3
    assert state['daily_quality']['pending']=='recollect'
    assert state['daily_quality']['repair_round']==0 and not studio.stopped


def test_actual_new_reviewed_cover_pixels_release_retry_without_body_face_ban(tmp_path):
    from PIL import Image
    state=recollection_state(tmp_path);studio=Acceptance(tmp_path)
    state['daily_quality']['scene_no_progress']=2
    source=copy.deepcopy(state['sources'][0])
    source['reviewed_intervals']=[{'source_start':0,'source_end':4}]
    path=tmp_path/'new-face-free-cover.png'
    Image.new('RGB',(32,32),(30,80,140)).save(path)
    state['daily_quality']['cover_repair_evidence']={
        'reviewed':True,'image_path':str(path),'image_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'source_sha256':source['sha256'],'source_timestamp':1,'rectangle':[0,0,32,32],
        'watermark_masks':source.get('watermark_masks',[]),
        'selection':{'source_sha256':source['sha256'],'source_id':source['id'],
            'timestamp':1,'frame_path':str(path),'frame_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'single_frame_confirmation':{'eligible':True,'faces_present':False,'face_blur_used':False}}}
    assert source['faces_present'] and editing_ready(source)
    accept(studio,state,[source])
    assert state['daily_quality']['scene_no_progress']==0
    assert state['daily_quality']['pending']=='reedit' and not studio.stopped


@pytest.mark.parametrize('status',['login_required','verification_required','cooldown','not_attempted','no_supported_queries','outcomes-only'])
def test_actual_unattempted_search_outcomes_are_waits_without_no_progress_or_cap_consumption(tmp_path,status):
    from hotpost.source_outcomes import platform_outcomes
    state=recollection_state(tmp_path);studio=Acceptance(tmp_path)
    state['daily_quality'].update(scene_no_progress=2,collection_attempt=4)
    searches=[] if status=='outcomes-only' else [
        {'provider':'tiktok','query':'재킷','status':status,'requests':0}]
    outcomes=platform_outcomes([],searches)
    assert outcomes['tiktok']['search_attempts']==outcomes['tiktok']['download_attempts']==0
    result=refresh_result([]);result.update(searches=searches,platform_outcomes=outcomes)
    studio._accept(state,{'id':'blocked','kind':'refresh_sources','payload':{'daily_quality_repair':True}},result)
    assert state['daily_quality']['scene_no_progress']==2
    assert state['daily_quality']['collection_attempt']==4 and state['daily_quality']['repair_round']==0
    expected = 'recollecting' if status in {'login_required','verification_required','cooldown'} else 'scene_wait'
    assert state['daily_quality']['pending']==expected and studio.advanced==studio.stopped==[]
    if expected == 'recollecting':
        assert result['_defer_until'] > 0 and state['source_search']['waiting'] is True
    assert state['daily_quality']['source_waits'][-1]['platform_outcomes']==outcomes
    assert state['source_acquisition']['rounds'][-1]['external_search_attempted'] is False


@pytest.mark.parametrize('status',['no_results','query_restricted','search_failed','error'])
def test_completed_search_without_new_usable_cover_data_counts_no_progress(tmp_path,status):
    from hotpost.source_outcomes import platform_outcomes
    state=recollection_state(tmp_path);studio=Acceptance(tmp_path)
    searches=[{'provider':'tiktok','query':'재킷','status':status,'requests':1}]
    result=refresh_result([]);result.update(searches=searches,platform_outcomes=platform_outcomes([],searches))
    studio._accept(state,{'id':'completed','kind':'refresh_sources','payload':{'daily_quality_repair':True}},result)
    assert state['daily_quality']['scene_no_progress']==1
    assert state['daily_quality']['pending']=='recollect' and state['daily_quality']['repair_round']==0


def test_mask_review_timestamp_without_changed_render_geometry_is_not_cover_progress(tmp_path):
    state=recollection_state(tmp_path);studio=Acceptance(tmp_path)
    state['sources'][0]['watermark_masks']=[{'source_start':0,'source_end':4,'rectangle':[0,0,.2,.1],
        'strength':20,'expected_scale':1,'reviewed':True,'reviewed_at':100}]
    source=copy.deepcopy(state['sources'][0]);source['watermark_masks'][0]['reviewed_at']=101
    accept(studio,state,[source])
    assert state['daily_quality']['scene_no_progress']==1
    assert state['daily_quality']['pending']=='recollect'


def test_mixed_rewrite_remap_preserves_cover_issue_and_maps_only_actual_body_index(tmp_path):
    from hotpost.scene_narration_prepare import prepare_narration_context
    from test_scene_narration_prepare import mixed, Studio, job, mapping
    state,plan=mixed(tmp_path);legacy=cover_issue()
    state['daily_quality']['feedback'].insert(0,copy.deepcopy(legacy))
    studio=Studio(tmp_path,state,plan)
    assert prepare_narration_context(studio,state,job(),generate=lambda *a:mapping())
    assert state['daily_quality']['feedback'][0]==legacy
    assert scenes.required_scenes(state)[0]['beat_id']=='new-action'
    assert len(scenes.required_scenes(state))==1


def test_empty_unknown_acquisition_has_no_completed_attempt_evidence(tmp_path):
    state=recollection_state(tmp_path);studio=Acceptance(tmp_path)
    state['daily_quality'].update(scene_no_progress=2,collection_attempt=4)
    result=refresh_result([]);result.update(searches=[],platform_outcomes={})
    studio._accept(state,{'id':'unknown','kind':'refresh_sources','payload':{'daily_quality_repair':True}},result)
    assert state['daily_quality']['scene_no_progress']==2
    assert state['daily_quality']['collection_attempt']==4 and state['daily_quality']['repair_round']==0
    assert state['daily_quality']['pending']=='scene_wait'
    assert studio.advanced==studio.stopped==[]
    assert state['daily_quality']['source_waits'][-1]['searches']==[]
    assert state['daily_quality']['source_waits'][-1]['platform_outcomes']=={}


def test_ready_body_receipt_same_actual_matches_with_changed_prose_and_time_is_not_progress(tmp_path):
    state=approved(tmp_path);studio=Acceptance(tmp_path)
    state.update(id='work',source_acquisition={'rounds':[],'strategy_version':2,'queries':[],'urls':[]},
        automation={'active':True})
    receipt=scenes.assess(Settings(data_dir=tmp_path),state,generate=lambda *a,**k:coverage(state['sources'][0]))
    assert receipt['ready'] and receipt['requirements'][0]['covered']
    state['daily_quality'].update(scene_requirements=receipt,scene_no_progress=2,collection_attempt=4,
        repair_round=0,max_repairs=3,pending='recollecting')
    from hotpost.quality_progress import permit,finish_attempt
    assert permit(state,'reedit',reserve=True,job_id='prior-render')
    finish_attempt(state,{'id':'prior-render'},failed=True)
    repeated=copy.deepcopy(receipt)
    repeated['checked_at']=999
    repeated['requirements'][0]['coverage_reason']='Updated explanation of the same observed cut'
    repeated['requirements'][0]['matches'][0]['supporting_reason']='New prose for unchanged actual supporting frame'
    result=refresh_result([]);result['scene_requirements']=repeated
    studio._accept(state,{'id':'same-body-proof','kind':'refresh_sources',
        'payload':{'daily_quality_repair':True}},result)
    assert state['daily_quality']['scene_no_progress']==3
    assert state['daily_quality']['collection_attempt']==5 and state['daily_quality']['repair_round']==0
    assert state['daily_quality']['pending']=='recollect' and not studio.stopped
    assert state['automation']['active']
    assert state['daily_quality']['progress_policy']['decision']['action']=='switch'
