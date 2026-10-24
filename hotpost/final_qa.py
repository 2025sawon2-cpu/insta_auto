"""Validate a producer's structured review against the current media files.

The judgments belong to the producer; this module checks their presence and
their binding to the files, not the truth of a visual or editorial judgment.
"""

from __future__ import annotations

from datetime import datetime
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
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


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
    if not isinstance(record, dict) or record.get("schema_version") != 1:
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
        if not isinstance(check, dict) or check.get("status") != "충족":
            raise ValueError(f"Final QA {name} is not confirmed")
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
        if not any(row["asset"] == asset for row in evidence):
            raise ValueError(f"Final QA {name} needs evidence from {asset}")
    return {"record_path": str(path), "record_sha256": hashlib.sha256(raw).hexdigest(),
            "video": verified["video"], "cover": verified["cover"],
            "task_id": record["task_id"], "run_id": record["run_id"],
            "producer": record["producer"], "edit_id": record["edit_id"]}
