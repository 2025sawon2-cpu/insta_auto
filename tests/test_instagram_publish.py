"""No live accounts: publication provenance, one-shot submission and recovery."""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from hotpost.instagram_publish import validate_package
from hotpost.monetization_store import MonetizationConflict, NextPostBusy
from test_monetization import followup_fixture


def ready_service(tmp_path, *, failure=False):
    service, calls, video, _ = followup_fixture(tmp_path)
    cover = tmp_path / 'cover.png'
    cover.write_bytes(b'reviewed-cover')
    video['edits'][0]['cover_path'] = str(cover)
    browser = service._browser()
    def publish(state, folder, progress):
        calls.append(('upload', state['package']['media']['video']['path']))
        progress('uploading')
        progress('submitting')
        calls.append(('share', state['package']['caption']))
        if failure:
            raise RuntimeError('Share response disconnected')
        progress('platform_processing')
        return dict(submitted=True, account=state['account'],
                    package_sha256=state['package']['package_sha256'],
                    automation_id=state['littly']['automation_id'], evidence_path='fixture-shared.json',
                    post_url='https://www.instagram.com/reel/OurPost/')
    browser.publish_instagram = publish
    service.browser_factory = lambda _: browser
    service.run('work-1', 'OurAccount', '나도')
    service.close()
    assert service.get('work-1')['stage'] == 'awaiting_post'
    return service, calls, cover, video


def test_preparation_does_not_publish_and_explicit_publish_is_one_shot(tmp_path):
    service, calls, _, _ = ready_service(tmp_path)
    assert not any(kind == 'share' for kind, _ in calls)
    result = service.publish('work-1', background=False)
    assert result['publication']['phase'] == 'awaiting_confirmation'
    assert result['publication']['media_verified'] is False
    assert result['stage'] == 'awaiting_post' and result['delivery_verified'] is False
    assert service.store.next_post_busy('ouraccount', 'another-task')
    with pytest.raises(MonetizationConflict):
        service.publish('work-1', background=False)
    assert len([row for row in calls if row[0] == 'share']) == 1


@pytest.mark.parametrize('changed', ['cover', 'caption', 'dm_message', 'affiliate_url', 'account', 'product'])
def test_changed_package_never_reaches_upload(tmp_path, changed):
    service, calls, cover, _ = ready_service(tmp_path)
    state = service.store.get('work-1')
    if changed == 'cover':
        cover.write_bytes(b'different pixels')
    elif changed == 'product':
        service.store.change('work-1', {'product': {**state['product'], 'product_url': 'https://www.coupang.com/vp/products/999'}})
    else:
        state['package'][changed] = 'tampered value'
        service.store.change('work-1', {'package': state['package']})
    with pytest.raises(ValueError):
        service.publish('work-1', background=False)
    assert not any(kind == 'upload' for kind, _ in calls)


def test_uncertain_share_survives_restart_and_only_read_only_inspection_recovers(tmp_path):
    service, calls, _, _ = ready_service(tmp_path, failure=True)
    result = service.publish('work-1', background=False)
    assert result['status'] == 'error' and result['external_result_uncertain']
    assert result['publication']['phase'] == 'submitting'
    service.store.recover_abandoned()
    with pytest.raises(MonetizationConflict):
        service.publish('work-1', background=False)
    service.inspect_post('work-1', 'https://www.instagram.com/reel/OurPost/')
    service.close()
    result = service.get('work-1')
    assert result['stage'] == 'awaiting_delivery' and result['status'] == 'ready'
    assert not result['external_result_uncertain'] and not result['delivery_verified']
    assert not service.store.next_post_busy('ouraccount', 'another-task')
    assert len([row for row in calls if row[0] == 'share']) == 1
    # The original uncertain receipt is preserved rather than deleted/reset.
    assert next(e for e in result['effects'] if e['kind'] == 'instagram_publish')['status'] == 'unknown'


def test_wrong_post_cannot_release_reservation_after_acknowledged_upload(tmp_path):
    service, _, _, _ = ready_service(tmp_path)
    service.publish('work-1', background=False)
    with pytest.raises(ValueError):
        service.inspect_post('work-1', 'https://www.instagram.com/reel/DifferentPost/')
    assert service.store.next_post_busy('ouraccount', 'another-task')


def test_wrong_reservation_owner_cannot_submit(tmp_path):
    service, calls, _, _ = ready_service(tmp_path)
    with service.store.connect() as db:
        db.execute('UPDATE next_post_slots SET task_id=?', ('other-task',))
    with pytest.raises(NextPostBusy):
        service.publish('work-1', background=False)
    assert not any(kind == 'upload' for kind, _ in calls)


def test_missing_cover_blocks_upload_without_destroying_prepared_text(tmp_path):
    service, calls, _, _ = followup_fixture(tmp_path)
    service.run('work-1', 'OurAccount', '나도'); service.close()
    caption = service.get('work-1')['package']['caption']
    with pytest.raises(ValueError):
        service.publish('work-1', background=False)
    assert service.get('work-1')['package']['caption'] == caption
    assert not any(kind == 'upload' for kind, _ in calls)


def test_actual_attach_browser_context_contract_is_used(tmp_path, monkeypatch):
    from hotpost.monetization_browser import MonetizationBrowser
    from hotpost.config import Settings
    from hotpost import source_browser_runtime as runtime
    import playwright.sync_api
    context = object()
    monkeypatch.setattr(playwright.sync_api, 'sync_playwright', lambda: nullcontext(object()))
    monkeypatch.setattr(runtime, 'browser_lease', lambda _: nullcontext())
    monkeypatch.setattr(runtime, 'attach_browser', lambda *_: context)
    with MonetizationBrowser(Settings(data_dir=tmp_path)).session() as actual:
        assert actual is context


def test_existing_only_attach_failure_does_not_navigate_or_recover_other_tabs(tmp_path, monkeypatch):
    from hotpost import source_browser_runtime as runtime
    from hotpost.config import Settings
    settings = Settings(data_dir=tmp_path, source_browser_existing_window_only=True)
    monkeypatch.setattr(runtime, 'endpoint', lambda _: 'http://127.0.0.1:12345')
    def fail(*_, **__): raise RuntimeError('connection unavailable')
    monkeypatch.setattr(runtime, '_recover_hung_cdp_pages', lambda _: pytest.fail('must not navigate other tabs'))
    with pytest.raises(RuntimeError, match='connection unavailable'):
        runtime.attach_browser(SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=fail)), settings)


def test_uncertain_littly_is_observed_without_another_create_or_comment(tmp_path):
    service, calls, _, _ = followup_fixture(tmp_path)
    browser = service._browser()
    original_register = browser.register_littly
    def lost(*args):
        original_register(*args)
        raise RuntimeError('confirmation lost')
    browser.register_littly = lost
    browser.inspect_littly_registration = lambda state, url, folder: {
        **state['package'], 'account': state['account'], 'automation_id': 'automation-1',
        'automation_url': url, 'saved_verified': True, 'evidence_path': 'fixture-reconciled.json'}
    service.browser_factory = lambda _: browser
    service.run('work-1', 'OurAccount', '나도'); service.close()
    state = service.get('work-1')
    assert state['stage'] == 'littly' and state['external_result_uncertain']
    assert service.store.next_post_busy('ouraccount', 'another-task')
    service.inspect_littly('work-1', 'https://app.litt.ly/automations/automation-1'); service.close()
    state = service.get('work-1')
    assert state['stage'] == 'awaiting_post' and not state['external_result_uncertain']
    assert service.store.next_post_busy('ouraccount', 'another-task')
    assert [kind for kind, _ in calls].count('littly') == 1
    assert [kind for kind, _ in calls].count('comment') == 1


@pytest.mark.parametrize('body', ['비활성', 'Inactive', '활성화하려면 누르세요', '예약 해제', '활성\n예약'])
def test_inactive_or_ambiguous_automation_is_not_saved_success(body):
    from hotpost.monetization_browser import automation_status
    with pytest.raises(ValueError): automation_status(body)


@pytest.fixture
def local_composer(tmp_path, monkeypatch):
    """Isolated headless Chromium; no user profile or external network."""
    from playwright.sync_api import sync_playwright
    from hotpost.config import Settings
    from hotpost.monetization_browser import MonetizationBrowser
    from hotpost import instagram_publish_browser, monetization_browser
    monkeypatch.setattr(instagram_publish_browser, 'request_pause', lambda: None)
    monkeypatch.setattr(monetization_browser, 'request_pause', lambda: None)
    with sync_playwright() as playwright:
        from pathlib import Path
        from hotpost.source_browser_runtime import chrome_executable
        executable = playwright.chromium.executable_path
        if not Path(executable).is_file(): executable = chrome_executable()
        chrome = playwright.chromium.launch(headless=True, executable_path=executable)
        try:
            context = chrome.new_context()
            context.route('**/*', lambda route: route.abort())
            page = context.new_page()
            page.set_content('''<a href="/ouraccount/">Profile</a>
<button onclick="document.querySelector('[role=dialog]').hidden=false">Create</button>
<div role="dialog" hidden>
<input type="file" accept="image/png,video/mp4" onchange="window.videoName=this.files[0].name;document.querySelector('video').hidden=false">
<video hidden style="width:100px;height:100px"></video>
<div id="editor" hidden><button onclick="document.querySelector('#cover').hidden=false">Select cover photo</button>
<input id="cover" type="file" accept="image/png" hidden onchange="window.coverName=this.files[0].name"></div>
<button id="next" onclick="if(!window.editing){window.editing=true;document.querySelector('#editor').hidden=false}
else {this.hidden=true;document.querySelector('#caption-stage').hidden=false}">Next</button>
<div id="caption-stage" hidden><span>ouraccount</span><textarea aria-label="Caption"></textarea>
<button id="share" onclick="window.shareCount=(window.shareCount||0)+1;window.sentCaption=document.querySelector('textarea').value;
document.querySelector('[role=dialog]').innerHTML='<p>Your post has been shared</p><a href=&quot;https://www.instagram.com/reel/OurPost/&quot;>Post</a>'">Share</button></div></div>''')
            automation = context.new_page()
            automation.set_content('<button aria-pressed="true">다음에 올릴게시물을 자동화할게요</button>')
            adapter = MonetizationBrowser(Settings(data_dir=tmp_path))
            adapter.session = lambda *_: nullcontext(context)
            adapter.page = lambda *_: page
            adapter._open_saved_automation = lambda *_: automation
            yield adapter, page
        finally:
            chrome.close()


def test_visible_composer_uploads_bound_files_and_exact_caption_once(tmp_path, local_composer):
    service, _, _, _ = ready_service(tmp_path)
    adapter, page = local_composer
    state = service.store.get('work-1')
    phases = []
    result = adapter.publish_instagram(state, tmp_path / 'ui', lambda phase, *_: phases.append(phase))
    assert result['submitted'] is True and result['media_verified'] is False
    assert result['post_url'] == 'https://www.instagram.com/reel/OurPost/'
    assert page.evaluate('window.shareCount') == 1
    assert page.evaluate('window.videoName') == 'video.mp4'
    assert page.evaluate('window.coverName') == 'cover.png'
    assert page.evaluate('window.sentCaption') == state['package']['caption']
    assert phases == ['uploading', 'submitting', 'platform_processing']


def test_visible_composer_rechecks_files_before_share(tmp_path, local_composer):
    service, _, cover, _ = ready_service(tmp_path)
    adapter, page = local_composer
    def progress(phase, *_):
        if phase == 'uploading': cover.write_bytes(b'changed during upload')
    with pytest.raises(ValueError):
        adapter.publish_instagram(service.store.get('work-1'), tmp_path / 'ui', progress)
    assert page.evaluate('window.shareCount || 0') == 0


def test_concurrent_publication_cannot_click_share_twice(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    service, calls, _, _ = ready_service(tmp_path)
    def publish(_):
        try:
            return service.publish('work-1', background=False)
        except MonetizationConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(publish, range(2)))
    assert len([row for row in calls if row[0] == 'share']) == 1


def test_late_upload_progress_cannot_write_another_effect(tmp_path):
    import uuid
    service, _, _, _ = ready_service(tmp_path)
    state = service.store.get('work-1')
    effect = service.store.reserve_effect(state, 'instagram_publish', {})
    with pytest.raises(MonetizationConflict):
        service.store.publish_progress('work-1', uuid.uuid4().hex, 'submitting')
    service.store.publish_progress('work-1', effect, 'submitting')
    assert service.store.get('work-1')['publication']['phase'] == 'submitting'


@pytest.mark.parametrize('supported', [True, False])
def test_followup_screen_only_publishes_on_click_and_with_supported_backend(tmp_path, local_composer, supported):
    import json
    from pathlib import Path
    service, _, _, _ = ready_service(tmp_path)
    state = service.get('work-1')
    _, page = local_composer
    web = Path(__file__).resolve().parents[1] / 'web'
    posts = []
    def handle(route):
        request = route.request
        path = request.url.split('test.invalid', 1)[-1].split('?')[0]
        if request.method == 'POST':
            posts.append(path)
            state['effects'].append({'kind': 'instagram_publish', 'status': 'dispatching'})
            state['worker_live'] = True
            data = {'accepted': True}
        elif path == '/api/monetization/connections':
            data = {'coupang': {'configured': True}, 'existing_browser_connected': True,
                    'automation': {'enabled': False, 'account': 'ouraccount'}, 'publication_supported': supported,
                    'automatic_inputs_supported': True, 'comment_keyword': '나도'}
        elif path == '/api/monetization/inputs':
            data = {'tasks': [{'id': 'work-1', 'title': '손난로', 'shortcode': 'Reference', 'keyword': '나도', 'comment_mode': 'fixed', 'keyword_error': ''}],
                    'selected_task_id': 'work-1', 'account': 'ouraccount', 'selection_error': ''}
        elif path == '/api/monetization/work-1':
            data = {'state': state}
        elif path.endswith('/monetization.js'):
            return route.fulfill(status=200, content_type='application/javascript', body=(web/'monetization.js').read_text('utf-8'))
        elif path.endswith('/monetization.html'):
            return route.fulfill(status=200, content_type='text/html', body=(web/'monetization.html').read_text('utf-8'))
        else:
            return route.fulfill(status=200, body='')
        route.fulfill(status=200, content_type='application/json', body=json.dumps(data))
    page.route('**/*', handle)
    page.goto('https://test.invalid/monetization.html?task=work-1')
    page.get_by_role('heading', name='게시글 본문', exact=True).wait_for()
    assert posts == []
    if supported:
        page.locator('[data-publish]').click()
        page.wait_for_function('!document.querySelector("[data-publish]")')
        assert posts == ['/api/monetization/work-1/publish']
    else:
        assert page.locator('[data-publish]').count() == 0
        assert '운영 적용을 기다리고' in page.locator('#result').inner_text()
