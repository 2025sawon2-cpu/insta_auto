"""The selected completed video uses the saved account and fixed '나도' comment."""
import copy
from io import BytesIO
import json
import sqlite3
from types import SimpleNamespace

import pytest

from hotpost.monetization_store import MonetizationStore
from hotpost.monetization_http import MonetizationHTTP
from test_monetization import followup_fixture
from test_instagram_publish import local_composer


def input_fixture(tmp_path, caption='댓글에 “키티” 남겨주세요'):
    service, calls, video, _ = followup_fixture(tmp_path)
    service.store.configure_automation(False, '@OurAccount')
    path = tmp_path / 'studio/studio.sqlite3'
    path.parent.mkdir()
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE tasks(id TEXT,shortcode TEXT,state TEXT,updated REAL)')
        db.execute('INSERT INTO tasks VALUES(?,?,?,?)', ('work-1', 'Reference', json.dumps({**video, 'title': '거울 손난로'}), 1))
    with sqlite3.connect(service.settings.db_path) as db:
        db.execute('CREATE TABLE posts(shortcode TEXT,caption TEXT)')
        db.execute('INSERT INTO posts VALUES(?,?)', ('Reference', caption))
    return service, calls, video


def test_page_automatically_selects_finished_video_and_fixed_comment_without_writes(tmp_path):
    service, calls, _ = input_fixture(tmp_path)
    before = service.store.get('work-1')
    result = service.inputs()
    assert result['selected_task_id'] == 'work-1'
    assert result['tasks'][0]['title'] == '거울 손난로'
    assert result['tasks'][0]['keyword'] == '나도'
    assert result['tasks'][0]['comment_mode'] == 'fixed'
    assert result['account'] == 'ouraccount'
    assert service.store.get('work-1') == before is None
    assert calls == []


def test_saved_account_and_keyword_are_used_without_manual_inputs(tmp_path):
    service, calls, _ = input_fixture(tmp_path)
    assert MonetizationStore(service.store.root).automation() == {'enabled': False, 'account': 'ouraccount'}
    service.run_saved('work-1'); service.close()
    assert ('comment', '나도') in calls
    assert ('comment', '키티') not in calls
    assert service.get('work-1')['account'] == 'ouraccount'
    assert service.get('work-1')['stage'] == 'awaiting_post'


@pytest.mark.parametrize('caption', ['댓글에 “키티” 남겨주세요', '아무 댓글이나 남겨주세요',
    '댓글 남겨주세요', '댓글에 “키티” 또는 댓글에 “다른말” 남겨주세요'])
def test_original_caption_never_changes_the_fixed_comment(tmp_path, caption):
    service, calls, _ = input_fixture(tmp_path, caption)
    item = service.inputs()['tasks'][0]
    assert item['comment_mode'] == 'fixed' and item['keyword'] == '나도'
    service.run_saved('work-1'); service.close()
    assert ('comment', '나도') in calls


def test_original_keyword_database_is_not_needed_or_read(tmp_path, monkeypatch):
    service, calls, _ = input_fixture(tmp_path)
    monkeypatch.setattr(type(service.settings), 'db_path', property(lambda _: tmp_path/'never-created.db'))
    assert service.inputs()['tasks'][0]['keyword'] == '나도'
    service.run_saved('work-1'); service.close()
    assert ('comment', '나도') in calls and not service.settings.db_path.exists()


def test_saved_account_is_required_without_guessing_an_existing_account(tmp_path):
    service, calls, _, _ = followup_fixture(tmp_path)
    with pytest.raises(ValueError, match='한 번 저장'): service.run_saved('work-1')
    assert calls == []


def test_deep_link_and_account_reservation_are_preferred_over_newer_video(tmp_path):
    service, _, video = input_fixture(tmp_path)
    other = copy.deepcopy(video)
    other.update(id='work-2', shortcode='Other', title='다른 영상')
    with sqlite3.connect(tmp_path/'studio/studio.sqlite3') as db:
        db.execute('INSERT INTO tasks VALUES(?,?,?,?)', ('work-2', 'Other', json.dumps(other), 2))
    assert service.inputs()['selected_task_id'] == 'work-2'
    assert service.inputs('work-1')['selected_task_id'] == 'work-1'
    state = service.prepare('work-1', 'ouraccount')
    service.store.reserve_next_post(state)
    assert service.inputs()['selected_task_id'] == 'work-1'
    assert service.inputs('missing')['selected_task_id'] == ''
    assert service.inputs('missing')['selection_error']


def test_task_discovery_is_bounded_and_explicit_link_can_recover_older_video(tmp_path):
    service, _, video = input_fixture(tmp_path)
    with sqlite3.connect(tmp_path/'studio/studio.sqlite3') as db:
        for i in range(60):
            state = {**video, 'id': f'work-extra-{i}', 'shortcode': f'Extra{i}', 'title': f'영상 {i}'}
            db.execute('INSERT INTO tasks VALUES(?,?,?,?)', (state['id'], state['shortcode'], json.dumps(state), i+2))
    assert len(service.inputs()['tasks']) == 50
    explicit = service.inputs('work-1')
    assert len(explicit['tasks']) == 51 and explicit['selected_task_id'] == 'work-1'


def test_incomplete_or_paused_videos_are_not_selected(tmp_path):
    service, _, video = input_fixture(tmp_path)
    with sqlite3.connect(tmp_path/'studio/studio.sqlite3') as db:
        for i, state in enumerate([{**video, 'status': 'preparing'}, {**video, 'automation': {'paused_by_user': True}}]):
            db.execute('INSERT INTO tasks VALUES(?,?,?,?)', (f'bad-{i}', f'Bad{i}', json.dumps(state), i+10))
    assert [row['id'] for row in service.inputs()['tasks']] == ['work-1']


def test_resume_after_product_discovery_does_not_require_resending_comment_keyword(tmp_path):
    service, calls, _ = input_fixture(tmp_path)
    service.prepare('work-1', 'ouraccount')
    service.discover_product('work-1', '키티', background=False)
    with sqlite3.connect(service.settings.db_path) as db: db.execute('DELETE FROM posts')
    service.run_saved('work-1'); service.close()
    assert [row for row in calls if row[0]=='comment'] == [('comment', '나도')]
    assert service.get('work-1')['stage'] == 'awaiting_post'


def test_http_run_ignores_caller_account_and_keyword_and_resolves_on_server():
    calls = []
    class Handler(MonetizationHTTP):
        path = '/api/monetization/work-1/run'
        body = json.dumps({'account': 'wrong-account', 'keyword': 'wrong-keyword'}).encode()
        headers = {'Content-Type': 'application/json', 'Content-Length': str(len(body))}
        rfile = BytesIO(body)
        def _json(self, result, status=200): self.result = result, status
    service = SimpleNamespace(run_saved=lambda task: calls.append(task) or {'accepted': True})
    handler = Handler()
    handler.monetization_request(service, mutation=True)
    assert calls == ['work-1'] and handler.result == ({'accepted': True}, 200)


def test_screen_populates_task_and_keyword_and_reuses_saved_account_on_reload(tmp_path, local_composer):
    from pathlib import Path
    from urllib.parse import urlsplit, parse_qs
    service, calls, _ = input_fixture(tmp_path)
    _, page = local_composer
    web = Path(__file__).resolve().parents[1] / 'web'
    posts = []
    credentials_ready = False
    def handle(route):
        nonlocal credentials_ready
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if request.method == 'POST':
            posts.append((path, request.post_data_json))
            if path.endswith('/automation'):
                body = request.post_data_json
                result = service.store.configure_automation(body['enabled'], body['account'])
            elif path.endswith('/connections'):
                result = service.credentials.save(request.post_data_json)
                credentials_ready = True
            else:
                result = service.run_saved('work-1')
        elif path.endswith('/connections'):
            result = service.connections()
            if not credentials_ready:
                result['coupang'] = {'configured': False, 'eligible': False, 'account_ref': ''}
        elif path.endswith('/inputs'):
            result = service.inputs(parse_qs(parsed.query).get('task', [''])[0])
        elif path.endswith('/preview'):
            result = service.preview('work-1')
        elif path == '/api/monetization/work-1':
            result = {'state': service.get('work-1')}
        elif path in ('/monetization.js', '/coupang-settings.js'):
            return route.fulfill(status=200, content_type='application/javascript', body=(web/path[1:]).read_text('utf-8'))
        elif path in ('/monetization.html', '/settings.html'):
            return route.fulfill(status=200, content_type='text/html', body=(web/path[1:]).read_text('utf-8'))
        else:
            return route.fulfill(status=200, body='')
        route.fulfill(status=200, content_type='application/json', body=json.dumps(result))
    page.route('**/*', handle)
    page.goto('https://test.invalid/monetization.html')
    page.wait_for_function('document.querySelector("#work select").value === "work-1" && document.querySelector("#automation input[name=account]").value === "ouraccount"')
    assert page.locator('#work select[name=task]').input_value() == 'work-1'
    assert page.locator('#work input').count() == 0
    assert page.locator('#automation input[name=account]').input_value() == 'ouraccount'
    assert posts == [] and calls == []
    assert page.locator('input[name=access_key], input[name=secret_key]').count() == 0
    assert page.locator('#coupang-setup-notice').is_visible()
    assert page.locator('#work button[type=submit]').is_disabled()
    page.get_by_role('link', name='쿠팡파트너스 API 설정 바로가기').click()
    page.wait_for_url('**/settings.html#coupang-partners')
    form = page.locator('#coupang-credentials')
    form.locator('[name=account_ref]').fill('fixture-account')
    form.locator('[name=access_key]').fill('fixture-access')
    form.locator('[name=secret_key]').fill('fixture-secret')
    form.locator('[name=eligible]').check()
    form.get_by_role('button', name='API 연결 저장').click()
    page.wait_for_function('document.querySelector("#coupang-status").textContent.includes("입력한 키는 화면에서 지웠습니다")')
    assert form.locator('[name=access_key]').input_value() == ''
    assert form.locator('[name=secret_key]').input_value() == ''
    assert len(posts) == 1 and posts[0][0] == '/api/monetization/connections' and calls == []
    page.goto('https://test.invalid/monetization.html?task=work-1')
    page.wait_for_function('document.querySelector("#work select").value === "work-1" && !document.querySelector("#work button[type=submit]").disabled')
    assert page.locator('#coupang-setup-notice').is_hidden()
    page.locator('#automation input[name=account]').fill('@SavedAccount')
    page.locator('#automation button').click()
    page.wait_for_function('document.querySelector("#saved-account").textContent.includes("savedaccount")')
    page.reload()
    page.wait_for_function('document.querySelector("#work select").value === "work-1" && document.querySelector("#automation input[name=account]").value === "savedaccount"')
    assert page.locator('#automation input[name=account]').input_value() == 'savedaccount'
    assert len(posts) == 2
    page.locator('#work button[type=submit]').click()
    try:
        page.wait_for_function('document.querySelector("#result").textContent.includes("게시글 본문")', timeout=10000)
    except Exception:
        print('UI diagnostic:', page.locator('#message').inner_text(), page.locator('#result').inner_text(), calls, service.get('work-1'))
        raise
    service.close()
    assert posts[-1] == ('/api/monetization/work-1/run', {})
    assert ('comment', '나도') in calls
    assert service.get('work-1')['account'] == 'savedaccount'


def test_preview_verifies_real_files_and_saved_account_without_preparing_or_sending(tmp_path):
    service, calls, _ = input_fixture(tmp_path)
    result = service.preview('work-1')
    assert result['verified'] and result['video_verified'] and result['account_matches']
    assert result['task_id'] == 'work-1' and result['keyword'] == '나도'
    assert result['account'] == result['execution_account'] == 'ouraccount'
    assert result['binding']['video_sha256']
    assert result['external_effects_started'] is False
    assert service.store.get('work-1') is None and calls == []


def test_preview_distinguishes_existing_binding_from_a_different_saved_account(tmp_path):
    service, calls, _ = input_fixture(tmp_path)
    service.prepare('work-1', 'ouraccount')
    service.store.configure_automation(False, 'differentaccount')
    result = service.preview('work-1')
    assert result['video_verified'] and not result['verified']
    assert result['account'] == 'differentaccount' and result['execution_account'] == 'ouraccount'
    assert result['reason'] and calls == []


def test_preview_does_not_claim_account_connection_when_nothing_is_saved(tmp_path):
    service, calls, _, _ = followup_fixture(tmp_path)
    result = service.preview('work-1')
    assert result['video_verified'] and not result['verified']
    assert not result['account_matches'] and not result['account']
    assert result['reason'] and calls == []
