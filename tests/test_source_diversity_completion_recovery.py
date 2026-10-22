"""Independent queue/recovery contracts; synthetic evidence in a temporary store only."""
import copy
import hashlib
import json

import pytest

from hotpost.config import Settings
from hotpost.source_coverage import search_scope_for_state
from hotpost.source_diversity import SourceDiversityRequired, acquisition_policy, inventory_signature,inventory_material
from source_policy_fixtures import saved_v5 as montage_policy
from hotpost.studio import Studio
from hotpost.studio_sources import source_goal, resolve_diversity_recovery


def asset(folder, number, *, core=False):
    path=folder/f'parent-{number}.mp4'
    path.write_bytes(f'independently reviewed physical source {number}'.encode())
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    return {'id':f'parent-{number}','path':str(path),'sha256':digest,
        'origin_url':f'https://www.youtube.com/watch?v=parent{number}',
        'source_quality':'clean-source','source_role':'core' if core else 'context_only',
        'video_meta':{'duration':6},'reviewed_intervals':[{'source_start':0.,'source_end':4.}],
        'functional_review':{'reviewed':True,'source_sha256':digest,'same_core_function':core,
            'context_usable':not core,'context_usage_limits':[] if core else ['related product use context'],
            'observed_actions':['actual product operation' if core else 'related product use'],
            'evidence_frames':[f'reviewed-native-{number}.jpg']}}


def search_receipts(state):
    words={'en':['hand warmer','electric hand warmer','portable hand warmer','red hand warmer','black hand warmer'],
           'zh':['暖手宝','电动暖手宝','便携暖手宝','红色暖手宝','黑色暖手宝']}
    return [{'provider':'youtube','query':query,'language':lang,'status':'no_results',
             'run_id':state['run_id'],'search_context':search_scope_for_state(state),
             'execution':{'query_submitted':True,'query_url_matched':True,'input_value':query}}
            for lang,queries in words.items() for query in queries]


def setup(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('independent-diversity-recovery','손난로',
        {'protocol':2,'active':True,'paused_by_user':False},prepare=False)
    folder=studio.folder(state['id']);folder.mkdir(parents=True,exist_ok=True)
    reference=folder/'reference.mp4';reference.write_bytes(b'fixed reference material')
    voice=folder/'approved-voice.wav';voice.write_bytes(b'fixed approved voice material')
    inventory=[asset(folder,i,core=i==0) for i in range(5)]
    def seed(s,db):
        s.update(original_text='빨간 검정 휴대용 전기 손난로',product='손난로',product_override=True,
            reference_video=str(reference),sources=inventory,script_id='script',voice_id='voice',
            scripts=[{'id':'script','text':'승인 대본을 그대로 보존합니다.'}],
            voices=[{'id':'voice','script_id':'script','path':str(voice),
                     'sha256':hashlib.sha256(voice.read_bytes()).hexdigest()}],
            source_policy=montage_policy())
        s['source_acquisition']={'round':0,'queries':search_receipts(s),'rounds':[],'urls':[]}
        s['runs'][0]['source_policy']=montage_policy()
        s['runs'][0]['inputs']['source_ids']=[v['id'] for v in inventory]
        studio.advance_workflow(s,db)
    studio.store.change(state['id'],seed)
    job=studio.store.claim('media',task_id=state['id'])
    assert job and job['kind']=='edit'
    assert source_goal(studio.store.get(state['id']))['ready']
    return studio,state['id'],folder,job


def fail_layout(studio,job):
    error=SourceDiversityRequired('본문에 실제 배치할 원본이 부족합니다.',
        {'minimum_parent_sources':5,'used_parent_sources':3,'shortfall':2})
    studio.handle_source_diversity_gap(job,error)
    return studio.store.get(job['task_id'])


def jobs(studio,task):
    with studio.store.connect() as db:
        return [{**dict(row),'payload':json.loads(row['payload'])} for row in db.execute(
            'SELECT * FROM jobs WHERE task_id=? ORDER BY created,rowid',(task,))]


def test_layout_failure_finishes_no_render_and_enqueues_normal_collection_without_deactivating(tmp_path):
    studio,task,_,edit=setup(tmp_path)
    before=studio.store.get(task)
    held=fail_layout(studio,edit)
    assert held['automation']['active'] is True and held['status']=='source_wait' and held['error']==''
    assert not source_goal(held)['ready'] and source_goal(held)['selection_recovery_required']
    gap=held['source_diversity_gap']
    assert gap['baseline_parent_count']==5 and gap['diagnostics']['used_parent_sources']==3 and gap['no_render']
    policy=acquisition_policy(held,held['source_policy'])
    assert policy['acquisition_parent_target']==6 and 'acquisition_parent_target' not in held['source_policy']
    rows=jobs(studio,task)
    assert next(j for j in rows if j['id']==edit['id'])['status']=='done'
    collectors=[j for j in rows if j['kind']=='collect_sources' and j['status']=='queued']
    assert len(collectors)==1 and collectors[0]['payload']['run_id']==held['run_id']
    assert held['scripts']==before['scripts'] and held['voices']==before['voices'] and held['edits']==before['edits']
    studio.store.change(task,lambda s,db:studio.advance_workflow(s,db))
    assert len([j for j in studio.store.jobs(task) if j['kind']=='edit'])==1
    assert len([j for j in studio.store.jobs(task) if j['kind']=='collect_sources'])==1


def test_new_approved_material_clears_gap_refreshes_source_selection_and_creates_new_edit_key(tmp_path):
    studio,task,folder,old_edit=setup(tmp_path)
    held=fail_layout(studio,old_edit);before=copy.deepcopy(held)
    collect=studio.store.claim('sources',task_id=task)
    assert collect and collect['kind']=='collect_sources'
    received=asset(folder,5)
    result={'round':0,'sources':[received],'searches':[],'attempted_urls':[],
            'source_search_manifest_path':str(folder/'fresh-manifest.json'),'source_policy':montage_policy()}
    studio.store.finish(collect,result,lambda s,db,r:studio.accept_source_round(s,collect,r,db))
    current=studio.store.get(task)
    assert 'source_diversity_gap' not in current and current['source_diversity_generation']==1
    assert source_goal(current)['ready'] and current['source_goal']['related_parent_count']==6
    assert current['source_diversity_history'][0]['resolution']=='changed_reviewed_footage_retry_layout'
    selected=current['runs'][0]['inputs']['source_ids']
    assert len(selected)==6 and set(before['runs'][0]['inputs']['source_ids'])<set(selected)
    edits=[j for j in jobs(studio,task) if j['kind']=='edit']
    assert len(edits)==2
    fresh=next(j for j in edits if j['id']!=old_edit['id'])
    assert fresh['status']=='queued' and fresh['key']!=old_edit['key']
    assert ':source-diversity:1' in fresh['key'] and fresh['payload']['source_ids']==selected
    assert current['scripts']==before['scripts'] and current['voices']==before['voices']
    assert current['automation']['active'] is True
    assert not resolve_diversity_recovery(current)


@pytest.mark.parametrize('change',['retry_id','order','notes','unreviewed','unrelated',
                                   'review_timestamp','duplicate_bytes','denied_new','deny_existing',
                                   'remove_existing','shrink_window','changed_bytes'])
def test_nonprogress_input_cannot_clear_the_failed_layout_or_authorize_new_edit(tmp_path,change):
    studio,task,folder,edit=setup(tmp_path)
    held=fail_layout(studio,edit);before=inventory_signature(held)
    changed=copy.deepcopy(held)
    if change=='retry_id':
        changed['source_diversity_gap']['job_id']='another-attempt-id'
        changed['source_acquisition']['round']+=1
    elif change=='order':changed['sources'].reverse()
    elif change=='notes':changed['sources'][0].update(notes='different prose',downloaded_at=12345.)
    elif change=='review_timestamp':changed['sources'][0]['functional_review'].update(reviewed_at=12345.,reason='rewritten explanation')
    elif change=='remove_existing':changed['sources'].pop()
    elif change=='shrink_window':changed['sources'][0]['reviewed_intervals'][0]['source_end']=3.
    elif change=='changed_bytes':
        from pathlib import Path
        Path(changed['sources'][0]['path']).write_bytes(b'file changed without new review')
    elif change=='deny_existing':changed['sources'][-1]['manual_usage_review']={'editing_eligible':False,'reason':'사용자 제외'}
    elif change=='duplicate_bytes':
        duplicate=copy.deepcopy(changed['sources'][0]);duplicate['id']='new-record-same-file'
        changed['sources'].append(duplicate)
    else:
        incoming=asset(folder,5)
        if change=='unreviewed':incoming['functional_review']={}
        elif change=='unrelated':incoming['functional_review'].update(same_core_function=False,context_usable=False)
        elif change=='denied_new':incoming['manual_usage_review']={'editing_eligible':False}
        changed['sources'].append(incoming)
    assert not resolve_diversity_recovery(changed), f'{change} is not new approved usable material'
    assert 'source_diversity_gap' in changed and not changed.get('source_diversity_generation')
    assert not source_goal(changed)['ready']
    assert acquisition_policy(changed,changed['source_policy'])['acquisition_parent_target']==6
    def advance(s,db):
        s.update(copy.deepcopy(changed))
        studio.advance_workflow(s,db)
    studio.store.change(task,advance)
    assert len([j for j in jobs(studio,task) if j['kind']=='edit'])==1
    assert studio.store.get(task)['automation']['active'] is True
    # Preserve the original failed evidence even when irrelevant inputs change.
    assert held['source_diversity_gap']['inventory_signature']==before


def test_same_physical_parent_new_approved_frames_can_retry_but_overlapping_trim_cannot(tmp_path):
    studio,task,folder,edit=setup(tmp_path)
    held=fail_layout(studio,edit)
    assert held['source_diversity_gap']['baseline_material']==inventory_material(held)
    duplicate=asset(folder,20)
    duplicate.update(original_sha256=held['sources'][0]['sha256'],original_interval={'start':0.,'end':6.})
    overlap=copy.deepcopy(held);overlap['sources'].append(duplicate)
    # Its independently reviewed 0–4 span is already in the parent baseline.
    assert not resolve_diversity_recovery(overlap)
    expanded=copy.deepcopy(held)
    expanded['sources'][0]['reviewed_intervals'][0]['source_end']=5.
    assert resolve_diversity_recovery(expanded)
    assert expanded['source_diversity_generation']==1 and source_goal(expanded)['ready']
    assert len(expanded['runs'][0]['inputs']['source_ids'])==5


def test_gap_without_historical_material_cannot_infer_progress_from_signature_change(tmp_path):
    studio,_,folder,edit=setup(tmp_path)
    held=fail_layout(studio,edit)
    held['source_diversity_gap'].pop('baseline_material')
    held['sources'].append(asset(folder,5))
    assert not resolve_diversity_recovery(held) and not source_goal(held)['ready']
    held['source_diversity_gap']['baseline_material']=[{'sha256':'old-but-unbound'}]
    assert not resolve_diversity_recovery(held)


def test_completed_task_new_running_v5_run_queues_collection_before_workflow_updates_task_status(tmp_path):
    studio,task,_,old_edit=setup(tmp_path)
    def complete_old(s,db,result):
        s['status']='completed';s['runs'][0]['status']='completed'
        legacy=copy.deepcopy(s['runs'][0]['source_policy']);legacy.update(version=4,minimum_total=1)
        legacy.pop('source_diversity_policy');legacy.pop('search_minimums')
        s['runs'][0]['source_policy']=legacy
    studio.store.finish(old_edit,{'synthetic_test_completion':True},complete_old)
    completed=studio.store.get(task);old_run=copy.deepcopy(completed['runs'][0])
    assert completed['status']=='completed'
    def new_running_run(s,db):
        s['run_id']='new-running-v5'
        s['runs'].append({'id':s['run_id'],'status':'running','number':2,
            'source_policy':montage_policy(),'inputs':{},'artifacts':{}})
        s['source_policy']=montage_policy()
        # The first workflow tick still sees the old task status. The selected
        # run is authoritative for permitting its own initial collection.
        assert s['status']=='completed'
        studio.ensure_source_collection(s,db)
    studio.store.change(task,new_running_run)
    current=studio.store.get(task)
    collectors=[j for j in jobs(studio,task) if j['kind']=='collect_sources']
    assert len(collectors)==1 and collectors[0]['status']=='queued'
    assert collectors[0]['payload']['run_id']=='new-running-v5'
    assert not current['source_goal']['ready'] and current['source_goal']['policy_version']==5
    assert current['source_goal']['search_coverage']['en']['count']==0
    assert current['source_goal']['search_coverage']['zh']['count']==0
    assert current['source_goal']['related_parent_count']==5
    assert current['runs'][0]==old_run and current['sources']==completed['sources']


def test_only_missing_real_language_searches_does_not_rereview_adequate_existing_intervals(tmp_path,monkeypatch):
    studio,task,_,job=setup(tmp_path)
    studio.store.change(task,lambda s,db:s['source_acquisition'].update(queries=[]))
    state=studio.store.get(task);goal=source_goal(state)
    assert goal['related_parent_count']==5 and goal['core_ready'] and goal['source_diversity_ready']
    assert not goal['search_ready'] and not goal['ready']
    monkeypatch.setattr('hotpost.source_interval_recovery.recover',lambda *a,**kw:pytest.fail(
        'More local intervals cannot satisfy missing actual English/Chinese search receipts'))
    assert studio._recover_local_source_intervals(state,job,lambda *a:None) is None
    assert 'interval_recovery' not in job['checkpoint']


@pytest.mark.parametrize('reason',['inventory_shortage','proven_layout_gap'])
def test_real_inventory_or_layout_gap_preserves_local_review_before_new_download(tmp_path,monkeypatch,reason):
    studio,task,_,job=setup(tmp_path)
    if reason=='inventory_shortage':
        studio.store.change(task,lambda s,db:s['sources'].pop())
        state=studio.store.get(task)
        assert not source_goal(state)['source_diversity_ready']
    else:
        state=fail_layout(studio,job)
        job=studio.store.claim('sources',task_id=task)
        assert source_goal(state)['selection_recovery_required']
    calls=[]
    monkeypatch.setattr('hotpost.source_interval_recovery.recover',
        lambda settings,source,*a,**kw:calls.append(source['sha256']) or copy.deepcopy(source))
    assert studio._recover_local_source_intervals(state,job,lambda *a:None) is None
    assert calls and 'interval_recovery' in job['checkpoint']
