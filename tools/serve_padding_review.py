"""Serve only requested, immutable Montbell review media through a read-only allowlist."""
import html
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hotpost.comparison_share import server_for
from improve_padding_quality import OUT,OLD,read,save,sha

receipt=read(OUT/'qa/technical-receipt.json')
assert receipt['technical_passed'] and receipt['editorial_review_passed']
assert sha(OUT/'verified-export/preview.mp4')==receipt['export_sha256']
state=read(OUT/'original-state.json');root=OUT/'review-page';root.mkdir(exist_ok=True)
assets={}
for source,name in [(Path(state['reference_video']),'reference.mp4'),
                    (OUT/'verified-export/preview.mp4','improved.mp4'),
                    (OLD/'preview.mp4','previous.mp4'),(OUT/'improved-video/cover.png','cover.png'),
                    (OUT/'boundary-before-after.jpg','boundary-before-after.jpg')]:
    target=root/name
    if not target.exists():shutil.copy2(source,target)
    assert sha(source)==sha(target)
    assets['/'+name]=target
page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>몽벨 패딩 · 영상 품질 개선</title><style>
*{box-sizing:border-box}body{background:#0e1422;color:#f3f4f8;margin:0;font:16px system-ui,sans-serif}
main{max-width:1100px;margin:auto;padding:28px}h1{font-size:26px}p{color:#bdc7dd;line-height:1.6}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:22px}article,details{background:#192235;padding:20px;border-radius:16px}
h2{font-size:18px;margin-top:0}video{width:100%;height:590px;object-fit:contain;background:#05070c;border-radius:8px}
a,button{display:inline-block;background:#3457aa;color:white;padding:12px 16px;border:0;border-radius:8px;margin:12px 8px 4px 0;font:inherit;text-decoration:none;cursor:pointer}
details{margin-top:24px}details video{height:500px}img{width:100%;margin-top:15px}#playback-state{font-size:13px;color:#bdc7dd}
@media(max-width:600px){main{padding:12px}.pair{gap:8px}article{padding:10px}video{height:350px}h1{font-size:22px}a,button{font-size:13px;padding:10px}}
</style><main><h1>몽벨 패딩 · 개선 영상</h1><p>기존 대본·개인 음성 유지 · 1080×1920 · 16.5초</p>
<div class="pair"><article><h2>원본 레퍼런스</h2><video id="reference" controls playsinline preload="metadata" src="/reference.mp4"></video></article>
<article><h2>개선본</h2><video id="improved" controls playsinline preload="metadata" poster="/cover.png" src="/improved.mp4"></video>
<button id="play-improved" type="button">개선본 처음부터 재생</button><a href="/improved.mp4?download=1" download="montbell-improved.mp4">개선 영상 다운로드</a>
<p id="playback-state" aria-live="polite">재생 준비</p></article></div>
<details><summary>이전 완성본과 경계 프레임 비교</summary><video controls playsinline preload="none" src="/previous.mp4"></video>
<img src="/boundary-before-after.jpg" alt="70번·388번 프레임의 수정 전후 비교"></details>
<details><summary>사용 소스 출처</summary>SOURCE_CREDITS<p>원 출처를 보존했습니다. 상업 이용 권리 확인은 별도입니다.</p></details>
<p>임시 공유 링크는 작업 PC와 터널 프로세스가 실행 중일 때 이용할 수 있습니다.</p></main><script src="/review.js"></script></html>'''
plan=read(OUT/'improved-video/timeline.json')
credits=sorted({s.get('origin_url','') for s in plan['sources'] if s.get('origin_url','').startswith(('https://','http://'))})
page=page.replace('SOURCE_CREDITS','<ul>'+''.join('<li><a rel="noopener noreferrer" target="_blank" href="'+html.escape(u,quote=True)+'">소스 '+str(i+1)+'</a></li>' for i,u in enumerate(credits))+'</ul>')
(root/'index.html').write_text(page,encoding='utf-8');assets['/']=root/'index.html'
(root/'review.js').write_text('''const video=document.querySelector('#improved');const status=document.querySelector('#playback-state');
document.querySelector('#play-improved').addEventListener('click',()=>{video.currentTime=0;video.play();});
video.addEventListener('playing',()=>status.textContent='재생 중');
video.addEventListener('ended',()=>status.textContent='전체 재생 완료 · '+video.currentTime.toFixed(1)+'초');''',encoding='utf-8')
assets['/review.js']=root/'review.js'
server=server_for(assets,port=0,allow_scripts=True);base='http://127.0.0.1:'+str(server.server_address[1])
ready=dict(local_url=base,server_pid=os.getpid(),public_files=[p.name for p in assets.values()])
binary=ROOT/'data/tools/cloudflared.exe'
if binary.is_file():
    log=(OUT/'cloudflared.log').open('a',encoding='utf-8')
    tunnel=subprocess.Popen([str(binary),'tunnel','--url',base,'--no-autoupdate'],stdout=log,stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    ready['tunnel_pid']=tunnel.pid
save(OUT/'review-server.json',ready)
server.serve_forever()
