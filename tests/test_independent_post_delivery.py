import hashlib
import json
from types import SimpleNamespace

from hotpost.post_preparation import PostPreparation


def test_independent_delivery_is_visible_without_creating_studio_state(tmp_path):
    service = PostPreparation(SimpleNamespace(data_dir=tmp_path))
    final, cover = tmp_path/'final.mp4', tmp_path/'cover.png'
    final.write_bytes(b'verified-final')
    cover.write_bytes(b'applied-first-frame')
    folder = tmp_path/'post-preparations/post'
    folder.mkdir(parents=True)
    value = {'completion_verified': True, 'version': 'daily-top1-20261026-post',
             'final': str(final), 'cover': str(cover), 'spoken_text': '키티 케이스를 살펴봐요.',
             'cover_text': '키티 케이스에\n숨은 기능?',
             'sha256': {'final': hashlib.sha256(final.read_bytes()).hexdigest(),
                        'cover': hashlib.sha256(cover.read_bytes()).hexdigest()}}
    (folder/'independent.json').write_text(json.dumps(value), encoding='utf8')
    data = service.get('post')
    assert data['source_run_id'] == value['version']
    assert data['media']['final'].endswith('?v='+value['version'])
    assert service.media('post', 'final', value['version']) == final
    assert not data['thumbnail']['ready']
    assert not (tmp_path/'studio').exists()
    final.write_bytes(b'changed-after-verification')
    assert service.get('post')['media']['final'] is None


def test_unverified_and_outside_independent_assets_are_not_exposed(tmp_path):
    service = PostPreparation(SimpleNamespace(data_dir=tmp_path/'data'))
    outside = tmp_path/'outside.mp4'
    outside.write_bytes(b'private')
    folder = service.root/'post-preparations/post'
    folder.mkdir(parents=True)
    for value in ({'completion_verified': False},
                  {'completion_verified': True, 'final': str(outside), 'cover': str(outside)}):
        (folder/'independent.json').write_text(json.dumps(value), encoding='utf8')
        assert service.get('post')['media']['final'] is None


def test_registered_completion_keeps_priority_over_manifest(tmp_path, monkeypatch):
    service = PostPreparation(SimpleNamespace(data_dir=tmp_path))
    registered = {'media_version': None, 'media': {'final': None, 'cover': None}}
    monkeypatch.setattr(service, '_registered_source', lambda code: registered)
    monkeypatch.setattr(service, '_independent_source', lambda code: {'media_version': 'manifest-version', 'media': {'final': tmp_path/'old.mp4'}})
    assert service.source('post') is registered
    import pytest
    with pytest.raises(FileNotFoundError):
        service.media('post', 'final', 'manifest-version')
