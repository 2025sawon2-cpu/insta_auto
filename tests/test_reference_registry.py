import json
import hashlib
from datetime import datetime, timezone

import pytest

from hotpost.reference_registry import load, main, mark, ranked, save, sync


def epoch(day, hour=0):
    return int(datetime(2026, 10, day, hour, tzinfo=timezone.utc).timestamp())


def post(code, day, score, *, kind="reel", tier=1):
    return {"shortcode": code, "username": "example", "url": f"https://www.instagram.com/reel/{code}/",
            "kind": kind, "tier": tier, "taken_at": epoch(day), "hot_detected_at": epoch(day),
            "rank_score": score, "assessment": {"status": "provisional"}, "views": 100,
            "metric_status": {"views": "observed"}}


def report(*posts):
    return {"is_sample": False, "posts": list(posts), "generated_at": epoch(24, 9),
            "collection_started_at": epoch(24, 8)}


def test_latest_published_date_then_daily_score_and_status_preserved(tmp_path):
    path = tmp_path / "registry.json"
    registry = load(path)
    sync(registry, report(post("older", 23, 99), post("new-low", 24, 1),
                          post("new-high", 24, 2), post("photo", 24, 5, kind="image")),
         "report.json", "3")
    assert [item["video_id"] for item in ranked(registry)] == ["new-high", "new-low", "older"]
    assert registry["posts"]["new-high"]["reference"]["rank_in_published_date"] == 1
    assert registry["posts"]["new-low"]["production"]["state"] == "unknown"
    mark(registry, "new-high", "paused", "User stopped this video's producer", expected="unknown",
         stage="source_search_active", owner="producer")
    save(path, registry)
    sync(registry, report(post("new-high", 24, 3)), "next-report.json", "4")
    assert registry["posts"]["new-high"]["production"]["state"] == "paused"
    assert registry["posts"]["older"]["reference"]["in_latest_report"] is False
    assert [item["video_id"] for item in ranked(registry)] == ["new-high"]


def test_new_video_requires_explicit_held_video_decision_and_distinct_monitor(tmp_path):
    registry = load(tmp_path / "registry.json")
    sync(registry, report(post("held", 23, 2), post("new", 24, 1)), "report.json")
    mark(registry, "held", "paused", "User pause", expected="unknown")
    kwargs = dict(expected="unknown", task_id="task-new", run_id="run-new",
                  owner="producer", monitor="watcher")
    with pytest.raises(ValueError, match="Explicit new-over-paused"):
        mark(registry, "new", "in_progress", "Selection", **kwargs)
    with pytest.raises(ValueError, match="decision and reason"):
        mark(registry, "new", "in_progress", "Selection", new_over_paused=["held"], **kwargs)
    mark(registry, "new", "in_progress", "User chose new after viewing held",
         new_over_paused=["held"], reason="User explicitly chose new video", **kwargs)
    assert registry["posts"]["held"]["production"]["state"] == "paused"
    assert registry["posts"]["new"]["production"]["history"][-1]["new_over_paused"] == ["held"]
    with pytest.raises(ValueError, match="Another video"):
        mark(registry, "held", "in_progress", "Resume", expected="paused",
             task_id="task-held", run_id="run-held", owner="producer-2", monitor="watcher-2")


def test_completion_needs_qa_and_read_only_view_does_not_write(tmp_path, capsys, monkeypatch):
    # Stage gates are covered in test_stage_gate.py; this test keeps the pre-gate path.
    monkeypatch.setattr('hotpost.stage_gate.REQUIRED_SINCE', datetime(2999, 1, 1, tzinfo=timezone.utc))
    registry_path = tmp_path / "registry.json"
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report(post("a", 24, 1))), encoding="utf-8")
    main(["--registry", str(registry_path), "list", "--report", str(report_path)])
    assert not registry_path.exists()
    assert "a" in capsys.readouterr().out
    registry = load(registry_path)
    sync(registry, report(post("a", 24, 1)), report_path)
    with pytest.raises(ValueError, match="Completion requires"):
        mark(registry, "a", "completed", "Rendered file", expected="unknown")
    mark(registry, "a", "in_progress", "One bound production", expected="unknown",
         task_id="task-a", run_id="run-a", owner="producer", monitor="watcher")
    video, cover = tmp_path / "final.mp4", tmp_path / "cover.png"
    video.write_bytes(b"reviewed video")
    cover.write_bytes(b"reviewed cover")
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    record = {
        "schema_version": 1, "video_id": "a", "task_id": "task-a", "run_id": "run-a",
        "edit_id": "edit-a", "producer": "producer", "reviewed_at": "2026-10-25T09:00:00+09:00",
        "artifacts": {
            **{key: {"id": key + "-a", "sha256": "a" * 64} for key in ("script", "voice", "plan")},
            "video": {"path": str(video), "sha256": sha(video)},
            "cover": {"path": str(cover), "sha256": sha(cover)},
        },
        "checks": {key: {"status": "충족", "evidence": [{"asset": asset,
                   "location": "00:02 or opening sentence", "observation": "Current output checked"}]}
                   for key, asset in (("script", "script"), ("visual", "video"),
                                      ("audio_captions", "video"), ("cover_delivery", "cover"))},
    }
    qa = tmp_path / "final-qa.json"
    qa.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="must be an existing file"):
        mark(registry, "a", "completed", "Fake QA", expected="in_progress",
             qa_evidence=tmp_path / "missing.json", final_sha256=sha(video))
    with pytest.raises(ValueError, match="completion request"):
        mark(registry, "a", "completed", "Wrong hash", expected="in_progress",
             qa_evidence=qa, final_sha256="a" * 64)
    record["checks"]["visual"]["status"] = "수정 필요"
    qa.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="visual is not confirmed"):
        mark(registry, "a", "completed", "Needs fix", expected="in_progress",
             qa_evidence=qa, final_sha256=sha(video))
    record["checks"]["visual"]["status"] = "충족"
    qa.write_text(json.dumps(record), encoding="utf-8")
    cover.write_bytes(b"changed cover")
    with pytest.raises(ValueError, match="cover bytes changed"):
        mark(registry, "a", "completed", "Stale cover", expected="in_progress",
             qa_evidence=qa, final_sha256=sha(video))
    record["artifacts"]["cover"]["sha256"] = sha(cover)
    qa.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match='schema_version=2'):
        mark(registry, 'a', 'completed', 'Legacy QA cannot certify a new completion',
             expected='in_progress', qa_evidence=qa, final_sha256=sha(video))
    record['schema_version'] = 2
    for name in ('script', 'voice', 'plan'):
        path = tmp_path / name
        path.write_bytes(name.encode())
        record['artifacts'][name].update(path=str(path), sha256=sha(path))
    source, rule = tmp_path / 'source.mp4', tmp_path / 'RULES.md'
    source.write_bytes(b'used source'); rule.write_bytes(b'applicable rules')
    record['dependencies'] = {name: [{'path': str(path), 'sha256': sha(path)}]
                              for name, path in (('sources', source), ('rules', rule))}
    qa.write_text(json.dumps(record), encoding='utf-8')
    mark(registry, "a", "completed", "Final QA verified", expected="in_progress",
         qa_evidence=qa, final_sha256=sha(video))
    production = registry["posts"]["a"]["production"]
    assert production["final_sha256"] == sha(video)
    assert production["cover_sha256"] == sha(cover)
    assert production["qa_record_sha256"] == sha(qa)
