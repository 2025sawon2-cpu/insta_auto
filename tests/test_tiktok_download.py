from hotpost.tiktok_download import complete_media_response
from hotpost.tiktok_download import MediaAssembly, item_media_urls
import pytest
from types import SimpleNamespace


def test_full_mp4_response_and_whole_file_range_are_accepted():
    assert complete_media_response(200, {'content-type': 'video/mp4', 'content-length': '100'}, 100)
    assert complete_media_response(206, {'content-type': 'video/mp4', 'content-range': 'bytes 0-99/100'}, 100)


def test_partial_or_truncated_media_cannot_be_saved_as_complete_video():
    assert not complete_media_response(200, {'content-type': 'video/mp4', 'content-length': '100'}, 50)
    assert not complete_media_response(206, {'content-type': 'video/mp4', 'content-range': 'bytes 0-49/100'}, 50)
    assert not complete_media_response(206, {'content-type': 'video/mp4', 'content-range': 'bytes 50-99/100'}, 50)
    assert not complete_media_response(200, {'content-type': 'text/html'}, 100)


def test_saved_request_limit_stops_download_before_connecting(tmp_path, monkeypatch):
    from hotpost import tiktok_download as td, browser_search as bs
    from hotpost.config import Settings
    settings = Settings(data_dir=tmp_path)
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    bs.BrowserSearcher(settings, tmp_path)._block('tiktok', {}, 'rate_limited',
        SimpleNamespace(headers={'retry-after': '1200'}))
    monkeypatch.setattr(td, 'endpoint', lambda _: 'http://existing-browser')
    monkeypatch.setattr(td, 'attach_browser', lambda *args: pytest.fail('Must not access browser during cooldown'))
    with pytest.raises(RuntimeError, match='휴식 상태'):
        td.download(settings, 'https://www.tiktok.com/@fixture/video/123456789',
            tmp_path / 'blocked.mp4', 1024)
    assert not (tmp_path / 'blocked.mp4').exists()


def test_ranges_are_ordered_and_gaps_are_never_saved():
    media = MediaAssembly(100)
    headers = lambda value: {'content-type': 'video/mp4', 'content-range': value, 'etag': 'one'}
    assert media.add(206, headers('bytes 6-9/10'), b'6789')
    assert media.add(206, headers('bytes 0-3/10'), b'0123')
    assert media.result() is None
    assert media.add(206, headers('bytes 3-6/10'), b'3456')
    assert media.result() == b'0123456789'
    assert media.add(206, headers('bytes 0-3/10'), b'0123')
    assert media.result() == b'0123456789'


def test_changed_or_conflicting_chunks_are_rejected():
    media = MediaAssembly(100)
    h = {'content-type': 'video/mp4', 'content-range': 'bytes 0-3/10', 'etag': 'one'}
    media.add(206, h, b'0123')
    with pytest.raises(ValueError, match='내용'):
        media.add(206, h, b'XXXX')
    with pytest.raises(ValueError, match='버전'):
        media.add(206, {**h, 'etag': 'two'}, b'0123')
    assert media.result() is None


def test_oversize_and_bad_chunk_boundaries_are_rejected():
    media = MediaAssembly(10)
    h = {'content-type': 'video/mp4'}
    assert not media.add(206, {**h, 'content-range': 'bytes 0-3/11'}, b'0123')
    assert not media.add(206, {**h, 'content-range': 'bytes 8-11/10'}, b'0123')
    assert not media.add(206, {**h, 'content-range': 'bytes 0-3/10'}, b'012')
    assert not complete_media_response(200, {**h, 'content-length': 'invalid'}, 10)


def test_blob_metadata_binding_excludes_other_recommended_videos():
    value = {'items': [
        {'id': 'chosen', 'video': {'playAddr': 'https://cdn/chosen', 'bitrateInfo': [{'PlayAddr': {'UrlList': ['https://cdn/chosen-alt']}}]}},
        {'id': 'other', 'video': {'playAddr': 'https://cdn/other'}}]}
    assert item_media_urls(value, 'chosen') == {'https://cdn/chosen', 'https://cdn/chosen-alt'}


def test_audio_or_initialization_segment_never_replaces_video(tmp_path, monkeypatch):
    from hotpost import tiktok_download as td
    monkeypatch.setattr(td.shutil, 'which', lambda _: 'ffprobe')
    monkeypatch.setattr(td.subprocess, 'run', lambda *args, **kwargs:
        SimpleNamespace(returncode=0, stdout='{"format":{"duration":"88"},"streams":[{"codec_type":"audio"}]}'))
    target = tmp_path / 'video.mp4'
    target.write_bytes(b'preserved')
    assert not td.publish_video(b'initialization-only', target, 88)
    assert target.read_bytes() == b'preserved'
    assert not list(tmp_path.glob('*.receiving.mp4'))


def test_short_video_is_rejected_and_complete_video_is_published(tmp_path, monkeypatch):
    from hotpost import tiktok_download as td
    monkeypatch.setattr(td.shutil, 'which', lambda _: 'ffprobe')
    monkeypatch.setattr(td.subprocess, 'run', lambda *args, **kwargs:
        SimpleNamespace(returncode=0, stdout='{"format":{"duration":"88"},"streams":[{"codec_type":"video","width":720,"nb_read_packets":"2600"}]}'))
    monkeypatch.setattr(td, 'run_progress_command', lambda *args, **kwargs:
        SimpleNamespace(returncode=0, stdout='frame=2600\nout_time_us=88000000\nprogress=end\n'))
    target = tmp_path / 'video.mp4'
    assert not td.publish_video(b'shorter', target, 120)
    assert not target.exists()
    assert td.publish_video(b'complete', target, 88)
    assert target.read_bytes() == b'complete'
    assert not list(tmp_path.glob('*.receiving.mp4'))
def test_same_item_photo_redirect_is_distinct_from_user_navigation():
    from hotpost.tiktok_download import selected_photo_redirect
    assert selected_photo_redirect('https://www.tiktok.com/@name/photo/123?image_index=2','123')
    assert not selected_photo_redirect('https://www.tiktok.com/@name/photo/456','123')
    assert not selected_photo_redirect('https://example.com/@name/photo/123','123')
    assert not selected_photo_redirect('https://www.tiktok.com/@name/video/123','123')
