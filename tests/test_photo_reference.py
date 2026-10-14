import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
import pytest
from hotpost.photo_reference import image_groups, prepare_reference
from hotpost.config import Settings
from hotpost.studio import Studio


def test_images_are_bound_to_exact_post_and_preserve_order():
    data = {'items': [{'code': 'wanted', 'carousel_media': [
        {'image_versions2': {'candidates': [
            {'url': 'small', 'width': 10, 'height': 10},
            {'url': 'large', 'width': 100, 'height': 100}]}},
        {'display_url': 'second'}]}, {'code': 'other', 'display_url': 'unrelated'}]}
    assert list(image_groups(data, 'wanted')) == ['large', 'second']
    graph = {'shortcode': 'wanted', 'edge_sidecar_to_children': {'edges': [
        {'node': {'display_url': 'first'}}, {'node': {'display_url': 'last'}}]}}
    assert list(image_groups(graph, 'wanted')) == ['first', 'last']


def test_caption_is_never_fabricated_as_speech(tmp_path, monkeypatch):
    import io
    image = io.BytesIO()
    Image.new('RGB', (120, 80), 'red').save(image, format='JPEG')
    monkeypatch.setattr('hotpost.source_finder._post', lambda *_: SimpleNamespace(
        kind='carousel', caption='아이 그림 목걸이', url='https://www.instagram.com/p/wanted/'))
    monkeypatch.setattr('hotpost.photo_reference.browser_images', lambda *_: ['https://cdn.example/photo.jpg'])
    monkeypatch.setattr('hotpost.photo_reference.request_pause', lambda: None)
    monkeypatch.setattr('hotpost.photo_reference.requests.get', lambda *a, **k: SimpleNamespace(
        content=image.getvalue(), raise_for_status=lambda: None))
    monkeypatch.setattr('hotpost.source_finder._executable', lambda _: 'ffmpeg')
    def render(args, **kwargs):
        Path(args[-1]).write_bytes(b'reference')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr('hotpost.photo_reference.subprocess.run', render)
    monkeypatch.setattr('hotpost.source_finder.probe_video', lambda _: {'duration': 4})
    result = prepare_reference(Settings(data_dir=tmp_path), 'wanted')
    transcript = json.loads(Path(result['transcript_path']).read_text('utf-8'))
    assert result['reference_kind'] == 'provided_text'
    assert result['reference_speech_text'] == ''
    assert transcript['speech'] == [] and transcript['screen_text'] == []
    assert transcript['provided_text'] == '아이 그림 목걸이'
    assert result['photo_provenance']['usage'] == 'analysis_reference_only'
    assert result['photo_provenance']['rights'] == 'unknown'
    assert Path(result['reference_images'][0]).is_file()
    monkeypatch.setattr('hotpost.photo_reference.browser_images', lambda *_: None)
    assert prepare_reference(Settings(data_dir=tmp_path), 'wanted') == result


def test_photo_prepare_uses_distinct_path():
    studio = object.__new__(Studio)
    studio.settings=SimpleNamespace(photo_production_enabled=True)
    result = {'reference_kind': 'provided_text', 'sources': []}
    with patch('hotpost.photo_reference.prepare_studio', return_value=result) as prepare:
        assert studio._prepare({'id':'photo-preview','creation_mode': 'photo_post'}, {'id': 'job'}) == result
        prepare.assert_called_once()


def test_disabled_photo_recovered_worker_preserves_assets_and_quality_history(tmp_path,monkeypatch):
    import copy
    from hotpost.daily_quality import POLICY
    studio=Studio(Settings(data_dir=tmp_path,photo_production_enabled=False),workers=False)
    state,_=studio.store.create('old-photo','old photo',initial={'creation_mode':'photo_post',
        'scripts':[{'id':'saved-script','text':'saved'}], 'sources':[{'id':'saved-photo'}],
        'daily_quality':{'policy':POLICY,'repair_round':7,'pending':'reediting','reviews':[]}})
    before=copy.deepcopy(studio.store.get(state['id']))
    monkeypatch.setattr(studio,'_prepare',lambda *a:pytest.fail('disabled queued photo must not execute its stage'))
    fail=studio.store.fail
    def stop_after_failure(job,error):
        result=fail(job,error);studio.stop.set();return result
    monkeypatch.setattr(studio.store,'fail',stop_after_failure)
    studio._worker('media')
    after=studio.store.get(state['id'])
    assert after['sources']==before['sources'] and after['scripts']==before['scripts']
    assert after['daily_quality']==before['daily_quality']
    assert studio.store.jobs(state['id'])[0]['status']=='failed'
    assert '비활성' in studio.store.jobs(state['id'])[0]['error']


def test_photo_progress_from_recovered_old_claim_cannot_write_current_state(tmp_path,monkeypatch):
    import pytest
    from hotpost.photo_reference import prepare_studio
    from hotpost.studio_store import StaleClaim
    studio=Studio(Settings(data_dir=tmp_path,photo_production_enabled=True),workers=False)
    state,_=studio.store.create('photo-live','photo',initial={'creation_mode':'photo_post'})
    old=studio.store.claim(task_id=state['id'])
    def reference(settings,code,progress):
        studio.store.recover()
        assert studio.store.claim(task_id=state['id'])
        progress('old worker progress',88)
        return {'original_caption':'caption'}
    monkeypatch.setattr('hotpost.photo_reference.prepare_reference',reference)
    with pytest.raises(StaleClaim):prepare_studio(studio,state,old)
    assert studio.store.get(state['id'])['message']!='old worker progress'
    assert not (studio.folder(state['id'])/(old['id']+'-reference.json')).exists()


def test_studio_photo_intake_requires_explicit_opt_in(tmp_path):
    import pytest
    from hotpost.models import Post
    from hotpost.storage import Storage
    settings = Settings(data_dir=tmp_path)
    db = Storage(settings.db_path)
    db.upsert_posts([Post('photo', 'owner', 100, 'carousel', caption='아이 그림 목걸이')])
    db.close()
    studio = Studio(settings, workers=False)
    with pytest.raises(ValueError, match='비활성화'):
        studio.create('photo')
    with pytest.raises(ValueError, match='비활성화'):
        studio.create('photo', allow_photo=True)
    assert studio.store.list() == []
    settings.photo_production_enabled = True
    task = studio.create('photo', allow_photo=True)
    assert task['creation_mode'] == 'photo_post'
    assert task['original_text'] == ''
    settings.photo_production_enabled = False
    before = studio.store.get(task['id'])
    with pytest.raises(ValueError, match='비활성화'):
        studio.action(task['id'], 'reproduce', {})
    assert studio.store.get(task['id']) == before
