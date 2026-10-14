"""Calendar browsing shares the dashboard's first hot-discovery timestamp."""
from .daily_hot import date_key


def post_collection_dates(first_seen, detected_at=None):
    at = detected_at or first_seen
    return {'collected_at': first_seen, 'hot_detected_at': detected_at,
            'collection_date_at': at, 'collection_date_kst': date_key(at),
            'collection_date_basis': 'hot_detected' if detected_at else 'first_collected' if first_seen else 'unknown'}
