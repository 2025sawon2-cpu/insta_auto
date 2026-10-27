import json
import sqlite3
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests

from hotpost.post_preparation import PostPreparation, DraftConflict
from hotpost.post_preparation_http import PostPreparationHTTP
from hotpost.post_preparation_content import DM_MESSAGE


@pytest.fixture
def service(tmp_path):
    root = tmp_path / 'data'
    root.mkdir()
    from hotpost.installation_settings import save
    save(root,{'revision':0,'values':{'publication_accounts':['mr.salrim','__ariddaum__'],
        'discovery_account':'collector','storefront_url':'https://influencers.coupang.com/s/test',
        'collection':'Test collection'}})
    return PostPreparation(SimpleNamespace(data_dir=root))


def historical(service):
    root = service.root
    (root / 'studio').mkdir()
    final = root / 'finished.mp4'
    final.write_bytes(b'0123456789')
    plan = root / 'plan.json'
    plan.write_text(json.dumps({'cover_spec': {'lines': ['완성본의', '표지 문구']}}), 'utf8')
    state = {'script_id': 'new', 'scripts': [{'id': 'old', 'text': '아, 우리가 고친 대본이에요. 댓글에 ‘나도’ 남겨주세요.'},
                                         {'id': 'new', 'text': '아직 제작하지 않은 새 대본'}],
             'latest_completed_run_id': 'finished', 'reference_video': str(final),
             'runs': [{'id': 'finished', 'status': 'completed', 'artifacts': {'edit_id': 'edit-old'}},
                      {'id': 'new', 'status': 'failed', 'artifacts': {'edit_id': 'edit-new'}}],
             'edits': [{'id': 'edit-old', 'script_id': 'old', 'export_verified': True,
                        'export_path': str(final), 'plan_path': str(plan)},
                       {'id': 'edit-new', 'script_id': 'new', 'export_verified': False, 'preview_path': str(final)}]}
    with sqlite3.connect(root / 'studio/studio.sqlite3') as db:
        db.execute('CREATE TABLE tasks (shortcode TEXT, state TEXT)')
        db.execute('INSERT INTO tasks VALUES (?,?)', ('post', json.dumps(state)))
    return state


def test_finished_media_caption_and_cover_belong_to_same_completed_edit(service):
    state = historical(service)
    before = (service.root / 'studio/studio.sqlite3').read_bytes()
    data = service.get('post')
    assert data['source_run_id'] == 'finished'
    assert data['draft']['thumbnail_options']['recommended'] == '완성본의\n표지 문구'
    assert data['draft']['caption'].startswith('✨ 우리가 고친 대본이에요.')
    assert data['draft']['caption'].count('댓글에') == 1
    assert '새 대본' not in data['draft']['caption']
    assert data['draft']['product_link'] == ''
    assert data['media']['final'] == '/api/post-preparations/post/media/final'
    assert before == (service.root / 'studio/studio.sqlite3').read_bytes()
    assert state['scripts'][0]['text'].startswith('아,')


@pytest.mark.parametrize('change', ['valid', 'missing', 'invalid_json', 'invalid_type', 'video_hash', 'cover_hash',
                                   'video_path', 'cover_path', 'disclosure'])
def test_independent_delivery_receipt_allows_mobile_package_only_for_matching_media(service, change):
    import hashlib
    import shutil
    from hotpost.mobile_reels import ReelJobs
    from hotpost.reference_registry import SCHEMA_VERSION
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    video, cover, script, plan = [service.root / name for name in
                                 ('video.mp4', 'cover.png', 'script.txt', 'plan.json')]
    video.write_bytes(b'completed video'); cover.write_bytes(b'completed cover')
    script.write_text('침대 둘레를 누빔 텐트가 감싸요.', encoding='utf8')
    plan.write_text('{}', encoding='utf8')
    qa = service.root / 'qa.json'
    qa.write_text(json.dumps({'edit_id': 'completed-edit', 'artifacts': {
        key: {'path': str(path), 'sha256': sha(path)} for key, path in
        [('video', video), ('cover', cover), ('script', script), ('plan', plan)]}}), encoding='utf8')
    registry = service.root / 'reference-status.json'
    registry.write_text(json.dumps({'schema_version': SCHEMA_VERSION, 'posts': {'post': {'production': {
        'state': 'completed', 'run_id': 'completed-run', 'qa_evidence': str(qa),
        'final_sha256': sha(video)}}}}), encoding='utf8')
    receipt = {'schema_version': 1, 'disclosure': 'upper-right-gray-v1',
               'video': str(video), 'cover': str(cover), 'video_sha256': sha(video), 'cover_sha256': sha(cover)}
    if change in ('video_hash', 'cover_hash'):
        receipt[change.replace('_hash', '_sha256')] = '0' * 64
    elif change in ('video_path', 'cover_path'):
        receipt[change.replace('_path', '')] = str(script)
    elif change == 'disclosure':
        receipt['disclosure'] = 'unverified'
    if change != 'missing':
        (service.root / 'delivery-receipt.json').write_text(
            '{' if change == 'invalid_json' else '[]' if change == 'invalid_type' else json.dumps(receipt), encoding='utf8')
    before = {p: p.read_bytes() for p in (video, cover, qa, registry)}
    jobs = ReelJobs(service.root / 'mobile-jobs')
    if change == 'valid':
        result = jobs.prepare(service, 'post', 'mr.salrim', converter=lambda s, t: (shutil.copyfile(s, t) and {}))
        assert result['phase'] == 'prepared'
        assert result['package']['source_video_sha256'] == sha(video)
        assert result['package']['rules']['advertising_disclosure'] == 'upper-right-gray-v1'
    else:
        with pytest.raises(ValueError, match='광고'):
            jobs.prepare(service, 'post', 'mr.salrim')
    assert all(p.read_bytes() == content for p, content in before.items())


def test_drafts_persist_are_separate_and_reject_stale_save(service):
    draft = service.get('post')['draft']
    draft.update(selected_accounts=['__ariddaum__', 'mr.salrim'], caption='직접 수정한 내용', product_link='')
    result = service.save('post', {'revision': 0, 'draft': draft})
    assert result['revision'] == 1
    reopened = PostPreparation(SimpleNamespace(data_dir=service.root)).get('post')
    assert reopened['draft']['caption'] == '직접 수정한 내용'
    assert reopened['draft']['selected_accounts'] == ['mr.salrim', '__ariddaum__']
    assert service.get('another')['revision'] == 0
    with pytest.raises(DraftConflict):
        service.save('post', {'revision': 0, 'draft': draft})
    assert service.get('post')['revision'] == 1


def test_old_draft_is_hydrated_without_rewriting_or_losing_saved_fields(service):
    draft = service.get('DesTrP8SwOa')['draft']
    draft.pop('dm_message'); draft.pop('dm_button_text')
    draft.update(caption='내 본문', pinned_comment='내 댓글', product_link='https://example.com/item',
                 selected_accounts=['mr.salrim'], selected_thumbnail='hook')
    stored = json.dumps(draft, ensure_ascii=False)
    with service.connect() as db:
        db.execute('INSERT INTO drafts VALUES (?,?,?,?)', ('DesTrP8SwOa', 7, stored, 123))
    result = service.get('DesTrP8SwOa')
    assert result['revision'] == 7
    assert result['updated'] == 123
    assert all(result['draft'][key] == value for key, value in draft.items())
    assert result['draft']['dm_message'] == DM_MESSAGE
    assert '변기' in result['draft']['dm_button_text']
    with service.connect() as db:
        assert db.execute('SELECT value FROM drafts').fetchone()[0] == stored
    result['draft']['dm_button_text'] = '욕실 수납의 빈자리 찾기'
    service.save('DesTrP8SwOa', {'revision': 7, 'draft': result['draft']})
    # A previously opened old client may save old fields, but cannot erase the new hook.
    service.save('DesTrP8SwOa', {'revision': 8, 'draft': draft})
    assert service.get('DesTrP8SwOa')['draft']['dm_button_text'] == '욕실 수납의 빈자리 찾기'


@pytest.mark.parametrize('key,value', [('dm_button_text', '가'*21), ('dm_button_text', ''),
    ('dm_button_text', ' \t '), ('dm_button_text', '두\n줄'), ('dm_button_text', '끝줄\n'),
    ('dm_button_text', '줄\u2028바꿈'), ('dm_button_text', []), ('dm_message', '다른 안내')])
def test_invalid_dm_fields_never_change_saved_draft(service, key, value):
    draft = service.get('post')['draft']
    draft[key] = value
    with pytest.raises(ValueError):
        service.save('post', {'revision': 0, 'draft': draft})
    assert service.get('post')['revision'] == 0


def test_twenty_unicode_character_button_round_trips(service):
    draft = service.get('post')['draft']
    draft['dm_button_text'] = '가'*19 + '👇'
    service.save('post', {'revision': 0, 'draft': draft})
    assert service.get('post')['draft']['dm_button_text'] == draft['dm_button_text']


def test_caption_keeps_cta_sentence_together(service):
    draft = service.defaults('post', {'cover_text': '', 'script': '내 침대만 어둡게 해요. 이 침대 텐트가 궁금하면 댓글에 ‘꿀잠’ 남겨주세요.'})
    assert '💬 이 침대 텐트가 궁금하면 댓글에 "나도" 남겨주세요.' in draft['caption']
    assert draft['caption'].count('댓글에') == 1


@pytest.mark.parametrize('key,value', [('selected_accounts', ['unexpected']), ('caption', 'x'*2201),
                                    ('thumbnail_options', {'recommended': 'one only'}),
                                    ('selected_thumbnail', 'unknown'), ('product_link', [])])
def test_invalid_draft_never_changes_saved_value(service, key, value):
    draft = service.get('post')['draft']
    draft[key] = value
    with pytest.raises(ValueError):
        service.save('post', {'revision': 0, 'draft': draft})
    assert service.get('post')['revision'] == 0


def test_paths_outside_data_are_never_exposed(service, tmp_path):
    state = historical(service)
    outside = tmp_path / 'private.mp4'
    outside.write_bytes(b'secret')
    state['reference_video'] = str(outside)
    state['edits'][0]['export_path'] = str(outside)
    with sqlite3.connect(service.root / 'studio/studio.sqlite3') as db:
        db.execute('UPDATE tasks SET state=?', (json.dumps(state),))
    assert service.get('post')['media']['reference'] is None
    assert service.get('post')['media']['final'] is None
    with pytest.raises(FileNotFoundError):
        service.media('post', 'final')
    with pytest.raises(ValueError):
        service.get('../private')


@pytest.fixture
def endpoint(service):
    class Handler(PostPreparationHTTP, SimpleHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *_args):
            pass

        def _json(self, value, status=200):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.post_preparation_request(service):
                self.send_error(404)

        def do_PUT(self):
            if not self.post_preparation_request(service, write=True):
                self.send_error(405)

        def do_POST(self):
            if not self.post_preparation_request(service, thumbnail=True):
                self.send_error(405)

    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(service.root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    server.server_close()
    thread.join()


def test_http_saves_and_conflicts_without_upload_endpoint(service, endpoint):
    url = endpoint + '/api/post-preparations/post'
    draft = requests.get(url).json()['draft']
    payload = {'revision': 0, 'draft': draft}
    assert requests.put(url, json=payload).status_code == 200
    assert requests.put(url, json=payload).status_code == 409
    assert requests.put(url, json=payload, headers={'Origin': 'https://other.example'}).status_code == 403
    assert requests.put(url+'/upload', json=payload).status_code == 404
    assert requests.put(endpoint+'/api/studio', json={}).status_code == 405
    assert requests.get(url).json()['revision'] == 1
    with requests.Session() as session:
        assert session.put(url, json=payload, headers={'Origin': 'https://other.example'}).status_code == 403
        assert session.get(url).status_code == 200


def test_video_seeking_download_and_invalid_ranges(service, endpoint):
    historical(service)
    url = endpoint + '/api/post-preparations/post/media/final'
    response = requests.get(url, headers={'Range': 'bytes=3-6'})
    assert response.status_code == 206
    assert response.content == b'3456'
    assert response.headers['Content-Range'] == 'bytes 3-6/10'
    assert requests.get(url, headers={'Range': 'bytes=-2'}).content == b'89'
    assert requests.get(url, headers={'Range': 'bytes=80-90'}).status_code == 416
    assert requests.get(url, headers={'Range': 'bytes=0-1,4-5'}).status_code == 416
    assert 'attachment' in requests.get(url+'?download=1').headers['Content-Disposition']


def test_only_explicit_thumbnail_post_can_start_render(service, endpoint, monkeypatch):
    calls=[]
    def start(code,payload):
        calls.append((code,payload))
        return {'id':'test-job','status':'queued','message':'썸네일 준비 중'}
    monkeypatch.setattr(service,'start_thumbnail',start)
    url=endpoint+'/api/post-preparations/post/thumbnail'
    assert requests.get(url).status_code==404
    assert calls==[]
    assert requests.post(url,json={'revision':0},headers={'Origin':'https://unrelated.example'}).status_code==403
    assert calls==[]
    result=requests.post(url,json={'revision':0})
    assert result.status_code==202
    assert result.json()['status']=='queued'
    assert calls==[('post',{'revision':0})]
    assert requests.post(endpoint+'/api/post-preparations/post/upload',json={}).status_code==404
