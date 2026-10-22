"""Preserved current incident through the real gate; external CDP only is isolated.
The installed setup deep-copies HOTPOST_REPAIR_INCIDENT, retains task/job/run and
failed readiness, and consistently rebinds isolated preparation media. Existing
pinned retry/load tests cover admission. No runtime approval is fabricated.
"""
import importlib.util
from pathlib import Path
import pytest
from hotpost.source_access_preflight import SourceAccessWaiting
from hotpost.source_search.readiness import readiness_record


def incident_tests():
    path=Path(__file__).with_name('test_submitted_search_scroll_incident.py')
    spec=importlib.util.spec_from_file_location('installed_scroll_fixture',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


_preserved_tests=incident_tests()
# Direct pytest collection retains each original function and parametrization.
# Their entry points are production execute, StudioStore.claim and source gate.
test_explicit_retry_claim_reaches_preserved_gate = _preserved_tests.test_explicit_retry_claim_reaches_preserved_gate
test_current_retry_admission_rejects_invalid_proof = _preserved_tests.test_current_retry_admission_rejects_invalid_proof
test_scroll_never_bypasses_failed_prerequisite = _preserved_tests.test_scroll_never_bypasses_failed_prerequisite


def setup_case(tmp_path,monkeypatch):
    return _preserved_tests.setup_incident(tmp_path,monkeypatch)


@pytest.mark.parametrize('condition,reason',[('query','owned_page_query_mismatch'),
    ('empty','owned_page_body_empty'),('response','matching_native_response_not_observed')])
def test_failure_is_persisted_and_same_job_can_reach_normal_gate(tmp_path,monkeypatch,condition,reason):
    fixture,state,job,failed,settings,page,store,owner,bundle=setup_case(tmp_path,monkeypatch)
    assert job['id']==fixture['job']['id']=='job-2861e0826f2f4395'
    assert job['checkpoint']['parser_response_recovery']['status']=='unavailable'
    original_url=page.url
    if condition=='query':page.url='https://www.tiktok.com/search?q=unrelated'
    elif condition=='empty':page.body=''
    with pytest.raises(SourceAccessWaiting):owner._source_access_gate(state,job)
    saved=store.reload(job)['parser_response_recovery']
    assert saved['status']=='unavailable'
    assert saved['observation_reason']==reason
    assert saved['task_id']==fixture['task']['id'] and saved['job_id']==fixture['job']['id']
    assert saved['run_id']==state['run_id']
    assert saved['query_submitted'] is False and saved['grants_media_approval'] is False
    assert readiness_record(tmp_path,'tiktok')==failed
    assert page.listeners==[] and page.emitted==0
    # Fresh external page state/response is test data, not a runtime permission.
    page.url=original_url;page.body='Search videos';page.scrolls.clear();page.enable_scroll=True
    assert 'tiktok' in owner._source_access_gate(store.get(state['id']),job)
    recovered=store.reload(job)['parser_response_recovery']
    assert recovered['status']=='response_validated'
    assert recovered['job_id']==fixture['job']['id'] and recovered['run_id']==state['run_id']
    assert recovered['grants_media_approval'] is False and recovered['query_submitted'] is False
    assert page.scrolls==[(0,900)] and page.listeners==[]
    assert not store.get(state['id'])['sources'] and not store.get(state['id'])['edits']
