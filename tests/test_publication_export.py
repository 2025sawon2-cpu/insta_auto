from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hotpost import publication_export as exports


def write_qa(source, path):
    video, cover = source['media']['final'], source['media']['cover']
    value = {
        'schema_version': 1, 'video_id': 'post', 'task_id': 'task-post',
        'run_id': source['run_id'], 'edit_id': source['edit_id'],
        'producer': 'producer', 'reviewed_at': '2026-10-25T09:00:00+09:00',
        'artifacts': {
            **{key: {'id': key + '-post', 'sha256': 'a' * 64} for key in ('script', 'voice', 'plan')},
            'video': {'path': str(video), 'sha256': exports.digest(video)},
            'cover': {'path': str(cover), 'sha256': exports.digest(cover)},
        },
        'checks': {key: {'status': '충족', 'evidence': [{'asset': asset,
                   'location': '00:02 or opening sentence', 'observation': 'Reviewed current output'}]}
                   for key, asset in (('script', 'script'), ('visual', 'video'),
                                      ('audio_captions', 'video'), ('cover_delivery', 'cover'))},
    }
    path.write_text(json.dumps(value), encoding='utf-8')


@pytest.fixture
def setup(tmp_path, monkeypatch):
    config = tmp_path / 'local/video-storage.json'
    destination = tmp_path / 'exports'
    exports.configure(destination, config)
    video, cover = tmp_path / 'current.mp4', tmp_path / 'current.png'
    video.write_bytes(b'verified current video')
    cover.write_bytes(b'applied cover, not the unsaved draft selection')
    source = {'run_id': 'completed', 'edit_id': 'edit', 'media_version': 'active-1',
              'media': {'final': video, 'cover': cover, 'reference': None}}
    source['qa_record'] = tmp_path / 'final-qa.json'
    write_qa(source, source['qa_record'])
    service = SimpleNamespace(source=lambda code: source)
    monkeypatch.setattr(exports, 'validate_video', lambda path: None)
    now = datetime(2026, 10, 22, 16, tzinfo=timezone.utc)
    return service, source, config, destination, now


def test_review_copy_preserves_unconfirmed_evidence_without_completion(setup):
    service, source, config, destination, now = setup
    path = source['qa_record']
    record = json.loads(path.read_text('utf8'))
    record['checks']['audio_captions']['status'] = '확인 불가'
    path.write_text(json.dumps(record), 'utf8')
    result = exports.save_review(service, 'post', topic='선반', config=config, now=now, qa_record=path)
    assert Path(result['video']).parent == destination / '검토본/2026-10-23'
    assert result['quality_complete'] is False
    assert result['unresolved'] == ['audio_captions']
    snapshot = json.loads(Path(result['qa_snapshot']).read_bytes())
    assert snapshot['original_qa'] == record
    assert snapshot['quality_complete'] is False
    assert exports.save_review(service, 'post', topic='선반', config=config, now=now, qa_record=path)['status'] == 'already_saved'
    with pytest.raises(ValueError, match='audio_captions is not confirmed'):
        exports.save_current(service, 'post', topic='선반', config=config, now=now, qa_record=path)
    source['media']['final'].write_bytes(b'changed after review')
    with pytest.raises(ValueError, match='bytes changed'):
        exports.save_review(service, 'post', topic='선반', config=config, now=now, qa_record=path)


def test_human_evidence_requires_current_file_and_explicit_scope(setup):
    from hotpost.final_qa import validate
    _, source, _, _, _ = setup
    path = source['qa_record']
    record = json.loads(path.read_text('utf8'))
    row = record['checks']['audio_captions']['evidence'][0]
    row.update(method='human_user_review', user_quote='좋아', review_context='대본을 제시함',
               reviewed_checks=['script'], video_sha256=exports.digest(source['media']['final']))
    path.write_text(json.dumps(record), 'utf8')
    with pytest.raises(ValueError, match='outside the human review scope'):
        validate(path, video_id='post')
    row.update(user_quote='영상을 보고 음성과 자막 싱크까지 확인했어', review_context='현재 영상 전체를 제시함',
               reviewed_checks=['audio_captions'], video_sha256='b' * 64)
    path.write_text(json.dumps(record), 'utf8')
    with pytest.raises(ValueError, match='another video'):
        validate(path, video_id='post')
    row['video_sha256'] = exports.digest(source['media']['final'])
    path.write_text(json.dumps(record), 'utf8')
    validate(path, video_id='post')


def test_review_copy_preserves_prior_versions_and_qa_changes(setup):
    service, source, config, _, now = setup
    path = source['qa_record']
    first = exports.save_review(service, 'post', topic='선반', config=config, now=now, qa_record=path)
    record = json.loads(path.read_text('utf8'))
    record['checks']['visual']['status'] = '수정 필요'
    path.write_text(json.dumps(record), 'utf8')
    second = exports.save_review(service, 'post', topic='선반', config=config, now=now, qa_record=path)
    assert first['video'] != second['video']
    assert Path(first['video']).is_file()
    assert second['unresolved'] == ['visual']


def test_configure_creates_personal_folder_and_retains_other_local_preferences(tmp_path):
    config = tmp_path / 'local/video-storage.json'
    config.parent.mkdir()
    config.write_text(json.dumps({'topics': {'post': '내주제'}, 'other': 'keep'}), 'utf8')
    destination = tmp_path / 'new-folder'
    exports.configure(destination, config)
    value = json.loads(config.read_text('utf8'))
    assert destination.is_dir()
    assert value == {'destination': str(destination), 'topics': {'post': '내주제'}, 'other': 'keep'}
    assert str(destination) in (config.parent / 'VIDEO_STORAGE.md').read_text('utf8')
    document = config.parent / 'VIDEO_STORAGE.md'
    document.write_text(document.read_text('utf8') + '\n내가 추가한 개인 메모\n', 'utf8')
    exports.configure(tmp_path / 'changed-folder', config)
    assert '내가 추가한 개인 메모' in document.read_text('utf8')
    assert str(tmp_path / 'changed-folder') in document.read_text('utf8')


def test_pair_uses_korean_date_short_filename_and_current_applied_thumbnail(setup):
    service, source, config, destination, now = setup
    result = exports.save_current(service, 'post', topic='욕실 수납선반', config=config, now=now,
                                  qa_record=source['qa_record'])
    assert result['status'] == 'saved'
    assert Path(result['video']) == destination / '2026-10-23/20261023_욕실_수납선반.mp4'
    assert Path(result['thumbnail']).name == '20261023_욕실_수납선반_썸네일.png'
    assert Path(result['video']).read_bytes() == source['media']['final'].read_bytes()
    assert Path(result['thumbnail']).read_bytes() == source['media']['cover'].read_bytes()
    assert [exports.digest(Path(result[key])) for key in ('video', 'thumbnail')] == result['sha256']
    assert not (destination / '.video-export.lock').exists()


def test_new_save_rejects_missing_or_wrong_run_qa(setup):
    service, source, config, destination, now = setup
    with pytest.raises(ValueError, match='record path is required'):
        exports.save_current(service, 'post', topic='선반', config=config, now=now)
    record = json.loads(source['qa_record'].read_text('utf-8'))
    record['run_id'] = 'another-run'
    source['qa_record'].write_text(json.dumps(record), encoding='utf-8')
    with pytest.raises(ValueError, match='run_id differs'):
        exports.save_current(service, 'post', topic='선반', config=config, now=now,
                             qa_record=source['qa_record'])
    assert list(destination.iterdir()) == []


def test_identical_pair_is_idempotent_and_new_version_keeps_previous_files(setup):
    service, source, config, destination, now = setup
    arguments = dict(topic='선반', config=config, now=now, qa_record=source['qa_record'])
    first = exports.save_current(service, 'post', **arguments)
    assert exports.save_current(service, 'post', **arguments)['status'] == 'already_saved'
    source['media']['cover'].write_bytes(b'new applied cover')
    with pytest.raises(ValueError, match='bytes changed after review'):
        exports.save_current(service, 'post', **arguments)
    write_qa(source, source['qa_record'])
    second = exports.save_current(service, 'post', **arguments)
    assert Path(second['video']).name == '20261023_선반_02.mp4'
    assert Path(second['thumbnail']).name == '20261023_선반_02_썸네일.png'
    assert exports.digest(first['thumbnail']) == first['sha256'][1]
    assert Path(second['thumbnail']).read_bytes() == b'new applied cover'


def test_existing_unrelated_single_file_is_not_overwritten(setup):
    service, source, config, destination, now = setup
    day = destination / '2026-10-23'
    day.mkdir()
    existing = day / '20261023_선반.mp4'
    existing.write_bytes(b'unrelated user video')
    result = exports.save_current(service, 'post', topic='선반', config=config, now=now,
                                  qa_record=source['qa_record'])
    assert Path(result['video']).name == '20261023_선반_02.mp4'
    assert existing.read_bytes() == b'unrelated user video'


def test_local_topic_can_be_used_without_shared_machine_path(setup):
    service, source, config, destination, now = setup
    rules = json.loads(config.read_text('utf8'))
    rules['topics'] = {'post': '욕실선반'}
    config.write_text(json.dumps(rules), 'utf8')
    result = exports.save_current(service, 'post', config=config, now=now, qa_record=source['qa_record'])
    assert Path(result['video']).name == '20261023_욕실선반.mp4'


@pytest.mark.parametrize('missing', ['run_id', 'edit_id', 'cover', 'final'])
def test_unfinished_or_coverless_result_cannot_be_reported_as_saved(setup, missing):
    service, source, config, destination, now = setup
    if missing in source:
        source[missing] = None
    else:
        source['media'][missing] = None
    with pytest.raises(ValueError, match='검증된 완성 영상'):
        exports.save_current(service, 'post', topic='선반', config=config, now=now,
                             qa_record=source['qa_record'])
    assert list(destination.iterdir()) == []


def test_corrupt_network_copy_never_publishes_a_final_pair(setup, monkeypatch):
    service, source, config, destination, now = setup
    monkeypatch.setattr(exports.shutil, 'copyfile', lambda original, temporary: temporary.write_bytes(b'bad transfer'))
    with pytest.raises(ValueError, match='검증에 실패'):
        exports.save_current(service, 'post', topic='선반', config=config, now=now,
                             qa_record=source['qa_record'])
    assert list((destination / '2026-10-23').iterdir()) == []
    assert not (destination / '.video-export.lock').exists()
    assert source['media']['final'].read_bytes() == b'verified current video'


def test_current_version_change_during_copy_stops_old_pair_publication(setup):
    service, source, config, destination, now = setup
    calls = []
    def current(code):
        calls.append(code)
        return {**source, 'media_version': 'active-1' if len(calls) == 1 else 'active-2'}
    service.source = current
    with pytest.raises(ValueError, match='현재 완성본이 변경'):
        exports.save_current(service, 'post', topic='선반', config=config, now=now,
                             qa_record=source['qa_record'])
    assert list((destination / '2026-10-23').iterdir()) == []


def test_another_agent_lock_is_preserved_and_no_files_are_copied(setup):
    service, source, config, destination, now = setup
    lock = destination / '.video-export.lock'
    lock.mkdir()
    with pytest.raises(ValueError, match='다른 저장 작업'):
        exports.save_current(service, 'post', topic='선반', config=config, now=now,
                             qa_record=source['qa_record'])
    assert lock.is_dir()
    assert list((destination / '2026-10-23').iterdir()) == []


def test_unconfigured_or_relative_destination_is_not_guessed(tmp_path):
    with pytest.raises(ValueError, match='먼저 설정'):
        exports.read_rules(tmp_path / 'missing.json')
    config = tmp_path / 'bad.json'
    config.write_text(json.dumps({'destination': 'some-relative-folder'}), 'utf8')
    with pytest.raises(ValueError, match='절대 경로'):
        exports.read_rules(config)
    assert exports.short_topic('욕실:/선반* 정리?') == '욕실선반_정리'


def test_incompatible_video_is_rejected_without_reencoding(tmp_path, monkeypatch):
    value = {'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'pix_fmt': 'yuv420p', 'profile': 'High 4:4:4 Predictive'}]}
    monkeypatch.setattr(exports.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=json.dumps(value)))
    with pytest.raises(ValueError, match='H.264'):
        exports.validate_video(tmp_path / 'old-incompatible.mp4')
