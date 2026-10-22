import copy
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from hotpost import source_interval_recovery as recovery
from hotpost.source_quality import sha256_file


def evidence():
    return {'frames':[{'frame_id':'middle','source_timestamp':.3},
                      {'frame_id':'edge','source_timestamp':.63}],
            'native_frame_timing':{'frames':[
                {'start':i/100,'end':(i+1)/100} for i in range(1000)]}}


def span(start=0,end=.65,ids=None):
    return {'start':start,'end':end,'reason':'actual product is visible',
            'evidence_frame_ids':ids or ['middle']}


def test_native_scope_identity_ignores_cosmetic_boundary_changes():
    first=recovery.normalized_scope(span(.001,.651),evidence())
    second=recovery.normalized_scope(span(.002,.652),evidence())
    assert first==second
    assert first['start']==.01 and first['end']==.65
    assert recovery.normalized_scope(span(ids=['not-supplied']),evidence()) is None
    assert recovery.normalized_scope(span(),evidence(),existing=[(.2,.4)]) is None
    assert recovery.normalized_scope(span(),evidence(),denied=[(.2,.4)]) is None


def test_anchor_must_still_be_in_normalized_scope():
    value=evidence()
    value['frames']=[{'frame_id':'edge','source_timestamp':19/30}]
    value['native_frame_timing']['frames']=[
        {'start':i/30,'end':(i+1)/30} for i in range(30)]
    assert recovery.normalized_scope(span(end=.65,ids=['edge']),value) is None


def source_fixture(tmp_path):
    path=tmp_path/'source.mp4';path.write_bytes(b'fixed actual source')
    return {'id':'keep-id','path':str(path),'sha256':sha256_file(path),
            'video_meta':{'duration':10},'mask_review':{'old':True},
            'reviewed_intervals':[{'source_start':0.,'source_end':1.}],
            'editing_eligible':True,'functional_review':{'reviewed':True},
            'presentation_review':{'reviewed':True}}


def test_joint_review_preserves_prior_scopes_and_stops_when_sufficient(tmp_path,monkeypatch):
    from hotpost import source_overlay_review
    source=source_fixture(tmp_path);seen=[]
    spans=[{'start':2.,'end':3.,'first_native_frame':60,'last_native_frame':89,'reason':'actual view'},
           {'start':5.,'end':6.,'first_native_frame':150,'last_native_frame':179,'reason':'another view'}]
    monkeypatch.setattr(recovery,'propose',lambda *a,**kw:(spans,None))
    def overlay(settings,prior,root,*,intervals,generate):
        seen.append(intervals)
        result=copy.deepcopy(prior)
        result['reviewed_intervals']=[{'source_start':a,'source_end':b} for a,b in intervals]
        return result
    monkeypatch.setattr(source_overlay_review,'review_source_overlays',overlay)
    def normal(candidate):
        assert not candidate['editing_eligible']
        assert 'functional_review' not in candidate and 'presentation_review' not in candidate
        assert candidate['interval_function_review_required']==[[0.,1.],[2.,3.]]
        candidate.update(editing_eligible=True,source_quality='clean-source',blur_required=False,
                         relevance_review_required=False,presentation_review_required=False)
        candidate['mask_review']={}
        return candidate
    context={'reference_sha256':'reference','product':'shelf','context_key':'same-evidence','receipts':{}}
    result=recovery.recover(None,source,tmp_path/'review',context,normal,
        sufficient=lambda s:len(s['reviewed_intervals'])>=2)
    assert seen==[[[0.,1.],[2.,3.]]]
    assert result['id']==source['id']
    assert len(result['interval_recovery_history'])==1
    assert len(context['receipts'])==1
    assert 'interval_recovery_history' not in source


def test_voice_becoming_ready_during_proposal_prevents_next_visual_calls(tmp_path,monkeypatch):
    from hotpost import source_overlay_review
    source=source_fixture(tmp_path);ready=[False]
    def propose(*a,**kw):
        ready[0]=True
        return [{'start':2.,'end':3.,'first_native_frame':60,'last_native_frame':89,'reason':'actual view'}],None
    monkeypatch.setattr(recovery,'propose',propose)
    monkeypatch.setattr(source_overlay_review,'review_source_overlays',lambda *a,**kw:pytest.fail('already sufficient'))
    result=recovery.recover(None,source,tmp_path/'review',{'receipts':{}},lambda s:s,
                            sufficient=lambda s:ready[0])
    assert result==source and not list((tmp_path/'review').glob('scope-*.json'))


def test_failed_joint_review_keeps_old_source_and_never_repeats_method(tmp_path,monkeypatch):
    from hotpost import source_overlay_review
    source=source_fixture(tmp_path);calls=[]
    spans=[{'start':2.,'end':3.,'first_native_frame':60,'last_native_frame':89,'reason':'actual view'}]
    monkeypatch.setattr(recovery,'propose',lambda *a,**kw:(spans,None))
    def overlay(settings,prior,root,**kwargs):
        calls.append(1);candidate=copy.deepcopy(prior)
        candidate['reviewed_intervals']=[{'source_start':2.,'source_end':3.}]
        return candidate
    monkeypatch.setattr(source_overlay_review,'review_source_overlays',overlay)
    context={'reference_sha256':'reference','product':'shelf','context_key':'same','receipts':{}}
    def never_review(s):pytest.fail('lost old approval must be rejected before function review')
    result=recovery.recover(None,source,tmp_path/'review',context,never_review)
    assert result['reviewed_intervals']==source['reviewed_intervals']
    recovery.recover(None,result,tmp_path/'review',context,never_review)
    recovery.recover(None,result,tmp_path/'review',{**context,'receipts':{}},never_review)
    assert calls==[1]
    path=next((tmp_path/'review').glob('scope-*.json'))
    value=json.loads(path.read_text('utf8'));value['status']='started'
    path.write_text(json.dumps(value),'utf8')
    pointer=next(iter(context['receipts'].values()));pointer['sha256']=sha256_file(path)
    from hotpost.source_preparation import PreparationEvidenceWaiting
    with pytest.raises(PreparationEvidenceWaiting):
        recovery.recover(None,result,tmp_path/'review',context,never_review)
    assert calls==[1]


def test_changed_joint_evidence_waits_instead_of_becoming_quality_rejection(tmp_path,monkeypatch):
    from hotpost import source_overlay_review
    from hotpost.source_preparation import PreparationEvidenceWaiting
    source=source_fixture(tmp_path)
    monkeypatch.setattr(recovery,'propose',lambda *a,**kw:([
        {'start':2.,'end':3.,'first_native_frame':60,'last_native_frame':89,'reason':'actual view'}],None))
    def changed(*a,**kw):raise ValueError('Preserved overlay proposal differs from current scope')
    monkeypatch.setattr(source_overlay_review,'review_source_overlays',changed)
    context={'reference_sha256':'reference','product':'shelf','context_key':'same','receipts':{}}
    with pytest.raises(PreparationEvidenceWaiting,match='근거 확인 대기'):
        recovery.recover(None,source,tmp_path/'review',context,lambda s:s)
    assert source['editing_eligible']
    assert json.loads(next((tmp_path/'review').glob('scope-*.json')).read_text('utf8'))['status']=='started'


def test_local_recovery_is_skipped_when_goal_is_ready(tmp_path,monkeypatch):
    from test_parallel_sources import task,asset
    from hotpost import studio_sources
    studio,tid,folder=task(tmp_path);state=studio.store.get(tid)
    monkeypatch.setattr(studio_sources,'source_goal',lambda *a:{'ready':True})
    monkeypatch.setattr(recovery,'recover',lambda *a,**k:pytest.fail('no unnecessary local model calls'))
    assert studio._recover_local_source_intervals(state,{'checkpoint':{}},lambda *a:None) is None


@pytest.mark.parametrize('editing_gap',[False,True])
def test_batch_inventory_rescues_distinct_parents_without_extending_counted_sources(tmp_path,monkeypatch,editing_gap):
    from test_parallel_sources import task,asset
    from hotpost import studio_sources
    studio,tid,folder=task(tmp_path)
    sources=[asset(folder,i,core=True) for i in range(3)]
    for i,s in enumerate(sources):
        s.update(rescued=i==0,overlay_review_error='fixture partial scope')
    studio.store.change(tid,lambda s,db:s.update(sources=sources,manifest_path=str(folder/'manifest.json')))
    state=studio.store.get(tid)
    if editing_gap:state['source_diversity_gap']={'reason':'selected source cannot fill the actual scene'}
    calls=[]
    def goal(s,*args):
        ids=[x['id'] for x in s['sources'] if x.get('rescued')]
        return {'ready':False,'policy_version':6,'duration_requirement':'preference','core_ready':True,
                'search_ready':True,'source_diversity_ready':False,'source_ids':ids,'related_parent_count':len(ids)}
    monkeypatch.setattr(studio_sources,'source_goal',goal)
    def recover(settings,source,root,context,review,*,check,sufficient):
        calls.append(source['id']);value=copy.deepcopy(source);value['rescued']=True
        assert sufficient(value) is (not editing_gap)
        return value
    monkeypatch.setattr(recovery,'recover',recover)
    job=studio.store.claim('sources')
    result=studio._recover_local_source_intervals(state,job,lambda *a:None,inventory_only=True)
    assert calls==[s['id'] for s in (sources if editing_gap else sources[1:])]
    assert len(result['sources'])==2


def test_recovery_goal_keeps_verified_batch_searches_when_reloading_live_state(tmp_path,monkeypatch):
    from test_parallel_sources import task,asset
    from hotpost import studio_sources
    studio,tid,folder=task(tmp_path);source=asset(folder,0,core=True)
    source['overlay_review_error']='fixture partial scope'
    studio.store.change(tid,lambda s,db:s.update(sources=[source],manifest_path=str(folder/'manifest.json')))
    state=studio.store.get(tid)
    state['source_acquisition']={'queries':[{'query':'actual submitted query','status':'results'}]}
    def goal(s,*args):
        return {'ready':bool(s['sources'][0].get('rescued') and s.get('source_acquisition',{}).get('queries'))}
    monkeypatch.setattr(studio_sources,'source_goal',goal)
    def recover(settings,source,root,context,review,*,check,sufficient):
        value=copy.deepcopy(source);value['rescued']=True
        assert sufficient(value)
        return value
    monkeypatch.setattr(recovery,'recover',recover)
    result=studio._recover_local_source_intervals(state,studio.store.claim('sources'),lambda *a:None)
    assert result['sources'][0]['rescued']


def test_v5_missing_actual_searches_precede_same_parent_interval_extension(tmp_path,monkeypatch):
    from test_parallel_sources import task
    from hotpost import studio_sources
    studio,tid,_=task(tmp_path)
    state=studio.store.get(tid)
    monkeypatch.setattr(studio_sources,'source_goal',lambda *a:{
        'ready':False,'policy_version':5,'core_ready':True,
        'source_diversity_ready':False,'related_parent_count':3,'search_ready':False})
    monkeypatch.setattr(recovery,'recover',lambda *a,**k:pytest.fail('same parent cannot add actual searches'))
    job={'checkpoint':{}}
    assert studio._recover_local_source_intervals(state,job,lambda *a:None) is None
    assert job['checkpoint']=={}


def test_production_path_tries_local_scopes_before_network_and_serializes_claim(tmp_path,monkeypatch):
    from test_parallel_sources import task,asset
    from hotpost import studio_sources,source_finder
    studio,tid,folder=task(tmp_path);source=asset(folder,0,core=True)
    source.update(overlay_review_error='prior large window rejected',editing_eligible=False)
    manifest=folder/'manifest.json';manifest.write_text('{"candidates":[]}',encoding='utf8')
    studio.store.change(tid,lambda s,db:s.update(sources=[source],manifest_path=str(manifest)))
    state=studio.store.get(tid);job=studio.store.claim('sources');calls=[]
    monkeypatch.setattr(studio_sources,'source_goal',lambda state,*a:{'ready':any(s.get('rescued') for s in state['sources'])})
    def recover(settings,source,root,context,review,*,check,sufficient):
        check();context['checkpoint']();calls.append('local')
        value=copy.deepcopy(source);value.update(rescued=True,editing_eligible=True)
        assert sufficient(value)
        return value
    monkeypatch.setattr(recovery,'recover',recover)
    monkeypatch.setattr(source_finder,'find_sources',lambda *a,**kw:pytest.fail('local sufficient; no external calls'))
    monkeypatch.setattr(studio,'_review_deferred_downloads',lambda *a:None)
    monkeypatch.setattr('hotpost.source_overlay_review.needs_overlay_review',lambda s:False)
    monkeypatch.setattr('hotpost.source_presentation.needs_pending_presentation_review',lambda s:False)
    state['reference_duration']=4
    result=studio._collect_source_attempt(state,job)
    assert result['local_interval_recovery'] and calls==['local']
    json.dumps(job['checkpoint'])


def test_function_review_sees_every_new_short_scope(tmp_path,monkeypatch):
    from hotpost.source_functional import review_function
    frames=[]
    for interval in ([0.,4.],[8.,8.7],[12.,16.]):
        for i in range(5):
            path=tmp_path/f'{interval[0]}-{i}.png';Image.new('RGB',(12,12),'gray').save(path)
            frames.append({'path':str(path),'source_timestamp':interval[0]+(interval[1]-interval[0])*i/5,
                           'review_interval':interval})
    seen=[]
    def generate(settings,instruction,data,*,media):
        seen.extend(media);return {'same_core_function':True,'observed_actions':['visible product view']}
    monkeypatch.setattr('hotpost.script_rewriter._generate',generate)
    result=review_function(None,SimpleNamespace(file_sha256='fixed'),[],frames)
    assert result['candidate_review_intervals']==[[0.,4.],[8.,8.7],[12.,16.]]
    assert len(result['evidence_frames'])==9
    assert any('8.5600s' in p.get('text','') for p in seen)
    frames[-1]['source_timestamp']=17
    with pytest.raises(ValueError,match='outside'):
        review_function(None,SimpleNamespace(file_sha256='fixed'),[],frames)


def test_typed_review_rejection_is_not_a_service_retry():
    from hotpost.source_review_status import failed_outcome,review_status,is_transient,ReviewResponseInvalid,NoApprovedOverlayIntervals
    from hotpost.scene_requirements import clear_cached_review_errors
    source={'sha256':'fixed','overlay_review_error':'429 timed out text is visible'}
    source['review_outcome']=failed_outcome('overlay',NoApprovedOverlayIntervals({'rejected_intervals':[]},'receipt'),source)
    assert review_status(source)=='no_usable_intervals'
    assert not is_transient(source,'overlay') and not clear_cached_review_errors(source)
    source['review_outcome']=failed_outcome('overlay',ReviewResponseInvalid('bad frames'),source)
    assert review_status(source)=='response_error'


def test_malformed_review_and_no_accepted_scope_are_not_quality_rejection_counts():
    from hotpost.source_outcomes import platform_outcomes
    from hotpost.source_review_status import failed_outcome,ReviewResponseInvalid,NoApprovedOverlayIntervals
    rows=[]
    for index,exc in enumerate([ReviewResponseInvalid('missing frames'),
            NoApprovedOverlayIntervals({'rejected_intervals':[]},'receipt')]):
        source={'url':f'https://youtube.com/watch?v={index}','downloaded_file':f'{index}.mp4',
                'sha256':str(index),'editing_eligible':False,'source_quality':'unknown',
                'overlay_review_error':str(exc)}
        source['review_outcome']=failed_outcome('overlay',exc,source);rows.append(source)
    reasons=platform_outcomes(rows,[])['youtube']['reasons']
    assert reasons['review_response_error']==1 and reasons['no_approved_intervals']==1
    assert 'quality_rejected' not in reasons


def test_clearer_tie_break_preserves_semantic_relation_and_all_alternatives(tmp_path):
    from hotpost.shot_presentation import interval_receipt,prefer_clear_options
    shots=[];observations={}
    for name,clarity,overlap in [('masked',.4,.6),('clear',.9,0),('context',1,0)]:
        path=tmp_path/f'{name}.png';Image.new('RGB',(12,12),'gray').save(path)
        shot={'id':name,'sha256':name,'start':0.,'end':1.,'frames':[str(path)]};shots.append(shot)
        value={'product_role':'promoted_product','product_visible':True,'visual_cluster':name,
            'uncertainty':'actual samples only','visible_information':['product shape'],
            'frame_product_visibility':[True],'composition':.8,'clarity':clarity,
            'product_coverage':.6,'mask_product_overlap':overlap}
        observations[name]={'shot_presentation':interval_receipt(shot,value)}
    options=[{'shot_id':'masked','relation':'direct'},{'shot_id':'context','relation':'context'},
             {'shot_id':'clear','relation':'direct'}]
    ranked=prefer_clear_options(options,observations,shots)
    assert [o['shot_id'] for o in ranked]==['clear','context','masked']
    assert len(ranked)==len(options)
    observations['clear']['shot_presentation']['source_sha256']='changed'
    assert [o['shot_id'] for o in prefer_clear_options(options,observations,shots)]==['masked','context','clear']


@pytest.mark.parametrize('has_core',[False,True])
def test_acquisition_caller_preserves_first_core_rescue_but_skips_counted_parent_seconds(tmp_path,monkeypatch,has_core):
    from test_parallel_sources import task,asset
    from hotpost import studio_sources,source_finder
    studio,tid,folder=task(tmp_path);source=asset(folder,0,core=True)
    source['overlay_review_error']='prior partially reviewed source'
    manifest=folder/'manifest.json';manifest.write_text('{"candidates":[]}',encoding='utf8')
    studio.store.change(tid,lambda s,db:s.update(sources=[source],manifest_path=str(manifest)))
    state=studio.store.get(tid);state['reference_duration']=4
    job=studio.store.claim('sources');calls=[]
    def goal(state,*args):
        return {'ready':any(s.get('rescued') for s in state['sources']),
            'policy_version':6,'duration_requirement':'preference','core_ready':has_core,
            'search_ready':True,'source_diversity_ready':False,'source_ids':[source['id']]}
    monkeypatch.setattr(studio_sources,'source_goal',goal)
    monkeypatch.setattr(studio,'_review_deferred_downloads',lambda *a:None)
    monkeypatch.setattr('hotpost.source_overlay_review.needs_overlay_review',lambda s:False)
    monkeypatch.setattr('hotpost.source_presentation.needs_pending_presentation_review',lambda s:False)
    def recover(settings,source,root,context,review,*,check,sufficient):
        calls.append('local');value=copy.deepcopy(source);value['rescued']=True
        assert sufficient(value)
        return value
    monkeypatch.setattr(recovery,'recover',recover)
    class ReachedNewDiscovery(Exception):pass
    def discover(*a,**k):raise ReachedNewDiscovery()
    monkeypatch.setattr(source_finder,'find_sources',discover)
    if has_core:
        with pytest.raises(ReachedNewDiscovery):studio._collect_source_attempt(state,job)
        assert calls==[]
    else:
        assert studio._collect_source_attempt(state,job)['local_interval_recovery']
        assert calls==['local']
