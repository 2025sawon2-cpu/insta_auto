"""Read existing routes before repeating acquisition preparation.

This module never launches Chrome, imports cookies, navigates or searches.
"""
import json
import time
from pathlib import Path


class SourceAccessWaiting(RuntimeError):
    def __init__(self, message, retry_at=None, observations=None):
        super().__init__(message)
        self.retry_at = retry_at or time.time() + 30
        self.observations = observations or []


def observe_routes(settings, providers, *, context=None, now=None):
    from .search_access import access_record, manual_required, challenge_on_page, login_wall_on_page, observe_saved_captcha
    from .source_collection_access import disabled_platforms
    from .source_search.readiness import readiness_blocked
    from .source_browser_runtime import existing_page, endpoint
    now = time.time() if now is None else now
    disabled = disabled_platforms(settings)
    rows = []
    for provider in providers:
        row = {'provider':provider, 'query':'', 'attempted':False, 'observed_at':now}
        record = access_record(settings.data_dir, provider)
        if provider in disabled:
            row.update(status='platform_disabled', reason=disabled[provider])
        elif record.get('until', 0) > now and record.get('reason') not in {'captcha','login_required'}:
            row.update(status='cooldown', retry_at=record['until'], reason=record.get('reason',''))
        elif readiness_blocked(settings.data_dir, provider):
            row.update(status='readiness_blocked', reason='page_unresolved')
        elif provider in {'bing','duckduckgo','google-vision'} and settings.source_browser_search:
            row.update(status='not_attempted', reason='existing_browser_search_not_implemented')
        elif context is None:
            row.update(status='not_attempted', reason='existing_browser_session_unavailable')
        else:
            try:
                page = existing_page(context, settings, provider)
                # Empty/inaccessible bodies never establish clear access.
                body = page.locator('body').inner_text(timeout=5000)
                if not body.strip():
                    raise ValueError('unobservable_existing_page')
                if record.get('reason') == 'captcha' and manual_required(record):
                    observation = observe_saved_captcha(settings, provider, page)
                    if observation.get('status') != 'clear':
                        row.update(status=observation.get('status','unavailable'), reason='current_captcha_observation')
                        rows.append(row)
                        continue
                    record = access_record(settings.data_dir, provider)
                if challenge_on_page(page):
                    row.update(status='captcha', reason='current_visible_challenge')
                elif login_wall_on_page(page, provider):
                    row.update(status='login_required', reason='current_visible_login_wall')
                elif manual_required(record):
                    row.update(status='login_required' if record.get('reason')=='login_required' else 'verification_required',
                               reason='saved_manual_gate_requires_explicit_recheck')
                else:
                    row.update(status='ready', reason='current_existing_page_observed')
            except Exception as exc:
                row.update(status='not_attempted', reason=str(exc)[:180] or type(exc).__name__)
        rows.append(row)
    return rows


def current_routes(settings, providers):
    """Pure CDP attach only to a previously established live session."""
    from .source_browser_runtime import endpoint
    address = endpoint(settings)
    marker = settings.source_browser_profile_dir/'hotpost-live-session-v1'
    if not address or not marker.is_file():
        return observe_routes(settings, providers)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(address, timeout=10000)
            if not browser.contexts:
                return observe_routes(settings, providers)
            # Deliberately not attach_browser: no cookie migration or marker writes.
            return observe_routes(settings, providers, context=browser.contexts[0])
    except Exception:
        return observe_routes(settings, providers)


def check_access(settings, state, job, *, history=None, plan=None, frames=None, observe=None):
    """Return runnable routes; all unavailable routes leave the same claim waiting."""
    if not settings.source_browser_search:
        return None  # Indexed mode retains its own existing access gates.
    from .source_search.planner import TEXT_ROUTES, IMAGE_ROUTES, round_queries
    from .source_search.strategy import fresh_queries, fresh_frames
    from .source_queries import platform_queries, tiktok_product_queries
    providers = [*TEXT_ROUTES, *IMAGE_ROUTES]
    rows = (observe or current_routes)(settings, providers)
    words = [r['query'] for r in (plan or {}).get('query_details',[]) if r.get('query')]
    # Evaluate all finite condition pools; an exhausted phase must not hide unused scopes.
    if plan:
        for phase in ('core_action','clean_action','scene_discovery'):
            words += [r['query'] for r in round_queries(plan, {'phase':phase})]
        request=job.get('payload',{}).get('request','')
        if request:
            from .source_queries import feedback_queries, prioritize_tiktok_requests
            requested=feedback_queries(request)
            words += requested
            if requested:plan=prioritize_tiktok_requests(plan,requested)
    words = list(dict.fromkeys(words))
    ready = []
    for row in rows:
        if row['status'] != 'ready':
            continue
        provider = row['provider']
        if plan is not None:
            if provider in IMAGE_ROUTES:
                has_scope = bool(fresh_frames(frames or [], provider, history or []))
                supported=bool(frames)
            else:
                pool = tiktok_product_queries(plan, words) if provider == 'tiktok' else words
                pool = platform_queries(pool, provider, len(pool))
                has_scope = bool(fresh_queries(pool, provider, history or []))
                supported=bool(pool)
            if not has_scope:
                row.update(status='query_exhausted' if supported else 'no_supported_queries', reason='no_unused_supported_scope')
                continue
        ready.append(provider)
    checkpoint = job.setdefault('checkpoint',{})
    checkpoint['source_access_preflight'] = {'at':time.time(), 'observations':rows, 'ready_routes':ready}
    if ready:
        return ready
    until = max([time.time()+max(30,settings.source_browser_search_interval),
                 *(r.get('retry_at',0) or 0 for r in rows)])
    diagnostics = ', '.join(f"{r['provider']}:{r['status']}" for r in rows)
    raise SourceAccessWaiting('기존 소스 경로 또는 미사용 검색 근거 대기 · '+diagnostics, until, rows)
