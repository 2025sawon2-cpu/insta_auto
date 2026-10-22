"""Observed claim wall time; parallel intervals are never added as total time."""
import json
import time


def record(store, db, job, outcome, *, wait_kind=None, not_before=None):
    checkpoint = job.get('checkpoint', {})
    started = checkpoint.get('_claim_started_at')
    if started is None:
        return  # Do not invent timings for historical claims.
    now = time.time()
    store.event(db, job['task_id'], 'job_timing', {
        'job_id': job['id'], 'kind': job['kind'],
        'claim_token': checkpoint['_claim_token'], 'started_at': started,
        'observed_at': now, 'outcome': outcome,
        'claim_wall_seconds': max(0, now-started),
        'wait_kind': wait_kind, 'not_before': not_before,
        'measurement': 'claim_wall_including_unclassified_internal_waits',
    })
    return now


def summarize(events):
    """Keep stage sums diagnostic; only the interval union is elapsed work time."""
    rows = []
    for event in events:
        if event['kind'] != 'job_timing':
            continue
        detail = event['detail']
        rows.append(json.loads(detail) if isinstance(detail, str) else detail)
    closed = [r for r in rows if r['outcome'] not in {'claimed', 'interrupted_unknown_end'}]
    spans = sorted((r['started_at'], r['observed_at']) for r in closed)
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    by_kind = {}
    for row in closed:
        by_kind[row['kind']] = by_kind.get(row['kind'], 0)+row['claim_wall_seconds']
    return {'claim_wall_union_seconds': sum(b-a for a, b in merged),
            'stage_wall_seconds': by_kind, 'attempts': rows,
            'internal_waits_separately_measured': False}
