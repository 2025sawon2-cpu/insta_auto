import copy
import hashlib
from pathlib import Path

from PIL import Image

from hotpost.scene_requirements import assess, input_signature
from hotpost.config import Settings


def test_requirement_rejects_frames_from_review_bound_to_another_source(tmp_path):
    frame = tmp_path / 'frame.jpg'
    Image.new('RGB', (64,64), 'red').save(frame)
    source = {'id':'source', 'sha256':'current-source', 'source_quality':'clean-source',
        'editing_eligible':True, 'mask_review':{'source_sha256':'another-source',
        'evidence_frames':[{'path':str(frame), 'sha256':hashlib.sha256(frame.read_bytes()).hexdigest()}]}}
    state = {'sources':[source], 'daily_quality':{'feedback':[{'kind':'scene_gap', 'beat_id':'b1', 'reason':'missing action'}]}}
    calls = []
    def review(*args, **kwargs):
        calls.append(args)
        return {'requirements':[{'index':0,'covered':True,'source_ids':['source'],'reason':'visible matching action'}]}
    result = assess(Settings(data_dir=tmp_path), state, generate=review)
    assert not result['ready'], 'An image hash is not a source-bound approval receipt'
    assert not calls, 'A review bound to another source must not be submitted as approved evidence'


def test_non_rendering_review_metadata_does_not_allow_duplicate_render():
    source = {'id':'source','sha256':'current','source_quality':'clean-source','editing_eligible':True,
        'functional_review':{'reviewed':True,'source_sha256':'current','observed_actions':['folding'],
            'checked_at':100,'reason':'visible folding'}}
    state = {'sources':[source], 'script_id':'script', 'voice_id':'voice', 'daily_quality':{}}
    later = copy.deepcopy(state)
    later['sources'][0]['functional_review']['checked_at'] = 200
    later['sources'][0]['functional_review']['reason'] = 'same folding observed again'
    assert input_signature(state) == input_signature(later), 'Review timestamps and prose are not new render inputs'


def test_capacity_single_probe_is_atomic_across_simultaneous_clients(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from hotpost import model_service as service
    root = tmp_path / 'writing'
    now = [100]
    monkeypatch.setattr(service.time, 'time', lambda:now[0])
    monkeypatch.setattr(service.random, 'uniform', lambda *args:1)
    now[0] = service.capacity_failure(root/'a') + 1
    barrier = Barrier(8)
    def submit(index):
        barrier.wait()
        try:
            return service.before_call(root/str(index))
        except service.ModelServiceUnavailable:
            return 'waiting'
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(submit, range(8)))
    assert values.count(True) == 1
    assert values.count('waiting') == 7


def test_older_inflight_success_does_not_clear_new_capacity_cooldown(tmp_path, monkeypatch):
    from hotpost import model_service as service
    root = tmp_path / 'writing'
    now = [100]
    monkeypatch.setattr(service.time, 'time', lambda:now[0])
    monkeypatch.setattr(service.random, 'uniform', lambda *args:1)
    assert service.before_call(root/'old-call') is False
    retry_at = service.capacity_failure(root/'failed-call')
    service.response_received(root/'old-call')
    try:
        service.before_call(root/'new-call')
    except service.ModelServiceUnavailable as exc:
        assert exc.retry_at == retry_at
    else:
        raise AssertionError('An old call succeeded without performing the designated recovery probe')


from test_daily_quality import ready, finish, issue


def test_new_render_after_quality_script_rewrite_counts_as_real_repair(ready):
    studio, task_id = ready
    finish(studio, task_id, issue('old-edit', 'script_fact'))
    rewrite = studio.store.claim(task_id=task_id)
    assert rewrite['kind'] == 'rewrite'
    studio.store.finish(rewrite, {'text':'새 제품 대본입니다.'}, lambda s,db,r:studio._accept(s,rewrite,r,db))
    current = studio.store.get(task_id)
    def new_render(state, db):
        new_voice = {**state['voices'][0], 'id':'new-voice', 'script_id':state['script_id']}
        state['voices'].append(new_voice)
        state.update(voice_id=new_voice['id'], approved_voice_id=new_voice['id'])
        new_edit = {**state['edits'][0], 'id':'new-render', 'script_id':state['script_id'], 'voice_id':new_voice['id']}
        job = {'kind':'edit', 'payload':{'voice_id':new_voice['id'],'script_id':state['script_id']}}
        studio._accept(state, job, new_edit, db)
    studio.store.change(task_id, new_render)
    result = studio.store.get(task_id)
    assert len(result['edits']) == 2
    assert result['daily_quality']['repair_round'] == 1, 'A new real render repairing quality findings consumes the same task-wide cap'
