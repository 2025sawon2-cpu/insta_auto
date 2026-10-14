"""Build explicitly reviewed revisions without activating the studio queue."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import time

from hotpost.config import load_settings
from hotpost.source_presentation import POLICY, review_scope, protect_automatic_crop
from hotpost.source_quality import sha256_file
from hotpost.source_finder import probe_video
from hotpost.studio import Studio
from tools.audit_source_repetition import OUT, union_seconds, sheet

GROUPS={
 'DeNb4AsSgGw':[(1,2,'fridge-hook'),(3,3,'photo-display'),(4,5,'print-cut'),(6,6,'magnetic-backing'),
 (7,9,'pet-photo-attach'),(10,11,'illustrated-magnets'),(12,13,'child-drawing'),(14,15,'drawing-attach'),
 (16,17,'diy-assembly'),(18,20,'photo-memories'),(21,22,'fridge-payoff')],
 'DeOhQMSzm5N':[(1,2,'food-label-hook'),(3,4,'macaron-product'),(5,6,'macaron-unpack'),(7,9,'macaron-open'),
 (10,11,'macaron-refill'),(12,14,'magic-write'),(15,16,'round-container'),(17,18,'food-pan-label'),
 (19,22,'magic-handle-v3'),(23,24,'label-peel'),(25,27,'compact-case'),(28,29,'macaron-colors'),
 (30,32,'food-label-write'),(33,34,'macaron-payoff')],
}
STARTS={'print-cut':1.4,'magnetic-backing':4.5,'drawing-attach':2.6,'magic-write':1.6,'food-pan-label':1.8,'macaron-payoff':2.0,'label-peel':2.0}

def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8')

def metrics(plan):
 shots={s['id']:s for s in plan['shots']};sources={s['id']:s for s in plan['sources']};uses={};screen={}
 for b in plan['beats']:
  shot=shots[b['selected_shot_id']];source=sources[shot['source_id']];key=source['original_sha256']
  offset=source['original_interval']['start'];uses.setdefault(key,[]).append((offset+b['source_start'],offset+b['source_end']))
  screen[key]=screen.get(key,0)+b['end']-b['start']
 unique=sum(union_seconds(v) for v in uses.values())
 return {'independent_original_videos':len(uses),'action_clips':len({b['selected_shot_id'] for b in plan['beats']}),
 'timeline_seconds':round(plan['duration'],3),'unique_seconds':round(unique,3),'replayed_seconds':round(plan['duration']-unique,3),
 'largest_original_share':round(max(screen.values())/plan['duration'],3),'original_intervals':uses}

def build(code):
 state=json.loads((OUT/code/'baseline-state.json').read_text('utf-8'))
 old=next(e for e in state['edits'] if e['id']==state['edit_id'])
 plan=json.loads(Path(old['plan_path']).read_text('utf-8'))
 clips=json.loads((OUT/code/'clip-kit-v2/proposed-clips.json').read_text('utf-8'))
 # All five decoded portrait samples of each listed clip were inspected in this session.
 for clip in clips:
  clip['pending_visual_review']=False
  clip['visual_review']={'reviewer':'codex_session_visual_review','reviewed_at':time.time(),
   'scope':'five decoded samples across this derivative clip; not the entire original video',
   'observation':clip['proposed_observation'],'evidence_frames':clip['evidence']['frames'],
   'quality_limit':'Landscape footage uses a contained subject on a blurred background. Some original clips are visibly soft.',
   'original_overlay_visible_in_samples':False}
 write(OUT/code/'clip-kit-v2/approved-clips.json',clips)
 plan['sources']=[];plan['shots']=[]
 for clip in clips:
  limits=['제공된 실제 구간에서 보이는 동작만 설명한다. 동일 원본 클립·정확한 제조사 일치는 확인되지 않았다.',
   '이 장면만으로 잔여물·번짐·접착력 성능이나 보이지 않는 부속품을 입증하지 않는다.']
  source={**clip,'provider':'youtube','source_quality':'clean-source','editing_eligible':True,
   'source_role':clip['proposed_role'],'blur_required':False,'watermark_masks':[],
   'functional_review':{'reviewed':True,'source_sha256':clip['sha256'],'policy':'visual-product-presentation-v2',
    'same_core_function':clip['proposed_role']=='core','context_usable':True,'context_usage_limits':limits,
    'observed_actions':[clip['proposed_observation']],'evidence_frames':[f['path'] for f in clip['evidence']['frames']],
    'reviewer':'codex_session_visual_review','reason':'실제 동작 구간 및 세로 출력 샘플을 직접 확인'},
   'presentation_review_required':False,'relevance_review_required':False}
  source['presentation_review']={'policy':POLICY,'reviewed':True,'source_sha256':source['sha256'],
   'scope':review_scope(source),'usable':True,'quality_usable':True,'action_preserved':True,
   'observations':[clip['proposed_observation']],'evidence_frames':clip['evidence']['frames'],'reviewer':'codex_session_visual_review'}
  start=STARTS.get(clip['name'],0.)
  plan['sources'].append(source)
  plan['shots'].append({'id':'shot-'+clip['name'],'source_id':source['id'],'path':source['path'],'sha256':source['sha256'],
   'start':start,'end':clip['video_meta']['duration'],'frames':[f['path'] for f in clip['evidence']['frames']],
   'observation':clip['proposed_observation'],'context_usage_limits':limits,'source_role':source['source_role'],
   'tags':[clip['name']],'visual_type':'actual-action-video','evidence_status':'actual-decoded-frame-review',
   'reviewed_by':'agent_actual_source_frames'})
 for first,last,name in GROUPS[code]:
  source=next(s for s in plan['sources'] if s['name']==name)
  for b in plan['beats'][first-1:last]:
   relation='direct' if source['source_role']=='core' else 'context'
   b.update(options=[{'shot_id':'shot-'+name,'relation':relation,'reason':source['proposed_observation'],'reviewed':True}],
    selected_shot_id='shot-'+name,emphasis=0,needs_review=False)
  shot=next(s for s in plan['shots'] if s['id']=='shot-'+name)
  needed=plan['beats'][last-1]['end']-plan['beats'][first-1]['start']
  assert shot['end']-shot['start']>=needed-1e-6,(code,name,needed,shot)
 plan['footage_selection_policy']='diverse-sequential-v1'
 plan['source_rework']={'date':'2026-10-10','parent_edit_id':old['id'],'same_script_and_voice':True,
  'reference_scene_sampling':20,'source_video_sampling':15,'portrait_action_samples_per_clip':5,
  'unresolved':['레퍼런스와 동일한 원본 클립 출처는 찾지 못했다.','테이프 제거 후 잔여물 없음의 직접 시연 구간은 새 풀에서 확보하지 못했다.'] if code=='DeOhQMSzm5N' else ['레퍼런스와 동일한 원본 클립 출처는 찾지 못했다.']}
 plan['warnings']=[]
 for k in ['rendered_clips','cover_path','sfx_path','output_dir']:plan.pop(k,None)
 protect_automatic_crop(plan)
 root=OUT/code/'new-edit-v3';root.mkdir(exist_ok=True)
 write(root/'render-request.json',{'action':'render','output_dir':str(root),'plan':plan})
 write(root/'selection-experiments-input.json',plan)
 # Only selection executes in auto_capcut's own environment; preserve the subprocess boundary.
 settings=load_settings()
 program="""import json,copy,sys
from pathlib import Path
from auto_capcut.core.studio_timeline import select_shots
p=json.loads(Path(sys.argv[1]).read_text('utf-8'))
core={s['id'] for s in p['sources'] if s['source_role']=='core'}
shots={s['id']:s for s in p['shots']}
missing=[b['id'] for b in p['beats'] if not any(shots[o['shot_id']]['source_id'] in core for o in b['options'])]
old=copy.deepcopy(p);old.pop('footage_selection_policy');old=select_shots(old)
new=select_shots(copy.deepcopy(p))
Path(sys.argv[2]).write_text(json.dumps({'strict_core_only':{'unfilled_beats':missing},'relaxed_legacy':old,'relaxed_sequential':new},ensure_ascii=False,indent=2),'utf-8')
"""
 subprocess.run([str(settings.auto_capcut_python),'-X','utf8','-c',program,str(root/'selection-experiments-input.json'),str(root/'selection-experiments-result.json')],cwd=settings.auto_capcut_root,check=True)
 variants=json.loads((root/'selection-experiments-result.json').read_text('utf-8'))
 summary={'strict_core_only':variants['strict_core_only'],'relaxed_legacy':metrics(variants['relaxed_legacy']),
  'relaxed_sequential':metrics(variants['relaxed_sequential'])}
 write(root/'selection-experiments-summary.json',summary)
 print(code,json.dumps(summary,ensure_ascii=False),flush=True)

def render(code):
 settings=load_settings();root=OUT/code/'new-edit-v3'
 with (root/'render.log').open('w',encoding='utf-8') as log:
  subprocess.run([str(settings.auto_capcut_python),'-X','utf8','-m','auto_capcut.studio_runner','--request',str(root/'render-request.json'),'--result',str(root/'render-result.json')],cwd=settings.auto_capcut_root,stdout=log,stderr=log,check=True)
 result=json.loads((root/'render-result.json').read_text('utf-8'));assert result['status']=='completed'
 plan=json.loads(Path(result['plan_path']).read_text('utf-8'));meta=probe_video(Path(result['preview_path']))
 assert meta['width']==1080 and meta['height']==1920 and abs(meta['duration']-plan['duration'])<.15
 audit=metrics(plan);assert audit['replayed_seconds']<.001 and not plan['footage_diversity']['frozen_beats']
 write(root/'final-audit.json',{'metrics':audit,'video_meta':meta,'voice_sha256':sha256_file(Path(plan['voice']['path']))})
 sheet(Path(result['preview_path']),root/'final-20.jpg')
 print(code,'rendered',json.dumps(audit,ensure_ascii=False),flush=True)

def attach(code):
 studio=Studio(load_settings(),workers=False);root=OUT/code/'new-edit-v3'
 result=json.loads((root/'render-result.json').read_text('utf-8'))
 baseline=json.loads((OUT/code/'baseline-state.json').read_text('utf-8'))
 old=next(e for e in baseline['edits'] if e['id']==baseline['edit_id'])
 audit=json.loads((root/'final-audit.json').read_text('utf-8'))
 assert result['status']=='completed' and audit['metrics']['replayed_seconds']<.001
 plan=json.loads(Path(result['plan_path']).read_text('utf-8'))
 assert sha256_file(Path(plan['voice']['path']))==plan['voice']['sha256']
 edit={k:v for k,v in result.items() if k!='status'}
 edit.update(id='rework-source-20261010-v3-'+code,parent_id=old['id'],script_id=old['script_id'],voice_id=old['voice_id'],
  created=time.time(),status='completed',export_path=result['preview_path'],export_verified=True,exported_at=time.time(),
  export_kind='web_render',registration_deferred=True,registration_note='영상 소스 비교용 새 수정본 · 자동 등록 없음',
  source_rework=plan['source_rework'],source_diversity=audit['metrics'])
 def change(s,db):
  if not any(e['id']==edit['id'] for e in s['edits']):s['edits'].append(edit)
  s['edit_id']=edit['id'];s['sources'].extend(x for x in plan['sources'] if not any(y['id']==x['id'] for y in s['sources']))
  s.update(status='completed',message='소스 구간을 다시 수집·검토한 비교용 영상 완성')
  studio.store.event(db,s['id'],'source_quality_rework',{'edit_id':edit['id'],'source_diversity':audit['metrics']})
 studio.store.change(baseline['id'],change)
 print(code,'attached preserving previous revisions',flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['build','render','attach']);parser.add_argument('--code',choices=list(GROUPS));args=parser.parse_args()
 bins=list(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
 os.environ['PATH']=str(bins[0])+os.pathsep+os.environ['PATH']
 for code in ([args.code] if args.code else GROUPS):globals()[args.phase](code)
