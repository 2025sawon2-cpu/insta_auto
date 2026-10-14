import copy
import hashlib
import json

import pytest

from hotpost import cover_product_crop,scene_requirements
from test_daily_quality import ready


def queue(studio,task):
    def mutate(state,db):
        state['daily_quality']['pending']='reedit'
        studio.advance_daily_quality(state,db,state['scripts'][0],state['voices'][0],
            state['edits'][0] if state['edits'] else None)
    return studio.store.change(task,mutate)


def prepare(studio,task):
    def initialize(state,db):
        db.execute("UPDATE jobs SET status='done' WHERE task_id=?",(task,))
        state['daily_quality'].update(repair_round=0,feedback=[{'kind':'scene_gap','scope':'cover',
            'reason':'실제 사용 장면에 얼굴이 보여 표지가 불가함','search_query':'제품 디테일'}],
            thumbnail_lines=['제품의 숨은 매력','무엇이 다를까요?'])
    return studio.store.change(task,initialize)


def test_completed_job_survives_contract_change_and_new_actual_cover_method_queues_once(ready,monkeypatch):
    studio,task=ready;prepare(studio,task)
    state=queue(studio,task)
    old=studio.store.claim(task_id=task);assert old['kind']=='quality_reedit'
    old_signature=old['payload']['repair_input_signature']
    studio.store.finish(old,{'no_render':True},lambda *_:None)
    state=queue(studio,task)
    assert state['daily_quality']['pending']=='scene_wait'
    assert state['daily_quality']['progress_policy']['decision']['action']=='stop_method'
    assert studio.store.claim(task_id=task) is None
    assert len([j for j in studio.store.jobs(task) if j['kind']=='quality_reedit'])==1
    monkeypatch.setattr(cover_product_crop,'PROPOSAL_INSTRUCTION',cover_product_crop.PROPOSAL_INSTRUCTION+' New actual crop contract.')
    state=queue(studio,task)
    assert state['daily_quality']['pending']=='scene_wait'
    assert len([j for j in studio.store.jobs(task) if j['kind']=='quality_reedit'])==1
    studio.store.change(task,lambda s,db:s['daily_quality'].update(thumbnail_lines=['제품의 다른 장점','어떤 촉감일까요?']))
    state=queue(studio,task)
    current=[j for j in studio.store.jobs(task) if j['kind']=='quality_reedit']
    assert len(current)==2 and sum(j['status']=='queued' for j in current)==1
    new=next(j for j in current if j['status']=='queued')
    with studio.store.connect() as db:
        payload=json.loads(db.execute('SELECT payload FROM jobs WHERE id=?',(new['id'],)).fetchone()['payload'])
    assert payload['repair_input_signature']!=old_signature
    assert payload['repair_signature_policy']==scene_requirements.REPAIR_SIGNATURE_POLICY
    queue(studio,task)
    assert len([j for j in studio.store.jobs(task) if j['kind']=='quality_reedit'])==2
    assert state['daily_quality']['repair_round']==0 and state['daily_quality']['max_repairs']==3
    assert next(j for j in studio.store.jobs(task) if j['id']==old['id'])['status']=='done'


def test_pre_contract_queue_failure_method_history_is_preserved_without_reopening(ready):
    studio,task=ready;state=prepare(studio,task)
    base=scene_requirements.input_signature(state)
    legacy=hashlib.sha256(json.dumps({'base':base,'constraints':[]},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    def legacy_job(state,db):
        key=f"quality:{state['run_id']}:0:sources:{legacy[:16]}:quality_reedit:{state['edit_id']}"
        identity=studio.store.enqueue(db,task,'quality_reedit',{'repair_input_signature':legacy,'repair_signature_policy':'repair-render-v2-required-intervals'},key)
        db.execute("UPDATE jobs SET status='done' WHERE id=?",(identity,))
        from hotpost.quality_progress import permit, finish_attempt
        permit(state,'reedit',reserve=True,job_id=identity)
        finish_attempt(state,{'id':identity},failed=True)
    studio.store.change(task,legacy_job)
    state=queue(studio,task)
    jobs=[j for j in studio.store.jobs(task) if j['kind']=='quality_reedit']
    assert len(jobs)==1 and jobs[0]['status']=='done'
    assert state['daily_quality']['repair_round']==0 and state['daily_quality']['pending']=='scene_wait'
    assert state['daily_quality']['progress_policy']['decision']['action']=='stop_method'


def test_fourth_repair_is_allowed_for_new_actual_cover_method_without_usage_reset(ready,monkeypatch):
    studio,task=ready;prepare(studio,task)
    studio.store.change(task,lambda state,db:state['daily_quality'].update(repair_round=3))
    monkeypatch.setattr(cover_product_crop,'POLICY',cover_product_crop.POLICY+'-changed')
    state=queue(studio,task)
    assert state['daily_quality']['repair_round']==3 and state['daily_quality']['max_repairs']==3
    assert state['daily_quality']['pending']=='reediting' and state['automation']['active']
    assert len([j for j in studio.store.jobs(task) if j['kind']=='quality_reedit' and j['status']=='queued'])==1


def test_same_contract_ignores_review_timestamps_and_reference_count_changes(ready):
    from hotpost import scene_analysis
    studio,task=ready;state=prepare(studio,task)
    before=scene_requirements.repair_render_signature(state)
    held=list(scene_analysis.analyze_shots.__code__.co_consts)
    changed=copy.deepcopy(state)
    changed['daily_quality'].update(checked_at=999,collection_attempt=7,condition_receipt={'at':999,'reason':'bookkeeping only'})
    for source in changed['sources']:source['functional_review']['checked_at']=999
    assert held and scene_requirements.repair_render_signature(changed)==before
