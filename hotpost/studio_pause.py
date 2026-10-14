"""Cooperative acquisition stop; saved receipts and media remain on disk."""
from contextlib import contextmanager
import threading

_operation = threading.local()


class StudioPaused(RuntimeError):
    pass


def check_paused(store, job):
    state = store.get(job['task_id'])
    if state.get('automation', {}).get('paused_by_user'):
        raise StudioPaused('자동 진행 중지 · 수집 중간 자료와 실행 기록 보존')


def bind_progress(callback, source):
    callback.check_cancel = getattr(source, 'check_cancel', None)
    for name in ('source_attempt_created', 'source_worker_checkpoint', 'source_worker_settled'):
        setattr(callback, name, getattr(source, name, None))
    return callback


def active_cancel():
    return getattr(_operation, 'check_cancel', None)


def active_receipt_hook(name):
    return getattr(_operation, name, None)


@contextmanager
def pause_scope(progress):
    previous = active_cancel()
    names = ('source_attempt_created', 'source_worker_checkpoint', 'source_worker_settled')
    old_hooks = {name: active_receipt_hook(name) for name in names}
    _operation.check_cancel = getattr(progress, 'check_cancel', None)
    for name in names:
        setattr(_operation, name, getattr(progress, name, None))
    try:
        yield
    finally:
        _operation.check_cancel = previous
        for name, old in old_hooks.items():
            setattr(_operation, name, old)
