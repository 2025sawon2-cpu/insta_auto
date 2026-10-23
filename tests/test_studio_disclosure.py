import copy
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.studio_disclosure import apply_render_disclosure
from hotpost.source_quality import sha256_file


def test_completion_hash_works_without_python311_file_digest(tmp_path, monkeypatch):
    from hotpost.monetization_completion import _digest
    monkeypatch.delattr(hashlib, 'file_digest', raising=False)
    path = tmp_path / 'file.mp4'
    path.write_bytes(b'current actual video')
    assert _digest(path) == hashlib.sha256(path.read_bytes()).hexdigest()
    assert _digest(tmp_path / 'missing') is None
    assert _digest(None) is None


@pytest.fixture
def prepared(tmp_path):
    studio = Studio(Settings(data_dir=tmp_path / 'data'), workers=False)
    state, _ = studio.store.create('disclosure', '광고 표시', prepare=False)
    root = studio.folder(state['id'])
    root.mkdir(exist_ok=True)
    video, plan, cover = root / 'preview.mp4', root / 'plan.json', root / 'cover.png'
    video.write_bytes(b'video'); plan.write_text('{}'); cover.write_bytes(b'cover')
    def setup(s, db):
        s.update(edits=[{'id': 'edit', 'voice_id': 'voice', 'script_id': 'script',
            'preview_path': str(video), 'plan_path': str(plan), 'cover_path': str(cover)}],
            edit_id='edit', approved_voice_id='voice', script_id='script', approved_script_id='script',
            automation={'protocol':2, 'active':False, 'paused_by_user':True, 'paused_at':123},
            daily_quality={'status':'needs_attention','pending':'failed','failed_job_id':'failed-qa'})
    studio.store.change(state['id'], setup)
    data = {'edit_id':'edit', 'render_sha256':sha256_file(video),
            'plan_sha256':sha256_file(plan), 'resume_pause_token':123}
    yield studio, state['id'], data
    studio.close()


@pytest.mark.parametrize('wrong', ['resume_pause_token','render_sha256','edit_id'])
def test_disclosure_rejects_stale_input_and_pause(prepared, wrong):
    studio, task, data = prepared
    data[wrong] = 'changed'
    with pytest.raises(ValueError): studio.action(task, 'apply-disclosure', data)
    state = studio.store.get(task)
    assert state['automation']['paused_by_user'] is True
    assert not studio.store.jobs(task)


def test_disclosure_queues_only_revision_and_preserves_failed_history(prepared):
    studio, task, data = prepared
    studio.action(task, 'apply-disclosure', data)
    state = studio.store.get(task)
    jobs = studio.store.jobs(task)
    assert len(jobs) == 1 and jobs[0]['kind'] == 'revision'
    assert jobs[0]['status'] == 'queued'
    with studio.store.connect() as db:
        payload = json.loads(db.execute('SELECT payload FROM jobs WHERE id=?', (jobs[0]['id'],)).fetchone()[0])
    assert payload['disclosure_only'] is True
    assert state['daily_quality']['disclosure_history'][0]['prior']['failed_job_id'] == 'failed-qa'
    assert state['edits'][0].get('quality_verified') is None
    with pytest.raises(ValueError): studio.action(task, 'apply-disclosure', data)


@pytest.mark.parametrize('field,value', [('pending','stop_method'), ('feedback',[{'kind':'watermark'}]),
                                        ('narration_context_hold',{'reason':'unresolved'})])
def test_disclosure_cannot_release_content_quality_hold(prepared, field, value):
    studio, task, data = prepared
    studio.store.change(task, lambda s, db: s['daily_quality'].update({field:value}))
    with pytest.raises(ValueError): studio.action(task, 'apply-disclosure', data)
    assert studio.store.get(task)['daily_quality'][field] == value
    assert not studio.store.jobs(task)


def test_real_disclosure_preserves_original_media_and_returns_new_bound_files(tmp_path):
    from PIL import Image
    if not shutil.which('ffmpeg'): pytest.skip('ffmpeg unavailable')
    fonts = [Path('C:/Windows/Fonts/malgun.ttf'), Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
    font = next((p for p in fonts if p.is_file()), None)
    if font is None: pytest.skip('test font unavailable')
    video = tmp_path / 'preview.mp4'; cover = tmp_path / 'cover.png'; plan = tmp_path / 'timeline.json'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=white:s=320x640:r=30:d=0.2',
        '-f','lavfi','-i','sine=frequency=400:duration=0.2','-c:v','libx264','-pix_fmt','yuv420p',
        '-c:a','aac','-shortest',str(video)], check=True, capture_output=True)
    Image.new('RGB',(320,640),'white').save(cover)
    original_plan = {'cover_spec':{'font':{'font_path':str(font)}}, 'script_text':'본문',
                     'voice':{'sha256':'unchanged'}, 'mask_application_clock':{'policy':'existing'}}
    plan.write_text(json.dumps(original_plan), 'utf-8')
    result = {'preview_path':str(video),'cover_path':str(cover),'plan_path':str(plan),'duration':0.2}
    before = {str(p):sha256_file(p) for p in (video,cover,plan)}
    updated = apply_render_disclosure(result, tmp_path)
    assert before == {str(p):sha256_file(p) for p in (video,cover,plan)}
    assert updated['preview_path'] != str(video) and Path(updated['preview_path']).is_file()
    after = json.loads(Path(updated['plan_path']).read_text('utf-8'))
    assert after['voice'] == original_plan['voice'] and after['script_text'] == '본문'
    assert after['mask_application_clock']['final_render_sha256'] == sha256_file(Path(updated['preview_path']))
    receipt = json.loads(Path(updated['publication_disclosure_receipt']).read_text('utf-8'))
    assert receipt['quality_approval'] is False
    assert receipt['plan_sha256'] == sha256_file(Path(updated['plan_path']))
    assert receipt['checks']['audio_packets_identical'] is True
