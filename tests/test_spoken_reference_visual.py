import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from hotpost.writing import visual_reference
from hotpost.writing.reference_evidence import VisualEvidenceIntegrityError


def fixture(tmp_path,monkeypatch):
    video=tmp_path/'reference.mp4';video.write_bytes(b'isolated reference fixture')
    identity=hashlib.sha256(video.read_bytes()).hexdigest();calls=[]
    monkeypatch.setattr(visual_reference,'_duration',lambda *a:4.)
    monkeypatch.setattr(visual_reference.shutil,'which',lambda *a:'ffprobe')
    def sample(source,sha,folder,intervals,**kwargs):
        calls.append((source,sha,intervals,kwargs))
        folder.mkdir(parents=True,exist_ok=True);frames=[]
        for i in range(6):
            path=folder/f'{i}.jpg';path.write_bytes(f'actual fixture pixel {i}'.encode())
            frames.append({'frame_id':str(i),'source_timestamp':i/2,'path':str(path),
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        return {'source_path':str(source),'source_sha256':sha,'source_duration':4.,'frames':frames}
    monkeypatch.setattr(visual_reference,'sample_source_frames',sample)
    return SimpleNamespace(data_dir=tmp_path),video,identity,calls


def test_spoken_reference_frames_are_reused_without_reextracting(tmp_path,monkeypatch):
    settings,video,sha,calls=fixture(tmp_path,monkeypatch)
    evidence=visual_reference.prepare(settings,video,sha)
    assert len(evidence['frames'])==6
    assert visual_reference.prepare(settings,video,sha)==evidence
    assert len(calls)==1 and calls[0][-1]['samples_per_interval']==6


@pytest.mark.parametrize('changed',['reference','frame'])
def test_changed_reference_pixels_are_not_silently_resampled(tmp_path,monkeypatch,changed):
    settings,video,sha,calls=fixture(tmp_path,monkeypatch)
    evidence=visual_reference.prepare(settings,video,sha)
    path=video if changed=='reference' else Path(evidence['frames'][0]['path'])
    path.write_bytes(b'changed')
    with pytest.raises(VisualEvidenceIntegrityError):visual_reference.prepare(settings,video,sha)
    assert len(calls)==1


def test_adapter_prepares_spoken_reference_visual_before_job_submission(tmp_path,monkeypatch):
    from hotpost.studio_adapter import StudioAdapter
    settings,video,sha,calls=fixture(tmp_path,monkeypatch)
    submitted=[]
    adapter=StudioAdapter(settings)
    adapter._jobs=SimpleNamespace(create=lambda kind,body,pid:submitted.append(body) or {'state':'queued'},start=lambda:None)
    adapter.submit('task',video,'reference speech',{'reference_kind':'speech'})
    assert len(submitted)==1 and len(submitted[0]['reference_visual_evidence']['frames'])==6
    assert submitted[0]['reference_video_sha256']==sha


def test_explicit_reference_images_are_checked_before_creating_a_job(tmp_path,monkeypatch):
    from hotpost.studio_adapter import StudioAdapter
    settings,video,sha,calls=fixture(tmp_path,monkeypatch)
    evidence=visual_reference.prepare(settings,video,sha)
    evidence=copy.deepcopy(evidence);evidence['frames'][0]['sha256']='0'*64
    adapter=StudioAdapter(settings)
    adapter._jobs=SimpleNamespace(create=lambda *a:pytest.fail('invalid pixels submitted'),start=lambda:None)
    with pytest.raises(VisualEvidenceIntegrityError):
        adapter.submit('task',video,'reference speech',{'reference_visual_evidence':evidence})


def test_actual_subject_replaces_early_title_fallback_and_preserves_manual_override():
    from hotpost.studio_automation import refresh_resolved_subject
    state={'product':'피아노 영상 속 카리나 착장 보자마자','original_text':'바지 소개'}
    manifest={'caption':'스웻팬츠 입을 때 가장 신경 쓰이는 게','product_evidence':{
        'primary_subject':{'name':'스웻팬츠','source':'caption','quote':'스웻팬츠 입을 때 가장 신경 쓰이는 게'}}}
    assert refresh_resolved_subject(state,manifest) and state['product']=='스웻팬츠'
    assert state['product_resolution_history'][0]['previous'].startswith('피아노')
    state.update(product='사용자 제품',product_override='사용자 제품')
    assert not refresh_resolved_subject(state,manifest) and state['product']=='사용자 제품'


def test_missing_reference_evidence_keeps_existing_product_instead_of_promoting_title():
    from hotpost.studio_automation import refresh_resolved_subject
    state={'product':'현재 제품명','title':'새로운 제목 문장','original_text':'같이 써봐요'}
    assert not refresh_resolved_subject(state,{})
    assert state['product']=='현재 제품명' and 'product_resolution_history' not in state


def test_resolved_old_native_requirement_cannot_be_applied_to_new_narration():
    from hotpost.scene_requirements import anchor_selected_scenes
    state={'daily_quality':{'feedback':[],'scene_requirements':{'ready':True,'requirements':[
        {'kind':'scene_gap','beat_id':'beat-15','reason':'old zipper issue','covered':True,
         'matches':[{'proof_mode':'direct_state','supporting_frame_ids':['old-frame']}]}]}}}
    plan={'script_text':'새 대본','shots':[],'beats':[{'id':'beat-15','text':'상의에도 차려입은'}]}
    original=copy.deepcopy((state,plan))
    anchor_selected_scenes(state,plan)
    assert (state,plan)==original


def test_active_native_requirement_still_rejects_unbound_old_receipt():
    from hotpost.scene_requirements import anchor_selected_scenes
    from hotpost.daily_quality import QualitySceneGap
    requirement={'kind':'scene_gap','beat_id':'beat-15','reason':'actual active issue'}
    state={'daily_quality':{'feedback':[requirement],'scene_requirements':{
        'ready':False,'requirements':[{**requirement,'covered':True,
         'matches':[{'proof_mode':'direct_state','supporting_frame_ids':['old-frame']}]}]}}}
    with pytest.raises(QualitySceneGap):anchor_selected_scenes(state,{'shots':[],'beats':[]})
