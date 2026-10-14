"""Independent real outbox checks for deterministic actual rendering contracts."""
import copy
import gc
import hashlib
from types import SimpleNamespace

import pytest

from hotpost import cover_product_crop, cover_selection, scene_analysis, scene_requirements
from hotpost.daily_quality import DailyQualityMixin, POLICY
from hotpost.scene_requirements import repair_render_signature
from hotpost.studio_store import StudioStore
from hotpost.studio_runtime.lifecycle import LifecycleMixin


def fixture(tmp_path,counter=0):
    source_path=tmp_path/'actual-source.mp4';source_path.write_bytes(b'actual source bytes')
    sha=hashlib.sha256(source_path.read_bytes()).hexdigest()
    source={'id':'source','path':str(source_path),'sha256':sha,'editing_eligible':True,
        'source_quality':'clean-source','reviewed_intervals':[{'source_start':0,'source_end':2}],
        'functional_review':{'reviewed':True,'source_sha256':sha,'same_core_function':True}}
    state={'script_id':'script','voice_id':'voice','approved_voice_id':'voice','edit_id':None,'edits':[],
        'scripts':[{'id':'script','text':'제품 대본'}],
        'voices':[{'id':'voice','script_id':'script','sha256':'voice-sha'}],
        'sources':[source],'run_id':'actual-run','automation':{'active':False},
        'daily_quality':{'policy':POLICY,'pending':'reedit','repair_round':counter,'max_repairs':3,
            'feedback':[{'kind':'scene_gap','scope':'cover','beat_id':'',
                         'reason':'얼굴 없는 제품 표지 부족','search_query':'니트'}],
            'scene_requirements':{'ready':True,'requirements':[]},'thumbnail_lines':['제품','무엇이 다를까?']}}
    store=StudioStore(tmp_path/'isolated-contract-store')
    created,_=store.create('contract-queue','제품',prepare=False,initial=state)
    worker=DailyQualityMixin();worker.store=store
    worker.settings=SimpleNamespace(studio_daily_quality_max_repairs=3)
    return worker,created['id']


def schedule(worker,task):
    def enqueue(state,db):
        state['daily_quality']['pending']='reedit'
        worker.advance_daily_quality(state,db,state['scripts'][0],state['voices'][0],None)
    return worker.store.change(task,enqueue)


def finish_old_pre_render_condition(worker,task):
    schedule(worker,task)
    job=worker.store.claim(task_id=task)
    assert job and job['kind']=='quality_reedit'
    worker.store.finish(job,{'no_render':True},lambda s,db,r:s['daily_quality'].update(pending='recollect'))
    assert worker.store.get(task)['edits']==[]
    return job


def test_done_same_method_contract_change_is_held_and_actual_cover_copy_queues_once(tmp_path,monkeypatch):
    worker,task=fixture(tmp_path);old=finish_old_pre_render_condition(worker,task)
    before=copy.deepcopy(worker.store.get(task));old_signature=old['payload']['repair_input_signature']
    monkeypatch.setattr(cover_product_crop,'POLICY',cover_product_crop.POLICY+'-new-reviewed-geometry-contract')
    changed=schedule(worker,task)
    jobs=worker.store.jobs(task)
    assert len(jobs)==1 and changed['daily_quality']['pending']=='scene_wait'
    assert next(j for j in jobs if j['id']==old['id'])['status']=='done'
    assert worker.store.claim(task_id=task) is None
    worker.store.change(task,lambda s,db:s['daily_quality'].update(thumbnail_lines=['제품의 새 매력','촉감은 어떨까?']))
    changed=schedule(worker,task)
    jobs=worker.store.jobs(task)
    assert len(jobs)==2 and len([j for j in jobs if j['status']=='queued'])==1
    actual=worker.store.claim(task_id=task)
    assert actual['id']!=old['id'] and actual['payload']['repair_input_signature']!=old_signature
    worker.store.recover()
    schedule(worker,task)
    assert len(worker.store.jobs(task))==2
    assert worker.store.get(task)['daily_quality']['repair_round']==before['daily_quality']['repair_round']==0
    assert worker.store.get(task)['edits']==[]


def test_unchanged_contract_and_review_metadata_do_not_redeliver_completed_job(tmp_path):
    worker,task=fixture(tmp_path);old=finish_old_pre_render_condition(worker,task)
    original=repair_render_signature(worker.store.get(task))
    def restate(state,db):
        state['daily_quality']['reviewed_at']=9876
        state['daily_quality']['scene_requirements'].update(checked_at=4567,coverage_reason='Same facts restated')
        state['sources'][0]['functional_review']['reviewed_at']=3456
        state['sources'][0]['review_note']='Same source and approved time windows'
    worker.store.change(task,restate)
    assert repair_render_signature(worker.store.get(task))==original
    for _ in range(2):
        held=schedule(worker,task)
        assert held['daily_quality']['pending']=='scene_wait'
        assert held['daily_quality']['progress_policy']['decision']['action']=='stop_method'
    jobs=worker.store.jobs(task)
    assert len(jobs)==1 and jobs[0]['id']==old['id'] and jobs[0]['status']=='done'
    assert worker.store.claim(task_id=task) is None


def test_actual_completed_render_contract_change_stays_held_until_new_defect_method(tmp_path,monkeypatch):
    worker,task=fixture(tmp_path)
    schedule(worker,task)
    old=worker.store.claim(task_id=task)
    old_signature=old['payload']['repair_input_signature']
    preview=tmp_path/'actual-render.mp4';preview.write_bytes(b'actual committed baseline render')
    rendered={'id':'actual-baseline','script_id':'script','voice_id':'voice','preview_path':str(preview),
              'repair_input_signature':old_signature}
    worker.store.finish(old,rendered,lambda s,db,r:LifecycleMixin()._accept(s,old,r))
    assert worker.store.get(task)['daily_quality']['repair_round']==0
    unchanged=schedule(worker,task)
    assert unchanged['daily_quality']['pending']=='scene_wait' and len(worker.store.jobs(task))==1
    monkeypatch.setattr(cover_selection,'INSTRUCTION',cover_selection.INSTRUCTION+' Actual new image review contract.')
    updated=schedule(worker,task)
    assert len(worker.store.jobs(task))==1 and updated['daily_quality']['pending']=='scene_wait'
    assert updated['daily_quality']['rendered_input_signatures']==[old_signature]
    worker.store.change(task,lambda s,db:s['daily_quality'].update(thumbnail_lines=['제품의 새 질문','이 촉감은 어떨까?']))
    actual=schedule(worker,task)
    assert len(worker.store.jobs(task))==2 and actual['daily_quality']['pending']=='reediting'
    assert actual['daily_quality']['repair_round']==0
    assert actual['daily_quality']['rendered_input_signatures']==[old_signature]


@pytest.mark.parametrize('terminal',['failed','superseded','cancelled'])
def test_confirmed_terminal_same_input_is_not_reset_or_replayed(tmp_path,terminal):
    worker,task=fixture(tmp_path);old=finish_old_pre_render_condition(worker,task)
    with worker.store.transaction() as db:
        db.execute('UPDATE jobs SET status=?,error=? WHERE id=?',
                   (terminal,'Preserved confirmed same-input failure',old['id']))
    held=schedule(worker,task)
    jobs=worker.store.jobs(task)
    assert len(jobs)==1 and jobs[0]['status']==terminal
    assert jobs[0]['error']=='Preserved confirmed same-input failure'
    assert held['daily_quality']['pending']=='scene_wait'
    assert held['daily_quality']['progress_policy']['decision']['action']=='stop_method'
    assert held['daily_quality']['repair_round']==0 and held['daily_quality']['max_repairs']==3


def test_fourth_actual_cover_method_queues_without_altering_historical_counter(tmp_path,monkeypatch):
    worker,task=fixture(tmp_path,3)
    original=copy.deepcopy(worker.store.get(task))
    monkeypatch.setattr(cover_product_crop,'POLICY',cover_product_crop.POLICY+'-new-geometry')
    after=schedule(worker,task)
    assert len(worker.store.jobs(task))==1 and after['daily_quality']['pending']=='reediting'
    assert after['daily_quality']['repair_round']==3 and after['daily_quality']['max_repairs']==3
    assert after['edits']==original['edits'] and not after['automation']['active']


@pytest.mark.parametrize('module,attribute',[
    (cover_product_crop,'PROPOSAL_INSTRUCTION'),(cover_selection,'INSTRUCTION'),
    (scene_analysis,'RANK_INSTRUCTION'),(scene_analysis,'OBSERVE_INSTRUCTION'),
    (scene_requirements,'POLICY'),
])
def test_each_actual_review_contract_change_changes_repair_signature(tmp_path,monkeypatch,module,attribute):
    worker,task=fixture(tmp_path);state=worker.store.get(task)
    before=repair_render_signature(state)
    monkeypatch.setattr(module,attribute,getattr(module,attribute)+' Meaningfully revised contract.')
    assert repair_render_signature(state)!=before


def test_contract_signature_is_stable_across_code_reference_counts_and_gc(tmp_path):
    worker,task=fixture(tmp_path);state=worker.store.get(task)
    code=cover_product_crop.product_crop_candidates.__code__
    before=repair_render_signature(state)
    held=list(code.co_consts)
    assert held and repair_render_signature(state)==before
    del held
    gc.collect()
    assert repair_render_signature(state)==before


def test_loaded_crop_code_change_changes_queue_contract_without_date_nonce(tmp_path,monkeypatch):
    worker,task=fixture(tmp_path);state=worker.store.get(task)
    before=repair_render_signature(state)
    code=cover_product_crop.crop_image.__code__
    changed=code.replace(co_consts=(*code.co_consts,'actual crop implementation revision'))
    assert changed.co_code==code.co_code
    monkeypatch.setattr(cover_product_crop.crop_image,'__code__',changed)
    assert repair_render_signature(state)!=before
