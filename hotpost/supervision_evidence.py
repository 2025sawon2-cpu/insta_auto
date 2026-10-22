"""Read-only, task-scoped useful-progress snapshots for durable supervision.

The caller MUST seed the first snapshot as its baseline and retain per-key high
water marks. This collector is stateless: observing an existing file, restarting
the supervisor, or seeing a smaller counter is never fresh progress by itself.
No process liveness, log timestamps, messages, or database revisions are progress.
"""
from __future__ import annotations

import hashlib
from contextlib import closing
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import sqlite3
import time

MAX_JSON_BYTES = 2 * 1024 * 1024
MEDIA = {'.mp4', '.webm', '.mkv', '.wav', '.jpg', '.jpeg', '.png'}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _inside(path, root):
    try:
        path = Path(path).resolve()
        return path if path.is_relative_to(root.resolve()) else None
    except (OSError, TypeError, ValueError):
        return None


def _small_json(path, errors):
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            errors.append({'path': str(path), 'reason': 'receipt_too_large'})
            return {}
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        errors.append({'path': str(path), 'reason': 'receipt_unreadable'})
        return {}


def _completed_result(path):
    """Studio atomically publishes results with status as the first JSON field.

    Read only that scalar, never the potentially large plan/media body. Unknown
    layouts conservatively provide no milestone. The closing brace rejects an
    ordinary partially written header; these are progress receipts, not QA.
    """
    try:
        with path.open('rb') as stream:
            prefix = stream.read(512).decode('utf-8', errors='ignore')
            stream.seek(max(0, path.stat().st_size - 32))
            tail = stream.read().rstrip()
        return bool(re.match(r'^\s*\{\s*"status"\s*:\s*"completed"\s*[,}]', prefix)
                    and tail.endswith(b'}'))
    except (OSError, UnicodeError):
        return False


@lru_cache(maxsize=256)
def _cached_digest(path, device, inode, size, modified, changed):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            digest.update(block)
    return digest.hexdigest()


def _digest(path):
    # Filesystem metadata is only an invalidation key, NEVER a progress counter.
    before = path.stat()
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    value = _cached_digest(str(path), *identity)
    after = path.stat()
    if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise OSError('Evidence changed while hashing')
    return value


def _files(folder, result):
    totals = {}
    if not folder.is_dir():
        return
    for path in folder.rglob('*'):
        if not _inside(path, folder) or not path.is_file():
            continue
        try:
            extension = path.suffix.lower()
            if extension in MEDIA:
                totals[extension] = totals.get(extension, 0) + path.stat().st_size
            elif path.name.endswith('-result.json') and _completed_result(path):
                relative = path.relative_to(folder).as_posix()
                result['progress']['completed:' + relative] = 1
                result['references'].append({'kind': 'completed_result', 'path': str(path)})
            elif path.name == 'semantic-plan.json' and path.stat().st_size:
                # One logical milestone, with its exact bytes recorded for audit.
                # Changing a hash alone cannot create a second progress event.
                result['progress']['semantic_plan'] = 1
                result['references'].append({'kind': 'semantic_plan', 'path': str(path),
                                              'sha256': _digest(path)})
        except OSError:
            result['errors'].append({'path': str(path), 'reason': 'artifact_unreadable'})
    for extension, count in totals.items():
        result['progress']['artifact_bytes:' + extension] = count
    result['references'].append({'kind': 'job_artifacts', 'path': str(folder)})


def _wait(result, kind, reference, until=None):
    value = {'kind': kind, 'reference': str(reference)}
    if until is None and kind != 'model_queue':
        return
    if until is not None:
        if not _number(until) or until <= time.time():
            return
        value['until'] = until
    if value not in result['waits']:
        result['waits'].append(value)


def _writing(root, checkpoint, result, *, allow_waits=True):
    linked = checkpoint.get('studio_job_id')
    if not isinstance(linked, str) or not re.fullmatch(r'codex[a-zA-Z0-9]+', linked):
        return
    folder = root / 'writing' / linked
    if not _inside(folder, root):
        return
    database = root / 'writing' / 'jobs.sqlite3'
    row = None
    if _inside(database, root) and database.is_file():
        try:
            with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=.2)) as db:
                # Do not SELECT payload/result: payload can contain base64 images.
                row = db.execute("SELECT state, json_extract(result,'$.error_reason'), "
                                 "json_extract(result,'$.retry_at') FROM jobs WHERE id=?", (linked,)).fetchone()
            if row:
                result['references'].append({'kind': 'writing_state', 'path': str(database),
                                              'job_id': linked, 'state': row[0]})
                if allow_waits and row[0] == 'queued':
                    _wait(result, 'model_queue', database)
                elif allow_waits and row[1] == 'model_capacity':
                    _wait(result, 'model_capacity', database, row[2])
        except sqlite3.Error:
            result['errors'].append({'path': str(database), 'reason': 'writing_state_unreadable'})
    output = folder / 'result.json'
    if row and row[0] == 'completed' and not row[1] and _inside(output, folder) and output.is_file():
        result['progress']['writing_output_bytes:' + linked] = output.stat().st_size
        result['references'].append({'kind': 'writing_output', 'path': str(output)})
    # Only linked call receipts. The writer's model_items sequence counts actual
    # unique content items, not percent/heartbeat events. Bind it to the exact
    # call and request; a new retry call ID alone cannot reset the counter.
    if folder.is_dir():
        for receipt in folder.glob('codex-*/receipt.json'):
            if not _inside(receipt, folder):
                continue
            value = _small_json(receipt, result['errors'])
            progress_path = receipt.parent / 'progress.json'
            progress = _small_json(progress_path, result['errors'])
            request_sha = value.get('request_sha256')
            if (value.get('provider') == 'codex' and value.get('call_id') == receipt.parent.name
                    and progress.get('kind') == 'model_items' and progress.get('call_id') == receipt.parent.name
                    and isinstance(request_sha, str) and re.fullmatch(r'[a-f0-9]{64}', request_sha)
                    and type(progress.get('sequence')) is int and progress['sequence'] > 0):
                key = 'model_items:' + linked + ':' + request_sha
                result['progress'][key] = max(result['progress'].get(key, 0), progress['sequence'])
                result['references'].append({'kind': 'unique_model_content', 'path': str(progress_path),
                                              'request_sha256': request_sha})
            output = receipt.parent / 'result.json'
            if (value.get('status') == 'completed' and value.get('exit_code') == 0
                    and _inside(output, folder) and output.is_file() and output.stat().st_size > 0):
                result['progress']['writing_completed:' + linked] = 1
                result['progress']['writing_call_output_bytes:' + linked] = max(
                    result['progress'].get('writing_call_output_bytes:' + linked, 0), output.stat().st_size)
                result['references'].append({'kind': 'completed_model_result', 'path': str(output)})


def _source_partial_transfers(manifest, candidates, result):
    """Count concrete yt-dlp bytes for candidates of this registered attempt.

    An info JSON binds a filename prefix to the candidate's original URL. No
    timestamp, metadata size or unrelated file can advance the counter. Split
    streams and their merged publication share the same per-video high water.
    """
    from .source_urls import canonical_video_key,video_url
    folder=manifest.parent/'videos'
    if not folder.is_dir() or _inside(folder,manifest.parent)!=folder:
        return
    identities={canonical_video_key(str(c.get('original_url') or c.get('url')))
        for c in candidates if isinstance(c,dict)
        and video_url(str(c.get('original_url') or c.get('url') or ''))}
    files=list(folder.iterdir())
    for info in files:
        if not info.name.endswith('.info.json') or _inside(info,folder)!=info or not info.is_file():
            continue
        metadata=_small_json(info,result['errors'])
        url=metadata.get('webpage_url') or metadata.get('original_url')
        if not isinstance(url,str) or not video_url(url):
            continue
        identity=canonical_video_key(url)
        if identity not in identities:
            continue
        prefix=info.name.removesuffix('.info.json')
        if not prefix:
            continue
        streams={};merged=0
        for media in files:
            if not media.name.startswith(prefix+'.') or _inside(media,folder)!=media or not media.is_file():
                continue
            name=media.name.removesuffix('.part')
            if Path(name).suffix.lower() not in {'.mp4','.m4a','.webm','.mkv','.mov','.aac','.opus'}:
                continue
            try:size=media.stat().st_size
            except FileNotFoundError:continue
            suffix=name[len(prefix):]
            if re.fullmatch(r'\.(mp4|m4a|webm|mkv|mov|aac|opus)',suffix,re.I):
                merged=max(merged,size)
            elif re.fullmatch(r'\.f[^.]+\.(mp4|m4a|webm|mkv|mov|aac|opus)',suffix,re.I):
                streams[name]=max(streams.get(name,0),size)
        count=max(merged,sum(streams.values()))
        if count:
            key='received_bytes:'+hashlib.sha256(identity.encode()).hexdigest()
            result['progress'][key]=max(result['progress'].get(key,0),count)
            result['references'].append({'kind':'source_transfer_bytes','path':str(info)})


def _source(root, job, checkpoint, result):
    from .source_attempts import search_execution
    from .source_search.strategy import search_key
    from .source_urls import canonical_video_key
    attempts = checkpoint.get('source_attempts') or []
    if not isinstance(attempts, list):
        return
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, dict):
            continue
        if attempt.get('task_id') != job['task_id'] or attempt.get('studio_job_id') != job['id']:
            continue
        manifest = _inside(attempt.get('manifest_path'), root / 'source_jobs')
        if not manifest or manifest.name != 'manifest.json' or manifest.parent.parent != root / 'source_jobs':
            continue
        saved = _small_json(manifest, result['errors'])
        _source_partial_transfers(manifest,saved.get('candidates') or [],result)
        documents = [(manifest, saved)]
        for worker in attempt.get('workers') or []:
            if not isinstance(worker, dict):
                continue
            path = _inside(worker.get('path'), manifest.parent)
            if (not path or path.parent.name not in {'browser_debug', 'refinement_debug'}
                    or path.parent.parent != manifest.parent
                    or not re.fullmatch(r'search-checkpoint-[a-f0-9]{32}\.json', path.name)):
                continue
            value = _small_json(path, result['errors'])
            documents.append((path, value))
            if index == len(attempts)-1 and not worker.get('settled'):
                _wait(result, 'source_pacing', path, value.get('waiting_until'))
        for path, value in documents:
            if not value:
                continue
            result['references'].append({'kind': 'source_receipt', 'path': str(path)})
            rows = value.get('searches', value.get('search_audit', []))
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict) and search_execution(row)['consumed']:
                    key = hashlib.sha256(json.dumps(search_key(row), ensure_ascii=False).encode()).hexdigest()
                    result['progress']['consumed_search:' + key] = 1
            for candidate in value.get('candidates') or []:
                if not isinstance(candidate, dict) or not candidate.get('downloaded_file'):
                    continue
                media = _inside(manifest.parent / candidate['downloaded_file'], manifest.parent)
                if not media or not media.is_file():
                    continue
                identity = candidate.get('original_url') or candidate.get('url')
                if not identity:
                    continue
                key = hashlib.sha256(canonical_video_key(str(identity)).encode()).hexdigest()
                result['progress']['received_bytes:' + key] = max(
                    result['progress'].get('received_bytes:' + key, 0), media.stat().st_size)
                # Downloaded alone is never a reviewed/verified-source count.
                review = candidate.get('functional_review') or {}
                sha = candidate.get('file_sha256')
                if (isinstance(review, dict) and review.get('reviewed') is True and sha
                        and review.get('source_sha256') == sha and review.get('evidence_frames')
                        and review.get('observed_actions') and _digest(media) == sha):
                    result['progress']['file_bound_review:' + sha] = 1
        # Transfer receipts are confined to this registered source attempt; only
        # concrete byte coverage counts, never stage/message/request counters.
        for path in manifest.parent.glob('**/*-transfer.json'):
            if not _inside(path, manifest.parent):
                continue
            value = _small_json(path, result['errors'])
            counts = [value.get(k) for k in ('saved_bytes', 'covered_bytes') if _number(value.get(k))]
            fallback = value.get('fallback') or {}
            if isinstance(fallback, dict):
                counts.extend(fallback[k] for k in ('saved_bytes', 'covered_bytes') if _number(fallback.get(k)))
            for transfer in (value, fallback):
                if isinstance(transfer, dict):
                    covered = [s['covered_bytes'] for s in transfer.get('received_streams', [])
                               if isinstance(s, dict) and s.get('bound_to_item') is True
                               and _number(s.get('covered_bytes'))]
                    if covered:
                        counts.append(sum(covered))
            if counts:
                key = 'transfer_bytes:' + str(path.relative_to(root).with_name(path.name.removesuffix('-transfer.json')))
                result['progress'][key] = max(counts)
                result['references'].append({'kind': 'transfer_bytes', 'path': str(path)})


def collect_evidence(data_dir, job):
    """Return bounded, conservative observations; this never changes runtime state.

    ``progress`` values are high-water inputs, not deltas. ``waits`` are explicit
    current gates and never progress/failures. Unknown evidence is not success.
    A running model is not an indefinite exemption; only queue/capacity records
    are waits. Consumers choose an appropriate observation deadline separately.
    """
    result = {'progress': {}, 'waits': [], 'references': [], 'errors': [], 'unknown': True}
    if not isinstance(job, dict):
        return result
    if any(not isinstance(job.get(k), str) or not re.fullmatch(r'[\w-]+', job[k])
           for k in ('id', 'task_id')):
        return result
    root = Path(data_dir).resolve()
    checkpoint = job.get('checkpoint') or {}
    if isinstance(checkpoint, str):
        try: checkpoint = json.loads(checkpoint)
        except ValueError: checkpoint = {}
    if not isinstance(checkpoint, dict):
        checkpoint = {}
    _wait(result, 'scheduled_retry', 'checkpoint.not_before', checkpoint.get('not_before'))
    local_wait = checkpoint.get('supervision_wait')
    if (isinstance(local_wait, dict) and job.get('claim_token')
            and local_wait.get('claim') == job['claim_token']
            and local_wait.get('kind') in {'local_compute', 'voice_service_busy'}):
        _wait(result, local_wait['kind'], 'checkpoint.supervision_wait', local_wait.get('until'))
    voice = checkpoint.get('supervision_voice')
    request_id = checkpoint.get('request_id')
    if (isinstance(voice, dict) and job.get('claim_token')
            and voice.get('claim') == job['claim_token']
            and type(request_id) is int and request_id >= 0
            and type(voice.get('request_id')) is int and voice['request_id'] == request_id
            and voice.get('status') in {'queued', 'running', 'succeeded'}):
        completed = voice.get('completed_segments')
        if type(completed) is int and completed >= 0:
            result['progress']['voice_segments:' + str(request_id)] = completed
            result['references'].append({'kind': 'voice_segments', 'request_id': request_id,
                                          'reference': 'checkpoint.supervision_voice'})
        if voice['status'] == 'queued':
            _wait(result, 'voice_queue', 'checkpoint.supervision_voice', voice.get('until'))
    payload = job.get('payload') or {}
    if job.get('kind') == 'voice' and isinstance(payload, dict):
        voice_id = payload.get('voice_id')
        if isinstance(voice_id, str) and re.fullmatch(r'[\w-]+', voice_id):
            output = _inside(root/'studio'/job['task_id']/voice_id/'original.wav', root)
            try:
                if output and output.is_file():
                    result['progress']['voice_output_bytes:' + voice_id] = output.stat().st_size
                    result['references'].append({'kind': 'voice_output', 'path': str(output)})
            except OSError:
                result['errors'].append({'scope': 'voice', 'reason': 'evidence_unavailable'})
    folder = _inside(root / 'studio' / job['task_id'] / job['id'], root)
    if folder:
        _files(folder, result)
    linked_ids = {checkpoint[k] for k in ('studio_job_id', 'supervision_model_job_id')
                  if isinstance(checkpoint.get(k), str)}
    history = checkpoint.get('supervision_model_history') or []
    if isinstance(history, list):
        linked_ids.update(linked for linked in history[-128:]
                          if isinstance(linked, str) and re.fullmatch(r'codex[a-zA-Z0-9]+', linked))
    current_link = checkpoint.get('supervision_model_job_id')
    if not isinstance(current_link, str) or not re.fullmatch(r'codex[a-zA-Z0-9]+', current_link):
        current_link = checkpoint.get('studio_job_id')
    if not isinstance(current_link, str) or not re.fullmatch(r'codex[a-zA-Z0-9]+', current_link):
        current_link = None
    for linked in linked_ids:
        try:
            _writing(root, {'studio_job_id': linked}, result, allow_waits=linked==current_link)
        except (OSError, TypeError, ValueError):
            result['errors'].append({'scope': 'writing', 'reason': 'evidence_unavailable'})
    try:
        _source(root, job, checkpoint, result)
    except (OSError, TypeError, ValueError):
        result['errors'].append({'scope': 'source', 'reason': 'evidence_unavailable'})
    result['unknown'] = not bool(result['progress'] or result['waits'])
    return result
