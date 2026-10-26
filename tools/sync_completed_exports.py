"""Copy completed publication media without starting production or changing its DB.

Run manually at the authorized completion point; this tool installs no scheduler.
Configuration and the recovery journal live in data/local-services, outside Git.
Only paired, verified completed
exports and the matching active thumbnail revision are eligible.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
import uuid

KST = timezone(timedelta(hours=9))


def read_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def local_file(root, value):
    if not value:
        return None
    path = Path(value).resolve()
    return path if path.is_relative_to(root) and path.is_file() and path.stat().st_size else None


def stamp(paths):
    return [[str(p), p.stat().st_size, p.stat().st_mtime_ns] for p in paths]


def topic_name(title):
    text = re.sub(r'[^\w\s가-힣-]', ' ', str(title), flags=re.UNICODE)
    return re.sub(r'\s+', '_', ' '.join(text.split()[:4]))[:28].strip('_. ') or '영상'


def candidates(root, enabled_after):
    database = root / 'studio' / 'studio.sqlite3'
    if not database.is_file():
        return
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
        states = db.execute('SELECT shortcode,state FROM tasks').fetchall()
    for code, raw in states:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', code):
            continue
        state = json.loads(raw)
        completed = []
        for run in state.get('runs', []):
            if run.get('status') != 'completed':
                continue
            for edit in state.get('edits', []):
                if edit.get('id') == run.get('artifacts', {}).get('edit_id') and edit.get('export_verified'):
                    completed.append((run, edit))
        if not completed:
            continue
        run, edit = next((pair for pair in completed if pair[0]['id'] == state.get('latest_completed_run_id')),
                         max(completed, key=lambda pair: pair[0].get('completed') or 0))
        finished = run.get('completed') or 0
        video = local_file(root, edit.get('export_path') or edit.get('preview_path'))
        cover = local_file(root, edit.get('cover_path'))
        version = edit['id']
        active_path = root / 'post-preparations' / code / 'active.json'
        active = read_json(active_path, {})
        if active.get('source_edit_id') == edit['id']:
            # Never fall back to an older cover if an active revision is incomplete.
            video, cover = (local_file(root, active.get(k)) for k in ('final', 'cover'))
            finished = max(finished, active.get('updated') or 0)
            version = active.get('version') or version
        if not video or not cover or finished < enabled_after:
            continue
        if video.suffix.lower() != '.mp4' or cover.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
            continue
        yield {'code': code, 'run': run['id'], 'version': version, 'finished': finished,
               'title': state.get('title') or code, 'paths': [video, cover],
               'active_path': active_path, 'active': active}


def export_pair(item, destination, journal, journal_path):
    original_stamp = stamp(item['paths'])
    key = hashlib.sha256(json.dumps([item['code'], item['run'], item['version'], original_stamp]).encode()).hexdigest()
    entries = journal.setdefault('entries', {})
    receipt = entries.get(key)
    if receipt and receipt.get('status') == 'complete':
        # A disconnected drive or missing output must not silently count as saved.
        outputs = [Path(p) for p in receipt['outputs']]
        if all(p.is_file() for p in outputs) and stamp(outputs) == receipt.get('output_stamp'):
            return False
    if not receipt:
        day = datetime.fromtimestamp(item['finished'], KST).strftime('%Y-%m-%d')
        folder = destination / day
        folder.mkdir(parents=True, exist_ok=True)
        base = day + '_' + topic_name(item['title'])
        number = 1
        reserved = {p.casefold() for row in entries.values() for p in row['outputs']}
        while True:
            name = base + (f'_{number:02d}' if number > 1 else '')
            outputs = [folder / (name + '.mp4'), folder / (name + '_썸네일' + item['paths'][1].suffix.lower())]
            if not any(p.exists() or str(p).casefold() in reserved for p in outputs):
                break
            number += 1
        receipt = {'status': 'pending', 'outputs': [str(p) for p in outputs],
                   'sizes': [p.stat().st_size for p in item['paths']],
                   'sha256': [digest(p) for p in item['paths']], 'code': item['code'], 'version': item['version']}
        entries[key] = receipt
        save_json(journal_path, journal)
    staged = []
    try:
        for source, output, expected in zip(item['paths'], receipt['outputs'], receipt['sha256']):
            output = Path(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_name('.' + output.name + '.' + uuid.uuid4().hex + '.partial')
            staged.append((temporary, output, expected))
            shutil.copyfile(source, temporary)
            if digest(temporary) != expected:
                raise OSError('복사 파일 검증 실패: ' + output.name)
        if stamp(item['paths']) != original_stamp or read_json(item['active_path'], {}) != item['active']:
            raise OSError('복사 중 현재 영상/썸네일이 변경되어 다음 확인 때 다시 저장합니다.')
        for temporary, output, expected in staged:
            if output.exists():
                if digest(output) != expected:
                    raise FileExistsError('기존 파일을 덮어쓰지 않았습니다: ' + str(output))
            else:
                # Windows rename publishes a whole file and refuses to overwrite.
                # POSIX rename overwrites, so use an exclusive hard link there.
                if os.name == 'nt':
                    os.rename(temporary, output)
                else:
                    os.link(temporary, output)
        receipt.update(status='complete', saved_at=time.time(),
                       output_stamp=stamp([Path(p) for p in receipt['outputs']]))
        save_json(journal_path, journal)
        return True
    finally:
        for temporary, _, _ in staged:
            temporary.unlink(missing_ok=True)


def sync(config_path):
    config = read_json(config_path)
    root, destination = Path(config['data_dir']).resolve(), Path(config['destination'])
    journal_path = config_path.with_name('completed-export-journal.json')
    status_path = config_path.with_name('completed-export-status.json')
    errors, copied, ready = [], 0, 0
    try:
        # Do not create a replacement drive/folder when the requested destination is offline.
        if not destination.is_dir():
            raise OSError('저장 위치 연결을 확인하세요: ' + str(destination))
        journal = read_json(journal_path, {'entries': {}})
        for item in candidates(root, config['enabled_after']):
            ready += 1
            try:
                copied += bool(export_pair(item, destination, journal, journal_path))
            except Exception as error:
                errors.append(item['code'] + ': ' + str(error))
    except Exception as error:
        errors.append(str(error))
    result = {'checked_at': datetime.now(KST).isoformat(), 'destination': str(destination),
              'eligible_pairs': ready, 'copied_pairs': copied, 'errors': errors}
    save_json(status_path, result)
    return result


def run_once(config_path):
    """Also exclude overlapping manual invocations on the installed Windows PC."""
    with config_path.with_name('completed-export.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            if not lock.seek(0, os.SEEK_END):
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return {'errors': [], 'skipped': 'another export check is running'}
        return sync(config_path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    result = run_once(args.config.resolve())
    # pythonw has no stdout; the status JSON remains available in both modes.
    import sys
    if sys.stdout:
        print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(1 if result['errors'] else 0)
