"""A new read-only snapshot of the original three products, including A7 v4."""
import hashlib
import argparse
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
import requests
from PIL import Image
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.comparison_share import build_comparison, server_for, LABELS
from hotpost.request_pacing import request_pause
from hotpost.editing_adapter import _atomic_json as save

CODE = 'DeRFXHpEwck'
CODES = ('DeRIBMYzn0x', CODE, 'DeJ7hD6zsnR')
ROOT = Path('data/file-functional-quality-20261011-v4') / CODE / 'final'
WRITING = Path('data/file-functional-quality-20261011-v3') / CODE / 'writing/quality-v5.json'
PORT = 8804
PREVIOUS = Path('data/file-functional-quality-20261011-v3') / CODE / 'final'


def main():
    global ROOT, WRITING, PORT, PREVIOUS
    parser = argparse.ArgumentParser()
    parser.add_argument('--revision', choices=['v4', 'v5'], default='v4')
    args = parser.parse_args()
    if args.revision == 'v5':
        PREVIOUS = ROOT
        ROOT = Path('data/file-functional-quality-20261011-v5') / CODE / 'final'
        WRITING = WRITING.with_name('quality-v7.json')
        PORT = 8805
    qa = json.loads((ROOT / 'verification.json').read_text('utf-8'))
    assert not qa['visual_review_pending'] and not qa['source_coverage_complete']
    expected = hashlib.sha256((ROOT / 'preview.mp4').read_bytes()).hexdigest()
    assert qa['reviewed_video_sha256'] == expected
    attachment = json.loads((ROOT / 'attachment.json').read_text('utf-8'))
    settings = load_settings()
    studio = Studio(settings, workers=False)
    state = studio.store.get(attachment['task_id'])
    assert state['edit_id'] == attachment['edit_id']
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', PORT))
    Image.open(ROOT / 'cover.png').convert('RGB').save(ROOT / 'comparison-poster.jpg', quality=95)
    LABELS.update({CODES[0]: '침대 암막 텐트 · 기존 품질 보완본', CODE: '미니 파일 홀더 · 새 기능 검토본',
                   CODES[2]: '노스페이스 패딩 · 기존 품질 보완본'})
    folder, assets = build_comparison(studio, codes=CODES, review_codes=(CODE,))
    page = (folder / 'index.html').read_text('utf-8')
    page = page.replace('원본 · 완성 영상 비교', '원본 · 재작업 검토본 비교')
    page = page.replace('오른쪽 완성본', '오른쪽 검토본')
    page = page.replace('활용 예시본 · 동일 제품 미확보', '미니 홀더 기능 시연 · 후킹 보완 중')
    page = page.replace('예시 영상 다운로드', '새 검토본 다운로드')
    metrics = qa['metrics']
    note = '<p>이번 새 영상은 미니 파일 홀더입니다. 텐트·패딩은 앞서 만든 품질 보완본을 함께 볼 수 있게 모았습니다.</p>'
    note += '<p>파일 홀더: 1안 현재편향 · 썸네일 도현 / 본문 십대 · 첫 1프레임 썸네일 · 그림자 흐림 80% / 60%</p>'
    note += '<p>다른 미니 봉투의 종이·소품 수납을 확인했고, 다른 파우치를 실제 가방에 넣는 보조 장면도 추가했습니다. 벨크로 확대 장면은 해당 설명에만 사용하고 마무리는 분홍 미니 봉투로 돌아옵니다.</p>'
    if args.revision == 'v5':
        note = note.replace('벨크로 확대 장면은 해당 설명에만 사용하고',
            '벨크로 설명에는 큰 빨간 파일 대신 분홍 미니 봉투를 실제로 닫는 장면을 쓰고')
        note += '<p>도입을 지금 정리하기 귀찮은 선택과 분류 없이 모으는 행동으로 바꿨습니다. 추상적인 동작 요약을 빼고 닫아 휴대하는 쓰임으로 끝냅니다. 썸네일은 “정리는 내일 / 이 봉투는 지금”으로 현재편향의 선택 차이를 연결했습니다.</p>'
    note += '<p>실제 영수증 수납 화면은 아직 부족하며, 썸네일의 호기심 유발력과 대본 마무리는 더 다듬을 여지가 있습니다. 최종 품질 통과본은 아닙니다.</p>'
    note += f'<p>파일 홀더 {qa["metadata"]["duration"]:.1f}초 · 원본 파일 {metrics["independent_original_videos"]}개 · 사용 구간 {metrics["action_clips"]}개 · 같은 원본 시간 구간 반복 {metrics["replayed_seconds"]:g}초 · 단일 원본 최대 비중 {metrics["largest_original_share"]*100:.1f}%</p>'
    note += '<p>파일 수가 독립 촬영자 수를 보증하지는 않습니다. 서로 다른 제품의 기능·생활 상황 예시를 사용했고, 동일 SKU·재사용 권리는 미확인입니다. 1인칭 생활 상황은 연출이며 댓글 성과는 검증되지 않았습니다.</p>'
    cover = folder / (CODE + '-cover.png')
    shutil.copy2(ROOT / 'cover.png', cover); assets['/' + cover.name] = cover
    note += f'<details><summary>첫 프레임 썸네일 크게 보기</summary><img src="/{cover.name}" style="width:100%;max-height:800px;object-fit:contain" alt="도현 두 줄 썸네일"></details>'
    previous = folder / (CODE + '-previous.mp4')
    shutil.copy2(PREVIOUS / 'preview.mp4', previous)
    assets['/' + previous.name] = previous
    note += f'<details><summary>이번 구간 배치 수정 전 영상도 비교</summary><video controls playsinline preload="metadata" src="/{previous.name}"></video></details>'
    quality = json.loads(WRITING.read_text('utf-8'))
    note += '<details><summary>파일 홀더 대본 1·2·3안 · 영상에는 1안 적용</summary>'
    for s in quality['scripts']:
        note += f'<h3>{s["number"]}안 · {html.escape(s["bias"])}</h3><p>{html.escape(s["changes"])}</p><p style="white-space:pre-wrap">{html.escape(s["text"])}</p><p>{html.escape(s["mechanism_application"])}</p>'
    note += '</details><details><summary>파일 홀더 검토본의 원 소스</summary><ul>'
    plan = json.loads((ROOT / 'timeline.json').read_text('utf-8'))
    used = {b['selected_shot_id'] for b in plan['beats']}
    ids = {s['source_id'] for s in plan['shots'] if s['id'] in used}
    for url in sorted({s['url'] for s in plan['sources'] if s['id'] in ids}):
        note += '<li><a target="_blank" rel="noopener noreferrer" href="' + html.escape(url, quote=True) + '">' + html.escape(url) + '</a></li>'
    note += '</ul></details>'
    start = page.index('<section><h2>' + LABELS[CODE])
    end = page.index('</section>', start)
    page = page[:end] + note + page[end:]
    (folder / 'index.html').write_text(page, 'utf-8')
    save(folder / 'share_manifest.json', {'public_files': [p.name for p in assets.values()],
                                         'codes': list(CODES), 'quality_draft': True})
    server = server_for(assets, PORT)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    def verify(base, whole=False):
        def req(method, suffix='', **kwargs):
            if base.startswith('https://'): request_pause()
            return requests.request(method, base + suffix, timeout=35, **kwargs)
        response = req('GET'); response.raise_for_status()
        assert '총 3건' in response.text and '최종 품질 통과본은 아닙니다' in response.text
        assert req('GET', '/api/studio').status_code == 404 and req('POST', '/').status_code == 405
        for code in CODES:
            for asset in (code + '-original.mp4', code + '-final.mp4'):
                response = req('GET', '/' + asset, headers={'Range': 'bytes=0-15'})
                assert response.status_code == 206 and len(response.content) == 16
                assert req('HEAD', '/' + asset + '?download=1').headers['Content-Disposition'].startswith('attachment;')
        if whole:
            response = req('GET', '/' + CODE + '-final.mp4'); response.raise_for_status()
            assert hashlib.sha256(response.content).hexdigest() == expected
    base = 'http://127.0.0.1:' + str(PORT); verify(base, whole=True)
    process = subprocess.Popen([str(settings.data_dir / 'tools/cloudflared.exe'), 'tunnel', '--url', base, '--no-autoupdate'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        for line in process.stdout:
            match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
            if not match: continue
            url = match.group(0)
            for attempt in range(12):
                try:
                    verify(url, whole=True); break
                except (requests.RequestException, AssertionError):
                    if attempt == 11: raise
                    time.sleep(3)
            save(settings.data_dir / ('file-functional-quality-20261011-' + args.revision + '-share.json'), {
                'url': url, 'verified': True, 'server_port': PORT, 'server_pid': os.getpid(),
                'tunnel_pid': process.pid, 'root': str(folder), 'codes': list(CODES),
                'new_render_codes': [CODE], 'public_final_sha256': expected, 'range_download_verified': True,
                'production_api_denied': True, 'quality_draft': True, 'source_coverage_complete': False,
                'temporary': True})
            print('Verified three-product comparison: ' + url, flush=True)
            threading.Thread(target=lambda: list(process.stdout), daemon=True).start()
            process.wait(); return
    finally:
        if process.poll() is None: process.terminate()
        server.shutdown(); server.server_close()


if __name__ == '__main__':
    main()
