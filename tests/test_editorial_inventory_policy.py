import copy

from hotpost.source_policy import adopt_policy, current_policy, goal_message, run_policy, montage_policy
from hotpost.studio_sources import source_goal
from test_parallel_sources import asset


def test_saved_v4_montage_run_keeps_short_reviewed_product_footage_contract(tmp_path):
    source = asset(tmp_path, 0, core=True)
    source['video_meta']['duration'] = 1.
    state = {'sources': [source], 'reference_duration': 30.}
    policy=montage_policy();policy.update(version=4,minimum_total=1)
    policy.pop('source_diversity_policy');policy.pop('search_minimums')
    state['source_policy']=policy
    adopt_policy(state)
    goal = source_goal(state)
    assert goal['policy_version'] == 4 and goal['ready']
    assert goal['usable_seconds'] == 1 and goal['required_seconds'] == 37.5
    assert goal['duration_requirement'] == 'preference'
    assert not goal['duration_target_met'] and not goal['core_duration_target_met']
    assert '권장' in goal_message(goal)


def test_montage_reuse_does_not_promote_context_only_or_unreviewed_product(tmp_path):
    source = asset(tmp_path, 0, core=False)
    state = {'sources': [source], 'reference_duration': 30.}
    adopt_policy(state)
    assert not source_goal(state)['ready']
    source['source_role'] = 'core'
    source['functional_review']['source_sha256'] = 'another file'
    assert not source_goal(state)['ready']


def test_reading_paused_legacy_run_does_not_migrate_its_duration_contract(tmp_path):
    source = asset(tmp_path, 0, core=True)
    state = {'sources': [source], 'reference_duration': 30., 'run_id': 'old',
             'runs': [{'id': 'old', 'status': 'paused', 'source_policy': current_policy()}]}
    before = copy.deepcopy(state)
    assert run_policy(state)['version'] == 3
    assert not source_goal(state)['ready']
    assert state == before


def test_explicit_reproduction_adopts_v6_without_overwriting_old_run_policy():
    state = {'run_id': 'old', 'runs': [{'id': 'old', 'status': 'superseded',
                                      'source_policy': current_policy()}]}
    before = copy.deepcopy(state['runs'])
    assert adopt_policy(state)['version'] == 3
    assert adopt_policy(state, new_run=True)['version'] == 6
    assert state['runs'] == before


def test_new_store_task_freezes_montage_policy_and_reopening_keeps_it(tmp_path):
    from hotpost.studio_store import StudioStore
    store = StudioStore(tmp_path / 'studio')
    state, created = store.create('new-montage', 'new', {'protocol': 2}, prepare=False)
    assert created and state['source_policy']['version'] == 6
    assert state['runs'][0]['source_policy']['duration_requirement'] == 'preference'
    before = copy.deepcopy(state)
    reopened, created = store.create('new-montage', 'ignored', {'protocol': 2}, prepare=False)
    assert not created and reopened == before


def test_new_v6_short_product_inventory_cannot_replace_five_sources_and_searches(tmp_path):
    source=asset(tmp_path,0,core=True)
    state={'sources':[source],'reference_duration':30.}
    adopt_policy(state)
    goal=source_goal(state)
    assert goal['policy_version']==6 and not goal['ready']
    assert goal['duration_requirement']=='preference'
    # A pre-v6 review cannot silently certify this new product-identity contract.
    assert goal['related_parent_count']==0 and not goal['source_diversity_ready']
    assert not goal['search_ready']
