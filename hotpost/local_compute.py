"""Serialize local writing work; cloud speech owns no local GPU."""
from contextlib import contextmanager
from functools import wraps
import threading
import time
from .model_service import ModelServiceUnavailable
_lock = threading.RLock()
@contextmanager
def compute_slot(settings,kind):
    if kind == 'voice':
        yield
        return
    deadline=time.monotonic()+float(settings.studio_timeout)
    from .studio_pause import active_cancel,active_receipt_hook
    cancel,hook=active_cancel(),active_receipt_hook('supervision_wait')
    try:
        while not _lock.acquire(timeout=.5):
            if cancel:cancel()
            if hook:hook('local_compute')
            if time.monotonic()>=deadline:
                raise ModelServiceUnavailable('로컬 집필 작업 대기 시간이 초과됐습니다.',attempted=False)
        try:
            if cancel:cancel()
            yield
        finally:_lock.release()
    finally:
        if hook:hook(None)
def serialized_compute(kind):
    def decorate(method):
        @wraps(method)
        def run(self,*args,**kwargs):
            with compute_slot(self.settings,kind):return method(self,*args,**kwargs)
        return run
    return decorate
