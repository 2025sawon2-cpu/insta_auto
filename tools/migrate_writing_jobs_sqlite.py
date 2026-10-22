"""Losslessly offload inline payloads from data/writing/jobs.sqlite3 to payload.json, compact media, VACUUM, and enable WAL."""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from hotpost.production import file_lock
from hotpost.writing.jobs import Jobs

ROOT = Path(__file__).resolve().parents[1]
WRITING_ROOT = ROOT / 'data/writing'
REPORT_PATH = ROOT / 'data/live-validation-20261014/sqlite-migration-report.json'


def _breakdown(db: sqlite3.Connection) -> list[dict]:
    rows = db.execute(
        'SELECT kind, state, COUNT(*), '
        'ROUND(COALESCE(SUM(LENGTH(payload)), 0) / 1048576.0, 2), '
        'ROUND(COALESCE(SUM(LENGTH(result)), 0) / 1048576.0, 2) '
        'FROM jobs GROUP BY kind, state ORDER BY kind, state'
    ).fetchall()
    return [
        {
            'kind': r[0],
            'state': r[1],
            'count': r[2],
            'payload_mb': r[3],
            'result_mb': r[4],
        }
        for r in rows
    ]


def migrate(writing_root: Path = WRITING_ROOT, report_path: Path | None = REPORT_PATH) -> dict:
    started = time.monotonic()
    db_path = writing_root / 'jobs.sqlite3'
    if not db_path.is_file():
        raise FileNotFoundError(f'Missing {db_path}')

    before_size_bytes = db_path.stat().st_size
    jobs = Jobs(writing_root)

    with file_lock(writing_root / 'worker.lock'):
        conn = sqlite3.connect(db_path, timeout=60)
        try:
            conn.execute('PRAGMA busy_timeout=60000')
            before_journal = conn.execute('PRAGMA journal_mode').fetchone()[0]
            before_total = conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
            before_breakdown = _breakdown(conn)
            non_null_ids = [
                r[0]
                for r in conn.execute('SELECT id FROM jobs WHERE payload IS NOT NULL').fetchall()
            ]

            offloaded = 0
            compacted = 0
            sample_editorial_id = None
            sample_script_id = None

            for jid in non_null_ids:
                row = conn.execute('SELECT kind, payload FROM jobs WHERE id=?', (jid,)).fetchone()
                if not row or not row[1]:
                    continue
                kind, raw_payload = row[0], row[1]
                parsed = json.loads(raw_payload)
                if jobs._compact_payload_media(jid, parsed):
                    compacted += 1
                else:
                    jobs._save_payload(jid, parsed)
                payload_file = writing_root / jid / 'payload.json'
                if not payload_file.is_file() or payload_file.stat().st_size == 0:
                    raise RuntimeError(f'Failed to persist payload.json for {jid}')
                offloaded += 1
                if kind == 'editorial' and sample_editorial_id is None and isinstance(parsed, dict) and parsed.get('media'):
                    sample_editorial_id = jid
                elif kind == 'script' and sample_script_id is None:
                    sample_script_id = jid

            with conn:
                conn.execute('UPDATE jobs SET payload = NULL WHERE payload IS NOT NULL')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_jobs_state_created ON jobs(state, created)')
        finally:
            conn.close()

        # Run VACUUM in autocommit mode while still in DELETE journal mode so a multi-GB WAL is not created.
        vacuum_conn = sqlite3.connect(db_path, timeout=60, isolation_level=None)
        try:
            vacuum_conn.execute('PRAGMA busy_timeout=60000')
            vacuum_conn.execute('VACUUM')
            after_journal = vacuum_conn.execute('PRAGMA journal_mode=WAL').fetchone()[0]
            vacuum_conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            after_total = vacuum_conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
            after_breakdown = _breakdown(vacuum_conn)
            indexes = [
                r[1]
                for r in vacuum_conn.execute("PRAGMA index_list('jobs')").fetchall()
            ]
        finally:
            vacuum_conn.close()

    after_size_bytes = db_path.stat().st_size
    if before_total != after_total:
        raise RuntimeError(f'Row count mismatch after migration: {before_total} != {after_total}')

    # Verify lossless payload re-hydration via Jobs.get(..., include_payload=True)
    verification = {}
    if sample_editorial_id:
        loaded_ed = jobs.get(sample_editorial_id, include_payload=True)
        media_parts = [
            p for p in (loaded_ed.get('payload') or {}).get('media', [])
            if isinstance(p, dict) and 'inlineData' in p
        ]
        first_b64 = media_parts[0]['inlineData']['data'] if media_parts else ''
        decoded_len = len(base64.b64decode(first_b64, validate=True)) if first_b64 else 0
        verification['sample_editorial'] = {
            'id': sample_editorial_id,
            'media_image_count': len(media_parts),
            'first_image_decoded_bytes': decoded_len,
            'rehydrated_ok': decoded_len > 0,
        }
    if sample_script_id:
        loaded_sc = jobs.get(sample_script_id, include_payload=True)
        verification['sample_script'] = {
            'id': sample_script_id,
            'has_reference_script': bool((loaded_sc.get('payload') or {}).get('reference_script')),
        }

    report = {
        'migrated_at': datetime.now().astimezone().isoformat(),
        'elapsed_seconds': round(time.monotonic() - started, 2),
        'db_path': str(db_path),
        'before': {
            'file_size_bytes': before_size_bytes,
            'file_size_mb': round(before_size_bytes / 1048576.0, 2),
            'journal_mode': before_journal,
            'total_rows': before_total,
            'breakdown': before_breakdown,
        },
        'after': {
            'file_size_bytes': after_size_bytes,
            'file_size_mb': round(after_size_bytes / 1048576.0, 2),
            'reduction_pct': round((1.0 - after_size_bytes / max(1, before_size_bytes)) * 100.0, 2),
            'journal_mode': after_journal,
            'indexes': indexes,
            'total_rows': after_total,
            'breakdown': after_breakdown,
        },
        'offloaded_rows': offloaded,
        'compacted_media_rows': compacted,
        'verification': verification,
    }
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    result = migrate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
