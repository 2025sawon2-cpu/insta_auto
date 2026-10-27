import copy,hashlib,json
import pytest
from hotpost.voicebench_adapter import VoiceBenchAdapter
from tests.test_voicebench_adapter import Response,Session,_settings,valid_wav

def snapshot():
 s={'id':'reels_bright_v1','version':1,'native':{'emotion_enabled':True,'emotion_sliders':{'happy':.35},'emotion_strength':1.,'emotion_cfg_scale':1.,'speaking_rate_enabled':False},'direction_assets_sha256':{'happy.npy':'a'*64}}
 s['sha256']=hashlib.sha256(json.dumps(s,sort_keys=True,separators=(',',':')).encode()).hexdigest();return s

class StyledSession(Session):
 def __init__(self,*,old=False,verified=True,supported=True):
  super().__init__(valid_wav());self.old=old;self.verified=verified;self.supported=supported;self.audio_downloads=0
 def status(self):
  s={} if self.old else snapshot()
  return {'id':17,'status':'succeeded','voice_id':None,'style':s,'style_actual':s if self.verified else {},'style_verified':self.verified}
 def get(self,url,**kwargs):
  if url.endswith('/health'):return Response({'ready':True,'default_voice_kind':'personal'})
  if url.endswith('/styles'):return Response({'styles':[snapshot()] if self.supported else []})
  if url.endswith('/audio'):self.audio_downloads+=1;return Response(content=self.wav)
  return Response(self.status())
 def post(self,url,**kwargs):
  self.posts+=1;assert kwargs['json']['style_id']=='reels_bright_v1';return Response(self.status())

def test_personal_reels_explicit_style_and_actual_receipt(tmp_path):
 s=StyledSession();settings=_settings(tmp_path)
 r=VoiceBenchAdapter(settings,session=s).synthesize('실제 대본',settings.data_dir/'voice.wav',require_personal_clone=True,generation_key='key-bright')
 assert s.posts==1 and s.audio_downloads==1
 assert r['requested_style_id']=='reels_bright_v1' and r['style']==r['style_actual']==snapshot()
 assert r['style_verified']

@pytest.mark.parametrize('kwargs',[{'request_id':17},{'request_id':17,'retry_failed':True},{}])
def test_old_neutral_id_or_post_never_becomes_styled_wav(tmp_path,kwargs):
 s=StyledSession(old=True);settings=_settings(tmp_path);p=settings.data_dir/'voice.wav'
 with pytest.raises(RuntimeError,match='스타일과 다릅니다'):
  VoiceBenchAdapter(settings,session=s).synthesize('실제 대본',p,require_personal_clone=True,**kwargs)
 assert not p.exists() and s.audio_downloads==0
 assert s.posts==(0 if kwargs.get('request_id') else 1)

def test_worker_unverified_style_never_downloaded(tmp_path):
 s=StyledSession(verified=False);settings=_settings(tmp_path)
 with pytest.raises(RuntimeError,match='스타일과 다릅니다'):
  VoiceBenchAdapter(settings,session=s).synthesize('실제 대본',settings.data_dir/'voice.wav',require_personal_clone=True)
 assert s.audio_downloads==0

def test_old_server_or_missing_style_fails_before_submit(tmp_path):
 s=StyledSession(supported=False);settings=_settings(tmp_path)
 with pytest.raises(RuntimeError,match='스타일 계약'):
  VoiceBenchAdapter(settings,session=s).synthesize('실제 대본',settings.data_dir/'voice.wav',require_personal_clone=True)
 assert s.posts==0
