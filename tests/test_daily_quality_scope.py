from pathlib import Path
import pytest
from hotpost.daily_quality_scope import resolve_visual_scope
from hotpost.daily_quality import validate_report

def fixture(tmp_path):
    frame=tmp_path/'actual.jpg';frame.write_bytes(b'actual supplied image')
    suspect={'kind':'scene_gap','beat_id':'b2','reason':'Overview seems not to show wiping','search_query':'wipe'}
    local={'kind':'scene_gap','beat_id':'b1','reason':'Actual wrong fitting state','search_query':'fit'}
    groups=[{'frames':[{'beat_id':'b1','timestamp':1,'path':str(frame)}],
             'review':{'issues':[local,suspect]}},
            {'frames':[{'beat_id':'b2','timestamp':2,'path':str(frame)}],'review':{'issues':[]}}]
    evidence={'all_beats':[{'id':'b1','text':'fit'},{'id':'b2','text':'wipe'}],'script':'fit then wipe'}
    return suspect,local,groups,evidence

def test_coarse_absence_finding_is_confirmed_with_its_own_actual_frames(tmp_path):
    suspect,local,groups,evidence=fixture(tmp_path);calls=[]
    def generate(settings,instruction,data,media):
        calls.append((data,media));return {'passed':True,'issues':[]}
    issues,audits=resolve_visual_scope(None,'review',evidence,groups,[],generate,validate_report)
    assert issues==[local]
    assert groups[0]['review']['issues']==[local,suspect]  # raw report preserved
    assert audits[0]['status']=='not_supported_by_actual_detailed_frames'
    assert calls[0][0]['detailed_beat_ids']==['b2'] and calls[0][1][-1]['inlineData']['data']

def test_a_confirmed_actual_failure_is_never_dismissed(tmp_path):
    suspect,local,groups,evidence=fixture(tmp_path)
    def generate(*a,**k):return {'passed':False,'issues':[suspect]}
    issues,audits=resolve_visual_scope(None,'review',evidence,groups,[],generate,validate_report)
    assert issues==[local,suspect] and audits[0]['status']=='confirmed'

def test_primary_detailed_group_failure_does_not_need_another_model_call(tmp_path):
    suspect,local,groups,evidence=fixture(tmp_path);groups[1]['review']['issues']=[suspect]
    def forbidden(*a,**k):raise AssertionError('Already detailed evidence')
    issues,audits=resolve_visual_scope(None,'review',evidence,groups,[],forbidden,validate_report)
    assert issues==[local,suspect] and audits[0]['status']=='also_reported_with_actual_detailed_frames'

def test_confirmation_error_stops_review_instead_of_passing(tmp_path):
    _,_,groups,evidence=fixture(tmp_path)
    def generate(*a,**k):raise RuntimeError('Unavailable reviewer')
    with pytest.raises(RuntimeError):resolve_visual_scope(None,'review',evidence,groups,[],generate,validate_report)
