"""Completion uses distinct approved time and core evidence, not platform/file quotas."""
import pytest

from hotpost.source_coverage import usable_seconds, coverage_goal, distinct_seconds
from hotpost.source_policy import current_policy
from hotpost.source_quality import editing_ready, relevance_reasons
from hotpost.source_functional import apply_function_review
from hotpost.source_finder import Candidate
from hotpost.source_targets import select_sources
from hotpost.studio_sources import source_goal
from test_parallel_sources import asset, automatic_review_fixture


def state_with(sources, **kwargs):
    return {'sources':sources, 'source_policy':current_policy(), 'reference_duration':30, **kwargs}


def test_two_sources_can_finish_without_any_tiktok(tmp_path):
    sources = [asset(tmp_path, i, core=i==0) for i in range(2)]
    for source in sources: source['video_meta']['duration']=20
    goal=source_goal(state_with(sources))
    assert goal['ready'] and goal['count']==2 and goal['usable_seconds']==40
    assert goal['required_seconds']==37.5 and goal['duration_basis']=='reference'
    assert goal['platform_preferences']['tiktok']['usable']==0


def test_ten_files_can_be_insufficient_and_context_cannot_replace_core(tmp_path):
    sources=[asset(tmp_path, i, core=i==0) for i in range(10)]
    goal=source_goal(state_with(sources, reference_duration=60))
    assert goal['core_ready'] and not goal['duration_ready'] and not goal['ready']
    sources[0]['source_role']='context_only'
    for source in sources: source['video_meta']['duration']=20
    goal=source_goal(state_with(sources))
    assert goal['duration_ready'] and not goal['core_ready'] and not goal['ready']


@pytest.mark.parametrize('script_id,basis,required', [('selected','voice',62.5), ('stale','reference',37.5)])
def test_only_voice_for_selected_script_sets_required_time(tmp_path, script_id, basis, required):
    state=state_with([asset(tmp_path,0,core=True)], script_id='selected', voice_id='voice',
        voices=[{'id':'voice','script_id':script_id,'duration':50}])
    goal=source_goal(state)
    assert goal['required_seconds']==required and goal['duration_basis']==basis


def test_duplicate_time_missing_metadata_and_stale_core_evidence_do_not_inflate_goal(tmp_path):
    source=asset(tmp_path,0,core=True); source['video_meta']['duration']=40
    assert source_goal(state_with([source,{**source,'id':'duplicate'}]))['usable_seconds']==40
    source['functional_review']['source_sha256']='wrong-file'
    assert not source_goal(state_with([source]))['ready']
    source.pop('video_meta')
    assert source_goal(state_with([source]))['usable_seconds']==0


def test_approved_intervals_are_clipped_validated_and_unioned():
    source={'video_meta':{'duration':20}, 'blur_required':True}
    assert usable_seconds(source)==0
    source['reviewed_intervals']=[{'source_start':0,'source_end':4}, {'source_start':2,'source_end':6},
        {'source_start':8,'source_end':12}, {'source_start':12,'source_end':14},
        {'source_start':-1,'source_end':4}, {'source_start':18,'source_end':25},
        {'source_start':float('nan'),'source_end':20}]
    assert usable_seconds(source)==12
    source['reviewed_intervals']=[]
    assert usable_seconds(source)==0


def test_overlapping_derivatives_do_not_inflate_completion():
    first = {'sha256': 'crop-a', 'original_sha256': 'parent',
             'original_interval': {'start': 10, 'end': 20}, 'video_meta': {'duration': 10}}
    second = {**first, 'sha256': 'crop-b', 'original_interval': {'start': 15, 'end': 25}}
    goal = coverage_goal([first, second], {'reference_duration': 15}, current_policy())
    assert goal['usable_seconds'] == 15
    assert not goal['duration_ready']  # 20 encoded seconds previously passed 18.75.
    assert not goal['visual_repeat_detection_complete']


def test_full_original_and_its_trim_share_one_time_axis():
    parent = {'sha256': 'parent', 'video_meta': {'duration': 40}}
    trim = {'sha256': 'trim', 'original_sha256': 'parent',
            'original_interval': {'start': 10, 'end': 20}, 'video_meta': {'duration': 10}}
    assert distinct_seconds([parent, trim]) == 40


def test_declared_slow_motion_does_not_inflate_original_coverage():
    from hotpost.source_coverage import footage_coordinates
    slow={'sha256':'slow','original_sha256':'parent','original_interval':{'start':10,'end':12},
        'video_meta':{'duration':4},'retiming':{'method':'ffmpeg-setpts','playback_rate':.5,
            'source_sha256':'slow','original_sha256':'parent','full_decode_passed':True}}
    assert footage_coordinates(slow)==(('footage','parent'),10,.5)
    assert distinct_seconds([slow])==2
    parent={'sha256':'parent','video_meta':{'duration':20},'reviewed_intervals':[{'source_start':10.5,'source_end':11.5}]}
    assert distinct_seconds([slow,parent])==2
    slow['retiming']['source_sha256']='changed'
    assert footage_coordinates(slow) is None

@pytest.mark.parametrize('trim_first',[True,False])
def test_source_inventory_keeps_full_parent_and_related_trim_in_either_order(tmp_path,trim_first):
    from hotpost.studio_sources import unique_sources
    parent=asset(tmp_path,0,core=True);parent.update(video_meta={'duration':40},
        origin_url='https://www.tiktok.com/@maker/video/123',frame_hashes=['abcd']*5)
    trim=asset(tmp_path,1,core=True);trim.update(video_meta={'duration':10},
        origin_url=parent['origin_url'],original_sha256=parent['sha256'],
        original_interval={'start':10,'end':20},frame_hashes=parent['frame_hashes'])
    sources=[trim,parent] if trim_first else [parent,trim]
    kept=unique_sources(sources)
    assert {s['id'] for s in kept}=={parent['id'],trim['id']}
    goal=source_goal(state_with(sources))
    assert goal['count']==2 and goal['usable_seconds']==40
    assert goal['original_count']==1 and goal['platform_preferences']['tiktok']['usable']==1

def test_same_url_without_valid_parent_time_mapping_stays_a_duplicate(tmp_path):
    from hotpost.studio_sources import unique_sources
    first=asset(tmp_path,0,core=True);other=asset(tmp_path,1,core=True)
    first['origin_url']=other['origin_url']='https://www.tiktok.com/@maker/video/123'
    assert len(unique_sources([first,other]))==1


def test_same_url_derivatives_keep_disjoint_time_in_source_goal(tmp_path):
    sources = [asset(tmp_path, i, core=True) for i in range(2)]
    for i, source in enumerate(sources):
        source.update(origin_url='https://www.youtube.com/watch?v=sameparent',
                      original_sha256='parent', original_interval={'start': i * 20, 'end': (i+1) * 20},
                      frame_hashes=[], video_meta={'duration': 20})
    goal = source_goal(state_with(sources))
    assert goal['count'] == 2 and goal['usable_seconds'] == 40 and goal['ready']
    sources[1]['original_interval'] = {'start': 10, 'end': 30}
    goal = source_goal(state_with(sources))
    assert goal['count'] == 2 and goal['usable_seconds'] == 30 and not goal['ready']


def test_distinct_parent_windows_and_reviewed_subintervals_are_preserved():
    first = {'sha256': 'crop-a', 'original_sha256': 'parent',
             'original_interval': {'start': 10, 'end': 20}, 'video_meta': {'duration': 10},
             'reviewed_intervals': [{'source_start': 0, 'source_end': 4}]}
    second = {**first, 'sha256': 'crop-b', 'original_interval': {'start': 12, 'end': 22}}
    assert distinct_seconds([first, second]) == 6
    second['original_interval'] = {'start': 30, 'end': 40}
    assert distinct_seconds([first, second]) == 8


def test_context_overlap_cannot_count_twice_as_core():
    first = {'sha256': 'context', 'original_sha256': 'parent',
             'original_interval': {'start': 10, 'end': 20}, 'video_meta': {'duration': 10}}
    second = {**first, 'sha256': 'core', 'original_interval': {'start': 15, 'end': 25},
              'functional_review': {'reviewed': True, 'same_core_function': True,
                  'source_sha256': 'core', 'observed_actions': ['closes flap'], 'evidence_frames': ['frame']}}
    goal = coverage_goal([first, second], {'reference_duration': 10}, current_policy())
    assert goal['usable_seconds'] == 15 and goal['core_seconds'] == 10


def test_file_identity_without_parent_and_different_parents_remain_separate():
    first = {'sha256': 'a', 'video_meta': {'duration': 10}}
    assert distinct_seconds([first, dict(first)]) == 10
    assert distinct_seconds([first, {**first, 'sha256': 'b'}]) == 20
    assert distinct_seconds([{**first, 'original_sha256': 'x', 'original_interval': {'start': 0, 'end': 10}},
                             {**first, 'sha256': 'b', 'original_sha256': 'y', 'original_interval': {'start': 0, 'end': 10}}]) == 20


@pytest.mark.parametrize('interval', [{'start': 0, 'end': 100}, {'start': -5, 'end': 5},
                                     {'start': 0, 'end': float('nan')}, {'start': 'bad', 'end': 10}])
def test_unverified_parent_mapping_cannot_inflate_duration(interval):
    source = {'sha256': 'a', 'original_sha256': 'parent', 'original_interval': interval,
              'video_meta': {'duration': 10}}
    assert distinct_seconds([source, dict(source)]) == 10


def test_similarity_is_warning_before_review_and_actual_negative_review_still_rejects():
    candidate=Candidate('https://youtube.com/watch?v=weak','youtube', title='other subject',query='garlic',
        similarity=.05,semantic_similarity=.1,hash_similarity=.01, file_sha256='hash')
    meta={'duration':20,'width':720,'height':1280}
    assert not relevance_reasons(candidate,meta,'functional')
    assert relevance_reasons(candidate,meta,'product')
    candidate.functional_review={'reviewed':True,'same_core_function':False}
    assert relevance_reasons(candidate,meta,'functional')==['different_core_function']


def test_new_pending_source_needs_real_review_receipt(tmp_path):
    source=asset(tmp_path,0,core=True); source['relevance_review_required']=True
    apply_function_review(source, {'same_core_function':True})
    assert source['relevance_review_required'] and not editing_ready(source)
    assert not source_goal(state_with([source]))['ready']


def test_soft_preference_never_reserves_slots_ahead_of_higher_ranked_sources():
    candidates=[Candidate('https://tiktok.com/@a/video/1','tiktok',source_score=.1),
        Candidate('https://youtube.com/watch?v=better','youtube',source_score=.9)]
    for i,c in enumerate(candidates):
        c.downloaded_file=f'{i}.mp4';c.file_sha256=str(i);c.source_quality='clean-source'
    assert select_sources(candidates,1,5,required=False)[0].provider=='youtube'


def test_manual_refresh_reviews_all_low_similarity_pending_candidates(tmp_path, monkeypatch):
    studio,tid,_,_,calls,_,_=automatic_review_fixture(tmp_path,monkeypatch,kind='refresh_sources')
    calls.clear()
    job={'id':'manual-refresh','kind':'refresh_sources','payload':{}}
    result=studio._refresh_sources(studio.store.get(tid),job)
    assert len(calls)==len(result['sources'])==14  # No former three-candidate rescue cap.
    assert all(not s['relevance_review_required'] for s in result['sources'])
    assert sum(o['usable'] for o in result['platform_outcomes'].values())==14
