"""Four remakes, originals and previous outputs on a media-only HTTPS portal."""
import html,json,os,re,shutil,socket,subprocess,threading,time
from pathlib import Path
import requests
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.comparison_share import build_comparison,server_for,LABELS
from hotpost.editing_adapter import _atomic_json
from hotpost.source_quality import sha256_file
from tools.attach_remake_20261012 import ROOT,VERSIONS,read

NOTES={
 'DeJ7hD6zsnR':('3번 · 노스페이스 패딩','대본 전개를 다시 쓰고 야외 착용·실제 키즈 착용을 추가했습니다. 로고 카드와 특정 배색 문구를 제외했습니다.'),
 'DeTaESASnr_':('5번 · 슬라이딩 자석보드','거울을 미리 보여주지 않는 썸네일로 바꿨습니다. 작은 제작자 표시는 추가 블러 처리하고 같은 보드 구도의 재등장을 줄였습니다.'),
 'DeTJ6HbKCdF':('6번 · 캠핑 카트 테이블','실제 펼치기·높이 조절·파라솔 끼우기 동작을 대사와 맞췄습니다. 출력 음성과 자막 시간축을 검증했습니다.'),
 'DeSvpmAsWgZ':('7번 · 노스페이스 숏패딩','대본과 소스 풀을 3번과 독립적으로 구성했습니다. 청바지 착용과 파란 패딩 장면을 추가하고 얼굴 없는 썸네일을 골랐습니다.')}

def main():
    port=8820
    with socket.socket() as probe:probe.bind(('127.0.0.1',port))
    settings=load_settings();studio=Studio(settings,workers=False)
    LABELS.update({c:v[0] for c,v in NOTES.items()})
    folder,assets=build_comparison(studio,codes=tuple(VERSIONS),review_codes=tuple(VERSIONS),snapshot_suffix='remake-20261012')
    page=(folder/'index.html').read_text('utf-8').replace('원본 · 완성 영상 비교','3·5·6·7번 재제작 비교')
    page=page.replace('preload="metadata"','preload="none"')
    page=page.replace('<main><h1>','<main><p>1·2·4번은 기존 결과 유지 · 왼쪽 원본 / 오른쪽 새 제작본</p><h1>')
    selection=[]
    for code,version in VERSIONS.items():
        out=ROOT/code/version;qa=read(out/'daily-review.json');assert qa['passed']
        base=read(ROOT/code/'baseline.json');old=base['edit'];name=code+'-previous.mp4';target=folder/name
        if not target.exists():shutil.copy2(old.get('export_path') or old['preview_path'],target)
        assets['/'+name]=target;v=read(out/'verification.json');m=v['metrics']
        body='<p>'+html.escape(NOTES[code][1])+'</p><p>사용 원본 '+str(m['parent_files'])+'개 · 동일 원본 시간 재사용 '+str(m['repeated_source_seconds'])+'초 · 최대 원본 비중 '+str(m['largest_source_share'])+'%</p>'
        body+='<details><summary>이전 제작본과 비교</summary><video controls playsinline preload="none" src="/'+name+'"></video></details>'
        p=read(out/'timeline.json');body+='<details><summary>새 대본 보기</summary><p>'+html.escape(p['script_text'])+'</p></details>'
        body+='<p>네 편 모두 같은 개인 음성 참조·Seed 13·생성 설정을 적용하고 전체 대본을 한 번에 합성했습니다. 음성의 자연스러움과 제품 궁금증은 재생하며 확인해 주세요.</p>'
        marker='<section><h2>'+html.escape(NOTES[code][0]);start=page.index(marker);end=page.index('</section>',start);page=page[:end]+body+page[end:]
        selection.append({'code':code,'version':version,'sha256':qa['render_sha256']})
    (folder/'index.html').write_text(page,'utf-8');server=server_for(assets,port)
    threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{port}'
    def verify(url):
        response=requests.get(url,timeout=30);response.raise_for_status();assert '총 4건' in response.text
        assert requests.get(url+'/api/studio',timeout=20).status_code==404
        assert requests.post(url+'/',timeout=20).status_code==405
        for path,file in assets.items():
            if not path.endswith('.mp4'):continue
            r=requests.get(url+path,headers={'Range':'bytes=0-15'},timeout=30)
            assert r.status_code==206 and r.content==file.read_bytes()[:16]
    verify(base)
    process=subprocess.Popen([str(settings.data_dir/'tools/cloudflared.exe'),'tunnel','--url',base,'--no-autoupdate'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
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
            _atomic_json(ROOT/'share.json',{'url':url,'verified':True,'server_pid':os.getpid(),'tunnel_pid':process.pid,'port':port,'root':str(folder),'selection':selection,'prior_outputs_preserved':True})
            print('Verified remake comparison: '+url,flush=True)
            threading.Thread(target=lambda:list(process.stdout),daemon=True).start();process.wait();return
    finally:
        if process.poll() is None:process.terminate()
        server.shutdown();server.server_close()

if __name__=='__main__':main()
