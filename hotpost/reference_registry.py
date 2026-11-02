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
BLOCK_KINDS = {'source_quality', 'content_quality', 'access', 'permission', 'technical'}


def _hold_kind(current, stage, block_kind):
    if block_kind is not None and block_kind not in BLOCK_KINDS:
        raise ValueError('Unknown block kind')
    if block_kind:
        return block_kind
    current_stage = current.get('stage') or ''
    proposed_stage = stage or current_stage
    if any(value.startswith('source') for value in (current_stage, proposed_stage)):
        return 'source_quality'
    if any(value in {'script', 'voice', 'edit', 'deliver', 'final_qa'}
           for value in (current_stage, proposed_stage)):
        return 'content_quality'
    return None


def _hold_review(value, *, code, current, kind):
    """Bind a hold judgment to existing files, not prove its semantic truth.

    The record may be a section of existing source answers/manifest JSON. It
    does not require a finished source stage or authorize any continued work.
    """
    from .final_qa import digest, file_input

    def text(value, label):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'Production hold review needs {label}')
        return value

    record_file = None
    if not isinstance(value, dict):
        if not value:
            raise ValueError('Production hold review is required; inspect existing intervals and next actions')
        try:
            record_file = file_input(value)
            value = json.loads(Path(record_file['path']).read_bytes())
        except (OSError, ValueError, TypeError) as error:
            raise ValueError('Production hold review must be an existing UTF-8 JSON record') from error
    record = value.get('hold_review', value) if isinstance(value, dict) else None
    if not isinstance(record, dict):
        raise ValueError('Production hold review must contain a record')
    for key, expected in (('video_id', code), ('task_id', current.get('task_id')),
                          ('run_id', current.get('run_id'))):
        if not expected or record.get(key) != expected:
            raise ValueError(f'Production hold review {key} differs from the current video/task/run')
    inputs = record.get('inputs')
    if not isinstance(inputs, list) or not inputs:
        raise ValueError('Production hold review needs current input files')
    bound = {}
    for item in inputs:
        if not isinstance(item, dict):
            raise ValueError('Production hold review needs input path, sha256 and role')
        path = Path(text(item.get('path'), 'input path'))
        if not path.is_absolute():
            raise ValueError('Production hold review input path must be absolute')
        try:
            actual = file_input(path)
        except (OSError, ValueError) as error:
            raise ValueError('Production hold review input file is unavailable') from error
        if actual['sha256'] != item.get('sha256'):
            raise ValueError('Production hold review input bytes changed after review')
        role = text(item.get('role'), 'input role')
        key = Path(actual['path'])
        if key in bound:
            raise ValueError('Production hold review input file is duplicated')
        bound[key] = {**actual, 'role': role}

    def evidence(rows, label, roles=None):
        if not isinstance(rows, list) or not rows:
            raise ValueError(f'Production hold review needs {label} evidence')
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f'Production hold review needs {label} observations')
            path = Path(text(row.get('input'), f'{label} input'))
            item = bound.get(path.resolve()) if path.is_absolute() else None
            if item is None or (roles and item['role'] not in roles):
                raise ValueError(f'Production hold review {label} evidence must refer to a bound input')
            text(row.get('location'), f'{label} location')
            text(row.get('observation'), f'{label} observation')

    if kind in {'access', 'permission', 'technical'}:
        evidence(record.get('blocker'), 'actual failure', {'failure'})
    else:
        roles = {item['role'] for item in bound.values()}
        purpose = {'script', 'brief', 'reference'} if kind == 'source_quality' else {'script'}
        if not {'source_review', 'rule'} <= roles or not purpose & roles:
            raise ValueError('Production hold review needs current script/subject, source_review and rule inputs')
        evidence(record.get('requirements'), 'current requirement', {'rule'})
        evidence(record.get('segments'), 'segment review', {'source', 'source_review'})
        alternatives = record.get('alternatives')
        if not isinstance(alternatives, list) or not alternatives:
            raise ValueError('Production hold review needs actual alternative results')
        for alternative in alternatives:
            if not isinstance(alternative, dict):
                raise ValueError('Production hold review needs actual alternative results')
            text(alternative.get('action'), 'alternative action')
            if alternative.get('outcome') not in {'ruled_out', 'unavailable'}:
                raise ValueError('Production hold review has an untried or viable alternative; inspect the next action')
            evidence(alternative.get('evidence'), 'alternative result')
        decision = record.get('main_decision')
        if not isinstance(decision, dict) or decision.get('decision') != 'hold':
            raise ValueError('Production hold review needs the main decision')
        evidence(decision.get('evidence'), 'main decision')
    if record_file and digest(record_file['path']) != record_file['sha256']:
        raise ValueError('Production hold review record changed during validation')
    for item in bound.values():
        if digest(item['path']) != item['sha256']:
            raise ValueError('Production hold review input bytes changed during validation')
    # A file hash records which existing review was used. Inline callers keep
    # their observations in history too; neither form establishes live roles.
    return {'kind': kind, **({'record': record_file} if record_file else
                            {'review': json.loads(json.dumps(record))}),
            'inputs': list(bound.values())}


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
    if state == 'completed':
        # User decision 2026-10-27: reviewed completions are final; later rule edits do not reopen them.
        qa = {'status': 'completed'}
    elif production.get('qa_evidence'):
        try:
            from .final_qa import validate
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
               'completed': 'skip_completed'}
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
         new_over_paused=(), stage_gates=None, hold_review=None, block_kind=None):
    if code not in registry["posts"]:
        raise ValueError(f"Unknown video ID: {code}")
    if state not in STATES or not evidence.strip():
        raise ValueError("Valid state and concrete evidence are required")
    current = registry["posts"][code]["production"]
    if current["state"] != expected:
        raise ValueError(f"State changed: expected {expected}, found {current['state']}")
    hold = None
    if state == 'blocked' and current['state'] == 'in_progress':
        kind = _hold_kind(current, stage, block_kind)
        if kind:
            for key, supplied in (('task_id', task_id), ('run_id', run_id),
                                  ('owner', owner), ('monitor', monitor)):
                if supplied is not None and supplied != current.get(key):
                    raise ValueError(f'Hold cannot change the bound {key}')
            hold = _hold_review(hold_review, code=code, current=current, kind=kind)
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
        _require_stage_gates(current, code, stage_gates, qa['video']['sha256'])
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
    if hold:
        updated['history'][-1]['hold_review'] = hold
    if state == "completed":
        updated["qa_evidence"] = qa["record_path"]
        updated["qa_record_sha256"] = qa["record_sha256"]
        updated["final_sha256"] = qa["video"]["sha256"]
        updated["cover_sha256"] = qa["cover"]["sha256"]
    registry["posts"][code]["production"] = updated
    return registry


def _require_stage_gates(current, code, gates, video_sha256):
    from . import stage_gate
    starts = [item['at'] for item in current.get('history', []) if item.get('to') == 'in_progress']
    if starts and datetime.fromisoformat(starts[0]) < stage_gate.REQUIRED_SINCE:
        return  # started before stage gates; finish on the original path
    if not gates:
        raise ValueError('Completion requires the task stage-gates directory (--stage-gates)')
    identity = {'video_id': code, 'task_id': current['task_id'], 'run_id': current['run_id']}
    stage_gate.require_complete(gates, identity)
    delivered = stage_gate.verify_end(gates, 'deliver', identity)['outputs']['delivery_receipt']
    if video_sha256 not in {item['sha256'] for item in delivered}:
        raise ValueError('Final QA video is not the delivered stage output')


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
    for key in ("stage", "task_id", "run_id", "owner", "monitor", "reason", "qa_evidence", "final_sha256",
                "stage_gates", "hold_review"):
        change.add_argument("--" + key.replace("_", "-"))
    change.add_argument('--block-kind', choices=sorted(BLOCK_KINDS),
                        help='Cause of a current hold; access/permission/technical also require bound failure evidence')
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
                 final_sha256=args.final_sha256, new_over_paused=args.new_over_paused,
                 stage_gates=args.stage_gates, hold_review=args.hold_review, block_kind=args.block_kind)
        print(f"{args.video_id}: {args.expected_state} -> {args.state}")


if __name__ == "__main__":
    main()
