"""Versioned recovery edits; actual frame review precedes source approval."""
import argparse,hashlib,json,os,subprocess,time
from pathlib import Path
from PIL import Image,ImageDraw
from hotpost.config import load_settings
from hotpost.source_quality import sha256_file
from hotpost.source_finder import probe_video
from hotpost.voicebench_adapter import VoiceBenchAdapter
from hotpost.studio import Studio
from tools.recover_daily_materials import ROOT
from tools.rework_tiktok_batch import save
from tools import build_tiktok_rework as build

CODES=('DeTaESASnr_','DeTJ6HbKCdF')
CHOICE={CODES[0]:1,CODES[1]:2}
CLIPS={
 CODES[0]:[
  ('mirror-slide','7616205003841129749',11.8,15.6,None,[.10,.285,.80,.065],'은색 보드를 옆으로 밀어 전신거울을 여는 장면'),
  ('key','7616205003841129749',7.1,8.65,None,[.10,.285,.80,.065],'작은 고리 장식을 자석 보드에 거는 손동작. 열쇠 자체는 아님'),
  ('silver','7616205003841129749',5.3,7.0,None,[.10,.285,.80,.065],'은색 보드가 닫힌 전체 모습'),
  ('decorate','7616205003841129749',17.0,19.3,None,[.10,.285,.80,.065],'닫힌 은색 보드에 장식과 메모가 모여 있는 모습'),
  ('magnets','7616205003841129749',8.7,10.6,None,[.10,.285,.80,.065],'작은 자석 장식을 은색 보드에 부착함'),
  ('full-mirror','7616205003841129749',19.3,21.5,None,[.10,.285,.80,.065],'한쪽에 반사면이 보이는 전신거울과 앞의 자석 보드'),
  ('panels','7616753780129893650',3.1,5.9,None,[.08,.403,.84,.055],'설치 전 바닥에 놓인 은색 보드와 거울판'),
  ('photo','7657376551079660807',12.5,14.5,None,[.08,.308,.84,.04],'작은 사진을 자석 보드에 부착함'),
  ('wood-room','7657376551079660807',8.9,11.85,None,[.08,.308,.84,.04],'나무 수납장 옆 거울 앞에서 보드를 열고 모습을 확인함'),
  ('entry-mirror','7657376551079660807',17.7,21.1,None,[.08,.308,.84,.04],'다른 방에서 은색 보드를 밀어 거울을 보임'),
  ('outfit','7657376551079660807',23,24.5,None,[.08,.308,.84,.04],'열린 전신거울 앞에서 사람이 옷차림을 확인함')],
 CODES[1]:[
  ('roll','7633755703873817877',40.0,45.5,None,[.13,.481,.74,.044],'다리를 접은 낮은 카트와 손잡이를 보여줌. 이동 장면은 아님'),
  ('fold-legs','7619137069176130832',1.3,7.9,None,[.02,.745,.96,.11],'야외에서 테이블 다리를 접어 상판 아래에 넣음'),
  ('wheel','7611046152779140365',3,8.5,None,None,'상판 아래에 바퀴를 연결하는 클로즈업'),
  ('table-legs','7611046152779140365',31.4,38.8,None,None,'테이블 아래쪽 접이식 다리를 펼치는 동작'),
  ('height','7611046152779140365',44.5,47.1,None,None,'테이블 상판을 손으로 펼치는 조립 장면. 높이 조절 동작은 확인되지 않음'),
  ('expand','7611046152779140365',48.4,50.8,None,None,'접힌 상판을 옆으로 펼쳐 넓히는 동작'),
  ('parasol','7633755703873817877',26.8,31.4,None,[.13,.481,.74,.044],'야외에서 펼친 테이블의 전체 모습. 파라솔은 보이지 않음'),
  ('cart-load','7633755703873817877',30.9,34.1,None,[.13,.481,.74,.044],'테이블 옆에 있던 수납 상자를 들어 짐을 옮김'),
  ('table','7633755703873817877',20.4,24.3,None,[.13,.481,.74,.044],'펼쳐진 야외 테이블 전체와 옆의 의자')]
}

def configure():
 build.ROOT=ROOT;build.CODES=CODES
 original_boundary=build.boundary
 build.boundary=lambda c,action,**kw:original_boundary(c,action,quality_revision='caption-predicate-20261011-v2',**kw)
 bins=next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
 os.environ['PATH']=str(bins)+os.pathsep+os.environ['PATH']

def prepare(c):
 v=json.loads((ROOT/c/'writing/quality-v3.json').read_text('utf-8'))
 assert not v['human_review_pending'],'Actual editorial review is required.'
 r=build.root(c);r.mkdir(parents=True,exist_ok=True)
 item=next(x for x in v['scripts'] if x['number']==CHOICE[c]);text=item['text'];digest=hashlib.sha256(text.encode()).hexdigest()
 script=dict(item,id='daily-rework-script-'+c+'-'+digest[:12],sha256=digest,created=time.time(),
   status='completed',writing_contract=v['writing_contract'])
 save(r/'script.json',script);(r/'words.txt').write_text(text,'utf-8')
 st=Studio(load_settings(),workers=False)
 rec=json.loads((ROOT/c/'transcript-recovery.json').read_text('utf-8'))
 transcript=json.loads((Path(rec['directory'])/'transcript.json').read_text('utf-8'))
 st.store.create(c,c,initial={'original_text':' '.join(x['text'] for x in transcript['speech']),
   'reference_kind':'speech','reference_video':str(Path(rec['directory'])/'reference.mp4'),
   'status':'preparing','message':'새 대본과 확보한 소스로 재제작'},prepare=False)
 vf=r/'voice.json'
 if vf.exists():assert json.loads(vf.read_text('utf-8'))['script_sha256']==digest;return
 submission=r/'voice-submission.json';request=json.loads(submission.read_text('utf-8')).get('request_id') if submission.exists() else None
 result=VoiceBenchAdapter(load_settings()).synthesize(text,r/'narration.wav',progress=lambda m,n:print(c,m,n,flush=True),
   request_id=request,on_submitted=lambda i:save(submission,{'request_id':i,'script_sha256':digest}),
   generation_key='daily-rework-'+c+'-'+digest,require_personal_clone=True)
 save(vf,dict(result,id='daily-rework-voice-'+c+'-'+digest[:12],path=str(r/'narration.wav'),
   sha256=sha256_file(r/'narration.wav'),duration=result['audio']['duration'],script_id=script['id'],
   script_sha256=digest,created=time.time(),status='completed'))
 print(c,'personal voice saved',result['audio']['duration'],flush=True)

def clips(c):
 rows=json.loads((ROOT/c/'discovery.json').read_text('utf-8'))['candidates'];r=build.root(c);r.mkdir(exist_ok=True);items=[]
 for name,vid,start,end,crop,band,observation in CLIPS[c]:
  row=next(x for x in rows if x['url'].endswith('/'+vid));source=Path(row['path']);target=r/'clips'/(name+'.mp4');target.parent.mkdir(exist_ok=True)
  vf='scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=30'
  if crop:
   w,h=row['video_meta']['width'],row['video_meta']['height'];x,y,x2,y2=crop
   vf=f'crop={int(w*(x2-x))//2*2}:{int(h*(y2-y))//2*2}:{int(w*x)//2*2}:{int(h*y)//2*2},'+vf
  if band:
   x,y,w,h=[int(n*k)//2*2 for n,k in zip(band,[720,1280,720,1280])]
   vf+=f',split[base][txt];[txt]crop={w}:{h}:{x}:{y},boxblur=12:2[blur];[base][blur]overlay={x}:{y}'
  subprocess.run(['ffmpeg','-v','error','-y','-ss',str(start),'-t',str(end-start),'-i',str(source),'-an','-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','18',str(target)],check=True)
  meta=probe_video(target);frames=[]
  for i,ratio in enumerate((.05,.35,.65,.95)):
   p=target.with_name(name+f'-{i}.jpg');t=(meta['duration']-.1)*ratio
   subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(target),'-frames:v','1',str(p)],check=True)
   frames.append({'path':str(p),'sha256':sha256_file(p),'timestamp':t})
  items.append(dict(id='daily-'+c+'-'+name,name=name,path=str(target),sha256=sha256_file(target),video_meta=meta,
   original_sha256=sha256_file(source),original_interval={'start':start,'end':end},original_path=str(source),url=row['url'],
   provider='tiktok',rights='unknown-check-before-reuse',source_role='core',proposed_observation=observation,
   evidence_frames=frames,pending_visual_review=True,crop=crop,caption_softening_band=band))
 save(r/'proposed-sources.json',items)
 for offset in range(0,len(items),5):
  batch=items[offset:offset+5];sheet=Image.new('RGB',(720,345*len(batch)),'#222');d=ImageDraw.Draw(sheet)
  for j,s in enumerate(batch):
   for k,f in enumerate(s['evidence_frames']):
    im=Image.open(f['path']);im.thumbnail((180,320));sheet.paste(im,(180*k,345*j+25));d.text((180*k+2,345*j+2),f"{s['name']} {f['timestamp']:.1f}",fill='white')
  sheet.save(r/f'clip-review-{offset//5+1}.jpg')
 print(c,'bounded clips await visual review',flush=True)

def main():
 p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','clips','analyze','select','render']);p.add_argument('--code',choices=CODES);a=p.parse_args();configure()
 for c in ([a.code] if a.code else CODES):
  (globals()[a.phase] if a.phase in ('prepare','clips') else getattr(build,a.phase))(c)

if __name__=='__main__':main()
