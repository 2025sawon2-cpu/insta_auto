"""Real local media probes/decodes and short-footage policy boundaries."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from hotpost import source_finder as sf, operation_progress as op, instagram_video as iv
from hotpost.config import Settings
from hotpost.source_quality import media_format_reasons, sha256_file
from hotpost.source_search.triage import discovery_duration_reasons
from hotpost.source_coverage import coverage_goal
from test_parallel_sources import asset


@pytest.fixture
def real_clip(tmp_path):
    ffmpeg=sf._executable('ffmpeg')
    if not ffmpeg or not sf._executable('ffprobe'):pytest.skip('Local full-decode test needs ffmpeg/ffprobe')
    path=tmp_path/'valid.mp4'
    command=[ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=160x240:rate=15',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=16000','-t','2',
        '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(path)]
    subprocess.run(command,check=True,capture_output=True,timeout=30,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return path


def test_two_second_footage_is_candidate_evidence_not_automatic_quality_success(tmp_path):
    meta={'duration':2.,'width':160,'height':240}
    assert media_format_reasons(meta)==[]
    assert discovery_duration_reasons(SimpleNamespace(discovery_meta=meta),180)==[]
    first=asset(tmp_path,1,core=True);second=asset(tmp_path,2,core=True)
    first['video_meta']['duration']=second['video_meta']['duration']=2.
    policy={'coverage_ratio':1.,'core_min_seconds':4.}
    state={'reference_duration':4.}
    one=coverage_goal([first],state,policy)
    both=coverage_goal([first,second],state,policy)
    duplicated=coverage_goal([first,first],state,policy)
    assert not one['core_ready'] and not one['duration_ready']
    assert both['core_ready'] and both['duration_ready']
    assert not duplicated['core_ready'] and duplicated['core_seconds']==2.


@pytest.mark.parametrize('duration',[0.,-1.,float('nan'),float('inf'),181.])
def test_invalid_duration_or_existing_resource_maximum_stays_rejected(duration):
    meta={'duration':duration,'width':160,'height':240}
    assert 'invalid_duration' in media_format_reasons(meta)
    assert discovery_duration_reasons(SimpleNamespace(discovery_meta=meta),180)==['invalid_duration']


def test_reference_decode_receipt_reuses_only_identical_validated_bytes(real_clip,tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path/'state')
    receipt=sf._verify_reference(settings,'post',real_clip)
    assert receipt['status']=='verified' and receipt['decoded_frames']==30 and receipt['audio_checked']
    assert receipt['source_sha256']==sha256_file(real_clip)
    monkeypatch.setattr(op,'run_progress_command',lambda *a,**k:pytest.fail('Validated same bytes should not decode repeatedly'))
    assert sf._verify_reference(settings,'post',real_clip)==receipt
    real_clip.write_bytes(b'invalid replacement media')
    with pytest.raises(ValueError):sf._verify_reference(settings,'post',real_clip)
    old=tmp_path/'state'/'reference-integrity'/'post'/(receipt['source_sha256']+'.json')
    assert json.loads(old.read_text('utf-8'))['status']=='verified'
    assert len(list(old.parent.glob('*.json')))==2


def test_probeable_truncation_cannot_publish_or_reuse_original(real_clip,tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path/'state',collection_source='browser')
    body=real_clip.read_bytes();broken=body[:-max(500,len(body)//4)]
    cached=settings.transcript_dir/'post-old'/'reference.mp4'
    cached.parent.mkdir(parents=True);cached.write_bytes(broken)
    # faststart leaves valid moov/header metadata even when later media is lost.
    assert sf.probe_video(cached)['width']==160 and sf.probe_video(cached)['duration']==2.
    target=tmp_path/'published.mp4';target.write_bytes(b'prior completed result')
    calls=[]
    monkeypatch.setattr(iv,'browser_video_url',lambda *a:calls.append(1) or 'https://s.cdninstagram.com/v.mp4')
    monkeypatch.setattr(sf,'request_pause',lambda:None)
    response=SimpleNamespace(status_code=200,headers={'Content-Length':str(len(broken))},
        iter_content=lambda n:[broken],close=lambda:None)
    monkeypatch.setattr(sf.requests,'get',lambda *a,**k:response)
    with pytest.raises(ValueError):sf._download_reference(settings,SimpleNamespace(shortcode='post'),target)
    assert calls==[1] and target.read_bytes()==b'prior completed result'
    assert cached.read_bytes()==broken
    digest=sha256_file(cached)
    assert json.loads((settings.data_dir/'reference-integrity'/'post'/(digest+'.json')).read_text('utf-8'))['status']=='invalid'
    assert (settings.data_dir/'reference-integrity'/'post'/(digest+'.received-invalid.mp4')).read_bytes()==broken
    # Confirmed identical failure needs no repeat ffmpeg interrogation.
    monkeypatch.setattr(op,'run_progress_command',lambda *a,**k:pytest.fail('Same corrupt bytes must not be decoded again'))
    with pytest.raises(ValueError):sf._verify_reference(settings,'post',cached)


def test_valid_legacy_reference_gets_receipt_and_is_reused_without_network(real_clip,tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path/'state',collection_source='browser')
    cached=settings.source_dir/'post-old'/'reference.mp4';cached.parent.mkdir(parents=True)
    cached.write_bytes(real_clip.read_bytes());target=tmp_path/'new.mp4'
    monkeypatch.setattr(iv,'browser_video_url',lambda *a:pytest.fail('Valid cached original must be reused'))
    sf._download_reference(settings,SimpleNamespace(shortcode='post'),target)
    assert target.read_bytes()==cached.read_bytes()
    digest=sha256_file(target)
    assert json.loads((settings.data_dir/'reference-integrity'/'post'/(digest+'.json')).read_text('utf-8'))['status']=='verified'


def test_stalled_decode_is_not_recorded_as_confirmed_content_rejection(real_clip,tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path/'state')
    monkeypatch.setattr(op,'run_progress_command',lambda *a,**k:(_ for _ in ()).throw(op.NoProgressTimeout('decoder stalled')))
    with pytest.raises(op.NoProgressTimeout):sf._verify_reference(settings,'post',real_clip)
    assert not list((settings.data_dir/'reference-integrity').rglob('*.json'))
    assert real_clip.is_file()


def test_copied_cache_bytes_cannot_inherit_receipt_after_concurrent_replacement(real_clip,tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path/'state',collection_source='browser')
    cached=settings.source_dir/'post-old'/'reference.mp4';cached.parent.mkdir(parents=True)
    cached.write_bytes(real_clip.read_bytes());target=tmp_path/'published.mp4'
    target.write_bytes(b'prior completed original')
    copy=sf.shutil.copy2
    def changed(source,destination):
        copy(source,destination)
        destination.write_bytes(b'changed copied bytes')
    monkeypatch.setattr(sf.shutil,'copy2',changed)
    monkeypatch.setattr(iv,'browser_video_url',lambda *a:(_ for _ in ()).throw(RuntimeError('No external acquisition in this test')))
    with pytest.raises(RuntimeError,match='No external acquisition'):
        sf._download_reference(settings,SimpleNamespace(shortcode='post'),target)
    assert target.read_bytes()==b'prior completed original'
    assert cached.read_bytes()==real_clip.read_bytes()
