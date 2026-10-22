import copy,hashlib,json,subprocess
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import pytest
from hotpost import ego_source_backend as ego,source_finder as finder
from hotpost.config import Settings
from hotpost.source_access_preflight import SourceAccessWaiting
from hotpost.source_attempts import candidate_execution
from hotpost.source_search.strategy import candidate_ledgers
from test_source_probe_budget import probe_run
NATIVE_DOWNLOAD=finder.download_candidate
NATIVE_PROBE=finder.probe_video
TASK='work-test'; IDS=['7111111111111111111','7222222222222222222']
URLS=['https://www.tiktok.com/@fixture/video/'+i for i in IDS]

@pytest.fixture
def configured(tmp_path):
 p=tmp_path/'binding.json';p.write_text(json.dumps({'spaceId':6,'authorizedTaskIds':[TASK],'pages':{'tiktok':'p1'}}),'utf8')
 s=Settings(data_dir=tmp_path/'data',source_ego_binding=str(p));s.source_dir.mkdir(parents=True)
 return s

def unavailable(index=0,**changes):
 row={'status':'candidate_unavailable','reason':'no_observed_successful_exact_playback_resource','attempted':False,'navigation_started':True,'navigation_attempted':True,'expected_id':IDS[index],'observed_id':IDS[index],'source_url':URLS[index], 'ego_receipt_path':'isolated-result.json','ego_receipt_sha256':'a'*64}
 row.update(changes);return row

def call_native(s,row,monkeypatch,tmp_path):
 monkeypatch.setattr(ego,'_invoke',lambda *a,**k:row)
 monkeypatch.setattr(finder,'SOURCE_COOLDOWNS',{})
 token=ego._OWNER.set((s,{'task_id':TASK,'job_id':'job-test','run_id':'run-test'}))
 candidate=finder.Candidate(URLS[0],'ego-tiktok');out=s.source_dir/'fixture/videos';out.mkdir(parents=True,exist_ok=True)
 try:return candidate,NATIVE_DOWNLOAD(candidate,out,1,1)
 finally:ego._OWNER.reset(token)

@pytest.mark.parametrize('reason',['exact_video_metadata_missing','no_exact_playable_video','no_observed_successful_exact_playback_resource'])
def test_confirmed_candidate_failure_returns_none_and_consumes_only_that_url(configured,monkeypatch,tmp_path,reason):
 candidate,path=call_native(configured,unavailable(reason=reason),monkeypatch,tmp_path)
 assert path is None and not candidate.download_attempted and not candidate.downloaded_file
 assert candidate.download_diagnostics['navigation_attempted'] is True
 assert candidate.download_diagnostics['ego_receipt_sha256']=='a'*64
 assert candidate.rejection_reasons==['candidate_unavailable'] and not candidate_execution(asdict(candidate))['waiting']
 assert candidate_ledgers([asdict(candidate)])['inspected_urls']==[URLS[0]]
 assert not candidate_ledgers([asdict(candidate)])['attempted_urls']
 assert not (configured.data_dir/'search_cooldowns/tiktok.json').exists()

@pytest.mark.parametrize('changes',[{'attempted':True},{'navigation_attempted':False},{'expected_id':IDS[1]},{'observed_id':IDS[1]},{'source_url':URLS[1]},{'reason':'SDK error'}])
def test_unbound_or_unknown_candidate_status_stays_wait(configured,monkeypatch,tmp_path,changes):
 with pytest.raises(SourceAccessWaiting):call_native(configured,unavailable(**changes),monkeypatch,tmp_path)

@pytest.mark.parametrize('status',['captcha_review_pending','login_required','rate_limited','access_denied','user_control','space_unavailable','browser_busy','started','not_attempted'])
def test_other_statuses_do_not_advance_to_next_candidate(configured,monkeypatch,tmp_path,status):
 with pytest.raises(SourceAccessWaiting):call_native(configured,{'status':status,'reason':'boundary hold','attempted':False,'navigation_started':True},monkeypatch,tmp_path)
 if status in {'captcha_review_pending','login_required','rate_limited','access_denied'}:
  saved=json.loads((configured.data_dir/'search_cooldowns/tiktok.json').read_text('utf8'));assert saved['reason']==status

@pytest.mark.parametrize('first_status',['candidate_unavailable','captcha_review_pending','login_required','rate_limited','access_denied','user_control','space_unavailable','browser_busy','started','not_attempted'])
def test_native_find_sources_unavailable_A_then_received_B_runs_native_probe_and_stays_unapproved(probe_run,tmp_path,monkeypatch,first_status):
 s=probe_run.settings;s.source_browser_search=True
 binding=tmp_path/'ego-binding.json';binding.write_text(json.dumps({'spaceId':6,'authorizedTaskIds':[TASK],'pages':{'tiktok':'p1'}}),'utf8');s.source_ego_binding=str(binding)
 # Keep normal finder/discovery/download/format/duplicate/final-selection flow.
 # External reference/model fixtures remain dry and cannot confer media approval.
 monkeypatch.setattr(finder,'download_candidate',NATIVE_DOWNLOAD)
 monkeypatch.setattr(finder,'probe_video',NATIVE_PROBE)
 monkeypatch.setattr(finder,'search_local_hints',lambda *_:[finder.Candidate(u,'ego-tiktok') for u in URLS])
 clip=tmp_path/'received-fixture.mp4'
 subprocess.run([finder._executable('ffmpeg'),'-v','error','-f','lavfi','-i','color=c=blue:s=360x640:r=10:d=4','-c:v','libx264','-pix_fmt','yuv420p','-y',str(clip)],check=True,capture_output=True)
 received=clip.read_bytes();calls=[]
 def boundary(settings,task,operation,**kw):
  assert task==TASK and operation=='download';calls.append(kw['url'])
  if len(calls)==1:return unavailable(status=first_status)
  Path(kw['target']).write_bytes(received)
  return {'status':'received','navigation_started':True,'attempted':True,'bytes':len(received),'sha256':hashlib.sha256(received).hexdigest(),'meta':{'id':IDS[1],'source_url':URLS[1]}}
 monkeypatch.setattr(ego,'_invoke',boundary)
 def run():return finder.find_sources(s,'ref',search_context={'task_id':TASK,'job_id':'job-test','run_id':'run-test'})
 if first_status!='candidate_unavailable':
  with pytest.raises(SourceAccessWaiting):run()
  assert calls==[URLS[0]]
  return
 result=run()
 assert calls==URLS
 byurl={x['url']:x for x in result['candidates']};a,b=[byurl[u] for u in URLS];assert a['rejection_reasons']==['candidate_unavailable'] and not a['downloaded_file']
 assert b['video_meta']['width']==360 and b['video_meta']['height']==640 and b['file_sha256']==hashlib.sha256(received).hexdigest()
 assert b['preview_file'] and b['presentation_review_required'] and b['relevance_review_required']
 assert not result['quota_ready'] and not a['selected_for_zip']
 assert not b.get('functional_review') and b['relevance_review_required']
 manifest=json.loads((Path(result['zip_path']).parent/'manifest.json').read_text('utf8'))
 assert manifest['status']!='failed' and next(x for x in manifest['candidates'] if x['url']==URLS[0])['download_diagnostics']['navigation_attempted']
 assert not (s.data_dir/'search_cooldowns/tiktok.json').exists()
