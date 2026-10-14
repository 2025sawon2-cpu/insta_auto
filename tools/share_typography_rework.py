"""Serve an immutable two-video typography comparison on its own tunnel."""
import html
import json
import re
import shutil
import subprocess
import threading
import time

import requests
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.comparison_share import build_comparison, server_for, LABELS
from hotpost.request_pacing import request_pause
from tools.build_typography_rework import CODES, OUT, root as edit_root, read


def augment(root, assets, studio):
    page=(root/'index.html').read_text('utf-8')
    note='십대 폰트 · 본문 그림자 흐림 60% · 첫 1프레임 하이라이트 썸네일 · 두 줄 후킹 문구와 기울기 · 썸네일 흐림 80%'
    page=page.replace('<main><h1>',f'<main><p>{note}</p><h1>')
    for code in CODES:
        state=next(s for s in studio.store.list() if s['shortcode']==code)
        old=next(e for e in state['edits'] if e['id']=='rework-source-20261010-v3-'+code)
        previous=code+'-previous.mp4';shutil.copy2(old['export_path'],root/previous)
        assets['/'+previous]=root/previous
        oldcover=code+'-previous-cover.png';shutil.copy2(OUT/code/'new-edit-v3/cover.png',root/oldcover)
        assets['/'+oldcover]=root/oldcover
        newcover=code+'-cover.png';shutil.copy2(edit_root(code)/'cover.png',root/newcover)
        assets['/'+newcover]=root/newcover
        page=page.replace('<section><h2>'+LABELS[code],'<section id="'+code+'"><h2>'+LABELS[code])
        token='<video controls playsinline preload="metadata" src="/'+code+'-final.mp4"'
        buttons=(f'<div class="versions"><button data-code="{code}" data-kind="final" aria-pressed="true">새 완성본</button> '
                 f'<button data-code="{code}" data-kind="previous" aria-pressed="false">이전 완성본</button></div>')
        page=page.replace(token,buttons+f'<video id="v-{code}" controls playsinline preload="metadata" src="/{code}-final.mp4"')
        page=page.replace(f'<a class="download" href="/{code}-final.mp4?',f'<a id="download-{code}" class="download" href="/{code}-final.mp4?')
        spec=read(edit_root(code)/'timeline.json')['cover_spec']
        lines=' / '.join(spec['lines'])
        detail=(f'<details><summary>썸네일 전후 비교 · {html.escape(lines)}</summary><div class="pair stills">'
                f'<article><h3>이전 첫 프레임</h3><img src="/{oldcover}" alt="이전 썸네일"></article>'
                f'<article><h3>새 첫 프레임</h3><img src="/{newcover}" alt="두 줄 하이라이트 썸네일"></article></div>'
                '<p>30fps 영상의 첫 한 프레임(약 0.033초)에만 썸네일을 넣었습니다. 원본 대본, 음성, 장면 구간과 영상 길이는 유지했습니다.</p></details>')
        section_start=page.index(f'<section id="{code}"');end=page.index('</section>',section_start)
        page=page[:end]+detail+page[end:]
    js=root/'typography-comparison.js'
    js.write_text('''document.querySelectorAll('button[data-code]').forEach(b=>b.addEventListener('click',()=>{
const c=b.dataset.code,k=b.dataset.kind,v=document.getElementById('v-'+c);v.pause();
v.src='/'+c+'-'+k+'.mp4';v.poster='/'+c+(k==='final'?'-cover.png':'-previous-cover.png');v.load();
document.getElementById('download-'+c).href=v.src+'?download=1';
document.querySelectorAll('button[data-code="'+c+'"]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));
}));''','utf-8')
    assets['/typography-comparison.js']=js
    page=page.replace('</main></html>','</main><script src="/typography-comparison.js"></script></html>')
    page=page.replace('h3{font-size:', 'button{cursor:pointer;border:1px solid #5676aa;border-radius:7px;background:#22314c;color:white;padding:8px 10px;margin-bottom:10px}button[aria-pressed="true"]{background:#3b5f99}.stills img{width:100%;max-height:540px;object-fit:contain}h3{font-size:')
    (root/'index.html').write_text(page,'utf-8')
    (root/'share_manifest.json').write_text(json.dumps({'public_files':[p.name for p in assets.values()],
        'codes':CODES,'version':'typography-cover-v4'},ensure_ascii=False,indent=2),'utf-8')


def main():
    settings=load_settings();studio=Studio(settings,workers=False)
    root,assets=build_comparison(studio,codes=CODES);augment(root,assets,studio)
    binary=shutil.which('cloudflared') or str(settings.data_dir/'tools/cloudflared.exe')
    if not shutil.which(binary) and not __import__('pathlib').Path(binary).is_file():raise FileNotFoundError(binary)
    server=server_for(assets,port=8789,allow_scripts=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}'
    videos=[uri for uri in assets if uri.endswith('.mp4')]
    def verify(url):
        def get(path='', **kwargs):
            if url.startswith('https://'):request_pause()
            return requests.get(url+path,**kwargs)
        def head(path, **kwargs):
            if url.startswith('https://'):request_pause()
            return requests.head(url+path,**kwargs)
        page=get(timeout=20);page.raise_for_status()
        assert '십대 폰트' in page.text and 'typography-comparison.js' in page.text
        assert get('/api/studio',timeout=10).status_code==404
        assert get('/typography-comparison.js',timeout=10).status_code==200
        for media in videos:
            response=get(media,headers={'Range':'bytes=0-15'},timeout=30)
            assert response.status_code==206 and len(response.content)==16
            assert response.headers['Content-Range'].startswith('bytes 0-15/')
            assert head(media+'?download=1',timeout=20).headers['Content-Disposition'].startswith('attachment;')
    verify(base)
    process=subprocess.Popen([binary,'tunnel','--url',base,'--no-autoupdate'],stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
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
            receipt={'url':url,'verified':True,'root':str(root),'temporary':True,
                     'requires_running_pc_and_tunnel':True,'verified_video_paths':videos,
                     'server_port':8789,'tunnel_pid':process.pid,'version':'typography-cover-v4'}
            (settings.data_dir/'two-typography-rework-share.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
            print('비교 링크:',url,flush=True)
            def drain():
                for _ in process.stdout:pass
            threading.Thread(target=drain,daemon=True).start()
            process.wait();return
        raise RuntimeError('외부 링크를 발급하지 못했습니다.')
    finally:
        if process.poll() is None:process.terminate()
        server.shutdown();server.server_close()


if __name__=='__main__':main()
