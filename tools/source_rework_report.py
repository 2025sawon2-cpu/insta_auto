"""Human-readable decision audit; publish only video-related, non-private fields."""
import html
import json
import shutil
from pathlib import Path
from tools.audit_source_repetition import OUT

LABELS={'DeNb4AsSgGw':'사진 냉장고 자석','DeOhQMSzm5N':'마카롱 매직테이프'}
REJECTED={
 'DeNb4AsSgGw':{9:'자석 시트의 포장·제품 설명 비중이 높아 실제 제작/부착 구간을 우선했다.',12:'긴 설명 영상 중 현재 편집에 더 잘 맞는 다른 사진 자석 실사용 구간을 선택했다.',17:'낮은 해상도의 둥근 자석 위주이고 사진/그림 자석 제작 동작이 부족했다.',25:'전용 프레스 기계로 만드는 방식은 레퍼런스의 간단한 DIY 방식과 다르다.',26:'대형 삽입 글자와 홍보 구성으로 필요한 깨끗한 동작 구간을 확보하기 어려웠다.'},
 'DeOhQMSzm5N':{1:'일반 검정 탁상 디스펜서. 마카롱 제품과 다른 형태여서 정확한 제품 시연을 우선했다.',2:'중앙에 구멍이 있는 도넛형. 마카롱 모델과 달라 제품 개폐·리필 근거로 사용하지 않았다.',5:'다른 도넛형이며 낮은 화질. 더 선명한 정확한 마카롱 시연을 선택했다.',7:'큰 원터치 탁상형으로 작동 구조가 다르다.',11:'길쭉한 다른 디스펜서이며 현재 제품 개폐 구간에 맞지 않았다.',13:'구멍이 있는 구형 디스펜서이고 중국어 삽입 자막이 많다.',15:'14번 광고의 세로 변형으로 같은 내용이다. 별개 원본 소스로 세지 않았다.',16:'다른 도넛형 제품이다. 정확한 마카롱 모델 영상이 있어 우선순위를 낮췄다.',19:'짧은 광고에 큰 삽입 글자가 있어 동작을 보존하며 사용하기 어렵다.',23:'설명하는 사람 위주. 실제 식품 라벨을 다루는 손동작 구간을 우선했다.',24:'설명하는 사람 비중이 높고 현재 대본에 필요한 동작 구간이 부족하다.',25:'정지 이미지 슬라이드쇼. 사진 게시물의 영상화 제외 방침에 맞춰 사용하지 않았다.',33:'일반 탁상 디스펜서 리필. 마카롱 구조와 다르다.'}}

def esc(value):return html.escape(str(value or ''),quote=True)
def link(url,label):
 return '<a target="_blank" rel="noopener noreferrer" href="'+esc(url)+'">'+esc(label)+'</a>' if str(url).startswith(('https://','http://')) else esc(label)

def build(root,assets):
 sections=[];all_decisions=[]
 for code,label in LABELS.items():
  baseline=json.loads((OUT/code/'baseline-audit.json').read_text('utf-8'))
  discovery=json.loads((OUT/code/'research/discovery.json').read_text('utf-8'))
  plan=json.loads((OUT/code/'new-edit-v3/timeline.json').read_text('utf-8'))
  result=json.loads((OUT/code/'new-edit-v3/final-audit.json').read_text('utf-8'))['metrics']
  experiments=json.loads((OUT/code/'new-edit-v3/selection-experiments-summary.json').read_text('utf-8'))
  approved=plan['sources'];rows=[];decisions=[]
  for index,candidate in enumerate(discovery['candidates'],1):
   clips=[s for s in approved if s['origin_url']==candidate['url']]
   if clips:
    decision='채택';reason=' / '.join(s['name']+': '+s['proposed_observation'] for s in clips)
    reason+=' · 사용 범위: '+', '.join(f"{s['original_interval']['start']:g}–{s['original_interval']['end']:g}초" for s in clips)
   elif candidate.get('path'):
    decision='검토 후 미사용';reason=REJECTED[code].get(index,'같은 역할의 다른 실제 동작 구간을 우선 선택했다.')
   elif candidate.get('download_error'):
    decision='다운로드 실패';reason=candidate['download_error'][:180]
   else:
    decision='다운로드 미시도';reason='제목·길이·검색 맥락으로 후보만 기록했다. 실제 기능/화질 탈락으로 집계하지 않는다.'
   thumb=''
   image=OUT/code/'research'/f'candidate-{index:02d}.jpg'
   if image.is_file():
    name=f'{code}-candidate-{index:02d}.jpg';target=root/name;shutil.copy2(image,target);assets['/'+name]=target
    thumb=f'<a href="/{name}" target="_blank">전체 15개 표본 보기</a>'
   decisions.append({'candidate':index,'title':candidate['title'],'url':candidate['url'],'decision':decision,'reason':reason})
   rows.append(f'<tr><td>{index}</td><td>{link(candidate["url"],candidate["title"])}</td><td>{esc(decision)}</td><td>{esc(reason)} {thumb}</td></tr>')
  oldrows=[]
  for source in baseline['source_reviews']:
   verdict='채택 가능' if source['eligible'] else '미채택/검토 미완료'
   reason=source.get('reason') or source.get('overlay_error') or source.get('portrait_error') or '실제 구간 검토가 완료되지 않았다.'
   if source.get('portrait_reason'):reason+=' · 세로 화면: '+source['portrait_reason']
   oldrows.append('<tr><td>'+link(source.get('origin_url'),source['id'])+'</td><td>'+verdict+'</td><td>'+esc(reason)+'</td></tr>')
  searchrows=''.join(f'<li>{esc(q["query"])} — {esc(q["status"])} / 결과 {q.get("count",0)}개</li>' for q in discovery['queries'])
  used=len({s['original_sha256'] for s in approved});downloaded=sum(bool(c.get('path')) for c in discovery['candidates'])
  all_decisions.append({'code':code,'decisions':decisions})
  sections.append(f'''<section id="{code}"><h2>{label}</h2><p>이전 저장 검색 manifest: 후보 {baseline['candidates']}개 / 다운로드 {baseline['downloaded']}개. 제작실에는 보충 자료 포함 {baseline['task_sources']}개, 편집 가능 {baseline['eligible']}개, 실제 사용 원본 {baseline['actually_used_files']}개.</p>
  <p>이번 검색 후보 {len(discovery['candidates'])}개 / 다운로드·전체 표본 검토 {downloaded}개 / 최종 원본 {used}개 / 동작 구간 {result['action_clips']}개. 다운로드 파일을 잘라 만든 구간들을 독립 원본으로 부풀려 세지 않았다.</p>
  <table><tr><th>측정</th><th>기존</th><th>새 제작</th></tr><tr><td>동일 시간 구간 재사용</td><td>{baseline['replayed_seconds']:.3f}초</td><td>{result['replayed_seconds']:.3f}초</td></tr><tr><td>한 원본의 최대 화면 점유율</td><td>{baseline['largest_source_share']*100:.1f}%</td><td>{result['largest_original_share']*100:.1f}%</td></tr></table>
  <h3>같은 검토 풀에 적용한 선택 실험</h3><ol><li>핵심 기능 구간만 허용: 현재 매핑 중 {len(experiments['strict_core_only']['unfilled_beats'])}개 자막 구간에 맞는 후보가 없음. 관련 준비·전시·그림 그리기까지 같은 핵심 기능을 요구하면 과도하게 좁아진다. 이 실험 조건이 기존 시스템 전체 조건과 같다는 뜻은 아니다.</li>
  <li>동작별 핵심/맥락 컷 허용 + 기존 시작점 초기화: 반복 {experiments['relaxed_legacy']['replayed_seconds']:.3f}초. 소스만 늘려도 편집 동작을 고치지 않으면 반복이 남는다.</li>
  <li>같은 풀 + 동작별 매핑 + 이어 재생: 반복 {experiments['relaxed_sequential']['replayed_seconds']:.3f}초. 실제 새 완성본에 적용.</li></ol>
  <details><summary>사용한 검색어와 실제 결과</summary><ul>{searchrows}</ul></details>
  <details><summary>이전 소스별 채택·미채택 이유</summary><table><tr><th>소스</th><th>판정</th><th>저장된 검토 이유</th></tr>{''.join(oldrows)}</table></details>
  <details><summary>이번 후보 전체의 채택·미채택·미시도 이유</summary><table><tr><th>#</th><th>출처</th><th>결과</th><th>이유·표본</th></tr>{''.join(rows)}</table></details></section>''')
 page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>영상 소스 품질 검토</title><style>body{background:#101725;color:#eaf0ff;font:16px/1.65 system-ui,sans-serif;margin:0}main{max-width:1080px;margin:auto;padding:24px}a{color:#aecdff}section{background:#192337;border-radius:14px;padding:20px;margin:22px 0}h1{font-size:27px}h2{font-size:22px}h3{font-size:18px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{border-bottom:1px solid #38445c;padding:10px;text-align:left;vertical-align:top;overflow-wrap:anywhere}details{margin:20px 0}summary{cursor:pointer;color:#c2d6ff}p{color:#c7d2e7}.note{background:#283650;padding:15px;border-radius:10px}@media(max-width:600px){main{padding:10px}section{padding:12px}td,th{padding:6px;font-size:12px}}</style><main><a href="/">← 원본·새 완성 영상 비교</a><h1>영상 소스 품질 검토 · 2026-10-10</h1>
 <p class="note">요약: 수집이 적다는 이유 하나로 설명되지 않는다. 검색 표현·플랫폼 실패·긴 영상의 동작 표본 누락·검토 미완료·자막마다 소스 시작점을 초기화하는 편집 문제가 겹쳤다. 기존 대본·음성·자막 시계를 보존한 두 새 버전으로 비교했다.</p>
 <h2>원인을 단계별로 확인한 결과</h2><ol><li><b>검색·접근:</b> 이전 TikTok/Douyin은 시간 초과, Xiaohongshu는 로그인, Lens/일부 검색엔진은 확인 화면에 막혔다. 이 기록은 영상을 품질로 탈락시킨 것과 다르다. 이번은 접근 가능한 YouTube를 중심으로 실제 제품 이름·재료·동작·한국어/영어/중국어/태국어 검색을 추가했다.</li>
 <li><b>잘못된 표현:</b> 사진 자석을 아크릴 액자로 좁히거나 일반 tape/dispenser로 검색하면 다른 구조의 제품·설명 영상이 섞인다. Scotch macaron/馬卡龍/마카롱과 magnetic sheet/photo fridge magnet 등 표현을 추가했고 검색어에 shorts를 일괄 덧붙이지 않는다.</li>
 <li><b>표본:</b> 이전은 균등 표본과 앞부분 장면 전환 표본을 섞고 제한 개수에서 잘라 뒤쪽 동작을 놓칠 수 있었다. 균등 표본을 보존하고 장면 전환도 전체 시간대를 나눠 찾도록 수정했다. 이번 레퍼런스는 전체 20개, 후보는 전체 15개 표본으로 확인한 뒤 실제 사용할 짧은 구간을 세로 출력 5개 표본으로 다시 봤다.</li>
 <li><b>채택:</b> 무관한 제품·소프트웨어 화면·정지 슬라이드쇼 제외는 타당했다. 기능 판정이 안 된 표본과 검토 실패를 실제 부적합 영상과 섞지 않아야 한다. 단순 외형/색상 차이는 허용하고 실제 동작을 판정한다. 준비·포장·전시·그림 그리기는 해당 문장의 맥락 컷으로 허용하되 제품 성능의 증거로 쓰지 않는다.</li>
 <li><b>분량:</b> 기존 완료 조건은 검토 분량 1.25배와 핵심 4초 중심이다. 문장별 필요한 동작이 골고루 있는지와 실제 반복량을 보장하지 않는다. 이번은 11/14개 동작 구간을 대본에 개별 매핑하고 반복·정지 보충·한 원본 점유율까지 확인했다.</li>
 <li><b>편집 오류:</b> 같은 소스가 연속 자막에 배치되면 시작점으로 돌아갔고 렌더러도 shot 시작점을 사용했다. 새 정책은 미사용 구간을 이어 재생하고 렌더러가 선택한 정확한 구간을 읽는다. 과거 정책의 타임라인·완성본은 보존했다.</li></ol>
 <h2>왜 레퍼런스와 똑같은 소스를 못 찾았나</h2><p>이번 검색에서도 동일 원본 클립은 확인하지 못했다. 다만 실제 마카롱 모델의 개폐·리필·전시 시연은 찾았다. 검색은 관련 상품을 찾는 것과 같은 촬영 클립의 출처를 찾는 것이 다르다. 자막·크롭·거울 반전·재업로드, 게시물 미색인·삭제·로그인 장벽도 원본 추적을 어렵게 한다.</p><p>두 레퍼런스의 끝까지 분산된 프레임을 확인했다. 특히 테이프 영상의 손·배경·촬영 방식이 이어져 제작자가 직접 찍은 시연일 가능성이 있다. 이는 영상 관찰에 따른 추정이며, 10~15개 인터넷 영상을 짜깁기했다거나 인터넷에 동일 원본이 공개되어 있다고 확정할 근거는 없다. 이번에는 영상 중반·후반의 필기/리필/부착 동작까지 검색·검토했다.</p>
 <p>정확한 제품 정보: <a href="https://www.scotch.com.tw/3M/zh_TW/p/d/v100715003/">3M Scotch 마카롱 디스펜서 공식 페이지</a>. 동일 제품 시연을 찾았다는 사실이 레퍼런스와 동일 촬영 원본을 찾았다는 뜻은 아니다.</p>
 <h2>남은 품질 한계</h2><p>테이프 제거 후 잔여물 없음의 직접 시연 소스는 확보하지 못했다. 해당 문구는 기존 승인 대본과 레퍼런스에 근거해 유지했고 새 컷은 사용 맥락이며 별도 성능 실증으로 판정하지 않았다. 일부 가로 영상은 손·도구를 살리기 위해 흐린 배경 위에 넣어 화면을 채우는 면적이 작고, 일부 원본은 선명도가 낮다. 반복 0초는 같은 시간 구간의 재사용이 없다는 측정이며, 비슷한 구도·행동이 전혀 없다는 뜻은 아니다.</p>
 <p>새 완성본은 1080×1920/30fps, 원래 편집 음성 해시와 자막 시간 보존, 실제 렌더 프레임 검토. 소스 관련 테스트 32개, 편집·구간·마스크 테스트 27개 통과. 자동 수집·제작·예약을 재활성화하지 않았다.</p>'''+''.join(sections)+'</main></html>'
 report=root/'source-report.html';report.write_text(page,'utf-8');assets['/source-report.html']=report
 (OUT/'source-decisions.json').write_text(json.dumps(all_decisions,ensure_ascii=False,indent=2),'utf-8')
 return report
