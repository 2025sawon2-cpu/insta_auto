"""A scoped, evidence-backed three-video review batch, without global workers."""
import argparse,copy,json,os,subprocess,time
from pathlib import Path
from PIL import Image,ImageDraw
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.source_quality import sha256_file
from hotpost.source_presentation import POLICY,review_scope
from hotpost.source_finder import probe_video
from tools.build_source_rework import metrics

CODES=('DeRIBMYzn0x','DeRFXHpEwck','DeJ7hD6zsnR')
BASE=Path(__file__).resolve().parents[1]/'data/selected-three-quality'
LINES={CODES[0]:['침대에 텐트를 치면','불빛이 줄어든다고?'],CODES[1]:['작은 파일 하나로','가방 속이 달라져?'],CODES[2]:['패딩 한 벌 살 돈으로','온 가족 겨울 준비?']}
def read(p):return json.loads(Path(p).read_text('utf-8'))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2),'utf-8')
def root(c):return BASE/c/'final-v1'
def state(c):return next(s for s in Studio(load_settings(),workers=False).store.list() if s['shortcode']==c)
def boundary(c,action,**kw):
 s=load_settings();r=root(c);r.mkdir(parents=True,exist_ok=True)
 req=r/(action+'-request.json');res=r/(action+'-result.json')
 write(req,dict(action=action,output_dir=str(r),**kw))
 with (r/(action+'.log')).open('w',encoding='utf-8') as log:
  subprocess.run([str(s.auto_capcut_python),'-X','utf8','-m','auto_capcut.studio_runner','--request',str(req),'--result',str(res)],cwd=s.auto_capcut_root,stdout=log,stderr=log,check=True)
 value=read(res);assert value['status']=='completed',value
 return value
def analyze(c):
 st=state(c);r=root(c);r.mkdir(parents=True,exist_ok=True);write(r/'baseline-state.json',st)
 kit=BASE/c/('proposed-clips-v3' if c==CODES[1] else 'proposed-clips-v2')
 sources=[]
 for x in read(kit/'proposed.json'):
  if c==CODES[2] and x['name'] in ('clip-06','clip-08'):continue
  assert sha256_file(Path(x['path']))==x['sha256']
  for f in x['evidence_frames']:assert sha256_file(Path(f['path']))==f['sha256']
  context=(c==CODES[0] and x['name']=='clip-05') or (c==CODES[1] and x['name'] in ('clip-06','clip-07'))
  limits=['확인한 구간의 동작만 사용. 레퍼런스와 정확한 제품·SKU·브랜드 일치는 미확인. 가격·수량·AS는 이 소스가 입증하지 않음.']
  if c==CODES[1]:limits.append('다이소 A7 실물 소스가 아닌 유사 파일 제품 및 정리 상황. 크기·용량을 동일 제품처럼 표시하지 않음.')
  x.update(pending_visual_review=False,provider='youtube',source_role='context' if context else 'core',source_quality='clean-source',editing_eligible=True,blur_required=False,watermark_masks=[],presentation_review_required=False,relevance_review_required=False)
  x['visual_review']={'reviewer':'codex_session_visual_review','reviewed_at':time.time(),'scope':'four uniformly distributed decoded frames of this bounded derivative; not the entire original','observation':x['proposed_observation'],'evidence_frames':x['evidence_frames'],'quality_limit':'Some landscape sources use blurred padding; some footage is soft.'}
  x['functional_review']={'reviewed':True,'source_sha256':x['sha256'],'same_core_function':not context,'context_usable':True,'context_usage_limits':limits,'observed_actions':[x['proposed_observation']],'evidence_frames':[f['path'] for f in x['evidence_frames']],'reviewer':'codex_session_visual_review'}
  x['presentation_review']={'policy':POLICY,'reviewed':True,'source_sha256':x['sha256'],'scope':review_scope(x),'usable':True,'quality_usable':True,'action_preserved':True,'observations':[x['proposed_observation']],'evidence_frames':x['evidence_frames'],'reviewer':'codex_session_visual_review'}
  sources.append(x)
 write(kit/'approved.json',sources)
 script=next(x for x in st['scripts'] if x['id']==st['script_id']);voice=next(x for x in st['voices'] if x['id']==st['voice_id'])
 result=boundary(c,'analyze',sources=sources,script=script,voice=voice,thumbnail_lines=LINES[c]);write(r/'analysis.json',result['plan'])
 print(c,'analysis complete',flush=True)
def prepare(c):
 p=read(root(c)/'analysis.json');p['shots']=[]
 for s in p['sources']:
  p['shots'].append(dict(id='shot-'+s['name'],source_id=s['id'],path=s['path'],sha256=s['sha256'],start=0,end=s['video_meta']['duration'],frames=[f['path'] for f in s['evidence_frames']],observation=s['proposed_observation'],source_role=s['source_role'],context_usage_limits=s['functional_review']['context_usage_limits'],evidence_status='actual-decoded-frame-review'))
 write(root(c)/'prepared-plan.json',p)
 print(c,'cues',json.dumps([(i+1,b['text'],round(b['start'],2),round(b['end'],2)) for i,b in enumerate(p['beats'])],ensure_ascii=False),flush=True)
def select(c):
 p=read(root(c)/'prepared-plan.json');groups=read(root(c)/'groups.json')
 for first,last,name in groups:
  shot=next(s for s in p['shots'] if s['id']=='shot-'+name);src=next(s for s in p['sources'] if s['id']==shot['source_id'])
  for b in p['beats'][first-1:last]:
   b.update(options=[dict(shot_id=shot['id'],relation='direct' if src['source_role']=='core' else 'context',reason=src['proposed_observation'],reviewed=True)],selected_shot_id=shot['id'],emphasis=0,needs_review=False)
  needed=p['beats'][last-1]['end']-p['beats'][first-1]['start']
  assert needed<=shot['end']-shot['start']+1e-6,(c,name,needed)
 s=load_settings();write(root(c)/'selection-input.json',p)
 program="from pathlib import Path; import json,sys; from auto_capcut.core.studio_timeline import select_shots; p=select_shots(json.loads(Path(sys.argv[1]).read_text('utf-8'))); Path(sys.argv[2]).write_text(json.dumps(p,ensure_ascii=False,indent=2),'utf-8')"
 subprocess.run([str(s.auto_capcut_python),'-X','utf8','-c',program,str(root(c)/'selection-input.json'),str(root(c)/'prepared-plan.json')],cwd=s.auto_capcut_root,check=True)
 p=read(root(c)/'prepared-plan.json');audit=metrics(p);assert audit['replayed_seconds']<.001,audit
 write(root(c)/'selection-audit.json',audit);result=boundary(c,'cover-candidates',plan=p)
 from tools.build_typography_rework import candidate_sheets
 # This batch owns its sheets; no old-video paths are touched.
 rows={}
 for x in result['candidates']:rows.setdefault(x['shot_id'],[]).append(x)
 items=list(rows.items())
 for j in range(0,len(items),6):
  batch=items[j:j+6];sheet=Image.new('RGB',(660,len(batch)*410),'#222222');d=ImageDraw.Draw(sheet)
  for y,(_,frames) in enumerate(batch):
   for k,f in enumerate(frames):
    im=Image.open(f['frame_path']).convert('RGB');im.thumbnail((216,384));sheet.paste(im,(k*220,y*410+25));d.text((k*220+2,y*410+2),f"{f['shot_id']} {f['timestamp']:.2f}",fill='white')
  sheet.save(root(c)/f'cover-sheet-{j//6+1}.jpg')
 print(c,audit,flush=True)
def preview(c):boundary(c,'cover-preview',plan=read(root(c)/'prepared-plan.json'));print(c,'cover preview ready',flush=True)
def render(c):
 result=boundary(c,'render',plan=read(root(c)/'prepared-plan.json'));p=read(result['plan_path']);meta=probe_video(Path(result['preview_path']));audit=metrics(p)
 assert audit['replayed_seconds']<.001 and not p['footage_diversity']['frozen_beats'];assert meta['width']==1080 and meta['height']==1920
 assert sha256_file(Path(p['voice']['path']))==p['voice']['sha256']
 draft=read(Path(result['portable_draft_path'])/'draft_content.json');cover_ids={s['material_id'] for t in draft['tracks'] if t.get('name','').startswith('cover-line-') for s in t['segments']}
 assert len(cover_ids)==2
 for text in draft['materials']['texts']:
  assert text['font_resource_id']=='6841117356756832776';assert abs(text['shadow_smoothing']-(2.4 if text['id'] in cover_ids else 1.8))<1e-5
 for track in draft['tracks']:
  if track.get('name','').startswith('cover-line-'):assert all(s['target_timerange']=={'start':0,'duration':33333} for s in track['segments'])
 subprocess.run(['ffmpeg','-v','error','-i',result['preview_path'],'-f','null','-'],check=True)
 frames=[];times=[0,1/30]+[p['duration']*(i+.5)/10 for i in range(10)]
 for batch in range(0,len(times),6):
  subset=times[batch:batch+6];sheet=Image.new('RGB',(3*270,2*505),'#222222');d=ImageDraw.Draw(sheet)
  for k,t in enumerate(subset):
   frame=root(c)/f'qa-{batch+k:02}.jpg';subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',result['preview_path'],'-frames:v','1',str(frame)],check=True);frames.append(str(frame))
   im=Image.open(frame);im.thumbnail((270,480));x=k%3*270;y=k//3*505;sheet.paste(im,(x,y+25));d.text((x+2,y+2),f'{t:.3f}s',fill='white')
  sheet.save(root(c)/f'qa-sheet-{batch//6+1}.jpg')
 write(root(c)/'verification.json',dict(metrics=audit,metadata=meta,full_decode_passed=True,font_and_cover_verified=True,review_frames=frames,visual_review_pending=True))
 print(c,'rendered',audit,flush=True)
def attach(c):
 v=read(root(c)/'verification.json');assert not v['visual_review_pending'];result=read(root(c)/'render-result.json');st=read(root(c)/'baseline-state.json');studio=Studio(load_settings(),workers=False)
 edit={k:x for k,x in result.items() if k!='status'};edit.update(id='selected-three-final-v1-'+c,script_id=st['script_id'],voice_id=st['voice_id'],created=time.time(),status='completed',export_path=result['preview_path'],export_verified=True,exported_at=time.time(),export_kind='web_render',registration_deferred=True,source_diversity=v['metrics'])
 p=read(result['plan_path'])
 def change(s,db):
  assert s['script_id']==st['script_id'] and s['voice_id']==st['voice_id']
  if not any(e['id']==edit['id'] for e in s['edits']):s['edits'].append(edit)
  s['sources'].extend(x for x in p['sources'] if not any(y['id']==x['id'] for y in s['sources']))
  s.update(edit_id=edit['id'],status='completed',message='새 소스 구간·십대 폰트·1프레임 썸네일 적용 완료',error='',progress=100)
  s.setdefault('automation',{}).update(active=False,stage='completed',completed_at=time.time())
  from hotpost.studio_workflow import snapshot
  run=snapshot(s);run['inputs']['source_ids']=[x['id'] for x in p['sources']];run['artifacts']['sources']=copy.deepcopy(p['sources']);run.update(status='completed',completed=time.time())
  s['latest_completed_run_id']=run['id']
  s['reviewed_source_pool']={'scope':'manually inspected bounded clips; overlapping original intervals are not counted twice','clip_seconds':sum(x['video_meta']['duration'] for x in p['sources']),'independent_original_videos':len({x['original_sha256'] for x in p['sources']}),'exact_reference_product_match':False}
  s['source_search']={'status':'done','progress':100,'message':'이번 3편용 소스 검토·편집 완료. 원본과 정확한 제품 일치는 미확인.'}
  db.execute("UPDATE jobs SET status='superseded',updated=? WHERE task_id=? AND status IN ('queued','running')",(time.time(),s['id']))
  studio.store.event(db,s['id'],'selected_three_completed',dict(edit_id=edit['id'],metrics=v['metrics']))
 studio.store.change(st['id'],change);print(c,'attached',flush=True)
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('phase',choices=['analyze','prepare','select','preview','render','attach']);a.add_argument('--code',choices=CODES);args=a.parse_args()
 bins=list(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'));os.environ['PATH']=str(bins[0])+os.pathsep+os.environ['PATH']
 for c in ([args.code] if args.code else CODES):globals()[args.phase](c)
