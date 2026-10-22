"""Distinguish internal evidence faults from external access waits."""
from .source_pause_receipts import SourceReceiptWaiting
from .source_preparation import PreparationEvidenceWaiting


def defer_source_wait(store, job, error, now):
    internal = isinstance(error, (SourceReceiptWaiting, PreparationEvidenceWaiting))
    return store.defer(job, str(error), max(1, error.retry_at - now),
                       waiting=not internal,
                       waiting_status='retry_wait' if internal else 'source_wait')
