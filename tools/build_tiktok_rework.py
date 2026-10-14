"""New bounded review clips and versioned renders; no worker or CapCut launch."""
import argparse,copy,json,time,subprocess,os
from pathlib import Path
from PIL import Image,ImageDraw
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.source_quality import sha256_file
from hotpost.source_finder import probe_video
from hotpost.source_presentation import POLICY,review_scope
from tools.rework_tiktok_batch import ROOT,save,QUERIES
from tools.build_source_rework import metrics
from tools.build_selected_three import state,read
CODES=tuple(QUERIES)
EXAMPLE_CODE='DeRFXHpEwck'
# Reviewed original scenes; each derivative is reviewed again before approval.
CLIPS={
CODES[0]:[
 ('clamp','7534760939048979717',11,16,[0,.22,1,1],'기둥 연결부를 손으로 고정하는 시연'),
 ('fabric','7534760939048979717',17,23,[0,.22,1,1],'침대 텐트 천을 프레임에 씌우는 시연'),
 ('close','7534760939048979717',43,49,[0,.22,1,1],'침대 커튼을 닫아 안쪽을 가리는 장면'),
 ('blanket','7534760939048979717',50,56,[0,.22,1,1],'텐트 안에 이불을 넣는 장면'),
 ('pocket','7534760939048979717',56,62,[0,.18,1,1],'안쪽 포켓에 책을 넣는 장면'),
 ('reading','7534760939048979717',65,68,[0,.18,1,1],'텐트 안에서 조명을 켜고 책을 보는 장면'),
 ('mesh','7537346959951006981',19,24,[0,0,1,.78],'망 부분 뒤에서 손을 움직이는 장면'),
 ('shade','7537346959951006981',24,29,[0,0,1,.78],'천을 닫고 불빛을 가리는 시연'),
 ('sleep','7537346959951006981',30,35,[0,0,1,.78],'분홍 침대 텐트 안에 누워 있는 장면'),
 ('lamp','7536121210812353797',29,34,[0,.22,1,1],'침대 텐트 안에서 조명을 쓰는 장면')],
CODES[2]:[
 ('black-detail','7585789877762018568',0,6,None,'검은 노스페이스 패딩의 전면과 지퍼를 보여줌'),
 ('lining','7585789877762018568',6,11,None,'패딩 안쪽과 목 부분을 손으로 보여줌'),
 ('beige','7585789877762018568',11,14,None,'베이지색 패딩 전면과 후드'),
 ('black-fit','7585789877762018568',22,26,None,'거울 앞에서 검은 패딩 착용 모습'),
 ('beige-fit','7585789877762018568',26,29.4,None,'베이지 패딩 착용 모습'),
 ('kid-front','7450841635404975393',1,5,None,'아이가 검은 패딩을 입고 앞면을 보여줌'),
 ('kid-back','7450841635404975393',6,10,None,'아이가 거울을 보며 패딩 뒷면을 보여줌'),
 ('kid-fit','7450841635404975393',12,16,None,'키즈 패딩 착용과 표정'),
 ('purple','7548142357628275971',2,7,None,'보라색 키즈 패딩 전면과 후드')],
}
def root(c):return ROOT/c/'final'
def boundary(c,action,**kw):
 s=load_settings();r=root(c);r.mkdir(exist_ok=True);req=r/(action+'-request.json');res=r/(action+'-result.json')
 save(req,dict(action=action,output_dir=str(r),**kw))
 with (r/(action+'.log')).open('w',encoding='utf-8') as log:subprocess.run([str(s.auto_capcut_python),'-X','utf8','-m','auto_capcut.studio_runner','--request',str(req),'--result',str(res)],cwd=s.auto_capcut_root,stdout=log,stderr=log,check=True)
 v=read(res);assert v['status']=='completed',v;return v
def clips(c):
 rows=read(ROOT/c/'discovery.json')['candidates'];r=root(c);r.mkdir(exist_ok=True);out=[]
 if (ROOT/c/'supplemental-sources.json').exists():rows+=read(ROOT/c/'supplemental-sources.json')
 defs=CLIPS.get(c) or read(ROOT/c/'clip-definitions.json')
 for name,vid,start,end,crop,observation in defs:
  row=next(x for x in rows if x['url'].endswith('/'+vid));original=Path(row['path']);target=r/'clips'/(name+'.mp4');target.parent.mkdir(exist_ok=True)
  vf='scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=30'
  if crop:
   w,h=row['video_meta']['width'],row['video_meta']['height'];x,y,x2,y2=crop
   cw=int(w*(x2-x))//2*2;ch=int(h*(y2-y))//2*2;cx=int(w*x)//2*2;cy=int(h*y)//2*2
   vf=f'crop={cw}:{ch}:{cx}:{cy},'+vf
  if c==EXAMPLE_CODE and name in ('capacity','pocket-end'):
   vf+=',split[base][txt];[txt]crop=iw:ih*0.2:0:ih*0.8,boxblur=24:2[blur];[base][blur]overlay=0:H-h'
  subprocess.run(['ffmpeg','-v','error','-y','-ss',str(start),'-t',str(end-start),'-i',str(original),'-an','-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','18',str(target)],check=True)
  meta=probe_video(target);frames=[]
  for i,ratio in enumerate((.05,.35,.65,.95)):
   p=target.with_name(name+f'-{i}.jpg');t=(meta['duration']-.1)*ratio
   subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(target),'-frames:v','1',str(p)],check=True);frames.append({'path':str(p),'sha256':sha256_file(p),'timestamp':t})
  out.append(dict(id='tiktok-'+c+'-'+name,name=name,path=str(target),sha256=sha256_file(target),video_meta=meta,original_sha256=sha256_file(original),original_interval={'start':start,'end':end},original_path=str(original),url=row.get('original_url') or row['url'],provider='youtube' if row.get('outside_tiktok_discovery') else 'tiktok',rights='unknown-check-before-reuse',source_role='context' if c==EXAMPLE_CODE else 'core',proposed_observation=observation,evidence_frames=frames,pending_visual_review=True,crop=crop))
 save(r/'proposed-sources.json',out)
 for offset in range(0,len(out),5):
  batch=out[offset:offset+5];sheet=Image.new('RGB',(720,345*len(batch)),'#222');d=ImageDraw.Draw(sheet)
  for j,s in enumerate(batch):
   for k,f in enumerate(s['evidence_frames']):
    im=Image.open(f['path']);im.thumbnail((180,320));sheet.paste(im,(180*k,345*j+25));d.text((180*k+2,345*j+2),f"{s['name']} {f['timestamp']:.1f}",fill='white')
  sheet.save(r/f'clip-review-{offset//5+1}.jpg')
 print(c,'clips ready',flush=True)
def analyze(c):
 r=root(c);sources=read(r/'proposed-sources.json');assert (r/'clips-reviewed.json').exists()
 for s in sources:
  s.update(pending_visual_review=False,source_quality='reviewed-portrait',editing_eligible=True,blur_required=False,watermark_masks=[],presentation_review_required=False,relevance_review_required=False)
  limits=['다른 촬영자의 유사 기능 또는 같은 브랜드 제품. 원본과 정확한 모델·SKU 일치는 미확인. 가격·재고·AS를 이 장면이 입증하지 않음.']
  if c==EXAMPLE_CODE:limits.append('원본의 다이소 6매 벨크로 미니 홀더 실물이 아님. 작은 포켓 활용 및 벨크로 구조 예시로만 사용. 동일 제품 시연으로 승인하지 않음.')
  s['functional_review']={'reviewed':True,'source_sha256':s['sha256'],'same_core_function':s['source_role']=='core','context_usable':True,'context_usage_limits':limits,'observed_actions':[s['proposed_observation']],'evidence_frames':[f['path'] for f in s['evidence_frames']],'reviewer':'codex_session_visual_review'}
  s['visual_review']={'reviewer':'codex_session_visual_review','reviewed_at':time.time(),'scope':'four decoded samples of bounded portrait clip','observation':s['proposed_observation'],'evidence_frames':s['evidence_frames']}
  s['presentation_review']={'policy':POLICY,'reviewed':True,'source_sha256':s['sha256'],'scope':review_scope(s),'usable':True,'quality_usable':True,'action_preserved':True,'observations':[s['proposed_observation']],'evidence_frames':s['evidence_frames'],'reviewer':'codex_session_visual_review'}
 save(r/'approved-sources.json',sources);save(r/'baseline-state.json',state(c));script=read(r/'script.json');voice=read(r/'voice.json')
 p=boundary(c,'analyze',sources=sources,script=script,voice=voice,thumbnail_lines=script['thumbnail_lines'])['plan']
 p['shots']=[dict(id='shot-'+s['name'],source_id=s['id'],path=s['path'],sha256=s['sha256'],start=0,end=s['video_meta']['duration'],frames=[f['path'] for f in s['evidence_frames']],observation=s['proposed_observation'],source_role=s['source_role'],context_usage_limits=s['functional_review']['context_usage_limits'],evidence_status='actual-decoded-frame-review') for s in sources]
 if c==EXAMPLE_CODE:p['source_notice']='유사 제품 활용 예시 · 동일 제품 아님'
 p['cover_font_style']={'font_path':str(load_settings().auto_capcut_root/'auto_capcut/assets/fonts/DoHyeon-Regular.ttf'),'font_family':'Do Hyeon','font_title':'도현','font_weight':700,'font_resource_id':'','font_status':'available'}
 save(r/'prepared-plan.json',p);print(c,json.dumps([(i+1,b['text'],round(b['start'],2),round(b['end'],2)) for i,b in enumerate(p['beats'])],ensure_ascii=False),flush=True)
def select(c):
 r=root(c);p=read(r/'prepared-plan.json');groups=read(r/'groups.json')
 for first,last,name in groups:
  shot=next(s for s in p['shots'] if s['id']=='shot-'+name)
  for b in p['beats'][first-1:last]:b.update(options=[{'shot_id':shot['id'],'relation':'context' if shot['source_role']=='context' else 'direct','reason':shot['observation'],'reviewed':True}],selected_shot_id=shot['id'],emphasis=0,needs_review=False)
  assert p['beats'][last-1]['end']-p['beats'][first-1]['start']<=shot['end']+.001
 s=load_settings();save(r/'selection-input.json',p)
 program="from pathlib import Path;import sys,json;from auto_capcut.core.studio_timeline import select_shots;p=select_shots(json.loads(Path(sys.argv[1]).read_text('utf-8')));Path(sys.argv[2]).write_text(json.dumps(p,ensure_ascii=False,indent=2),'utf-8')"
 subprocess.run([str(s.auto_capcut_python),'-X','utf8','-c',program,str(r/'selection-input.json'),str(r/'prepared-plan.json')],cwd=s.auto_capcut_root,check=True)
 p=read(r/'prepared-plan.json');audit=metrics(p);assert abs(audit['replayed_seconds'])<.08,audit;save(r/'selection-audit.json',audit)
 result=boundary(c,'cover-candidates',plan=p)
 items=result['candidates'];sheet=Image.new('RGB',(810,505*((len(items)+2)//3)),'#222');d=ImageDraw.Draw(sheet)
 for i,f in enumerate(items):
  im=Image.open(f['frame_path']);im.thumbnail((270,480));x=i%3*270;y=i//3*505;sheet.paste(im,(x,y+25));d.text((x,y+2),f"{f['shot_id']} {f['timestamp']:.2f}",fill='white')
 sheet.save(r/'cover-candidates.jpg');print(c,audit,flush=True)
def render(c):
 r=root(c);p=read(r/'prepared-plan.json');res=boundary(c,'render',plan=p);p=read(res['plan_path']);meta=probe_video(Path(res['preview_path']));audit=metrics(p)
 assert abs(audit['replayed_seconds'])<.08;assert (meta['width'],meta['height'])==(1080,1920);assert sha256_file(Path(p['voice']['path']))==p['voice']['sha256']
 draft=read(Path(res['portable_draft_path'])/'draft_content.json');cover={s['material_id'] for t in draft['tracks'] if t.get('name','').startswith('cover-line-') for s in t['segments']};assert len(cover)==2
 for text in draft['materials']['texts']:
  if text['id'] not in cover:assert text['font_resource_id']=='6841117356756832776'
  assert abs(text['shadow_smoothing']-(2.4 if text['id'] in cover else 1.8))<1e-5
 for t in draft['tracks']:
  if t.get('name','').startswith('cover-line-'):assert all(s['target_timerange']=={'start':0,'duration':33333} for s in t['segments'])
 assert p['cover_spec']['font']['font_family']=='Do Hyeon'
 subprocess.run(['ffmpeg','-v','error','-xerror','-i',res['preview_path'],'-f','null','-'],check=True)
 times=[0,1/30]+[p['duration']*(i+.5)/10 for i in range(10)];frames=[]
 for batch in range(0,len(times),6):
  sheet=Image.new('RGB',(810,1010),'#222');d=ImageDraw.Draw(sheet)
  for k,t in enumerate(times[batch:batch+6]):
   f=r/f'qa-{batch+k:02}.jpg';subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',res['preview_path'],'-frames:v','1',str(f)],check=True);frames.append(str(f));im=Image.open(f);im.thumbnail((270,480));x=k%3*270;y=k//3*505;sheet.paste(im,(x,y+25));d.text((x,y+2),f'{t:.3f}s',fill='white')
  sheet.save(r/f'qa-sheet-{batch//6+1}.jpg')
 save(r/'verification.json',dict(metrics=audit,metadata=meta,full_decode_passed=True,font_and_cover_verified=True,review_frames=frames,visual_review_pending=True));print(c,'rendered',audit,flush=True)
def attach(c):
 r=root(c);v=read(r/'verification.json');assert not v['visual_review_pending'];res=read(r/'render-result.json');script=read(r/'script.json');voice=read(r/'voice.json');st=read(r/'baseline-state.json');p=read(res['plan_path']);studio=Studio(load_settings(),workers=False)
 edit={k:x for k,x in res.items() if k!='status'};edit.update(id='tiktok-rework-20261011-'+c,script_id=script['id'],voice_id=voice['id'],created=time.time(),status='completed',export_path=res['preview_path'],export_verified=True,exported_at=time.time(),export_kind='web_render',registration_deferred=True,source_diversity=v['metrics'])
 if c==EXAMPLE_CODE:edit.update(review_draft=True,source_coverage_complete=False,source_limit='동일 제품 핵심 소스 미확보. 유사 제품 활용·구조 예시만 포함.')
 def change(s,db):
  for key,obj in [('scripts',script),('voices',voice),('edits',edit)]:
   if not any(x['id']==obj['id'] for x in s[key]):s[key].append(obj)
  s['sources'].extend(x for x in p['sources'] if not any(y['id']==x['id'] for y in s['sources']))
  s.update(script_id=script['id'],voice_id=voice['id'],edit_id=edit['id'],status='completed',message='TikTok 소스·새 대본·도현 썸네일로 재제작 완료',error='',progress=100)
  s.setdefault('automation',{}).update(active=False,stage='completed',completed_at=time.time())
  if c==EXAMPLE_CODE:
   s.update(status='draft_review',message='유사 제품 활용 예시본 생성. 동일 제품 핵심 소스는 미확보.')
   s['automation'].update(stage='source_wait',source_coverage_complete=False)
  s['script_variants']=next(x for x in read(ROOT/'writing/variants.json')['items'] if x['code']==c)
  from hotpost.studio_workflow import snapshot
  run=snapshot(s);run['inputs']['source_ids']=[x['id'] for x in p['sources']];run['artifacts']['sources']=copy.deepcopy(p['sources']);run.update(status='review' if c==EXAMPLE_CODE else 'completed',completed=time.time())
  if c!=EXAMPLE_CODE:s['latest_completed_run_id']=run['id']
  s['reviewed_source_pool']={'scope':'actual reviewed portrait clips; same original intervals not counted twice','clip_seconds':sum(x['video_meta']['duration'] for x in p['sources']),'independent_original_videos':v['metrics']['independent_original_videos'],'exact_reference_product_match':False}
  studio.store.event(db,s['id'],'tiktok_rework_completed',{'edit_id':edit['id'],'metrics':v['metrics']})
 studio.store.change(st['id'],change);print(c,'attached',flush=True)
def main():
 a=argparse.ArgumentParser();a.add_argument('phase',choices=['clips','analyze','select','render','attach']);a.add_argument('--code',choices=CODES);args=a.parse_args()
 bins=list(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'));os.environ['PATH']=str(bins[0])+os.pathsep+os.environ['PATH']
 for c in ([args.code] if args.code else CODES):globals()[args.phase](c)
if __name__=='__main__':main()
