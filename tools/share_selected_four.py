"""Publish only the four verified completed exports through a temporary tunnel."""
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


def drain(stream):
    for _ in stream:
        pass


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--wait',action='store_true');args=parser.parse_args()
    settings = load_settings()
    studio = Studio(settings, workers=False)
    deadline=time.monotonic()+900
    while True:
        try:
            root, assets = build_comparison(studio)
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
    server = server_for(assets)
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
            (settings.data_dir / 'selected-four-share.json').write_text(
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
