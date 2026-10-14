import copy
import base64
import io
import hashlib
import json
import sys
from pathlib import Path

import pytest
from PIL import Image,ImageDraw

from hotpost import cover_product_crop as crops
from hotpost.cover_selection import select_cover
from hotpost.daily_quality import QualitySceneGap
from hotpost.model_service import ModelServiceUnavailable


def fixture(tmp_path,monkeypatch):
    video=tmp_path/'actual.mp4';video.write_bytes(b'actual used source bytes')
    sha=hashlib.sha256(video.read_bytes()).hexdigest()
    native=Image.new('RGB',(270,480),'blue');draw=ImageDraw.Draw(native)
    draw.rectangle((0,0,269,100),fill='red') # A test face region above the actual garment detail.
    draw.rectangle((30,190,240,420),fill='green')
    original=tmp_path/'used.jpg';native.save(original)
    source={'id':'source','sha256':sha,'path':str(video),'source_quality':'clean-source','watermark_masks':[]}
    shot={'id':'used','source_id':'source','sha256':sha,'path':str(video),'start':0,'end':3}
    plan={'script_text':'승인된 니트 대본입니다.','sources':[source],'shots':[shot],
        'beats':[{'id':'b','text':'승인된 니트 대본입니다.','start':0,'end':2,
            'selected_shot_id':'used','source_start':0,'source_end':2}],
        'cover_spec':{'lines':['이 니트','무엇이 다를까?']}}
    candidate={'shot_id':'used','source_id':'source','source_sha256':sha,'timestamp':1,
        'frame_path':str(original),'score':3}
    captures=[]
    def capture(source,timestamp,path):
        captures.append((source['sha256'],timestamp));native.save(path)
    monkeypatch.setattr(crops,'_capture_source_frame',capture)
    return plan,[candidate],captures


def verdict(**changes):
    return {'id':'0','eligible':True,'faces_present':False,'face_blur_used':False,'hook_unresolved':True,
        'overlays_acceptable':True,'mask_coverage_valid':True,'product_view_preserved':True,
        'reason':'실제 니트 디테일만 보이며 구체적 제품 궁금증이 남음',**changes}


def model_log(calls,*,batch=None,final=None,proposal=None):
    def model(settings,instruction,evidence,*,media):
        calls.append(copy.deepcopy(evidence))
        if evidence['purpose']=='cover_product_crop_proposal':
            return {'crops':proposal if proposal is not None else [
                {'frame_id':'0','crop':[.1,.4,.9,.9],'reason':'실제로 보이는 니트 디테일'}]}
        if evidence['purpose']=='cover_selection' and not evidence.get('candidate_geometry'):
            return {'frames':[verdict(faces_present=True,eligible=False)]}
        if evidence['purpose']=='cover_selection':return {'frames':[batch or verdict()]}
        if evidence['purpose']=='cover_single_frame_confirmation':return {'frames':[final or verdict()]}
        pytest.fail('Unexpected model stage '+evidence['purpose'])
    return model


def test_rejected_wearing_frame_gets_real_product_crop_then_batch_and_single_review(tmp_path,monkeypatch):
    plan,candidates,captures=fixture(tmp_path,monkeypatch);before=copy.deepcopy(plan);calls=[]
    result=select_cover(None,plan,candidates,tmp_path,model_log(calls))
    selected=result['cover_spec']['source'];evidence=selected['cover_crop_evidence']
    assert [c['purpose'] for c in calls]==['cover_selection','cover_product_crop_proposal',
        'cover_selection','cover_single_frame_confirmation']
    assert captures==[(candidates[0]['source_sha256'],1)]
    assert selected['crop']==[.1,.4,.9,.9] and Path(selected['frame_path']).is_file()
    assert evidence['original_frame_sha256']==hashlib.sha256(Path(candidates[0]['frame_path']).read_bytes()).hexdigest()
    assert evidence['source_sha256']==candidates[0]['source_sha256'] and evidence['timestamp']==1
    assert evidence['image_sha256']==hashlib.sha256(Path(selected['frame_path']).read_bytes()).hexdigest()
    with Image.open(selected['frame_path']) as image:assert image.size==(1080,1920)
    assert evidence['geometry_requires_independent_review'] is True
    assert calls[-1]['cover_crop_evidence']==evidence and plan==before
    select_cover(None,plan,candidates,tmp_path,model_log(calls))
    assert len(calls)==4 and len(captures)==1 # Cached pixels and reviews, no new external operation.


def test_lossless_actual_crop_uses_valid_bounded_jpeg_transport_without_resizing(tmp_path,monkeypatch):
    plan,candidates,_=fixture(tmp_path,monkeypatch);normal=model_log([]);seen=[]
    def model(settings,instruction,evidence,*,media):
        if evidence.get('candidate_geometry') or evidence.get('cover_crop_evidence'):
            inline=next(block['inlineData'] for block in media if 'inlineData' in block)
            assert inline['mimeType']=='image/jpeg'
            with Image.open(io.BytesIO(base64.b64decode(inline['data']))) as image:
                assert image.format=='JPEG' and image.size==(1080,1920)
            assert sum(len(block.get('inlineData',{}).get('data','')) for block in media)<6*1024*1024
            seen.append(evidence['purpose'])
        return normal(settings,instruction,evidence,media=media)
    select_cover(None,plan,candidates,tmp_path,model)
    assert seen==['cover_selection','cover_single_frame_confirmation']


@pytest.mark.parametrize('field,value',[
    ('faces_present',True),('face_blur_used',True),('overlays_acceptable',False),
    ('mask_coverage_valid',False),('product_view_preserved',False)])
def test_changed_crop_never_inherits_face_or_mask_approval(tmp_path,monkeypatch,field,value):
    plan,candidates,_=fixture(tmp_path,monkeypatch);before=copy.deepcopy(plan);calls=[]
    row=verdict();row[field]=value
    with pytest.raises(QualitySceneGap):select_cover(None,plan,candidates,tmp_path,model_log(calls,batch=row))
    assert plan==before and not any(c['purpose']=='cover_single_frame_confirmation' for c in calls)


def test_final_individual_face_rejection_still_blocks_crop(tmp_path,monkeypatch):
    plan,candidates,_=fixture(tmp_path,monkeypatch);calls=[]
    with pytest.raises(QualitySceneGap):
        select_cover(None,plan,candidates,tmp_path,model_log(calls,final=verdict(faces_present=True)))
    assert calls[-1]['purpose']=='cover_single_frame_confirmation'


@pytest.mark.parametrize('change',['wrong_sha','unused_timestamp','invented_shot','changed_source'])
def test_crop_proposal_requires_actual_used_timestamp_and_current_source_hash(tmp_path,monkeypatch,change):
    plan,candidates,captures=fixture(tmp_path,monkeypatch);calls=[]
    if change=='wrong_sha':candidates[0]['source_sha256']='a'*64
    elif change=='unused_timestamp':candidates[0]['timestamp']=2.5
    elif change=='invented_shot':candidates[0]['shot_id']='unknown'
    else:Path(plan['sources'][0]['path']).write_bytes(b'changed actual source')
    with pytest.raises(QualitySceneGap):select_cover(None,plan,candidates,tmp_path,model_log(calls))
    assert [c['purpose'] for c in calls]==['cover_selection'] and not captures


@pytest.mark.parametrize('crop',[[0,0,1,1.1],[0,0,float('nan'),1],[1,0,0,1],[True,0,1,1],[0,0,0,1]])
def test_invalid_crop_proposal_cannot_create_or_approve_image(tmp_path,monkeypatch,crop):
    plan,candidates,captures=fixture(tmp_path,monkeypatch);calls=[]
    proposal=[{'frame_id':'0','crop':crop,'reason':'invalid'}]
    with pytest.raises(QualitySceneGap):select_cover(None,plan,candidates,tmp_path,model_log(calls,proposal=proposal))
    assert not captures


def test_capacity_at_final_confirmation_resumes_images_and_batch_receipts(tmp_path,monkeypatch):
    plan,candidates,captures=fixture(tmp_path,monkeypatch);calls=[];normal=model_log(calls)
    def unavailable(settings,instruction,evidence,*,media):
        if evidence['purpose']=='cover_single_frame_confirmation':raise ModelServiceUnavailable()
        return normal(settings,instruction,evidence,media=media)
    with pytest.raises(ModelServiceUnavailable):select_cover(None,plan,candidates,tmp_path,unavailable)
    result=select_cover(None,plan,candidates,tmp_path,normal)
    assert result['cover_spec']['source']['single_frame_confirmation'] and len(captures)==1
    assert [c['purpose'] for c in calls].count('cover_product_crop_proposal')==1
    assert [c['purpose'] for c in calls].count('cover_selection')==2


@pytest.mark.parametrize('asset',['original','crop','native'])
def test_actual_crop_provenance_detects_tampered_images(tmp_path,monkeypatch,asset):
    plan,candidates,_=fixture(tmp_path,monkeypatch)
    result=select_cover(None,plan,candidates,tmp_path,model_log([]));selected=result['cover_spec']['source']
    if asset=='original':Path(candidates[0]['frame_path']).write_bytes(b'changed')
    elif asset=='crop':Path(selected['frame_path']).write_bytes(b'changed')
    else:
        native=next((tmp_path/'product-crop').glob('*-native.png'));native.write_bytes(b'changed')
        with pytest.raises(ValueError,match='해시'):select_cover(None,plan,candidates,tmp_path,model_log([]))
        return
    with pytest.raises(ValueError):crops.validate_crop_selection(plan,selected)


def test_bound_crop_reuses_approved_canvas_and_matches_final_consumer(tmp_path,monkeypatch):
    import subprocess
    import shutil
    from PIL import ImageOps
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'auto_capcut'))
    from auto_capcut.core import studio_cover
    plan,candidates,captures=fixture(tmp_path,monkeypatch)
    mask={'source_index':0,'reviewed':True,'source_start':0,'source_end':2,
        'rectangle':{'width':.2,'height':.1,'centerX':0,'centerY':-.2},'strength':.5,'expected_scale':1}
    plan['sources'][0]['watermark_masks']=[mask]
    plan['sources'][0]['reviewed_intervals']=[{'source_start':0,'source_end':2}]
    plan['sources'][0]['mask_review']={'source_sha256':plan['sources'][0]['sha256'],
        'intervals':[{'source_start':0,'source_end':2,'coverage_confirmed':True,'subject_visible':True}]}
    native=Image.new('RGB',(270,480),'green');ImageDraw.Draw(native).rectangle((80,240,190,285),fill='white')
    monkeypatch.setattr(studio_cover,'_probe_clock',lambda shot:[{'best_effort_timestamp_time':str(i)} for i in range(3)])
    def execute(args):
        if '-filter_complex' in args:
            subprocess.run([shutil.which('ffmpeg'),'-v','error',*args],check=True,capture_output=True)
        else:ImageOps.fit(native,(1080,1920),Image.Resampling.LANCZOS).save(Path(args[-1]))
    bound=studio_cover.prepare_masked_candidates(plan,candidates,tmp_path/'bound',execute)
    proposed=crops.product_crop_candidates(None,plan,bound,tmp_path,model_log([]))
    selected=proposed[0]
    crops.validate_crop_selection(plan,selected)
    def forbidden(args):pytest.fail('Final cover must reuse approved pixels without another decode')
    actual=studio_cover.masked_frame(plan,selected,tmp_path/'engine.png',forbidden)
    expected=Image.open(selected['frame_path']).convert('RGB')
    assert actual.size==expected.size and actual.tobytes()==expected.tobytes()
    assert captures==[]
