"""Slow local verification must not look like excessive platform traffic."""
import subprocess
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from hotpost.config import Settings
from hotpost.models import Post
from hotpost.source_finder import Candidate


@pytest.fixture
def probe_run(tmp_path, monkeypatch):
    from hotpost import source_finder as sf, source_functional, text_overlay

    clock = SimpleNamespace(now=100.0, network=2.0, review=400.0, fail=False)
    monkeypatch.setattr(sf.time, 'monotonic', lambda: clock.now)
    settings = Settings(data_dir=tmp_path, source_browser_search=False,
                        source_query_model_enabled=False, source_transcribe_reference=False,
                        source_refine_max_candidates=0, source_match_mode='functional',
                        source_max_downloads=4, source_max_probe_downloads=4,
                        source_probe_time_budget=900, source_platform_probe_budget=300)
    monkeypatch.setattr(sf, '_post', lambda *_: Post('ref', 'u', 1, 'reel', caption='차 뒤에 달고 다니다 펼치는 텐트'))
    monkeypatch.setattr(sf, '_download_reference', lambda *args: (args[-1].write_bytes(b'reference'), args[-1])[1])

    def frames(_video, directory, *_args, **_kwargs):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / 'candidate_001.jpg'
        Image.new('RGB', (20, 30), 'white').save(path)
        return [path]

    monkeypatch.setattr(sf, 'extract_frames', frames)
    monkeypatch.setattr(sf, 'OpenClipVerifier', lambda *_: SimpleNamespace(
        error='', product_evidence=[], last_embedding=None, subject_reference_indices=[],
        focus_subject=lambda _: None, discover_product_queries=lambda: [], score=lambda _: .7))
    monkeypatch.setattr(sf, 'search_google_vision', lambda *_: ([], []))
    monkeypatch.setattr(sf, 'search_local_hints', lambda *_: [
        Candidate('https://youtube.com/watch?v=first', 'youtube'),
        Candidate('https://youtube.com/watch?v=second', 'youtube')])
    monkeypatch.setattr(text_overlay, 'TextOverlayDetector', lambda *_: SimpleNamespace(
        note='', reference_text=lambda _: '', analyze=lambda _: {'source_quality': 'clean-source'}))
    monkeypatch.setattr(sf, 'probe_video', lambda _: {'duration': 10, 'width': 720, 'height': 1280})

    def compare(reference, video, directory):
        frames(video, directory)
        return .3  # Requires functional review; appearance alone cannot pass.

    monkeypatch.setattr(sf, 'compare_videos', compare)
    attempts, reviews = [], []

    def download(candidate, directory, index, *_args, deadline=None, **_kwargs):
        attempts.append({'url': candidate.url, 'started': clock.now, 'deadline': deadline})
        clock.now += clock.network
        if clock.fail:
            raise subprocess.TimeoutExpired('download', clock.network)
        path = directory / f'{index}.mp4'
        path.write_bytes(str(index).encode())
        return path

    def review(_settings, candidate, reference, candidate_frames):
        reviews.append(candidate.url)
        clock.now += clock.review
        return {'reviewed': True, 'same_core_function': False,
                'reason': 'Different mechanism', 'source_sha256': candidate.file_sha256}

    monkeypatch.setattr(sf, 'download_candidate', download)
    monkeypatch.setattr(source_functional, 'review_function', review)
    return SimpleNamespace(clock=clock, settings=settings, attempts=attempts, reviews=reviews,
                           run=lambda: sf.find_sources(settings, 'ref'))


def test_visual_review_is_deferred_without_exhausting_platform_download_budget(probe_run):
    result = probe_run.run()
    assert result['probe_attempts'] == 2 and not probe_run.reviews
    assert result['platform_probe_seconds'] == {'youtube': 4.0}
    assert [call['deadline'] for call in probe_run.attempts] == [None, None]
    assert result['downloaded'] == result['review_pending'] == 1  # Identical fixture frames remain deduplicated.
    assert all(c['relevance_review_required'] for c in result['candidates'])
    assert all('different_core_function' not in c['rejection_reasons'] for c in result['candidates'])
    assert not result['quota_ready']  # Acquisition is not a visual approval.


@pytest.mark.parametrize('failed_download', [False, True])
def test_elapsed_network_time_never_exhausts_platform_execution_rights(probe_run, failed_download):
    probe_run.clock.network, probe_run.clock.review = 300.0, 0.0
    probe_run.clock.fail = failed_download
    result = probe_run.run()
    assert result['probe_attempts'] == 2
    assert all(c['deadline'] is None for c in probe_run.attempts)
    assert result['platform_probe_seconds'] == {'youtube': 600.0}


def test_slow_local_verification_does_not_shorten_next_download(probe_run, monkeypatch):
    from hotpost import source_finder as sf
    compare = sf.compare_videos
    def slow_compare(*args):
        probe_run.clock.now += 1000.0
        return compare(*args)
    monkeypatch.setattr(sf, 'compare_videos', slow_compare)
    result = probe_run.run()
    assert result['probe_attempts'] == 2
    assert result['budget_stop'] == ''
    assert result['platform_probe_seconds'] == {'youtube': 4.0}


def test_obsolete_total_budget_does_not_allocate_any_download_deadline(probe_run):
    probe_run.settings.source_probe_time_budget = 10
    probe_run.clock.network, probe_run.clock.review = 10.0, 0.0
    result = probe_run.run()
    assert all(c['deadline'] is None for c in probe_run.attempts)
    assert result['probe_attempts'] == 2 and result['budget_stop'] == ''


def test_each_probe_checkpoint_survives_before_next_network_attempt(probe_run, monkeypatch):
    from hotpost import source_finder as sf
    download = sf.download_candidate
    receipts = []
    def checked_download(*args, **kwargs):
        receipt = json.loads(next(probe_run.settings.source_dir.glob('ref-*/manifest.json')).read_text(encoding='utf-8'))
        receipts.append(receipt)
        return download(*args, **kwargs)
    monkeypatch.setattr(sf, 'download_candidate', checked_download)
    result = probe_run.run()
    assert len(receipts)==2
    assert receipts[0]['candidates'][0]['download_attempted'] is True
    assert receipts[1]['candidates'][0]['downloaded_file']
    assert receipts[1]['candidates'][0]['relevance_review_required']
    assert receipts[1]['candidates'][0]['similarity_warnings']
    assert result['source_target']==1 and not result['platform_targets']
    assert result['platform_preferences']['tiktok']['target']==5
    assert result['platform_preferences']['tiktok']['required'] is False
    assert result['platform_outcomes']['tiktok']['search_attempts']==0
    assert result['platform_outcomes']['tiktok']['reasons']['not_attempted']==1


def test_many_ranked_candidates_are_not_prorated_by_platform_elapsed_time(probe_run, monkeypatch):
    from hotpost import source_finder as sf
    # Extraction, request pacing and a valid transfer need forty seconds.
    # Twelve proposals must not all be cancelled at 300/12=25 seconds.
    monkeypatch.setattr(sf, 'search_local_hints', lambda *_: [
        Candidate(f'https://youtube.com/watch?v=proposal-{i}', 'youtube') for i in range(12)])
    probe_run.settings.source_max_probe_downloads=30
    probe_run.clock.network, probe_run.clock.review = 40.0, 0.0
    original_download = sf.download_candidate

    def timed_transfer(candidate, directory, index, *args, deadline=None, **kwargs):
        if deadline is not None and probe_run.clock.now+40 > deadline:
            probe_run.clock.now = deadline
            candidate.error = 'Valid transfer cancelled by deadline'
            return None
        return original_download(candidate, directory, index, *args, deadline=deadline, **kwargs)

    monkeypatch.setattr(sf, 'download_candidate', timed_transfer)
    result = probe_run.run()
    assert result['probe_attempts'] == len(probe_run.attempts) == 12
    assert result['review_pending'] == 1 and not probe_run.reviews
    assert result['platform_probe_seconds']['youtube'] == 480
    assert result['downloaded'] == 1 and not result['quota_ready']


def test_time_allocator_has_been_removed():
    from hotpost.source_search import budget
    assert not hasattr(budget,'candidate_probe_seconds')


@pytest.mark.parametrize('ready_at,expected_downloads',[(1,3),(2,6),(3,7)])
def test_download_batches_wait_for_real_review_and_stop_when_ready(probe_run,monkeypatch,ready_at,expected_downloads):
    from hotpost import source_finder as sf
    monkeypatch.setattr(sf,'search_local_hints',lambda *_:[
        Candidate(f'https://youtube.com/watch?v=batch-{i}','youtube') for i in range(7)])
    probe_run.settings.source_max_probe_downloads=20
    snapshots=[]
    def review(path):
        before=path.read_bytes();value=json.loads(before)
        assert value['status']=='review_pending'
        assert len(probe_run.attempts)==len(value['candidates'])
        snapshots.append((path,before))
        return {'ready':len(snapshots)==ready_at}
    result=sf.find_sources(probe_run.settings,'ref',review_batch=review)
    assert len(probe_run.attempts)==expected_downloads
    assert all(path.read_bytes()==raw for path,raw in snapshots)
    assert result['batch_review']['ready'] is True
    assert not result['quota_ready']  # Finder cannot manufacture an approval.


def test_review_pause_stops_before_next_download_and_keeps_batch(probe_run,monkeypatch):
    from hotpost import source_finder as sf
    from hotpost.studio_pause import StudioPaused
    monkeypatch.setattr(sf,'search_local_hints',lambda *_:[
        Candidate(f'https://youtube.com/watch?v=pause-{i}','youtube') for i in range(8)])
    probe_run.settings.source_max_probe_downloads=20
    def pause(path):
        assert path.is_file()
        raise StudioPaused('preserve this review input')
    with pytest.raises(StudioPaused):sf.find_sources(probe_run.settings,'ref',review_batch=pause)
    assert len(probe_run.attempts)==3
    manifest=next(probe_run.settings.source_dir.glob('ref-*/manifest.json'))
    assert json.loads(manifest.read_text('utf8'))['status']=='paused'
    assert manifest.with_name('batch-0001.json').is_file()
