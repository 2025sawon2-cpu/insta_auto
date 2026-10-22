import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost.editing_adapter import _atomic_json
from hotpost.source_batches import TaskBatchReviewer, cached_records
from hotpost.studio_sources import SourceAcquisitionMixin


def fixture(tmp_path):
    settings=Settings(data_dir=tmp_path)
    root=settings.source_dir/'ref-batch';root.mkdir(parents=True)
    rows=[]
    for i in range(4):
        path=root/f'{i}.mp4';path.write_bytes(f'actual fixture {i}'.encode())
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append({'id':f'source-{i}','path':str(path),'sha256':sha,'source_quality':'clean-source',
            'origin_url':f'https://youtube.com/watch?v={i}', 'video_meta':{'duration':8,'width':720,'height':1280},
            'source_role':'core','functional_review':{'reviewed':True,'same_core_function':True,'source_sha256':sha,
                'context_usable':True,'observed_actions':['repair'],'evidence_frames':['frame.jpg']}})
    state={'id':'task','reference_duration':10,'sources':[],'voices':[],'automation':{'active':True}}
    from hotpost.source_policy import current_policy
    state['source_policy']=current_policy(settings)
    job={'id':'job','task_id':'task','kind':'collect_sources','claim_token':'token12345','payload':{},'checkpoint':{}}
    saved=[]
    store=SimpleNamespace(get=lambda _:copy.deepcopy(state),assert_owned=lambda _:None,
                          checkpoint=lambda j,c:saved.append(copy.deepcopy(c)))
    def source_records(files,manifest):return copy.deepcopy(rows)
    studio=SimpleNamespace(settings=settings,store=store,_source_records=source_records,
        _recover_local_source_intervals=lambda *a,**k:None)
    studio._checkpoint_deferred_review=lambda j,s:SourceAcquisitionMixin._checkpoint_deferred_review(studio,j,s)
    manifest=root/'batch-0001.json'
    _atomic_json(manifest,{'candidates':[{'downloaded_file':Path(s['path']).name} for s in rows]})
    return studio,state,job,manifest,rows


def test_partial_batch_review_is_bound_to_immutable_manifest_and_file_sha(tmp_path):
    studio,state,job,path,rows=fixture(tmp_path)
    def review(s,j,merged,progress):
        for source in merged:studio._checkpoint_deferred_review(j,source)
        return merged,None
    studio._review_source_records=review
    assert TaskBatchReviewer(studio,job,lambda *a:None)(path)['ready']
    assert len(cached_records(studio,job))==4
    path.write_text('{}','utf8')
    from hotpost.source_preparation import PreparationEvidenceWaiting
    with pytest.raises(PreparationEvidenceWaiting):cached_records(studio,job)


def test_voice_finishing_during_review_checks_received_remainder_first(tmp_path):
    studio,state,job,path,rows=fixture(tmp_path);calls=[]
    def review(s,j,merged,progress):
        calls.append(len(merged))
        selected=merged[:2] if len(calls)==1 else merged
        for source in selected:studio._checkpoint_deferred_review(j,source)
        state.update(voice_id='voice',voices=[{'id':'voice','duration':24}])
        return selected,{'reason':'quota_met'}
    studio._review_source_records=review
    result=TaskBatchReviewer(studio,job,lambda *a:None)(path)
    assert calls==[4,4] and result['ready']
    assert result['goal']['required_seconds']==30


def test_lost_claim_cannot_start_batch_review(tmp_path):
    studio,state,job,path,rows=fixture(tmp_path)
    def lost(_):raise RuntimeError('claim lost')
    studio.store.assert_owned=lost
    studio._review_source_records=lambda *a:pytest.fail('late model review')
    with pytest.raises(RuntimeError,match='claim lost'):TaskBatchReviewer(studio,job,None)(path)
    assert not job['checkpoint']


def test_paused_task_preserves_input_without_starting_model_review(tmp_path):
    studio,state,job,path,rows=fixture(tmp_path)
    state['automation']['paused_by_user']=True
    studio._review_source_records=lambda *a:pytest.fail('paused model review')
    from hotpost.studio_pause import StudioPaused
    with pytest.raises(StudioPaused):TaskBatchReviewer(studio,job,None)(path)
    assert path.is_file() and not job['checkpoint']


def test_batch_cache_cannot_be_used_for_a_different_product_context(tmp_path):
    studio,state,job,path,rows=fixture(tmp_path)
    def review(s,j,merged,progress):
        for source in merged:studio._checkpoint_deferred_review(j,source)
        return merged,None
    studio._review_source_records=review
    TaskBatchReviewer(studio,job,None)(path)
    state['product']='different product'
    from hotpost.source_preparation import PreparationEvidenceWaiting
    with pytest.raises(PreparationEvidenceWaiting):cached_records(studio,job)


def test_latest_review_updates_existing_source_metadata_for_goal(tmp_path):
    studio,state,job,path,rows=fixture(tmp_path)
    state['sources']=copy.deepcopy(rows)
    for row in state['sources']:
        row['editing_eligible']=False
        row['functional_review']={}
    def review(s,j,merged,progress):
        for source in rows:studio._checkpoint_deferred_review(j,source)
        return copy.deepcopy(rows),None
    studio._review_source_records=review
    assert TaskBatchReviewer(studio,job,None)(path)['ready']


def test_manual_exclusion_during_review_cannot_satisfy_goal(tmp_path):
    studio,state,job,path,rows=fixture(tmp_path)
    def review(s,j,merged,progress):
        for source in rows:studio._checkpoint_deferred_review(j,source)
        state['sources']=copy.deepcopy(rows)
        for source in state['sources']:
            source['manual_usage_review']={'editing_eligible':False,'reason':'user exclusion'}
        return copy.deepcopy(rows),None
    studio._review_source_records=review
    assert not TaskBatchReviewer(studio,job,None)(path)['ready']


def test_new_batch_rescues_received_intervals_before_another_download(tmp_path):
    studio,state,job,path,rows=fixture(tmp_path)
    state.update(voice_id='voice',voices=[{'id':'voice','duration':24}])
    calls=[]
    def review(s,j,merged,progress):
        limited=copy.deepcopy(merged)
        for source in limited:
            source['reviewed_intervals']=[{'source_start':0.,'source_end':1.}]
            studio._checkpoint_deferred_review(j,source)
        return limited,None
    def rescue(s,j,progress,*,inventory_only=False):
        assert inventory_only
        calls.append([source['sha256'] for source in s['sources']])
        return {'sources':copy.deepcopy(rows)}
    studio._review_source_records=review
    studio._recover_local_source_intervals=rescue
    result=TaskBatchReviewer(studio,job,None)(path)
    assert result['ready'] and len(calls)==1
    assert result['goal']['usable_seconds']==32
    assert all('reviewed_intervals' not in s for s in cached_records(studio,job).values())


@pytest.mark.parametrize('existing_edit', [False, True])
@pytest.mark.parametrize('montage', [False, True])
def test_montage_repair_can_use_new_reviewed_ranges_without_new_original_files(tmp_path, existing_edit, montage):
    studio,state,job,path,rows=fixture(tmp_path)
    from hotpost.source_policy import montage_policy
    if montage:
        # This regression preserves the saved v4 interval-reuse contract.
        policy=montage_policy(studio.settings)
        policy.update(version=4,minimum_total=1)
        policy.pop('source_diversity_policy');policy.pop('search_minimums')
        state['source_policy']=policy
    state['sources']=copy.deepcopy(rows)
    for row in state['sources']:
        row['reviewed_intervals']=[{'source_start':0.,'source_end':1.}]
    if existing_edit:state['edit_id']='existing-edit'
    job['payload']['daily_quality_repair']=True
    def review(s,j,merged,progress):
        # Same actual parent files, independently reviewed larger physical ranges.
        for source in rows:studio._checkpoint_deferred_review(j,source)
        return copy.deepcopy(rows),None
    studio._review_source_records=review
    result=TaskBatchReviewer(studio,job,None)(path)
    assert result['goal']['ready']
    assert result['ready'] is montage
    assert {s['sha256'] for s in rows}=={s['sha256'] for s in state['sources']}
