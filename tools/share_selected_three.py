"""Publish only the three requested immutable media comparisons."""
import html,json,os,re,shutil,subprocess,threading,time
from pathlib import Path
import requests
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.comparison_share import build_comparison,server_for,LABELS
from hotpost.request_pacing import request_pause
from tools.build_selected_three import CODES,root as edit_root,read

TITLES=dict(zip(CODES,['침대 암막 수면텐트','다이소 미니 파일 홀더','노스페이스 패딩 가족코디']))
NOTES={CODES[0]:'유사한 침대 텐트와 모기장 시연을 조합했습니다. 레퍼런스와 동일 제품인지 확인되지 않았습니다.',CODES[1]:'정확한 다이소 A7 제품의 추가 소스는 확보하지 못했습니다. 유사 파일 제품 시연과 소품 정리 장면을 사용했으므로, 실물 크기·브랜드·용량이 원본과 다릅니다.',CODES[2]:'여러 노스페이스 패딩과 키즈 시연을 조합했습니다. 정확한 모델 일치는 미확인입니다. 가격·AS 문구는 레퍼런스 내용이며 현재 판매 조건을 확인한 내용은 아닙니다.'}
def main():
 settings=load_settings();studio=Studio(settings,workers=False);LABELS.update(TITLES)
 for c in CODES:
  cover=edit_root(c)/'cover.png'
  from PIL import Image
  Image.open(cover).convert('RGB').save(edit_root(c)/'comparison-poster.jpg',quality=95)
 folder,assets=build_comparison(studio,codes=CODES);page=(folder/'index.html').read_text('utf-8')
 page=page.replace('<main><h1>','<main><p>십대 폰트 · 자막 그림자 흐림 60% · 첫 1프레임 썸네일 · 두 줄 후킹 문구와 기울기 · 썸네일 흐림 80%</p><h1>')
 for c in CODES:
  v=read(edit_root(c)/'verification.json');name=c+'-cover.png';shutil.copy2(edit_root(c)/'cover.png',folder/name);assets['/'+name]=folder/name
  audit=v['metrics'];note=NOTES[c]
  page=page.replace('<section><h2>'+TITLES[c],'<section id="'+c+'"><h2>'+TITLES[c])
  token='<section id="'+c+'"';start=page.index(token);end=page.index('</section>',start)
  detail=f'<p>원본 소스 {audit["independent_original_videos"]}개 · 동일 소스 구간 반복 {max(0,audit["replayed_seconds"]):g}초 · 완성본 {v["metadata"]["duration"]:.1f}초</p><p>{html.escape(note)}</p><details><summary>첫 프레임 썸네일 크게 보기</summary><img style="width:100%;max-height:650px;object-fit:contain" src="/{name}" alt="두 줄 썸네일"></details>'
  page=page[:end]+detail+page[end:]
 (folder/'index.html').write_text(page,'utf-8')
 (folder/'share_manifest.json').write_text(json.dumps({'codes':CODES,'files':[p.name for p in assets.values()]},ensure_ascii=False,indent=2),'utf-8')
 server=server_for(assets,8795);threading.Thread(target=server.serve_forever,daemon=True).start();base='http://127.0.0.1:8795'
 media=[u for u in assets if u.endswith('.mp4')]
 def verify(url):
  def req(method,path='',**kw):
   if url.startswith('https://'):request_pause()
   return requests.request(method,url+path,timeout=30,**kw)
  r=req('GET');r.raise_for_status();assert '총 3건' in r.text and '다이소 A7' in r.text
  assert req('GET','/api/studio').status_code==404;assert req('POST','/').status_code==405
  for u in media:
   r=req('GET',u,headers={'Range':'bytes=0-15'});assert r.status_code==206 and len(r.content)==16
   assert r.headers['Content-Range'].startswith('bytes 0-15/')
   assert req('HEAD',u+'?download=1').headers['Content-Disposition'].startswith('attachment;')
 verify(base)
 binary=str(settings.data_dir/'tools/cloudflared.exe')
 process=subprocess.Popen([binary,'tunnel','--url',base,'--no-autoupdate'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 try:
  for line in process.stdout:
   m=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',line)
   if not m:continue
   url=m.group(0)
   for attempt in range(12):
    try:verify(url);break
    except (requests.RequestException,AssertionError):
     if attempt==11:raise
     time.sleep(3)
   receipt=dict(url=url,verified=True,codes=CODES,server_port=8795,server_pid=os.getpid(),tunnel_pid=process.pid,root=str(folder),temporary=True,requires_running_pc_and_tunnel=True,video_paths=media)
   (settings.data_dir/'selected-three-20261010-share.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
   print('Verified comparison:',url,flush=True)
   threading.Thread(target=lambda:list(process.stdout),daemon=True).start();process.wait();return
  raise RuntimeError('No tunnel URL')
 finally:
  if process.poll() is None:process.terminate()
  server.shutdown();server.server_close()
if __name__=='__main__':main()
