"""Prepare proposed action-scoped portrait clips for explicit visual review."""
import json
import os
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file
from hotpost.source_mask_review import sample_source_frames
from tools.audit_source_repetition import OUT

# name, discovery index (or retained source id), start/end in ORIGINAL video,
# normalized visible crop, observed purpose, core/context role, exact featured product.
SPECS={
 'DeNb4AsSgGw':[
  ('fridge-hook',15,2.8,7.0,[.22,0,.5,1],'사진 자석을 금속 냉장고 표면에 붙이고 보여주는 손동작','core',False),
  ('photo-display',14,5.0,7.5,[.25,0,.5,.82],'냉장고에 전시된 사진 자석','core',False),
  ('print-cut',7,4.0,7.0,[.3,0,.5,1],'인쇄 사진을 재단하는 손과 도구','context_only',False),
  ('magnetic-backing',8,63.0,69.0,[.2,0,.6,1],'사진을 붙일 접착식 자석 시트와 뒷면 취급','core',False),
  ('pet-photo-attach',42,73.2,77.0,[.2,0,.6,.8],'사진을 담은 자석을 냉장고에 부착','core',False),
  ('illustrated-magnets',24,36.0,43.0,[0,0,1,.75],'그림을 담은 사각 자석 여러 개를 전시','core',False),
  ('child-drawing',34,123.0,128.0,[.335,0,.33,1],'아이가 종이에 연필로 그림을 그리는 장면','context_only',False),
  ('drawing-attach',43,117.0,122.0,[.06,0,.88,.78],'그림이 담긴 소품을 자석으로 문에 붙이는 장면','core',False),
  ('diy-assembly',41,45.0,50.0,[.32,.20,.38,.55],'사진을 투명 사각 판에 맞추어 누르는 조립 장면','context_only',False),
  ('photo-memories',13,192.0,197.0,[.05,0,.9,.8],'여러 가족 사진 자석을 부착한 냉장고','core',False),
  ('fridge-payoff',7,11.9,14.0,[.22,0,.56,1],'사진 자석들이 전시된 냉장고와 부착 동작','core',False),
 ],
 'DeOhQMSzm5N':[
  ('food-label-hook','source-7eb8d245ec964b4a',69.0,72.0,[0,.48,1,.51],'손글씨 테이프 라벨이 붙은 식재료 봉투를 제시','core',False),
  ('macaron-product',36,4.0,8.0,[.18,0,.64,1],'손으로 닫힌 마카롱 모양 테이프 디스펜서를 제시','context_only',True),
  ('macaron-unpack',3,43.0,49.0,[.30,.20,.50,.78],'마카롱 테이프 포장을 열어 제품을 꺼냄','context_only',True),
  ('macaron-open',36,117.0,120.0,[.33,.22,.43,.72],'마카롱 디스펜서의 덮개를 열어 내부를 제시','core',True),
  ('macaron-refill',3,138.0,143.0,[.25,.2,.50,.78],'마카롱 디스펜서 안에 테이프 롤을 넣는 시연','core',True),
  ('magic-write',17,27.0,30.6,[.32,.20,.42,.55],'매직테이프 위에 펜으로 글씨를 쓰는 손동작','core',False),
  ('round-container','source-7eb8d245ec964b4a',15.5,18.5,[0,.35,1,.64],'둥근 식품 용기에 붙은 손글씨 테이프 라벨을 제시','core',False),
  ('food-pan-label',28,35.0,39.0,[.1,.08,.8,.82],'식품 보관용 팬의 라벨을 취급','context_only',False),
  ('magic-handle-v3',17,23.8,27.0,[.32,.20,.42,.55],'테이프를 손에 들고 취급하는 장면; 용기에서 제거하는 성능은 입증하지 않음','context_only',False),
  ('label-peel',26,30.0,34.0,[.2,0,.6,1],'라벨을 롤에서 뽑는 손동작; 용기에서 제거하는 성능은 입증하지 않음','context_only',False),
  ('compact-case',36,93.0,97.0,[.12,0,.76,1],'닫힌 마카롱 테이프의 둥근 옆면 제시','context_only',True),
  ('macaron-colors',14,7.5,10.3,[.28,0,.44,1],'상자 안의 여러 색상 마카롱 디스펜서','context_only',True),
  ('food-label-write','source-7eb8d245ec964b4a',40.0,44.0,[0,.48,1,.51],'식품 라벨용 테이프 위에 글씨를 쓰는 손동작','core',False),
  ('macaron-payoff',3,193.0,197.0,[.08,0,.84,1],'마카롱 디스펜서 여러 색상과 책상 전시','context_only',True),
 ]}


def main():
 bins=list(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
 os.environ['PATH']=str(bins[0])+os.pathsep+os.environ['PATH']
 for code,specs in SPECS.items():
  root=OUT/code/'clip-kit-v2';root.mkdir(exist_ok=True)
  discovery=json.loads((OUT/code/'research/discovery.json').read_text('utf-8'))
  state=json.loads((OUT/code/'baseline-state.json').read_text('utf-8'))
  records=[]
  for name,index,start,end,crop,description,role,exact in specs:
   row=discovery['candidates'][index-1] if isinstance(index,int) else next(s for s in state['sources'] if s['id']==index)
   source=Path(row['path']);meta=probe_video(source)
   assert 0<=start<end<=meta['duration']
   w,h,x,y=[int(value//2*2) for value in (meta['width']*crop[2],meta['height']*crop[3],meta['width']*crop[0],meta['height']*crop[1])]
   clip=root/(name+'.mp4')
   foreground=f'crop={w}:{h}:{x}:{y}'
   graph=(f'[0:v]{foreground},split=2[bg][fg];'
          '[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=35,eq=brightness=-0.12[background];'
          '[fg]scale=1080:1920:force_original_aspect_ratio=decrease[foreground];'
          '[background][foreground]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30[out]')
   if not clip.is_file():
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',str(start),'-t',str(end-start),'-i',str(source),
        '-filter_complex',graph,'-map','[out]','-an','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',str(clip)],check=True,capture_output=True)
   digest=sha256_file(clip);duration=probe_video(clip)['duration']
   evidence_path=root/name/'evidence.json'
   if evidence_path.is_file():evidence=json.loads(evidence_path.read_text('utf-8'))
   else:
    evidence=sample_source_frames(clip,digest,root/name,[[0.,duration]],samples_per_interval=5)
    evidence_path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),'utf-8')
   records.append({'id':'rework-'+name,'name':name,'path':str(clip),'sha256':digest,'video_meta':probe_video(clip),
      'origin_url':row.get('origin_url') or row['url'],'rights':row.get('rights','unknown-check-before-reuse'),
      'original_path':str(source),'original_sha256':sha256_file(source),'original_interval':{'start':start,'end':end},
      'crop_pixels':{'width':w,'height':h,'x':x,'y':y},'transform':'crop subject; contain on blurred portrait background',
      'proposed_observation':description,'proposed_role':role,'exact_product':exact,'pending_visual_review':True,
      'evidence':evidence})
   print(code,name,'prepared',flush=True)
  for batch in range((len(records)+4)//5):
   canvas=Image.new('RGB',(960,5*376),'#202020');draw=ImageDraw.Draw(canvas)
   for rindex,record in enumerate(records[batch*5:batch*5+5]):
    draw.text((8,rindex*376+3),record['name'],fill='white')
    for findex,frame in enumerate(record['evidence']['frames']):
     with Image.open(frame['path']) as image:
      image.thumbnail((180,320));canvas.paste(image,(findex*192,rindex*376+28))
     draw.text((findex*192+5,rindex*376+351),f"{frame['source_timestamp']:.2f}s",fill='white')
   canvas.save(root/f'review-sheet-{batch+1}.jpg')
  (root/'proposed-clips.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),'utf-8')


if __name__=='__main__':main()
