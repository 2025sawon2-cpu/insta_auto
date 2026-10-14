"""A separate immutable public review snapshot; older comparison links stay live."""
import html,json,os,re,shutil,socket,subprocess,threading,time
import requests
from PIL import Image
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.comparison_share import build_comparison,server_for,LABELS
from hotpost.request_pacing import request_pause
from tools.refine_tiktok_quality import ROOT,OLD

CODES=('DeRIBMYzn0x','DeJ7hD6zsnR')
TITLES={CODES[0]:'침대 암막 텐트 · 품질 보완 2차',CODES[1]:'노스페이스 패딩 · 품질 보완 2차'}


def variants(code):
    folder=ROOT/code/'writing';p=folder/'quality-final.json'
    if not p.exists():p=folder/'quality.json'
    q=json.loads(p.read_text('utf-8'))
    detail='<details><summary>새 대본 1·2·3안과 심리 후킹 분석</summary><p>'+html.escape(q['analysis']['original_hook_analysis'])+'</p>'
    for s in q['scripts']:
        detail+=f'<h3>{s["number"]}안 · {html.escape(s["bias"])}</h3><p>{html.escape(s["changes"])}</p><p style="white-space:pre-wrap">{html.escape(s["text"])}</p><p>{html.escape(s["mechanism_application"])}</p>'
    return detail+'</details>'


def main():
    settings=load_settings();studio=Studio(settings,workers=False);LABELS.update(TITLES)
    with socket.socket() as probe:probe.bind(('127.0.0.1',8798))
    for c in CODES:
        assert not json.loads((ROOT/c/'final/verification.json').read_text('utf-8'))['visual_review_pending']
        Image.open(ROOT/c/'final/cover.png').convert('RGB').save(ROOT/c/'final/comparison-poster.jpg',quality=95)
    folder,assets=build_comparison(studio,codes=CODES);page=(folder/'index.html').read_text('utf-8')
    page=page.replace('원본 · 완성 영상 비교','원본 · 품질 보완 검토본 비교')
    page=page.replace('<main><h1>','<main><p>기존 3편 중 텐트·패딩의 새 검토본 2편 · 미니 파일홀더 소스 보완 중 · 썸네일 도현 / 본문 십대 · 첫 1프레임 썸네일</p><h1>')
    for c in CODES:
        r=ROOT/c/'final';v=json.loads((r/'verification.json').read_text('utf-8'));a=v['metrics']
        previous=folder/(c+'-previous.mp4');shutil.copy2(OLD/c/'final/preview.mp4',previous);assets['/'+previous.name]=previous
        cover=folder/(c+'-cover.png');shutil.copy2(r/'cover.png',cover);assets['/'+cover.name]=cover
        detail=f'<p>새 검토본 {v["metadata"]["duration"]:.1f}초 · 사용 소스 파일 {a["independent_original_videos"]}개 · 편집 구간 {a["action_clips"]}개 · 같은 원본 구간 재생 {max(0,a["replayed_seconds"]):g}초 · 단일 원본 최대 점유 {a["largest_original_share"]*100:.1f}%</p>'
        detail+='<p>여러 제품·촬영자의 시연을 사용했습니다. 정확한 모델·SKU와 제품 진위, 재사용 권리는 확인되지 않았습니다. 파일 수는 서로 독립적으로 촬영된 영상 수를 보증하지 않습니다.</p>'
        if c==CODES[1]:detail+='<p>현재 할인 가격·재고·AS 및 동일한 키즈 배색 판매는 주장하지 않습니다. 검은 키즈 패딩은 같은 브랜드의 다른 모델 활용 예시입니다.</p>'
        else:detail+='<p>빛·찬바람 차단과 모기장 사용을 소개하며 숙면이나 난방비 절감을 보장하지 않습니다.</p>'
        detail+=f'<details><summary>첫 프레임 썸네일 크게 보기</summary><img src="/{cover.name}" style="width:100%;max-height:700px;object-fit:contain" alt="새 두 줄 썸네일"></details>'
        detail+=f'<details><summary>이전 검토본과도 비교</summary><video controls playsinline preload="metadata" src="/{previous.name}"></video><a href="/{previous.name}?download=1">이전 검토본 다운로드</a></details>'
        detail+=variants(c)+'<details><summary>새 검토본에 사용한 소스 원 출처</summary><ul>'
        p=json.loads((r/'timeline.json').read_text('utf-8'));used={b['selected_shot_id'] for b in p['beats']};ids={s['source_id'] for s in p['shots'] if s['id'] in used}
        for u in sorted({s['url'] for s in p['sources'] if s['id'] in ids}):
            detail+='<li><a href="'+html.escape(u,quote=True)+'" target="_blank" rel="noopener noreferrer">'+html.escape(u)+'</a></li>'
        detail+='</ul><p>인물·생활 상황은 연출이며 심리 후킹은 실제 댓글률을 검증한 결과가 아닌 제작 가설입니다.</p></details>'
        start=page.index('<section><h2>'+TITLES[c]);end=page.index('</section>',start);page=page[:end]+detail+page[end:]
    page=page.replace('</main>','<section><h2>미니 파일홀더 · 보완 진행 중</h2><p>A7 6매입 벨크로 구조의 정확한 핵심 소스는 미확보입니다. 똑딱이/아코디언 제품을 동일 제품의 시연으로 쓰지 않았습니다. 아래 새 3안은 아직 이 버전의 영상으로 제작하지 않았습니다.</p>'+variants('DeRFXHpEwck')+'</section></main>')
    (folder/'index.html').write_text(page,'utf-8');server=server_for(assets,8798);threading.Thread(target=server.serve_forever,daemon=True).start()
    base='http://127.0.0.1:8798';media=[u for u in assets if u.endswith('.mp4')]
    def verify(url):
        def req(method,path='',**kw):
            if url.startswith('https://'):request_pause()
            return requests.request(method,url+path,timeout=30,**kw)
        response=req('GET');response.raise_for_status();assert '총 2건' in response.text and '미니 파일홀더 · 보완 진행 중' in response.text
        assert req('GET','/api/studio').status_code==404 and req('POST','/').status_code==405
        for u in media:
            response=req('GET',u,headers={'Range':'bytes=0-15'});assert response.status_code==206 and len(response.content)==16
            assert req('HEAD',u+'?download=1').headers['Content-Disposition'].startswith('attachment;')
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
            receipt={'url':url,'verified':True,'codes':CODES,'server_port':8798,'server_pid':os.getpid(),'tunnel_pid':process.pid,'root':str(folder),'temporary':True,'requires_running_pc_and_tunnel':True}
            (settings.data_dir/'tiktok-quality-20261011-v2-share.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
            print('Verified quality comparison:',url,flush=True);threading.Thread(target=lambda:list(process.stdout),daemon=True).start();process.wait();return
    finally:
        if process.poll() is None:process.terminate()
        server.shutdown();server.server_close()


if __name__=='__main__':main()
