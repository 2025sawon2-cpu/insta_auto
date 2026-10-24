"""Local, evidence-backed reference and production state for Hotpost videos."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
STATES = {"unknown", "not_started", "in_progress", "paused", "blocked", "completed"}
UNFINISHED = {"in_progress", "paused", "blocked"}
SCHEMA_VERSION = 1


def kst_date(seconds):
    return datetime.fromtimestamp(seconds, KST).date().isoformat() if isinstance(seconds, (int, float)) and seconds > 0 else None


def load(path: Path):
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "report": None, "posts": {}}
    registry = json.loads(path.read_text(encoding="utf-8"))
    if registry.get("schema_version") != SCHEMA_VERSION or not isinstance(registry.get("posts"), dict):
        raise ValueError("Unsupported reference registry; preserve it and inspect before changing")
    return registry


def save(path: Path, registry):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def sync(registry, report, report_path, run_id=None):
    if report.get("is_sample"):
        raise ValueError("Sample report cannot establish live reference status")
    if not isinstance(report.get("posts"), list):
        raise ValueError("Report has no posts list")
    for entry in registry["posts"].values():
        entry["reference"]["in_latest_report"] = False
    candidates = [p for p in report["posts"] if p.get("kind") == "reel" and (p.get("tier") or 0) >= 1 and p.get("shortcode")]
    # Date desc, then score desc, then publication time desc, then stable ID.
    candidates.sort(key=lambda p: p["shortcode"])
    candidates.sort(key=lambda p: (p.get("rank_score") or 0, p.get("taken_at") or 0), reverse=True)
    candidates.sort(key=lambda p: kst_date(p.get("taken_at")) or "", reverse=True)
    ranks = {}
    for post in candidates:
        code = post["shortcode"]
        day = kst_date(post.get("taken_at"))
        ranks[day] = ranks.get(day, 0) + 1
        old = registry["posts"].get(code, {})
        ref = old.get("reference", {})
        detection = post.get("hot_detected_at") or ref.get("first_hot_at")
        url = post.get("url") or f"https://www.instagram.com/reel/{code}/"
        ref.update({
            "username": post.get("username"),
            "url": url,
            "published_at": post.get("taken_at"),
            "published_date_kst": day,
            "first_hot_at": detection,
            "first_hot_date_kst": kst_date(detection),
            "rank_in_published_date": ranks[day],
            "rank_score": post.get("rank_score"),
            "tier": post.get("tier"),
            "assessment": post.get("assessment"),
            "views": post.get("views"),
            "metric_status": post.get("metric_status"),
            "in_latest_report": True,
            "report_generated_at": report.get("generated_at"),
        })
        registry["posts"][code] = {
            "video_id": code,
            "reference": ref,
            "production": old.get("production", {"state": "unknown", "stage": None, "task_id": None, "run_id": None,
                                                  "owner": None, "monitor": None, "reason": "Existing work not yet audited",
                                                  "evidence": [], "history": [], "updated_at": None}),
        }
    registry["report"] = {"path": str(report_path), "generated_at": report.get("generated_at"),
                          "collection_started_at": report.get("collection_started_at"), "run_id": run_id,
                          "candidate_count": len(candidates)}
    return registry


def ranked(registry, include_old=False):
    entries = list(registry["posts"].values())
    if not include_old:
        entries = [p for p in entries if p["reference"].get("in_latest_report")]
    entries.sort(key=lambda p: p["video_id"])
    entries.sort(key=lambda p: (p["reference"].get("rank_score") or 0,
                                p["reference"].get("published_at") or 0), reverse=True)
    entries.sort(key=lambda p: p["reference"].get("published_date_kst") or "", reverse=True)
    return entries


def mark(registry, code, state, evidence, *, expected, stage=None, task_id=None, run_id=None,
         owner=None, monitor=None, reason=None, qa_evidence=None, final_sha256=None,
         new_over_paused=()):
    if code not in registry["posts"]:
        raise ValueError(f"Unknown video ID: {code}")
    if state not in STATES or not evidence.strip():
        raise ValueError("Valid state and concrete evidence are required")
    current = registry["posts"][code]["production"]
    if current["state"] != expected:
        raise ValueError(f"State changed: expected {expected}, found {current['state']}")
    if state == "in_progress":
        if not all((task_id or current.get("task_id"), run_id or current.get("run_id"),
                    owner or current.get("owner"), monitor or current.get("monitor"))):
            raise ValueError("Starting production requires task/run and separate owner/monitor")
        if (owner or current.get("owner")) == (monitor or current.get("monitor")):
            raise ValueError("Producer and monitor must be distinct")
        others = {key: post["production"]["state"] for key, post in registry["posts"].items()
                  if key != code and post["production"]["state"] in UNFINISHED}
        active = [key for key, value in others.items() if value == "in_progress"]
        if active:
            raise ValueError(f"Another video is in progress: {', '.join(active)}")
        held = {key for key, value in others.items() if value in {"paused", "blocked"}}
        if held and held != set(new_over_paused):
            raise ValueError("Explicit new-over-paused decision must name every held video ID")
        if held and not reason:
            raise ValueError("Record the user's explicit new-over-paused decision and reason")
    if state == "completed":
        if not qa_evidence or not final_sha256 or not re.fullmatch(r"[0-9a-fA-F]{64}", final_sha256):
            raise ValueError("Completion requires final QA evidence and final file SHA-256")
        if current["state"] != "in_progress":
            raise ValueError("Only the current in-progress video can be completed")
        if not all(current.get(key) for key in ("task_id", "run_id", "owner", "monitor")):
            raise ValueError("Completion requires the bound task/run and producer/monitor")
        if current["owner"] == current["monitor"]:
            raise ValueError("Producer and monitor must be distinct")
        for key, supplied in (("task_id", task_id), ("run_id", run_id), ("owner", owner), ("monitor", monitor)):
            if supplied is not None and supplied != current[key]:
                raise ValueError(f"Completion cannot change the bound {key}")
        from .final_qa import validate
        qa = validate(qa_evidence, video_id=code, task_id=current["task_id"],
                      run_id=current["run_id"], producer=current["owner"],
                      final_sha256=final_sha256)
    changed_at = datetime.now(KST).isoformat()
    updated = dict(current)
    updated.update({"state": state, "stage": stage if stage is not None else current.get("stage"),
                    "task_id": task_id or current.get("task_id"), "run_id": run_id or current.get("run_id"),
                    "owner": owner or current.get("owner"), "monitor": monitor or current.get("monitor"),
                    "reason": reason, "evidence": list(current.get("evidence", [])) + [evidence],
                    "history": list(current.get("history", [])) + [{
                        "from": expected, "to": state, "at": changed_at,
                        "evidence": evidence, "reason": reason,
                        "new_over_paused": sorted(new_over_paused),
                    }],
                    "updated_at": changed_at})
    if new_over_paused:
        updated["new_over_paused"] = sorted(new_over_paused)
    if state == "completed":
        updated["qa_evidence"] = qa["record_path"]
        updated["qa_record_sha256"] = qa["record_sha256"]
        updated["final_sha256"] = qa["video"]["sha256"]
        updated["cover_sha256"] = qa["cover"]["sha256"]
    registry["posts"][code]["production"] = updated
    return registry


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path("data/reference-status.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    sync_cmd = sub.add_parser("sync")
    sync_cmd.add_argument("--report", type=Path, default=Path("data/report.json"))
    sync_cmd.add_argument("--run-id")
    listing = sub.add_parser("list")
    listing.add_argument("--all", action="store_true")
    listing.add_argument("--report", type=Path, help="Merge this report in memory without changing the registry")
    show = sub.add_parser("show")
    show.add_argument("video_id")
    show.add_argument("--report", type=Path, help="Merge this report in memory without changing the registry")
    change = sub.add_parser("mark")
    change.add_argument("video_id")
    change.add_argument("--state", required=True, choices=sorted(STATES))
    change.add_argument("--expected-state", required=True, choices=sorted(STATES))
    change.add_argument("--evidence", required=True)
    for key in ("stage", "task_id", "run_id", "owner", "monitor", "reason", "qa_evidence", "final_sha256"):
        change.add_argument("--" + key.replace("_", "-"))
    change.add_argument("--new-over-paused", action="append", default=[])
    args = parser.parse_args(argv)
    registry = load(args.registry)
    if args.command == "sync":
        report = json.loads(args.report.read_text(encoding="utf-8"))
        sync(registry, report, args.report, args.run_id)
        save(args.registry, registry)
        print(f"Synced {registry['report']['candidate_count']} hot reels; production states preserved")
    elif args.command == "list":
        if args.report:
            sync(registry, json.loads(args.report.read_text(encoding="utf-8")), args.report)
        for item in ranked(registry, args.all):
            ref, prod = item["reference"], item["production"]
            print(f"{item['video_id']}\t{ref.get('published_date_kst') or '?'}\t#{ref.get('rank_in_published_date') or '?'}"
                  f"\t{ref.get('rank_score') or '?'}\t{prod['state']}\t{(ref.get('assessment') or {}).get('status', '?')}")
    elif args.command == "show":
        if args.report:
            sync(registry, json.loads(args.report.read_text(encoding="utf-8")), args.report)
        if args.video_id not in registry["posts"]:
            raise SystemExit(f"Unknown video ID: {args.video_id}")
        print(json.dumps(registry["posts"][args.video_id], ensure_ascii=False, indent=2))
    else:
        mark(registry, args.video_id, args.state, args.evidence, expected=args.expected_state,
             stage=args.stage, task_id=args.task_id, run_id=args.run_id, owner=args.owner,
             monitor=args.monitor, reason=args.reason, qa_evidence=args.qa_evidence,
             final_sha256=args.final_sha256, new_over_paused=args.new_over_paused)
        save(args.registry, registry)
        print(f"{args.video_id}: {args.expected_state} -> {args.state}")


if __name__ == "__main__":
    main()
