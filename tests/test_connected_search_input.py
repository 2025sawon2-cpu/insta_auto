"""Actual connected failures: repeated Search labels and restored input text."""
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from hotpost.browser_search import BrowserSearcher
from hotpost.config import Settings
from hotpost.source_search.readiness import readiness_blocked


def harness(tmp_path,monkeypatch,*,text_count=3,icon_count=1,restore=False,input_count=1,redirect=None):
    events=[]
    class Field:
        visible=False
        value='apple'
        def is_visible(self):return self.visible
        def count(self):return input_count if self.visible else 0
        def wait_for(self,**kwargs):assert self.visible
        def press_sequentially(self,text,**kwargs):self.value=text if not restore else 'apple '+text
        def input_value(self):return self.value
        def press(self,key):
            events.append(key)
            if key=='ControlOrMeta+A':self.value=''
            if key=='Enter':page.url=(redirect or 'https://www.tiktok.com/search')+'?'+urlencode({'q':self.value})
    field=Field();field.first=field
    class Control:
        def __init__(self,count,label):self.n=count;self.label=label
        def filter(self,**kwargs):return self
        def count(self):return self.n
        def click(self,**kwargs):events.append(self.label);field.visible=True
    text=Control(text_count,'text-control');icon=Control(icon_count,'icon-control')
    page=SimpleNamespace(url='https://www.tiktok.com/search?q=apple',
                         is_closed=lambda:False,context=SimpleNamespace(browser=SimpleNamespace(is_connected=lambda:True)),
                         get_by_text=lambda *a,**kw:text,
                         locator=lambda selector:icon if 'DivSearchIconContainer' in selector else field,
                         wait_for_timeout=lambda _:None)
    def wait_for_url(predicate,**kwargs):assert predicate(page.url)
    page.wait_for_url=wait_for_url
    searcher=BrowserSearcher(Settings(data_dir=tmp_path),tmp_path/'debug')
    monkeypatch.setattr(searcher,'_check_block',lambda *args:False)
    monkeypatch.setattr(searcher,'_pace',lambda *args,**kwargs:None)
    return searcher,page,events


def test_three_search_labels_use_one_actual_icon_without_waiting_on_hidden_field(tmp_path,monkeypatch):
    searcher,page,events=harness(tmp_path,monkeypatch)
    audit={}
    assert searcher._submit_search(page,'tiktok','사과',audit)
    assert events==['icon-control','ControlOrMeta+A','Enter']
    assert audit['execution']['input_value']=='사과'
    assert audit['execution']['query_submitted'] and audit['execution']['query_url_matched']


def test_ambiguous_icon_never_types_or_consumes_the_query(tmp_path,monkeypatch):
    searcher,page,events=harness(tmp_path,monkeypatch,icon_count=2)
    audit={}
    assert not searcher._submit_search(page,'tiktok','사과',audit)
    assert events==[] and not audit.get('requests')
    assert audit['status']=='page_unresolved' and not audit['execution']['query_submitted']
    assert readiness_blocked(searcher.settings.data_dir,'tiktok')


def test_restored_old_query_is_recorded_without_pressing_enter(tmp_path,monkeypatch):
    searcher,page,events=harness(tmp_path,monkeypatch,restore=True)
    audit={}
    assert not searcher._submit_search(page,'tiktok','사과',audit)
    assert 'Enter' not in events
    assert audit['execution']['input_value']=='apple 사과'
    assert audit['stage']=='search_input_mismatch' and not audit['execution']['query_submitted']


def test_url_wait_failure_preserves_submit_and_unconfirmed_result(tmp_path,monkeypatch):
    searcher,page,events=harness(tmp_path,monkeypatch)
    def fail(*args,**kwargs):raise TimeoutError('unconfirmed search response')
    page.wait_for_url=fail
    audit={}
    with pytest.raises(TimeoutError):searcher._submit_search(page,'tiktok','사과',audit)
    assert audit['execution']['query_submitted'] and not audit['execution']['query_url_matched']
    assert events.count('Enter')==1


@pytest.mark.parametrize('redirect',['https://unrelated.example/search','https://www.tiktok.com/login'])
def test_matching_query_on_wrong_origin_or_path_cannot_verify_the_search(tmp_path,monkeypatch,redirect):
    searcher,page,events=harness(tmp_path,monkeypatch,redirect=redirect)
    audit={}
    with pytest.raises(AssertionError):searcher._submit_search(page,'tiktok','사과',audit)
    assert audit['execution']['query_submitted'] and not audit['execution']['query_url_matched']


def test_two_visible_inputs_are_not_selected_arbitrarily(tmp_path,monkeypatch):
    searcher,page,events=harness(tmp_path,monkeypatch,input_count=2)
    audit={}
    assert not searcher._submit_search(page,'tiktok','사과',audit)
    assert 'Enter' not in events and 'ControlOrMeta+A' not in events
    assert audit['stage']=='search_input_ambiguous'


def test_typing_failure_before_enter_holds_the_parser_without_retransmission(tmp_path,monkeypatch):
    searcher,page,events=harness(tmp_path,monkeypatch)
    field=page.locator('input')
    def fail(*args,**kwargs):raise RuntimeError('controlled input was detached')
    field.press_sequentially=fail
    monkeypatch.setattr(searcher,'_cooling_down',lambda *args,**kwargs:False)
    monkeypatch.setattr(searcher,'_page',lambda *args:page)
    monkeypatch.setattr(searcher,'_retry_pause',lambda *args:pytest.fail('No repeated input'))
    searcher._platforms(None,['사과'],3,providers={'tiktok'})
    row=next(row for row in searcher.searches if row.get('query')=='사과')
    assert row['status']=='page_unresolved' and not row['execution']['query_submitted']
    assert events.count('ControlOrMeta+A')==1 and 'Enter' not in events
    assert readiness_blocked(searcher.settings.data_dir,'tiktok')
