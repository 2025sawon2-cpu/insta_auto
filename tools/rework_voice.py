import argparse,json,time,hashlib
from hotpost.config import load_settings
from hotpost.voicebench_adapter import VoiceBenchAdapter
from hotpost.source_quality import sha256_file
from tools.rework_tiktok_batch import ROOT,save,QUERIES
def main():
 p=argparse.ArgumentParser();p.add_argument('--code',choices=list(QUERIES));a=p.parse_args()
 items=json.loads((ROOT/'writing/variants.json').read_text('utf-8'))['items']
 for item in items:
  c=item['code']
  if a.code and c!=a.code:continue
  r=ROOT/c/'final';r.mkdir(exist_ok=True);v=next(v for v in item['variants'] if v['number']==item['recommended_variant'])
  text=v['text'];digest=hashlib.sha256(text.encode()).hexdigest();vf=r/'voice.json'
  if vf.exists():
   old=json.loads(vf.read_text('utf-8'));assert old['script_sha256']==digest;continue
  script=dict(v,id='tiktok-rework-script-'+c,sha256=digest,created=time.time(),status='completed',writing_contract=json.loads((ROOT/'writing/variants.json').read_text('utf-8'))['writing_contract'])
  save(r/'script.json',script);(r/'words.txt').write_text(text,'utf-8')
  submission=r/'voice-submission.json';request=json.loads(submission.read_text('utf-8')).get('request_id') if submission.exists() else None
  result=VoiceBenchAdapter(load_settings()).synthesize(text,r/'narration.wav',progress=lambda m,n:print(c,m,n,flush=True),request_id=request,on_submitted=lambda i:save(submission,{'request_id':i,'script_sha256':digest}),generation_key='tiktok-rework-'+c+'-'+digest,require_personal_clone=True)
  voice=dict(result,id='tiktok-rework-voice-'+c,path=str(r/'narration.wav'),sha256=sha256_file(r/'narration.wav'),duration=result['audio']['duration'],script_id=script['id'],script_sha256=digest,created=time.time(),status='completed')
  save(vf,voice);print(c,'voice done',voice['duration'],flush=True)
if __name__=='__main__':main()
