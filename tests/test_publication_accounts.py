from http.client import HTTPConnection
from contextlib import closing
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from hotpost.config import Settings
from hotpost.publication_server import PublicationServer, make_publication_handler


@pytest.fixture
def dashboard(tmp_path):
    settings = Settings(data_dir=tmp_path/'data', influencer_file=tmp_path/'accounts.txt', web_dir=tmp_path/'web')
    handler = make_publication_handler(settings, {'/api/accounts': {'accounts': [], 'count': 0},
                                                 '/api/collection-status': {'state': 'stopped'}})
    server = PublicationServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method, path, body=None, headers=None):
        with closing(HTTPConnection(*server.server_address, timeout=5)) as conn:
            payload = json.dumps(body, ensure_ascii=False).encode('utf8') if body is not None else None
            conn.request(method, path, payload, {'Content-Type': 'application/json', **(headers or {})})
            response = conn.getresponse()
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    yield request, settings
    server.shutdown()
    server.server_close()
    thread.join(3)


def test_account_add_is_persisted_and_visible_without_restart_or_snapshot_refresh(dashboard):
    request, settings = dashboard
    assert request('GET', '/api/accounts')[1]['count'] == 0
    status, body = request('POST', '/api/accounts', {'account': '@bongsallim', 'note': '살림'})
    assert status == 201 and body['created'] and body['account']['username'] == 'bongsallim'
    assert 'https://www.instagram.com/bongsallim/' in settings.influencer_file.read_text('utf8')
    status, body = request('GET', '/api/accounts?refresh=1')
    assert status == 200 and body['count'] == 1 and body['accounts'][0]['note'] == '살림'
    status, body = request('POST', '/api/accounts', {'account': 'https://www.instagram.com/bongsallim/', 'note': '수정'})
    assert status == 200 and not body['created']
    assert request('GET', '/api/accounts')[1]['count'] == 1
    assert request('DELETE', '/api/accounts/bongsallim')[0] == 200
    assert request('GET', '/api/accounts')[1]['count'] == 0


@pytest.mark.parametrize('body', [[], {'account': 'not a username'}, {'account': 1}, {'account': 'bongsallim', 'note': 'a'*201}])
def test_invalid_account_request_does_not_write_membership(dashboard, body):
    request, settings = dashboard
    assert request('POST', '/api/accounts', body)[0] == 400
    assert not settings.influencer_file.exists()


def test_cross_origin_write_and_other_mutations_stay_blocked(dashboard):
    request, settings = dashboard
    assert request('POST', '/api/accounts', {'account': 'bongsallim'}, {'Origin': 'https://unrelated.example'})[0] == 403
    assert not settings.influencer_file.exists()
    for method, path in [('POST', '/api/collect'), ('POST', '/api/studio'), ('POST', '/api/storage/cleanup'),
                         ('PUT', '/api/collection-settings'), ('DELETE', '/api/studio/task'), ('PATCH', '/api/accounts')]:
        assert request(method, path, {})[0] == 405
    assert request('GET', '/api/collection-status')[1] == {'state': 'stopped'}
    health = request('GET', '/api/health')[1]
    assert health['production_workers'] == health['collection_workers'] == 0


def test_conflicted_file_is_reported_without_replacing_it(dashboard):
    request, settings = dashboard
    request('POST', '/api/accounts', {'account': 'bongsallim'})
    settings.influencer_file.write_text('<<<<<<< HEAD\n', 'utf8')
    assert request('GET', '/api/accounts')[0] == 409
    assert request('POST', '/api/accounts', {'account': 'another'})[0] == 400
    assert settings.influencer_file.read_text('utf8') == '<<<<<<< HEAD\n'


def test_publication_draft_routes_keep_working_alongside_accounts(dashboard):
    request, _ = dashboard
    status, state = request('GET', '/api/post-preparations/example')
    assert status == 200 and state['revision'] == 0
    state['draft']['caption'] = '보존할 게시물 초안'
    status, saved = request('PUT', '/api/post-preparations/example',
                            {'revision': state['revision'], 'draft': state['draft']})
    assert status == 200 and saved['revision'] == 1
    assert request('GET', '/api/post-preparations/example')[1]['draft']['caption'] == '보존할 게시물 초안'
    assert request('POST', '/api/post-preparations/example/thumbnail', {'revision': 1})[0] == 400


def test_startup_does_not_import_retired_production_or_collection_runners():
    result = subprocess.run([sys.executable, '-c',
        "import sys; import hotpost.publication_server; "
        "assert not any(n in sys.modules for n in ('hotpost.server','hotpost.studio','hotpost.job_queue','hotpost.collector'))"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('method', ['GET', 'HEAD'])
def test_settings_entry_uses_existing_installation_page_without_legacy_apis(dashboard, method):
    request, settings = dashboard
    handler = make_publication_handler(settings)
    with PublicationServer(('127.0.0.1', 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with closing(HTTPConnection(*server.server_address, timeout=5)) as conn:
                conn.request(method, '/settings.html?from=main')
                response = conn.getresponse()
                assert response.status == 302
                assert response.getheader('Location') == '/setup.html'
                assert response.read() == b''
        finally:
            server.shutdown()
            thread.join(3)
    assert request('GET', '/api/installation')[0] == 200
    assert request('GET', '/api/criteria')[0] == 404
    assert request('PUT', '/api/criteria', {'values': {}})[0] == 405


def test_coupang_lookup_requires_explicit_post_and_rejects_cross_origin(dashboard, monkeypatch):
    from hotpost.post_preparation import PostPreparation
    calls = []
    def start(service, code, payload):
        calls.append((code, payload))
        return {'status': 'running', 'id': 'lookup'}
    monkeypatch.setattr(PostPreparation, 'start_coupang_link', start)
    request, _ = dashboard
    assert request('GET', '/api/post-preparations/post')[0] == 200
    assert calls == []
    assert request('POST', '/api/post-preparations/post/coupang-link', {},
                   {'Origin': 'https://unrelated.example'})[0] == 403
    assert calls == []
    status, result = request('POST', '/api/post-preparations/post/coupang-link', {'revision': 0})
    assert status == 202 and result['id'] == 'lookup'
    assert calls == [('post', {'revision': 0})]
    assert request('PUT', '/api/post-preparations/post/coupang-link', {})[0] == 404
    health = request('GET', '/api/health')[1]
    assert health['production_workers'] == health['collection_workers'] == 0


def test_completed_history_includes_old_completions_and_never_changes_registry(dashboard, monkeypatch):
    from hotpost.post_preparation import PostPreparation
    from hotpost.reference_registry import load
    request, settings = dashboard
    registry = load(settings.data_dir/'reference-status.json')
    for code, state, at, latest in [('old', 'completed', '2026-09-01T12:00:00+09:00', False),
                                    ('new', 'completed', '2026-10-30T12:00:00+09:00', True),
                                    ('missing', 'completed', '2026-10-25T12:00:00+09:00', False),
                                    ('blocked', 'blocked', '2026-10-31T12:00:00+09:00', True),
                                    ('working', 'in_progress', '2026-10-31T12:00:00+09:00', True)]:
        registry['posts'][code] = {'reference': {'username': 'creator', 'in_latest_report': latest},
                                   'production': {'state': state, 'updated_at': at}}
    path = settings.data_dir/'reference-status.json'
    path.write_text(json.dumps(registry), 'utf8')
    before = path.read_bytes()
    def source(self, code):
        return {'cover_text': '완성한 영상\n'+code, 'media_version': 'version1',
                'media': {'final': None if code == 'missing' else settings.data_dir/'final.mp4',
                          'cover': settings.data_dir/'cover.png'}}
    monkeypatch.setattr(PostPreparation, 'source', source)
    status, result = request('GET', '/api/completed-posts')
    assert status == 200
    assert [p['shortcode'] for p in result['posts']] == ['new', 'missing', 'old']
    assert result['posts'][1]['media']['final'] is None
    assert result['posts'][0]['media']['cover'] == '/api/post-preparations/new/media/cover?v=version1'
    assert str(settings.data_dir) not in json.dumps(result)
    assert path.read_bytes() == before
    assert request('POST', '/api/completed-posts', {})[0] == 405
    assert request('GET', '/api/health')[1]['production_workers'] == 0
