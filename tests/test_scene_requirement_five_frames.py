import copy
import hashlib
import json

from PIL import Image

from hotpost.config import Settings
from hotpost import scene_requirements as scenes
from hotpost.source_mask_review import GEOMETRY
from hotpost.source_presentation import POLICY as PORTRAIT_POLICY, review_scope
from test_scene_requirement_intervals import approved


def five_frames(tmp_path):
    state=approved(tmp_path);source=state['sources'][0]
    frames=[]
    for index in range(5):
        path=tmp_path/f'five-{index}.jpg'
        Image.new('RGB',(32,32),(index*40,10,20)).save(path)
        frames.append({'frame_id':str(index),'source_timestamp':index+1,'path':str(path),
                       'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    source['reviewed_intervals']=[{'source_start':0,'source_end':6}]
    source['video_meta']={'width':720,'height':1280,'duration':6}
    source['mask_review'].update(geometry=dict(GEOMETRY),evidence_frames=[frames[i] for i in (4,1,3,0,2)])
    from hotpost.source_frame_timing import timing_from_probe
    source['mask_review']['native_frame_timing']=timing_from_probe({'streams':[{'duration':6}],
        'frames':[{'best_effort_timestamp_time':t,'pkt_duration_time':.04}
                  for base in range(1,6) for t in (base,base+.04)]},source['sha256'])
    source['presentation_review']={'reviewed':True,'usable':True,'quality_usable':True,
        'action_preserved':True,'reviewer':'independent_portrait','policy':PORTRAIT_POLICY,
        'source_sha256':source['sha256'],'scope':review_scope(source),
        'evidence_frames':[frames[i] for i in (0,2,4)]}
    return state,frames


def match():
    return {'requirements':[{'index':0,'covered':True,'reason':'Intermediate installation states visible',
        'matches':[{'source_id':'source','source_start':2,'source_end':4,'evidence_frame_ids':['1','3'],
                    'proof_mode':'direct_transition',
                    'supporting_frame_ids':['1','3'],'supporting_reason':'Both observed installation states are essential'}]}]}


def test_actual_two_extra_approved_frames_are_attached_chronologically_and_reusable(tmp_path):
    state,frames=five_frames(tmp_path);captured=[]
    def generate(settings,instruction,evidence,media):
        captured.append(media)
        return match()
    result=scenes.assess(Settings(data_dir=tmp_path),state,generate=generate)
    labels=[json.loads(part['text']) for part in captured[0] if 'text' in part]
    images=[part['inlineData'] for part in captured[0] if 'inlineData' in part]
    assert [row['frame_id'] for row in labels]==['0','1','2','3','4']
    assert [row['timestamp'] for row in labels]==[1,2,3,4,5]
    assert len(images)==5
    assert set(row['frame_id'] for row in labels)-{f['frame_id'] for f in state['sources'][0]['presentation_review']['evidence_frames']}=={'1','3'}
    assert result['ready'] and result['policy']==scenes.POLICY
    state['daily_quality']['scene_requirements']=result
    assert scenes.coverage_current(state), 'Final gate must bind the same approved mask-frame IDs'
    scenes.assess(Settings(data_dir=tmp_path),state,generate=lambda *a,**k: (_ for _ in ()).throw(AssertionError('Do not repeat identical proof')))


def test_old_three_frame_rejection_is_retried_once_with_actual_five_frame_payload(tmp_path):
    state,frames=five_frames(tmp_path)
    state['daily_quality']['scene_requirements']={'policy':'scene-coverage-v2-source-interval',
        'signature':scenes.input_signature(state),'requirements_key':scenes.requirements_key(state),
        'evidence_key':scenes.evidence_signature(state),'ready':False}
    calls=[]
    def generate(*args,**kwargs):
        calls.append(kwargs['media']);return {'requirements':[{'index':0,'covered':False,'reason':'Still uncertain'}]}
    result=scenes.assess(Settings(data_dir=tmp_path),state,generate=generate)
    assert len(calls)==1 and len([p for p in calls[0] if 'inlineData' in p])==5
    state['daily_quality']['scene_requirements']=result
    scenes.assess(Settings(data_dir=tmp_path),state,generate=lambda *a,**k: (_ for _ in ()).throw(AssertionError('Same negative input must stay cached')))


def test_batches_stop_only_after_all_actual_matches_are_valid(tmp_path):
    state,_=five_frames(tmp_path)
    for index in range(3):
        source=copy.deepcopy(state['sources'][0]);source['id']=f'other-{index}'
        state['sources'].append(source)
    calls=[]
    def sufficient(*args,**kwargs):calls.append(kwargs['evidence'] if 'evidence' in kwargs else args[2]);return match()
    result=scenes.assess(Settings(data_dir=tmp_path),state,generate=sufficient)
    assert len(calls)==1 and result['ready']
    assert result['completion_reason']=='all_required_scenes_have_validated_matches'
    calls.clear()
    def invalid(*args,**kwargs):
        calls.append(args[2]);value=match();value['requirements'][0]['matches'][0]['source_end']=5
        return value
    result=scenes.assess(Settings(data_dir=tmp_path),state,generate=invalid)
    assert len(calls)==2 and not result['ready'], 'Claimed coverage outside actual frame bracket must not stop later batches'


def test_one_valid_requirement_does_not_stop_while_another_is_missing(tmp_path):
    state,_=five_frames(tmp_path)
    state['daily_quality']['feedback'].append({'kind':'scene_gap','beat_id':'second',
        'reason':'Completed mat shape must be visible','search_query':'L자 주방매트'})
    for index in range(3):
        source=copy.deepcopy(state['sources'][0]);source['id']=f'other-{index}'
        state['sources'].append(source)
    calls=[]
    def generate(*args,**kwargs):
        calls.append(args[2]);return match()
    result=scenes.assess(Settings(data_dir=tmp_path),state,generate=generate)
    assert len(calls)==2 and not result['ready']
    assert [r['covered'] for r in result['requirements']]==[True,False]
    assert 'completion_reason' not in result


def test_five_frame_candidate_budget_uses_all_five_real_attachment_costs(tmp_path,monkeypatch):
    state,_=five_frames(tmp_path)
    from hotpost import visual_media
    monkeypatch.setattr(visual_media,'review_frame_data',lambda path:{'mimeType':'image/jpeg','data':'x'*(1300*1024)})
    result=scenes.assess(Settings(data_dir=tmp_path),state,generate=lambda *a,**k: (_ for _ in ()).throw(AssertionError('Never exceed the 6 MiB candidate budget')))
    assert not result['ready'] and result['assessments'][0]['reason']=='approved_window_attachment_limit'
    assert len(result['assessments'][0]['frame_ids'])==5
