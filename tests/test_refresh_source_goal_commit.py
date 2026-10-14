import copy
import hashlib

import pytest

from hotpost.config import Settings
from hotpost.source_policy import current_policy
from hotpost.studio_runtime.lifecycle import LifecycleMixin


class Acceptance(LifecycleMixin):
    def __init__(self,tmp_path):
        self.settings=Settings(data_dir=tmp_path,source_min_usable=10)


def source(tmp_path,identity,duration,windows,core=True,**extra):
    path=tmp_path/(identity+'.mp4');path.write_bytes(identity.encode())
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    return {'id':identity,'path':str(path),'sha256':sha,'origin_url':'https://example.com/'+identity,
        'source_quality':'clean-source','editing_eligible':True,
        'source_role':'core' if core else 'context_only','video_meta':{'duration':duration},
        'reviewed_intervals':[{'source_start':a,'source_end':b} for a,b in windows],
        'functional_review':{'reviewed':True,'source_sha256':sha,'same_core_function':core,
            'observed_actions':['Actual reviewed use'],'evidence_frames':['Actual reviewed frame']},**extra}


@pytest.mark.parametrize('local_review',[False,True])
def test_refresh_commit_goal_uses_merged_current_approved_ranges_and_preserves_denials_and_counters(tmp_path,local_review):
    studio=Acceptance(tmp_path)
    core=source(tmp_path,'initial-core',10,[(0,2)])
    context=source(tmp_path,'initial-context',5,[(0,5)],core=False)
    denial={'editing_eligible':False,'reason':'Explicit user exclusion','receipt_id':'keep-entire-receipt'}
    denied=source(tmp_path,'manual-denied',30,[(0,30)],manual_usage_review=copy.deepcopy(denial),editing_eligible=False)
    policy=current_policy(studio.settings)
    state={'id':'isolated-task','sources':[core,context,denied],'source_policy':policy,
        'run_id':'run','runs':[{'id':'run','source_policy':copy.deepcopy(policy),'status':'running'}],
        'script_id':'script','voice_id':'voice','voices':[{'id':'voice','script_id':'script','duration':8}],
        'source_goal':{'count':1,'usable_seconds':2,'core_seconds':2,'target':10},
        'source_acquisition':{'rounds':[{'job_id':'old-round','external_search_attempted':True}],
            'round':7,'no_progress_rounds':2,'queries':[],'urls':[]},
        'daily_quality':{'repair_round':2,'max_repairs':3,'scene_no_progress':2,'collection_attempt':5},
        'automation':{'active':False,'paused_by_user':True}}
    prior=copy.deepcopy(state)
    updated_core=copy.deepcopy(core);updated_core['reviewed_intervals']=[{'source_start':0,'source_end':4}]
    attempted_denial_release=copy.deepcopy(denied)
    attempted_denial_release.update(editing_eligible=True,manual_usage_review={'editing_eligible':True})
    incoming=[updated_core,attempted_denial_release,
        source(tmp_path,'new-core',20,[(3,9),(7,12)]), # Union is nine actual approved seconds.
        source(tmp_path,'new-context',50,[(10,15)],core=False),
        source(tmp_path,'rejected',100,[(0,100)],editing_eligible=False)]
    completion={'completed':False,'reviewed':5,'deferred':3}
    result={'sources':incoming,'source_goal':{'count':999,'usable_seconds':999},
        'source_search_manifest_path':'isolated-manifest.json','searches':[],
        'attempted_urls':[],'local_deferred_review':local_review,'review_completion':completion,
        'source_policy':{'version':1,'minimum_total':999}}
    studio._accept(state,{'id':'refresh','kind':'refresh_sources','payload':{}},result)
    goal=state['source_goal']
    assert goal['policy_version']==policy['version'] and goal['count']==4
    assert goal['usable_seconds']==23 and goal['core_seconds']==13
    assert goal['required_seconds']==10 and goal['output_seconds']==8
    assert set(goal['source_ids'])=={'initial-core','initial-context','new-core','new-context'}
    assert next(s for s in state['sources'] if s['id']=='manual-denied')['manual_usage_review']==denial
    assert next(s for s in state['sources'] if s['id']=='manual-denied')['editing_eligible'] is False
    assert state['daily_quality']==prior['daily_quality'] and state['automation']==prior['automation']
    assert state['runs']==prior['runs'] and state['source_policy']==prior['source_policy']
    assert state['source_acquisition']['round']==7 and state['source_acquisition']['no_progress_rounds']==2
    key='local_source_reviews' if local_review else 'rounds'
    assert state['source_acquisition'][key][-1]['review_completion']==completion
    assert state['source_acquisition']['rounds'][0]==prior['source_acquisition']['rounds'][0]
