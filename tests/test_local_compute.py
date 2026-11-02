from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from hotpost.local_compute import compute_slot

def test_cloud_voice_does_not_wait_for_local_writing():
    settings=SimpleNamespace(studio_timeout=2)
    with compute_slot(settings,'script'):
        with ThreadPoolExecutor(max_workers=1) as pool:
            def voice():
                with compute_slot(settings,'voice'):return 'cloud'
            assert pool.submit(voice).result(timeout=1)=='cloud'

def test_local_writing_is_serialized():
    settings=SimpleNamespace(studio_timeout=2);entered=Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with compute_slot(settings,'script'):
            def other():
                with compute_slot(settings,'script'):entered.set()
            result=pool.submit(other)
            assert not entered.wait(.1)
        result.result(timeout=1)
        assert entered.is_set()
