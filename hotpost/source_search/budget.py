"""Measure provider probing separately from local candidate verification."""
from contextlib import contextmanager
import time


@contextmanager
def charge_platform_probe(seconds, platform):
    """Charge only acquisition, including pacing/failures, to its platform.

    OCR, CLIP and local AI queue waits happen outside this scope. The caller
    does not use elapsed platform time as an execution limit.
    """
    started = time.monotonic()
    try:
        yield
    finally:
        seconds[platform] = seconds.get(platform, 0) + time.monotonic() - started
