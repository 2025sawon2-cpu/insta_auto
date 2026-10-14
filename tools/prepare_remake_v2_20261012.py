"""Keep first exports; improve actual visual motifs using newly observed footage."""
import argparse,copy,json,subprocess,time
from pathlib import Path
from PIL import Image,ImageDraw
from hotpost.editing_adapter import _atomic_json
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file
from hotpost.source_presentation import POLICY,review_scope

ROOT=Path('data/feedback-remake-20261012-v1').resolve()
NEW={
 'DeJ7hD6zsnR':[('gray-outdoor',8,.1,3.7,'회색 후드 패딩을 입고 야외에서 앞면과 옆면 착용을 보여줌'),('gray-outdoor-back',8,14.0,16.2,'회색 패딩의 전면에서 후면으로 돌아서며 후드와 기장을 보여줌')],
 'DeSvpmAsWgZ':[('black-jeans',10,1.8,5.0,'검정 노스페이스 숏패딩과 청바지를 입은 전신 정면·측면'),('black-jeans-back',10,5.1,8.7,'같은 검정 패딩과 청바지 차림의 다른 정면·측면 및 지퍼를 잡는 손'),('blue-fit',6,9.8,15.1,'파란 노스페이스 패딩을 입은 전체 실루엣과 소매를 보여줌'),('blue-side',6,31.0,34.6,'파란 패딩을 입고 옆면과 뒷면으로 돌아섬')]
}

def clips(code):
    out=ROOT/code/'final-v2';out.mkdir(exist_ok=True);ledger=json.loads((ROOT/code/'discovery/ledger.json').read_text('utf-8'))
    rows=[];sheet=Image.new('RGB',(800,len(NEW[code])*382),'#222');d=ImageDraw.Draw(sheet)
    for j,(name,index,a,z,observation) in enumerate(NEW[code]):
        s=ledger['candidates'][index];target=out/(name+'.mp4')
        if not target.exists():
            subprocess.run(['ffmpeg','-v','error','-ss',str(a),'-t',str(z-a),'-i',s['path'],'-an','-vf','scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=30','-c:v','libx264','-crf','18','-preset','veryfast',str(target)],check=True,capture_output=True)
        frames=[]
        for i,fraction in enumerate((.02,.3,.65,.98)):
            stamp=(probe_video(target)['duration']-.05)*fraction;frame=out/(name+f'-{i}.jpg')
            subprocess.run(['ffmpeg','-v','error','-y','-ss',str(stamp),'-i',str(target),'-frames:v','1',str(frame)],check=True,capture_output=True)
            im=Image.open(frame);im.thumbnail((200,356));sheet.paste(im,(i*200,j*382+26));d.text((i*200+2,j*382+2),name+f' {stamp:.2f}',fill='white')
            frames.append({'path':str(frame),'timestamp':stamp,'sha256':sha256_file(frame)})
        rows.append({'id':'remake-v2-'+code+'-'+name,'name':name,'path':str(target),'sha256':sha256_file(target),'video_meta':probe_video(target),
          'original_path':s['path'],'original_sha256':s['sha256'],'original_interval':{'start':a,'end':z},'url':s['url'],'provider':'tiktok','rights':'unknown-check-before-reuse',
          'source_role':'core','observation':observation,'evidence_frames':frames,'pending_visual_review':True})
    sheet.save(out/'new-motifs.jpg',quality=95);_atomic_json(out/'new-sources-pending.json',rows)

def approve(code):
    out=ROOT/code/'final-v2';sources=json.loads((out/'new-sources-pending.json').read_text('utf-8'))
    for s in sources:
        assert sha256_file(Path(s['path']))==s['sha256']
        limits=['검토한 패딩 형태·착용의 예시. 정확한 SKU·현재 가격·실제 구매 경험의 증거가 아님.']
        s.update(pending_visual_review=False,editing_eligible=True,source_quality='reviewed-portrait',blur_required=False,watermark_masks=[],presentation_review_required=False,relevance_review_required=False)
        s['functional_review']={'reviewed':True,'source_sha256':s['sha256'],'same_core_function':True,'context_usable':True,'context_usage_limits':limits,'observed_actions':[s['observation']],'evidence_frames':[v['path'] for v in s['evidence_frames']],'reviewer':'codex_session_visual_review'}
        s['presentation_review']={'policy':POLICY,'reviewed':True,'source_sha256':s['sha256'],'scope':review_scope(s),'usable':True,'quality_usable':True,'action_preserved':True,'observations':[s['observation']],'evidence_frames':s['evidence_frames'],'reviewer':'codex_session_visual_review'}
    _atomic_json(out/'new-sources-approved.json',sources)

def plan(code):
    out=ROOT/code/'final-v2';out.mkdir(exist_ok=True);p=json.loads((ROOT/code/'final/timeline.json').read_text('utf-8'))
    for key in ('rendered_clips','cover_path','sfx_path','output_dir'):p.pop(key,None)
    for key in ('source','background_path','image_path','layout','font_render_check'):p['cover_spec'].pop(key,None)
    if code in NEW:
        sources=json.loads((out/'new-sources-approved.json').read_text('utf-8'))
        for source in sources:
            p['sources'].append(source);length=source['video_meta']['duration'];shotid='new-'+source['name'];frames=source['evidence_frames']
            p['shots'].append({'id':shotid,'source_id':source['id'],'path':source['path'],'sha256':source['sha256'],'start':0,'end':length,'frames':[f['path'] for f in frames],
              'observation':source['observation'],'source_role':'core','evidence_status':'observed','context_usage_limits':source['functional_review']['context_usage_limits']})
    if code=='DeTaESASnr_':
        base=json.loads((ROOT/code/'baseline.json').read_text('utf-8'))
        for s in base['plan']['sources']:
            if not s['id'].endswith(('wood-room','photo','panels')):continue
            p['sources'].append(s);sid='extra-'+s['name'];length=probe_video(Path(s['path']))['duration']
            p['shots'].append({'id':sid,'source_id':s['id'],'path':s['path'],'sha256':s['sha256'],'start':0,'end':length,'frames':[],
                'observation':'; '.join(s['functional_review']['observed_actions']),'context_usage_limits':s['functional_review'].get('context_usage_limits',[])})
    maps={
      'DeJ7hD6zsnR':[['shot-9-1'],['shot-9-1'],['new-gray-outdoor'],['new-gray-outdoor'],['shot-3-1'],['shot-3-2'],['shot-7-1'],['shot-4-1'],['shot-1-2'],['shot-7-1'],['shot-8-1'],['shot-4-2'],['new-gray-outdoor-back'],['shot-2-2'],['shot-5-1'],['shot-5-1']],
      'DeSvpmAsWgZ':[['new-black-jeans'],['new-black-jeans'],['new-black-jeans'],['new-blue-fit'],['new-blue-fit'],['shot-1-1'],['shot-1-1'],['shot-4-1'],['shot-4-1'],['shot-3-1'],['shot-3-1'],['new-blue-side'],['new-blue-side'],['shot-6-1'],['shot-7-1'],['shot-7-1'],['new-black-jeans-back'],['new-black-jeans-back']],
      'DeTaESASnr_':[['shot-4-1'],['extra-wood-room'],['extra-wood-room'],['shot-14-1'],['shot-1-1'],['shot-1-1'],['shot-1-1'],['extra-wood-room'],['shot-8-1'],['shot-5-1'],['shot-11-1'],['extra-photo'],['shot-10-1'],['shot-3-1'],['shot-13-1'],['extra-panels'],['extra-panels']],
      'DeTJ6HbKCdF':[['shot-7-1'],['shot-3-1'],['shot-1-1'],['shot-14-1'],['shot-20-1'],['shot-18-1'],['shot-2-2','shot-4-2'],['shot-7-1'],['shot-13-1'],['shot-6-1'],['shot-15-1'],['shot-9-1'],['shot-20-1'],['shot-16-1'],['shot-4-2'],['shot-3-2'],['shot-10-1']]
    }
    if code=='DeTJ6HbKCdF':
        for s in p['shots']:
            if s['id']=='shot-2-2':s['start']=4.0
    for i,(b,ids) in enumerate(zip(p['beats'],maps[code],strict=True)):
        b.pop('selected_shot_id',None)
        direct=code=='DeTJ6HbKCdF' and i in (1,3,4,5,6,8,9,10)
        b['options']=[{'shot_id':sid,'relation':'direct' if direct else 'context','reason':'직접 확인한 실제 제품·동작·사용 상황. 연출된 화자 경험/가족 상황이나 정확한 SKU는 입증하지 않음.','reviewed':True} for sid in ids]
    p['session_options_ready']=True;_atomic_json(out/'selection-input.json',p)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['clips','approve','plan']);p.add_argument('code');a=p.parse_args();globals()[a.action](a.code)
