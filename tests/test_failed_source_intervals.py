import copy
import hashlib
import json
import pytest
from hotpost.failed_source_intervals import attach, _new_approval


def fixture(tmp_path):
    source={'id':'s','sha256':'a'*64,'watermark_masks':[],
            'mask_review':{'proposal_sha256':'old'}}
    old={'sources':[source],'shots':[{'id':'old','source_id':'s'}],
         'rendered_clips':[{'beat_id':'beat-3','selected_shot_id':'old',
             'source_sha256':source['sha256'],'selected_source_window':[0,1.1]}]}
    path=tmp_path/'timeline.json';path.write_text(json.dumps(old))
    state={'edits':[{'id':'edit','plan_path':str(path)}], 'daily_quality':{'reviews':[{
        'edit_id':'edit','plan_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'passed':False,'issues':[{'kind':'watermark','beat_id':'beat-3','reason':'Exposed right-edge credit'}]}]}}
    p={'sources':[copy.deepcopy(source)],'shots':[{'id':'moved','source_id':'s','sha256':source['sha256'],'start':0,'end':4}],
       'beats':[{'id':'beat-8','selected_shot_id':'moved','source_start':0,'source_end':.8}]}
    return state,p


def test_moved_beat_gets_global_bounded_failure_without_changing_history(tmp_path):
    state,p=fixture(tmp_path);before=copy.deepcopy(state)
    attach(state,p)
    assert [(x['start'],x['end']) for x in p['shots'][0]['failed_source_intervals']]==[(0,1.1)]
    assert state==before
    p['shots'][0].update(start=2,end=4);attach(state,p)
    assert p['shots'][0]['failed_source_intervals']==[]


def test_same_parent_derivative_cannot_hide_failed_time(tmp_path):
    state,p=fixture(tmp_path)
    p['sources'][0].update(sha256='b'*64,original_sha256='a'*64,
        original_interval={'start':.5,'end':2.5},video_meta={'duration':2})
    p['shots'][0].update(sha256='b'*64,start=0,end=2)
    attach(state,p)
    assert p['shots'][0]['failed_source_intervals'][0]['end']==pytest.approx(.6)


def test_changed_failed_plan_holds_instead_of_forgetting_defect(tmp_path):
    state,p=fixture(tmp_path)
    state['daily_quality']['reviews'][0]['plan_sha256']='wrong'
    with pytest.raises(ValueError,match='SHA'):attach(state,p)


def test_new_box_requires_new_revalidated_independent_approval(tmp_path,monkeypatch):
    state,p=fixture(tmp_path);old=copy.deepcopy(p['sources'][0]);new=p['sources'][0]
    new.update(watermark_masks=[{'source_start':0,'source_end':4,'rectangle':{'width':.1},'reviewed':True}],
               mask_review={'proposal_sha256':'new'},overlay_review_path=str(tmp_path))
    assert not _new_approval(new,old,0,1.1)
    from hotpost import source_overlay_review
    monkeypatch.setattr(source_overlay_review,'_restore_review',lambda *a,**k:(
        {**new,'reviewed_intervals':[{'source_start':0,'source_end':4}]},{},{}))
    assert _new_approval(new,old,0,1.1)
    attach(state,p)
    assert p['shots'][0]['failed_source_intervals']==[]
    new['mask_review']['proposal_sha256']='old'
    assert not _new_approval(new,old,0,1.1)
