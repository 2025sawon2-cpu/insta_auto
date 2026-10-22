"""A review service wait must not replay completed external acquisition."""
import json
from types import SimpleNamespace

import pytest

from hotpost.model_service import ModelServiceUnavailable
from hotpost.studio_runtime.generation import GenerationMixin


def fixture_refresh(tmp_path, monkeypatch):
    manifest=tmp_path/'manifest.json'
    manifest.write_text('{}',encoding='utf-8')
    result={'zip_path':str(tmp_path/'sources.zip'),'candidates':[],
            'search_audit':[{'provider':'tiktok','query':'L자주방매트','status':'results'}]}
    calls=[];saved=[]
    monkeypatch.setattr('hotpost.source_finder.find_sources',lambda *a,**k:calls.append(k) or result)
    monkeypatch.setattr('hotpost.source_audit.reviewed_platform_outcomes',lambda *a:{})
    mixin=GenerationMixin();mixin.settings=SimpleNamespace()
    mixin.store=SimpleNamespace(change=lambda *a:None,checkpoint=lambda job,c:saved.append(json.loads(json.dumps(c))))
    mixin._source_records=lambda *a:[]
    state={'id':'task','shortcode':'reference','sources':[],'source_acquisition':{}}
    mixin.store.get=lambda tid:state
    job={'id':'job','payload':{'request':'L자주방매트'},'checkpoint':{}}
    return mixin,state,job,calls,saved


def test_completed_acquisition_resumes_after_capacity_wait(tmp_path,monkeypatch):
    mixin,state,job,calls,saved=fixture_refresh(tmp_path,monkeypatch)
    mixin._review_source_records=lambda *a:(_ for _ in ()).throw(ModelServiceUnavailable())
    with pytest.raises(ModelServiceUnavailable):mixin._refresh_sources(state,job)
    assert len(calls)==1 and saved[-1]['refresh_discovery']['sha256']
    # A fresh worker receives only the durable checkpoint.
    job['checkpoint']=saved[-1]
    mixin._review_source_records=lambda *a:([],None)
    output=mixin._refresh_sources(state,job)
    assert len(calls)==1 and output['searches'][0]['query']=='L자주방매트'


def test_explicit_new_search_keeps_saved_scopes_and_defers_old_reviews(tmp_path,monkeypatch):
    mixin,state,job,calls,saved=fixture_refresh(tmp_path,monkeypatch)
    state['source_acquisition']['interrupted_attempts']=[{'saved':'preserved'}]
    state['source_acquisition']['queries']=[{'provider':'tiktok','query':'previous bag','status':'results'}]
    job['payload']['search_before_saved_reviews']=True
    mixin._review_deferred_downloads=lambda *a:pytest.fail('Explicit new search must keep old review deferred')
    mixin._source_access_gate=lambda *a:['tiktok']
    mixin._review_source_records=lambda *a:([],None)
    mixin._refresh_sources(state,job)
    assert len(calls)==1
    assert any(r.get('query')=='previous bag' for r in calls[0]['previous_searches'])
    assert state['source_acquisition']['interrupted_attempts']==[{'saved':'preserved'}]


@pytest.mark.parametrize('change',['request','receipt'])
def test_changed_resume_input_is_not_automatically_searched_again(tmp_path,monkeypatch,change):
    mixin,state,job,calls,saved=fixture_refresh(tmp_path,monkeypatch)
    mixin._review_source_records=lambda *a:(_ for _ in ()).throw(ModelServiceUnavailable())
    with pytest.raises(ModelServiceUnavailable):mixin._refresh_sources(state,job)
    if change=='request':job['payload']['request']='다른 매트'
    else:(tmp_path/'refresh-result.json').write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='자동 반복'):mixin._refresh_sources(state,job)
    assert len(calls)==1


def test_durable_writing_job_and_overlay_lock_error_recovery(tmp_path):
    from hotpost.writing.jobs import Jobs
    from hotpost.scene_requirements import clear_cached_review_errors
    from hotpost.source_overlay_review import needs_overlay_review, POLICY
    jobs=Jobs(tmp_path/'writing')
    created=jobs.create('editorial',{'instruction':'check','evidence':{}})
    jid=created['id']
    folder=tmp_path/'writing'/jid
    call_dir=folder/'codex-testcall'
    call_dir.mkdir(parents=True)
    (call_dir/'receipt.json').write_text(json.dumps({'status':'completed','exit_code':0}),encoding='utf-8')
    expected={'value':{'frames':[]},'inference':{'provider':'codex','calls':[],'fallback':False},'processing_seconds':1.2}
    (folder/'result.json').write_text(json.dumps(expected),encoding='utf-8')
    jobs.update(jid,state='failed',error='database is locked',result={'error_reason':'OperationalError'},message='집필 실패')
    recovered=jobs.get(jid,include_payload=False)
    assert recovered['state']=='completed' and recovered['result']==expected and recovered['error']==''
    locked_source={'id':'s1','sha256':'abc','source_quality':'edited-with-text',
                   'overlay_review_error':'Codex 실행 실패: database is locked',
                   'overlay_review_attempted_policy':POLICY,'overlay_review_attempted_sha256':'abc'}
    rejected_source={'id':'s2','sha256':'def','source_quality':'edited-with-text',
                     'overlay_review_error':'An independent visual reviewer and exact intervals are required',
                     'overlay_review_attempted_policy':POLICY,'overlay_review_attempted_sha256':'def'}
    assert needs_overlay_review(locked_source) is True
    assert needs_overlay_review(rejected_source) is False
    assert clear_cached_review_errors(locked_source) is True
    assert 'overlay_review_error' not in locked_source
    assert clear_cached_review_errors(rejected_source) is False
    assert rejected_source.get('overlay_review_error')
