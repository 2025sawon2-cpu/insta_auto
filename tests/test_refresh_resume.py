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


@pytest.mark.parametrize('change',['request','receipt'])
def test_changed_resume_input_is_not_automatically_searched_again(tmp_path,monkeypatch,change):
    mixin,state,job,calls,saved=fixture_refresh(tmp_path,monkeypatch)
    mixin._review_source_records=lambda *a:(_ for _ in ()).throw(ModelServiceUnavailable())
    with pytest.raises(ModelServiceUnavailable):mixin._refresh_sources(state,job)
    if change=='request':job['payload']['request']='다른 매트'
    else:(tmp_path/'refresh-result.json').write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='자동 반복'):mixin._refresh_sources(state,job)
    assert len(calls)==1
