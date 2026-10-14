"""Read-only recovery review page with preserved original and source provenance."""
import html,json,os,re,shutil,socket,subprocess,threading,time
import requests
from PIL import Image
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.comparison_share import build_comparison,server_for,LABELS
from hotpost.request_pacing import request_pause
from tools.recover_daily_materials import ROOT
from tools.build_daily_rework import CODES

TITLES={CODES[0]:'슬라이딩 자석 보드 전신거울',CODES[1]:'테이블 카트',
        'DeSvpmAsWgZ':'노스페이스 패딩 · 대본 보완 4차'}

def main(*,codes=CODES,port=8797,receipt_name='daily-rework-20261011-share.json',writing_revisions=None,review_codes=(),lazy_media=False,snapshot_suffix=''):
 writing_revisions=writing_revisions or {}
 settings=load_settings();studio=Studio(settings,workers=False);LABELS.update(TITLES)
 # Explicitly fail if this port is already owned; never replace a running share.
 with socket.socket() as probe:probe.bind(('127.0.0.1',port))
 for c in codes:Image.open(ROOT/c/'final/cover.png').convert('RGB').save(ROOT/c/'final/comparison-poster.jpg',quality=95)
 snapshot_kw={'snapshot_suffix':snapshot_suffix} if snapshot_suffix else {}
 folder,assets=build_comparison(studio,codes=codes,review_codes=review_codes,**snapshot_kw);page=(folder/'index.html').read_text('utf-8')
 page=page.replace('원본 · 완성 영상 비교','원본 · 재작업 검토본 비교')
 page=page.replace('<main><h1>','<main><p>2026-10-11 자료 복구 후 새 제작 · 썸네일 도현 / 본문 십대 · 첫 1프레임 썸네일</p><h1>')
 for c in codes:
  r=ROOT/c/'final';v=json.loads((r/'verification.json').read_text('utf-8'));q=json.loads((ROOT/c/'writing'/writing_revisions.get(c,'quality-v3.json')).read_text('utf-8'))
  start=page.index('<section><h2>'+TITLES[c]);end=page.index('</section>',start)
  detail=f'<p>검토본 {v["metadata"]["duration"]:.1f}초 · 소스 파일 {v["metrics"]["independent_original_videos"]}개 · 편집 구간 {v["metrics"]["action_clips"]}개 · 같은 원본 시간 구간 재생 {max(0,v["metrics"]["replayed_seconds"]):g}초</p>'
  detail+='<p>파일 수는 서로 독립적으로 촬영된 영상 수를 뜻하지 않습니다. 여러 재편집 영상에 같은 촬영 장면이 섞여 있습니다. 기능이 유사한 여러 제품을 사용했으며 정확한 모델·SKU 일치는 확인되지 않았습니다.</p>'
  if c in CODES:detail+='<p>원본 자막을 흐리게 한 작은 영역이 남아 있습니다.</p>'
  if c==CODES[1]:
   claim=(v.get('visual_review') or {}).get('direct_height_adjustment_witnessed',False)
   if (v.get('visual_review') or {}).get('opening_loaded_walking_witnessed'):
    detail+='<p>이번 보완: 도입부의 정지 장면 일부를 상자를 싣고 야외에서 실제로 걷는 장면으로 바꿨습니다. 기존 대본·개인 목소리·썸네일과 이후 편집은 유지했습니다. 새 소스는 29.47초 전체 디코드를 확인했습니다. 원본이 360×640이라 확대 화질이 부드럽고 자막 흐림 영역이 남습니다. 정확한 SKU·이동 목적지가 차인지·독립 촬영자인지는 확인되지 않았습니다.</p>'
   elif (v.get('visual_review') or {}).get('leg_folding_moment_witnessed') and (v.get('visual_review') or {}).get('loaded_pulling_witnessed'):
    detail+='<p>이번 보완: 실제 다리를 안으로 접는 동작과 상자를 싣고 손잡이로 끄는 동작을 해당 대사에 배치했습니다. 새 YouTube 파일은 앞부분만 받은 실패를 수정해 33.1초 전체 디코드를 확인했습니다. 이동 목적지가 차인지는 이 장면으로 확인되지 않습니다. 같은 촬영 장면이 여러 재편집 영상에 들어 있을 수 있으므로 새 촬영자 확보로 세지 않습니다.</p>'
   elif claim and (v.get('visual_review') or {}).get('direct_parasol_fitting_witnessed'):
    detail+='<p>짐 올리기·다리 길이 조절·파라솔을 꽂아 펼치는 동작을 직접 확인해 배치했습니다. 다리를 펼치던 반대 동작은 제거하고, 이미 접힌 상태에서 바퀴 달린 카트로 전환하는 모습으로 바꿨습니다. 다리를 접는 순간과 차까지 걷는 이동은 아직 확보하지 못했습니다. 마지막에는 야외에서 컵과 음식을 놓고 사용하는 모습을 넣었습니다.</p>'
   elif claim:detail+='<p>새 무자막 세로 영상에서 짐 올리기와 다리 길이 조절을 직접 확인해 해당 대사에 배치했습니다. 카트는 짐을 실은 상태와 기울이는 장면으로 보여줍니다. 차까지 걷는 이동·파라솔 부착 시연은 아직 확보하지 못했습니다.</p>'
   else:detail+='<p>파라솔 부착·높이 조절은 원본의 제품 설명입니다. 이번 확보 장면은 그 동작을 직접 입증하지 않아 관련 대사에는 테이블 사용 장면을 배치했습니다.</p>'
  if c=='DeSvpmAsWgZ':detail+='<p>기존 검토 소스 파일을 재사용했습니다. 현재 할인 가격·재고·AS·제품 진위 및 동일 키즈 배색 판매는 확인되지 않았습니다. 키즈의 검은 패딩은 같은 브랜드의 다른 모델 활용 예시입니다. 완성본에는 현재 가격을 주장하는 대사를 사용하지 않았습니다.</p>'
  if c=='DeSvpmAsWgZ' and v.get('conditional_price_mentioned'):
   detail+='<p>이번 대본은 “10만원대라면”이라는 조건으로 가격 부담과 가족 제품 탐색을 연결했습니다. 현재 그 가격에 판매 중이라는 뜻은 아닙니다. 1안 소유효과, 2안 기회비용 현저성, 3안 원작 흐름과 표면 치환을 함께 검토할 수 있습니다.</p>'
  if c=='DeJ7hD6zsnR' and v.get('conditional_price_mentioned'):
   detail+='<p>이번 검토본은 2안 소유효과로 새 대본과 개인 음성을 제작했습니다. 고르기 전에는 다른 후보도 괜찮았지만 내 겨울옷으로 정한 뒤 바꾸기 아까워지는 갈등입니다. “십만 원대에 살 수 있다면”은 조건이며 현재 판매 가격·할인·재고·AS 보장이 아닙니다. 남색 패딩은 다른 후보, 검은 키즈 패딩은 별도 라인 예시로만 사용했습니다. 1안 심적 회계와 3안의 가격 앵커링·손실회피 및 표면 치환도 아래에서 볼 수 있습니다.</p>'
  if c=='DeRFXHpEwck' and (v.get('visual_review') or {}).get('receipt_storage_revised'):
   detail+='<p>이번 보완은 실제 영수증이 들어 있는 파일의 보관 장면과 썸네일 문구입니다. 본문과 개인 음성은 유지했습니다. 새 TikTok 소스는 19.5초 전체 파일과 디코드를 확인했습니다. 다중 포켓 파일은 다른 제품의 활용 예시이며, 미니 벨크로 봉투에 영수증을 직접 넣는 동작이나 동일 상품을 입증하지 않습니다. 흐림 영역과 유사한 촬영 구도가 남습니다.</p>'
  if c=='DeRFXHpEwck' and (v.get('visual_review') or {}).get('envelope_alignment_corrected'):
   detail+='<p>작은 봉투에 넣는 대사와 분류 없이 담는 대사에는 실제 한칸 미니 봉투의 종이 수납 장면을 배치했습니다. 수집 완료 기준은 사용 가능 분량과 검토된 핵심 동작 4초로 판단하며, 같은 SKU나 영수증 직접 삽입 장면을 별도 필수 조건으로 추가하지 않았습니다. 같은 원본 시간의 반복은 없지만 미니 봉투를 보여주는 비중은 늘었습니다.</p>'
  if c=='DeSoiZvyyqj' and (v.get('visual_review') or {}).get('storage_cues_revised'):
   detail+='<p>저장 대사에 실제 휴대폰 USB-C 연결, PC 파일 복사 진행 창, 휴대폰 파일 목록을 배치했습니다. 사진 파일이 휴대폰에서 외부 저장장치로 복사되는 전체 과정과 폰 뒤 부착은 아직 확인하지 못했습니다. 새 썸네일은 실물 폴더에 내 사진을 간직한다는 반전을 강조합니다. 본문 대본과 개인 목소리는 유지했으며 최종 품질 검토는 진행 중입니다. 홍보 자막을 흐린 작은 영역이 남아 있습니다.</p>'
  if c=='DeSoiZvyyqj' and (v.get('visual_review') or {}).get('usb_use_corrected'):
   detail+='<p>폰 뒤 부착 설명을 폰과 USB 케이블로 연결하는 사용 방식으로 정정하고, 새 개인 음성으로 제작했습니다. 새 TikTok 원본은 세로 1080×1920, 38.9초 전체 수신과 디코드를 확인했습니다. 실제 케이블 삽입과 휴대폰 연결 장면을 사용하고 앞부분의 SSD 조립 장면을 손에 든 폴더 외형으로 바꿨습니다. 썸네일은 내 기록에 느끼는 가치와 실물 폴더의 반전을 유지했습니다. 특정 사진이 휴대폰에서 외부 저장장치로 복사되는 전체 과정은 확인하지 못했고, 일부 홍보 자막을 흐린 영역이 남아 있습니다.</p>'
  if c=='DeTaESASnr_' and (v.get('visual_review') or {}).get('opening_and_closing_corrected'):
   detail+='<p>거울을 여는 대사와 닫는 대사에 해당 동작을 맞추고, 메모·열쇠 대사에는 메모판과 금속 열쇠고리 활용 예시를 배치했습니다. 개별 열쇠 종류와 메모판의 기본 구성품 여부는 확인되지 않았습니다. 끝부분의 설치 전 바닥·부품 화면을 설치된 거울과 보드의 활용 장면으로 바꿨습니다. 이번 영상은 1안 자기참조 효과의 본문과 개인 목소리를 유지했습니다. 2안은 단순 노출 효과로 별도 전개를 새로 쓰고, 3안은 원작 흐름을 유지하며 장소·인물·계기를 바꿨습니다. 홍보 자막을 흐린 영역과 출처 표시는 남아 있습니다.</p>'
  if c=='DeRIBMYzn0x' and (v.get('visual_review') or {}).get('construction_closeup_removed_at_cta'):
   detail+='<p>이번 보완은 마지막 댓글 요청의 장면입니다. 연결 부품 대신 침대 텐트 전체와 실제로 안에 눕는 모습을 배치했습니다. 대본·개인 목소리·썸네일은 이전 검토본을 유지했습니다. 숙면이나 난방비 절감을 보장하는 영상은 아닙니다. 실제 청음과 후킹 반응 검토는 남아 있습니다.</p>'
  detail+='<details><summary>새 대본 1·2·3안과 심리 후킹 분석</summary><p>'+html.escape(q['analysis']['original_hook_analysis'])+'</p>'
  for s in q['scripts']:
   detail+=f'<h3>{s["number"]}안 · {html.escape(s["bias"])}</h3><p>{html.escape(s["changes"])}</p><p style="white-space:pre-wrap">{html.escape(s["text"])}</p>'
  detail+='</details><details><summary>사용 소스 원 출처</summary><ul>'
  p=json.loads((r/'timeline.json').read_text('utf-8'));used={b['selected_shot_id'] for b in p['beats']};ids={s['source_id'] for s in p['shots'] if s['id'] in used}
  for url in sorted({s['url'] for s in p['sources'] if s['id'] in ids}):detail+='<li><a target="_blank" rel="noopener noreferrer" href="'+html.escape(url,quote=True)+'">'+html.escape(url)+'</a></li>'
  detail+='</ul><p>재사용·상업 이용 권리는 확인되지 않았습니다. 새 생활 상황은 연출이며 심리 후킹 효과는 실제 반응률로 검증한 결과가 아닙니다.</p></details>'
  page=page[:end]+detail+page[end:]
 if lazy_media:
  page=re.sub(r'<video\b[^>]*>',lambda m:m.group(0).replace('preload="metadata"','preload="none"')
              if '-final.mp4' in m.group(0) else m.group(0),page)
 (folder/'index.html').write_text(page,'utf-8');server=server_for(assets,port);threading.Thread(target=server.serve_forever,daemon=True).start()
 base=f'http://127.0.0.1:{port}';media=[p for p in assets if p.endswith('.mp4')]
 def verify(url):
  def req(method,path='',**kw):
   if url.startswith('https://'):request_pause()
   return requests.request(method,url+path,timeout=30,**kw)
  response=req('GET');response.raise_for_status();assert f'총 {len(codes)}건' in response.text and '새 대본 1·2·3안' in response.text
  assert req('GET','/api/studio').status_code==404 and req('POST','/').status_code==405
  for p in media:
   response=req('GET',p,headers={'Range':'bytes=0-15'});assert response.status_code==206 and len(response.content)==16
   assert req('HEAD',p+'?download=1').headers['Content-Disposition'].startswith('attachment;')
 verify(base)
 process=subprocess.Popen([str(settings.data_dir/'tools/cloudflared.exe'),'tunnel','--url',base,'--no-autoupdate'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 try:
  for line in process.stdout:
   match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',line)
   if not match:continue
   url=match.group(0)
   for attempt in range(12):
    try:verify(url);break
    except (requests.RequestException,AssertionError):
     if attempt==11:raise
     time.sleep(3)
   receipt={'url':url,'verified':True,'codes':codes,'server_port':port,'server_pid':os.getpid(),'tunnel_pid':process.pid,'root':str(folder),'temporary':True}
   (settings.data_dir/receipt_name).write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
   print('Verified recovery comparison:',url,flush=True);threading.Thread(target=lambda:list(process.stdout),daemon=True).start();process.wait();return
 finally:
  if process.poll() is None:process.terminate()
  server.shutdown();server.server_close()

if __name__=='__main__':main()
