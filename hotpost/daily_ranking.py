"""Rank one existing-Chrome snapshot of the last 72 hours; no growth tracking."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import time

MODE = 'views_per_follower_72h'
WINDOW = 72 * 3600
KST = timezone(timedelta(hours=9))
# User decision 2026-10-27: reels whose post body mentions Daiso are excluded from the 7 AM ranking.
EXCLUDED_TOPICS = {'daiso': re.compile(r'다이소|daiso', re.I)}


def post_body(caption):
    """Body text (with hashtags) from the collected panel text, without the header or comments.

    Panel text is: account, audio, 팔로우, account, NBSP, [수정됨, •,] age, body..., then
    comments as commenter, NBSP, age, text. Unrecognized layouts fall back to the whole text.
    """
    lines = caption.split('\n')
    if '\xa0' not in lines:
        return caption
    start = lines.index('\xa0') + 1
    while start < len(lines) and lines[start] in ('수정됨', '•'):
        start += 1
    start += 1  # age, e.g. "2일"
    end = next((i for i in range(start, len(lines) - 1) if lines[i + 1] == '\xa0'), len(lines))
    return '\n'.join(lines[start:end])


def excluded_topics(caption):
    body = post_body(caption)
    return [name for name, pattern in EXCLUDED_TOPICS.items() if pattern.search(body)]


def timestamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Observation timestamps must include a timezone')
    return parsed.timestamp()


def count(value):
    """Keep the visible label; abbreviated counts are usable approximate values."""
    raw = str(value).strip() if value is not None else ''
    text = re.sub(r'^(?:팔로워|조회수|followers|views)\s*', '', raw, flags=re.I)
    text = re.sub(r'\s*(?:명|회|followers|views)$', '', text, flags=re.I).strip()
    match = re.fullmatch(r'([\d,]+(?:\.\d+)?)\s*([천만억kKmMbB]?)', text)
    number = None
    if match:
        unit = match[2].lower()
        factor = {'': 1, '천': 1000, '만': 10000, '억': 100000000,
                  'k': 1000, 'm': 1000000, 'b': 1000000000}[unit]
        try:
            number = int(Decimal(match[1].replace(',', '')) * factor)
        except (InvalidOperation, ValueError):
            pass
    return {'raw': raw, 'value': number,
            'precision': 'missing' if number is None else 'approximate' if match[2] else 'exact'}


def build_report(profiles, details, grid, settings, *, generated_at=None):
    """Use only observations supplied for this run; never reuse yesterday's metrics."""
    started = timestamp(profiles['started_at'])
    if any(timestamp(item['started_at']) != started for item in (details, grid)):
        raise ValueError('Input files belong to different collection snapshots')
    accounts = []
    for row in profiles['accounts']:
        if row.get('observed_at') is not None and timestamp(row['observed_at']) < started:
            raise ValueError('Profile metrics predate the current collection')
        metric = count(row.get('followers'))
        accounts.append({'username': row['username'], 'followers': metric['value'],
                         'followers_display': metric['raw'], 'followers_metric': metric,
                         'observed_at': row.get('observed_at'),
                         'available': row.get('available', bool(row.get('cards', True))),
                         'full_name': row.get('full_name', '')})
    by_account = {row['username']: row for row in accounts}
    if len(by_account) != len(accounts):
        raise ValueError('Duplicate account observations')
    views = {row['href']: row for row in grid['rows']}
    if len(views) != len(grid['rows']):
        raise ValueError('Duplicate view observations')
    posts, seen = [], set()
    for row in details['rows']:
        match = re.fullmatch(r'/([^/]+)/(reel|p)/([A-Za-z0-9_-]+)/', row['href'])
        if not match or match[1] != row['username'] or row['username'] not in by_account:
            raise ValueError('Post identity differs from observed account')
        code = match[3]
        if code in seen:
            raise ValueError('Duplicate post observations')
        seen.add(code)
        published = timestamp(row['last'])
        if not started - WINDOW <= published <= started:
            continue
        account = by_account[row['username']]
        view = views.get(row['href'], {})
        if view.get('observed_at') is not None and timestamp(view['observed_at']) < started:
            raise ValueError('View metrics predate the current collection')
        metric = count(view.get('raw', view.get('views')))
        followers, total = account['followers'], metric['value']
        ratio = total / followers if total is not None and followers and followers > 0 else None
        caption = row.get('caption') or ''
        excluded = excluded_topics(caption)
        eligible = (match[2] == 'reel' and ratio is not None and not excluded
                    and total >= settings.acquisition_min_views
                    and ratio >= settings.acquisition_min_views_per_follower)
        tier = (3 if ratio >= settings.tier3_multiplier else
                2 if ratio >= settings.tier2_multiplier else 1) if eligible else 0
        posts.append({
            'shortcode': code, 'username': row['username'], 'taken_at': published,
            'kind': 'reel' if match[2] == 'reel' else 'image',
            'url': f'https://www.instagram.com/{match[2]}/{code}/',
            'caption': caption, 'hashtags': re.findall(r'#([\w가-힣]+)', caption),
            'views': total, 'views_display': metric['raw'], 'views_metric': metric,
            'followers': followers, 'followers_display': account['followers_display'],
            'views_per_follower': ratio, 'rank_score': ratio or 0,
            'multiplier': ratio or 0, 'tier': tier, 'ranking_mode': MODE,
            'eligible': eligible, 'evaluated_at': started,
            'likes': None, 'comments': None, 'thumb': row.get('thumb'),
            'video_duration': row.get('video_duration'), 'flags': [], 'terms': [],
            'categories': row.get('categories') or ['생활·기타'],
            'age_hours': (started - published) / 3600,
            'baseline': {}, 'ratios': {'views': ratio},
            'metric_status': {'views': metric['precision']},
            'assessment': {'status': 'qualified' if eligible else 'excluded' if excluded
                           else 'unavailable' if ratio is None else 'normal',
                           'label': '기준 통과' if eligible else '다이소 주제 제외' if excluded
                           else '수치 미확인' if ratio is None else '기준 미달',
                           'reasons': [f'excluded_topic:{name}' for name in excluded],
                           'scope': 'views_per_follower'},
        })
    posts.sort(key=lambda p: (-p['rank_score'], -(p['views'] or 0), -p['taken_at'], p['shortcode']))
    rank = 0
    for post in posts:
        if post['eligible']:
            rank += 1
            post['rank'] = rank
    generated = generated_at if generated_at is not None else time.time()
    return {
        'version': 'daily-72h-v1', 'ranking_mode': MODE, 'is_sample': False,
        'source': 'browser_ui_existing_chrome', 'generated_at': generated,
        'generated_at_kst': datetime.fromtimestamp(generated, KST).strftime('%Y-%m-%d %H:%M'),
        'collection_started_at': started,
        'window': {'start': started - WINDOW, 'end': started, 'hours': 72},
        'criteria': {'version': 1, 'values': {
            't1': settings.acquisition_min_views_per_follower,
            't2': settings.tier2_multiplier, 't3': settings.tier3_multiplier,
            'minViews': settings.acquisition_min_views}},
        'settings': {'recent_days': 3}, 'accounts': accounts, 'posts': posts, 'topics': [],
        'summary': {'accounts': len(accounts), 'posts': len(posts), 'hot': rank,
                    'reels': sum(p['kind'] == 'reel' for p in posts)},
        'collection_verification': {
            'scope': 'current_snapshot', 'approximate_counts_allowed': True,
            'growth_tracking': False,
            'excluded_topics': sorted(EXCLUDED_TOPICS),
            'excluded_posts': sum(p['assessment']['status'] == 'excluded' for p in posts),
            'missing_metrics': sum(p['assessment']['status'] == 'unavailable' for p in posts)},
    }


def select_next(registry):
    """Read-only selection. Only completed work is automatically skipped."""
    from .reference_registry import ranked, UNFINISHED
    unfinished = [p for p in registry['posts'].values() if p['production']['state'] in UNFINISHED]
    if unfinished:
        return {'action': 'review_existing', 'video_ids': [p['video_id'] for p in unfinished]}
    for item in ranked(registry):
        state = item['production']['state']
        if state == 'completed':
            # User decision 2026-10-27: a reviewed completion is final and is not rechecked.
            continue
        return {'action': 'start' if state == 'not_started' else 'audit_history',
                'video_id': item['video_id'], 'rank': item['reference'].get('rank')}
    return {'action': 'no_candidate'}


def public_production(code, production):
    result = {'state': production.get('state', 'unknown')}
    if result['state'] == 'completed':
        result['completed_video_ready'] = True
    return result


def publish(report, settings, snapshot_path):
    """Save current metrics/report and merge production states without starting work."""
    from .models import Post, Profile
    from .storage import Storage
    from .report import write_report
    from .reference_registry import transaction, sync
    prior = snapshot_path.with_name('previous-report.json')
    if settings.report_path.is_file():
        with prior.open('xb') as stream:
            stream.write(settings.report_path.read_bytes())
    store = Storage(settings.db_path)
    try:
        # Reserve novelty before the post upsert: a crash cannot turn an
        # unqueued new post into an old post on the next collection.
        from .collection_products import CollectionProducts
        known = [row[0] for row in store.conn.execute('SELECT shortcode FROM posts')]
        queued = CollectionProducts(settings.data_dir).enqueue(report, known)
        report['collection_products'] = {'queued': queued, 'browser_actions_started': False}
        old = store.profiles()
        from dataclasses import replace
        for account in report['accounts']:
            if account['followers'] is not None:
                profile = old.get(account['username']) or Profile(username=account['username'])
                store.upsert_profile(replace(profile, followers=account['followers']))
        fields = Post.__dataclass_fields__
        posts = []
        for post in report['posts']:
            values = {key: value for key, value in post.items() if key in fields}
            old_post = store.conn.execute('SELECT * FROM posts WHERE shortcode=?', (post['shortcode'],)).fetchone()
            if old_post:
                # These fields are no longer ranking inputs; preserve prior metadata.
                for key in ('likes', 'comments', 'thumbnail_url', 'video_duration', 'media_id'):
                    if values.get(key) is None or values.get(key) == '':
                        values[key] = old_post[key]
            posts.append(Post(**values))
        store.upsert_posts(posts)
        store.record_run(int(report['collection_started_at']), report['source'],
                         sum(a['available'] for a in report['accounts']),
                         sum(not a['available'] for a in report['accounts']),
                         len(report['posts']),
                         '72-hour current snapshot; views/followers; no growth tracking. ' + str(snapshot_path))
        report['collection_verification']['run_id'] = store.last_run()['id']
    finally:
        store.close()
    registry_path = settings.data_dir / 'reference-status.json'
    with transaction(registry_path) as registry:
        sync(registry, report, settings.report_path, report['collection_verification']['run_id'])
        for post in report['posts']:
            production = registry['posts'].get(post['shortcode'], {}).get('production', {})
            post['production'] = public_production(post['shortcode'], production)
        write_report(settings, report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--observations', type=Path, required=True,
                        help='Folder with current-run profile-cards, post-details and reel-grid-views JSON')
    parser.add_argument('--output', type=Path, required=True, help='New snapshot report path')
    parser.add_argument('--publish', action='store_true',
                        help='Also update local DB/dashboard/registry, preserving production state')
    args = parser.parse_args(argv)
    from .config import load_settings
    inputs = [json.loads((args.observations / name).read_text('utf-8')) for name in
              ('profile-cards.json', 'post-details.json', 'reel-grid-views.json')]
    settings = load_settings()
    report = build_report(*inputs, settings)
    # A new immutable snapshot first; publishing/syncing is a separate explicit step.
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    if args.publish:
        publish(report, settings, args.output)
    print(f"{report['summary']['hot']} qualified reels from the current 72-hour snapshot")


if __name__ == '__main__':
    main()
