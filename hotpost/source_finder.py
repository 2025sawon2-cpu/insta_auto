"""릴스의 장면을 바탕으로 공개 웹에서 재료 영상 후보를 찾고 검증한다.

외부 서비스의 로그인/DRM/봇 차단을 우회하지 않는다. 다운로드한 후보의 사용 권리는
별도 확인이 필요하며, 출처와 탐색 근거를 manifest.json에 보존한다.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

import requests
from PIL import Image, ImageOps

from .config import Settings
from .model_service import ModelServiceUnavailable
# Compatibility exports: callers keep the existing source_finder API.
from .source_search.models import Candidate
from .source_search.catalog import KO_EN_ZH, PRODUCT_CONCEPTS
from .source_search.semantic import OpenClipVerifier
from .source_search.budget import charge_platform_probe
from .request_pacing import request_pause, ytdlp_pacing_args
from .storage import Storage
from .source_urls import video_url, canonical_video_key
from .source_queries import tiktok_product_queries, product_query_plan, platform_queries, clean_terms, language
from .source_quality import (platform_of, sha256_file,
                             relevance_reasons, reuse_reasons, select_valid_candidates, media_format_reasons,
                             title_query_agreement)

Progress = Callable[[str, int], None]
SOURCE_COOLDOWNS: dict[str, float] = {}


def _executable(name: str) -> str | None:
    """Find a command on PATH or beside the active virtualenv Python."""
    found = shutil.which(name)
    if found:
        return found
    suffix = ".exe" if os.name == "nt" else ""
    candidate = Path(sys.executable).with_name(name + suffix)
    return str(candidate) if candidate.is_file() else None

# CLIP은 번역기가 아니라 영상 속 물체/사용 장면을 이 카탈로그에 매칭한다. 너무 넓은 단어보다
# 실제 숏폼 검색에 쓰이는 상품명 표현을 영어·중국어 쌍으로 관리한다.


def _run(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                          timeout=timeout, check=False)


def _safe_name(text: str, limit: int = 70) -> str:
    value = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", text).strip("._")[:limit]
    return value or "video"


def _post(settings: Settings, shortcode: str):
    store = Storage(settings.db_path)
    row = store.conn.execute("SELECT * FROM posts WHERE shortcode=?", (shortcode,)).fetchone()
    if not row:
        store.close()
        raise ValueError(f"게시물을 찾지 못했습니다: {shortcode}")
    post = Storage._row_to_post(row)
    store.close()
    return post


def _verify_reference(settings, shortcode, path):
    """Validate a particular set of bytes, preserving media and past receipts."""
    from .editing_adapter import _atomic_json
    from .operation_progress import run_progress_command
    digest = sha256_file(path)
    receipt = settings.data_dir / 'reference-integrity' / shortcode / (digest + '.json')
    policy = 'reference-full-decode-v1'
    if receipt.is_file():
        try:saved = json.loads(receipt.read_text('utf-8'))
        except (OSError, ValueError):saved = {}
        if saved.get('policy') == policy and saved.get('source_sha256') == digest:
            if saved.get('status') == 'verified':
                return saved
            if saved.get('status') == 'invalid':
                raise ValueError('기준 영상의 동일 바이트가 전체 디코드 검증에서 실패했습니다.')
    ffmpeg, ffprobe = _executable('ffmpeg'), _executable('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('기준 영상 전체 검증에 ffmpeg/ffprobe가 필요합니다.')
    inspected = _run([ffprobe, '-v', 'error', '-show_entries',
        'format=duration:stream=codec_type,duration,width,height,nb_frames', '-of', 'json', str(path)], timeout=30)
    def invalid(reason):
        if sha256_file(path) != digest:
            raise RuntimeError('기준 영상 검증 중 파일이 변경되어 실패를 확정하지 않습니다.')
        _atomic_json(receipt, {'policy':policy, 'source_sha256':digest, 'status':'invalid',
            'bytes':path.stat().st_size, 'reason':reason, 'observed_at':time.time()})
        raise ValueError('기준 영상 전체 검증 실패: ' + reason)
    try:
        info = json.loads(inspected.stdout)
        stream = next((r for r in info.get('streams', []) if r.get('codec_type') == 'video'), {})
        duration = float(stream.get('duration') or info.get('format', {}).get('duration') or 0)
    except (ValueError, TypeError, AttributeError):
        return invalid('영상 스트림 metadata를 읽을 수 없습니다.')
    if inspected.returncode or not stream.get('width') or not stream.get('height') or not math.isfinite(duration) or duration <= 0:
        return invalid('재생 가능한 양수 길이 영상 스트림이 없습니다.')
    decoded = run_progress_command([ffmpeg, '-v', 'error', '-xerror', '-err_detect', 'explode',
        '-i', str(path), '-map', '0:v:0', '-progress', 'pipe:1', '-nostats', '-f', 'null', '-'])
    progress = dict(line.split('=',1) for line in decoded.stdout.splitlines() if '=' in line)
    try:
        frames = int(progress.get('frame',0))
        decoded_seconds = int(progress.get('out_time_us',0)) / 1_000_000
        expected_frames = int(stream.get('nb_frames') or 0) if str(stream.get('nb_frames','')).isdigit() else 0
    except (TypeError, ValueError):
        return invalid('전체 디코드 완료 근거가 올바르지 않습니다.')
    if decoded.returncode or progress.get('progress') != 'end' or frames <= 0:
        return invalid('전체 영상 디코드가 오류로 종료되었습니다.')
    if expected_frames and frames != expected_frames:
        return invalid('실제 디코드 프레임 수가 영상 스트림의 전체 프레임 수와 다릅니다.')
    if duration - decoded_seconds > max(.25, 2 * duration / frames):
        return invalid('영상 끝까지 디코드되지 않았습니다.')
    # Inspect audio too because this exact reference feeds transcription.
    if any(r.get('codec_type') == 'audio' for r in info.get('streams', [])):
        audio = run_progress_command([ffmpeg, '-v', 'error', '-xerror', '-err_detect', 'explode',
            '-i', str(path), '-map', '0:a:0', '-progress', 'pipe:1', '-nostats', '-f', 'null', '-'])
        if audio.returncode or 'progress=end' not in audio.stdout:
            return invalid('원본 음성 전체 디코드가 오류로 종료되었습니다.')
    if sha256_file(path) != digest:
        raise RuntimeError('기준 영상 전체 검증 중 실제 파일이 변경되었습니다.')
    saved = {'policy':policy, 'source_sha256':digest, 'status':'verified', 'bytes':path.stat().st_size,
        'duration':duration, 'decoded_seconds':decoded_seconds, 'decoded_frames':frames,
        'expected_frames':expected_frames, 'audio_checked':any(r.get('codec_type') == 'audio' for r in info.get('streams', [])),
        'observed_at':time.time()}
    _atomic_json(receipt, saved)
    return saved


def _download_reference(settings: Settings, post, out: Path) -> Path:
    """로컬 영상을 재사용하고 설정된 인증 방식으로 기준 영상을 받는다."""
    from .reference_cache import reusable_reference
    if getattr(post, 'kind', '') in {'image','carousel'}:
        from .photo_reference import prepare_reference
        prepared = prepare_reference(settings, post.shortcode)
        shutil.copy2(prepared['reference_video'],out)
        return out
    cached_files = [*settings.source_dir.glob(f'{post.shortcode}-*/reference.mp4'),
                    *settings.transcript_dir.glob(f'{post.shortcode}-*/reference.mp4')]
    for cached in sorted(cached_files, key=lambda p: p.stat().st_mtime, reverse=True):
        if not reusable_reference(settings, post.shortcode, cached):
            continue
        if cached != out and 0 < cached.stat().st_size <= settings.source_max_file_mb * 1024 * 1024:
            meta = probe_video(cached)
            if (meta.get('duration') or 0) > 0 and meta.get('width'):
                temporary = out.with_name(out.name + '.receiving')
                try:
                    _verify_reference(settings, post.shortcode, cached)
                    shutil.copy2(cached, temporary)
                    # Bind the actual copied bytes too; a concurrent cache
                    # replacement cannot inherit the original receipt.
                    _verify_reference(settings, post.shortcode, temporary)
                    temporary.replace(out)
                except ValueError:
                    continue  # Preserve invalid originals/receipts; try another authorized reference.
                finally:
                    temporary.unlink(missing_ok=True)
                return out
    if settings.collection_source == 'browser':
        from .instagram_video import browser_video_url
        source_url = browser_video_url(settings, post.shortcode)
    else:
        from .collectors.web_graphql import WebGraphQLCollector

        if not post.media_id:
            raise RuntimeError("이 게시물에는 media_id가 없어 기준 영상을 가져올 수 없습니다.")
        collector = WebGraphQLCollector(settings)
        source_url = ""
        try:
            r = collector.s.get(
                f"https://www.instagram.com/api/v1/media/{post.media_id}/info/",
                headers=collector._api_headers(post.url), timeout=30,
                allow_redirects=False,
            )
            if r.status_code == 200:
                item = ((r.json() or {}).get("items") or [{}])[0]
                versions = item.get("video_versions") or []
                if versions:
                    source = max(
                        versions,
                        key=lambda v: (
                            v.get("width", 0) * v.get("height", 0), v.get("type", 0)
                        ),
                    )
                    source_url = str(source.get("url") or "")
        except (requests.RequestException, ValueError):
            source_url = ""

        # New web sessions can access GraphQL while the legacy media-info route
        # redirects to /accounts/login/. Instaloader still exposes the signed CDN
        # URL embedded in post metadata, so use that as a bounded fallback.
        if not source_url:
            import instaloader
            from .collectors.instaloader_collector import load_session

            loader = load_session(settings)
            reference = instaloader.Post.from_shortcode(loader.context, post.shortcode)
            if not reference.is_video:
                raise RuntimeError("Instagram 게시물이 영상이 아닙니다.")
            source_url = str(reference.video_url or "")

    parsed = urlparse(source_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (
        host == "cdninstagram.com" or host.endswith(".cdninstagram.com")
        or host == "fbcdn.net" or host.endswith(".fbcdn.net")
    ):
        raise RuntimeError("Instagram이 허용된 CDN 영상 URL을 반환하지 않았습니다.")
    request_pause()
    video = requests.get(source_url, stream=True, timeout=60)
    if video.status_code != 200:
        video.close()
        raise RuntimeError(
            f"Instagram CDN 영상 다운로드 실패 (HTTP {video.status_code})."
        )
    limit = settings.source_max_file_mb * 1024 * 1024
    size = 0
    temporary = out.with_name(out.name + '.receiving')
    try:
        with temporary.open("wb") as f:
            for chunk in video.iter_content(1024 * 256):
                size += len(chunk)
                if size > limit:
                    raise RuntimeError("기준 영상이 설정된 최대 크기를 초과했습니다.")
                f.write(chunk)
        expected = (getattr(video, 'headers', {}) or {}).get('Content-Length')
        if not size or expected and size != int(expected):
            raise RuntimeError('기준 영상 수신 크기가 응답과 다릅니다.')
        try:
            _verify_reference(settings, post.shortcode, temporary)
        except ValueError:
            # A complete but corrupt reception remains diagnostic evidence,
            # separate from publishable reference.mp4 and automatic cache scans.
            digest = sha256_file(temporary)
            failure_file = settings.data_dir / 'reference-integrity' / post.shortcode / (digest + '.received-invalid.mp4')
            failure_file.parent.mkdir(parents=True, exist_ok=True)
            if not failure_file.is_file():shutil.copy2(temporary, failure_file)
            raise
        temporary.replace(out)
    finally:
        video.close()
        temporary.unlink(missing_ok=True)
    return out


def extract_frames(video: Path, frame_dir: Path, prefix: str = "frame", max_frames: int = 12) -> list[Path]:
    """전체 균등 시간 증거를 유지하고 추가 장면 변화의 중복만 제거한다."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg/ffprobe가 필요합니다.")
    frame_dir.mkdir(parents=True, exist_ok=True)
    probe = _run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)])
    try:
        duration = max(1.0, float(probe.stdout.strip()))
    except ValueError as exc:
        raise RuntimeError("영상 길이를 읽지 못했습니다.") from exc
    scene_slots = min(4, max_frames // 3)
    uniform_slots = max(2, max_frames - scene_slots)
    interval = duration / uniform_slots
    pattern = str(frame_dir / f"{prefix}_%03d.jpg")
    result = _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
                   "-vf", f"fps=1/{interval:.6f},scale=480:-2", "-frames:v", str(uniform_slots), "-q:v", "3", pattern])
    if result.returncode:
        raise RuntimeError(f"프레임 추출 실패: {result.stderr[-300:]}")
    files = [frame_dir / f'{prefix}_{index:03d}.jpg' for index in range(1,uniform_slots+1)
             if (frame_dir / f'{prefix}_{index:03d}.jpg').is_file()]
    # 짧게 등장하는 장면도 검색 근거로 남긴다. 출력 수와 실행 시간을 제한한다.
    scene_files = []
    scene_token = time.time_ns()
    # Each section of the full recording gets a scene-change opportunity.
    # Taking the first four cuts globally biased reverse search toward the intro.
    for index in range(scene_slots):
        target = frame_dir / f'{prefix}_{scene_token}_scene_{index+1:03d}.jpg'
        try:
            scene_result = _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                '-ss', str(duration*index/scene_slots), '-t', str(duration/scene_slots), '-i', str(video),
                '-vf', "select='gt(scene,0.3)',scale=480:-2", '-fps_mode', 'vfr',
                '-frames:v', '1', '-q:v', '3', str(target)], timeout=90)
            if scene_result.returncode == 0 and target.is_file():scene_files.append(target)
        except subprocess.TimeoutExpired:
            continue
    # Reserve the uniform sequence before extra cuts so bounded downstream
    # review keeps endpoints and a defensible chronological sequence.
    files = list(dict.fromkeys([*files, *scene_files]))
    unique: list[Path] = []
    hashes: list[int] = []
    for path in files:
        h = dhash(path)
        if '_scene_' not in path.name or not hashes or min((h ^ old).bit_count() for old in hashes) >= 5:
            unique.append(path); hashes.append(h)
        else:
            path.unlink(missing_ok=True)
    return unique[:max_frames]


def dhash(path: Path) -> int:
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw).convert("L")
        # 상하 자막/워터마크의 영향을 줄이고 실제 장면 중심부를 비교한다.
        w, h = image.size
        image = image.crop((0, int(h * .12), w, int(h * .84))).resize((17, 16), Image.Resampling.LANCZOS)
        px = list(image.get_flattened_data())
    bits = 0
    for y in range(16):
        for x in range(16):
            bits = (bits << 1) | (px[y * 17 + x] > px[y * 17 + x + 1])
    return bits


def compare_videos(reference_frames: list[Path], candidate: Path, work: Path) -> float:
    cframes = extract_frames(candidate, work, "candidate", max_frames=16)
    if not cframes or not reference_frames:
        return 0.0
    left = [dhash(p) for p in reference_frames]
    right = [dhash(p) for p in cframes]
    best = [1.0 - min((a ^ b).bit_count() for b in right) / 256 for a in left]
    # 한 장의 우연한 일치보다 여러 장면 일치를 보상한다.
    top = sorted(best, reverse=True)[:min(3, len(best))]
    return round(sum(top) / len(top), 4)


def probe_video(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {"duration": None, "width": None, "height": None, "bytes": path.stat().st_size}
    result = _run([ffprobe, "-v", "error", "-show_entries",
                   "format=duration:stream=width,height", "-of", "json", str(path)], timeout=30)
    try:
        info = json.loads(result.stdout)
        stream = next((row for row in info.get("streams", []) if row.get("width") and row.get("height")), {})
        return {"duration": float(info.get("format", {}).get("duration") or 0),
                "width": stream.get("width"), "height": stream.get("height"),
                "bytes": path.stat().st_size}
    except (ValueError, json.JSONDecodeError):
        return {"duration": None, "width": None, "height": None, "bytes": path.stat().st_size}


def _keywords(caption: str) -> list[str]:
    clean = re.sub(r"https?://\S+|[@#][\w.]+|[^0-9A-Za-z가-힣 ]+", " ", caption)
    stop = {"댓글", "남겨주세요", "정보", "진짜", "이건", "있어서", "있고", "하나씩", "있는", "너무", "사용", "제품",
            "보내드릴게요", "부서지시죠", "그대로예요", "궁금하시면", "프로필", "링크", "확인", "해주세요"}
    words = [w for w in clean.split() if 2 <= len(w) <= 12 and w not in stop
             and not re.search(r'(?:드릴게요|하시면|주세요|하시죠|예요|이에요)$', w)]
    scored = sorted(set(words), key=lambda w: (w in KO_EN_ZH, len(w)), reverse=True)
    return scored[:8]


def build_queries(caption: str) -> list[str]:
    words = _keywords(caption)
    concepts = [key for key in KO_EN_ZH if key in caption]
    mapped = [KO_EN_ZH[w] for w in concepts]
    ko = " ".join((concepts + words)[:6])
    en = " ".join(dict.fromkeys(x[0] for x in mapped[:4]))
    zh = " ".join(dict.fromkeys(x[1] for x in mapped[:4]))
    if any(x in caption for x in ("차량", "자동차", "차문")) and any(x in caption for x in ("컵", "홀더", "음료")):
        en = "car door hanging cup holder organizer"
        zh = "车门挂式杯架 汽车收纳"
    intent = []
    if "car door" in en:
        intent = ["car door hanging cup holder", "car door cup holder", "car door hanging trash can cup holder", "车门 挂式 杯架 垃圾桶"]
    return [q for q in dict.fromkeys((ko, *intent, en, zh)) if q.strip()]


def _clean_visual_terms(terms: list[str]) -> list[str]:
    generic = {"text in image", "person", "people", "human", "car", "vehicle", "video", "image", "photo"}
    return [term.strip() for term in clean_terms(terms)
            if term.strip() and term.strip().lower() not in generic and len(term.strip()) >= 3]


def _transcript_evidence(settings: Settings, shortcode: str) -> dict[str, str]:
    from .reference_cache import reusable_reference
    paths = sorted(settings.transcript_dir.glob(f"{shortcode}-*/transcript.json"), reverse=True)
    for path in paths:
        if not reusable_reference(settings, shortcode, path):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            from .reference_narrative import cached_reference_text
            speech = '\n'.join(str(row.get('text', '')) for row in data.get('speech', [])).strip()
            try:
                verified = cached_reference_text(path, speech)
            except (OSError, ValueError, KeyError, TypeError):
                verified = None  # Unverified cache never becomes search evidence.
            if verified:
                return {'speech':speech if verified['kind'] == 'mixed' else '',
                        'screen_text':'\n'.join(dict.fromkeys(r['text'] for r in verified['quotes'] if r['text'])),
                        'reference_kind':verified['kind']}
            return {key: " ".join(row.get("text", "") for row in data.get(key, []))
                    for key in ("speech", "screen_text")}
        except (OSError, json.JSONDecodeError):
            continue
    return {"speech": "", "screen_text": ""}


def build_grounded_queries(caption: str, visual_queries: list[str], vision_terms: list[str],
                           transcript: dict[str, str]) -> list[dict]:
    """제품 근거를 유지하면서 영어·중국어·한국어 검색 의도를 배분한다."""
    return product_query_plan(caption, visual_queries, vision_terms, transcript, build_queries(caption))['query_details']


def _yt_cookie_args(cookie_file: Path | None) -> list[str]:
    return ["--cookies", str(cookie_file)] if cookie_file and cookie_file.is_file() else []


def _yt_runtime_args(configured: str = '') -> list[str]:
    if configured:
        return ['--js-runtimes', configured]
    for name in ('deno', 'node'):
        executable = _executable(name)
        if executable:
            return ['--js-runtimes', f'{name}:{executable}']
    return []


def search_youtube(queries: list[str], limit: int, cookie_file: Path | None = None,
                   audit: list | None = None, js_runtime: str = '') -> list[Candidate]:
    """yt-dlp의 공개 YouTube 검색 추출기로 Shorts/제품 시연 후보를 찾는다."""
    ytdlp = _executable("yt-dlp")
    if not ytdlp or limit <= 0:
        return []
    out: list[Candidate] = []
    # 영어/중국어 검색이 글로벌 제품 소스에 가장 잘 맞는다.
    selected_queries = platform_queries(queries, 'youtube', min(6, limit))
    for query_index, query in enumerate(selected_queries):
        record = {'provider': 'youtube', 'query': query, 'language': language(query), 'status': 'started', 'candidates': 0}
        if audit is not None: audit.append(record)
        remaining_queries = len(selected_queries) - query_index
        count = min(6, max(1, (limit - len(out) + remaining_queries - 1) // remaining_queries))
        try:
            request_pause()
            result = _run([ytdlp, *ytdlp_pacing_args(), *_yt_runtime_args(js_runtime), *_yt_cookie_args(cookie_file), "--flat-playlist", "--dump-single-json",
                           "--no-warnings", f"ytsearch{count}:{query}"], timeout=90)
        except (OSError, subprocess.TimeoutExpired) as exc:
            record.update(status='error', error=type(exc).__name__)
            continue
        try:
            entries = json.loads(result.stdout).get("entries") or []
        except (json.JSONDecodeError, AttributeError):
            entries = []
        record.update(status='results' if entries else ('error' if result.returncode else 'no_results'), candidates=len(entries))
        for item in entries:
            url = item.get("webpage_url") or item.get("url") or ""
            if url and not url.startswith("http") and item.get("id"):
                url = f"https://www.youtube.com/watch?v={item['id']}"
            if url:
                meta = {'duration':item['duration']} if isinstance(item.get('duration'),(float,int)) else None
                out.append(Candidate(url=url, provider="youtube", title=item.get("title") or "", query=query, discovery_meta=meta))
        if len(out) >= limit:
            break
    return _dedupe(out)[:limit]


def _unwrap_ddg(url: str) -> str:
    if "duckduckgo.com/l/" in url:
        return unquote(parse_qs(urlparse(url).query).get("uddg", [url])[0])
    return url


def search_web(queries: list[str], limit: int, audit: list | None = None) -> list[Candidate]:
    from .search_access import indexed_gate
    gate = indexed_gate('duckduckgo')
    if gate:
        if audit is not None: audit.append({'provider':'duckduckgo', 'query':next(iter(queries), ''), 'candidates':0, **gate})
        return []
    out: list[Candidate] = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; hotpost-source-finder/1.0)"}
    selected_queries = list(dict.fromkeys(q.strip() for q in queries if q.strip()))[:max(0, limit)]
    for query_index, query in enumerate(selected_queries):
        remaining_queries = len(selected_queries) - query_index
        query_limit = max(1, (limit - len(out) + remaining_queries - 1) // remaining_queries)
        record = {'provider': 'duckduckgo', 'query': query, 'language': language(query), 'status': 'started', 'candidates': 0}
        if audit is not None: audit.append(record)
        from .source_collection_access import collection_disabled
        domains = [('tiktok','tiktok.com'), ('douyin','douyin.com'),
                   ('xiaohongshu','xiaohongshu.com'), ('youtube','youtube.com/shorts'),
                   ('bilibili','bilibili.com'), ('vendor','lazada.com.ph/videodetail'),
                   ('vendor','lazada.com.my/videodetail')]
        scopes = ' OR '.join('site:'+host for platform, host in domains if not collection_disabled(platform))
        scoped = f'{query} ({scopes})'
        try:
            request_pause()
            r = requests.get("https://html.duckduckgo.com/html/", params={"q": scoped}, headers=headers, timeout=20)
            record.update(http_status=r.status_code, requests=[{'operation':'indexed_search','at':time.time()}])
            gate = indexed_gate('duckduckgo', r)
            if gate:
                record.update(gate)
                break
            r.raise_for_status()
        except requests.RequestException as exc:
            record.update(status='error', error=type(exc).__name__)
            continue
        record['status'] = 'no_results'
        for href, title in re.findall(r'class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
            url = _unwrap_ddg(html.unescape(href))
            if not video_url(url):
                continue
            out.append(Candidate(url=url, provider=urlparse(url).netloc, title=re.sub("<.*?>", "", html.unescape(title)), query=query))
            record.update(status='results', candidates=record['candidates'] + 1)
            if len(out) >= limit:
                return _dedupe(out)
            if record['candidates'] >= query_limit:
                break
    return _dedupe(out)


def search_bing(queries: list[str], limit: int, audit: list | None = None) -> list[Candidate]:
    """키 없는 공개 검색 폴백. 영상 플랫폼과 상품 시연 페이지를 함께 찾는다."""
    from .search_access import indexed_gate
    from .source_urls import unwrap_bing_video_url
    gate = indexed_gate('bing')
    if gate:
        if audit is not None: audit.append({'provider':'bing', 'query':next(iter(queries), ''), 'candidates':0, **gate})
        return []
    out: list[Candidate] = []
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/150 Safari/537.36"}
    selected_queries = list(dict.fromkeys(q.strip() for q in queries if q.strip()))[:max(0, limit)]
    for query_index, query in enumerate(selected_queries):
        remaining_queries = len(selected_queries) - query_index
        query_limit = max(1, (limit - len(out) + remaining_queries - 1) // remaining_queries)
        record = {'provider': 'bing', 'query': query, 'language': language(query), 'status': 'started', 'candidates': 0}
        if audit is not None: audit.append(record)
        try:
            request_pause()
            r = requests.get("https://www.bing.com/search", params={"q": f'{query} video'}, headers=headers, timeout=20)
            record.update(http_status=r.status_code, requests=[{'operation':'indexed_search','at':time.time()}])
            gate = indexed_gate('bing', r)
            if gate:
                record.update(gate)
                break
            r.raise_for_status()
        except requests.RequestException as exc:
            record.update(status='error', error=type(exc).__name__)
            continue
        record['status'] = 'no_results'
        blocks = re.findall(r'<li class="b_algo".*?</li>', r.text, re.S)
        for block in blocks:
            match = re.search(r'<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
            if not match:
                continue
            raw_url = html.unescape(match.group(1))
            url = unwrap_bing_video_url(raw_url)
            title = re.sub("<.*?>", "", html.unescape(match.group(2)))
            record['result_links'] = record.get('result_links', 0) + 1
            if url != raw_url:
                record['decoded_video_links'] = record.get('decoded_video_links', 0) + 1
            if video_url(url):
                out.append(Candidate(url=url, provider=urlparse(url).netloc, title=title, query=query))
                record.update(status='results', candidates=record['candidates'] + 1)
                if len(out) >= limit:
                    return _dedupe(out)
                if record['candidates'] >= query_limit:
                    break
    return _dedupe(out)


def search_google_vision(settings: Settings, frames: list[Path], limit: int, audit: list | None = None) -> tuple[list[Candidate], list[str]]:
    if settings.source_browser_search:
        if audit is not None:
            audit.append({'provider':'google-vision', 'query':'', 'status':'not_attempted',
                          'candidates':0, 'reason':'existing_browser_session_required'})
        return [], []
    key = settings.source_google_vision_api_key or os.environ.get("GOOGLE_CLOUD_VISION_API_KEY", "")
    if not key:
        return [], []
    out: list[Candidate] = []
    terms: list[str] = []
    for frame in frames[:6]:
        from .source_search.strategy import image_sha256, image_signature
        record = {'provider':'google-vision', 'query':frame.name, 'language':'image',
                  'image_sha256':image_sha256(frame), 'image_signature':image_signature(frame), 'status':'started', 'candidates':0}
        if audit is not None: audit.append(record)
        payload = {"requests": [{"image": {"content": base64.b64encode(frame.read_bytes()).decode()},
                                  "features": [{"type": "WEB_DETECTION", "maxResults": 15},
                                               {"type": "LABEL_DETECTION", "maxResults": 10}]}]}
        try:
            request_pause()
            r = requests.post(f"https://vision.googleapis.com/v1/images:annotate?key={key}", json=payload, timeout=30)
            r.raise_for_status()
            response = (r.json().get("responses") or [{}])[0]
            web = response.get("webDetection") or {}
        except requests.RequestException as exc:
            record.update(status='error', error=type(exc).__name__)
            continue
        record['status'] = 'no_results'
        terms.extend(label.get("label", "") for label in web.get("bestGuessLabels", []))
        terms.extend(entity.get("description", "") for entity in web.get("webEntities", [])
                     if float(entity.get("score") or 0) >= .35)
        terms.extend(label.get("description", "") for label in response.get("labelAnnotations", [])
                     if float(label.get("score") or 0) >= .70)
        for page in web.get("pagesWithMatchingImages", []):
            url = page.get("url", "")
            if video_url(url):
                record.update(status='results', candidates=record['candidates']+1)
                out.append(Candidate(url=url, provider="google-vision", title=page.get("pageTitle", ""),
                                     query=frame.name, match_kind="visual-match"))
                if len(out) >= limit:
                    return _dedupe(out), [x for x in dict.fromkeys(terms) if x][:12]
    return _dedupe(out), [x for x in dict.fromkeys(terms) if x][:12]


def search_pexels(settings: Settings, queries: list[str], limit: int, audit: list | None = None) -> list[Candidate]:
    key = settings.source_pexels_api_key or os.environ.get("PEXELS_API_KEY", "")
    if not key:
        return []
    out: list[Candidate] = []
    for query in [q.strip() for q in queries if q.strip()][:1]:
        record = {'provider':'pexels', 'query':query, 'language':language(query), 'status':'started', 'candidates':0}
        if audit is not None: audit.append(record)
        try:
            request_pause()
            r = requests.get("https://api.pexels.com/v1/videos/search", params={"query": query, "orientation": "portrait", "per_page": min(limit, 10)},
                             headers={"Authorization": key}, timeout=30)
            r.raise_for_status()
        except requests.RequestException as exc:
            record.update(status='error', error=type(exc).__name__)
            continue
        for item in r.json().get("videos", []):
            files = item.get("video_files") or []
            if not files:
                continue
            f = max(files, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0))
            out.append(Candidate(url=f.get("link", ""), provider="pexels", title=f"Pexels video {item.get('id')}", query=query,
                                 match_kind="stock-b-roll", rights="pexels-license"))
        record.update(status='results' if out else 'no_results', candidates=len(out))
    return _dedupe(out)


def search_local_cache(settings: Settings, shortcode: str, limit: int) -> list[Candidate]:
    """같은 릴스에서 이미 검증·다운로드한 후보를 재사용한다."""
    out: list[Candidate] = []
    manifests = sorted(settings.source_dir.glob(f"{shortcode}-*/manifest.json"), reverse=True)
    for path in manifests:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in data.get("candidates", []):
            if not item.get("downloaded_file") or not item.get("url"):
                continue
            # A downloaded file is not a verified source. Re-promoting rejected
            # celebrity/background clips consumed the next run's probe budget.
            if not item.get("selected_for_zip") or item.get("rejection_reasons") or not item.get("editing_eligible", True):
                continue
            if not (path.parent / item['downloaded_file']).is_file():
                continue
            out.append(Candidate(url=item["url"], provider=item.get("provider", "cache"), title=item.get("title", ""),
                                 uploader=item.get("uploader", ""),
                                 query=item.get("query", ""), match_kind="cached-candidate", rights=item.get("rights", "unknown-check-before-reuse"),
                                 cached_path=str(path.parent/item['downloaded_file'])))
            if len(_dedupe(out)) >= limit:
                return _dedupe(out)[:limit]
    return _dedupe(out)[:limit]


def search_local_hints(settings: Settings, shortcode: str) -> list[Candidate]:
    """Operator shortlists still pass the normal download and visual gates."""
    path = settings.source_dir / 'source-hints.json'
    if not path.is_file():
        return []
    try:
        rows = json.loads(path.read_text(encoding='utf-8')).get(shortcode, [])
    except (OSError, ValueError):
        return []
    return [Candidate(url=row['url'], provider='operator-web-search',
                      title=str(row.get('title', ''))[:240], query=str(row.get('query', ''))[:120],
                      match_kind='operator-shortlist', rights='unknown-check-before-reuse',
                      cached_path=str(row.get('cached_file','')))
            for row in rows[:max(12, settings.source_max_candidates)]
            if isinstance(row, dict) and video_url(row.get('url', ''))]


def _dedupe(items: list[Candidate]) -> list[Candidate]:
    seen = set(); out = []
    for item in items:
        normalized = canonical_video_key(item.url)
        if normalized and normalized not in seen:
            seen.add(normalized); out.append(item)
    return out


def download_candidate(candidate: Candidate, out_dir: Path, index: int, max_mb: int,
                       cookie_file: Path | None = None, deadline: float | None = None,
                       js_runtime: str = '') -> Path | None:
    from .source_collection_access import collection_disabled
    from .source_browser_runtime import BrowserBusy
    candidate.download_attempted = False
    candidate.download_diagnostics = None
    if collection_disabled(candidate.platform):
        candidate.error = '사용자 설정으로 해당 플랫폼 수집 제외'
        candidate.download_attempted = False
        candidate.rejection_reasons = ['platform_disabled']
        return None
    if not video_url(candidate.url):
        candidate.error = '영상 상세 URL이 아닙니다.'
        candidate.rejection_reasons = ['not_video_url']
        return None
    stem = f"{index:02d}_{_safe_name(candidate.provider)}"
    parsed = urlparse(candidate.url)
    video_id = parse_qs(parsed.query).get("v", [""])[0] if "youtube.com" in parsed.netloc else parsed.path.strip("/").split("/")[-1]
    if candidate.platform == 'youtube':
        from .youtube_download import video_id as youtube_video_id
        video_id = youtube_video_id(candidate.url) or ''
    if video_id:
        cache_root = out_dir.parent.parent
        explicit = Path(candidate.cached_path).resolve() if candidate.cached_path else None
        files = ([explicit] if explicit and explicit.is_relative_to(cache_root.resolve()) else [])
        files.extend(cache_root.glob(f"*/videos/*_{video_id}.*"))
        cached = next((p for p in files
                       if p.parent != out_dir and p.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}
                       and p.is_file() and p.stat().st_size<=max_mb*1024*1024
                       and p.name!='reference.mp4' and (probe_video(p) or {}).get('width')), None)
        if cached:
            target = out_dir / f"{stem}_{video_id}{cached.suffix.lower()}"
            shutil.copy2(cached, target)
            candidate.download_attempted = False
            candidate.acquisition = 'local-cache'
            candidate.reused_from = str(cached)
            return target
    if SOURCE_COOLDOWNS.get(candidate.platform, 0) > time.time():
        candidate.error = "429 쿨다운 중인 플랫폼"
        candidate.download_attempted = False
        return None
    candidate.acquisition = 'network'
    if candidate.platform == 'youtube':
        from .config import load_settings
        from .youtube_download import download
        diagnostics = {'attempted':False, 'navigation_started':False}
        try:
            candidate.acquisition = 'existing-browser-playback'
            path = download(load_settings(), candidate.url,
                            out_dir / f'{stem}_{video_id}.mp4', max_mb * 1024 * 1024, diagnostics=diagnostics)
            if path:diagnostics['attempted'] = True  # A published network reception completed.
            return path
        except Exception as exc:
            from .source_browser_runtime import BrowserBusy
            if isinstance(exc,(BrowserBusy,ModelServiceUnavailable)):raise
            candidate.error = f'YouTube 현재 브라우저 영상 수신 실패: {str(exc)[:240]}'
            return None
        finally:
            candidate.download_attempted = bool(diagnostics.get('attempted'))
            from .source_attempts import transfer_diagnostics
            candidate.download_diagnostics = transfer_diagnostics(diagnostics)
    if candidate.platform == 'tiktok':
        from .config import load_settings
        from .tikvideo_download import with_fallback as download
        diagnostics = {'attempted':False, 'navigation_started':False}
        try:
            path = download(load_settings(), candidate.url,
                            out_dir / f'{stem}_{video_id}.mp4', max_mb * 1024 * 1024, diagnostics=diagnostics)
            if path:diagnostics['attempted'] = True
            return path
        except Exception as exc:
            from .source_browser_runtime import BrowserBusy
            if isinstance(exc,(BrowserBusy,ModelServiceUnavailable)):raise
            candidate.error = f'TikTok 현재 브라우저 영상 수신 실패: {str(exc)[:240]}'
            return None
        finally:
            candidate.download_attempted = bool(diagnostics.get('attempted')
                or (diagnostics.get('fallback') or {}).get('attempted'))
            from .source_attempts import transfer_diagnostics
            candidate.download_diagnostics = transfer_diagnostics(diagnostics)
    from .source_urls import lazada_video_id
    vendor_id = lazada_video_id(candidate.url)
    if vendor_id:
        from .public_vendor import download
        try:
            candidate.download_attempted = True
            return download(candidate.url, out_dir / f'{stem}_{vendor_id}.mp4',
                            max_mb * 1024 * 1024)
        except (OSError, ValueError, requests.RequestException) as exc:
            if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code == 429:
                SOURCE_COOLDOWNS[candidate.platform] = time.time() + 60
            candidate.error = f'공개 판매처 영상 수신 실패: {type(exc).__name__}'
            return None
    if candidate.provider == "pexels":
        target = out_dir / f"{stem}.mp4"
        for attempt in range(3):
            try:
                request_pause()
                candidate.download_attempted = True
                with requests.get(candidate.url, stream=True, timeout=(30, 60)) as r:
                    if r.status_code == 429:
                        SOURCE_COOLDOWNS[candidate.platform] = time.time() + 60
                        candidate.error = "429 제한 · 60초 쿨다운"
                        return None
                    r.raise_for_status(); size = 0
                    with target.open("wb") as f:
                        for chunk in r.iter_content(1024 * 256):
                            size += len(chunk)
                            if size > max_mb * 1024 * 1024:
                                raise RuntimeError("파일 크기 제한 초과")
                            f.write(chunk)
                return target
            except Exception as exc:  # noqa: BLE001
                if isinstance(exc,(BrowserBusy,ModelServiceUnavailable)):raise
                target.unlink(missing_ok=True); candidate.error = str(exc)[:240]
                if attempt < 2 and isinstance(exc, requests.RequestException):
                    time.sleep(2 ** attempt)
                    continue
                return None
    ytdlp = _executable("yt-dlp")
    if not ytdlp:
        candidate.error = "yt-dlp 실행 파일이 없습니다."
        return None
    template = str(out_dir / f"{stem}_%(id)s.%(ext)s")
    from .login_exchange import downloader_cookies
    cookie_file = downloader_cookies(cookie_file, candidate.platform, out_dir)
    command = [ytdlp, *ytdlp_pacing_args(), *_yt_runtime_args(js_runtime), *_yt_cookie_args(cookie_file), "--no-playlist", "--no-progress",
               "--restrict-filenames", "--write-info-json", "--max-filesize", f"{max_mb}M",
               "--socket-timeout", "15", "--retries", "1", "--fragment-retries", "1",
               "--extractor-retries", "1",
               "--format", "bv*[height<=1080]+ba/b[height<=1080]/b", "--merge-output-format", "mp4", "-o", template,
               "--", candidate.url]
    # Bilibili gets one resumable timeout retry; authentication errors still stop.
    is_bilibili = candidate.provider == "bilibili" or "bilibili.com" in candidate.url
    from .operation_progress import run_progress_command, NoProgressTimeout
    for attempt in range(3):
        request_pause()
        try:
            candidate.download_attempted = True
            result = run_progress_command(command, progress_dir=out_dir)
        except NoProgressTimeout as exc:
            candidate.error = str(exc)
            if is_bilibili and attempt == 0:
                continue  # Retry a stalled transfer once, retaining its partial file.
            return None
        diagnostic = (result.stderr or result.stdout or '').lower()
        if "429" in diagnostic or "too many requests" in diagnostic:
            SOURCE_COOLDOWNS[candidate.platform] = time.time() + 60
            candidate.error = "429 제한 · 60초 쿨다운"
            return None
        if result.returncode == 0 or any(word in diagnostic for word in ("login", "captcha", "drm", "private")):
            break
        # Unsupported/private/deleted content and format/extractor errors are
        # confirmed failures of this method; unchanged retries cannot repair it.
        transfer_error = bool(re.search(r'timed? out|timeout|connection (?:reset|aborted)|'
            r'temporary failure|temporarily unavailable|http error 5\d\d|remote end closed', diagnostic))
        if attempt < 2 and transfer_error:
            time.sleep(2 ** attempt)
            continue
        break
    info_file = next(iter(out_dir.glob(f"{stem}_*.info.json")), None)
    if info_file:
        try:
            info = json.loads(info_file.read_text(encoding="utf-8"))
            candidate.title = info.get("title") or candidate.title
            candidate.uploader = info.get("uploader") or info.get("channel") or ""
            candidate.url = info.get("webpage_url") or candidate.url
        except (OSError, json.JSONDecodeError):
            pass
    files = sorted(out_dir.glob(f"{stem}_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    video = next((p for p in files if p.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}
                  and (probe_video(p) or {}).get('width')), None)
    if not video:
        candidate.error = (result.stderr or result.stdout or '영상 파일을 받지 못했습니다.')[-350:].strip()
    return video


def create_contact_sheet(frames: list[Path], out: Path) -> None:
    if not frames:
        return
    thumbs = []
    for p in frames:
        with Image.open(p) as im:
            x = ImageOps.fit(im.convert("RGB"), (180, 320), method=Image.Resampling.LANCZOS)
            thumbs.append(x.copy())
    cols = min(4, len(thumbs)); rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 180, rows * 320), "white")
    for i, im in enumerate(thumbs): sheet.paste(im, ((i % cols) * 180, (i // cols) * 320))
    sheet.save(out, quality=88)


def find_sources(settings: Settings, shortcode: str, progress: Progress | None = None, *, search_request: str = '',
                 search_round: int = 0, previous_searches: list | None = None, exclude_urls: list | None = None,
                 search_context: dict | None = None) -> dict:
    from .source_policy import current_policy
    from .source_outcomes import platform_outcomes, failure_reason
    from .editing_adapter import _atomic_json
    if not re.fullmatch(r'[A-Za-z0-9_-]+', shortcode):
        raise ValueError('올바르지 않은 게시물 ID입니다.')
    policy = current_policy(settings)
    root = settings.source_dir / f"{shortcode}-{time.time_ns()}"
    root.mkdir(parents=True)
    receipt = {'job_id':root.name, 'created_at':int(time.time()), 'shortcode':shortcode,
               'status':'running', 'source_policy':policy, 'source_target':policy['minimum_total'],
               'audit_checkpoint':'preparation', 'execution_audit_available':True,
               'search_audit':[], 'candidates':[], 'platform_outcomes':platform_outcomes([], [], policy['platform_minimums'])}
    _atomic_json(root/'manifest.json', receipt)
    created = getattr(progress, 'source_attempt_created', None)
    if created:
        created(root/'manifest.json')
    phase = 'preparation'
    def report(message, pct):
        nonlocal phase
        phase = 'preparation' if pct < 32 else 'discovery' if pct < 50 else 'candidate_verification'
        if progress:
            progress(message, pct)
    from .studio_pause import bind_progress, pause_scope, StudioPaused
    bind_progress(report, progress)
    try:
        with pause_scope(report):
            return _find_sources(settings, shortcode, report, search_request=search_request,
                search_round=search_round, previous_searches=previous_searches, exclude_urls=exclude_urls,
                search_context=search_context, root=root, policy=policy)
    except Exception as exc:
        # Preserve the attempt even when reference/model preparation fails
        # before a platform is contacted. Never invent per-platform CAPTCHA.
        try:
            receipt = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
        receipt.update(status='paused' if isinstance(exc, StudioPaused) else 'failed',
                       failure={'stage':phase, 'type':type(exc).__name__,
                       'reason':'user_stopped' if isinstance(exc, StudioPaused) else failure_reason(str(exc), default='pipeline_failed')})
        if phase == 'discovery' and receipt.get('audit_checkpoint') in {'preparation','planned'}:
            # A provider may have been contacted before discovery returned.
            # Missing intermediate evidence means unknown, not unattempted.
            receipt.update(execution_audit_available=False, platform_outcomes={})
        _atomic_json(root/'manifest.json', receipt)
        raise


def _find_sources(settings, shortcode, progress, *, search_request, search_round, previous_searches,
                  exclude_urls, root, policy, search_context=None):
    from .studio_pause import bind_progress
    from .source_targets import candidate_batch, select_sources, tiktok_count, tiktok_coverage
    from .source_outcomes import platform_outcomes
    from .source_quality import editing_ready
    from .editing_adapter import _atomic_json
    tiktok_target = policy.get('platform_preferences', policy['platform_minimums']).get('tiktok', 0)
    progress = progress or (lambda _m, _p: None)
    post = _post(settings, shortcode)
    if not post.is_video and getattr(post, "kind", "") not in {"image","carousel"}:
        raise ValueError("지원하지 않는 게시물 종류입니다.")
    job_id = root.name
    frames_dir = root / "reference_frames"; candidates_dir = root / "videos"; compare_dir = root / "compare"
    candidates_dir.mkdir(parents=True); compare_dir.mkdir(parents=True)
    from .source_preparation import prior_bundle, save_bundle, query_policy, bundle_paths
    raw_transcript = _transcript_evidence(settings, shortcode)
    prepared,bundle_path = prior_bundle(settings,shortcode,post.caption,raw_transcript,search_context)
    if prepared:
        progress('저장된 기준 영상·프레임 SHA 검증 완료 · 준비 자료 재사용',20)
        reference=Path(prepared['reference']);frames=[Path(f) for f in prepared['frames']]
        contact_sheet=Path(prepared['sheet'])
    else:
        progress("기준 릴스를 가져오는 중", 8)
        reference = _download_reference(settings, post, root / "reference.mp4")
        progress("장면을 추출하는 중", 20)
        frames = extract_frames(reference, frames_dir)
        contact_sheet=root / "reference_contact_sheet.jpg"
        create_contact_sheet(frames, contact_sheet)
    transcript = copy.deepcopy(raw_transcript)
    if post.is_video and settings.source_transcribe_reference and not any(transcript.values()):
        from .transcript import extract_transcript
        try:
            extract_transcript(settings, shortcode, lambda message, pct: progress('검색 근거 분석 · ' + message, 20 + int(pct * .03)))
            transcript = _transcript_evidence(settings, shortcode)
            raw_transcript = copy.deepcopy(transcript)
        except Exception as exc:
            if isinstance(exc, ModelServiceUnavailable):
                raise
            transcript['analysis_note'] = f'음성 분석 실패({type(exc).__name__}): 캡션·화면 근거로 계속'
    progress("음성·화면·캡션에서 검색 주제와 행동을 분석하는 중", 24)
    verifier = OpenClipVerifier(settings, frames)
    verification_notes = [verifier.error] if verifier.error else []
    visual_queries = prepared.get('visual_product_queries',[]) if prepared else verifier.discover_product_queries()
    from .source_search.strategy import fresh_frames
    vision_audit = []
    if prepared:
        vision_candidates=[];vision_terms=prepared.get('google_vision_terms',[])
        verifier.product_evidence=prepared.get('openclip_product_evidence',[])
        verifier.subject_reference_indices=prepared.get('subject_reference_indices',[])
    else:
        vision_candidates, vision_terms = search_google_vision(settings,
            fresh_frames(frames, 'google-vision', previous_searches or []), settings.source_max_candidates, vision_audit)
    from .text_overlay import TextOverlayDetector
    overlay_detector = TextOverlayDetector(settings)
    if overlay_detector.note:
        verification_notes.append(overlay_detector.note)
    if transcript.get('analysis_note'):
        verification_notes.append(transcript['analysis_note'])
    if prepared:
        transcript=copy.deepcopy(prepared.get('transcript',transcript))
    elif transcript.get('reference_kind') not in {'screen_text', 'mixed'}:
        transcript['screen_text'] = ' '.join([transcript.get('screen_text', ''), overlay_detector.reference_text(frames)])
    reuse_plan=bool(prepared and prepared.get('query_policy')==query_policy())
    query_plan = copy.deepcopy(prepared['query_plan']) if reuse_plan else product_query_plan(post.caption, visual_queries, vision_terms, transcript, build_queries(post.caption))
    if not prepared:
        # A query-model capacity wait must retain completed media preparation.
        media_path,_=bundle_paths(settings,shortcode,post.caption,raw_transcript)
        save_bundle(media_path.with_suffix('.media.json'),post.caption,raw_transcript,reference,frames,contact_sheet,
                    query_policy='media-only',transcript=transcript,query_plan=query_plan,
                    visual_product_queries=visual_queries,google_vision_terms=vision_terms,
                    openclip_product_evidence=verifier.product_evidence,
                    subject_reference_indices=verifier.subject_reference_indices)
    if settings.source_query_model_enabled and not reuse_plan:
        from .source_planning import cached_enrich_plan
        query_plan = cached_enrich_plan(settings, query_plan, post.caption, transcript,
                                        reference_sha256=sha256_file(reference))
    from .source_search.planner import grounded_actions, choose_strategy, round_queries, annotate_audit
    if not reuse_plan:
        literal_actions = grounded_actions(query_plan, {'caption':post.caption, 'speech':transcript.get('speech',''),
                                                      'screen_text':transcript.get('screen_text','')})
        query_plan['query_details'] = [*literal_actions, *query_plan['query_details']]
        # Policy upgrades receive a separate immutable preparation receipt.
        _,bundle_path=bundle_paths(settings,shortcode,post.caption,raw_transcript)
        save_bundle(bundle_path,post.caption,raw_transcript,reference,frames,contact_sheet,
                    transcript=transcript,query_plan=query_plan,visual_product_queries=visual_queries,
                    google_vision_terms=vision_terms,openclip_product_evidence=verifier.product_evidence,
                    subject_reference_indices=verifier.subject_reference_indices)
    from .search_access import access_record, manual_required
    from .source_search.readiness import readiness_blocked, readiness_record
    context = {**(search_context or {}), 'blocked_routes':[p for p in ('tiktok','douyin','xiaohongshu','bilibili','google-lens','yandex-images')
                                                        if manual_required(access_record(settings.data_dir,p)) or readiness_blocked(settings.data_dir,p)],
               'rechecked_routes':[p for p in ('tiktok','douyin','xiaohongshu','bilibili') if readiness_record(settings.data_dir,p).get('recheck_requested')]}
    strategy = choose_strategy(query_plan, context, previous_searches)
    from .source_collection_access import disabled_platforms
    disabled = disabled_platforms(settings)
    strategy['routes'] = [route for route in strategy['routes'] if route not in disabled]
    ready_routes=(search_context or {}).get('ready_routes')
    if ready_routes is not None:
        unavailable=[route for route in strategy['routes'] if route not in ready_routes]
        strategy['routes']=[route for route in strategy['routes'] if route in ready_routes]
        strategy['skipped_routes'].update({route:'현재 기존 경로 미준비 또는 미사용 범위 없음' for route in unavailable})
    strategy['skipped_routes'].update(disabled)
    query_plan['search_strategy'] = strategy
    progress('검색 전략 · ' + strategy['label'] + ' · ' + '; '.join(strategy['reasons']), 28)
    verification_notes.extend(query_plan.get('planning_notes', []))
    if settings.source_match_mode in {'product', 'functional'}:
        verifier.focus_subject(query_plan['products'])
    query_details = round_queries(query_plan, strategy)
    if search_request.strip():
        from .source_queries import feedback_queries, prioritize_tiktok_requests
        requested = feedback_queries(search_request)
        if not requested:
            verification_notes.append('긴 소스 검색 지시문을 검색어로 보내지 않았습니다. 짧은 검색어를 줄마다 입력하세요.')
        query_details = [{'query':q, 'language':language(q), 'origin':'user_feedback'} for q in requested] + query_details
        if requested:
            query_plan=prioritize_tiktok_requests(query_plan,requested)
            if query_plan.get('tiktok_operator_query_rejections'):
                verification_notes.append('TikTok 사용자 검색어의 명사·수식어 원본 근거 미확인 · '
                    +str(len(query_plan['tiktok_operator_query_rejections']))+'개 미전송')
    queries = [item["query"] for item in query_details]
    if not queries:
        verification_notes.append('근거 있는 텍스트 검색어를 생성하지 못함 · 이미지 검색만 가능; 빈 문자열로 텍스트 검색하지 않음')
    langs = ', '.join({'ko': '한국어', 'en': '영어', 'zh': '중국어'}.get(l, l) for l in sorted({d['language'] for d in query_details}))
    progress(f"{langs or '이미지'} 검색어 {len(queries)}개 준비 · 플랫폼 검색 중", 32)
    planned = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    planned.update(audit_checkpoint='planned', queries=queries, query_details=query_details,
                   search_strategy=strategy, product_evidence={k:v for k,v in query_plan.items() if k != 'query_details'})
    _atomic_json(root/'manifest.json', planned)
    from .source_search.discovery import discover
    from .source_search.triage import deferred_candidates, rank_candidates, discovery_duration_reasons
    pending = deferred_candidates(search_context,exclude_urls,settings.source_max_candidates)
    candidates, queries, browser_result, search_audit, tiktok_preference = discover(
        settings, shortcode, frames, queries, query_plan, vision_candidates, root,
        previous_searches, exclude_urls, progress, services=sys.modules[__name__], deferred=pending)
    search_audit[:0] = vision_audit
    annotate_audit(search_audit, strategy)
    def save_attempts(status='running'):
        _atomic_json(root/'manifest.json', {'job_id':job_id, 'created_at':int(time.time()), 'shortcode':shortcode,
            'status':status, 'source_policy':policy, 'source_target':policy['minimum_total'],
            'audit_checkpoint':'discovered', 'execution_audit_available':True,
            'queries':queries, 'query_details':query_details,
            'search_strategy':strategy,
            'product_evidence':{k:v for k,v in query_plan.items() if k != 'query_details'},
            'verification_notes':verification_notes,
            'search_audit':search_audit, 'candidates':[asdict(c) for c in candidates],
            'platform_outcomes':platform_outcomes(candidates, search_audit, policy['platform_minimums'])})
    save_attempts()
    candidates = _dedupe(candidates)
    already_checked = {canonical_video_key(url) for url in exclude_urls or [] if url}
    candidates = [c for c in candidates if canonical_video_key(c.url) not in already_checked]
    invalid_candidates = [c for c in candidates if not video_url(c.url)]
    for candidate in invalid_candidates:
        candidate.rejection_reasons = ['not_video_url']
    ranked = rank_candidates([c for c in candidates if video_url(c.url)],query_plan)
    candidates = candidate_batch(ranked, settings.source_max_candidates, tiktok_preference)
    progress(f"후보 {len(candidates)}개를 확인하는 중", 50)
    probed = 0
    attempted = 0
    embeddings = {}
    budget_stop = ''
    refinement_details = []
    refined = False
    platform_seconds = {}
    probe_progress = 50
    for i, candidate in enumerate(candidates, 1):
        from .source_collection_access import collection_disabled
        if collection_disabled(candidate.platform, settings):
            candidate.download_attempted = False
            candidate.rejection_reasons = ['platform_disabled']
            save_attempts()
            continue
        preliminary = discovery_duration_reasons(candidate,max(180,settings.source_long_video_max_seconds))
        if preliminary:
            candidate.download_attempted = False
            candidate.rejection_reasons = preliminary
            save_attempts()
            continue
        if attempted >= max(1, settings.source_max_attempts):
            budget_stop = 'attempt_limit'
            break
        if probed >= max(settings.source_max_downloads, settings.source_max_probe_downloads):
            budget_stop = 'probe_limit'
            break
        skip_reason = 'platform_cooldown' if SOURCE_COOLDOWNS.get(candidate.platform, 0) > time.time() else ''
        candidate_started = time.monotonic()
        path = None
        candidate.download_attempted = not bool(skip_reason)
        if not skip_reason:
            candidate.download_budget_seconds = None  # Historical field only; no time allocation.
            attempted += 1
            save_attempts()
            with charge_platform_probe(platform_seconds, candidate.platform):
                try:
                    path = download_candidate(candidate, candidates_dir, i, settings.source_max_file_mb,
                                              settings.source_browser_cookie_file,
                                              js_runtime=settings.source_ytdlp_js_runtime)
                except (OSError, subprocess.SubprocessError, ValueError) as exc:
                    candidate.error = f'{type(exc).__name__}: {str(exc)[:240]}'
                finally:
                    if candidate.download_attempted is False:
                        attempted -= 1  # Saved access gates/local reuse did not send this URL.
                    save_attempts()
        if path:
            probed += 1
            candidate.downloaded_file = str(path.relative_to(root))
            candidate.video_meta = probe_video(path)
            candidate.rejection_reasons = media_format_reasons(candidate.video_meta, max(180, settings.source_long_video_max_seconds))
            if not candidate.rejection_reasons:
                if 180 < (candidate.video_meta.get('duration') or 0) <= settings.source_long_video_max_seconds:
                    from .source_segments import extract_relevant_segment
                    try:
                        segment = extract_relevant_segment(settings, path, candidate.video_meta, verifier,
                                                           root / 'segments' / f'{i:02d}')
                        if segment:
                            candidate.original_downloaded_file = candidate.downloaded_file
                            path, candidate.source_interval = segment
                            candidate.downloaded_file = str(path.relative_to(root))
                            candidate.video_meta = probe_video(path)
                    except (OSError, subprocess.SubprocessError, ValueError) as exc:
                        candidate.error = f'긴 영상 구간 검사 실패: {type(exc).__name__}'
                candidate.rejection_reasons = media_format_reasons(candidate.video_meta)
                if not candidate.rejection_reasons:
                    from .source_presentation import format_warnings, portrait_geometry
                    candidate.format_warnings = format_warnings(candidate.video_meta)
                    candidate.portrait_geometry = portrait_geometry(candidate.video_meta)
                    candidate.presentation_review_required = True
                    candidate.file_sha256 = sha256_file(path)
                    try:
                        candidate.hash_similarity = compare_videos(frames, path, compare_dir / f"{i:02d}")
                        candidate_frames = sorted((compare_dir / f"{i:02d}").glob("candidate_*.jpg"))
                        candidate.semantic_similarity = verifier.score(candidate_frames)
                        if verifier.last_embedding is not None:
                            embeddings[id(candidate)] = verifier.last_embedding.clone()
                        candidate.frame_hashes = [f"{dhash(frame):064x}" for frame in candidate_frames]
                        candidate.similarity = round(
                            candidate.hash_similarity if candidate.semantic_similarity is None else
                            candidate.hash_similarity * .55 + candidate.semantic_similarity * .45, 4,
                        )
                        candidate.match_quality = ("same-scene-likely" if candidate.similarity >= .82 and candidate.hash_similarity >= .80 else
                                                   "close-match" if candidate.similarity >= .72 else "topic-related")
                        if settings.source_match_mode == 'product' and (candidate.semantic_similarity or 0) >= .82 and candidate.hash_similarity < .72:
                            candidate.match_quality = 'product-related'
                        overlay = overlay_detector.analyze(candidate_frames)
                        for key, value in overlay.items():
                            if hasattr(candidate, key):
                                setattr(candidate, key, value)
                        clean_score = {"clean-source": 1.0, "light-overlay": .62,
                                       "edited-with-text": .2, "unknown": .45}[candidate.source_quality]
                        semantic = candidate.semantic_similarity if candidate.semantic_similarity is not None else candidate.hash_similarity
                        candidate.source_score = round(clean_score * .55 + (semantic or 0) * .30
                                                       + (candidate.hash_similarity or 0) * .15
                                                       - (.08 if (candidate.video_meta.get("width") or 0) > (candidate.video_meta.get("height") or 0) else 0)
                                                       - min(.06, .02 * len(candidate.format_warnings))
                                                       + (.03 if candidate.rights == "pexels-license" else 0), 4)
                        preview = root / "previews" / f"{i:02d}.jpg"
                        preview.parent.mkdir(exist_ok=True)
                        create_contact_sheet(sorted((compare_dir / f"{i:02d}").glob("candidate_*.jpg"))[:8], preview)
                        candidate.preview_file = str(preview.relative_to(root))
                        if settings.source_match_mode == 'functional':
                            candidate.similarity_warnings = relevance_reasons(candidate, candidate.video_meta, 'product')
                            # Review selected footage once in Studio using the
                            # exact overlay-approved intervals. No three-item
                            # rescue cap and no score gate before visual review.
                            candidate.relevance_review_required = True
                        candidate.rejection_reasons = [*relevance_reasons(candidate, candidate.video_meta, settings.source_match_mode),
                                                       *reuse_reasons(candidate)]
                    except Exception as exc:  # noqa: BLE001
                        if isinstance(exc, ModelServiceUnavailable):
                            raise
                        candidate.error = f"유사도 계산 실패: {exc}"
                        candidate.rejection_reasons = ["verification_failed"]
        else:
            candidate.rejection_reasons = candidate.rejection_reasons or [skip_reason or (
                'not_attempted' if candidate.download_attempted is False else 'download_failed')]
        save_attempts()
        probe_progress = max(probe_progress, min(88, 50 + int(i / max(1, len(candidates)) * 38)))
        progress(f"후보 다운로드/검증 {i}/{len(candidates)}", probe_progress)
        # 부족한 경우 플랫폼별 미사용 검색어와 검증된 제목 근거로 한 차례 확장한다.
        usable = len(select_valid_candidates(copy.deepcopy([c for c in candidates
                     if editing_ready(asdict(c))]), settings.source_max_downloads))
        if ((i == len(candidates) or i == min(20, len(candidates))) and not refined
                and (sum(bool(c.downloaded_file) and not c.rejection_reasons for c in candidates) < settings.source_max_downloads
                     if policy.get('completion_mode') == 'scene_duration' else
                     usable < policy['minimum_total'] or tiktok_count(candidates, settings.source_max_downloads) < tiktok_target)
                and settings.source_refine_max_candidates > 0
                and attempted < settings.source_max_attempts
                and probed < max(settings.source_max_downloads, settings.source_max_probe_downloads)):
            refined = True
            titles = [c.title for c in candidates if c.title and (c.semantic_similarity or 0) >= .82][:3]
            if titles or query_details:
                refinement_strategy = {**strategy, 'phase':'clean_action' if strategy['phase'] == 'core_action' else 'scene_discovery',
                                       'label':'후보 검증 후 다른 영상 조건으로 추가 검색'}
                refinement_details = [] if strategy['phase'] == 'scene_discovery' else round_queries(query_plan, refinement_strategy)
                extra_queries = list(dict.fromkeys(d['query'] for d in refinement_details))
                if extra_queries:
                    probe_progress = max(probe_progress, 80)
                    progress((f'후보 확보 {sum(bool(c.downloaded_file) and not c.rejection_reasons for c in candidates)}개 · 장면 검토 대기 · 추가 검색 중'
                              if policy.get('completion_mode') == 'scene_duration' else
                              f'유효 소스 {usable}개 · TikTok {tiktok_count(candidates, settings.source_max_downloads)}/{tiktok_target}개 · 추가 검색 중'), 80)
                    search_started = time.monotonic()
                    extra = []
                    if settings.source_browser_search:
                        from .browser_search import browser_search
                        additional = browser_search(settings, [], extra_queries, settings.source_refine_max_candidates,
                                                    root / 'refinement_debug', previous_searches=[*(previous_searches or []), *search_audit],
                                                    routes=strategy['routes'],
                                                    provider_queries={'tiktok': tiktok_product_queries(query_plan, extra_queries)},
                                                    progress=bind_progress(lambda msg: progress('추가 검색 · ' + msg, 80), progress))
                        extra += [Candidate(**item) for item in additional['candidates']]
                        search_audit.extend(additional.get('searches', []))
                        browser_result['notes'].extend(additional.get('notes', []))
                    from .source_search.strategy import fresh_queries
                    if not settings.source_browser_search and 'youtube' in strategy['routes']:
                        extra += search_youtube(platform_queries(fresh_queries(extra_queries, 'youtube', [*(previous_searches or []), *search_audit]), 'youtube', settings.source_queries_per_platform), settings.source_refine_max_candidates,
                                               settings.source_browser_cookie_file, search_audit, settings.source_ytdlp_js_runtime)
                    if not settings.source_browser_search and 'bing' in strategy['routes']:
                        extra += search_bing(platform_queries(fresh_queries(extra_queries, 'bing', [*(previous_searches or []), *search_audit]), 'youtube', 3), settings.source_refine_max_candidates, search_audit)
                    annotate_audit(search_audit, refinement_strategy)
                    seen = {canonical_video_key(c.url) for c in candidates} | already_checked
                    novel = [c for c in _dedupe(extra) if video_url(c.url) and canonical_video_key(c.url) not in seen]
                    # Probe fresh search intents before reusing the remaining candidate slots.
                    candidates[i:i] = candidate_batch(rank_candidates(novel,query_plan), max(0, min(settings.source_refine_max_candidates,
                                                                         settings.source_max_attempts - attempted)), tiktok_target)
    candidates.sort(key=lambda c: (c.downloaded_file != "", c.source_score or 0, c.similarity or 0), reverse=True)
    candidates.extend(invalid_candidates)
    selected = select_sources(candidates, settings.source_max_downloads, tiktok_target,
                              required=bool(policy.get('platform_minimums')))
    coverage = tiktok_coverage(candidates, search_audit, tiktok_target, budget_stop)
    downloaded = len(selected)
    quality_counts = {key: sum(c.selected_for_zip and c.source_quality == key for c in candidates)
                      for key in ("clean-source", "light-overlay", "edited-with-text", "unknown")}
    manifest = {
        "job_id": job_id, "created_at": int(time.time()), "shortcode": shortcode, "reference_url": post.url,
        "status":"completed", "source_policy":policy,
        "audit_checkpoint":"completed", "execution_audit_available":True,
        "caption": post.caption, "queries": queries, "query_details": query_details,
        "product_evidence": {key: value for key, value in query_plan.items() if key != 'query_details'},
        "match_mode": settings.source_match_mode, "budget_stop": budget_stop,
        "refinement_query_details": refinement_details,
        "search_strategy": strategy,
        "search_audit": search_audit, "search_policy_version": 6,
        "source_target": policy['minimum_total'],
        "platform_targets": {"tiktok": coverage} if policy.get('platform_minimums') else {},
        "platform_preferences": {"tiktok": {**coverage, 'required': False}} if tiktok_target else {},
        "platform_outcomes": platform_outcomes(candidates, search_audit, policy['platform_minimums'], budget_stop),
        "quota_ready": False if policy.get('completion_mode') == 'scene_duration' else
                       sum(editing_ready(asdict(c)) for c in selected) >= policy['minimum_total'] and coverage['status'] == 'met',
        "review_pending": sum(c.relevance_review_required or c.presentation_review_required for c in selected),
        "visual_product_queries": visual_queries, "openclip_product_evidence": verifier.product_evidence,
        "subject_reference_indices": verifier.subject_reference_indices,
        "google_vision_terms": vision_terms,
        "reference_frames": [os.path.relpath(p, root) for p in frames],
        "preparation_bundle_path": str(bundle_path.resolve()),
        "preparation_bundle_sha256": sha256_file(bundle_path),
        "reference_contact_sheet": os.path.relpath(contact_sheet,root),
        "browser_notes": browser_result["notes"], "verification_notes": verification_notes,
        "candidates": [asdict(c) for c in candidates], "downloaded": downloaded,
        "probe_attempts": attempted, "probed_downloads": probed,
        "platform_probe_seconds": {k: round(v, 2) for k, v in platform_seconds.items()},
        "quality_counts": quality_counts,
        "funnel": {platform: {'discovered': sum(c.platform == platform for c in candidates),
                             'received': sum(c.platform == platform and bool(c.downloaded_file) for c in candidates),
                             'selected': sum(c.platform == platform and c.selected_for_zip for c in candidates)}
                   for platform in sorted({c.platform for c in candidates})},
        "rights_notice": "각 파일의 저작권과 상업적 이용 허가를 원 출처에서 확인한 뒤 사용하세요. Pexels 항목만 Pexels 라이선스로 표시됩니다.",
    }
    _atomic_json(root / "manifest.json", manifest)
    # 기준 릴스는 분석용일 뿐 소스 ZIP에는 넣지 않는다.
    zip_path = root / f"sources_{shortcode}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(root / "manifest.json", "manifest.json")
        z.write(contact_sheet, "reference_contact_sheet.jpg")
        for c in candidates:
            if c.selected_for_zip:
                folder = {"clean-source": "clean_sources", "light-overlay": "review_needed",
                          "edited-with-text": "edited_references", "unknown": "unclassified"}[c.source_quality]
                z.write(root / c.downloaded_file, f"{folder}/{Path(c.downloaded_file).name}")
            if c.selected_for_zip and c.preview_file:
                z.write(root / c.preview_file, c.preview_file)
    progress(f"후보 확보 완료 · {len(selected)}개 · 장면·사용 가능 길이 검토 대기 · TikTok 선호 {tiktok_target}개", 100)
    manifest["zip_path"] = str(zip_path)
    return manifest


class SourceJobManager:
    def __init__(self, settings: Settings, job_queue=None):
        from .job_queue import JobQueue
        self.settings = settings
        self.queue = job_queue or JobQueue(settings)
        self.queue.register("source", lambda shortcode, progress: find_sources(settings, shortcode, progress))

    def start(self, shortcode: str) -> dict:
        return self.queue.start("source", shortcode)

    def get(self, job_id: str) -> dict | None:
        return self.queue.get(job_id)
