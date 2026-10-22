"""Durable per-input/per-failure retry reservations, independent of job IDs."""
from __future__ import annotations

import copy
import hashlib
import json
import time

LIMIT = 2
POLICY = 'semantic-typed-retry-v1'
_VOLATILE = {
    'job_id', 'studio_job_id', 'run_id', 'claim_id', 'claim_token', '_claim_token',
    'request_id', 'trace_id', 'attempt_id', 'owner', 'created', 'updated',
    'created_at', 'updated_at', 'queued_at', 'started_at', 'finished_at',
    'timestamp', 'retry_at', 'not_before', 'auto_retries', 'service_retries',
    'retry_count', 'retry_requested', 'retry_budget', 'supervision',
    'output_path', 'output_dir', 'work_dir', 'log_path',
}


def _stable(value):
    if isinstance(value, dict):
        return {str(k): _stable(v) for k, v in value.items() if str(k) not in _VOLATILE}
    if isinstance(value, (list, tuple)):
        return [_stable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError('Retry input must contain serializable semantic values.')


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _sha(value):
    return hashlib.sha256(_dump(value).encode('utf-8')).hexdigest()


def _material(job, classification, state):
    payload = _stable(job.get('payload') or {})
    # These are output identities, not the selected input identities below.
    output_ids = {'voice': ('voice_id',), 'edit': ('edit_id',),
                  'quality_reedit': ('edit_id',), 'rewrite': ('script_id',)}
    for key in output_ids.get(job.get('kind'), ()):
        payload.pop(key, None)
    script_id = (job.get('payload') or {}).get('script_id') if job.get('kind') == 'voice' else None
    script_id = script_id or state.get('script_id')
    voice_id = state.get('voice_id')
    script = next((s for s in state.get('scripts', []) if s.get('id') == script_id), {})
    voice = next((s for s in state.get('voices', []) if s.get('id') == voice_id), {})
    sources = []
    by_id = {}
    for source in state.get('sources', []):
        if not source.get('sha256'):
            continue
        by_id[source.get('id')] = source['sha256']
        row = {k: _stable(source[k]) for k in ('sha256', 'original_sha256', 'original_interval',
            'retiming', 'source_role') if k in source}
        row['reviewed_intervals'] = [{k: r[k] for k in ('source_start', 'source_end') if k in r}
                                     for r in (source.get('reviewed_intervals') or [])]
        row['watermark_masks'] = [{k: r[k] for k in ('source_start', 'source_end', 'rectangle',
            'strength', 'expected_scale') if k in r} for r in (source.get('watermark_masks') or [])]
        row['reviewed_intervals'] = sorted(row['reviewed_intervals'], key=_dump)
        row['watermark_masks'] = sorted(row['watermark_masks'], key=_dump)
        sources.append(row)
    if isinstance(payload.get('source_ids'), list):
        payload['source_ids'] = sorted(by_id.get(s, s) for s in payload['source_ids'])
    repair = (job.get('payload') or {}).get('repair_input_signature') or (
        job.get('checkpoint') or {}).get('repair_input_signature') or state.get('repair_input_signature')
    return {'policy': POLICY, 'task_id': job.get('task_id') or state.get('id'),
        'kind': job.get('kind'), 'payload': payload,
        'selected_script': {'id': script_id, 'text_sha256': _sha(script['text']) if 'text' in script else None},
        'selected_voice': {'id': voice_id, 'sha256': voice.get('sha256')},
        'sources': [json.loads(row) for row in sorted({_dump(s) for s in sources})],
        'repair_input_signature': repair,
        'reference_sha256': state.get('reference_sha256'),
        'original_text_sha256': _sha(state.get('original_text', '')),
        'product': state.get('product'), 'source_policy': _stable(state.get('source_policy')),
        'failure': {k: _stable(classification.get(k)) for k in ('category', 'reason', 'signature_material')}}


def reserve(store, job, classification, state):
    """Atomically reserve at most two retries for the same semantic failure.

    Append every call, including denied calls. Service/access/no-progress waits do
    not consume the budget. A current claim's diagnostic checkpoint is persisted
    here so a denied reservation survives the caller's subsequent fail operation.
    No job is enqueued, retried, completed, or reset by this function.
    """
    material = _material(job, classification, state)
    fingerprint = _sha(material)
    eligible = (classification.get('retryable') is True
                and classification.get('category') in {'transport', 'http_status'})
    token = job.get('claim_token') or (job.get('checkpoint') or {}).get('_claim_token') or ''
    diagnostic = None
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS retry_budget_attempts (
            id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL, task_id TEXT NOT NULL,
            job_id TEXT NOT NULL, claim_token TEXT NOT NULL, created REAL NOT NULL,
            eligible INTEGER NOT NULL, reserved INTEGER NOT NULL, reason TEXT NOT NULL,
            classification TEXT NOT NULL, material TEXT NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS retry_budget_fingerprint ON retry_budget_attempts(fingerprint,reserved)')
        owned = not token or store.owns(db, job)
        used = db.execute('SELECT COUNT(*) FROM retry_budget_attempts WHERE fingerprint=? AND reserved=1',
                          (fingerprint,)).fetchone()[0]
        duplicate = bool(token and db.execute('''SELECT 1 FROM retry_budget_attempts
            WHERE fingerprint=? AND job_id=? AND claim_token=? AND reserved=1 LIMIT 1''',
            (fingerprint, job.get('id', ''), token)).fetchone())
        allowed = bool(eligible and owned and not duplicate and used < LIMIT)
        reason = ('stale_claim' if not owned else 'not_retryable' if not eligible else
                  'duplicate_reservation' if duplicate else 'budget_exhausted' if used >= LIMIT else 'reserved')
        cursor = db.execute('''INSERT INTO retry_budget_attempts
            (fingerprint,task_id,job_id,claim_token,created,eligible,reserved,reason,classification,material)
            VALUES(?,?,?,?,?,?,?,?,?,?)''', (fingerprint, str(job.get('task_id') or state.get('id') or ''),
            str(job.get('id') or ''), token, time.time(), int(eligible), int(allowed), reason,
            _dump(classification), _dump(material)))
        diagnostic = {'policy': POLICY, 'fingerprint': fingerprint, 'attempt_id': cursor.lastrowid,
                      'used': used + int(allowed), 'limit': LIMIT, 'reserved': allowed, 'reason': reason}
        if token and owned:
            saved = json.loads(db.execute('SELECT checkpoint FROM jobs WHERE id=?', (job['id'],)).fetchone()[0])
            saved['retry_budget'] = diagnostic
            db.execute('UPDATE jobs SET checkpoint=? WHERE id=?', (_dump(saved), job['id']))
    job.setdefault('checkpoint', {})['retry_budget'] = copy.deepcopy(diagnostic)
    return allowed
