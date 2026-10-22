"""Small, sanitized transfer receipts; writing a receipt is never progress."""
import time
from pathlib import Path


def event(stats, stage=None, **values):
    now = time.time()
    stats.setdefault('started_at', now)
    if stage and stats.get('stage') != stage:
        rows = stats.setdefault('stage_events', [])
        if len(rows) < 40:
            rows.append({'stage':stage, 'at':now})
        stats['stage'] = stage
    stats.update(values)
    checkpoint = stats.get('_checkpoint')
    if checkpoint:
        checkpoint()


def attach(stats, path):
    from .editing_adapter import _atomic_json
    from .source_attempts import transfer_diagnostics
    def checkpoint():
        _atomic_json(Path(path), transfer_diagnostics(stats))
    stats['_checkpoint'] = checkpoint
    event(stats, 'starting')


def finish(stats, *, error=None):
    values = {'ended_at':time.time(), 'complete':error is None}
    if error is not None:
        values.update(failure_stage=stats.get('stage', 'unknown'), error_type=type(error).__name__,
                      error=str(error)[:500])
    event(stats, 'failed' if error else 'complete', **values)
