"""Serve an immutable seven-video feedback snapshot with media-only access."""
import html,json,os,re,shutil,socket,subprocess,threading,time
from pathlib import Path
import requests
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.comparison_share import build_comparison,server_for,LABELS
from hotpost.editing_adapter import _atomic_json
from tools.share_audited_seven import TITLES

ROOT=Path('data/user-feedback-revisions-20261011').resolve()
NOTES={'DeJ7hD6zsnR':'3번: 전체 대본을 한 번에 합성했습니다. 개인 목소리 설정은 유지하고, 대본은 소유효과 전개로 간결하게 다시 썼습니다. 출처 로고 소스와 일부 반복 구도를 대체했습니다.',
    'DeTaESASnr_':'5번: 사용한 8개 클립의 작은 @whytem.kr 및 @ping_gu.item 표시를 찾아 블러 처리했습니다. 대본·개인 음성·기존 장면 순서는 유지했습니다.',
    'DeTJ6HbKCdF':'6번: 출력 음성의 중간 약 2.04초 누락을 수정했습니다. 승인 음성과 효과음을 같은 시간축에서 먼저 혼합해 자막 시각을 맞췄습니다. 추가로 발견한 Active pick 표시도 작은 이동 블러로 처리했습니다.',
    'DeSvpmAsWgZ':'7번: 제품·가격 부담·여행 예산의 갈등·성인/키즈 탐색이 연결되는 2안으로 다시 작성했습니다. 실제 사용 원본은 3개에서 9개, 최대 원본 비중은 46.0%에서 17.3%로 개선했습니다. 기존 검토 소스를 넓혀 재사용한 것이며 이번에 새로 9개를 다운로드했다는 뜻은 아닙니다.'}

def main():
    port=8819
    with socket.socket() as probe:probe.bind(('127.0.0.1',port))
    settings=load_settings();studio=Studio(settings,workers=False);LABELS.update(TITLES)
    LABELS['DeJ7hD6zsnR']='노스페이스 패딩 · 전체 음성 재합성'
    LABELS['DeSvpmAsWgZ']='노스페이스 패딩 · 대본·소스 다양성 수정'
    folder,assets=build_comparison(studio,codes=tuple(TITLES),review_codes=tuple(TITLES),snapshot_suffix='feedback-v1')
    page=(folder/'index.html').read_text('utf-8').replace('원본 · 완성 영상 비교','피드백 반영 · 7개 영상 비교')
    page=page.replace('<main><h1>','<main><p>1·2·4번 유지 / 3·5·6·7번 수정 · 이전 제작본 보존</p><h1>')
    selection=[]
    tasks={s['shortcode']:s for s in studio.store.list()}
    for n,code in enumerate(TITLES,1):
        state=tasks[code];edit=next(e for e in state['edits'] if e['id']==state['edit_id']);out=Path(edit['plan_path']).parent
        if code in NOTES:
            qa=json.loads((out/'daily-review.json').read_text('utf-8'));assert qa['passed']
            old=json.loads(Path('data/user-feedback-20261011-v1',code+'-baseline.json').read_text('utf-8'))['edit']
            name=code+'-previous.mp4';target=folder/name
            if not target.exists():shutil.copy2(old.get('export_path') or old['preview_path'],target)
            assets['/'+name]=target
            note='<p>'+html.escape(NOTES[code])+'</p><details><summary>피드백 이전 제작본</summary><video controls playsinline preload="none" src="/'+name+'"></video></details>'
            if code in {'DeJ7hD6zsnR','DeSvpmAsWgZ'}:
                q=json.loads((ROOT/code/'writing/quality.json').read_text('utf-8'))
                note+='<details><summary>새 대본 1·2·3안</summary>'
                for script in q['scripts']:
                    note+='<h3>'+str(script.get('number',script.get('variant_number','')))+'안 · '+html.escape(script['bias'])+'</h3><p>'+html.escape(script['changes'])+'</p><p>'+html.escape(script['text'])+'</p>'
                note+='</details><p>가격은 조건부 대사입니다. 현재 가격·재고를 확인했다는 뜻은 아닙니다. 새 생활 상황은 연출입니다.</p>'
            note+='<p>실제 프레임과 출력 음성 시간 검토 통과. 목소리의 자연스러움은 재생하며 확인해 주세요.</p>'
        else:note='<p>'+str(n)+'번: OK 피드백을 받아 기존 제작본을 유지했습니다.</p>'
        title=html.escape(LABELS.get(code,state['title']));start=page.index('<section><h2>'+title);end=page.index('</section>',start)
        page=page[:end]+note+page[end:]
        selection.append({'number':n,'code':code,'edit_id':edit['id'],'plan_path':edit['plan_path'],'export_path':edit['export_path']})
    page=page.replace('preload="metadata"','preload="none"')
    (folder/'index.html').write_text(page,'utf-8');server=server_for(assets,port)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{port}'
    def verify(url):
        response=requests.get(url,timeout=30);response.raise_for_status();assert '총 7건' in response.text
        assert requests.get(url+'/api/studio',timeout=30).status_code==404
        assert requests.post(url+'/',timeout=30).status_code==405
        for path in assets:
            if not path.endswith('.mp4'):continue
            r=requests.get(url+path,headers={'Range':'bytes=0-15'},timeout=30);assert r.status_code==206 and len(r.content)==16
    verify(base)
    process=subprocess.Popen([str(settings.data_dir/'tools/cloudflared.exe'),'tunnel','--url',base,'--no-autoupdate'],
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        for line in process.stdout:
            match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',line)
            if not match:continue
            url=match.group(0)
            for attempt in range(24):
                try:verify(url);break
                except (requests.RequestException,AssertionError):
                    if attempt==23:raise
                    time.sleep(5)
            _atomic_json(settings.data_dir/'feedback-seven-20261011-share.json',{'url':url,'verified':True,
                'server_pid':os.getpid(),'tunnel_pid':process.pid,'port':port,'root':str(folder),'selection':selection})
            print('Verified feedback comparison: '+url,flush=True)
            threading.Thread(target=lambda:list(process.stdout),daemon=True).start();process.wait();return
    finally:
        if process.poll() is None:process.terminate()
        server.shutdown();server.server_close()

if __name__=='__main__':main()
