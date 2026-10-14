"""Two immutable typography/thumbnail revisions through the Auto CapCut boundary."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import time

from PIL import Image, ImageDraw
from hotpost.config import load_settings
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file
from hotpost.studio import Studio
from tools.audit_source_repetition import OUT

CODES = ('DeNb4AsSgGw','DeOhQMSzm5N')
COPY = {
 'DeNb4AsSgGw':[['휴대폰 속 여행 사진을','냉장고에 붙인다고?'],
                 ['사진첩 속 추억을','냉장고 자석으로?'],
                 ['여행 다녀온 뒤','이렇게 간직한다고?']],
 'DeOhQMSzm5N':[['비싼 라벨기 대신','이 귀여운 테이프?'],
                 ['라벨기 없이도','이름표가 된다고?'],
                 ['주방 식재료 라벨링','이 테이프 하나로?']],
}


def root(code):return OUT/code/'new-edit-v4-font-cover'
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8')
def read(path):return json.loads(Path(path).read_text('utf-8'))


def runner(code, action, plan, output=None):
 settings=load_settings(); folder=Path(output or root(code));folder.mkdir(parents=True,exist_ok=True)
 request=folder/(action+'-request.json');result=folder/(action+'-result.json')
 write(request,{'action':action,'output_dir':str(folder),'plan':plan})
 with (folder/(action+'.log')).open('w',encoding='utf-8') as log:
  subprocess.run([str(settings.auto_capcut_python),'-X','utf8','-m','auto_capcut.studio_runner',
   '--request',str(request),'--result',str(result)],cwd=settings.auto_capcut_root,stdout=log,stderr=log,check=True)
 value=read(result)
 if value['status']!='completed':raise RuntimeError(value.get('error'))
 return value


def candidate_sheets(code, candidates):
 groups={}
 for c in candidates:groups.setdefault(c['shot_id'],[]).append(c)
 items=list(groups.items())
 for batch in range(0,len(items),6):
  rows=items[batch:batch+6]
  sheet=Image.new('RGB',(3*220,len(rows)*310),'#252525');draw=ImageDraw.Draw(sheet)
  for y,(_,frames) in enumerate(rows):
   for x,f in enumerate(frames):
    im=Image.open(f['frame_path']).convert('RGB');im.thumbnail((216,276))
    sheet.paste(im,(x*220+(220-im.width)//2,y*310+28))
    draw.text((x*220+3,y*310+3),f"{f['shot_id'][5:]} {f['timestamp']:.2f}s",fill='white')
  sheet.save(root(code)/f'cover-candidates-{batch//6+1:02}.jpg')


def prepare(code):
 settings=load_settings();folder=root(code);folder.mkdir(parents=True,exist_ok=True)
 source=OUT/code/'new-edit-v3/timeline.json'
 program="""import json,sys
from pathlib import Path
from auto_capcut.core.studio_typography import default_style
from auto_capcut.core.studio_cover import default_spec
p=json.loads(Path(sys.argv[1]).read_text('utf-8'))
p['caption_style']=default_style()
if p['caption_style']['font_status']!='available': raise ValueError('Requested CapCut font unavailable')
p['cover_spec']=default_spec(p['script_text'],json.loads(sys.argv[3])[0])
p['cover_spec']['copy_candidates']=json.loads(sys.argv[3])
p['cover_spec']['copy_origin']='codex_summary_of_approved_script'
p['cover_spec']['copy_review']={'reviewer':'codex','new_claims_added':False}
p['typography_rework']={'date':'2026-10-10','parent_version':'new-edit-v3','same_script_and_voice':True,'caption_blur_percent':60,'cover_blur_percent':80}
for k in ('rendered_clips','cover_path','sfx_path','output_dir'):p.pop(k,None)
Path(sys.argv[2]).write_text(json.dumps(p,ensure_ascii=False,indent=2),'utf-8')
"""
 subprocess.run([str(settings.auto_capcut_python),'-X','utf8','-c',program,str(source),
  str(folder/'prepared-plan.json'),json.dumps(COPY[code],ensure_ascii=False)],cwd=settings.auto_capcut_root,check=True)
 result=runner(code,'cover-candidates',read(folder/'prepared-plan.json'))
 candidate_sheets(code,result['candidates'])
 print(code,'whole-timeline cover candidates:',len(result['candidates']),flush=True)


def preview(code):
 result=runner(code,'cover-preview',read(root(code)/'prepared-plan.json'))
 write(root(code)/'preview-cover-spec.json',result['cover_spec'])
 print(code,result['cover_path'],flush=True)


def render(code):
 result=runner(code,'render',read(root(code)/'prepared-plan.json'))
 plan=read(result['plan_path']);meta=probe_video(Path(result['preview_path']))
 old=read(OUT/code/'new-edit-v3/timeline.json')
 assert plan['script_text']==old['script_text'] and plan['voice']['sha256']==old['voice']['sha256']
 assert sha256_file(Path(plan['voice']['path']))==plan['voice']['sha256']
 assert [(b['selected_shot_id'],b['source_start'],b['source_end']) for b in plan['beats']]==[(b['selected_shot_id'],b['source_start'],b['source_end']) for b in old['beats']]
 assert meta['width']==1080 and meta['height']==1920 and abs(meta['duration']-old['duration'])<.15
 draft=read(Path(result['portable_draft_path'])/'draft_content.json')
 cover_ids={s['material_id'] for t in draft['tracks'] if t.get('name','').startswith('cover-line-') for s in t['segments']}
 assert len(cover_ids)==2
 values=[]
 for t in draft['materials']['texts']:
  body=json.loads(t['content']);cover=t['id'] in cover_ids
  assert t['font_resource_id']=='6841117356756832776'
  assert abs(t['shadow_smoothing']-(2.4 if cover else 1.8))<1e-5
  assert all(abs(s['shadows'][0]['diffuse']-(.8/6 if cover else .6/6))<1e-5 for s in body['styles'])
  values.append({'role':'cover' if cover else 'caption','text':body['text'],
    'smoothing':t['shadow_smoothing'],'font_resource_id':t['font_resource_id']})
 for track in draft['tracks']:
  if track.get('name','').startswith('cover-line-'):
   assert all(s['target_timerange']=={'start':0,'duration':33333} for s in track['segments'])
 write(root(code)/'verification.json',{'status':'structural_checks_passed','same_script_voice_and_source_windows':True,
  'metadata':meta,'native_texts':values,'visual_review_pending':True})
 print(code,'rendered; exact voice/source windows retained; editable cover and 60/80 native values verified',flush=True)


def attach(code):
 folder=root(code);verified=read(folder/'verification.json')
 if verified.get('visual_review_pending'):raise ValueError('실제 완성본 프레임 검토가 필요합니다.')
 studio=Studio(load_settings(),workers=False)
 state=next(s for s in studio.store.list() if s['shortcode']==code)
 parent=next(e for e in state['edits'] if e['id']=='rework-source-20261010-v3-'+code)
 result=read(folder/'render-result.json')
 edit={k:v for k,v in result.items() if k!='status'}
 edit.update(id='style-cover-20261010-v4-'+code,parent_id=parent['id'],script_id=parent['script_id'],
  voice_id=parent['voice_id'],created=time.time(),status='completed',export_path=result['preview_path'],
  export_verified=True,exported_at=time.time(),export_kind='web_render',registration_deferred=True,
  registration_note='십대 폰트·본문 흐림 60%·두 줄 썸네일 흐림 80% · 새 편집본',
  typography_rework=read(result['plan_path'])['typography_rework'])
 def change(s,db):
  if not any(e['id']==edit['id'] for e in s['edits']):s['edits'].append(edit)
  s.update(edit_id=edit['id'],status='completed',message='십대 폰트와 하이라이트 썸네일 적용 완료')
  studio.store.event(db,s['id'],'typography_cover_rework',{'edit_id':edit['id']})
 studio.store.change(state['id'],change)
 print(code,'attached new version; older edits retained',flush=True)


def qa(code):
 folder=root(code);result=read(folder/'render-result.json');video=result['preview_path']
 old=OUT/code/'new-edit-v3/preview.mp4'
 if not old.is_file():
  parent=next(e for s in Studio(load_settings(),workers=False).store.list() if s['shortcode']==code
              for e in s['edits'] if e['id']=='rework-source-20261010-v3-'+code)
  old=Path(parent['export_path'])
 def ff(args):return subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',*args],capture_output=True,text=True,check=True).stdout.strip()
 hashes=[ff(['-i',str(p),'-map','0:a:0','-f','hash','-hash','sha256','-']) for p in (old,video)]
 # Carry the previous approved audio stream, including its opening effect.
 # Re-encoding an unchanged mix may differ; typography never requires it.
 if hashes[0]!=hashes[1]:
  for target in (Path(video),Path(result['clean_preview_path'])):
   temporary=target.with_name(target.stem+'-audio-preserved.mp4')
   ff(['-i',str(target),'-i',str(old),'-map','0:v:0','-map','1:a:0','-c','copy','-movflags','+faststart',str(temporary)])
   temporary.replace(target)
  hashes[1]=ff(['-i',video,'-map','0:a:0','-f','hash','-hash','sha256','-'])
 assert hashes[0]==hashes[1], 'Audio changed unexpectedly'
 counts=[]
 for p in (old,video):
  data=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=nb_read_frames,r_frame_rate','-of','json',str(p)],text=True))
  counts.append(data['streams'][0])
 assert counts[0]==counts[1], 'Frame count changed unexpectedly'
 ff(['-i',video,'-f','null','-'])
 duration=read(folder/'verification.json')['metadata']['duration']
 times=[0,1/30]+[duration*(i+.5)/12 for i in range(12)]
 sheet=Image.new('RGB',(4*270,4*500),'#222222');draw=ImageDraw.Draw(sheet)
 frames=[]
 for index,t in enumerate(times):
  frame=folder/f'qa-frame-{index:02}.png';ff(['-ss',str(t),'-i',video,'-frames:v','1',str(frame)])
  frames.append(str(frame));im=Image.open(frame).convert('RGB');im.thumbnail((270,480))
  x=index%4*270;y=index//4*500;sheet.paste(im,(x,y+20));draw.text((x+4,y+2),f'{t:.3f}s',fill='white')
 sheet.save(folder/'qa-contact.jpg')
 v=read(folder/'verification.json');v.update(audio_pcm_hash=hashes[1],same_decoded_audio=True,
  same_frame_count=True,video_stream=counts[1],full_decode_passed=True,review_frames=frames)
 write(folder/'verification.json',v)
 print(code,'audio identical, frame count identical, complete decode passed',flush=True)


if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['prepare','preview','render','qa','attach']);parser.add_argument('--code',choices=CODES);args=parser.parse_args()
 bins=list(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
 os.environ['PATH']=str(bins[0])+os.pathsep+os.environ['PATH']
 for code in ([args.code] if args.code else CODES):globals()[args.phase](code)
