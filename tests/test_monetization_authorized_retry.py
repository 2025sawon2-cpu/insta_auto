from concurrent.futures import ThreadPoolExecutor
import pytest

from hotpost.monetization_store import MonetizationStore,MonetizationConflict
from test_monetization import followup_fixture


def failed_attempt(tmp_path):
    store=MonetizationStore(tmp_path)
    state=store.prepare('task','mr.salrim','Reference',{},'ggul_dol2')
    effect=store.reserve_effect(state,'product_discovery',{'keyword':'나도','attempt_count':1})
    state=store.resolve_effect('task',effect,'error',{'reason':'before submit','comment_submit_called':False},
                               {'error':'before submit','error_evidence_path':'prior-error.json'})
    return store,state,effect


def test_explicit_retry_preserves_old_attempt_and_consumes_one_grant(tmp_path):
    store,failed,old_effect=failed_attempt(tmp_path)
    approved=store.authorize_product_retry('task',old_effect,'사용자: 좋아 해봐',expected=failed['revision'])
    new_effect=store.reserve_effect(approved,'product_discovery',{'keyword':'나도','attempt_count':1})
    current=store.get('task')
    effect=store.effects(current)[0]
    assert new_effect!=old_effect and current['product_retry']['status']=='consumed'
    assert effect['details']['attempt_count']==2
    history=effect['details']['previous_attempts']
    assert history[0]['id']==old_effect and history[0]['status']=='error'
    assert history[0]['details']['reason']=='before submit'
    assert current['product_retry']['previous_error_evidence_path']=='prior-error.json'
    with pytest.raises(MonetizationConflict): store.reserve_effect(current,'product_discovery',{})
    MonetizationStore(tmp_path).recover_abandoned()
    assert store.get('task')['status']=='error'
    assert store.effects(current)[0]['status']=='unknown'
    with pytest.raises(MonetizationConflict):
        store.authorize_product_retry('task',new_effect,'stale/unknown request',expected=store.get('task')['revision'])


def test_retry_is_not_automatic_and_approval_cannot_be_replayed(tmp_path):
    service,calls,_,_=followup_fixture(tmp_path,fail_dm=True)
    service.store.configure_automation(False,'ouraccount')
    service.run_saved('work-1');service.close()
    failed=service.get('work-1')
    service.run_saved('work-1');service.close()
    assert len([row for row in calls if row[0]=='comment'])==1
    service.retry_product_authorized('work-1',failed['effect_id'],'user approved one retry',failed['revision'])
    service.close()
    current=service.get('work-1')
    assert len([row for row in calls if row[0]=='comment'])==2
    assert current['effects'][0]['details']['attempt_count']==2
    assert len(current['effects'][0]['details']['previous_attempts'])==1
    with pytest.raises(MonetizationConflict):
        service.retry_product_authorized('work-1',failed['effect_id'],'same approval',current['revision'])
    assert len([row for row in calls if row[0]=='comment'])==2


def test_racing_reservations_cannot_use_approval_twice(tmp_path):
    store,state,effect=failed_attempt(tmp_path)
    approved=store.authorize_product_retry('task',effect,'user instruction',expected=state['revision'])
    def reserve(_):
        try:return store.reserve_effect(approved,'product_discovery',{})
        except MonetizationConflict:return None
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(reserve,range(2)))
    assert sum(row is not None for row in results)==1


def test_generic_state_changes_cannot_invent_retry_permission(tmp_path):
    store,state,effect=failed_attempt(tmp_path)
    with pytest.raises(ValueError):store.change('task',{'product_retry':{'status':'authorized'}})
    with pytest.raises(ValueError):store.authorize_product_retry('task',effect,'',expected=state['revision'])
    with pytest.raises(MonetizationConflict):store.authorize_product_retry('task',effect,'user',expected=state['revision']-1)
    assert store.get('task')==state


def test_same_approved_attempt_can_continue_only_before_first_submit(tmp_path):
    store,state,old=failed_attempt(tmp_path)
    approved=store.authorize_product_retry('task',old,'one comment approved',expected=state['revision'])
    effect=store.reserve_effect(approved,'product_discovery',{'attempt_count':2})
    failed=store.resolve_effect('task',effect,'error',{'reason':'rerender','comment_submit_called':False},
                                {'error':'rerender','error_evidence_path':'rerender.json'})
    with pytest.raises(MonetizationConflict):
        store.continue_unsubmitted_product('task',effect,'wrong approval',expected=failed['revision'])
    continued=store.continue_unsubmitted_product('task',effect,continued_id:=failed['product_retry']['id'],expected=failed['revision'])
    assert continued['effect_id']==effect and continued['status']=='running'
    details=store.effects(continued)[0]['details']
    assert details['attempt_count']==2 and len(details['previous_attempts'])==1
    assert details['pre_submit_repairs'][0]['error_evidence_path']=='rerender.json'
    after_submit=store.resolve_effect('task',effect,'error',{'comment_submit_called':True},{'error':'DM not received'})
    with pytest.raises(MonetizationConflict):
        store.continue_unsubmitted_product('task',effect,continued_id,expected=after_submit['revision'])
