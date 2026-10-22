"""Cooperative acquisition stop; saved receipts and media remain on disk."""
from contextlib import contextmanager
import threading

_operation = threading.local()
PAUSE_MESSAGE = '자동 진행 중지 · 수집 중간 자료와 실행 기록 보존'


class StudioPaused(RuntimeError):
    pass


def check_paused(store, job):
    supervisor = getattr(store, 'supervisor', None)
    if supervisor:
        supervisor.check(job)
    state = store.get(job['task_id'])
    if state.get('automation', {}).get('paused_by_user'):
        payload = job.get('payload', {})
        if (job.get('kind') == 'refresh_sources' and payload.get('manual_source_request') is True
                and payload.get('pause_token') is not None
                and payload['pause_token'] == state['automation'].get('paused_at')):
            return  # This exact request is allowed; a later pause revokes it.
        raise StudioPaused(PAUSE_MESSAGE)


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
    names = ('source_attempt_created', 'source_worker_checkpoint', 'source_worker_settled', 'supervision_model', 'supervision_cancel', 'supervision_resume', 'supervision_wait', 'supervision_voice')
    old_hooks = {name: active_receipt_hook(name) for name in names}
    _operation.check_cancel = getattr(progress, 'check_cancel', None)
    for name in names:
        setattr(_operation, name, getattr(progress, name, old_hooks[name] if name.startswith('supervision_') else None))
    try:
        yield
    finally:
        _operation.check_cancel = previous
        for name, old in old_hooks.items():
            setattr(_operation, name, old)
