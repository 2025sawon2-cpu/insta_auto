"""Independent crop binding and normal changed-image approval edge cases."""
import copy
from pathlib import Path

import pytest
from PIL import Image

from hotpost import cover_product_crop as crops
from hotpost.cover_selection import select_cover
from hotpost.daily_quality import QualitySceneGap
from test_cover_product_crop import fixture, model_log, verdict


@pytest.mark.parametrize('change',['unknown_candidate_source','wrong_candidate_hash',
    'not_selected_shot','used_end_exclusive','nonfinite_time','skewed_input_image'])
def test_unbound_or_wrong_canvas_candidate_cannot_become_crop_eligible(tmp_path,monkeypatch,change):
    plan,candidates,captures=fixture(tmp_path,monkeypatch)
    if change=='unknown_candidate_source':candidates[0]['source_id']='invented'
    elif change=='wrong_candidate_hash':candidates[0]['source_sha256']='a'*64
    elif change=='not_selected_shot':plan['beats'][0]['selected_shot_id']='different-shot'
    elif change=='used_end_exclusive':candidates[0]['timestamp']=2
    elif change=='nonfinite_time':candidates[0]['timestamp']=float('inf')
    else:Image.new('RGB',(480,270),'green').save(candidates[0]['frame_path'])
    calls=[]
    with pytest.raises(QualitySceneGap):select_cover(None,plan,candidates,tmp_path,model_log(calls))
    assert calls and all(c['purpose']=='cover_selection' for c in calls)
    assert captures==[] and 'source' not in plan['cover_spec']


@pytest.mark.parametrize('crop',[[.2,.2,.20001,.8],[-.1,.2,.7,.8],
    [.1,.2,.7,float('inf')],[.1,.9,.7,.2],[.1,.2,.7],[[.1],.2,.7,.8]])
def test_invalid_or_subpixel_rectangle_never_reaches_source_capture(tmp_path,monkeypatch,crop):
    plan,candidates,captures=fixture(tmp_path,monkeypatch);calls=[]
    proposals=[{'frame_id':'0','crop':crop,'reason':'A proposal cannot confer eligibility'}]
    with pytest.raises(QualitySceneGap):
        select_cover(None,plan,candidates,tmp_path,model_log(calls,proposal=proposals))
    assert captures==[] and not plan['cover_spec'].get('source')


@pytest.mark.parametrize('field',['overlays_acceptable','mask_coverage_valid','product_view_preserved'])
def test_unknown_changed_geometry_flags_cannot_inherit_old_body_approval(tmp_path,monkeypatch,field):
    plan,candidates,_=fixture(tmp_path,monkeypatch)
    source=plan['sources'][0]
    source['mask_review']={'source_sha256':source['sha256'],'faces_present':False,
                          'overlays_acceptable':True,'geometry':'body-approved'}
    old=copy.deepcopy(plan);calls=[]
    row=verdict();row.pop(field)
    with pytest.raises(QualitySceneGap):select_cover(None,plan,candidates,tmp_path,model_log(calls,batch=row))
    assert plan==old and not any(c['purpose']=='cover_single_frame_confirmation' for c in calls)
    changed=next(c for c in calls if c.get('candidate_geometry'))
    assert changed['candidate_geometry']['0']['geometry_requires_independent_review'] is True


def test_failed_actual_crop_review_is_durable_without_blind_approval_or_repeated_proposal(tmp_path,monkeypatch):
    plan,candidates,captures=fixture(tmp_path,monkeypatch);calls=[]
    model=model_log(calls,final=verdict(faces_present=True))
    for _ in range(2):
        with pytest.raises(QualitySceneGap):select_cover(None,plan,candidates,tmp_path,model)
    assert [c['purpose'] for c in calls]==['cover_selection','cover_product_crop_proposal',
        'cover_selection','cover_single_frame_confirmation']
    assert len(captures)==1 and not plan['cover_spec'].get('source')


@pytest.mark.parametrize('field',['overlays_acceptable','mask_coverage_valid','product_view_preserved'])
def test_final_single_image_must_confirm_transformed_geometry_independently(tmp_path,monkeypatch,field):
    plan,candidates,_=fixture(tmp_path,monkeypatch);calls=[]
    row=verdict();row.pop(field)
    with pytest.raises(QualitySceneGap):
        select_cover(None,plan,candidates,tmp_path,model_log(calls,final=row))
    assert calls[-1]['purpose']=='cover_single_frame_confirmation'
    assert not plan['cover_spec'].get('source')


@pytest.mark.parametrize('change',['time_within_used_window','evidence_source_hash',
    'both_crop_fields','invalid_both_crop_fields','evidence_canvas','evidence_fit'])
def test_reviewed_crop_receipt_cannot_drift_from_actual_renderer_geometry(tmp_path,monkeypatch,change):
    plan,candidates,_=fixture(tmp_path,monkeypatch)
    reviewed=select_cover(None,plan,candidates,tmp_path,model_log([]))
    selected=copy.deepcopy(reviewed['cover_spec']['source'])
    evidence=selected['cover_crop_evidence']
    if change=='time_within_used_window':selected['timestamp']=1.5
    elif change=='evidence_source_hash':evidence['source_sha256']='f'*64
    elif change=='both_crop_fields':selected['crop']=evidence['crop']=[.15,.45,.85,.85]
    elif change=='invalid_both_crop_fields':selected['crop']=evidence['crop']=[0,0,2,2]
    elif change=='evidence_canvas':evidence['canvas']=[1920,1080]
    else:evidence['fit']='stretch-before-mask'
    with pytest.raises(ValueError):crops.validate_crop_selection(plan,selected)


def test_success_keeps_original_body_sources_masks_beats_and_geometry_immutable(tmp_path,monkeypatch):
    plan,candidates,_=fixture(tmp_path,monkeypatch)
    plan['sources'][0]['mask_review']={'geometry':{'canvas':[1080,1920]},'policy':'body-existing'}
    original=copy.deepcopy(plan);calls=[]
    reviewed=select_cover(None,plan,candidates,tmp_path,model_log(calls))
    assert plan==original
    for key in ('sources','shots','beats','script_text'):
        assert reviewed[key]==original[key]
    selection=reviewed['cover_spec']['source']
    assert selection['frame_path']!=candidates[0]['frame_path']
    assert selection['reviewed'] and selection['single_frame_confirmation']
    assert selection['cover_crop_evidence']['image_sha256']!=selection['cover_crop_evidence']['original_frame_sha256']
    assert Path(candidates[0]['frame_path']).is_file()


def test_image_modified_during_final_review_is_rejected_before_returning_selected_cover(tmp_path,monkeypatch):
    plan,candidates,_=fixture(tmp_path,monkeypatch);calls=[];normal=model_log(calls)
    def model(settings,instruction,evidence,*,media):
        result=normal(settings,instruction,evidence,media=media)
        if evidence['purpose']=='cover_single_frame_confirmation':
            target=next((tmp_path/'product-crop').glob('*-crop.png'))
            Image.new('RGB',(1080,1920),'orange').save(target)
        return result
    with pytest.raises(ValueError):select_cover(None,plan,candidates,tmp_path,model)
    assert not plan['cover_spec'].get('source')
