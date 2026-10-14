"""Create proposed, bounded clips; approval happens only after actual frame review."""
import json
import os
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file

ROOT = Path('data/selected-three-quality').resolve()
# Pool, source index, source interval, crop x/y/width/height, framing, observation.
SPECS = {
 'DeRIBMYzn0x': [
  ('supplement',2,22,28,[0,0,1,.83],'contain','사각 침대 텐트 내부와 열린 출입구'),
  ('supplement',4,30,38,[.24,0,.55,1],'contain','침대 텐트 안에서 사람이 누워 사용'),
  ('supplement',4,17,25,[0,0,1,1],'contain','검은 텐트의 프레임과 고정 끈을 연결하는 설치'),
  ('supplement',3,20,27,[0,0,1,.63],'contain','텐트 프레임에 끈과 고리를 연결하는 손동작'),
  ('inventory',1,16,24,[.27,0,.60,1],'contain','침대 모기장의 망과 출입구 사용'),
  ('inventory',5,59,64,[.1,0,.9,1],'contain','검은 침대 텐트에 매트리스를 넣는 설치 동작'),
 ],
 'DeRFXHpEwck': [
  ('supplement',2,9,13,[.05,.34,.90,.53],'contain','색상 봉투형 파일을 손에 들고 제시'),
  ('supplement',2,14,17.5,[.32,.20,.65,.60],'fill','색상 봉투의 찍찍이 고정부를 여닫는 손동작'),
  ('supplement',4,11,17,[0,.26,.50,.55],'contain','봉투형 파일에 서류를 넣는 손동작'),
  ('supplement',4,17,23,[.15,.05,.70,.60],'fill','봉투의 찍찍이 원형 고정부 클로즈업'),
  ('supplement',2,21,25,[0,.03,1,.56],'contain','여러 색상 봉투를 펼쳐 정리하는 손동작'),
  ('inventory',1,5,17,[0,.05,1,.85],'contain','책상에서 종이와 메모용지를 정리하는 보조 장면'),
  ('inventory',2,13,25,[0,0,1,1],'contain','작은 화장품과 잡동사니를 모아 정리하는 보조 장면'),
 ],
 'DeJ7hD6zsnR': [
  ('inventory',8,0,7,[.25,.14,.50,.64],'contain','검은 노스페이스 숏패딩을 입은 모습'),
  ('inventory',1,28,36,[.30,0,.40,1],'fill','밝은 패딩의 로고와 원단 클로즈업'),
  ('inventory',7,76,83,[0,.05,1,.61],'fill','노스페이스 패딩 지퍼를 여닫는 손동작'),
  ('inventory',15,35,43,[.31,0,.40,1],'fill','노스페이스 숏패딩의 가슴 로고와 지퍼'),
  ('inventory',16,10,18,[0,.1,1,.8],'contain','매장에 진열된 두 색상의 노스페이스 패딩'),
  ('inventory',17,14,20,[.30,0,.35,1],'fill','키즈 패딩을 입은 아이의 모습'),
  ('inventory',17,26,29,[.24,0,.43,1],'fill','보라색 키즈 패딩 착용 모습'),
  ('inventory',15,102,110,[.31,0,.40,1],'fill','검은 숏패딩의 옆모습 착용'),
 ],
}


def main():
 bins = list(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
 os.environ['PATH'] = str(bins[0])+os.pathsep+os.environ['PATH']
 for code, specs in SPECS.items():
  pools = {name:{r['index']:r for r in json.loads((ROOT/code/f'source-{name}-1.json').read_text('utf-8'))}
           for name in {spec[0] for spec in specs}}
  out = ROOT/code/'proposed-clips-v3';out.mkdir(exist_ok=True);records=[]
  for i,(pool,index,start,end,crop,framing,observation) in enumerate(specs):
   row=pools[pool][index];raw=Path(row['path']);meta=probe_video(raw)
   assert 0<=start<end<=meta['duration']
   w,h,x,y=[int(value//2*2) for value in (meta['width']*crop[2],meta['height']*crop[3],meta['width']*crop[0],meta['height']*crop[1])]
   clip=out/f'clip-{i+1:02}.mp4';foreground=f'crop={w}:{h}:{x}:{y}'
   if framing=='fill':
    graph=f'{foreground},scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30'
    args=['-vf',graph]
   else:
    graph=(f'[0:v]{foreground},split=2[bg][fg];'
      '[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=35,eq=brightness=-0.12[background];'
      '[fg]scale=1080:1920:force_original_aspect_ratio=decrease[foreground];'
      '[background][foreground]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30[out]')
    args=['-filter_complex',graph,'-map','[out]']
   if not clip.is_file():
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',str(start),'-t',str(end-start),'-i',str(raw),
      *args,'-an','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',str(clip)],check=True,capture_output=True)
   frames=[]
   for j,fraction in enumerate([.08,.36,.64,.92]):
    t=(end-start)*fraction;p=out/f'clip-{i+1:02}-{j}.jpg'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',str(t),'-i',str(clip),'-frames:v','1','-vf','scale=216:384',str(p)],check=True,capture_output=True)
    frames.append({'frame_id':f'clip-{i+1:02}-{j}','path':str(p),'sha256':sha256_file(p),'source_timestamp':t})
   records.append({'id':'source-clip-'+sha256_file(clip)[:16],'name':f'clip-{i+1:02}','path':str(clip),'sha256':sha256_file(clip),
     'origin_url':row['origin_url'],'rights':'unknown-check-before-reuse','video_meta':probe_video(clip),
     'original_path':str(raw),'original_sha256':sha256_file(raw),'original_interval':{'start':start,'end':end},
     'crop':crop,'framing':framing,'proposed_observation':observation,'evidence_frames':frames,'pending_visual_review':True})
  for offset in range(0,len(records),6):
   group=records[offset:offset+6];sheet=Image.new('RGB',(4*220,len(group)*412),'#222');draw=ImageDraw.Draw(sheet)
   for y,r in enumerate(group):
    draw.text((3,y*412+4),r['name'],fill='white')
    for x,f in enumerate(r['evidence_frames']):sheet.paste(Image.open(f['path']),(x*220,y*412+24))
   sheet.save(out/f'review-{offset//6+1}.jpg')
  (out/'proposed.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),'utf-8')
  print(code,len(records),'proposed clips ready',flush=True)


if __name__=='__main__':main()
