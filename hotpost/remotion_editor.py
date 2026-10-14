"""Validated overlay documents and a separate, local Remotion render process."""
from __future__ import annotations

import copy
import json
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .editing_adapter import _atomic_json

ROOT = Path(__file__).resolve().parents[1] / 'remotion'
EMOJIS = {'😊', '😍', '👍', '👇', '👉', '🔥', '✨', '❤️', '✅', '🎉'}


def node_binary():
    override = os.environ.get('HOTPOST_REMOTION_NODE')
    if override:
        return override
    found = shutil.which('node')
    if found:
        return found
    bundled = Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    return str(bundled) if bundled.is_file() else None


def available():
    return bool(node_binary() and (ROOT/'node_modules/@remotion/renderer/package.json').is_file()
                and (ROOT.parent/'web/remotion-editor.js').is_file())


def validate_document(document, duration):
    """No user paths, HTML, URLs or executable props cross this schema."""
    if not isinstance(document, dict) or set(document) != {'version', 'elements'} or type(document.get('version')) is not int or document['version'] != 1:
        raise ValueError('지원하지 않는 편집 문서입니다.')
    elements = document['elements']
    if not isinstance(elements, list) or len(elements) > 120:
        raise ValueError('꾸미기 요소는 최대 120개입니다.')
    duration = float(duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('영상 길이를 확인할 수 없습니다.')
    allowed = {'id', 'kind', 'text', 'start', 'end', 'x', 'y', 'size', 'rotation', 'color', 'background', 'shape'}
    seen = set()
    result = []
    for item in elements:
        if not isinstance(item, dict) or set(item) != allowed:
            raise ValueError('올바르지 않은 꾸미기 요소입니다.')
        identifier = item['id']
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', identifier) or identifier in seen:
            raise ValueError('꾸미기 요소 ID가 중복되거나 잘못됐습니다.')
        seen.add(identifier)
        if item['kind'] not in {'text', 'arrow', 'emoji'}:
            raise ValueError('자막·화살표·이모지만 추가할 수 있습니다.')
        for field, low, high in [('start', 0, duration), ('end', 0, duration), ('x', 0, 1080),
                                 ('y', 0, 1920), ('size', 24, 500), ('rotation', -180, 180)]:
            value = item[field]
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'꾸미기 {field} 값을 확인하세요.')
        # Align to the same nearest 30fps frame as the Player; empty subframe cues are invalid.
        if math.floor(item['end']*30+.5) <= math.floor(item['start']*30+.5):
            raise ValueError('표시 끝은 시작보다 최소 한 프레임 뒤여야 합니다.')
        if not isinstance(item['text'], str) or len(item['text']) > 200:
            raise ValueError('자막은 200자 이하로 입력하세요.')
        if item['kind'] == 'text' and not item['text'].strip():
            raise ValueError('자막 내용을 입력하세요.')
        if item['kind'] == 'emoji' and item['text'] not in EMOJIS:
            raise ValueError('목록에서 이모지를 선택하세요.')
        if not isinstance(item['color'], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', item['color']):
            raise ValueError('올바르지 않은 색상입니다.')
        if type(item['background']) is not bool or item['shape'] not in {'straight', 'curved'}:
            raise ValueError('꾸미기 모양을 확인하세요.')
        result.append(copy.deepcopy(item))
    return {'version': 1, 'elements': result}


def render_overlays(studio, state, job, edit, plan):
    if not available():
        raise RuntimeError('Remotion 연결이 준비되지 않았습니다. remotion 의존성과 편집 번들을 설치하세요.')
    from .source_review_withdrawals import validate_plan
    validate_plan(studio.settings, plan)
    document = validate_document(job['payload']['overlay_document'], edit['duration'])
    clean = edit.get('clean_preview_path')
    if not clean or not Path(clean).is_file():
        clean = studio._process(state, job, 'caption-preview', {'plan': plan})['clean_preview_path']
    # Only task-owned immutable clean footage is accepted, never a URL from the client.
    source = Path(clean).resolve(strict=True)
    if not source.is_relative_to(studio.folder(state['id']).resolve()):
        raise ValueError('이 작업의 편집 미리보기가 아닙니다.')
    folder = studio.folder(state['id'])/job['id']
    folder.mkdir(exist_ok=True)
    request, receipt = folder/'remotion-request.json', folder/'remotion-result.json'
    _atomic_json(request, {'source': str(source), 'duration': edit['duration'], 'document': document,
                          'output_dir': str(folder.resolve())})
    with studio.render_lock:
        with (folder/'remotion.log').open('a', encoding='utf-8') as log:
            proc = subprocess.Popen([node_binary(), str(ROOT/'render.mjs'), str(request), str(receipt)],
                                    cwd=ROOT, stdout=log, stderr=log,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            job['checkpoint']['remotion_pid'] = proc.pid
            studio.store.checkpoint(job['id'], job['checkpoint'])
            try:
                proc.wait(timeout=studio.settings.auto_capcut_timeout)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError('편집 시간이 길어지고 있습니다. 재시도하면 진행 중인 렌더링을 이어받습니다.') from exc
    if not receipt.is_file():
        raise RuntimeError('Remotion이 결과를 반환하지 않았습니다. 편집 로그를 확인하세요.')
    result = json.loads(receipt.read_text(encoding='utf-8'))
    if result.get('status') != 'completed':
        raise RuntimeError('Remotion 영상 제작 실패: '+str(result.get('error', '알 수 없는 오류'))[:1000])
    target = Path(result['export_path']).resolve(strict=True)
    if not target.is_relative_to(folder.resolve()) or target.stat().st_size < 1024:
        raise RuntimeError('수정 영상 파일을 확인할 수 없습니다.')
    # Verify receipt against actual MP4 streams, including the retained narration.
    probe = shutil.which('ffprobe')
    if not probe:
        candidate = studio.settings.auto_capcut_root/'.venv/Scripts/ffprobe.exe'
        probe = str(candidate) if candidate.is_file() else None
    if not probe:
        raise RuntimeError('ffprobe를 찾을 수 없어 수정 영상 검증을 완료하지 못했습니다.')
    info = json.loads(subprocess.run([probe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(target)],
                                    capture_output=True, check=True, encoding='utf-8', timeout=60).stdout)
    video = next((s for s in info['streams'] if s['codec_type'] == 'video'), {})
    if (video.get('width'), video.get('height'), video.get('r_frame_rate')) != (1080, 1920, '30/1') or not any(s['codec_type'] == 'audio' for s in info['streams']):
        raise RuntimeError('수정 영상의 영상·음성 규격이 일치하지 않습니다.')
    if abs(float(info['format']['duration'])-edit['duration']) > .15:
        raise RuntimeError('수정 영상 길이가 원본과 다릅니다.')
    revised = copy.deepcopy(plan)
    revised['overlay_document'] = document
    path = folder/'remotion-timeline.json'
    _atomic_json(path, revised)
    return {'plan_path': str(path), 'clean_preview_path': str(source), 'preview_path': str(target),
            'export_path': str(target), 'export_verified': True, 'exported_at': time.time(),
            'export_kind': 'remotion', 'duration': edit['duration'], 'review_count': 0,
            **({'cover_path': edit['cover_path']} if edit.get('cover_path') else {})}
