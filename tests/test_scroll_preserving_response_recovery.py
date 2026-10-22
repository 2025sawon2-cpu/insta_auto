"""Preserved unavailable checkpoint through the actual recovery entry.
External browser doubles only; no media approval. The preparation integration
regression must accompany this test before independent review.
"""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from hotpost import source_parser_recovery as recovery
from hotpost.editing_adapter import _atomic_json
from hotpost.source_search.readiness import readiness_record
from test_source_parser_response_incident import browser_fixture, response, DiskStore


@pytest.mark.parametrize('blocked',[False,True])
def test_saved_incident_scroll_then_bound_refresh(tmp_path,monkeypatch,blocked):
    fixture=json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    state=copy.deepcopy(fixture['task']);job=copy.deepcopy(fixture['job'])
    assert job['id']=='job-f0a99c40533f423f'
    assert state['id']==job['task_id'] and state['run_id']==job['payload']['run_id']
    failed=copy.deepcopy(job['checkpoint']['parser_repair_context']['observations'][0]['readiness'])
    assert job['checkpoint']['parser_response_recovery']['status']=='unavailable'
    settings,page=browser_fixture(monkeypatch,tmp_path,failed['query'])
    _atomic_json(tmp_path/'search_readiness'/'tiktok.json',failed)
    scrolls=[];refreshes=[]
    page.mouse=SimpleNamespace(wheel=lambda *args:scrolls.append(args))
    page.wait_for_timeout=lambda milliseconds:None
    def reload(**kwargs):
        assert kwargs=={'wait_until':'domcontentloaded','timeout':10000}
        starts=json.loads((settings.source_browser_profile_dir/'hotpost-search-starts.json').read_text('utf8'))
        assert starts['tiktok']>0
        refreshes.append(kwargs)
        payload=response(failed['query'])
        item=SimpleNamespace(status=200,url=payload['response_url'],json=lambda:payload['body'])
        for callback in list(page.listeners):callback(item)
    page.reload=reload
    with pytest.raises(recovery.ResponseObservationUnavailable) as unavailable:
        recovery.read_response(settings,failed['query'])
    assert unavailable.value.reason=='matching_native_response_not_observed'
    assert scrolls==[(0,900)] and refreshes==[]
    store=DiskStore(state,tmp_path)
    before=copy.deepcopy(state)
    if blocked:
        _atomic_json(tmp_path/'search_cooldowns'/'tiktok.json',{'reason':'login_required','requires_verification':True,'until':0})
    assert recovery.recover_response(settings,store,state,job) is (not blocked)
    saved=store.reload(job)['parser_response_recovery']
    assert saved['task_id']==state['id'] and saved['job_id']==job['id']
    assert saved['run_id']==state['run_id'] and saved['previous_readiness']==failed
    assert saved['grants_media_approval'] is False and saved['query_submitted'] is False
    assert saved['status']==('unavailable' if blocked else 'response_validated')
    assert len(refreshes)==(0 if blocked else 1) and page.listeners==[]
    assert state==before
    if blocked:assert readiness_record(tmp_path,'tiktok')==failed
    else:
        assert scrolls==[(0,900),(0,900)]
        assert readiness_record(tmp_path,'tiktok')['previous_failure']==failed
        assert saved['response']['requests'][0]['minimum_interval_seconds']>=30
