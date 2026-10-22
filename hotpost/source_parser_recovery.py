"""Passive native-response recovery; never a source or media approval."""
import copy
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class ResponseObservationUnavailable(RuntimeError):
    def __init__(self, reason):
        self.reason=reason
        super().__init__(reason)


def read_response(settings, query, before_refresh=None):
    # Include responses completed while attaching and checking the owned page.
    # Evidence predating this invocation still cannot establish fresh access.
    started=time.time()
    from .source_browser_runtime import browser_lease, attach_browser, existing_page, pace
    from .source_collection_access import disabled_platforms
    from .search_access import access_record, manual_required
    from .source_search.tiktok_results import search_response_candidates
    from .browser_search import BrowserSearcher, BROWSER_COOLDOWNS
    if not getattr(settings, 'source_browser_existing_window_only', False):return None
    record=access_record(settings.data_dir,'tiktok')
    if ('tiktok' in disabled_platforms(settings) or manual_required(record)
            or record.get('until',0)>time.time()
            or BROWSER_COOLDOWNS.get('tiktok',0)>time.time()):return None
    from playwright.sync_api import sync_playwright
    with browser_lease(settings), sync_playwright() as pw:
        context=attach_browser(pw,settings)
        page=existing_page(context,settings,'tiktok')
        parsed=urlparse(page.url)
        if (parsed.hostname not in ('www.tiktok.com','tiktok.com')
                or parsed.path.rstrip('/') not in ('/search','/search/video')
                or parse_qs(parsed.query).get('q',[''])[0]!=query):
            raise ResponseObservationUnavailable('owned_page_query_mismatch')
        if not page.locator('body').inner_text(timeout=5000).strip():
            raise ResponseObservationUnavailable('owned_page_body_empty')
        guard=BrowserSearcher(settings,Path(settings.data_dir)/'parser-response-observation')
        audit={'provider':'tiktok','query':query}
        if guard._check_block(page,'tiktok',audit):return None
        found=[];limited=[]
        def receive(response):
            host=urlparse(response.url).hostname or ''
            if response.status==429 and (host=='tiktok.com' or host.endswith('.tiktok.com')):
                limited.append(response);return
            if response.status!=200:return
            try:
                body=response.json()
                if search_response_candidates(response.url,body,query):
                    found.append({'response_url':response.url,'body':body,'page_url':page.url,
                        'http_status':200,'received_at':time.time(),'observation_started_at':started})
            except Exception:return
        page.on('response',receive)
        try:
            retained=getattr(page,'requests',None)
            if callable(retained):
                for request in list(retained())[-100:]:
                    parsed_request=urlparse(request.url)
                    if (parsed_request.scheme!='https'
                            or parsed_request.hostname not in ('www.tiktok.com','tiktok.com')
                            or parsed_request.path not in ('/api/search/item/full/','/api/search/general/full/')
                            or parse_qs(parsed_request.query).get('keyword',[''])[0]!=query):
                        continue
                    # Missing provenance cannot turn an old same-query response
                    # into current access evidence. Playwright timing is in ms.
                    import math
                    timing=getattr(request,'timing',None)
                    if not isinstance(timing,dict):continue
                    origin=timing.get('startTime');end=timing.get('responseEnd')
                    if (type(origin) not in (int,float) or type(end) not in (int,float)
                            or not math.isfinite(origin) or not math.isfinite(end)
                            or end<0 or origin/1000<started
                            or (origin+end)/1000>time.time()):continue
                    main=getattr(page,'main_frame',None)
                    if main is None or getattr(request,'frame',None) is not main:continue
                    response=request.response()
                    if response is not None and page.url==str(parsed.geturl()):
                        count=len(found)
                        receive(response)
                        if len(found)>count:
                            found[-1].update(observation_method='retained_page_response',
                                received_at=(origin+end)/1000,
                                request_started_at=origin/1000,
                                request_frame='owned_main_frame')
            for attempt in range(20):
                page.wait_for_timeout(250)
                if limited:
                    guard._block('tiktok',audit,'rate_limited',limited[0]);return None
                if guard._check_block(page,'tiktok',audit):return None
                record=access_record(settings.data_dir,'tiktok')
                if manual_required(record) or record.get('until',0)>time.time():return None
                if found:return found[-1]
                if attempt == 9:
                    # Continue observing the submitted page through the normal
                    # collector's single scroll; never resubmit or scrape links.
                    current=urlparse(page.url)
                    if (current.hostname not in ('www.tiktok.com','tiktok.com')
                            or current.path.rstrip('/') not in ('/search','/search/video')
                            or parse_qs(current.query).get('q',[''])[0]!=query):return None
                    mouse=getattr(page,'mouse',None)
                    if mouse is not None:mouse.wheel(0,900)
            if before_refresh is None:
                raise ResponseObservationUnavailable('matching_native_response_not_observed')
            pace(settings,'tiktok')
            before_refresh()
            if existing_page(context,settings,'tiktok') is not page:return None
            current=urlparse(page.url)
            if (current.hostname not in ('www.tiktok.com','tiktok.com')
                    or current.path.rstrip('/') not in ('/search','/search/video')
                    or parse_qs(current.query).get('q',[''])[0]!=query):return None
            record=access_record(settings.data_dir,'tiktok')
            if ('tiktok' in disabled_platforms(settings) or manual_required(record)
                    or record.get('until',0)>time.time()
                    or BROWSER_COOLDOWNS.get('tiktok',0)>time.time()
                    or guard._check_block(page,'tiktok',audit)):return None
            if limited:
                guard._block('tiktok',audit,'rate_limited',limited[0]);return None
            if found:return found[-1]
            guard._audit_request(audit,'parser_response_refresh')
            page.reload(wait_until='domcontentloaded',timeout=10000)
            for _ in range(20):
                page.wait_for_timeout(250)
                if limited:
                    guard._block('tiktok',audit,'rate_limited',limited[0]);return None
                if guard._check_block(page,'tiktok',audit):return None
                record=access_record(settings.data_dir,'tiktok')
                if manual_required(record) or record.get('until',0)>time.time():return None
                if found:
                    found[-1]['requests']=copy.deepcopy(audit.get('requests',[]))
                    return found[-1]
        finally:page.remove_listener('response',receive)
    raise ResponseObservationUnavailable('matching_native_response_not_observed')


def recover_response(settings,store,state,job):
    from .studio_pause import check_paused
    from .video_agent_actions import parser_repair_context
    from .source_search.readiness import readiness_record
    from .source_search.tiktok_results import search_response_candidates
    from .editing_adapter import _atomic_json
    check_paused(store,job)
    current=store.get(job['task_id'])
    if (job.get('task_id')!=state.get('id') or current.get('id')!=state.get('id')
            or current.get('run_id')!=state.get('run_id')
            or not parser_repair_context(current,job)):return False
    rows=job['checkpoint']['parser_repair_context']['observations']
    if len(rows)!=1 or rows[0].get('provider')!='tiktok':return False
    previous=copy.deepcopy(rows[0]['readiness']);query=previous.get('query')
    if not query or readiness_record(settings.data_dir,'tiktok')!=previous:return False
    store.checkpoint(job,job['checkpoint'])
    started=time.time();error_type=None;observation_reason=None;error_frames=[]
    def before_refresh():
        check_paused(store,job)
        latest=store.get(job['task_id'])
        if (latest.get('id')!=state.get('id')
                or latest.get('run_id')!=state.get('run_id')
                or not parser_repair_context(latest,job)
                or readiness_record(settings.data_dir,'tiktok')!=previous):
            raise RuntimeError('parser_response_refresh_binding_changed')
        store.checkpoint(job,job['checkpoint'])
    try:response=read_response(settings,query,before_refresh)
    except ResponseObservationUnavailable as exc:
        response=None;error_type=type(exc).__name__;observation_reason=exc.reason
    except Exception as exc:
        response=None;error_type=type(exc).__name__
        # Structural diagnostics only: never persist exception text, locals,
        # browser URLs, cookies or service response bodies.
        trace=exc.__traceback__
        while trace is not None:
            error_frames.append({'module':str(trace.tb_frame.f_globals.get('__name__',''))[:120],
                'function':trace.tb_frame.f_code.co_name[:120],'line':trace.tb_lineno})
            error_frames=error_frames[-8:]
            trace=trace.tb_next
    check_paused(store,job)
    current=store.get(job['task_id'])
    if (current.get('run_id')!=state.get('run_id') or not parser_repair_context(current,job)
            or readiness_record(settings.data_dir,'tiktok')!=previous):return False
    valid=False
    try:
        if isinstance(response,dict):
            page=urlparse(response.get('page_url',''))
            observed=response.get('observation_started_at');received=response.get('received_at')
            valid=(response.get('http_status')==200
                and type(observed) in (int,float) and type(received) in (int,float)
                and started<=observed<=received<=time.time()
                and page.hostname in ('www.tiktok.com','tiktok.com')
                and page.path.rstrip('/') in ('/search','/search/video')
                and parse_qs(page.query).get('q',[''])[0]==query
                and bool(search_response_candidates(response.get('response_url',''),response.get('body'),query)))
    except (TypeError,ValueError,AttributeError):valid=False
    receipt={'task_id':state['id'],'job_id':job['id'],'run_id':state['run_id'],
        'previous_readiness':previous,'at':time.time(),
        'status':'response_validated' if valid else 'unavailable',
        'grants_media_approval':False,'query_submitted':False,'error_type':error_type}
    if observation_reason is not None:receipt['observation_reason']=observation_reason
    if error_frames:receipt['error_frames']=error_frames
    if valid:receipt['response']=response
    old=copy.deepcopy(job['checkpoint'])
    job['checkpoint']['parser_response_recovery']=receipt
    try:store.checkpoint(job,job['checkpoint'])
    except BaseException:
        job['checkpoint'].clear();job['checkpoint'].update(old);raise
    if not valid or readiness_record(settings.data_dir,'tiktok')!=previous:return False
    _atomic_json(Path(settings.data_dir)/'search_readiness'/'tiktok.json',
        {'reason':'search_response_observed','parser_revision':previous['parser_revision'],
         'at':time.time(),'previous_failure':previous,'recovery':receipt})
    return True
