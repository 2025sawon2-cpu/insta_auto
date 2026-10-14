"""Publish the two reworked source-quality revisions through a temporary tunnel."""
import json
import re
import shutil
import subprocess
import threading
import argparse
import time
from pathlib import Path

import requests
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.comparison_share import build_comparison, server_for
from hotpost.request_pacing import request_pause
from tools.source_rework_report import build as build_report
from tools.audit_source_repetition import OUT


def drain(stream):
    for _ in stream:
        pass


def augment(root, assets):
    build_report(root, assets)
    page=(root/'index.html').read_text('utf-8')
    page=page.replace('<main><h1>', '<main><p><a href="/source-report.html">검색·채택·탈락 기준과 세 차례 선택 실험 결과 보기</a></p><h1>')
    for code,label in [('DeNb4AsSgGw','사진 냉장고 자석'),('DeOhQMSzm5N','마카롱 매직테이프 라벨링')]:
        page=page.replace('<section><h2>'+label, '<section id="'+code+'"><h2>'+label)
        state=json.loads((OUT/code/'baseline-state.json').read_text('utf-8'))
        edit=next(e for e in state['edits'] if e['id']==state['edit_id'])
        name=code+'-previous.mp4';target=root/name;shutil.copy2(edit['export_path'],target);assets['/'+name]=target
        token='<video controls playsinline preload="metadata" src="/'+code+'-final.mp4"'
        replacement='<div><button data-video="v-'+code+'" data-src="/'+code+'-final.mp4">새 완성본</button> <button data-video="v-'+code+'" data-src="/'+name+'">이전 완성본</button></div><video id="v-'+code+'" controls playsinline preload="metadata" src="/'+code+'-final.mp4"'
        page=page.replace(token,replacement)
    script=root/'comparison.js'
    script.write_text('document.querySelectorAll("button[data-video]").forEach(b=>b.addEventListener("click",()=>{const v=document.getElementById(b.dataset.video);v.pause();v.src=b.dataset.src;v.load();}));','utf-8')
    assets['/comparison.js']=script
    page=page.replace('</main></html>', '</main><script src="/comparison.js"></script></html>')
    page=page.replace('h3{font-size:', 'button{cursor:pointer;background:#294673;border:1px solid #5275a5;border-radius:7px;color:white;padding:8px 12px;margin-bottom:10px}h3{font-size:')
    (root/'index.html').write_text(page,'utf-8')
    (root/'share_manifest.json').write_text(json.dumps({'public_files':[p.name for p in assets.values()],
        'codes':['DeNb4AsSgGw','DeOhQMSzm5N']},ensure_ascii=False,indent=2),'utf-8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--wait',action='store_true');args=parser.parse_args()
    settings = load_settings()
    studio = Studio(settings, workers=False)
    deadline=time.monotonic()+900
    while True:
        try:
            root, assets = build_comparison(studio, codes=('DeNb4AsSgGw','DeOhQMSzm5N'))
            augment(root, assets)
            break
        except ValueError as exc:
            if not args.wait or time.monotonic()>=deadline:raise
            print('완성 4건 대기:',str(exc),flush=True)
            time.sleep(10)
    binary = shutil.which('cloudflared')
    local_binary = settings.data_dir / 'tools' / 'cloudflared.exe'
    if not binary and local_binary.is_file():
        binary = str(local_binary)
    if not binary:
        raise RuntimeError('cloudflared가 설치되지 않았습니다. 검증된 비교 파일은 로컬에 보존했습니다.')
    server = server_for(assets, allow_scripts=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    videos = [uri for uri in assets if uri.endswith('.mp4')]
    for media in videos:
        ranged = requests.get(base + media, headers={'Range': 'bytes=0-15'}, timeout=10)
        assert ranged.status_code == 206 and ranged.headers['Accept-Ranges'] == 'bytes'
        assert ranged.headers['Content-Range'].startswith('bytes 0-15/')
        if media.endswith('-final.mp4'):
            downloaded = requests.head(base + media + '?download=1', timeout=10)
            assert downloaded.headers['Content-Disposition'].startswith('attachment;')
    assert requests.get(base + '/api/studio', timeout=10).status_code == 404
    # Tunnel targets only the read-only comparison server, never port 8775.
    process = subprocess.Popen([binary, 'tunnel', '--url', base, '--no-autoupdate'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
        errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        for line in process.stdout:
            match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
            if not match:
                continue
            url = match.group(0)
            for attempt in range(10):
                request_pause()
                try:
                    page = requests.get(url, timeout=15)
                    page.raise_for_status()
                    break
                except requests.RequestException:
                    if attempt==9:raise
            if '원본 · 완성 영상 비교' not in page.text:
                raise RuntimeError('외부 비교 페이지 내용을 검증하지 못했습니다.')
            for media in videos:
                request_pause()
                response = requests.get(url + media, headers={'Range': 'bytes=0-15'}, timeout=30)
                if response.status_code != 206 or len(response.content) != 16:
                    raise RuntimeError('외부 영상 구간 응답을 검증하지 못했습니다: '+media)
                if media.endswith('-final.mp4'):
                    request_pause()
                    download = requests.head(url + media + '?download=1', timeout=30)
                    if not download.headers.get('Content-Disposition', '').startswith('attachment;'):
                        raise RuntimeError('외부 다운로드 헤더를 검증하지 못했습니다.')
            receipt = {'url': url, 'verified': True, 'root': str(root),
                'temporary': True, 'requires_running_pc_and_tunnel': True, 'verified_video_paths':videos}
            (settings.data_dir / 'two-source-rework-share.json').write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
            print('비교 링크:', url, flush=True)
            print('이 PC와 터널 프로세스가 실행 중일 때만 링크가 유지됩니다.', flush=True)
            # Drain ongoing tunnel logs so the child can never block on its pipe.
            threading.Thread(target=drain,args=(process.stdout,),daemon=True).start()
            process.wait()
            return
        raise RuntimeError('Cloudflare가 외부 링크를 발급하지 못했습니다.')
    finally:
        if process.poll() is None:
            process.terminate()
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
