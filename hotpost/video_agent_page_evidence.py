"""Read-only existing search-page facts for a bound parser incident.

No navigation, refresh, scroll, cookie migration, access verdict or retry grant.
"""
import copy
import hashlib
import json
import math
from urllib.parse import parse_qs,urlparse

BODY_LIMIT=8000
LINK_LIMIT=24
ANCESTOR_LIMIT=7
DOM_SCOPE='Unclassified visible link ancestry only; not search hits or an access verdict'


class _ReadinessChanged(ValueError):
    def __init__(self,current,expected):
        super().__init__('readiness_changed')
        def strings(record,keys):
            return {key:record[key][:200] for key in keys if isinstance(record.get(key),str)
                    and not any(0xD800<=ord(ch)<=0xDFFF for ch in record[key])}
        record=current if isinstance(current,dict) else {}
        self.summary=strings(record,('reason','parser_revision'))
        at=record.get('at')
        if type(at) in (int,float) and math.isfinite(at):self.summary['at']=at
        recovery=record.get('recovery')
        if isinstance(recovery,dict):
            self.summary['recovery']=strings(recovery,('task_id','job_id','run_id','status','error_type'))
        self.summary.update(previous_failure_matches_incident=record.get('previous_failure')==expected,
            scope='Saved readiness metadata only; current normal access preflight still required',
            query_submitted=False,grants_retry=False)

_PAGE_FACTS_JS='''(el,limit)=>{
    const clip=(value,limit)=>Array.from(value||'').slice(0,limit).join('');
    let text="",characters=0;
    for(const ch of (el.innerText||"")){if(characters<limit)text+=ch;characters++}
    const structure=[];
    for(const a of Array.from(el.querySelectorAll('a[href]')).slice(0,1000)){
        const rect=a.getBoundingClientRect();
        if(!a.getAttribute('href').includes('/video/')||rect.width<=0||rect.height<=0)continue;
        const ancestors=[];
        for(let node=a;node&&ancestors.length<7;node=node.parentElement){
            ancestors.push({tag:clip(node.tagName,32),
                role:clip(node.getAttribute('role'),80),
                data_e2e:clip(node.getAttribute('data-e2e'),120)});
            if(node===el)break;
        }
        structure.push({ancestors});if(structure.length>=24)break;
    }
    return {text,characters,structure};
}'''


def _validated_structure(value):
    if not isinstance(value,list) or len(value)>LINK_LIMIT:raise ValueError('invalid_link_structure')
    for link in value:
        if not isinstance(link,dict) or set(link)!={'ancestors'}:raise ValueError('invalid_link_structure')
        ancestors=link['ancestors']
        if not isinstance(ancestors,list) or not 1<=len(ancestors)<=ANCESTOR_LIMIT:raise ValueError('invalid_link_structure')
        for node in ancestors:
            if not isinstance(node,dict) or set(node)!={'tag','role','data_e2e'}:raise ValueError('invalid_link_structure')
            if any(not isinstance(node[key],str) or len(node[key])>limit
                   for key,limit in [('tag',32),('role',80),('data_e2e',120)]):raise ValueError('invalid_link_structure')
            if any(0xD800<=ord(ch)<=0xDFFF for value in node.values() for ch in value):
                raise ValueError('invalid_link_structure')
    return value


def _read(settings,expected):
    from .source_browser_runtime import browser_lease,endpoint,existing_page
    from .source_search.readiness import readiness_record
    from playwright.sync_api import sync_playwright
    current=readiness_record(settings.data_dir,'tiktok')
    if current!=expected:raise _ReadinessChanged(current,expected)
    address=endpoint(settings)
    if not address:raise ValueError('existing_session_unavailable')
    with browser_lease(settings),sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp(address,timeout=5000)
        if not browser.contexts:raise ValueError('existing_context_unavailable')
        page=existing_page(browser.contexts[0],settings,'tiktok')
        url=page.url;parsed=urlparse(url)
        if (parsed.scheme!='https' or parsed.hostname not in {'www.tiktok.com','tiktok.com'}
                or parsed.path.rstrip('/') not in {'/search','/search/video'}
                or parse_qs(parsed.query,keep_blank_values=True).get('q')!=[expected['query']]):
            raise ValueError('existing_page_query_differs')
        body=page.locator('body').evaluate(
            _PAGE_FACTS_JS,
            BODY_LIMIT,timeout=5000)
        if page.url!=url:raise ValueError('existing_page_changed')
    current=readiness_record(settings.data_dir,'tiktok')
    if current!=expected:raise _ReadinessChanged(current,expected)
    if (not isinstance(body,dict) or not isinstance(body.get('text'),str)
            or type(body.get('characters')) is not int or body['characters']<len(body['text'])
            or len(body['text'])>BODY_LIMIT):raise ValueError('invalid_page_observation')
    return {'page_url':url,'body_text':body['text'],'body_characters':body['characters'],
        'body_truncated':body['characters']>len(body['text']),
        'visible_video_link_structure':_validated_structure(body.get('structure')),'dom_scope':DOM_SCOPE,
        'captured_text_sha256':hashlib.sha256(body['text'].encode()).hexdigest()}


def current_parser_page(studio,state,jobs):
    """Observe only the current host-bound incident, never self-declared URLs."""
    import time
    from .video_agent_context import semantic_fingerprint
    settings=getattr(studio,'settings',None)
    if (not getattr(settings,'source_browser_search',False)
            or not getattr(settings,'source_browser_existing_window_only',False)):
        return []
    job=None
    for candidate in jobs:
        cp=candidate.get('checkpoint') or {};parser=cp.get('parser_repair_context') if isinstance(cp,dict) else None
        if (candidate.get('task_id')==state.get('id') and candidate.get('kind')=='collect_sources'
                and candidate.get('status') in {'queued','paused','failed'}
                and isinstance(candidate.get('payload'),dict)
                and candidate['payload'].get('run_id')==state.get('run_id')
                and isinstance(parser,dict) and parser.get('task_id')==state.get('id')
                and parser.get('run_id')==state.get('run_id')):
            job=candidate;break
    if not job:return []
    parser=job['checkpoint']['parser_repair_context'];rows=parser.get('observations') or []
    if (not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict) or rows[0].get('provider')!='tiktok'
            or rows[0].get('status')!='readiness_blocked' or rows[0].get('manual_gate_active') is not False):return []
    expected=copy.deepcopy(rows[0].get('readiness'))
    if (not isinstance(expected,dict) or expected.get('reason')!='page_unresolved'
            or not isinstance(expected.get('query'),str) or not 1<=len(expected['query'])<=200):return []
    result={'status':'unavailable','task_id':state['id'],'job_id':job['id'],'run_id':state['run_id'],
        'readiness':expected,'observed_at':time.time(),'query_submitted':False,'grants_retry':False,
        'scope':'Current page of the stored readiness query only; not this video\'s search, source, access verdict or parser repair.'}
    try:
        with studio.store.connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='video_agents'").fetchone():return []
            owner=db.execute('SELECT epoch FROM video_agents WHERE task_id=?',(state['id'],)).fetchone()
        if not owner:return []
        epoch=owner['epoch'];result['agent_epoch']=epoch
        changed=None
        try:observed=_read(settings,expected)
        except _ReadinessChanged as exc:changed=exc
        current=studio.store.get(state['id'])
        with studio.store.connect() as db:
            saved=db.execute('SELECT task_id,status,payload,checkpoint FROM jobs WHERE id=?',(job['id'],)).fetchone()
            owner=db.execute('SELECT epoch FROM video_agents WHERE task_id=?',(state['id'],)).fetchone()
        if (semantic_fingerprint(current)!=semantic_fingerprint(state) or not saved
                or not owner or owner['epoch']!=epoch
                or saved['task_id']!=state['id'] or saved['status']!=job['status']
                or json.loads(saved['payload']).get('run_id')!=state['run_id']
                or json.loads(saved['checkpoint']).get('parser_repair_context')!=parser):
            raise ValueError('incident_changed_during_observation')
        if changed:raise changed
        result.update(observed,status='observed')
    except Exception as exc:
        # Browser contention or observation failure is neither content failure
        # nor evidence that the page is clear, empty, logged out or blocked.
        result['reason']=str(exc)[:200] if isinstance(exc,ValueError) else type(exc).__name__
        if isinstance(exc,_ReadinessChanged):result['current_saved_readiness']=exc.summary
    return [result]
