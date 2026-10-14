"""New collection always uses the 24 hours preceding the run's start."""
import time

WINDOW_SECONDS = 24 * 3600


def collection_time(collector):
    return getattr(collector, 'collection_started_at', int(time.time()))


def in_collection_window(taken_at, started):
    return started - WINDOW_SECONDS <= taken_at <= started
