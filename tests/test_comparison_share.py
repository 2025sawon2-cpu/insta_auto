import threading
from types import SimpleNamespace

import requests
import pytest
from hotpost.comparison_share import server_for, build_comparison


def test_public_allowlist_range_and_download(tmp_path):
    video = tmp_path / 'final.mp4'
    video.write_bytes(b'0123456789')
    index = tmp_path / 'index.html'
    index.write_text('<h1>comparison</h1>')
    server = server_for({'/': index, '/final.mp4': video}, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:' + str(server.server_port)
    try:
        assert requests.get(base + '/').headers['Content-Type'] == 'text/html; charset=utf-8'
        r = requests.get(base + '/final.mp4', headers={'Range': 'bytes=2-5'})
        assert r.status_code == 206 and r.content == b'2345'
        assert r.headers['Content-Range'] == 'bytes 2-5/10'
        assert r.headers['Accept-Ranges'] == 'bytes'
        r = requests.get(base + '/final.mp4', headers={'Range': 'bytes=-3'})
        assert r.status_code == 206 and r.content == b'789'
        for invalid in ['bytes=10-', 'bytes=0-1,3-4']:
            assert requests.get(base + '/final.mp4', headers={'Range': invalid}).status_code == 416
        r = requests.head(base + '/final.mp4?download=1')
        assert r.status_code == 200 and r.content == b''
        assert r.headers['Content-Disposition'] == 'attachment; filename="final.mp4"'
        for path in ['/api/studio', '/share_manifest.json', '/../secret.json', '/%2e%2e/secret.json']:
            assert requests.get(base + path).status_code == 404
        assert requests.post(base + '/').status_code == 405
    finally:
        server.shutdown()
        server.server_close()


def test_unfinished_task_cannot_be_published(tmp_path):
    studio = SimpleNamespace(store=SimpleNamespace(list=lambda: [
        {'shortcode': 'wanted', 'status': 'source_wait', 'edits': []}]),
        settings=SimpleNamespace(data_dir=tmp_path))
    with pytest.raises(ValueError, match='검증된 완성 영상'):
        build_comparison(studio, ['wanted'])
    assert not (tmp_path / 'public_comparisons').exists()


def test_same_edit_id_changed_media_creates_new_content_snapshot_and_old_snapshot_survives(tmp_path):
    original = tmp_path/'original.mp4'; original.write_bytes(b'original')
    video = tmp_path/'final.mp4'; video.write_bytes(b'old')
    state = {'shortcode':'wanted','title':'product','status':'completed','reference_video':str(original),
             'edit_id':'edit','edits':[{'id':'edit','export_verified':True,'export_path':str(video)}]}
    studio = SimpleNamespace(store=SimpleNamespace(list=lambda:[state]),settings=SimpleNamespace(data_dir=tmp_path))
    first, _ = build_comparison(studio, ['wanted'])
    video.write_bytes(b'new')
    second, _ = build_comparison(studio, ['wanted'])
    assert first != second
    assert (first/'wanted-final.mp4').read_bytes() == b'old'
    assert (second/'wanted-final.mp4').read_bytes() == b'new'


def test_daily_completed_share_requires_pass_bound_to_exact_video_and_plan(tmp_path):
    from hotpost.daily_quality import POLICY
    from hotpost.production import file_digest
    original = tmp_path/'original.mp4'; original.write_bytes(b'original')
    video = tmp_path/'final.mp4'; video.write_bytes(b'video')
    plan = tmp_path/'plan.json'; plan.write_text('{}')
    edit = {'id':'edit','export_verified':True,'export_path':str(video),'plan_path':str(plan),'quality_verified':True}
    receipt = {'edit_id':'edit','passed':True,'render_sha256':file_digest(video),'plan_sha256':file_digest(plan)}
    state = {'shortcode':'wanted','title':'product','status':'completed','reference_video':str(original),
             'edit_id':'edit','edits':[edit], 'daily_quality':{'policy':POLICY,'status':'passed',
                 'reviewed_edit_id':'edit','reviews':[receipt]}}
    studio = SimpleNamespace(store=SimpleNamespace(list=lambda:[state]),settings=SimpleNamespace(data_dir=tmp_path))
    first, _ = build_comparison(studio, ['wanted'])
    video.write_bytes(b'changed after pass')
    with pytest.raises(ValueError,match='품질 검수'):
        build_comparison(studio, ['wanted'])
    assert (first/'wanted-final.mp4').read_bytes() == b'video'


def test_gallery_left_final_right_and_private_manifest_is_not_public(tmp_path):
    image = tmp_path / 'photo.jpg'
    image.write_bytes(b'image')
    final = tmp_path / 'finished.mp4'
    final.write_bytes(b'video')
    state = {'shortcode': 'wanted', 'title': '상품 <비교>', 'status': 'completed',
        'creation_mode': 'photo_post', 'reference_images': [str(image)], 'edit_id': 'edit-1',
        'edits': [{'id': 'edit-1', 'export_verified': True, 'export_path': str(final)}], 'sources': []}
    studio = SimpleNamespace(store=SimpleNamespace(list=lambda: [state]),
        settings=SimpleNamespace(data_dir=tmp_path))
    root, assets = build_comparison(studio, ['wanted'])
    page = (root / 'index.html').read_text('utf-8')
    assert page.index('<h3>원본</h3>') < page.index('<h3>완성본</h3>')
    assert '상품 &lt;비교&gt;' in page
    assert '/share_manifest.json' not in assets
    assert all(p.parent == root for p in assets.values())


def test_verified_illustrative_draft_requires_explicit_review_scope(tmp_path):
    original = tmp_path / 'original.mp4'
    original.write_bytes(b'original')
    final = tmp_path / 'draft.mp4'
    final.write_bytes(b'draft')
    edit = {'id': 'review-1', 'export_verified': True, 'export_path': str(final),
            'review_draft': True, 'source_coverage_complete': False}
    state = {'shortcode': 'wanted', 'title': '예시', 'status': 'draft_review',
             'reference_video': str(original), 'edit_id': edit['id'], 'edits': [edit]}
    studio = SimpleNamespace(store=SimpleNamespace(list=lambda: [state]),
                             settings=SimpleNamespace(data_dir=tmp_path))
    with pytest.raises(ValueError):
        build_comparison(studio, ['wanted'])
    root, _ = build_comparison(studio, ['wanted'], review_codes=['wanted'])
    assert '활용 예시본 · 동일 제품 미확보' in (root / 'index.html').read_text('utf-8')
    assert state['status'] == 'draft_review'
    edit['export_verified'] = False
    with pytest.raises(ValueError):
        build_comparison(studio, ['wanted'], review_codes=['wanted'])


@pytest.mark.parametrize('coverage', [None, True])
def test_verified_quality_review_does_not_require_incomplete_source_claim(tmp_path, coverage):
    original = tmp_path / 'original.mp4'
    original.write_bytes(b'original')
    final = tmp_path / 'draft.mp4'
    final.write_bytes(b'draft')
    edit = {'id': 'quality-review', 'export_verified': True, 'export_path': str(final),
            'review_draft': True, 'source_coverage_complete': coverage}
    state = {'shortcode': 'wanted', 'title': '품질 검토', 'status': 'draft_review',
             'reference_video': str(original), 'edit_id': edit['id'], 'edits': [edit]}
    studio = SimpleNamespace(store=SimpleNamespace(list=lambda: [state]),
                             settings=SimpleNamespace(data_dir=tmp_path))
    with pytest.raises(ValueError):
        build_comparison(studio, ['wanted'])
    root, _ = build_comparison(studio, ['wanted'], review_codes=['wanted'])
    page = (root / 'index.html').read_text('utf-8')
    assert '<h3>재작업 검토본</h3>' in page
    assert '동일 제품 미확보' not in page
    state['status'] = 'source_wait'
    with pytest.raises(ValueError):
        build_comparison(studio, ['wanted'], review_codes=['wanted'])
