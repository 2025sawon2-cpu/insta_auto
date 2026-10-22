import copy

import pytest


def test_repair_keeps_verified_interval_presentation_in_parent_observation_cache(tmp_path,monkeypatch):
    from hotpost import studio_ai
    real_describe=studio_ai.describe_shots
    from test_semantic_plan_cache import fixture
    editor,state,job,_,_=fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(studio_ai,'describe_shots',real_describe)
    original=editor._process
    def analyze(*a,**k):
        result=original(*a,**k)
        result['plan']['shots'][0]['interval_presentation_required']=True
        return result
    monkeypatch.setattr(editor,'_process',analyze)
    calls=[]
    def generate(settings,instruction,data,**kwargs):
        calls.append(data)
        if 'shot_ids' in data:
            return {'shots':[{'id':'shot','observation':'Actual glossy hooded jacket',
                'visual_type':'product','tags':['hood'],
                'presentation':{'product_role':'promoted_product','product_visible':True,
                    'frame_product_visibility':[True],'visible_information':['glossy hood'],
                    'visual_cluster':'actual-view','uncertainty':'sample evidence',
                    'composition':.8,'clarity':.8,'product_coverage':.6,'mask_product_overlap':.1}}]}
        return {'beats':[{'id':'beat','promoted_subject_reference':True,
            'options':[{'shot_id':'shot','relation':'direct','reason':'Actually observed product',
                        'action_match':'supports'}]}]}
    monkeypatch.setattr('hotpost.script_rewriter._generate',generate)
    monkeypatch.setattr(studio_ai,'_generate',generate)
    first=editor._edit(state,job)
    assert first['plan']['shots'][0]['shot_presentation']['product_visible']
    state['edit_id']='edit'
    repaired=editor._edit(state,{**job,'id':'repair','checkpoint':{}})
    assert repaired['plan']['shots'][0]['shot_presentation']['product_visible']
    assert repaired['plan']['beats'][0]['semantic_analysis_status']=='ranked'
    assert len([data for data in calls if 'shot_ids' in data])==1
    assert len([data for data in calls if 'shot_ids' not in data])==2


def parent_fixture(tmp_path):
    from hotpost.shot_presentation import interval_receipt
    from hotpost.studio_runtime.editing import _semantic_plan_hash,_semantic_contract,_semantic_hash
    old=tmp_path/'old.jpg';old.write_bytes(b'actual identical interval pixels')
    new=tmp_path/'new.jpg';new.write_bytes(old.read_bytes())
    shot={'id':'parent-shot','source_id':'source','sha256':'source-identity',
        'start':1.,'end':3.,'frames':[str(old)],'source_role':'core',
        'observation':'Actual jacket','evidence_status':'observed','tags':['hood'],'visual_type':'product',
        'context_usage_limits':['do not prove leather composition']}
    value={'product_role':'related_product','product_visible':True,'frame_product_visibility':[True],
        'visible_information':['hood'],'visual_cluster':'same-view','uncertainty':'sample only',
        'composition':.8,'clarity':.8,'product_coverage':.6,'mask_product_overlap':.1}
    shot['shot_presentation']=interval_receipt(shot,value)
    parent={'shots':[shot]};parent['semantic_cache']={'analysis_complete':True,
        'contract_sha256':_semantic_hash(_semantic_contract()),'plan_sha256':_semantic_plan_hash(parent)}
    current={**copy.deepcopy(shot),'id':'new-shot','frames':[str(new)]}
    current.pop('shot_presentation')
    return parent,current


def test_same_actual_pixels_at_new_path_keep_complete_review_and_rebind_frames(tmp_path):
    from hotpost.studio_runtime.editing import _parent_observations
    from hotpost.shot_presentation import interval_receipt
    parent,current=parent_fixture(tmp_path)
    before=copy.deepcopy(parent)
    reused=_parent_observations(parent,[current])
    assert reused['new-shot']['presentation']['product_role']=='related_product'
    receipt=interval_receipt(current,reused['new-shot']['presentation'])
    assert receipt['evidence_frames'][0]['path']==current['frames'][0]
    assert parent==before


@pytest.mark.parametrize('change',['source','rounded_window','new_frame','old_frame','missing_frame',
    'metadata_tamper','legacy','policy','visibility','rating','usage_limits','role',
    'featured_subject','product_source_kind','old_contract','missing_contract'])
def test_incomplete_or_changed_visual_evidence_requires_fresh_normal_review(tmp_path,change):
    from pathlib import Path
    from hotpost.studio_runtime.editing import _parent_observations,_semantic_plan_hash
    parent,current=parent_fixture(tmp_path);prior=parent['shots'][0]
    if change=='source':current['sha256']='different source'
    elif change=='rounded_window':current['start']+=.00001
    elif change=='new_frame':Path(current['frames'][0]).write_bytes(b'different current pixels')
    elif change=='old_frame':Path(prior['frames'][0]).write_bytes(b'different old pixels')
    elif change=='missing_frame':Path(prior['frames'][0]).unlink()
    elif change=='metadata_tamper':prior['observation']='Invented leather claim'
    elif change=='legacy':prior.pop('shot_presentation')
    elif change=='policy':prior['shot_presentation']['policy']='obsolete policy'
    elif change=='visibility':prior['shot_presentation']['frame_product_visibility']=[]
    elif change=='rating':prior['shot_presentation']['clarity']='unknown'
    elif change=='usage_limits':current['context_usage_limits']=[]
    elif change=='role':current['source_role']='context_only'
    elif change=='featured_subject':current['featured_subject']='different featured subject'
    elif change=='product_source_kind':current['product_source_kind']='core_product'
    elif change=='old_contract':parent['semantic_cache']['contract_sha256']='old-code-and-prompt'
    elif change=='missing_contract':parent['semantic_cache'].pop('contract_sha256')
    if change!='metadata_tamper':parent['semantic_cache']['plan_sha256']=_semantic_plan_hash(parent)
    assert _parent_observations(parent,[current])=={}
