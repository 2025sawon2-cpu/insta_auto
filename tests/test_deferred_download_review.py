import copy
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from hotpost.config import Settings
from hotpost.model_service import ModelServiceUnavailable
from hotpost.studio_sources import SourceAcquisitionMixin
from hotpost.studio_runtime.generation import GenerationMixin
from hotpost.studio_runtime.media import MediaMixin


class MemoryStore:
    def __init__(self,state):self.state=state;self.checkpoints=[]
    def get(self,task):return copy.deepcopy(self.state)
    def checkpoint(self,job,value):self.checkpoints.append(copy.deepcopy(value))
    def change(self,task,callback):callback(self.state,None);return copy.deepcopy(self.state)


class Harness(SourceAcquisitionMixin,GenerationMixin):
    _source_records=staticmethod(MediaMixin._source_records)
    def folder(self,task):return self.root


def fixture(tmp_path,monkeypatch):
    manifest=tmp_path/'received'/'manifest.json';manifest.parent.mkdir()
    candidates=[]
    for index in range(9):
        path=manifest.parent/f'{index}.mp4';path.write_bytes(f'actual received bytes {index}'.encode())
        candidates.append({'url':f'https://www.tiktok.com/@product/video/{index}',
            'downloaded_file':path.name,'file_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'selected_for_zip':True,'source_quality':'unknown','functional_review':None,
            'video_meta':{'duration':4,'width':720,'height':1280},
            'relevance_review_required':True,'presentation_review_required':True,'rejection_reasons':[]})
    candidates[4]['rejection_reasons']=['quality_rejected']
    candidates[5]['manual_usage_review']={'editing_eligible':False,'reason':'User excluded'}
    candidates[6]['url']=candidates[0]['url']
    manifest.write_text(json.dumps({'shortcode':'product','candidates':candidates}),encoding='utf-8')
    existing=MediaMixin._source_records([manifest.parent/c['downloaded_file'] for c in candidates[:3]],manifest)
    existing[0].update(editing_eligible=True,functional_review={'reviewed':True,'source_sha256':existing[0]['sha256']})
    existing[1].update(editing_eligible=False,overlay_review_error='Confirmed rejection')
    existing[2].update(editing_eligible=False,manual_usage_review={'editing_eligible':False,'reason':'Preserve this denial','checked_at':123})
    reference=tmp_path/'reference.mp4';reference.write_bytes(b'actual reference')
    image=tmp_path/'reference.jpg';Image.new('RGB',(32,32),'red').save(image)
    state={'id':'work','shortcode':'product','run_id':'run','sources':existing,
        'reference_video':str(reference),'reference_duration':4,'original_text':'Actual product behavior',
        'automation':{'active':False},'source_acquisition':{'round':4,'bounded_rounds':2,'no_progress_rounds':2,
            'urls':[c['url'] for c in candidates],
            'rounds':[{'job_id':'collect-original','round':3,'run_id':'run','manifest_path':str(manifest),
                'review_completion':{'reason':'quota_met','checked_sources':3,'deferred_sources':6,
                    'reviewed_source_sha256':[candidates[7]['file_sha256']]}}]}}
    h=Harness();h.root=tmp_path/'work';h.root.mkdir();h.settings=Settings(data_dir=tmp_path)
    h.store=MemoryStore(state)
    calls=[]
    monkeypatch.setattr('hotpost.source_finder.find_sources',lambda *a,**k:pytest.fail('Never search/download while received deferred files remain'))
    monkeypatch.setattr('hotpost.source_finder.extract_frames',lambda *a,**k:[image])
    def overlay(settings,source,folder):
        calls.append(('overlay',source['sha256']))
        return {**source,'source_quality':'clean-source','mask_review':{'source_sha256':source['sha256'],
            'evidence_frames':[{'path':str(image),'source_timestamp':1}]},'reviewed_intervals':[{'source_start':0,'source_end':4}]}
    monkeypatch.setattr('hotpost.source_overlay_review.review_source_overlays',overlay)
    monkeypatch.setattr('hotpost.source_functional.reference_review_info',lambda *a:{})
    from hotpost.source_functional import REVIEW_POLICY
    def functional(settings,candidate,*args):
        calls.append(('functional',candidate.file_sha256))
        return {'reviewed':True,'policy':REVIEW_POLICY,'source_sha256':candidate.file_sha256,
            'same_core_function':True,'observed_actions':['Actual behavior'],'evidence_frames':[str(image)]}
    monkeypatch.setattr('hotpost.source_functional.review_function',functional)
    from hotpost import source_presentation
    def portrait(settings,source,folder):
        calls.append(('portrait',source['sha256']))
        return {'reviewed':True,'policy':source_presentation.POLICY,'source_sha256':source['sha256'],
            'scope':source_presentation.review_scope(source),'evidence_frames':[{'path':str(image)}],
            'usable':True,'quality_usable':True,'action_preserved':True}
    monkeypatch.setattr(source_presentation,'review_presentation',portrait)
    job={'id':'refresh','kind':'refresh_sources','payload':{'request':'Needed actual scene'},'checkpoint':{}}
    return h,state,job,candidates,manifest,calls,portrait


@pytest.mark.parametrize('kind',['refresh_sources','collect_sources'])
def test_only_received_deferred_files_resume_before_any_external_work(tmp_path,monkeypatch,kind):
    h,state,job,candidates,manifest,calls,_=fixture(tmp_path,monkeypatch)
    before=copy.deepcopy(state);raw=manifest.read_bytes();job['kind']=kind
    result=h._refresh_sources(state,job) if kind=='refresh_sources' else h._collect_source_attempt(state,job)
    expected={candidates[i]['file_sha256'] for i in (3,8)}
    assert {s['sha256'] for s in result['sources']}==expected
    assert [stage for stage,_ in calls]==['overlay','functional','portrait']*2
    assert result['local_deferred_review'] and result['visual_review_only']
    assert result['attempted_urls']==[] and result['searches']==[]
    assert all(s['presentation_review']['usable'] for s in result['sources'])
    assert state['sources']==before['sources']
    assert all(state['source_acquisition'][key]==value for key,value in before['source_acquisition'].items())
    assert manifest.read_bytes()==raw
    assert result['review_completion']['reviewed_source_sha256']==[candidates[i]['file_sha256'] for i in (3,8)]


def test_capacity_resumes_completed_function_and_overlay_without_redownload_or_promotion(tmp_path,monkeypatch):
    h,state,job,candidates,manifest,calls,portrait=fixture(tmp_path,monkeypatch)
    failures=[True]
    def wait_once(*args):
        if failures.pop() if failures else False:raise ModelServiceUnavailable()
        return portrait(*args)
    monkeypatch.setattr('hotpost.source_presentation.review_presentation',wait_once)
    before=copy.deepcopy(state['sources'])
    with pytest.raises(ModelServiceUnavailable):h._refresh_sources(state,job)
    assert state['sources']==before
    assert calls==[('overlay',candidates[3]['file_sha256']),('functional',candidates[3]['file_sha256'])]
    job['checkpoint']=copy.deepcopy(h.store.checkpoints[-1])
    result=h._refresh_sources(state,job)
    assert len([c for c in calls if c==('overlay',candidates[3]['file_sha256'])])==1
    assert len([c for c in calls if c==('functional',candidates[3]['file_sha256'])])==1
    assert {s['sha256'] for s in result['sources']}=={candidates[i]['file_sha256'] for i in (3,8)}


def test_completed_local_rejection_is_not_reviewed_again_after_later_capacity_wait(tmp_path,monkeypatch):
    h,state,job,candidates,manifest,calls,portrait=fixture(tmp_path,monkeypatch)
    from hotpost import source_overlay_review
    original=source_overlay_review.review_source_overlays
    def rejected(settings,source,folder):
        if source['sha256']==candidates[3]['file_sha256']:
            calls.append(('rejected-overlay',source['sha256']));raise ValueError('Confirmed overlay rejection')
        return original(settings,source,folder)
    monkeypatch.setattr(source_overlay_review,'review_source_overlays',rejected)
    failures=[True]
    def wait_once(*args):
        if failures.pop() if failures else False:raise ModelServiceUnavailable()
        return portrait(*args)
    monkeypatch.setattr('hotpost.source_presentation.review_presentation',wait_once)
    with pytest.raises(ModelServiceUnavailable):h._refresh_sources(state,job)
    job['checkpoint']=copy.deepcopy(h.store.checkpoints[-1])
    result=h._refresh_sources(state,job)
    bad=next(s for s in result['sources'] if s['sha256']==candidates[3]['file_sha256'])
    assert bad['editing_eligible'] is False and bad['overlay_review_error']=='Confirmed overlay rejection'
    assert calls.count(('rejected-overlay',candidates[3]['file_sha256']))==1


def test_user_denial_added_during_service_wait_dominates_saved_positive_function(tmp_path,monkeypatch):
    h,state,job,candidates,manifest,calls,portrait=fixture(tmp_path,monkeypatch)
    monkeypatch.setattr('hotpost.source_presentation.review_presentation',lambda *a:(_ for _ in ()).throw(ModelServiceUnavailable()))
    with pytest.raises(ModelServiceUnavailable):h._refresh_sources(state,job)
    denied=MediaMixin._source_records([manifest.parent/candidates[3]['downloaded_file']],manifest)[0]
    denied.update(editing_eligible=False,manual_usage_review={'editing_eligible':False,'reason':'New user denial','at':456})
    state['sources'].append(denied);saved_denial=copy.deepcopy(denied)
    monkeypatch.setattr('hotpost.source_presentation.review_presentation',portrait)
    job['checkpoint']=copy.deepcopy(h.store.checkpoints[-1])
    result=h._refresh_sources(state,job)
    assert [s['sha256'] for s in result['sources']]==[candidates[8]['file_sha256']]
    assert state['sources'][-1]==saved_denial


def test_explicit_deferred_digest_list_does_not_resurrect_other_selected_files(tmp_path,monkeypatch):
    h,state,job,candidates,manifest,calls,_=fixture(tmp_path,monkeypatch)
    state['source_acquisition']['rounds'][0]['review_completion']['deferred_source_sha256']=[candidates[8]['file_sha256']]
    result=h._refresh_sources(state,job)
    assert [s['sha256'] for s in result['sources']]==[candidates[8]['file_sha256']]


@pytest.mark.parametrize('change',['foreign_task','foreign_run','no_deferred_receipt','changed_file','path_escape'])
def test_scope_and_actual_file_binding_are_required(tmp_path,monkeypatch,change):
    h,state,job,candidates,manifest,calls,_=fixture(tmp_path,monkeypatch)
    if change=='foreign_task':
        data=json.loads(manifest.read_text());data['shortcode']='other';manifest.write_text(json.dumps(data))
    elif change=='foreign_run':state['source_acquisition']['rounds'][0]['run_id']='other-run'
    elif change=='no_deferred_receipt':state['source_acquisition']['rounds'][0]['review_completion']=None
    elif change=='changed_file':(manifest.parent/candidates[3]['downloaded_file']).write_bytes(b'replaced')
    else:
        data=json.loads(manifest.read_text());data['candidates'][3]['downloaded_file']='../reference.mp4'
        data['candidates'][8]['selected_for_zip']=False;manifest.write_text(json.dumps(data))
    if change=='changed_file':
        with pytest.raises(ValueError,match='SHA'):h._deferred_download_records(state)
    else:assert h._deferred_download_records(state)[0]==[]
    assert calls==[]


def test_local_progress_does_not_change_for_retiming_review_timestamp_only(tmp_path):
    from hotpost.quality_issue_scope import approved_footage_signature
    path=tmp_path/'actual-retimed.mp4';path.write_bytes(b'actual unchanged retimed bytes')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    source={'path':str(path),'sha256':digest,'source_quality':'clean-source','editing_eligible':True,
        'original_sha256':'parent','original_interval':{'start':1,'end':5},'video_meta':{'duration':4},
        'retiming':{'playback_rate':1,'method':'ffmpeg-setpts','source_sha256':digest,
                   'original_sha256':'parent','full_decode_passed':True}}
    later=copy.deepcopy(source);later['retiming']['checked_at']=123
    assert approved_footage_signature([source])==approved_footage_signature([later])


def test_saved_refresh_discovery_reviews_its_four_received_files_before_any_deferred_or_search(tmp_path,monkeypatch):
    h,state,job,candidates,manifest,calls,_=fixture(tmp_path,monkeypatch)
    received=[copy.deepcopy(candidates[i]) for i in (3,8)]
    for index in (9,10):
        path=manifest.parent/f'{index}.mp4';path.write_bytes(f'checkpoint received file {index}'.encode())
        received.append({**copy.deepcopy(candidates[8]),'url':f'https://www.tiktok.com/@product/video/{index}',
            'downloaded_file':path.name,'file_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    original=json.loads(manifest.read_text(encoding='utf-8'))
    original['candidates'].extend(received[2:]);manifest.write_text(json.dumps(original),encoding='utf-8')
    manifest_bytes=manifest.read_bytes()
    result={'zip_path':str(manifest.parent/'sources.zip'),'candidates':received,
        'search_audit':[{'provider':'tiktok','status':'results','query':'Previously completed discovery','requests':1}]}
    receipt=manifest.parent/'interrupted-refresh-result.json'
    receipt.write_text(json.dumps(result),encoding='utf-8');receipt_bytes=receipt.read_bytes()
    saved={'path':str(receipt),'sha256':hashlib.sha256(receipt_bytes).hexdigest(),
        'request_key':hashlib.sha256((state['shortcode']+'\n'+job['payload']['request']).encode()).hexdigest()}
    job['checkpoint']['refresh_discovery']=copy.deepcopy(saved)
    monkeypatch.setattr(h,'_review_deferred_downloads',lambda *a:pytest.fail('An already received job checkpoint must precede old deferred rounds'))
    output=h._refresh_sources(state,job)
    assert {s['sha256'] for s in output['sources']}=={c['file_sha256'] for c in received}
    assert [stage for stage,_ in calls]==['overlay','functional','portrait']*4
    assert output['searches']==result['search_audit']
    assert job['checkpoint']['refresh_discovery']==saved
    assert 'deferred_source_review' not in job['checkpoint']
    assert manifest.read_bytes()==manifest_bytes and receipt.read_bytes()==receipt_bytes
