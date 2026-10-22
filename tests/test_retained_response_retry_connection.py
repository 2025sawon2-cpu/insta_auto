"""Preserved paused incident through real retry, claim and source gate.
The unchanged helper deep-copies HOTPOST_REPAIR_INCIDENT, preserves task/job/run,
pending submission and readiness, and rebinds preparation media in isolation.
Only browser/service I/O is doubled; internal validators remain real.
No test proof or response is installed as production authorization.
"""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
import pytest
from hotpost.source_access_preflight import SourceAccessWaiting
from hotpost.source_search.readiness import readiness_record


def helpers():
    path=Path(__file__).with_name('test_submitted_search_scroll_incident.py')
    spec=importlib.util.spec_from_file_location('retained_retry_helpers',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def retained(query,status=200):
    url='https://www.tiktok.com/api/search/item/full/?keyword='+quote(query)
    body={'status_code':0,'item_list':[{'id':'1234567890123456789',
        'author':{'uniqueId':'isolated_fixture'},'desc':'silicone pot lid',
        'video':{'width':1080,'height':1920,'duration':12}}]}
    response=SimpleNamespace(url=url,status=status,headers={},json=lambda:copy.deepcopy(body))
    return SimpleNamespace(url=url,response=lambda:response)


def test_explicit_retry_claim_retained_response_connection(tmp_path,monkeypatch):
    from hotpost.video_agent_actions import execute
    h=helpers()
    fixture,state,job,failed,settings,page,store,owner,bundle=h.setup_incident(tmp_path,monkeypatch)
    assert job['status']=='paused' and not job['checkpoint'].get('video_agent_park_receipt')
    history=copy.deepcopy(state['source_acquisition']['queries'])
    studio,action,fingerprint,hold=h.isolated_retry_contract(tmp_path,state,job,store)
    # Preserve the current incident's host-attested hold identity in the copy.
    hold['diagnosis_id']='codex1439bfccb8e3758327c33d8d3dc7af44'
    with store.transaction() as db:
        db.execute('UPDATE supervision_jobs SET record=? WHERE job_id=?',(json.dumps(hold),job['id']))
    assert store.claim('sources',task_id=state['id'],job_id=job['id']) is None
    result=execute(studio,state['id'],action,'isolated-retained-retry',fingerprint)
    assert result['status']=='queued' and result['job_ids']==[fixture['job']['id']]
    claimed=store.claim('sources',task_id=state['id'],job_id=job['id'])
    assert claimed and claimed['id']==fixture['job']['id']
    assert claimed['task_id']==state['id'] and claimed['payload']['run_id']==state['run_id']
    import inspect
    import textwrap
    import hotpost.source_parser_recovery as production
    repaired=production.read_response
    source=textwrap.dedent(inspect.getsource(repaired))
    start=source.index("        retained=getattr(page,'requests',None)\n")
    end=source.index('        for attempt in range(20):',start)
    # Reconstruct the exact pre-patch production function by removing only
    # this repair's insertion; all internal validators and refresh stay real.
    original_source=source[:start]+source[end:]
    assert original_source!=source and 'retained=getattr' not in original_source
    namespace=dict(vars(production))
    exec(compile(original_source,'<isolated-original-read_response>','exec'),namespace)
    import time
    clock=[time.time()]
    def advancing_time():
        clock[0]+=.01
        return clock[0]
    monkeypatch.setattr(production.time,'time',advancing_time)
    page.main_frame=object()
    response=retained(failed['query'])
    response.frame=page.main_frame
    page.requests=lambda:[response]
    original_on=page.on
    registrations=[]
    def register(event,callback):
        # External browser fixture: a response completes during attachment/
        # page checks, before the observer is registered. Each invocation gets
        # fresh browser evidence with the same query, body and causal ordering.
        registered=advancing_time()
        response.timing={'startTime':(registered-.005)*1000,'responseEnd':1}
        registrations.append((registered,copy.deepcopy(response.timing)))
        return original_on(event,callback)
    page.on=register
    # Both versions receive the same external response content and ordering;
    # neither gets an event after registration. The clock advances normally.
    with monkeypatch.context() as baseline:
        baseline.setattr(production,'read_response',namespace['read_response'])
        with pytest.raises(SourceAccessWaiting):
            owner._source_access_gate(store.get(state['id']),claimed)
    assert production.read_response is repaired
    assert store.reload(claimed)['parser_response_recovery']['status']=='unavailable'
    assert readiness_record(tmp_path,'tiktok')==failed
    assert page.requests()[0] is response
    assert store.get(state['id'])['source_acquisition']['queries']==history
    page.scrolls.clear()
    ready=owner._source_access_gate(store.get(state['id']),claimed)
    receipt=store.reload(claimed)['parser_response_recovery']
    assert 'tiktok' in ready and receipt['status']=='response_validated'
    assert receipt['task_id']==fixture['task']['id'] and receipt['job_id']==fixture['job']['id']
    assert receipt['run_id']==state['run_id']
    assert receipt['response']['observation_method']=='retained_page_response'
    registered,timing=registrations[-1]
    request_started=timing['startTime']/1000
    completed=(timing['startTime']+timing['responseEnd'])/1000
    assert receipt['response']['observation_started_at']<request_started<completed<registered
    assert receipt['response']['received_at']==completed
    assert receipt['response']['request_started_at']==request_started
    assert clock[0]>registered
    assert len(registrations)>=2
    assert receipt['response']['request_frame']=='owned_main_frame'
    assert receipt['query_submitted'] is False and receipt['grants_media_approval'] is False
    assert page.scrolls==[] and page.emitted==0 and page.listeners==[]
    current=store.get(state['id'])
    assert current['source_acquisition']['queries']==history
    assert not current['sources'] and not current['edits']
    assert readiness_record(tmp_path,'tiktok')['previous_failure']==failed
    with store.connect() as db:
        saved=json.loads(db.execute('SELECT record FROM supervision_jobs WHERE job_id=?',(job['id'],)).fetchone()[0])
    assert saved['phase']=='method_changed' and saved['diagnosis_id']==hold['diagnosis_id']
    assert 'released_at' not in saved


@pytest.mark.parametrize('damage',['wrong_query','login','http_error'])
def test_retained_response_rejects_invalid_external_evidence(tmp_path,monkeypatch,damage):
    _,state,job,failed,settings,page,store,owner,bundle=helpers().setup_incident(tmp_path,monkeypatch)
    import time
    import hotpost.source_parser_recovery as production
    observed=time.time()
    monkeypatch.setattr(production.time,'time',lambda:observed)
    page.main_frame=object()
    query='unrelated' if damage=='wrong_query' else failed['query']
    request=retained(query,500 if damage=='http_error' else 200)
    request.frame=page.main_frame
    request.timing={'startTime':observed*1000,'responseEnd':0}
    accessed=[]
    external_response=request.response
    def response():
        accessed.append(True)
        return external_response()
    request.response=response
    page.requests=lambda:[request]
    assert request.frame is page.main_frame
    assert request.timing=={'startTime':observed*1000,'responseEnd':0}
    if damage=='login':page.body='Log in to search'
    with pytest.raises(SourceAccessWaiting):owner._source_access_gate(state,job)
    assert readiness_record(tmp_path,'tiktok')==failed
    assert store.reload(job)['parser_response_recovery']['status']=='unavailable'
    assert not store.get(state['id'])['sources']
    if damage=='http_error':
        assert accessed==[True]
        assert external_response().status==500
    elif damage=='wrong_query':
        assert accessed==[]
        assert query!=failed['query']


@pytest.mark.parametrize('damage',['old_same_query','missing_timing','other_frame','unfinished'])
def test_retained_provenance_cannot_release_preserved_gate(tmp_path,monkeypatch,damage):
    import time
    _,state,job,failed,settings,page,store,owner,bundle=helpers().setup_incident(tmp_path,monkeypatch)
    observed=time.time()
    import hotpost.source_parser_recovery as production
    monkeypatch.setattr(production.time,'time',lambda:observed)
    page.main_frame=object()
    request=retained(failed['query'])
    request.frame=page.main_frame
    request.timing={'startTime':observed*1000,'responseEnd':0}
    if damage=='old_same_query':request.timing['startTime']=(failed['at']-60)*1000
    if damage=='missing_timing':del request.timing
    if damage=='other_frame':request.frame=object()
    if damage=='unfinished':request.timing['responseEnd']=-1
    page.requests=lambda:[request]
    history=copy.deepcopy(state['source_acquisition']['queries'])
    with pytest.raises(SourceAccessWaiting):owner._source_access_gate(state,job)
    assert readiness_record(tmp_path,'tiktok')==failed
    assert store.reload(job)['parser_response_recovery']['status']=='unavailable'
    assert store.get(state['id'])['source_acquisition']['queries']==history
    assert not store.get(state['id'])['sources']


# Collect unchanged ownership/access regressions, rather than merely attaching text.
_prior=helpers()
test_current_retry_admission_rejects_invalid_proof=_prior.test_current_retry_admission_rejects_invalid_proof
test_scroll_never_bypasses_failed_prerequisite=_prior.test_scroll_never_bypasses_failed_prerequisite
