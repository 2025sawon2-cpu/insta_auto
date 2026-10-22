"""Read-only physical observations cannot change readiness or repair authority."""
import copy
import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from test_video_agent_planning_claim import install
from hotpost import video_agent_page_evidence as evidence


def bound(tmp_path):
    store,state,parent,child=install(tmp_path)
    readiness={'reason':'page_unresolved','query':'previous product','parser_revision':'revision','at':1}
    parser={'task_id':state['id'],'run_id':state['run_id'],'observations':[
        {'provider':'tiktok','status':'readiness_blocked','manual_gate_active':False,'readiness':readiness}]}
    child.update(payload=json.loads(child['payload']),checkpoint={'parser_repair_context':parser})
    with store.transaction() as db:
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(child['checkpoint']),child['id']))
    studio=SimpleNamespace(store=store,settings=SimpleNamespace(data_dir=tmp_path,
        source_browser_search=True,source_browser_existing_window_only=True))
    return studio,state,child,readiness


def test_observation_is_bound_to_current_incident_and_never_mutates_production(tmp_path,monkeypatch):
    studio,state,job,readiness=bound(tmp_path)
    observed={'page_url':'https://www.tiktok.com/search?q=previous%20product','body_text':'Actual visible cards',
        'body_characters':20,'body_truncated':False,'captured_text_sha256':'body-sha'}
    monkeypatch.setattr(evidence,'_read',lambda settings,expected:copy.deepcopy(observed))
    with studio.store.connect() as db:
        before={table:[tuple(r) for r in db.execute('select * from '+table)] for table in ('tasks','jobs','events','video_agents','video_agent_action_receipts')}
    rows=evidence.current_parser_page(studio,state,[job]);assert len(rows)==1
    row=rows[0]
    assert row['status']=='observed' and row['body_text']==observed['body_text']
    assert row['job_id']==job['id'] and row['readiness']==readiness and row['agent_epoch']==1
    assert row['query_submitted'] is False and row['grants_retry'] is False
    with studio.store.connect() as db:
        assert {table:[tuple(r) for r in db.execute('select * from '+table)] for table in before}==before


@pytest.mark.parametrize('damage',['task','run','payload_run','running','manual','other_provider','missing_query',
    'parser_list','rows_dict','no_browser','allow_restart','no_owner'])
def test_foreign_or_ineligible_incident_does_not_touch_browser(tmp_path,monkeypatch,damage):
    studio,state,job,readiness=bound(tmp_path)
    parser=job['checkpoint']['parser_repair_context']
    if damage=='task':job['task_id']='foreign'
    if damage=='run':parser['run_id']='foreign'
    if damage=='payload_run':job['payload']['run_id']='foreign'
    if damage=='running':job['status']='running'
    if damage=='manual':parser['observations'][0]['manual_gate_active']=True
    if damage=='other_provider':parser['observations'][0]['provider']='youtube'
    if damage=='missing_query':readiness.pop('query')
    if damage=='parser_list':job['checkpoint']['parser_repair_context']=['malformed']
    if damage=='rows_dict':parser['observations']={'malformed':True}
    if damage=='no_browser':studio.settings.source_browser_search=False
    if damage=='allow_restart':studio.settings.source_browser_existing_window_only=False
    if damage=='no_owner':
        with studio.store.transaction() as db:db.execute('delete from video_agents')
    monkeypatch.setattr(evidence,'_read',lambda *a:pytest.fail('Ineligible browser attach'))
    assert evidence.current_parser_page(studio,state,[job])==[]


@pytest.mark.parametrize('mutation',['epoch','semantic','job_status','job_context','payload_run','missing_job'])
@pytest.mark.parametrize('changed_readiness',[False,True])
def test_changed_incident_during_observation_is_not_delivered_as_current(tmp_path,monkeypatch,mutation,changed_readiness):
    studio,state,job,readiness=bound(tmp_path)
    def read(*args):
        with studio.store.transaction() as db:
            if mutation=='epoch':db.execute('update video_agents set epoch=2')
            elif mutation=='semantic':
                changed=copy.deepcopy(state);changed['original_text']='changed'
                db.execute('update tasks set state=?',(json.dumps(changed),))
            elif mutation=='job_status':db.execute("update jobs set status='running' where id=?",(job['id'],))
            elif mutation=='job_context':db.execute("update jobs set checkpoint='{}' where id=?",(job['id'],))
            elif mutation=='payload_run':db.execute("update jobs set payload=? where id=?",(json.dumps({'run_id':'foreign'}),job['id']))
            elif mutation=='missing_job':db.execute('delete from jobs where id=?',(job['id'],))
        if changed_readiness:raise evidence._ReadinessChanged({'reason':'search_response_observed'},readiness)
        return {'body_text':'must not escape'}
    monkeypatch.setattr(evidence,'_read',read)
    row=evidence.current_parser_page(studio,state,[job])[0]
    assert row['status']=='unavailable' and 'incident_changed' in row['reason']
    assert 'body_text' not in row and row['grants_retry'] is False
    assert 'current_saved_readiness' not in row


@pytest.mark.parametrize('damage',[None,'foreign_url','foreign_host','homepage','url_changed','readiness_changed',
    'oversized','invalid_count','duplicate_query','duplicate_blank','http','structure_count'])
def test_passive_transport_only_reads_exact_existing_search_page(tmp_path,monkeypatch,damage):
    from hotpost import source_browser_runtime as runtime
    from hotpost.source_search import readiness as records
    import playwright.sync_api
    settings=SimpleNamespace(data_dir=tmp_path);expected={'query':'previous product','reason':'page_unresolved'}
    calls=[]
    class Page:
        url='https://www.tiktok.com/search?q=previous%20product'
        def locator(self,selector):
            assert selector=='body';return self
        def evaluate(self,script,limit,**kwargs):
            assert 'innerText' in script and 'characters<limit' in script
            assert limit==evidence.BODY_LIMIT and kwargs=={'timeout':5000}
            calls.append('read')
            if damage=='url_changed':self.url='https://www.tiktok.com/search?q=other'
            text='x'*(evidence.BODY_LIMIT+1) if damage=='oversized' else 'visible result cards'
            structure=[{'ancestors':[{'tag':'A','role':'','data_e2e':'search-card'}]}]
            if damage=='structure_count':structure*=25
            return {'text':text,'characters':0 if damage=='invalid_count' else len(text),'structure':structure}
    page=Page()
    if damage=='foreign_url':page.url='https://www.tiktok.com/search?q=other'
    if damage=='foreign_host':page.url='https://other.example/search?q=previous%20product'
    if damage=='homepage':page.url='https://www.tiktok.com/'
    if damage=='duplicate_query':page.url+='&q=other'
    if damage=='duplicate_blank':page.url+='&q='
    if damage=='http':page.url=page.url.replace('https:','http:')
    context=object()
    class PW:
        chromium=None
        def __enter__(self):self.chromium=self;return self
        def __exit__(self,*args):pass
        def connect_over_cdp(self,address,**kwargs):
            assert address=='existing endpoint' and kwargs=={'timeout':5000};calls.append('attach')
            return SimpleNamespace(contexts=[context])
    reads=[]
    def readiness(*args):
        reads.append(1)
        return {'query':'changed'} if damage=='readiness_changed' and len(reads)>1 else expected
    monkeypatch.setattr(records,'readiness_record',readiness)
    monkeypatch.setattr(runtime,'endpoint',lambda s:'existing endpoint')
    monkeypatch.setattr(runtime,'browser_lease',lambda s:nullcontext())
    def select(ctx,s,provider):
        assert ctx is context and s is settings and provider=='tiktok';return page
    monkeypatch.setattr(runtime,'existing_page',select)
    monkeypatch.setattr(playwright.sync_api,'sync_playwright',PW)
    if damage:
        with pytest.raises(ValueError):evidence._read(settings,expected)
    else:
        result=evidence._read(settings,expected)
        assert result['body_text']=='visible result cards' and len(result['captured_text_sha256'])==64
        assert result['visible_video_link_structure'][0]['ancestors'][0]['data_e2e']=='search-card'
        assert result['dom_scope']==evidence.DOM_SCOPE
        assert calls==['attach','read']


@pytest.mark.parametrize('damage',['count','depth','missing','extra','role','attribute','tag','type','empty','surrogate'])
def test_dom_diagnostic_rejects_unbounded_or_unexpected_attributes(damage):
    node={'tag':'A','role':'link','data_e2e':'search-card'}
    value=[{'ancestors':[node]}]
    if damage=='count':value*=25
    if damage=='depth':value[0]['ancestors']*=8
    if damage=='missing':node.pop('role')
    if damage=='extra':node['href']='https://unexpected.example'
    if damage=='role':node['role']='x'*81
    if damage=='attribute':node['data_e2e']='x'*121
    if damage=='tag':node['tag']='x'*33
    if damage=='type':node['role']=False
    if damage=='empty':value[0]['ancestors']=[]
    if damage=='surrogate':node['data_e2e']='x'*119+'\ud83d'
    with pytest.raises(ValueError,match='invalid_link_structure'):evidence._validated_structure(value)


def test_dom_diagnostic_preserves_raw_unclassified_structure_at_budget():
    value=[{'ancestors':[{'tag':'DIV','role':'','data_e2e':'x'*119+'😀'} for _ in range(7)]} for _ in range(24)]
    assert evidence._validated_structure(value)==value
    json.dumps(value,ensure_ascii=False).encode('utf8')


def test_changed_readiness_exposes_only_bounded_saved_metadata_not_global_response(tmp_path,monkeypatch):
    studio,state,job,expected=bound(tmp_path)
    current={'reason':'search_response_observed','parser_revision':'new-parser','at':2,
        'previous_failure':expected,'recovery':{'task_id':'other-task','job_id':'other-job','run_id':'other-run',
        'status':'response_validated','response':{'sensitive':'full native body'},'cookie':'not exposed'},
        'unexpected':'not exposed'}
    def read(*args):raise evidence._ReadinessChanged(current,expected)
    monkeypatch.setattr(evidence,'_read',read)
    row=evidence.current_parser_page(studio,state,[job])[0]
    assert row['status']=='unavailable' and row['reason']=='readiness_changed'
    summary=row['current_saved_readiness']
    assert summary['reason']=='search_response_observed' and summary['at']==2
    assert summary['previous_failure_matches_incident'] is True
    assert summary['recovery']=={'task_id':'other-task','job_id':'other-job','run_id':'other-run','status':'response_validated'}
    assert row['grants_retry'] is False and summary['grants_retry'] is False
    assert 'sensitive' not in json.dumps(row) and 'not exposed' not in json.dumps(row)
    assert 'body_text' not in row and 'visible_video_link_structure' not in row


def test_saved_metadata_is_bounded_even_when_malformed():
    changed=evidence._ReadinessChanged({'reason':'x'*500,'parser_revision':'\ud83d','at':float('nan'),
        'recovery':{'task_id':'x'*500,'status':False}}, {})
    assert len(changed.summary['reason'])==200 and 'parser_revision' not in changed.summary
    assert 'at' not in changed.summary and 'status' not in changed.summary['recovery']
    assert changed.summary['previous_failure_matches_incident'] is False
    json.dumps(changed.summary,ensure_ascii=False,allow_nan=False).encode('utf8')


def test_observer_module_is_protected_from_owner_patch():
    from hotpost.video_agent_repairs import _PROTECTED
    assert 'video_agent_page_evidence.py' in _PROTECTED


def test_snapshot_and_actual_proposal_capture_host_page_facts_not_model_spoof(tmp_path,monkeypatch):
    from test_preparation_query_diagnostics import captured
    from hotpost.video_agents import VideoAgentManager
    from hotpost.video_agent_context import snapshot,semantic_fingerprint
    studio,state,*_=captured(tmp_path)
    studio.settings.source_browser_search=True
    studio.settings.source_browser_existing_window_only=True
    readiness={'query':'previous product','reason':'page_unresolved','at':1}
    parser={'task_id':state['id'],'run_id':state['run_id'],'observations':[
        {'provider':'tiktok','status':'readiness_blocked','manual_gate_active':False,'readiness':readiness}]}
    with studio.store.transaction() as db:
        jid=studio.store.enqueue(db,state['id'],'collect_sources',{'run_id':state['run_id']},'page-incident')
        db.execute("update jobs set status='failed',checkpoint=? where id=?",(json.dumps({'parser_repair_context':parser}),jid))
    monkeypatch.setattr(evidence,'_read',lambda *a:{'body_text':'Actual settled product results','page_url':'owned existing page'})
    received=[]
    studio.video_repair_pipeline=SimpleNamespace(propose_patch=lambda patch:received.append(patch) or 'repair',
        repair_material=lambda *args:{'content_fingerprint':'new-code'})
    manager=VideoAgentManager(studio)
    try:
        row=snapshot(studio,state['id'])['current_parser_page_observation'][0]
        assert row['status']=='observed' and row['body_text']=='Actual settled product results'
        result=manager.execute(state['id'],{'kind':'propose_patch','_agent_epoch':1,
            'patch':{'binding':{'job_id':jid},'incident_fixture':{'current_parser_page_observation':['spoofed']}}},
            'host-observe',semantic_fingerprint(state))
        assert result['status']=='completed'
        patch=received[0]
        assert patch['incident_fixture']['current_parser_page_observation']==patch['incident']['current_parser_page_observation']
        assert patch['incident_fixture']['current_parser_page_observation'][0]['body_text']=='Actual settled product results'
        assert 'spoofed' not in json.dumps(patch)
    finally:manager.pool.shutdown(wait=True)
