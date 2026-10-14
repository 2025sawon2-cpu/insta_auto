"""Independent cumulative repair accounting with durable local test stores."""
import copy
from types import SimpleNamespace

import pytest

from hotpost.studio_store import StudioStore
from hotpost.studio_runtime.lifecycle import LifecycleMixin


def state_fixture(prior=(), counter=0):
    return {'edits':copy.deepcopy(list(prior)), 'edit_id':None,
        'approved_voice_id':'approved-voice', 'runs':[],
        'automation':{'active':False},
        'daily_quality':{'repair_round':counter,'max_repairs':3,
            'scene_no_progress':2,'collection_attempt':7,'pending':'reediting',
            'feedback':[{'kind':'scene_gap','beat_id':'b8','reason':'Original actual product mismatch'}]}}


def job_fixture(kind='quality_reedit'):
    return {'id':'completed-render-job','kind':kind,'payload':{
        'voice_id':'approved-voice','edit_id':None,'repair_input_signature':'actual-new-input'}}


def result_fixture(tmp_path):
    path=tmp_path/'actual-preview.mp4';path.write_bytes(b'new successfully rendered bytes')
    return {'id':'actual-new-edit','voice_id':'approved-voice','script_id':'script',
            'preview_path':str(path)}


@pytest.mark.parametrize('counter',[0,2])
def test_failed_pre_render_attempts_first_success_is_baseline_without_resetting_counter(tmp_path,counter):
    state=state_fixture([{'id':'pre-render-failed','no_render':True}],counter)
    result=result_fixture(tmp_path);job=job_fixture()
    original=copy.deepcopy(state['daily_quality'])
    LifecycleMixin()._accept(state,job,result)
    q=state['daily_quality'];receipt=q['render_accounting'][0]
    assert q['repair_round']==counter and q['max_repairs']==3
    assert receipt==result['repair_accounting']
    assert receipt['prior_edit_ids']==[] and receipt['classification']=='initial_baseline'
    assert receipt['repair_charge']==0 and receipt['repair_round_before']==receipt['repair_round_after']==counter
    assert (receipt['job_id'],receipt['edit_id'])==(job['id'],result['id'])
    for key in ('feedback','scene_no_progress','collection_attempt'):
        assert q[key]==original[key]


@pytest.mark.parametrize('old_preview',['missing_field','nonexistent_path','deleted_actual_file'])
def test_missing_old_preview_cannot_erase_committed_render_history_or_repair_charge(tmp_path,old_preview):
    prior={'id':'accepted-old-render','voice_id':'approved-voice'}
    if old_preview!='missing_field':prior['preview_path']=str(tmp_path/'old-preview.mp4')
    if old_preview=='deleted_actual_file':
        old=tmp_path/'old-preview.mp4';old.write_bytes(b'previous accepted render');old.unlink()
    state=state_fixture([prior],2);saved_prior=copy.deepcopy(state['edits'])
    result=result_fixture(tmp_path)
    LifecycleMixin()._accept(state,job_fixture(),result)
    q=state['daily_quality'];audit=q['render_accounting'][0]
    assert q['repair_round']==3 and q['max_repairs']==3
    assert audit['prior_edit_ids']==['accepted-old-render'] and audit['repair_charge']==1
    assert audit['classification']=='quality_repair'
    assert state['edits'][:-1]==saved_prior


def test_three_existing_committed_renders_charge_one_next_repair_not_all_history(tmp_path):
    prior=[{'id':f'accepted-{i}','preview_path':str(tmp_path/f'old-{i}.mp4')} for i in range(3)]
    state=state_fixture(prior,2);result=result_fixture(tmp_path)
    LifecycleMixin()._accept(state,job_fixture(),result)
    receipt=result['repair_accounting']
    assert receipt['prior_edit_ids']==['accepted-0','accepted-1','accepted-2']
    assert (receipt['repair_round_before'],receipt['repair_charge'],receipt['repair_round_after'])==(2,1,3)
    assert state['daily_quality']['repair_round']==3


@pytest.mark.parametrize('prior',[[],[{'id':'previous-accepted-render'}]])
def test_no_render_has_no_charge_and_no_new_receipt_even_with_existing_counter(tmp_path,prior):
    state=state_fixture(prior,2);saved=copy.deepcopy(state)
    LifecycleMixin()._accept(state,job_fixture(),{'no_render':True,'repair_cap_reached':True})
    assert state['edits']==saved['edits']
    assert state['daily_quality']['repair_round']==2 and state['daily_quality']['max_repairs']==3
    assert not state['daily_quality'].get('render_accounting')
    assert not state['daily_quality'].get('rendered_input_signatures')


@pytest.mark.parametrize('prior',[[],[{'id':'accepted-before-restart','preview_path':'gone.mp4'}]])
def test_actual_store_restart_and_duplicate_completion_preserve_exact_accounting(tmp_path,prior):
    store=StudioStore(tmp_path/'isolated-studio')
    initial=state_fixture(prior,2)
    state,_=store.create('independent-accounting','제품',prepare=False,initial=initial)
    store.change(state['id'],lambda s,db:store.enqueue(db,s['id'],'quality_reedit',
        job_fixture()['payload'],'durable-render-test'))
    job=store.claim(task_id=state['id'])
    assert job['kind']=='quality_reedit'
    result=result_fixture(tmp_path)
    store.finish(job,result,lambda s,db,r:LifecycleMixin()._accept(s,job,r))
    saved=store.get(state['id']);quality=copy.deepcopy(saved['daily_quality'])
    assert len(quality['render_accounting'])==1
    assert quality['repair_round']==(3 if prior else 2)
    assert store.jobs(state['id'])[0]['status']=='done'
    restarted=StudioStore(tmp_path/'isolated-studio');restarted.recover()
    restarted.finish(copy.deepcopy(job),copy.deepcopy(result),
        lambda s,db,r:LifecycleMixin()._accept(s,job,r))
    after=restarted.get(state['id'])
    assert after['daily_quality']==quality and after['edits']==saved['edits']
    assert restarted.claim(task_id=state['id']) is None


def test_missing_files_preserve_usage_and_hold_worker_without_new_defect_evidence(tmp_path):
    store=StudioStore(tmp_path/'isolated-cap')
    initial=state_fixture([{'id':f'committed-{i}','preview_path':str(tmp_path/f'deleted-{i}.mp4')}
                           for i in range(4)],3)
    state,_=store.create('cap-history','제품',prepare=False,initial=initial)
    payload=job_fixture()['payload']
    store.change(state['id'],lambda s,db:store.enqueue(db,s['id'],'quality_reedit',payload,'cap-test'))
    class Once:
        calls=0
        def is_set(self):self.calls+=1;return self.calls>1
        def wait(self,*args):pass
    class Worker(LifecycleMixin):
        def _quality_reedit(self,*args):pytest.fail('No renderer call without new actual defect evidence')
    worker=Worker();worker.store=store;worker.stop=Once()
    worker.settings=SimpleNamespace(studio_daily_quality_max_repairs=3)
    worker._worker()
    after=store.get(state['id'])
    assert after['daily_quality']['repair_round']==3 and after['daily_quality']['max_repairs']==3
    assert after['daily_quality']['pending']=='scene_wait'
    assert after['edits']==initial['edits'] and not after['daily_quality'].get('render_accounting')
    assert not after['automation']['active'] and store.jobs(state['id'])[0]['status']=='done'


@pytest.mark.parametrize('kind',['quality_reedit','edit'])
@pytest.mark.parametrize('has_prior',[False,True])
def test_committed_edit_round_metadata_binds_to_exact_cumulative_ledger_in_both_paths(tmp_path,kind,has_prior):
    prior=[{'id':'committed-before','preview_path':'historical-missing.mp4'}] if has_prior else []
    state=state_fixture(prior,2)
    job=job_fixture(kind)
    if kind=='edit':job['payload'].update(quality_repair=True,parent_edit_id='committed-before')
    result=result_fixture(tmp_path);result['quality_repair_round']=999
    LifecycleMixin()._accept(state,job,result)
    expected=3 if has_prior else 2
    assert state['daily_quality']['repair_round']==expected
    assert result['quality_repair_round']==result['repair_accounting']['repair_round_after']==expected
    assert state['edits'][-1]['quality_repair_round']==expected
    assert state['daily_quality']['max_repairs']==3
    frozen=copy.deepcopy(state)
    duplicate=copy.deepcopy(result);duplicate['quality_repair_round']=888
    LifecycleMixin()._accept(state,copy.deepcopy(job),duplicate)
    assert state==frozen and len(state['daily_quality']['render_accounting'])==1


def test_first_real_draft_provisional_one_is_committed_as_zero_not_a_consumed_repair(tmp_path):
    state=state_fixture();job=job_fixture();result=result_fixture(tmp_path)
    result['quality_repair_round']=1
    LifecycleMixin()._accept(state,job,result)
    assert state['daily_quality']['repair_round']==0
    assert result['repair_accounting']['classification']=='initial_baseline'
    assert result['repair_accounting']['repair_charge']==0
    assert result['quality_repair_round']==state['edits'][-1]['quality_repair_round']==0
