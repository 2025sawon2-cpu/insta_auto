"""Candidate discovery with injectable provider services and shortlist-first routing."""
from ..source_urls import canonical_video_key
from ..source_queries import platform_queries, language, tiktok_product_queries
from .strategy import fresh_queries


def discover(settings, shortcode, frames, queries, query_plan, vision_candidates, root,
             previous_searches, exclude_urls, progress, services, deferred=None):
    # Known public URLs still pass the same download, duplicate and visual gates.
    # Probe new URLs first; when exhausted the next round resumes discovery.
    used = {canonical_video_key(url) for url in exclude_urls or [] if url}
    from ..source_collection_access import disabled_platforms
    disabled = disabled_platforms(settings)
    cached = getattr(services, 'search_local_cache', lambda *args: [])(settings, shortcode, settings.source_max_candidates)
    from .library import discover as library_candidates
    library = library_candidates(settings, shortcode, query_plan, settings.source_max_candidates)
    pools = [('deferred-candidates', deferred or []),
             ('operator-shortlist', services.search_local_hints(settings, shortcode)),
             ('local-cache', cached), ('source-library', library)]
    from ..search_access import access_record, manual_required
    shortlist, shortlist_audit, seen = [], [], set(used)
    for provider, candidates in pools:
        added = 0
        for candidate in candidates:
            identity = canonical_video_key(candidate.url)
            if identity in seen or candidate.platform in disabled:
                continue
            if provider == 'deferred-candidates' and manual_required(access_record(settings.data_dir, candidate.platform)):
                continue
            shortlist.append(candidate)
            seen.add(identity)
            added += 1
        if added:
            shortlist_audit.append({'provider':provider, 'query':'', 'status':'results', 'candidates':added})
    tiktok_preference = max(0, settings.source_tiktok_min_usable)
    minimums=query_plan.get('search_minimums') or {}
    from ..source_coverage import actual_search_coverage
    coverage=actual_search_coverage(previous_searches or [],minimums,query_plan.get('search_identity'))
    pending=bool(minimums) and not all(r['ready'] for r in coverage.values())
    search_only=bool(query_plan.get('search_only'))
    if not pending and (shortlist or search_only):
        label = '저장된 소스·공개' if any(row['provider'] in {'local-cache','source-library'} for row in shortlist_audit) else '시간 부족으로 미검증한' if deferred else '확보한 공개'
        progress(f"{label} 후보 {len(shortlist)}개부터 검증하는 중", 42)
        browser = {"candidates": [], "terms": [], "notes": []}
        return shortlist, queries, browser, shortlist_audit, tiktok_preference
    browser_result = {"candidates": [], "terms": [], "notes": []}
    strategy = query_plan.get('search_strategy')
    allowed = strategy['routes'] if strategy else None
    search_audit = list(shortlist_audit)
    def enabled(provider):
        return allowed is None or provider in allowed
    def run_browser():
        nonlocal browser_result
        if settings.source_browser_search:
            from ..browser_search import browser_search
            options = {'routes':allowed} if strategy else {}
            options['provider_queries'] = {'tiktok': tiktok_product_queries(query_plan, queries)}
            if minimums:options['search_minimums']=minimums
            if query_plan.get('search_identity') is not None:options['search_identity']=query_plan['search_identity']
            if search_only:options['search_only']=True
            from ..studio_pause import bind_progress
            browser_result = browser_search(settings, frames, queries, settings.source_max_candidates, root / "browser_debug",
                                            previous_searches=[*(previous_searches or []), *search_audit],
                                            progress=bind_progress(lambda msg: progress(msg, 32), progress), **options)
            search_audit.extend(browser_result.get('searches', []))
            if any(r.get('status')=='browser_busy' for r in browser_result.get('searches',[])):
                from ..source_browser_runtime import BrowserBusy
                raise BrowserBusy('수집용 브라우저 사용 종료 대기')
    if strategy:
        search_audit.extend({'provider':provider,'query':'','status':'strategy_skipped','candidates':0,'reason':reason}
                            for provider, reason in strategy['skipped_routes'].items())
    if settings.source_browser_search:
        # Browser mode means the operator's existing session, including a
        # YouTube-first strategy. An empty/blocked browser result must not
        # silently invoke yt-dlp search or a separate indexed HTTP search.
        run_browser()
        queries = list(dict.fromkeys(q for q in queries if q.strip()))
        candidates = [*shortlist,*vision_candidates,
                      *(services.Candidate(**item) for item in browser_result['candidates'])]
        candidates = [c for c in candidates if c.platform not in disabled]
        return candidates, queries, browser_result, search_audit, tiktok_preference
    defer_browser = bool(allowed and allowed[0] in {'youtube','bing','duckduckgo'})
    if not defer_browser:
        run_browser()
    # Keep the grounded pool even after all routes exhaust it. Image labels
    # must not silently replace the actual subject with background objects.
    queries = list(dict.fromkeys(q for q in queries if q.strip()))
    candidates = [*shortlist,*vision_candidates]
    if not defer_browser:
        candidates += [services.Candidate(**item) for item in browser_result["candidates"]]
    def available(pool, provider, maximum, language_provider=None):
        selected = fresh_queries(pool, provider, [*(previous_searches or []), *search_audit])
        if not selected:
            search_audit.append({'provider':provider, 'query':'', 'status':'query_exhausted' if pool else 'no_supported_queries', 'candidates':0})
        return platform_queries(selected, language_provider or provider, maximum,search_minimums=minimums)
    progress("공개 웹 검색 결과를 합치는 중", 42)
    per_platform = max(4, settings.source_max_candidates // 5)
    # Ordinary indexed public TikTok links supplement low-yield in-site search.
    tiktok_pool = tiktok_product_queries(query_plan, queries)
    tiktok_queries = platform_queries(tiktok_pool, 'tiktok', len(tiktok_pool))
    indexed_tiktok_queries = [q + ' site:tiktok.com/@ inurl:video' for q in tiktok_queries]
    tiktok_preference = max(0, settings.source_tiktok_min_usable)
    tiktok_candidates = []
    if enabled('youtube') and defer_browser:
        candidates += services.search_youtube(available(queries, 'youtube', settings.source_queries_per_platform), per_platform,
                                      settings.source_browser_cookie_file, search_audit, settings.source_ytdlp_js_runtime)
    if enabled('duckduckgo') and enabled('tiktok'):
        # The noun boundary runs before external index operators are attached.
        # These operators go to DDG/Bing, never to TikTok's search input.
        tiktok_candidates = services.search_web(available(indexed_tiktok_queries, 'duckduckgo', 3, 'youtube'), min(settings.source_max_candidates, tiktok_preference * 3), search_audit)
    if enabled('bing') and enabled('tiktok') and not any(c.platform == 'tiktok' for c in tiktok_candidates):
        tiktok_candidates += services.search_bing(available(indexed_tiktok_queries, 'bing', 3, 'youtube'), min(settings.source_max_candidates, tiktok_preference * 3), search_audit)
    candidates += [c for c in tiktok_candidates if c.platform == 'tiktok']
    web_queries = queries
    candidates += services.search_local_cache(settings, shortcode, per_platform)
    candidates += services.search_local_hints(settings, shortcode)
    if enabled('duckduckgo'):
        candidates += services.search_web(available(web_queries, 'duckduckgo', settings.source_queries_per_platform, 'youtube'), per_platform, search_audit)
    if enabled('bing'):
        candidates += services.search_bing(available(web_queries, 'bing', settings.source_queries_per_platform, 'youtube'), per_platform, search_audit)
    # Public product clips often retain the exact object when broad social
    # queries return unrelated storage products. The same CLIP/OCR gates apply.
    vendor_queries = [q + ' site:lazada.com.ph/videodetail/' for q in queries if language(q) == 'en']
    if enabled('bing') and (not strategy or strategy['vendor_search']):
        candidates += services.search_bing(available(vendor_queries, 'bing', 2), min(4, per_platform), search_audit)
    if enabled('youtube') and not defer_browser:
        candidates += services.search_youtube(available(web_queries, 'youtube', settings.source_queries_per_platform), per_platform,
                                 settings.source_browser_cookie_file, search_audit, settings.source_ytdlp_js_runtime)
    if defer_browser:
        run_browser()
        candidates += [services.Candidate(**item) for item in browser_result['candidates']]
    candidates += services.search_pexels(settings, available(queries, 'pexels', 1, 'youtube'), per_platform, search_audit)
    candidates = [c for c in candidates if c.platform not in disabled]
    return candidates, queries, browser_result, search_audit, tiktok_preference
