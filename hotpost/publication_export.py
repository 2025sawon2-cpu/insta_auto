"""Copy a verified publication video and its applied cover using PC-local rules."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


def rules_path(project=ROOT):
    """Linked worktrees share the original clone's local rules, never a remote path."""
    project = Path(project)
    if (project / '.git').is_file():
        common = subprocess.check_output(
            ['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],
            cwd=project, text=True, encoding='utf8').strip()
        project = Path(common).parent
    return project / 'local' / 'video-storage.json'


def read_rules(path=None):
    path = Path(path) if path else rules_path()
    if not path.is_file():
        raise ValueError('이 PC의 local/video-storage.json 저장 위치를 먼저 설정하세요.')
    value = json.loads(path.read_text('utf8'))
    destination = value.get('destination')
    if not isinstance(destination, str) or not destination.strip() or not Path(destination).is_absolute():
        raise ValueError('이 PC의 저장 위치는 절대 경로여야 합니다.')
    topics = value.get('topics', {})
    if not isinstance(topics, dict) or any(not isinstance(topic, str) for topic in topics.values()):
        raise ValueError('PC별 topics는 게시물 코드와 짧은 주제명의 목록이어야 합니다.')
    return Path(destination), value


def configure(destination, path=None):
    path = Path(path) if path else rules_path()
    destination = Path(destination)
    if not destination.is_absolute():
        raise ValueError('저장 위치는 절대 경로로 지정하세요.')
    # A missing mapped drive must not silently create a similarly named local path.
    if not Path(destination.anchor).is_dir():
        raise ValueError('저장 드라이브 연결을 먼저 확인하세요.')
    destination.mkdir(parents=True, exist_ok=True)
    value = json.loads(path.read_text('utf8')) if path.is_file() else {}
    value['destination'] = str(destination)
    value.setdefault('topics', {})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf8')
    local_document = path.parent / 'VIDEO_STORAGE.md'
    if local_document.is_file():
        document = local_document.read_text('utf8')
        lines = document.splitlines()
        old = next((line for line in lines if line.startswith('- 저장 위치: ')), None)
        updated = f'- 저장 위치: `{destination}`'
        local_document.write_text(document.replace(old, updated, 1) if old else document + '\n' + updated + '\n', 'utf8')
        return destination
    local_document.write_text(
        '# 이 PC의 완성 영상 저장 규칙\n\n'
        f'- 저장 위치: `{destination}`\n'
        '- 기준 설정: 같은 폴더의 `video-storage.json`. 이 폴더 전체는 Git에서 제외한다.\n'
        '- 영상 완료 및 썸네일 변경 완료 뒤 공통 저장 도구로 현재 검증본과 실제 적용 썸네일을 함께 저장한다.\n'
        '- 날짜 폴더는 한국 시간 `YYYY-MM-DD`, 파일은 `YYYYMMDD_간단한주제명.mp4`와 '
        '`YYYYMMDD_간단한주제명_썸네일.png`다. 이미지 확장자는 실제 원본을 따른다.\n'
        '- 같은 파일 쌍은 중복 복사하지 않고, 내용이 다른 기존 파일은 보존하고 `_02`부터 번호를 붙인다.\n'
        '- 복사 후 원본과 두 파일의 SHA256이 같은지 확인한다. 저장 실패를 완료로 보고하지 않는다.\n'
        '- 주제명은 명시 입력 또는 `topics`의 게시물별 간단한 이름을 사용한다. 공통 절차는 '
        '`../docs/LOCAL_VIDEO_STORAGE.md`를 읽는다.\n', 'utf8')
    return destination


def digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def short_topic(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', str(value))
    value = re.sub(r'\s+', '_', value).strip(' ._')[:24].rstrip(' ._')
    if not value:
        raise ValueError('간단한 주제명을 지정하세요.')
    return value


def validate_video(path):
    result = subprocess.run(
        [shutil.which('ffprobe') or 'ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(path)],
        check=True, capture_output=True, text=True, encoding='utf8', timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    streams = json.loads(result.stdout)['streams']
    video = next((stream for stream in streams if stream['codec_type'] == 'video'), {})
    if (video.get('codec_name') != 'h264' or video.get('pix_fmt') != 'yuv420p'
            or video.get('profile') not in ('Baseline', 'Constrained Baseline', 'Main', 'High')):
        raise ValueError('게시용 H.264/yuv420p 호환 영상인지 확인하세요. 저장 도구는 재인코딩하지 않습니다.')
    if any(stream.get('codec_name') != 'aac' for stream in streams if stream['codec_type'] == 'audio'):
        raise ValueError('게시용 영상의 음성은 AAC여야 합니다.')


def save_current(service, code, *, topic=None, config=None, now=None, qa_record=None):
    from .post_preparation import shortcode
    code = shortcode(code)
    destination, rules = read_rules(config)
    source = service.source(code)
    video, cover = source['media']['final'], source['media']['cover']
    if not source['run_id'] or not source['edit_id'] or not video or not cover:
        raise ValueError('검증된 완성 영상과 실제 적용 썸네일이 모두 있어야 저장할 수 있습니다.')
    from .final_qa import validate as validate_final_qa
    qa = validate_final_qa(qa_record, video_id=code, run_id=source['run_id'],
                           edit_id=source['edit_id'], video=video, cover=cover)
    topic = short_topic(topic or rules.get('topics', {}).get(code, ''))
    validate_video(video)
    hashes = [digest(video), digest(cover)]
    when = now or datetime.now(KST)
    if when.tzinfo is None:
        raise ValueError('저장 시각에는 시간대가 필요합니다.')
    when = when.astimezone(KST)
    day = destination / when.strftime('%Y-%m-%d')
    day.mkdir(parents=True, exist_ok=True)
    base = when.strftime('%Y%m%d') + '_' + topic
    suffix = cover.suffix.lower()
    if suffix not in ('.png', '.jpg', '.jpeg', '.webp'):
        raise ValueError('지원하는 썸네일 이미지 파일이 필요합니다.')
    # The directory lock coordinates separate agents/processes on this destination.
    lock = destination / '.video-export.lock'
    try:
        lock.mkdir()
    except FileExistsError:
        raise ValueError('다른 저장 작업이 진행 중입니다. 기존 저장 결과를 확인한 뒤 다시 실행하세요.') from None
    try:
        for number in range(1, 10000):
            stem = base + (f'_{number:02}' if number > 1 else '')
            targets = [day / (stem + '.mp4'), day / (stem + '_썸네일' + suffix)]
            if all(path.is_file() for path in targets) and [digest(path) for path in targets] == hashes:
                validate_final_qa(qa_record, video_id=code, run_id=source['run_id'],
                                  edit_id=source['edit_id'], video=video, cover=cover)
                return {'status': 'already_saved', 'video': str(targets[0]), 'thumbnail': str(targets[1]), 'sha256': hashes}
            if any(path.exists() for path in targets):
                continue
            # Verify the pair before exposing final filenames on a network drive.
            with tempfile.TemporaryDirectory(prefix='.video-export-', dir=day) as staging:
                staged = [Path(staging) / 'video.mp4', Path(staging) / ('cover' + suffix)]
                for original, temporary, expected in zip((video, cover), staged, hashes):
                    shutil.copyfile(original, temporary)
                    if digest(temporary) != expected or digest(original) != expected:
                        raise ValueError('복사 중 파일이 바뀌었거나 검증에 실패했습니다. 완료로 처리하지 않았습니다.')
                # Refresh current source after I/O so a changed applied cover cannot be mislabeled.
                current = service.source(code)
                if (current['media'] != source['media'] or current['edit_id'] != source['edit_id']
                        or current.get('media_version') != source.get('media_version')):
                    raise ValueError('저장 중 현재 완성본이 변경됐습니다. 최신 결과로 다시 저장하세요.')
                validated = validate_final_qa(qa_record, video_id=code, run_id=source['run_id'],
                                              edit_id=source['edit_id'], video=video, cover=cover)
                if validated['record_sha256'] != qa['record_sha256']:
                    raise ValueError('저장 중 최종 QA 기록이 변경됐습니다. 다시 검토하세요.')
                for temporary, target in zip(staged, targets):
                    # Exclusive creation protects unrelated files even from non-cooperating writers.
                    with target.open('xb') as output, temporary.open('rb') as input_file:
                        shutil.copyfileobj(input_file, output)
                    if digest(target) != digest(temporary):
                        raise ValueError('저장 파일 검증에 실패했습니다. 완료로 처리하지 않았습니다.')
            return {'status': 'saved', 'video': str(targets[0]), 'thumbnail': str(targets[1]), 'sha256': hashes}
        raise ValueError('같은 날짜와 주제의 저장 파일이 너무 많습니다. 주제명을 구체화하세요.')
    finally:
        lock.rmdir()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='PC-local rules file; normally auto-detected')
    commands = parser.add_subparsers(dest='command', required=True)
    setup = commands.add_parser('configure')
    setup.add_argument('destination', type=Path)
    save = commands.add_parser('save')
    save.add_argument('shortcode')
    save.add_argument('--topic', help='Short subject, without a date or file extension')
    save.add_argument('--qa-record', type=Path, required=True, help='Producer final QA JSON for the current video and cover')
    args = parser.parse_args()
    try:
        if args.command == 'configure':
            print(json.dumps({'destination': str(configure(args.destination, args.config))}, ensure_ascii=False))
        else:
            from .config import load_settings
            from .post_preparation import PostPreparation
            result = save_current(PostPreparation(load_settings()), args.shortcode, topic=args.topic,
                                  config=args.config, qa_record=args.qa_record)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
