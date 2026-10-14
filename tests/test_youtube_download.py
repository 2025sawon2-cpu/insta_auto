import json
from types import SimpleNamespace
import pytest

from hotpost import youtube_download as yd


def test_no_total_playback_deadline_allocator_remains():
    assert not hasattr(yd,'playback_deadline')


def test_final_buffer_is_only_permission_to_verify_not_a_download_approval():
    assert not yd.final_buffer_observed({'duration': 129, 'buffered_end': 55, 'ended': False})
    assert yd.final_buffer_observed({'duration': 129, 'buffered_end': 128.99, 'ended': False})
    assert yd.final_buffer_observed({'duration': 129, 'buffered_end': 0, 'ended': True})
    assert not yd.final_buffer_observed({'duration': 17, 'buffered_end': 17, 'ended': True, 'ad': True})


def test_video_identity_accepts_detail_urls_and_rejects_foreign_hosts_or_playlists():
    for url in ('https://www.youtube.com/watch?v=E2vmIs5gmTc&list=abc',
                'https://youtu.be/E2vmIs5gmTc', 'https://www.youtube.com/shorts/E2vmIs5gmTc'):
        assert yd.video_id(url) == 'E2vmIs5gmTc'
    for url in ('https://youtube.com.attacker/shorts/E2vmIs5gmTc',
                'https://www.youtube.com/results?search_query=E2vmIs5gmTc',
                'https://www.youtube.com/playlist?list=E2vmIs5gmTc'):
        assert yd.video_id(url) is None


def test_ranges_share_stream_but_different_formats_and_versions_never_do():
    assert yd.stream_key('https://r.googlevideo.com/v?itag=398&range=0-10&version=1') == yd.stream_key('https://r.googlevideo.com/v?itag=398&range=11-20&version=1')
    assert yd.stream_key('https://r.googlevideo.com/v?itag=398&version=1') != yd.stream_key('https://r.googlevideo.com/v?itag=399&version=1')
    assert yd.stream_key('https://r.googlevideo.com/v?itag=398&version=1') != yd.stream_key('https://r.googlevideo.com/v?itag=398&version=2')


def test_saved_auth_or_rate_limit_stops_before_browser_connection(tmp_path, monkeypatch):
    from hotpost import browser_search as bs
    from hotpost.config import Settings
    settings = Settings(data_dir=tmp_path)
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    bs.BrowserSearcher(settings, tmp_path)._block('youtube', {}, 'rate_limited',
        SimpleNamespace(headers={'retry-after': '1200'}))
    monkeypatch.setattr(yd, 'attach_browser', lambda *args: pytest.fail('No browser access during cooldown'))
    with pytest.raises(RuntimeError, match='휴식 상태'):
        yd.download(settings, 'https://www.youtube.com/shorts/E2vmIs5gmTc', tmp_path/'blocked.mp4', 1024)


@pytest.mark.parametrize('dimensions,decode_ok,expected', [((720,1280),True,True), ((1280,720),True,False), ((720,1280),False,False)])
def test_publication_requires_player_dimensions_and_full_decode(tmp_path, monkeypatch, dimensions, decode_ok, expected):
    target = tmp_path/'candidate.mp4'
    def receive(body, staging, duration):
        staging.write_bytes(body)
        return True
    def run(command, **kwargs):
        if '-show_entries' in command:
            return SimpleNamespace(stdout=json.dumps({'streams':[{'codec_type':'video','width':dimensions[0],'height':dimensions[1]}]}))
        if not decode_ok:
            raise yd.subprocess.CalledProcessError(1, command)
        return SimpleNamespace(returncode=0, stdout='frame=300\nout_time_us=10000000\nprogress=end\n')
    monkeypatch.setattr(yd, 'publish_video', receive)
    monkeypatch.setattr(yd.subprocess, 'run', run)
    monkeypatch.setattr(yd, 'run_progress_command', run)
    result = yd.publish_track(b'actual-received-body', target, {'duration':10,'width':720,'height':1280})
    assert bool(result) == expected
    assert target.exists() == expected
    assert not list(tmp_path.glob('*reception.mp4'))


def test_full_container_duration_and_clean_exit_cannot_approve_incomplete_fragments(tmp_path, monkeypatch):
    target = tmp_path/'candidate.mp4'
    def receive(body, staging, duration):
        assert duration == 33.161
        staging.write_bytes(body)
        return True  # The real truncated init also declares 33.1 seconds.
    def run(command, **kwargs):
        if '-show_entries' in command:
            return SimpleNamespace(stdout=json.dumps({'streams':[{'codec_type':'video', 'width':720,'height':1280}]}))
        return SimpleNamespace(returncode=0, stdout='frame=634\nout_time_us=21133333\nprogress=end\n')
    monkeypatch.setattr(yd, 'publish_video', receive)
    monkeypatch.setattr(yd.subprocess, 'run', run)
    monkeypatch.setattr(yd, 'run_progress_command', run)
    assert not yd.publish_track(b'incomplete-fragments', target, {'duration':33.161,'width':720,'height':1280})
    assert not target.exists() and not list(tmp_path.glob('*reception.mp4'))


def test_existing_source_is_never_overwritten(tmp_path):
    target = tmp_path/'candidate.mp4'
    target.write_bytes(b'preserved')
    with pytest.raises(RuntimeError, match='preserved'):
        yd.publish_track(b'new', target, {'duration':10,'width':720,'height':1280})
    assert target.read_bytes() == b'preserved'


def test_legacy_expired_budget_cannot_shorten_new_download(tmp_path,monkeypatch):
    from hotpost.config import Settings
    calls=[]
    monkeypatch.setattr(yd,'endpoint',lambda _:calls.append(1) or None)
    with pytest.raises(RuntimeError,match='Chrome'):
        yd.download(Settings(data_dir=tmp_path),'https://www.youtube.com/shorts/E2vmIs5gmTc',tmp_path/'expired.mp4',1024,deadline=0.17)
    assert calls==[1]


def test_general_candidate_route_never_falls_back_to_cookie_extractor(tmp_path, monkeypatch):
    from hotpost import source_finder as sf, source_collection_access as access
    from hotpost.source_search.models import Candidate
    monkeypatch.setattr(access, 'collection_disabled', lambda _:False)
    monkeypatch.setattr(sf, '_executable', lambda _:pytest.fail('No yt-dlp fallback'))
    monkeypatch.setattr(yd, 'download', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('manual authentication required')))
    item = Candidate('https://www.youtube.com/shorts/E2vmIs5gmTc', 'youtube')
    assert sf.download_candidate(item, tmp_path/'videos', 1, 80) is None
    assert item.acquisition == 'existing-browser-playback'
    assert 'manual authentication required' in item.error


def test_shorts_general_route_keeps_video_id_in_saved_filename(tmp_path, monkeypatch):
    from hotpost import source_finder as sf, source_collection_access as access
    from hotpost.source_search.models import Candidate
    monkeypatch.setattr(access, 'collection_disabled', lambda _:False)
    monkeypatch.setattr(yd, 'download', lambda settings, url, target, *args, **kwargs:target)
    item = Candidate('https://www.youtube.com/shorts/E2vmIs5gmTc', 'youtube')
    result = sf.download_candidate(item, tmp_path/'videos', 1, 80)
    assert result.name == '01_youtube_E2vmIs5gmTc.mp4'
