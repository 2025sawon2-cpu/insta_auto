"""New automatic source reruns must consume later inventory without changing voice/history."""
import copy

import pytest

from tests.test_studio_workflow import prepared, small_inventory_contract, complete


def test_explicit_automatic_reanalysis_waits_then_freezes_new_inventory(prepared, monkeypatch):
    studio, task = prepared
    complete(studio, task)
    def pin(s, db):
        s['runs'][-1]['inputs']['source_ids'] = ['source1']
        s['reviewed_scene_rules'] = [{'source_sha256': 'old', 'pattern': '.'}]
    before = studio.store.change(task, pin)
    old = copy.deepcopy(before['runs'][-1])
    monkeypatch.setattr(studio, 'ensure_source_collection', lambda *a: None)
    goal = {'ready': False, 'source_ids': ['source1'], 'minimum_total': 5}
    monkeypatch.setattr('hotpost.studio_sources.source_goal', lambda *a: goal)
    monkeypatch.setattr('hotpost.source_policy.goal_message', lambda *a: '5 sources needed')
    studio.action(task, 'make-video', {'source_selection_mode': 'automatic'})
    waiting = studio.store.get(task)
    assert waiting['status'] == 'source_wait'
    assert waiting['voice_id'] == before['voice_id']
    assert waiting['script_id'] == before['script_id']
    assert waiting['edit_id'] is None
    assert not waiting.get('reviewed_scene_rules')
    assert 'source_ids' not in waiting['runs'][-1]['inputs']
    assert waiting['runs'][-2] == old
    ids = [f'source{i}' for i in range(1, 6)]
    goal.update(ready=True, source_ids=ids)
    studio.store.change(task, lambda s, db: studio.advance_workflow(s, db))
    queued = [j for j in studio.store.jobs(task) if j['status'] == 'queued']
    assert [j['kind'] for j in queued] == ['edit']
    claimed = studio.store.claim()
    assert claimed['payload']['source_ids'] == ids
    assert claimed['payload']['voice_id'] == before['voice_id']
    frozen = studio.store.get(task)
    assert frozen['runs'][-1]['inputs']['source_ids'] == ids
    assert frozen['runs'][-2] == old
    # Once submitted, later inventory cannot mutate that edit's input binding.
    goal['source_ids'] = ids + ['source6']
    assert studio.store.get(task)['runs'][-1]['inputs']['source_ids'] == ids


def test_manual_selection_after_automatic_feedback_keeps_exclusions(prepared, monkeypatch):
    studio, task = prepared
    complete(studio, task)
    studio.action(task, 'save-feedback', {'source_selection_mode': 'automatic'})
    monkeypatch.setattr(studio, 'ensure_source_collection', lambda *a: None)
    monkeypatch.setattr('hotpost.studio_sources.source_goal',
                        lambda *a: {'ready': True, 'source_ids': ['source1', 'source2']})
    studio.action(task, 'make-video', {'source_ids': ['source1']})
    queued = [j for j in studio.store.jobs(task) if j['status'] == 'queued']
    assert [j['kind'] for j in queued] == ['edit']
    assert studio.store.claim()['payload']['source_ids'] == ['source1']
    assert studio.store.get(task)['runs'][-1]['inputs']['source_selection_mode'] == 'manual'


@pytest.mark.parametrize('data', [
    {'source_selection_mode': 'automatic', 'source_ids': ['source1']},
    {'source_selection_mode': 'bogus'},
])
def test_invalid_auto_selection_is_atomic(prepared, data):
    studio, task = prepared
    before = studio.store.get(task)
    jobs = studio.store.jobs(task)
    with pytest.raises(ValueError):
        studio.action(task, 'make-video', data)
    assert studio.store.get(task) == before
    assert studio.store.jobs(task) == jobs


def test_old_core_does_not_fill_new_automatic_inventory_before_reanalysis(prepared):
    from hotpost.studio_sources import source_goal
    from hotpost.source_functional import REVIEW_POLICY
    studio,task=prepared
    state=studio.store.get(task)
    old=copy.deepcopy(state['sources'][0])
    state['runs'][-1]['inputs']['source_selection_mode']='automatic'
    state['sources'][0]['functional_review']['policy']='visual-product-presentation-v4-full-reference-features'
    assert source_goal(state,1)['count']==0
    assert not source_goal(state,1)['core_ready']
    state['sources'][0]['functional_review']['policy']=REVIEW_POLICY
    assert source_goal(state,1)['count']==1
    assert source_goal(state,1)['core_ready']
    assert studio.store.get(task)['sources'][0]==old


def test_identity_only_pending_reaches_normal_local_review(prepared,monkeypatch):
    studio,task=prepared
    state=studio.store.get(task)
    state['manifest_path']='existing-manifest.json'
    state['runs'][-1]['inputs']['source_selection_mode']='automatic'
    monkeypatch.setattr('hotpost.source_overlay_review.needs_overlay_review',lambda s:False)
    monkeypatch.setattr('hotpost.source_presentation.needs_pending_presentation_review',lambda s:False)
    monkeypatch.setattr(studio.store,'checkpoint',lambda *a:None)
    called=[]
    monkeypatch.setattr(studio,'_review_source_records',lambda state,job,rows,progress:(called.extend(rows) or rows,None))
    result=studio._review_pending_local_sources(state,{},lambda *a:None)
    assert result['local_deferred_review']
    assert [r['id'] for r in called]==['source1']
    assert not result['searches'] and not result['attempted_urls']


def test_local_identity_review_resumes_cached_items_and_accepts_real_round(prepared,monkeypatch):
    import json
    from pathlib import Path
    from hotpost.source_functional import needs_identity_reanalysis, REVIEW_POLICY
    studio,task=prepared
    manifest=studio.folder(task)/'identity-manifest.json'
    manifest.write_text('{}',encoding='utf8')
    def stage(s,db):
        s['manifest_path']=str(manifest)
        s['runs'][-1]['inputs']['source_selection_mode']='automatic'
        db.execute("UPDATE jobs SET status='done' WHERE task_id=?",(task,))
        studio.store.enqueue(db,task,'collect_sources',{'round':4,'run_id':s['run_id']},'identity-review-test')
    studio.store.change(task,stage)
    monkeypatch.setattr('hotpost.source_overlay_review.needs_overlay_review',lambda s:False)
    monkeypatch.setattr('hotpost.source_presentation.needs_pending_presentation_review',lambda s:False)
    monkeypatch.setattr('hotpost.studio_automation.refresh_resolved_subject',lambda *a:False)
    monkeypatch.setattr('hotpost.reference_context.post_caption',lambda *a:'')
    calls=[]
    def review(state,job,rows,progress):
        for row in rows:
            if needs_identity_reanalysis(state,row):
                calls.append(row['sha256'])
                row['functional_review']['policy']=REVIEW_POLICY
            studio._checkpoint_deferred_review(job,row)
        return rows,None
    monkeypatch.setattr(studio,'_review_source_records',review)
    first=studio.store.claim('sources')
    result=studio._review_pending_local_sources(studio.store.get(task),first,lambda *a:None)
    assert result['round']==4 and len(calls)==1
    saved=first['checkpoint']['identity_source_review']
    assert len(json.loads(Path(saved['path']).read_text('utf8'))['sources'])==1
    studio.store.defer(first,'test service boundary',0,waiting=True)
    second=studio.store.claim('sources')
    assert second['id']==first['id']
    resumed=studio._review_pending_local_sources(studio.store.get(task),second,lambda *a:None)
    assert len(calls)==1, 'completed item must not run the model again'
    studio.store.finish(second,resumed,lambda s,db,r:studio._accept(s,second,r,db))
    after=studio.store.get(task)
    assert after['sources'][0]['functional_review']['policy']==REVIEW_POLICY
    assert after['source_acquisition']['round']==5
    assert after['source_acquisition']['rounds'][-1]['round']==4
    assert next(j for j in studio.store.jobs(task) if j['id']==second['id'])['status']=='done'
