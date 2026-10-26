"""Local, evidence-backed reference and production state for Hotpost videos."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
STATES = {"unknown", "not_started", "in_progress", "paused", "blocked", "completed"}
UNFINISHED = {"in_progress", "paused", "blocked"}
SCHEMA_VERSION = 1


class Registry(dict):
    """JSON-compatible state with a private, non-persisted read token."""


def _bytes(path):
    return path.read_bytes() if path.exists() else None


def kst_date(seconds):
    return datetime.fromtimestamp(seconds, KST).date().isoformat() if isinstance(seconds, (int, float)) and seconds > 0 else None


def load(path: Path):
    path = Path(path).resolve()
    raw = _bytes(path)
    registry = Registry(json.loads(raw) if raw is not None else
                        {"schema_version": SCHEMA_VERSION, "report": None, "posts": {}})
    if registry.get("schema_version") != SCHEMA_VERSION or not isinstance(registry.get("posts"), dict):
        raise ValueError("Unsupported reference registry; preserve it and inspect before changing")
    revision = registry.get('revision', 0)
    if type(revision) is not int or revision < 0:
        raise ValueError('Invalid reference registry revision')
    registry.source_path, registry.source_bytes = path, raw
    return registry


def save(path: Path, registry):
    from .state_lock import file_lock
    path = Path(path).resolve()
    with file_lock(path.with_name(path.name + '.lock')):
        _save_locked(path, registry)


def _save_locked(path, registry):
    if not isinstance(registry, Registry) or registry.source_path != path:
        raise ValueError('Load this reference registry before saving')
    if _bytes(path) != registry.source_bytes:
        raise ValueError('Reference registry changed; reload before saving')
    original = json.loads(registry.source_bytes) if registry.source_bytes is not None else {}
    if registry.get('revision', 0) != original.get('revision', 0):
        raise ValueError('Reference registry revision cannot be edited manually')
    path.parent.mkdir(parents=True, exist_ok=True)
    updated = dict(registry, revision=original.get('revision', 0) + 1)
    content = json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temp, path)
        registry['revision'] = updated['revision']
        registry.source_bytes = content.encode('utf-8')
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def transaction(path, *, expected_revision=None):
    """Serialize load, all transition checks and atomic save in one process lock."""
    from .state_lock import file_lock
    path = Path(path).resolve()
    with file_lock(path.with_name(path.name + '.lock')):
        registry = load(path)
        if expected_revision is not None and registry.get('revision', 0) != expected_revision:
            raise ValueError('Reference registry revision changed; inspect current context')
        yield registry
        _save_locked(path, registry)


def context(registry, code):
    """Small read-only recovery view; role bindings do not prove worker liveness."""
    if code not in registry['posts']:
        raise ValueError(f'Unknown video ID: {code}')
    production = registry['posts'][code]['production']
    state = production['state']
    qa = {'status': 'not_recorded'}
    if production.get('qa_evidence'):
        try:
            from .final_qa import validate
            if state == 'completed':
                from .daily_ranking import require_completion_binding
                require_completion_binding(production)
            result = validate(production['qa_evidence'], video_id=code,
                              task_id=production.get('task_id'), run_id=production.get('run_id'),
                              producer=production.get('owner'), final_sha256=production.get('final_sha256'))
            qa = {'status': 'current', 'input_binding': result['input_binding']}
        except (OSError, ValueError) as error:
            qa = {'status': 'needs_review', 'reason': str(error)}
    actions = {'unknown': 'audit_history', 'not_started': 'confirm_selection_and_bind_workers',
               'in_progress': 'verify_actual_workers_and_current_artifacts',
               'paused': 'require_explicit_resume_and_current_evidence',
               'blocked': 'require_explicit_resume_and_new_progress_evidence',
               'completed': 'verify_completion_before_skipping'}
    return {'video_id': code, 'revision': registry.get('revision', 0),
            **{key: production.get(key) for key in ('state', 'stage', 'reason', 'task_id', 'run_id', 'owner', 'monitor')},
            'worker_observation': 'unverified; bound identities are not live tool observations',
            'evidence': production.get('evidence', [])[-5:], 'qa': qa,
            'next_action': actions[state], 'grants_execution_authority': False,
            'rule_paths': ['AGENTS.md', 'docs/COLLABORATION.md', 'docs/WORKFLOW.md', 'docs/REFERENCE_STATUS.md']}


def sync(registry, report, report_path, run_id=None):
    if report.get("is_sample"):
        raise ValueError("Sample report cannot establish live reference status")
    if not isinstance(report.get("posts"), list):
        raise ValueError("Report has no posts list")
    for entry in registry["posts"].values():
        entry["reference"]["in_latest_report"] = False
    candidates = [p for p in report["posts"] if p.get("kind") == "reel" and (p.get("tier") or 0) >= 1 and p.get("shortcode")]
    daily = report.get('ranking_mode') == 'views_per_follower_72h'
    # Old reports retain their historical ordering; daily snapshots span all 72 hours.
    candidates.sort(key=lambda p: p["shortcode"])
    candidates.sort(key=lambda p: (p.get("rank_score") or 0,
                                   (p.get('views') or 0) if daily else 0,
                                   p.get("taken_at") or 0), reverse=True)
    if not daily:
        candidates.sort(key=lambda p: kst_date(p.get("taken_at")) or "", reverse=True)
    ranks = {}
    for rank, post in enumerate(candidates, 1):
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
            "rank": rank if daily else None,
            "ranking_mode": report.get('ranking_mode'),
            "views_display": post.get('views_display'),
            "followers": post.get('followers'),
            "followers_display": post.get('followers_display'),
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
                          "candidate_count": len(candidates), "ranking_mode": report.get('ranking_mode')}
    return registry


def ranked(registry, include_old=False):
    entries = list(registry["posts"].values())
    if not include_old:
        entries = [p for p in entries if p["reference"].get("in_latest_report")]
    entries.sort(key=lambda p: p["video_id"])
    daily = (registry.get('report') or {}).get('ranking_mode') == 'views_per_follower_72h'
    entries.sort(key=lambda p: (p["reference"].get("rank_score") or 0,
                                (p['reference'].get('views') or 0) if daily else 0,
                                p["reference"].get("published_at") or 0), reverse=True)
    if not daily:
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
        if qa['schema_version'] != 2:
            raise ValueError('New completion requires file-bound final QA schema_version=2')
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
    recovery = sub.add_parser('context', help='Read-only compact recovery; never resume work')
    recovery.add_argument('video_id')
    next_cmd = sub.add_parser('next', help='Read-only next production candidate/state audit')
    next_cmd.add_argument('--report', type=Path)
    change = sub.add_parser("mark")
    change.add_argument("video_id")
    change.add_argument("--state", required=True, choices=sorted(STATES))
    change.add_argument("--expected-state", required=True, choices=sorted(STATES))
    change.add_argument("--evidence", required=True)
    for key in ("stage", "task_id", "run_id", "owner", "monitor", "reason", "qa_evidence", "final_sha256"):
        change.add_argument("--" + key.replace("_", "-"))
    change.add_argument("--new-over-paused", action="append", default=[])
    change.add_argument('--expected-revision', type=int)
    args = parser.parse_args(argv)
    registry = load(args.registry)
    if args.command == "sync":
        report = json.loads(args.report.read_text(encoding="utf-8"))
        with transaction(args.registry) as registry:
            sync(registry, report, args.report, args.run_id)
        print(f"Synced {registry['report']['candidate_count']} hot reels; production states preserved")
    elif args.command == 'context':
        print(json.dumps(context(registry, args.video_id), ensure_ascii=False, indent=2))
    elif args.command == "list":
        if args.report:
            sync(registry, json.loads(args.report.read_text(encoding="utf-8")), args.report)
        for item in ranked(registry, args.all):
            ref, prod = item["reference"], item["production"]
            print(f"{item['video_id']}\t{ref.get('published_date_kst') or '?'}\t#{ref.get('rank') or ref.get('rank_in_published_date') or '?'}"
                  f"\t{ref.get('rank_score') or '?'}\t{prod['state']}\t{(ref.get('assessment') or {}).get('status', '?')}")
    elif args.command == 'next':
        if args.report:
            sync(registry, json.loads(args.report.read_text('utf-8')), args.report)
        from .daily_ranking import select_next
        print(json.dumps(select_next(registry), ensure_ascii=False))
    elif args.command == "show":
        if args.report:
            sync(registry, json.loads(args.report.read_text(encoding="utf-8")), args.report)
        if args.video_id not in registry["posts"]:
            raise SystemExit(f"Unknown video ID: {args.video_id}")
        print(json.dumps(registry["posts"][args.video_id], ensure_ascii=False, indent=2))
    else:
        with transaction(args.registry, expected_revision=args.expected_revision) as registry:
            mark(registry, args.video_id, args.state, args.evidence, expected=args.expected_state,
                 stage=args.stage, task_id=args.task_id, run_id=args.run_id, owner=args.owner,
                 monitor=args.monitor, reason=args.reason, qa_evidence=args.qa_evidence,
                 final_sha256=args.final_sha256, new_over_paused=args.new_over_paused)
        print(f"{args.video_id}: {args.expected_state} -> {args.state}")


if __name__ == "__main__":
    main()
