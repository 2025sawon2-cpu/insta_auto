import json
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.production import ProductionManager, digest, file_digest, file_lock
from hotpost.storage import Storage


class Studio:
    def __init__(self, reference, text):
        self.submits = 0
        self.result = {'scripts': [{'title': '새 관점', 'text': text,
            'rewrite_review': {'status': 'needs_editorial_review',
                              'script_sha256': digest(text), 'reference_sha256': digest(reference)}}]}

    def submit(self, *args):
        self.submits += 1
        return {'id': 'remote123'}

    def get(self, job_id):
        return {'id': job_id, 'state': 'completed', 'result': self.result}


class Voice:
    def __init__(self):
        self.calls = []

    def synthesize(self, text, target, request_id=None, on_submitted=None, generation_key=None):
        self.calls.append((text, request_id))
        on_submitted(17)
        target.write_bytes(b'RIFF' + b'\0' * 4 + b'WAVE' + b'\0' * 32)
        return {'output_path': str(target), 'voicebench_request_id': 17}


class Editor:
    def __init__(self):
        self.calls = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        draft=kwargs['script_path'].parent/'test-draft'
        draft.mkdir(exist_ok=True)
        (draft/'draft_content.json').write_text('{}','utf-8')
        return {'status': 'completed', 'draft_path': str(draft), 'warnings': [], 'output_kind': 'capcut_draft'}


@pytest.fixture
def workflow(tmp_path):
    settings = Settings(data_dir=tmp_path)
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'clip.mp4').write_bytes(b'source')
    (source / 'manifest.json').write_text(json.dumps({'candidates': [
        {'selected_for_zip': True, 'downloaded_file': 'clip.mp4', 'source_quality': 'clean', 'rights': 'retained'}]}))
    original = tmp_path / 'transcript'
    original.mkdir()
    (original / 'reference.mp4').write_bytes(b'reference')
    reference = '원본에서 소개하는 제품 이야기예요.'
    text = '퇴근하고 식탁을 정리할 때 이런 일이 있죠?\n손잡이로 한 번에 꺼내 보세요.'
    (original / 'transcript.json').write_text(json.dumps({'speech': [{'text': reference}],
                                                        'screen_text': [{'text': 'not narration'}]}))
    store = Storage(settings.db_path)
    for jid, kind, result in [('s1', 'source', {'zip_path': str(source / 'sources.zip')}),
                               ('t1', 'transcript', {'json_path': str(original / 'transcript.json')})]:
        store.create_job(jid, kind, 'reel1')
        store.update_job(jid, status='done', result_json=json.dumps(result))
    store.close()
    studio, voice, editor = Studio(reference, text), Voice(), Editor()
    manager = ProductionManager(settings, studio, voice, editor)
    job = manager.create({'source_job_id': 's1', 'transcript_job_id': 't1', 'product': '수납함'})
    return manager, job, studio, voice, editor


def selection():
    return {'script_index': 0, 'reviewed': True, 'edit_style': 'calm',
            'transformation': {'new_angle': '퇴근 후 사용 상황으로 변경',
                               'structure_change': '결과를 먼저 제시하고 사용 순서를 설명',
                               'visual_change': '정리 전후 장면 순서를 새롭게 배치'},
            'scenes': [{'asset_id': '0', 'label': '식탁 정리 손잡이', 'range': [0, 2]}]}


def test_completed_edit_does_not_hide_later_missing_or_mutated_inputs(workflow):
    manager, job, studio, voice, editor = workflow
    manager.run(job['id'], 'rewrite')
    selected = manager.select(job['id'], selection())
    manager.run(job['id'], 'build')
    Path(selected['script_path']).write_text('changed after completion', 'utf-8')
    result = manager.run(job['id'], 'build')
    assert result['status'] == 'blocked' and '변경' in result['error']
    assert len(editor.calls) == len(voice.calls) == 1


def test_rewrite_terminal_failure_returns_without_polling_until_timeout(workflow, monkeypatch):
    manager, job, studio, *_ = workflow
    studio.get = lambda jid: {'id':jid,'state':'failed','error':'confirmed failure'}
    monkeypatch.setattr('hotpost.production.time.sleep', lambda _: pytest.fail('terminal failure must not sleep'))
    result = manager.run(job['id'], 'rewrite')
    assert result['status'] == 'blocked' and 'confirmed failure' in result['error']


def test_end_to_end_selected_version_and_resume_without_duplicates(workflow):
    manager, job, studio, voice, editor = workflow
    assert manager.run(job['id'], 'build')['status'] == 'blocked'
    assert not voice.calls
    assert manager.run(job['id'], 'rewrite')['status'] == 'awaiting_selection'
    selected = manager.select(job['id'], selection())
    assert file_digest(selected['script_path']) == selected['script_sha256']
    assert manager.run(job['id'], 'build')['status'] == 'draft_ready'
    assert editor.calls[0]['edit_style'] == 'calm'
    assert editor.calls[0]['source_ranges'] == [[0, 2]]
    assert editor.calls[0]['script_path'].read_text('utf-8') == voice.calls[0][0]
    assert manager.run(job['id'], 'build')['status'] == 'draft_ready'
    assert len(editor.calls) == len(voice.calls) == studio.submits == 1


def test_failed_edit_reuses_wav_and_script_modification_is_blocked(workflow):
    manager, job, studio, voice, editor = workflow
    manager.run(job['id'], 'rewrite')
    selected = manager.select(job['id'], selection())
    editor.build = lambda **kw: {'status': 'blocked', 'message': 'CapCut open'}
    assert manager.run(job['id'], 'build')['status'] == 'blocked'
    manager.run(job['id'], 'build')
    assert len(voice.calls) == 1
    Path(selected['script_path']).write_text('changed', 'utf-8')
    assert '변경' in manager.run(job['id'], 'build')['error']


def test_copy_or_stale_review_cannot_be_selected(workflow):
    manager, job, studio, *_ = workflow
    manager.run(job['id'], 'rewrite')
    studio.result['scripts'][0]['text'] = 'edited since review'
    with pytest.raises(ValueError, match='검사 결과'):
        manager.select(job['id'], selection())


def test_os_lock_blocks_concurrent_work_and_releases_after_exit(tmp_path):
    path = tmp_path / 'work.lock'
    with file_lock(path):
        with pytest.raises(ValueError):
            with file_lock(path):
                pass
    with file_lock(path):
        pass


def test_source_range_and_editorial_plan_are_required(workflow):
    manager, job, *_ = workflow
    manager.run(job['id'], 'rewrite')
    payload = selection()
    payload['scenes'][0]['range'] = [4, 2]
    with pytest.raises(ValueError, match='구간'):
        manager.select(job['id'], payload)


def test_manual_service_wait_reuses_script_key_and_request_even_when_scene_style_changes(workflow):
    from hotpost.model_service import ModelServiceUnavailable
    manager, job, _, voice, _ = workflow
    manager.run(job['id'], 'rewrite')
    manager.select(job['id'], selection())
    keys = []
    original = voice.synthesize
    def interrupted(text, target, request_id=None, on_submitted=None, generation_key=None):
        keys.append((generation_key, request_id))
        if len(keys) == 1:
            on_submitted(17)
            raise ModelServiceUnavailable('audio transfer wait', retry_at=123456)
        return original(text, target, request_id, on_submitted, generation_key)
    voice.synthesize = interrupted
    waiting = manager.run(job['id'], 'build')
    assert waiting['status'] == 'service_wait' and waiting['voicebench_request_id'] == 17
    assert waiting['service_retry_at'] == 123456 and not voice.calls
    waiting['edit_style'] = 'brisk'; waiting['scenes'][0]['range'] = [1, 3]
    manager.save(waiting)
    assert manager.run(job['id'], 'build')['status'] == 'draft_ready'
    assert keys[0][0] == keys[1][0] == 'prod-'+job['id']+'-'+waiting['script_sha256'][:32]
    assert keys[1][1] == 17 and voice.calls == [(Path(waiting['script_path']).read_text('utf-8'), 17)]


@pytest.mark.parametrize('new_selection', [False, True])
def test_manual_retry_respects_provider_cooldown_even_after_new_script_selection(workflow, monkeypatch, new_selection):
    import copy
    from hotpost.model_service import ModelServiceUnavailable
    manager, job, studio, voice, editor = workflow
    manager.run(job['id'], 'rewrite')
    manager.select(job['id'], selection())
    monkeypatch.setattr('hotpost.production.time.time', lambda: 1000.0)
    calls=[]
    original=voice.synthesize
    def interrupted(text,target,request_id=None,on_submitted=None,generation_key=None):
        calls.append((request_id,generation_key))
        if len(calls)==1:
            on_submitted(17)
            raise ModelServiceUnavailable('provider Retry-After',retry_at=1120)
        return original(text,target,request_id,on_submitted,generation_key)
    voice.synthesize=interrupted
    waiting=manager.run(job['id'],'build')
    assert waiting['status']=='service_wait' and waiting['service_retry_at']==1120
    if new_selection:
        new_text='새 대본으로 고른 제품 이야기예요.'
        studio.result['scripts'][0]['text']=new_text
        studio.result['scripts'][0]['rewrite_review']['script_sha256']=digest(new_text)
        waiting=manager.select(job['id'],selection())
        assert waiting['voicebench_request_id'] is None
    before=copy.deepcopy(waiting)
    files={str(p):p.read_bytes() for p in manager.folder(job['id']).rglob('*') if p.is_file()}
    for _ in range(3):
        assert manager.run(job['id'],'build')==before
    assert len(calls)==1 and not editor.calls and not voice.calls
    assert files=={str(p):p.read_bytes() for p in manager.folder(job['id']).rglob('*') if p.is_file()}
    monkeypatch.setattr('hotpost.production.time.time',lambda:1120.0)
    assert manager.run(job['id'],'build')['status']=='draft_ready'
    assert len(calls)==2
    if new_selection:
        assert calls[1][0] is None and calls[1][1]!=calls[0][1]
    else:
        assert calls[1]==(17,calls[0][1])
