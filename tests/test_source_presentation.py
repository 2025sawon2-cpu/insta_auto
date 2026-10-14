"""Raw dimensions are advisory; actual portrait samples decide edit eligibility."""
import copy
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from hotpost import source_presentation as sp
from hotpost.config import Settings
from hotpost.source_quality import editing_ready, media_format_reasons, sha256_file
from hotpost.studio_sources import source_goal
from hotpost.source_policy import current_policy
from test_parallel_sources import asset, automatic_review_fixture
from test_source_probe_budget import probe_run


def receipt(source, quality=True, action=True):
    return {'policy':sp.POLICY,'reviewed':True,'source_sha256':source['sha256'],
        'scope':copy.deepcopy(sp.review_scope(source)), 'evidence_frames':[{'path':'portrait.png'}],
        'usable':quality and action, 'quality_usable':quality, 'action_preserved':action}


@pytest.mark.parametrize('width,height', [(320,568),(1280,360),(5120,1440),(1920,1080)])
def test_raw_dimensions_warn_without_rejecting_downloaded_candidate(probe_run, monkeypatch, width, height):
    from hotpost import source_finder as sf
    meta={'width':width,'height':height,'duration':10}
    assert not media_format_reasons(meta)
    monkeypatch.setattr(sf,'probe_video',lambda _:meta)
    result=probe_run.run()
    selected=next(c for c in result['candidates'] if c['selected_for_zip'])
    assert selected['format_warnings'] and selected['presentation_review_required']
    assert not selected['rejection_reasons'] and not editing_ready(selected)


@pytest.mark.parametrize('width,height', [(None,720),(0,720),(720,float('inf')),(720,float('nan'))])
def test_missing_or_invalid_video_dimensions_cannot_become_a_candidate(width,height):
    assert media_format_reasons({'width':width,'height':height,'duration':10})==['invalid_video_dimensions']


def test_effective_resolution_describes_the_actual_center_crop():
    g=sp.portrait_geometry({'width':1920,'height':1080})
    assert g['effective_width']==607.5 and g['effective_height']==1080
    assert g['upscale_factor']==1.778 and g['retained_area_ratio']==.3164
    g=sp.portrait_geometry({'width':720,'height':1280})
    assert g['retained_area_ratio']==1 and g['upscale_factor']==1.5
    assert not sp.format_warnings({'width':720,'height':1280})


@pytest.mark.parametrize('quality,action', [(False,True),(True,False),(True,True)])
def test_actual_portrait_verdict_controls_usable_time(tmp_path,quality,action):
    source=asset(tmp_path,0,core=True)
    source['video_meta']={'width':320,'height':568,'duration':40}
    source['presentation_review_required']=True
    assert not editing_ready(source)
    sp.apply_presentation_review(source,receipt(source,quality,action))
    assert editing_ready(source) is (quality and action)
    goal=source_goal({'sources':[source],'source_policy':current_policy()})
    assert goal['ready'] is (quality and action)
    assert goal['usable_seconds']==(40 if quality and action else 0)


def test_stale_file_geometry_intervals_and_activity_require_new_review(tmp_path):
    source=asset(tmp_path,0,core=True)
    sp.apply_presentation_review(source,receipt(source))
    assert not sp.needs_presentation_review(source) and editing_ready(source)
    for change in ({'sha256':'changed'}, {'video_meta':{'width':1080,'height':1920,'duration':4}},
                   {'reviewed_intervals':[{'source_start':1,'source_end':3}]}, {'source_role':'context_only'}):
        changed={**copy.deepcopy(source),**change}
        assert sp.needs_presentation_review(changed) and not editing_ready(changed)


def test_missing_or_inconsistent_review_cannot_grant_approval(tmp_path):
    source=asset(tmp_path,0,core=True)
    bad=receipt(source,False,True);bad['usable']=True
    sp.apply_presentation_review(source,bad)
    assert not editing_ready(source) and not source['editing_eligible']
    source['editing_eligible']=True
    bad=receipt(source);bad['evidence_frames']=[]
    sp.apply_presentation_review(source,bad)
    assert source['presentation_review_required'] and not editing_ready(source)


def test_cut_off_action_is_excluded_in_real_studio_review_loop(tmp_path,monkeypatch):
    studio,tid,job,result,_,_,_=automatic_review_fixture(tmp_path,monkeypatch,active=False)
    sources=result['sources'][:2]
    for s in sources: s['presentation_review_required']=True;s.pop('presentation_review')
    monkeypatch.setattr(sp,'review_presentation',lambda settings,s,output:receipt(s,action=False))
    reviewed,_=studio._review_source_records(studio.store.get(tid),job,sources,lambda *_:None)
    assert all(not editing_ready(s) and 'portrait_action_cut_off' in s['presentation_rejection_reasons'] for s in reviewed)


def test_review_failure_is_not_approval_or_an_endless_retry(tmp_path,monkeypatch):
    studio,tid,job,result,_,_,_=automatic_review_fixture(tmp_path,monkeypatch,active=False)
    s=result['sources'][0];s['presentation_review_required']=True;s.pop('presentation_review')
    calls=[]
    def fail(*args):
        calls.append(1);raise RuntimeError('Model unavailable')
    monkeypatch.setattr(sp,'review_presentation',fail)
    reviewed,_=studio._review_source_records(studio.store.get(tid),job,[s],lambda *_:None)
    assert not editing_ready(reviewed[0]) and reviewed[0]['presentation_review_error']=='Model unavailable'
    studio._review_source_records(studio.store.get(tid),job,reviewed,lambda *_:None)
    assert len(calls)==1


def test_real_wide_video_supplies_actual_cropped_pixels_to_visual_reviewer(tmp_path,monkeypatch):
    ffmpeg,ffprobe=shutil.which('ffmpeg'),shutil.which('ffprobe')
    if not ffmpeg or not ffprobe: pytest.skip('ffmpeg/ffprobe unavailable')
    video=tmp_path/'wide.mp4'
    subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-f','lavfi','-i',
        'color=c=green:size=1280x360:rate=10:duration=2','-vf',
        'drawbox=x=0:y=0:w=300:h=360:color=red:t=fill','-c:v','libx264',str(video)],
        check=True,capture_output=True)
    source={'path':str(video),'sha256':sha256_file(video),'source_role':'core',
        'video_meta':{'width':1280,'height':360,'duration':2},
        'functional_review':{'observed_actions':['central activity']}}
    observed={}
    def generate(settings,instruction,data,*,media):
        observed.update(data=data,media=media)
        return {'quality_usable':True,'action_preserved':False,'reason':'Needed action lost'}
    monkeypatch.setattr('hotpost.script_rewriter._generate',generate)
    result=sp.review_presentation(Settings(data_dir=tmp_path),source,tmp_path/'samples')
    assert result['usable'] is False and len(result['evidence_frames'])==3
    assert len([m for m in observed['media'] if 'inlineData' in m])==3
    for frame in result['evidence_frames']:
        with Image.open(frame['path']) as img:
            assert img.size==(1080,1920)
            red,green,blue=img.getpixel((20,960))[:3]
            assert green>red  # Original left red activity is absent from the real center crop.


@pytest.mark.parametrize('approved',[True,False])
def test_audit_reports_post_crop_decision_without_rewriting_original_manifest(tmp_path,approved):
    import json
    from hotpost.source_audit import summarize
    source=asset(tmp_path,0,core=True)
    source['presentation_review_required']=True
    source['format_warnings']=['not_crop_friendly']
    source['editing_eligible']=True  # The preceding functional review accepted the clip.
    sp.apply_presentation_review(source,receipt(source,action=approved))
    manifest=tmp_path/'manifest.json'
    data={'downloaded':1,'search_audit':[],'candidates':[{'url':source['origin_url'],
        'downloaded_file':Path(source['path']).name, 'file_sha256':source['sha256'],
        'selected_for_zip':True,'source_quality':'clean-source','editing_eligible':None,
        'rejection_reasons':None, 'format_warnings':['not_crop_friendly'],
        'presentation_review_required':True}]}
    manifest.write_text(json.dumps(data))
    audit=summarize(manifest,[source])
    assert audit['usable']==int(approved)
    assert audit['inspection'][0]['presentation_review']['usable'] is approved
    assert audit['format_warnings']=={'not_crop_friendly':1}
    assert ('portrait_action_cut_off' in audit['rejections']) is (not approved)
    assert json.loads(manifest.read_text())==data


def test_automatic_render_uses_reviewed_crop_and_preserves_explicit_zoom_request(tmp_path):
    source=asset(tmp_path,0,core=True)
    sp.apply_presentation_review(source,receipt(source))
    plan={'sources':[source], 'shots':[{'id':'shot','path':source['path'],'sha256':source['sha256']}],
          'beats':[{'id':'auto','selected_shot_id':'shot','emphasis':2},
                   {'id':'manual','selected_shot_id':'shot','emphasis':2}]}
    sp.protect_automatic_crop(plan,[{'beat_id':'manual','emphasis':2}])
    assert plan['beats'][0]['emphasis']==0 and plan['beats'][1]['emphasis']==2
    sp.protect_automatic_crop(plan)  # A subsequent caption/export must preserve the explicit edit.
    assert plan['beats'][1]['emphasis']==2
    legacy=copy.deepcopy(plan)
    legacy['sources'][0].pop('presentation_review')
    legacy['beats'][0]['emphasis']=2
    sp.protect_automatic_crop(legacy)
    assert legacy['beats'][0]['emphasis']==2
