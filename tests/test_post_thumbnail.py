import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time
from types import SimpleNamespace

import pytest
from PIL import Image

from hotpost.post_preparation import PostPreparation, DraftConflict
from hotpost import post_thumbnail as thumbnails


@pytest.fixture
def ready(tmp_path):
    font = next((p for p in (Path('C:/Windows/Fonts/arialbd.ttf'), Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')) if p.is_file()), None)
    if not font or not shutil.which('ffmpeg'):
        pytest.skip('A local font and ffmpeg are needed for a real thumbnail render')
    original = tmp_path/'original.mp4'
    thumbnails.command(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x568:rate=30:duration=1',
                        '-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-pix_fmt','yuv420p',
                        '-c:a','aac','-shortest',str(original)])
    background = tmp_path/'background.png'
    Image.new('RGB',(320,568),'#456a53').save(background)
    plan = tmp_path/'plan.json'
    plan.write_text(json.dumps({'cover_spec':{'lines':['Old','title'],'background_path':str(background)},
                                'cover_font_style':{'font_path':str(font)}}),'utf8')
    state = {'latest_completed_run_id':'run', 'scripts':[{'id':'script','text':'Product text.'}],
             'edits':[{'id':'edit','script_id':'script','export_verified':True,'export_path':str(original),'plan_path':str(plan)}],
             'runs':[{'id':'run','status':'completed','artifacts':{'edit_id':'edit'}}]}
    (tmp_path/'studio').mkdir()
    with sqlite3.connect(tmp_path/'studio/studio.sqlite3') as db:
        db.execute('CREATE TABLE tasks(shortcode TEXT,state TEXT)')
        db.execute('INSERT INTO tasks VALUES (?,?)',('post',json.dumps(state)))
    service = PostPreparation(SimpleNamespace(data_dir=tmp_path))
    draft = service.get('post')['draft']
    draft['selected_thumbnail']='hook'
    draft['thumbnail_options']['hook']='New\nheadline'
    service.save('post',{'revision':0,'draft':draft})
    return service, original


def wait(service):
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        state=thumbnails.job_status(service,'post')
        if state['status'] not in thumbnails.ACTIVE:
            return state
        time.sleep(.05)
    pytest.fail('Thumbnail render did not finish')


def test_real_render_replaces_current_media_and_keeps_audio_and_body_frames(ready):
    service, original=ready
    original_sha=hashlib.sha256(original.read_bytes()).hexdigest()
    database=service.root/'studio/studio.sqlite3'
    database_sha=hashlib.sha256(database.read_bytes()).hexdigest()
    result=service.start_thumbnail('post',{'revision':1})
    assert result['status'] in ('queued','running')
    finished=wait(service)
    assert finished['status']=='completed',finished
    current=service.get('post')
    assert current['thumbnail']['applied_text']=='New\nheadline'
    assert '?v=' in current['media']['final']
    assert current['draft']['selected_thumbnail']=='hook'
    manifest=json.loads((service.root/'post-preparations/post/active.json').read_text('utf8'))
    assert manifest['checks']['body_frames_identical']
    assert manifest['checks']['audio_identical']
    assert manifest['rules']['advertising_disclosure']=='upper-right-gray-v1'
    assert Path(manifest['body_final']).name=='disclosed-body.mp4'
    # The overlay survives the whole body; outside its area the decoded frames match.
    assert thumbnails.hashes(original,crop='crop=200:ih:0:0')[1:] == thumbnails.hashes(Path(manifest['final']),crop='crop=200:ih:0:0')[1:]
    assert all(a!=b for a,b in zip(thumbnails.hashes(original,crop='crop=120:80:200:0'),
                                  thumbnails.hashes(Path(manifest['final']),crop='crop=120:80:200:0')))
    assert thumbnails.hashes(original)[0] != thumbnails.hashes(Path(manifest['final']))[0]
    assert hashlib.sha256(original.read_bytes()).hexdigest()==original_sha
    assert hashlib.sha256(database.read_bytes()).hexdigest()==database_sha
    assert service.media('post','final',finished['id']).is_file()
    with pytest.raises(FileNotFoundError):
        service.media('other','final',finished['id'])


def test_failed_render_does_not_replace_existing_result(ready,monkeypatch):
    service,original=ready
    before=service.get('post')['media']['final']
    def fail(*args):
        raise ValueError('검증용 렌더 실패')
    monkeypatch.setattr(thumbnails,'replace_first_frame',fail)
    service.start_thumbnail('post',{'revision':1})
    assert wait(service)['status']=='failed'
    assert service.get('post')['media']['final']==before
    assert not (service.root/'post-preparations/post/active.json').exists()


def test_changed_revision_cannot_render_stale_words(ready):
    service,_=ready
    with pytest.raises(DraftConflict):
        service.start_thumbnail('post',{'revision':0})
    assert thumbnails.job_status(service,'post')['status']=='idle'


def test_duplicate_request_returns_same_active_job(ready,monkeypatch):
    service,_=ready
    import threading
    started,release=threading.Event(),threading.Event()
    real=thumbnails.replace_first_frame
    def pause(*args):
        started.set();release.wait(10);real(*args)
    monkeypatch.setattr(thumbnails,'replace_first_frame',pause)
    first=service.start_thumbnail('post',{'revision':1})
    try:
        assert started.wait(5)
        second=service.start_thumbnail('post',{'revision':1})
        assert second['id']==first['id']
    finally:
        release.set()
    assert wait(service)['status']=='completed'


def test_later_thumbnail_keeps_previously_edited_body(ready):
    service,original=ready
    service.start_thumbnail('post',{'revision':1})
    assert wait(service)['status']=='completed'
    edited=service.root/'edited-body.mp4'
    thumbnails.command(['ffmpeg','-v','error','-y','-i',str(original),'-vf',
                        "drawbox=x=0:y=0:w=60:h=60:color=white:t=fill:enable='gte(t,.3)'",
                        '-c:v','libx264','-qp','0','-c:a','copy',str(edited)])
    pointer=service.root/'post-preparations/post/active.json'
    manifest=json.loads(pointer.read_text('utf8'));manifest['body_final']=str(edited)
    pointer.write_text(json.dumps(manifest),'utf8')
    assert service.source('post')['base_final']==edited.resolve()
    service.start_thumbnail('post',{'revision':1})
    assert wait(service)['status']=='completed'
    current=json.loads(pointer.read_text('utf8'))
    assert current['body_final']==str(edited)
    assert thumbnails.hashes(Path(current['final']))[1:]==thumbnails.hashes(edited)[1:]
    assert thumbnails.hashes(Path(current['final']))[1:]!=thumbnails.hashes(original)[1:]


def test_later_thumbnail_keeps_disclosure_and_corrected_audio(ready):
    service,_=ready
    service.start_thumbnail('post',{'revision':1})
    assert wait(service)['status']=='completed'
    pointer=service.root/'post-preparations/post/active.json'
    first=json.loads(pointer.read_text('utf8'))
    first['spoken_text']='청소용품 하나로 시작해요.'
    first['rules']['content_opening']='no-interjection-v1'
    pointer.write_text(json.dumps(first,ensure_ascii=False),'utf8')
    service.start_thumbnail('post',{'revision':1})
    assert wait(service)['status']=='completed'
    second=json.loads(pointer.read_text('utf8'))
    assert second['rules']==first['rules']
    assert second['spoken_text']==first['spoken_text']
    assert thumbnails.hashes(Path(first['final']),audio=True)==thumbnails.hashes(Path(second['final']),audio=True)
    assert thumbnails.hashes(Path(first['final']))[1:]==thumbnails.hashes(Path(second['final']))[1:]
