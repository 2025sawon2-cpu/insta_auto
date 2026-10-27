"""Validate a producer's structured review against the current media files.

The judgments belong to the producer; this module checks their presence and
their binding to the files, not the truth of a visual or editorial judgment.
"""

from __future__ import annotations

from datetime import datetime
import argparse
import hashlib
import json
from pathlib import Path
import re


CHECK_ASSETS = {
    "script": "script",
    "visual": "video",
    "audio_captions": "video",
    "cover_delivery": "cover",
}
SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        before = _identity(stream)
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
        if _identity(stream) != before:
            raise ValueError('Final QA file changed while hashing')
    current = Path(path).stat()
    if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns) != before:
        raise ValueError('Final QA file replaced while hashing')
    return value.hexdigest()


def _identity(stream):
    import os
    stat = os.fstat(stream.fileno())
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def file_input(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('Final QA input must be an existing file')
    return {'path': str(path), 'sha256': digest(path)}


def capture_inputs(*, script, voice, plan, sources, rules):
    """Snapshot before review. No quality verdict or existing QA is updated."""
    if not sources or not rules:
        raise ValueError('Final QA inputs require used sources and applicable rules')
    return {'schema_version': 2,
            'artifacts': {name: file_input(path) for name, path in
                          (('script', script), ('voice', voice), ('plan', plan))},
            'dependencies': {name: [file_input(path) for path in paths]
                             for name, paths in (('sources', sources), ('rules', rules))}}


def _verified_input(item, label):
    if not isinstance(item, dict):
        raise ValueError(f'Final QA {label} file binding is required')
    path = Path(_text(item.get('path'), f'{label} path'))
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f'Final QA {label} must name an existing absolute file')
    if digest(path) != _hash(item.get('sha256'), f'{label} sha256'):
        raise ValueError(f'Final QA {label} bytes changed after review')
    return path


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Final QA {label} is missing")
    return value


def _hash(value, label):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError(f"Final QA {label} must be a SHA-256 digest")
    return value.lower()


def validate(record_path, *, video_id, task_id=None, run_id=None, producer=None,
             edit_id=None, video=None, cover=None, final_sha256=None):
    """Return verified record identity and digests, or reject completion.

    ``video`` and ``cover`` are the selected current paths when a caller has
    them independently (publication export). The registry can use the paths
    in the record, but still checks their real bytes.
    """
    result = inspect_record(record_path, video_id=video_id, task_id=task_id,
                            run_id=run_id, producer=producer, edit_id=edit_id,
                            video=video, cover=cover, final_sha256=final_sha256)
    if result['unresolved']:
        raise ValueError(f"Final QA {result['unresolved'][0]} is not confirmed")
    return result


def inspect_record(record_path, *, video_id, task_id=None, run_id=None, producer=None,
                   edit_id=None, video=None, cover=None, final_sha256=None):
    """Check identity and evidence for review storage; never authorize completion."""
    if not record_path:
        raise ValueError("Final QA record path is required")
    try:
        path = Path(record_path).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError("Final QA record must be an existing file") from error
    if not path.is_file():
        raise ValueError("Final QA record must be a file")
    raw = path.read_bytes()
    try:
        record = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Final QA record must be UTF-8 JSON") from error
    if not isinstance(record, dict) or type(record.get('schema_version')) is not int or record['schema_version'] not in (1, 2):
        raise ValueError("Unsupported final QA record schema")
    if record.get("video_id") != video_id:
        raise ValueError("Final QA video ID differs from the selected post")
    for key, expected in (("task_id", task_id), ("run_id", run_id),
                          ("producer", producer), ("edit_id", edit_id)):
        actual = _text(record.get(key), key)
        if expected is not None and actual != expected:
            raise ValueError(f"Final QA {key} differs from the current work")
    reviewed = _text(record.get("reviewed_at"), "reviewed_at")
    try:
        timestamp = datetime.fromisoformat(reviewed)
    except ValueError as error:
        raise ValueError("Final QA reviewed_at must be an ISO timestamp") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Final QA reviewed_at must include a timezone")

    artifacts = record.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("Final QA artifacts are required")
    for name in ("script", "voice", "plan"):
        item = artifacts.get(name)
        if not isinstance(item, dict):
            raise ValueError(f"Final QA {name} identity is required")
        _text(item.get("id"), f"{name} id")
        _hash(item.get("sha256"), f"{name} sha256")
        if record['schema_version'] == 2:
            _verified_input(item, name)

    if record['schema_version'] == 2:
        dependencies = record.get('dependencies')
        if not isinstance(dependencies, dict):
            raise ValueError('Final QA dependencies are required')
        for name in ('sources', 'rules'):
            items = dependencies.get(name)
            if not isinstance(items, list) or not items:
                raise ValueError(f'Final QA {name} dependencies are required')
            for item in items:
                _verified_input(item, name)

    verified = {}
    for name, current in (("video", video), ("cover", cover)):
        item = artifacts.get(name)
        if not isinstance(item, dict):
            raise ValueError(f"Final QA {name} file is required")
        filename = Path(_text(item.get("path"), f"{name} path"))
        if not filename.is_absolute() or not filename.is_file():
            raise ValueError(f"Final QA {name} must name an existing absolute file")
        filename = filename.resolve(strict=True)
        if current is not None and filename != Path(current).resolve(strict=True):
            raise ValueError(f"Final QA {name} is not the current applied file")
        expected = _hash(item.get("sha256"), f"{name} sha256")
        if digest(filename) != expected:
            raise ValueError(f"Final QA {name} bytes changed after review")
        verified[name] = {"path": str(filename), "sha256": expected}
    if final_sha256 is not None and verified["video"]["sha256"] != _hash(final_sha256, "final_sha256"):
        raise ValueError("Final QA video hash differs from the completion request")

    checks = record.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("Final QA checks are required")
    for name, asset in CHECK_ASSETS.items():
        check = checks.get(name)
        if not isinstance(check, dict) or check.get("status") not in ("충족", "수정 필요", "확인 불가"):
            raise ValueError(f"Final QA {name} has an invalid status")
        evidence = check.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"Final QA {name} needs specific evidence")
        for row in evidence:
            if not isinstance(row, dict):
                raise ValueError(f"Final QA {name} evidence is malformed")
            if row.get("asset") not in artifacts:
                raise ValueError(f"Final QA {name} evidence names an unknown asset")
            _text(row.get("location"), f"{name} evidence location")
            _text(row.get("observation"), f"{name} evidence observation")
            if row.get('method') == 'human_user_review':
                _text(row.get('user_quote'), f'{name} user quote')
                _text(row.get('review_context'), f'{name} review context')
                scope = row.get('reviewed_checks')
                if not isinstance(scope, list) or name not in scope or any(item not in CHECK_ASSETS for item in scope):
                    raise ValueError(f'Final QA {name} is outside the human review scope')
                if row.get('video_sha256') != verified['video']['sha256']:
                    raise ValueError(f'Final QA {name} human review names another video')
        if not any(row["asset"] == asset for row in evidence):
            raise ValueError(f"Final QA {name} needs evidence from {asset}")
    # Long video/source hashing must not hide an input changed during this check.
    if record['schema_version'] == 2:
        for name in ('script', 'voice', 'plan'):
            _verified_input(artifacts[name], name)
        for name in ('sources', 'rules'):
            for item in record['dependencies'][name]:
                _verified_input(item, name)
    if path.read_bytes() != raw:
        raise ValueError('Final QA record changed during validation')
    return {"record_path": str(path), "record_sha256": hashlib.sha256(raw).hexdigest(),
            'schema_version': record['schema_version'],
            'input_binding': 'files' if record['schema_version'] == 2 else 'legacy_metadata_only',
            "video": verified["video"], "cover": verified["cover"],
            "task_id": record["task_id"], "run_id": record["run_id"],
            "producer": record["producer"], "edit_id": record["edit_id"],
            "unresolved": [name for name in CHECK_ASSETS if checks[name]['status'] != '충족']}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Capture current QA input files before content review; no quality approval')
    sub = parser.add_subparsers(dest='command', required=True)
    inputs = sub.add_parser('inputs')
    for name in ('script', 'voice', 'plan'):
        inputs.add_argument('--' + name, type=Path, required=True)
    inputs.add_argument('--source', type=Path, action='append', required=True)
    inputs.add_argument('--rule', type=Path, action='append', required=True)
    args = parser.parse_args(argv)
    # Every stage's contract rules are always bound; --rule only adds extra guidance.
    from .stage_gate import required_rules
    given = {path.resolve() for path in args.rule}
    rules = args.rule + [path for path in required_rules() if path.resolve() not in given]
    print(json.dumps(capture_inputs(script=args.script, voice=args.voice, plan=args.plan,
                                   sources=args.source, rules=rules), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
