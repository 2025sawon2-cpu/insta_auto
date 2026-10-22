"""Real-time subprocess watcher for a Studio production task.

Monitors task state, jobs, operation_progress.json, writing jobs, and search queries.
Records a JSONL timeline and immediately exits with code 2 if a defect (such as
no-progress repetitive work, SQLite lock failure, bad search query, or unexpected
hold/failure) is detected so the main agent can record and fix the code right away.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def read_json_safe(path: Path) -> dict:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def inspect_task(task_id: str) -> dict:
    studio_db = ROOT / "data/studio/studio.sqlite3"
    with sqlite3.connect(studio_db.as_uri() + "?mode=ro", uri=True, timeout=10.0) as db:
        db.row_factory = sqlite3.Row
        t_row = db.execute("SELECT id, shortcode, revision, state, updated FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not t_row:
            return {"exists": False}
        state = json.loads(t_row["state"] or "{}")
        jobs = [
            {
                "id": r["id"],
                "kind": r["kind"],
                "status": r["status"],
                "key": r["key"],
                "error": r["error"],
                "created": r["created"],
                "updated": r["updated"],
                "checkpoint": json.loads(r["checkpoint"] or "{}"),
                "payload": json.loads(r["payload"] or "{}"),
            }
            for r in db.execute(
                "SELECT id, kind, status, key, error, created, updated, checkpoint, payload "
                "FROM jobs WHERE task_id=? ORDER BY created DESC, rowid DESC LIMIT 20",
                (task_id,),
            )
        ]

    task_dir = ROOT / "data/studio" / task_id
    op_summaries = {}
    search_queries = []
    if task_dir.is_dir():
        for op_file in sorted(task_dir.glob("*/operation_progress.json")):
            op_data = read_json_safe(op_file)
            if op_data:
                op_summaries[str(op_file.relative_to(ROOT))] = op_data.get("stage_summary") or {
                    "stage": op_data.get("stage"),
                    "step": op_data.get("step"),
                    "completed": op_data.get("completed"),
                    "total": op_data.get("total"),
                    "updated_at": op_data.get("updated_at"),
                }
        for manifest_file in sorted(task_dir.glob("*/manifest.json")):
            m_data = read_json_safe(manifest_file)
            if m_data:
                q_list = m_data.get("queries") or m_data.get("search_queries") or []
                if q_list:
                    search_queries.append((str(manifest_file.relative_to(ROOT)), q_list))

    # Also check writing jobs db for recent jobs created since task creation
    writing_jobs = []
    task_created = float(state.get("created") or 0)
    writing_db = ROOT / "data/writing/jobs.sqlite3"
    if writing_db.is_file():
        try:
            with sqlite3.connect(writing_db.as_uri() + "?mode=ro", uri=True, timeout=5.0) as wdb:
                wdb.row_factory = sqlite3.Row
                for wrow in wdb.execute(
                    "SELECT id, kind, state, progress, message, error, created FROM jobs WHERE created >= ? ORDER BY created DESC LIMIT 15",
                    (task_created - 5.0,),
                ):
                    writing_jobs.append(dict(wrow))
        except Exception:
            pass

    dq = state.get("daily_quality") or {}
    latest_edit = state.get("edits", [-1])[-1] if state.get("edits") else {}
    return {
        "exists": True,
        "at": now_kst(),
        "ts": time.time(),
        "task_id": task_id,
        "shortcode": t_row["shortcode"],
        "revision": t_row["revision"],
        "status": state.get("status"),
        "message": state.get("message"),
        "error": state.get("error"),
        "product": state.get("product"),
        "sources_count": len(state.get("sources") or []),
        "editing_ready_count": sum(1 for s in (state.get("sources") or []) if s.get("editing_eligible")),
        "scripts_count": len(state.get("scripts") or []),
        "voices_count": len(state.get("voices") or []),
        "edits_count": len(state.get("edits") or []),
        "latest_edit_id": state.get("edit_id"),
        "export_verified": bool(latest_edit.get("export_verified")),
        "daily_quality_status": dq.get("status"),
        "daily_quality_pending": dq.get("pending"),
        "daily_quality_repair_round": dq.get("repair_round"),
        "daily_quality_reviews_count": len(dq.get("reviews") or []),
        "source_hold": (state.get("source_acquisition") or {}).get("hold"),
        "editorial_hold": state.get("editorial_content_hold"),
        "jobs": jobs,
        "op_summaries": op_summaries,
        "search_queries": search_queries,
        "writing_jobs": writing_jobs,
    }


def detect_defects(snap: dict, history: list[dict], stall_seconds: int) -> list[dict]:
    defects = []
    at = snap["at"]

    # 1. Check failed or retry_wait jobs or SQLite lock errors
    for j in snap.get("jobs", []):
        if j["status"] == "failed":
            defects.append({
                "at": at,
                "kind": "job_failed",
                "job_id": j["id"],
                "job_kind": j["kind"],
                "cause": j.get("error") or "Job marked failed",
                "evidence_path": f"data/studio/studio.sqlite3#jobs.{j['id']}",
            })
        auto_retries = (j.get("checkpoint") or {}).get("auto_retries", 0)
        if auto_retries and auto_retries >= 1 and j["status"] in {"queued", "running"}:
            defects.append({
                "at": at,
                "kind": "job_auto_retry",
                "job_id": j["id"],
                "job_kind": j["kind"],
                "auto_retries": auto_retries,
                "cause": f"Job {j['kind']} triggered auto_retries={auto_retries} (status={snap.get('status')}, msg={snap.get('message')})",
                "evidence_path": f"data/studio/studio.sqlite3#jobs.{j['id']}",
            })

    # 2. Check writing_jobs failure or lock error
    for wj in snap.get("writing_jobs") or []:
        if wj.get("state") == "failed" or "database is locked" in str(wj.get("error") or ""):
            defects.append({
                "at": at,
                "kind": "writing_job_error",
                "writing_job_id": wj.get("id"),
                "cause": wj.get("error") or f"Writing job state={wj.get('state')}",
                "evidence_path": f"data/writing/jobs/{wj.get('id')}/result.json",
            })

    # 3. Check unexpected holds (source_hold, editorial_hold, scene_wait, exhausted, failed, attention)
    if snap.get("status") in {"attention", "failed", "paused"}:
        defects.append({
            "at": at,
            "kind": "task_stopped_or_attention",
            "status": snap.get("status"),
            "cause": snap.get("error") or snap.get("message") or "Task entered stopped/attention status",
            "evidence_path": f"data/studio/studio.sqlite3#tasks.{snap['task_id']}",
        })
    if snap.get("daily_quality_pending") in {"exhausted", "failed", "scene_wait"}:
        defects.append({
            "at": at,
            "kind": "quality_loop_hold",
            "pending": snap.get("daily_quality_pending"),
            "cause": f"daily_quality.pending={snap.get('daily_quality_pending')} (msg={snap.get('message')})",
            "evidence_path": f"data/studio/studio.sqlite3#tasks.{snap['task_id']}.daily_quality",
        })
    if snap.get("source_hold"):
        defects.append({
            "at": at,
            "kind": "source_acquisition_hold",
            "cause": json.dumps(snap["source_hold"], ensure_ascii=False),
            "evidence_path": f"data/studio/studio.sqlite3#tasks.{snap['task_id']}.source_acquisition.hold",
        })

    # 4. Check search query quality (e.g., overly long sentence queries > 6 tokens on TikTok or duplicate queries)
    for m_path, q_list in snap.get("search_queries", []):
        seen_q = set()
        for q_item in q_list:
            q_str = q_item.get("query") if isinstance(q_item, dict) else str(q_item)
            if not q_str:
                continue
            norm = re.sub(r"\s+", " ", q_str.strip().lower())
            if norm in seen_q:
                defects.append({
                    "at": at,
                    "kind": "duplicate_search_query",
                    "cause": f"Duplicate search query in manifest: {q_str!r}",
                    "evidence_path": m_path,
                })
            seen_q.add(norm)
            if len(norm.split()) > 6:
                defects.append({
                    "at": at,
                    "kind": "overlong_search_query",
                    "cause": f"Search query exceeds 6 words ({len(norm.split())} words): {q_str!r}",
                    "evidence_path": m_path,
                })

    # 5. Check no-progress stall across history
    if history:
        # Find earliest snapshot with identical progress fingerprint
        def fingerprint(s: dict) -> str:
            running_jobs = [(j["id"], j["kind"], j["status"], j["updated"]) for j in s.get("jobs", [])[:3]]
            return json.dumps(
                {
                    "rev": s.get("revision"),
                    "status": s.get("status"),
                    "jobs": running_jobs,
                    "ops": s.get("op_summaries"),
                    "wj": s.get("writing_jobs"),
                },
                sort_keys=True,
                ensure_ascii=False,
            )

        cur_fp = fingerprint(snap)
        earliest_same_ts = snap["ts"]
        for past in reversed(history):
            if fingerprint(past) == cur_fp:
                earliest_same_ts = past["ts"]
            else:
                break
        elapsed_without_progress = snap["ts"] - earliest_same_ts
        if elapsed_without_progress >= stall_seconds:
            defects.append({
                "at": at,
                "kind": "no_progress_stall",
                "elapsed_seconds": round(elapsed_without_progress, 1),
                "cause": f"No state/job/operation_progress change for {elapsed_without_progress:.0f}s while in status={snap.get('status')} ({snap.get('message')})",
                "evidence_path": f"data/studio/{snap['task_id']}",
            })

    return defects


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--log-jsonl", required=True)
    parser.add_argument("--defect-json", required=True)
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--stall-seconds", type=int, default=240)
    parser.add_argument("--max-Wait-seconds", type=int, default=1800)
    args = parser.parse_args()

    log_path = Path(args.log_jsonl)
    defect_path = Path(args.defect_json)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    defect_path.parent.mkdir(parents=True, exist_ok=True)

    history: list[dict] = []
    start_ts = time.time()
    last_printed_summary = None

    while time.time() - start_ts < args.max_Wait_seconds:
        snap = inspect_task(args.task_id)
        if not snap.get("exists"):
            print(f"[{now_kst()}] Task {args.task_id} not found yet...", flush=True)
            time.sleep(args.interval)
            continue

        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(snap, ensure_ascii=False) + "\n")

        active_jobs = [(j["kind"], j["status"], j["id"]) for j in snap.get("jobs", []) if j["status"] in {"running", "queued"}]
        summary_line = (
            f"rev={snap['revision']} status={snap['status']} msg={snap['message']!r} "
            f"sources={snap['sources_count']}(ready={snap['editing_ready_count']}) "
            f"scripts={snap['scripts_count']} voices={snap['voices_count']} edits={snap['edits_count']} "
            f"dq={snap['daily_quality_status']}/{snap['daily_quality_pending']}(r={snap['daily_quality_repair_round']}) "
            f"active_jobs={active_jobs} ops={list(snap['op_summaries'].values())}"
        )
        if summary_line != last_printed_summary:
            print(f"[{snap['at']}] {summary_line}", flush=True)
            last_printed_summary = summary_line

        if (
            snap.get("status") == "completed"
            and snap.get("daily_quality_status") == "passed"
            and snap.get("export_verified")
        ):
            print(f"[{snap['at']}] [TASK_COMPLETED] {args.task_id} completed and verified!", flush=True)
            return 0

        defects = detect_defects(snap, history, args.stall_seconds)
        if defects:
            existing = []
            if defect_path.is_file():
                try:
                    existing = json.loads(defect_path.read_text(encoding="utf-8"))
                except Exception:
                    existing = []
            seen_keys = {
                d.get("defect_key")
                for d in existing
                if isinstance(d, dict) and d.get("defect_key")
            }
            new_defects = []
            for d in defects:
                d_key = f"{d['kind']}:{d.get('job_id') or d.get('writing_job_id') or d.get('pending') or d.get('status') or ''}:{d.get('evidence_path')}:{d.get('cause')}"
                d["defect_key"] = d_key
                if d_key not in seen_keys:
                    new_defects.append(d)
                    seen_keys.add(d_key)
            if new_defects:
                existing.extend(new_defects)
                defect_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"[{snap['at']}] [DEFECT_DETECTED] {json.dumps(new_defects, ensure_ascii=False)}", flush=True)
                return 2

        history.append(snap)
        time.sleep(args.interval)

    print(f"[{now_kst()}] [WATCH_WINDOW_ELAPSED] Watcher window ({args.max_Wait_seconds}s) elapsed; re-invoke to continue watching.", flush=True)
    return 3


if __name__ == "__main__":
    sys.exit(main())
