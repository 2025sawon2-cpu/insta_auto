"""Read-only folder draft comparison; keep previous review tunnels untouched."""
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import threading
import time

from PIL import Image
import requests
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.comparison_share import build_comparison, server_for, LABELS
from hotpost.request_pacing import request_pause
from hotpost.editing_adapter import _atomic_json as save
from tools.build_folder_quality_draft import ROOT, DAILY, CODE


def main():
    qa = json.loads((ROOT / 'verification.json').read_text('utf-8'))
    assert not qa['visual_review_pending'] and not qa['source_coverage_complete']
    quality = json.loads((DAILY / 'writing/quality-v5.json').read_text('utf-8'))
    assert {s['number'] for s in quality['scripts']} == {1, 2, 3}
    attachment = json.loads((ROOT / 'attachment.json').read_text('utf-8'))
    settings = load_settings()
    studio = Studio(settings, workers=False)
    state = studio.store.get(attachment['task_id'])
    assert state['edit_id'] == attachment['edit_id']
    assert qa['reviewed_video_sha256'] == hashlib.sha256((ROOT / 'preview.mp4').read_bytes()).hexdigest()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 8803))
    Image.open(ROOT / 'cover.png').convert('RGB').save(ROOT / 'comparison-poster.jpg', quality=95)
    LABELS[CODE] = '실물 폴더 저장 케이스 · 품질 검토본'
    folder, assets = build_comparison(studio, codes=(CODE,), review_codes=(CODE,))
    page = (folder / 'index.html').read_text('utf-8')
    page = page.replace('원본 · 완성 영상 비교', '원본 · 폴더 품질 검토본 비교')
    page = page.replace('오른쪽 완성본', '오른쪽 새 검토본')
    page = page.replace('활용 예시본 · 동일 제품 미확보', '새 검토본 · 장면 보완 중')
    page = page.replace('예시 영상 다운로드', '새 검토본 다운로드')
    metrics = qa['metrics']
    note = '<p>2안 소유효과 응용 · 썸네일 도현 / 본문 십대 · 첫 1프레임 썸네일</p>'
    note += ('<p>폰 뒤 부착·실제 사진 복사 화면은 아직 부족합니다. 사진 이야기 중 조립 장면이 길게 나오는 구간도 보완 중입니다. '
             '아직 최종 품질 검토를 통과한 영상은 아닙니다.</p>')
    note += f'<p>{qa["metadata"]["duration"]:.1f}초 · 세로 원본 파일 3개 · 사용 구간 {metrics["action_clips"]}개 · 같은 원본 구간 반복 {metrics["replayed_seconds"]:g}초 · 단일 원본 최대 비중 {metrics["largest_original_share"]*100:.1f}%</p>'
    note += '<p>파일 3개가 서로 독립적으로 촬영된 영상 3개를 뜻하지는 않습니다. 동일 SKU·재사용 권리는 미확인입니다. 1인칭 생활 상황은 연출이며 심리 효과와 댓글 성과는 검증되지 않았습니다.</p>'
    cover = folder / (CODE + '-cover.png')
    shutil.copy2(ROOT / 'cover.png', cover)
    assets['/' + cover.name] = cover
    note += f'<details><summary>첫 프레임 썸네일 크게 보기</summary><img src="/{cover.name}" style="width:100%;max-height:800px;object-fit:contain" alt="도현 두 줄 썸네일"></details>'
    note += '<details><summary>새 대본 1·2·3안 · 영상에는 2안 적용</summary>'
    for s in quality['scripts']:
        note += f'<h3>{s["number"]}안 · {html.escape(s["bias"])}</h3><p>{html.escape(s["changes"])}</p><p style="white-space:pre-wrap">{html.escape(s["text"])}</p><p>{html.escape(s["mechanism_application"])}</p>'
    note += '</details><details><summary>사용한 영상의 원 출처</summary><ul>'
    plan = json.loads((ROOT / 'timeline.json').read_text('utf-8'))
    used = {b['selected_shot_id'] for b in plan['beats']}
    ids = {s['source_id'] for s in plan['shots'] if s['id'] in used}
    for url in sorted({s['url'] for s in plan['sources'] if s['id'] in ids}):
        note += '<li><a target="_blank" rel="noopener noreferrer" href="' + html.escape(url, quote=True) + '">' + html.escape(url) + '</a></li>'
    note += '</ul></details>'
    page = page.replace('</main>', note + '</main>')
    (folder / 'index.html').write_text(page, 'utf-8')
    save(folder / 'share_manifest.json', {'public_files': [p.name for p in assets.values()],
                                         'codes': [CODE], 'quality_draft': True})
    server = server_for(assets, 8803)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    expected = hashlib.sha256((ROOT / 'preview.mp4').read_bytes()).hexdigest()
    def verify(base, whole=False):
        def req(method, suffix='', **kwargs):
            if base.startswith('https://'):
                request_pause()
            return requests.request(method, base + suffix, timeout=35, **kwargs)
        response = req('GET')
        response.raise_for_status()
        assert '총 1건' in response.text and '아직 최종 품질' in response.text
        assert req('GET', '/api/studio').status_code == 404
        assert req('POST', '/').status_code == 405
        for asset in (CODE + '-original.mp4', CODE + '-final.mp4'):
            r = req('GET', '/' + asset, headers={'Range': 'bytes=0-15'})
            assert r.status_code == 206 and len(r.content) == 16
            assert req('HEAD', '/' + asset + '?download=1').headers['Content-Disposition'].startswith('attachment;')
        if whole:
            r = req('GET', '/' + CODE + '-final.mp4')
            r.raise_for_status()
            assert hashlib.sha256(r.content).hexdigest() == expected
    base = 'http://127.0.0.1:8803'
    verify(base, whole=True)
    process = subprocess.Popen([str(settings.data_dir / 'tools/cloudflared.exe'), 'tunnel', '--url', base, '--no-autoupdate'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        for line in process.stdout:
            match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
            if not match:
                continue
            url = match.group(0)
            for attempt in range(12):
                try:
                    verify(url, whole=True)
                    break
                except (requests.RequestException, AssertionError):
                    if attempt == 11:
                        raise
                    time.sleep(3)
            save(settings.data_dir / 'folder-quality-20261011-v6-share.json', {
                'url': url, 'verified': True, 'server_port': 8803, 'server_pid': os.getpid(),
                'tunnel_pid': process.pid, 'root': str(folder), 'codes': [CODE],
                'public_final_sha256': expected, 'range_download_verified': True,
                'production_api_denied': True, 'quality_draft': True,
                'source_coverage_complete': False, 'temporary': True})
            print('Verified folder draft comparison: ' + url, flush=True)
            threading.Thread(target=lambda: list(process.stdout), daemon=True).start()
            process.wait()
            return
    finally:
        if process.poll() is None:
            process.terminate()
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
