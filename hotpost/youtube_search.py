"""Search the existing YouTube tab; bind visible cards to its new response."""
from __future__ import annotations

import hashlib
import base64
import re
import time
from urllib.parse import parse_qs, urlparse

from .source_queries import language, platform_queries
from .source_search.strategy import fresh_queries
from .youtube_download import video_id


def response_video_ids(payload):
    """Only the new search contents are evidence, never page recommendations."""
    ids = set()
    stack = [payload.get('contents', {})] if isinstance(payload, dict) else []
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            identity = node.get('videoId')
            if isinstance(identity, str) and re.fullmatch(r'[A-Za-z0-9_-]{11}', identity):
                ids.add(identity)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return ids


def _visible_cards(page, ids, query):
    rows = page.locator('ytd-video-renderer,ytm-shorts-lockup-view-model').evaluate_all('''els=>els.filter(e=>{
        const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&r.top<innerHeight&&r.bottom>0&&r.left<innerWidth&&r.right>0&&getComputedStyle(e).visibility!=="hidden";
    }).map(e=>{const a=[...e.querySelectorAll('a[href]')].find(a=>a.href.includes('/watch?')||a.href.includes('/shorts/'));
        return a?{url:a.href,text:e.innerText,title:a.getAttribute('title')}:null;}).filter(Boolean)''')
    cards = [{'url':row['url'], 'title':re.sub(r'\s+', ' ', row.get('title') or row.get('text') or '')[:240],
             'provider':'playwright-youtube', 'query':query, 'match_kind':'platform-search',
             'discovery_meta':{'result_method':'visible_card_bound_to_search_response'}}
            for row in rows if video_id(row.get('url', '')) in ids]
    cards.sort(key=lambda c: 0 if '/shorts/' in c.get('url', '') else 1)
    return cards


def search_existing_youtube(searcher, context, queries, limit):
    from .browser_search import SearchBudgetReached
    if limit <= 0 or searcher._cooling_down('youtube',context=context):
        return
    from .source_search.strategy import minimum_search_queries
    minimums=getattr(searcher,'search_minimums',{}) or {}
    available = platform_queries(queries, 'youtube', len(queries),search_minimums=minimums)
    query_limit=max(searcher.settings.source_queries_per_platform,sum(minimums.values()))
    search_only=getattr(searcher,'search_only',False)
    selected = minimum_search_queries(available,'youtube',[*searcher.previous_searches,*searcher.searches],minimums,query_limit,search_only=search_only,search_identity=getattr(searcher,'search_identity',None))
    if not selected:
        searcher.searches.append({'provider':'youtube', 'query':'', 'candidates':0,
            'status':'query_exhausted' if available else 'no_supported_queries'})
        return
    pages = [p for p in context.pages if not p.is_closed() and
             urlparse(p.url).hostname in {'www.youtube.com', 'youtube.com', 'm.youtube.com'}]
    if len(pages) != 1:
        searcher.searches.append({'provider':'youtube', 'query':'', 'candidates':0,
            'status':'not_attempted', 'reason':'existing_youtube_tab_missing' if not pages else 'existing_youtube_tab_ambiguous'})
        searcher.notes.append('YouTube · 기존 탭을 하나로 특정할 수 없어 검색 중지 · 새 탭을 만들지 않음')
        return
    page = pages[0]
    maximum = min(limit, max(1, searcher.settings.source_candidates_per_platform))
    per_query = max(1, (maximum + len(selected) - 1) // len(selected))
    seen = set()
    for query in selected:
        if search_only:
            from .source_search.strategy import search_quota_needed
            if not search_quota_needed([*searcher.previous_searches,*searcher.searches],minimums,query,search_identity=getattr(searcher,'search_identity',None)):continue
        audit = {'provider':'youtube', 'query':query, 'language':language(query),
                 'status':'started', 'candidates':0, 'requests':[],
                 'execution':{'query_submitted':False,'query_url_matched':False}}
        if getattr(searcher,'search_identity',None) is not None:audit['search_identity']=searcher.search_identity
        searcher.searches.append(audit)
        if searcher._check_block(page, 'youtube', audit):
            break
        try:
            searcher._pace('youtube', reserve=searcher.settings.source_browser_navigation_timeout + 2)
            timeout = max(1000, searcher.settings.source_browser_navigation_timeout * 1000)
            control = page.locator('input[name="search_query"]:visible')
            control.wait_for(state='visible', timeout=timeout)
            control.fill(query)
            searcher._audit_request(audit, 'visible_search_input_enter')

            def matching_response(response):
                parsed = urlparse(response.url)
                if parsed.hostname not in {'www.youtube.com', 'youtube.com', 'm.youtube.com'} or parsed.path != '/youtubei/v1/search':
                    return False
                observation = {'status':response.status}
                try:
                    payload = response.request.post_data_json
                    observation.update(request_body_keys=sorted(payload) if isinstance(payload, dict) else [],
                        body_query=str(payload.get('query', ''))[:240] if isinstance(payload, dict) else '')
                except Exception as exc:
                    # Attached CDP can omit request bodies. Never log a parser
                    # exception's text: it can contain the full POST body.
                    observation.update(request_body_unavailable=True, request_body_error=type(exc).__name__)
                    payload = None
                audit.setdefault('search_response_observations', []).append(observation)
                if isinstance(payload, dict) and 'query' in payload:
                    observation['binding'] = 'request_query'
                    return payload['query'] == query
                try:
                    started_at = response.request.timing['startTime'] / 1000
                except (AttributeError, TypeError, KeyError):
                    return False
                observation.update(binding='request_started_after_enter', request_started_at=started_at)
                return started_at >= audit['requests'][-1]['at']

            with page.expect_response(matching_response, timeout=timeout) as pending:
                control.press('Enter', timeout=timeout)
                audit['execution'].update(query_submitted=True,input_value=query,submitted_at=time.time())
            response = pending.value
            audit['http_status'] = response.status
            if searcher._check_block(page, 'youtube', audit, response):
                break
            if response.status >= 400:
                audit['status'] = 'http_error'
                break
            response.finished()
            ids = response_video_ids(response.json())
            page.wait_for_url(lambda url: urlparse(str(url)).path == '/results' and
                parse_qs(urlparse(str(url)).query).get('search_query', [''])[0] == query, timeout=timeout)
            if control.input_value() != query:
                raise RuntimeError('YouTube visible query changed during search')
            audit['execution']['query_url_matched']=True
            audit['result_method'] = 'visible_card_bound_to_search_response'
            started = time.monotonic()
            found = []
            empty_visible = False
            for _ in range(max(1, searcher.settings.source_browser_result_timeout) + 1):
                if searcher._check_block(page, 'youtube', audit):
                    break
                found = _visible_cards(page, ids, query)
                empty_visible = not ids and page.locator('ytd-background-promo-renderer').is_visible()
                if found or empty_visible:
                    break
                if time.monotonic() - started >= searcher.settings.source_browser_result_timeout:
                    break
                page.wait_for_timeout(1000)
            if audit['status'] in {'captcha', 'login_required', 'rate_limited'}:
                break
            added = 0
            for item in found:
                identity = video_id(item['url'])
                if identity not in seen and len(seen) < maximum and added < per_query:
                    searcher.candidates.append(item)
                    seen.add(identity)
                    added += 1
            audit.update(status='results' if found else ('no_results' if empty_visible else 'page_unresolved'),
                         candidates=added, response_video_count=len(ids), visible_video_count=len(found),
                         result_wait_seconds=round(time.monotonic() - started, 2))
            try:
                page.screenshot(path=str(searcher.debug_dir / ('youtube-' + hashlib.sha256(query.encode()).hexdigest()[:12] + '.png')),
                                full_page=False, timeout=5000)
            except Exception as exc:
                audit['screenshot_error'] = type(exc).__name__
                session = context.new_cdp_session(page)
                try:
                    pixels = session.send('Page.captureScreenshot', {'format':'png', 'captureBeyondViewport':False})['data']
                    (searcher.debug_dir / ('youtube-' + hashlib.sha256(query.encode()).hexdigest()[:12] + '.png')).write_bytes(base64.b64decode(pixels))
                    audit['screenshot_method'] = 'existing_page_cdp_capture'
                except Exception as capture_error:
                    audit['screenshot_fallback_error'] = type(capture_error).__name__
                finally:
                    session.detach()
            searcher.progress(f'YouTube · {query} → 표시된 후보 {added}개')
            from .source_coverage import actual_search_coverage
            quota=actual_search_coverage([*searcher.previous_searches,*searcher.searches],minimums)
            minima_met=all(row['ready'] for row in quota.values())
            if (search_only and minima_met or len(seen) >= maximum and minima_met
                    or audit['status'] == 'page_unresolved'):
                break
        except SearchBudgetReached:
            audit.update(status='budget_exhausted')
            raise
        except Exception as exc:
            # A failed navigation is not permission to read old result cards,
            # restart Chrome, or invoke a cookie-file/extractor search.
            if not searcher._check_block(page, 'youtube', audit):
                audit.update(status='error', error=type(exc).__name__)
            searcher.notes.append(f'YouTube · 검색 실패: {type(exc).__name__} · 이전 결과를 채택하지 않음')
            break
