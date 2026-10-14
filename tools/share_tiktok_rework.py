"""Read-only, versioned original/redo comparison. No studio API exposure."""
import html,json,os,re,shutil,subprocess,threading,time
from pathlib import Path
import requests
from PIL import Image
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.comparison_share import build_comparison,server_for,LABELS
from hotpost.request_pacing import request_pause
from tools.build_tiktok_rework import CODES,root,read
from tools.rework_tiktok_batch import ROOT
TITLES=dict(zip(CODES,['침대 암막 수면텐트','다이소 미니 파일 홀더','노스페이스 패딩 가족코디']))
NOTES={CODES[0]:'여러 침대 텐트 시연을 사용했습니다. 정확한 모델·SKU 일치는 확인되지 않았습니다.',CODES[1]:'원본의 다이소 6매 벨크로 미니 홀더 소스는 확보하지 못했습니다. 스냅·아코디언 포켓의 활용 장면과 다른 봉투형 파일의 벨크로 구조를 사용한 예시본입니다. 동일 제품 시연 또는 제작 소스 기준 충족으로 승인하지 않았습니다. 영상에도 다른 제품임을 표시했습니다.',CODES[2]:'같은 브랜드의 여러 어른용·키즈 패딩을 사용했습니다. 정확한 모델 일치는 미확인입니다. 가격대는 레퍼런스의 비교 정보이며 현재 판매처 가격을 검증한 내용은 아닙니다.'}
def main():
 settings=load_settings();studio=Studio(settings,workers=False);LABELS.update(TITLES)
 for c in CODES:Image.open(root(c)/'cover.png').convert('RGB').save(root(c)/'comparison-poster.jpg',quality=95)
 folder,assets=build_comparison(studio,codes=CODES,review_codes=(CODES[1],));page=(folder/'index.html').read_text('utf-8')
 page=page.replace('원본 · 완성 영상 비교','원본 · 재제작 영상 비교').replace('오른쪽 완성본','오른쪽 재제작·예시본')
 page=page.replace('<main><h1>','<main><p>2026-10-11 TikTok 소스 재제작 · 썸네일 도현 / 본문 십대 · 그림자 흐림 80% / 60% · 첫 1프레임 썸네일</p><h1>')
 for c in CODES:
  v=read(root(c)/'verification.json');audit=v['metrics'];ledger=read(ROOT/c/'discovery.json');variants=next(x for x in read(ROOT/'writing/variants.json')['items'] if x['code']==c)
  name=c+'-cover.png';shutil.copy2(root(c)/'cover.png',folder/name);assets['/'+name]=folder/name
  page=page.replace('<section><h2>'+TITLES[c],'<section id="'+c+'"><h2>'+TITLES[c]);start=page.index('<section id="'+c+'"');end=page.index('</section>',start)
  if c==CODES[1]:
   section=page[start:end].replace('<h3>완성본</h3>','<h3>활용 예시본 · 동일 제품 미확보</h3>').replace('완성 영상 다운로드','예시 영상 다운로드')
   page=page[:start]+section+page[end:];end=page.index('</section>',start)
  detail=f'<p>검색 후보 {len(ledger["candidates"])}개 · 저장 {sum(bool(x.get("path")) for x in ledger["candidates"])}개 · 편집에 사용한 소스 파일 {audit["independent_original_videos"]}개 / 장면 {audit["action_clips"]}개 · 같은 시간 구간 재생 {max(0,audit["replayed_seconds"]):g}초 · {v["metadata"]["duration"]:.1f}초</p><p>{html.escape(NOTES[c])}</p>'
  detail+=f'<details><summary>첫 프레임 썸네일</summary><img style="width:100%;max-height:650px;object-fit:contain" src="/{name}" alt="두 줄 후킹 썸네일"></details>'
  detail+='<details><summary>대본 1·2·3안과 심리 후킹 분석</summary><p>'+html.escape(variants['original_hook_analysis'])+'</p>'
  for variant in variants['variants']:
   detail+=f'<h3>{variant["number"]}안 · {html.escape(variant["type"])} {"(제작 선택)" if variant["number"]==variants["recommended_variant"] else ""}</h3><p>{html.escape(variant["category"])} / {html.escape(variant["bias"])}</p><p>{html.escape(variant["changes"])}</p><p style="white-space:pre-wrap">{html.escape(variant["text"])}</p>'
  detail+='</details><details><summary>사용한 소스 원 출처</summary><ul>'
  sources=read(root(c)/'approved-sources.json');urls=list(dict.fromkeys(s['url'] for s in sources if s['original_sha256'] in audit['original_intervals']))
  for u in urls:detail+=f'<li><a href="{html.escape(u)}" target="_blank" rel="noopener noreferrer">{html.escape(u)}</a></li>'
  detail+='</ul><p>각 파일의 출처를 기록했습니다. 재사용·상업 이용 허가는 확인되지 않았습니다. 개인 이야기 설정은 새로 구성한 연출입니다.</p></details>'
  page=page[:end]+detail+page[end:]
 (folder/'index.html').write_text(page,'utf-8');server=server_for(assets,8796);threading.Thread(target=server.serve_forever,daemon=True).start();base='http://127.0.0.1:8796';media=[u for u in assets if u.endswith('.mp4')]
 def verify(url):
  def req(method,path='',**kw):
   if url.startswith('https://'):request_pause()
   return requests.request(method,url+path,timeout=30,**kw)
  r=req('GET');r.raise_for_status();assert '총 3건' in r.text and '도현' in r.text and '대본 1·2·3안' in r.text
  assert req('GET','/api/studio').status_code==404;assert req('POST','/').status_code==405
  for u in media:
   r=req('GET',u,headers={'Range':'bytes=0-15'});assert r.status_code==206 and len(r.content)==16;assert r.headers['Content-Range'].startswith('bytes 0-15/');assert req('HEAD',u+'?download=1').headers['Content-Disposition'].startswith('attachment;')
 verify(base);process=subprocess.Popen([str(settings.data_dir/'tools/cloudflared.exe'),'tunnel','--url',base,'--no-autoupdate'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
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
   receipt=dict(url=url,verified=True,codes=CODES,server_port=8796,server_pid=os.getpid(),tunnel_pid=process.pid,root=str(folder),temporary=True,requires_running_pc_and_tunnel=True,video_paths=media)
   (settings.data_dir/'tiktok-rework-20261011-share.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8');print('Verified comparison:',url,flush=True);threading.Thread(target=lambda:list(process.stdout),daemon=True).start();process.wait();return
  raise RuntimeError('No tunnel URL')
 finally:
  if process.poll() is None:process.terminate()
  server.shutdown();server.server_close()
if __name__=='__main__':main()
