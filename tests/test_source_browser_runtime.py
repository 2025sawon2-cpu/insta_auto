from types import SimpleNamespace
import json
import subprocess
import sys

import pytest

from hotpost.config import Settings
from hotpost import source_browser_runtime as runtime
from hotpost import browser_search as bs


def test_first_search_immediate_elapsed_time_and_other_jobs_share_pacing(tmp_path, monkeypatch):
    clock = [100.0]
    waits = []
    monkeypatch.setattr(runtime.time, 'time', lambda: clock[0])
    def sleep(seconds):
        waits.append(seconds); clock[0] += seconds
    monkeypatch.setattr(runtime.time, 'sleep', sleep)
    settings = Settings(data_dir=tmp_path)
    runtime.pace(settings, 'youtube')
    assert waits == []
    clock[0] += 7
    runtime.pace(Settings(data_dir=tmp_path), 'youtube')
    assert waits == [3]
    clock[0] += 15
    runtime.pace(settings, 'youtube')
    runtime.pace(settings, 'douyin')
    assert waits == [3]


def test_tiktok_search_and_download_share_thirty_second_floor(tmp_path, monkeypatch):
    clock = [100.0]
    waits = []
    monkeypatch.setattr(runtime.time, 'time', lambda: clock[0])
    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr(runtime.time, 'sleep', sleep)
    settings = Settings(data_dir=tmp_path)
    runtime.pace(settings, 'tiktok')
    clock[0] += 7
    runtime.pace(Settings(data_dir=tmp_path), 'tiktok', minimum=1)
    assert waits == [23]
    assert runtime.operation_interval(settings, 'tiktok', minimum=60) == 60


def test_tiktok_captcha_stops_without_automatic_wait_or_retry(tmp_path, monkeypatch):
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    monkeypatch.setattr(searcher, '_captcha', lambda page: True)
    page = SimpleNamespace(url='https://www.tiktok.com/',
        wait_for_timeout=lambda _: pytest.fail('Must stop on the first challenge'))
    assert searcher._check_block(page, 'tiktok', {})
    assert bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)._cooling_down('tiktok')


def test_operation_lease_excludes_other_process_and_recovers_after_exit(tmp_path):
    settings = Settings(data_dir=tmp_path)
    script = """
import sys
from pathlib import Path
from hotpost.config import Settings
from hotpost.source_browser_runtime import browser_lease, BrowserBusy
try:
    with browser_lease(Settings(data_dir=Path(sys.argv[1]))): pass
except BrowserBusy: sys.exit(7)
"""
    with runtime.browser_lease(settings):
        assert subprocess.run([sys.executable, '-c', script, str(tmp_path)]).returncode == 7
    assert subprocess.run([sys.executable, '-c', script, str(tmp_path)]).returncode == 0


def test_server_retry_after_is_preserved_across_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    clock = [100.0]
    monkeypatch.setattr(bs.time, 'time', lambda: clock[0])
    settings = Settings(data_dir=tmp_path)
    searcher = bs.BrowserSearcher(settings, tmp_path)
    searcher._check_block(None, 'tiktok', {}, SimpleNamespace(status=429, headers={'retry-after': '1200'}))
    clock[0] = 800
    bs.BROWSER_COOLDOWNS.clear()
    assert bs.BrowserSearcher(settings, tmp_path)._cooling_down('tiktok')
    clock[0] = 1301
    assert not bs.BrowserSearcher(settings, tmp_path)._cooling_down('tiktok')


def test_visible_search_fills_and_submits_without_replacing_page(tmp_path, monkeypatch):
    actions = []
    field = SimpleNamespace(is_visible=lambda: True, wait_for=lambda **kw: None,
        input_value=lambda:'slow search',
        press_sequentially=lambda text,**kw: actions.append(('type', text)), press=lambda key: actions.append(('press', key)))
    page = SimpleNamespace(url='https://www.tiktok.com/',
        locator=lambda selector: SimpleNamespace(first=field,count=lambda:1), wait_for_timeout=lambda ms:None,
        wait_for_url=lambda predicate, **kw: actions.append(('matching', predicate('https://www.tiktok.com/search?q=slow+search'))))
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    monkeypatch.setattr(searcher, '_check_block', lambda *a: False)
    assert searcher._submit_search(page, 'tiktok', 'slow search', {})
    assert actions == [('press', 'ControlOrMeta+A'), ('type', 'slow search'), ('press', 'Enter'), ('matching', True)]


def test_collapsed_tiktok_search_opens_existing_page_before_input(tmp_path, monkeypatch):
    visible = [False]
    actions = []

    def open_panel(**kwargs):
        actions.append('open_search')
        visible[0] = True

    def wait_for(**kwargs):
        assert visible[0], 'The hidden input must be revealed before waiting'

    field = SimpleNamespace(is_visible=lambda: visible[0], wait_for=wait_for,
        input_value=lambda:'bed tent',
        press_sequentially=lambda text,**kw: actions.append(('type', text)), press=lambda key: actions.append(('press', key)))
    control = SimpleNamespace(filter=lambda **kwargs: control, count=lambda: 1, click=open_panel)
    page = SimpleNamespace(url='https://www.tiktok.com/',
        locator=lambda selector: SimpleNamespace(first=field,count=lambda:1), get_by_text=lambda pattern: control, wait_for_timeout=lambda ms:None,
        wait_for_url=lambda predicate, **kwargs: actions.append(('matching', predicate('https://www.tiktok.com/search?q=bed+tent'))))
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    monkeypatch.setattr(searcher, '_check_block', lambda *args: False)
    audit = {}
    assert searcher._submit_search(page, 'tiktok', 'bed tent', audit)
    assert actions == ['open_search', ('press', 'ControlOrMeta+A'), ('type', 'bed tent'), ('press', 'Enter'), ('matching', True)]
    assert audit['stage'] == 'search_results'


def test_opening_tiktok_search_stops_if_authentication_wall_appears(tmp_path, monkeypatch):
    field = SimpleNamespace(is_visible=lambda: False,
        wait_for=lambda **kwargs: (_ for _ in ()).throw(AssertionError('Must stop at the access wall')))
    control = SimpleNamespace(filter=lambda **kwargs: control, count=lambda: 1, click=lambda **kwargs: None)
    page = SimpleNamespace(url='https://www.tiktok.com/',
        locator=lambda selector: SimpleNamespace(first=field), get_by_text=lambda pattern: control)
    checks = iter([False, True])
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    monkeypatch.setattr(searcher, '_check_block', lambda *args: next(checks))
    assert not searcher._submit_search(page, 'tiktok', 'bed tent', {})


def test_tiktok_results_button_uses_previous_query_label(tmp_path, monkeypatch):
    actions = []
    field = SimpleNamespace(is_visible=lambda:False,wait_for=lambda **kwargs:None,
        input_value=lambda:'new query',
        press_sequentially=lambda text,**kw:actions.append(text),press=lambda key:None)
    missing = SimpleNamespace(filter=lambda **kwargs:missing,count=lambda:0)
    control = SimpleNamespace(filter=lambda **kwargs:control,count=lambda:1,click=lambda **kwargs:actions.append('open_previous_query'))
    page = SimpleNamespace(url='https://www.tiktok.com/search?q=old+query',
        locator=lambda selector:SimpleNamespace(first=field,count=lambda:1),wait_for_timeout=lambda ms:None,
        get_by_text=lambda text,**kwargs:control if text=='old query' else missing,
        wait_for_url=lambda *args,**kwargs:None)
    searcher=bs.BrowserSearcher(Settings(data_dir=tmp_path),tmp_path)
    monkeypatch.setattr(searcher,'_check_block',lambda *args:False)
    monkeypatch.setattr(searcher,'_pace',lambda *args,**kwargs:None)
    assert searcher._submit_search(page,'tiktok','new query',{})
    assert actions==['open_previous_query','new query']


def test_stale_sidebar_label_opens_search_icon_and_replaces_query_with_keys(tmp_path, monkeypatch):
    actions=[];missing=SimpleNamespace(filter=lambda **kw:missing,count=lambda:0)
    icon=SimpleNamespace(count=lambda:1,click=lambda **kw:actions.append('icon'))
    field=SimpleNamespace(is_visible=lambda:False,wait_for=lambda **kw:None,
        input_value=lambda:'fresh query',
        fill=lambda _:pytest.fail('Controlled input must use key events'),
        press=lambda key:actions.append(key),press_sequentially=lambda text,**kw:actions.append((text,kw['delay'])))
    page=SimpleNamespace(url='https://www.tiktok.com/search?q=new+url+but+stale+label',
        locator=lambda selector:icon if 'TUXButton-content' in selector else SimpleNamespace(first=field,count=lambda:1),
        get_by_text=lambda *args,**kw:missing,wait_for_timeout=lambda ms:None,wait_for_url=lambda *args,**kw:None)
    searcher=bs.BrowserSearcher(Settings(data_dir=tmp_path),tmp_path)
    monkeypatch.setattr(searcher,'_check_block',lambda *args:False);monkeypatch.setattr(searcher,'_pace',lambda *args,**kw:None)
    assert searcher._submit_search(page,'tiktok','fresh query',{})
    assert actions==['icon','ControlOrMeta+A',('fresh query',90),'Enter']


def test_result_arriving_after_ten_seconds_is_collected_without_next_search(tmp_path, monkeypatch):
    clock = [0]
    hits = []
    monkeypatch.setattr(bs.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(bs, 'empty_results_on_page', lambda _: False)
    monkeypatch.setattr(bs, 'search_restriction_on_page', lambda _: False)
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    monkeypatch.setattr(searcher, '_check_block', lambda *a: False)
    def wait(_):
        clock[0] += 1
        if clock[0] == 15:
            hits.append({'url': 'https://www.tiktok.com/@fixture/video/1234567890123'})
    audit = {}
    result = searcher._wait_platform_results(SimpleNamespace(wait_for_timeout=wait), 'tiktok', 'slow', audit, hits)
    assert result == hits and len(result) == 1
    assert audit['result_wait_seconds'] == 15


def test_worker_attaches_without_launching_or_closing_chrome(tmp_path, monkeypatch):
    context = SimpleNamespace(set_default_timeout=lambda _: None, cookies=lambda: [],
                              close=lambda: pytest.fail('Attached context must remain open'))
    settings = Settings(data_dir=tmp_path)
    settings.source_browser_profile_dir.mkdir()
    (settings.source_browser_profile_dir / 'hotpost-live-session-v1').write_text('1')
    monkeypatch.setattr(runtime, 'endpoint', lambda _: 'http://127.0.0.1:1234')
    connected = []
    playwright = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=lambda url, **kw:
        connected.append(url) or SimpleNamespace(contexts=[context])))
    assert runtime.attach_browser(playwright, settings) is context
    assert connected == ['http://127.0.0.1:1234']


def test_managed_tab_reused_without_touching_user_tabs(tmp_path):
    settings = Settings(data_dir=tmp_path)
    front = []
    user = SimpleNamespace(id='user')
    created = SimpleNamespace(id='collection', bring_to_front=lambda: front.append('collection'))
    pages = [user]
    def new_page():
        pages.append(created); return created
    def session(page):
        return SimpleNamespace(send=lambda _: {'targetInfo': {'targetId': page.id}}, detach=lambda: None)
    context = SimpleNamespace(pages=pages, new_page=new_page, new_cdp_session=session)
    assert runtime.managed_page(context, settings, 'tiktok') is created
    assert runtime.managed_page(context, settings, 'tiktok') is created
    assert pages == [user, created] and front == ['collection', 'collection']


def test_search_uses_existing_platform_tab_and_does_not_create_replacement(tmp_path):
    settings = Settings(data_dir=tmp_path)
    unrelated = SimpleNamespace(url='https://www.youtube.com/', is_closed=lambda:False)
    existing = SimpleNamespace(url='https://www.tiktok.com/search?q=old', is_closed=lambda:False)
    context = SimpleNamespace(pages=[unrelated, existing],
        new_page=lambda:pytest.fail('Search may not create a replacement tab'))
    assert runtime.existing_page(context, settings, 'tiktok') is existing
    with pytest.raises(LookupError, match='missing'):
        runtime.existing_page(context, settings, 'douyin')
    context.pages.append(SimpleNamespace(url='https://www.tiktok.com/', is_closed=lambda:False))
    context.new_cdp_session = lambda p:SimpleNamespace(send=lambda _: {'targetInfo':{'targetId':str(id(p))}}, detach=lambda:None)
    with pytest.raises(LookupError, match='ambiguous'):
        runtime.existing_page(context, settings, 'tiktok')


def test_search_controller_cannot_launch_chrome_if_connection_is_missing(tmp_path, monkeypatch):
    from hotpost.source_browser_worker import isolated_search
    monkeypatch.setattr(runtime, 'endpoint', lambda _:None)
    monkeypatch.setattr(runtime, 'ensure_browser', lambda _:pytest.fail('No automatic browser launch'))
    result = isolated_search(Settings(data_dir=tmp_path), [], ['cart'], 5, tmp_path/'debug')
    assert result['candidates'] == [] and result['searches'][0]['status'] == 'connection_failed'
