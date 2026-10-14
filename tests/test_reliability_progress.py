import json
import sys
from pathlib import Path

import pytest

from hotpost.operation_progress import ProgressWatch, NoProgressTimeout, watch_browser_transfer
from hotpost import model_service as service
from hotpost.source_browser_worker import run_bounded
from test_parallel_sources import task, finish
from test_source_strategy import claim_next, round_result
from test_daily_quality import ready


def test_progressing_operation_can_outlive_any_original_wall_clock_allowance():
    now=[0]
    watch=ProgressWatch(30,clock=lambda:now[0])
    for i in range(1,101):
        now[0]+=20
        watch.observe('unique_bytes',i*100)
        watch.check()
    assert now[0]==2000
    now[0]+=30
    assert not watch.observe('unique_bytes',10000)
    with pytest.raises(NoProgressTimeout):watch.check()


def test_scheduled_wait_does_not_reduce_execution_opportunity():
    now=[0];watch=ProgressWatch(30,clock=lambda:now[0])
    now[0]=86400
    watch.reset('actual transfer')
    now[0]+=29
    watch.check()


def test_duplicate_browser_transfer_does_not_reset_progress():
    from types import SimpleNamespace
    callbacks={};now=[0]
    session=SimpleNamespace(on=lambda k,f:callbacks.update({k:f}),send=lambda *a:None,detach=lambda:None)
    context=SimpleNamespace(new_cdp_session=lambda p:session)
    watch=ProgressWatch(30,clock=lambda:now[0])
    close=watch_browser_transfer(context,None,watch,lambda u:u=='selected')
    response=lambda req:callbacks['Network.responseReceived']({'requestId':req,'response':
        {'url':'selected','status':206,'mimeType':'video/mp4','headers':{'Content-Range':'bytes 0-99/200'}}})
    response('first');callbacks['Network.dataReceived']({'requestId':'first','dataLength':100})
    now[0]=20;response('duplicate');callbacks['Network.dataReceived']({'requestId':'duplicate','dataLength':100})
    assert watch.last_progress==0
    now[0]=30
    with pytest.raises(NoProgressTimeout):watch.check()
    close()


def test_shared_capacity_gate_survives_restart_and_allows_one_recovery_probe(tmp_path,monkeypatch):
    root=tmp_path/'writing';now=[100]
    monkeypatch.setattr(service.time,'time',lambda:now[0])
    monkeypatch.setattr(service.random,'uniform',lambda *a:1)
    retry_at=service.capacity_failure(root/'job1')
    with pytest.raises(service.ModelServiceUnavailable) as exc:service.before_call(root/'job2')
    assert not exc.value.attempted
    now[0]=retry_at+1
    service.before_call(root/'job3')
    with pytest.raises(service.ModelServiceUnavailable):service.before_call(root/'job4')
    service.response_received(root/'job3')
    service.before_call(root/'job4')


def test_local_review_no_gain_does_not_block_untried_external_scope(tmp_path):
    studio,tid,folder=task(tmp_path)
    for i in range(3):
        job=claim_next(studio,tid)
        value=round_result(i);value['visual_review_only']=True
        finish(studio,job,value)
    state=studio.store.get(tid)
    assert not state['source_acquisition'].get('hold')
    studio.store.recover()
    assert claim_next(studio,tid)


def test_uncovered_required_scene_does_not_schedule_reediting(ready):
    from test_daily_quality import finish as complete, issue
    studio,tid=ready
    complete(studio,tid,issue('old-edit'))
    before=studio.store.get(tid)['daily_quality']
    complete(studio,tid,{'sources':[],'source_search_manifest_path':'manifest.json','searches':[],
                         'scene_requirements':{'ready':False,'requirements':[]}})
    state=studio.store.get(tid)
    assert state['daily_quality']['repair_round']==0
    assert not any(j['kind']=='quality_reedit' for j in studio.store.jobs(tid))
    assert state['daily_quality']['pending']=='scene_wait'
    assert state['daily_quality'].get('collection_attempt',0)==before.get('collection_attempt',0)
    assert state['daily_quality'].get('scene_no_progress',0)==before.get('scene_no_progress',0)
    count=len(studio.store.jobs(tid))
    studio.store.change(tid,lambda s,db:studio.advance_workflow(s,db))
    studio.store.recover()
    assert len(studio.store.jobs(tid))==count
    assert studio.store.claim(task_id=tid) is None


def test_edit_cannot_choose_old_source_after_replacement_was_verified(tmp_path):
    from hotpost.config import Settings
    from hotpost.scene_requirements import constrain_plan,assess,coverage_current
    from test_scene_requirement_intervals import approved,coverage
    state=approved(tmp_path);source=state['sources'][0];source['id']='replacement'
    def reviewed(*args,**kwargs):
        result=coverage(source);result['requirements'][0]['matches'][0]['source_id']='replacement'
        return result
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,generate=reviewed)
    assert state['daily_quality']['feedback'][0]['kind']=='scene_gap'
    assert state['daily_quality']['feedback'][0].get('scope')!='cover'
    assert coverage_current(state)
    plan={'shots':[{'id':'bad','source_id':'old','start':0,'end':4},
            {'id':'good','source_id':'replacement','path':source['path'],'sha256':source['sha256'],'start':0,'end':4}],
          'beats':[{'id':'b1','text':'Observed action.','start':0,'end':1,
            'selected_shot_id':'bad','options':[{'shot_id':'bad'},{'shot_id':'good'}]}]}
    constrain_plan(state,plan)
    assert 'selected_shot_id' not in plan['beats'][0]
    assert len(plan['beats'][0]['options'])==1
    selected=next(s for s in plan['shots'] if s['id']==plan['beats'][0]['options'][0]['shot_id'])
    assert selected['source_id']=='replacement' and selected['sha256']==source['sha256']
    assert (selected['start'],selected['end'])==pytest.approx((1,3.04))


def test_successful_review_clears_current_error_and_retains_its_history():
    from hotpost.scene_requirements import clear_resolved_errors
    old={'sha256':'source','overlay_review_error':'old transport error'}
    incoming={'sha256':'source','mask_review':{'source_sha256':'source'}}
    clear_resolved_errors(old,incoming)
    assert 'overlay_review_error' not in old
    assert old['review_error_history'][0]['error']=='old transport error'


def test_cached_success_resolves_only_current_hash_bound_review():
    from hotpost.scene_requirements import clear_cached_review_errors
    from hotpost.source_overlay_review import POLICY
    source={'sha256':'current','overlay_review_error':'old transport error',
        'overlay_review_policy':POLICY,'mask_review':{'source_sha256':'other'},
        'reviewed_intervals':[{'source_start':0,'source_end':4}]}
    assert not clear_cached_review_errors(source)
    source['mask_review']['source_sha256']='current'
    assert clear_cached_review_errors(source)
    assert 'overlay_review_error' not in source
    assert not clear_cached_review_errors(source)


def test_download_process_can_continue_while_output_file_grows(tmp_path):
    from hotpost.operation_progress import run_progress_command
    script='''import sys,time
from pathlib import Path
p=Path(sys.argv[1])
for i in range(6):
 with p.open('ab') as f:f.write(b'chunk')
 time.sleep(.4)
'''
    result=run_progress_command([sys.executable,'-c',script,str(tmp_path/'video.mp4.part')],
                                idle_seconds=1,progress_dir=tmp_path)
    assert result.returncode==0
    assert (tmp_path/'video.mp4.part').stat().st_size==30


def test_silent_download_process_stops_at_no_progress_point(tmp_path):
    from hotpost.operation_progress import run_progress_command
    with pytest.raises(NoProgressTimeout):
        run_progress_command([sys.executable,'-c','import time;time.sleep(10)'],
                             idle_seconds=1,progress_dir=tmp_path)


def test_new_portrait_transport_retries_old_failure_once():
    from hotpost.source_presentation import needs_presentation_review, review_scope, ERROR_POLICY
    source={'sha256':'source','video_meta':{'width':1080,'height':1920,'duration':4},
        'presentation_review_required':True,'presentation_review_error':'old error',
        'presentation_review_error_sha256':'source','presentation_review_error_policy':'portrait-presentation-v1'}
    source['presentation_review_error_scope']=review_scope(source)
    assert needs_presentation_review(source)
    source['presentation_review_error_policy']=ERROR_POLICY
    assert not needs_presentation_review(source)


def test_capacity_wait_does_not_spend_content_repair_attempts(ready,monkeypatch):
    studio,tid=ready
    before=studio.store.get(tid)['daily_quality']['repair_round']
    monkeypatch.setattr(studio,'_quality_review',lambda *a:(_ for _ in ()).throw(service.ModelServiceUnavailable()))
    defer=studio.store.defer
    def waiting(*a,**k):
        defer(*a,**k);studio.stop.set()
    monkeypatch.setattr(studio.store,'defer',waiting)
    studio._worker('media')
    state=studio.store.get(tid)
    assert state['daily_quality']['repair_round']==before
    job=studio.store.jobs(tid)[0]
    assert job['status']=='queued'


def test_worker_with_useful_checkpoints_is_not_killed_by_total_elapsed_time(tmp_path):
    script='''import json,sys,time
from pathlib import Path
p=json.load(sys.stdin)
for i in range(5):
 Path(p['checkpoint']).write_text(json.dumps({'searches':[{'provider':'tiktok','query':str(i),'status':'results'}]}))
 time.sleep(.6)
'''
    target=tmp_path/'checkpoint.json'
    result=run_bounded([sys.executable,'-c',script],{'checkpoint':str(target)},target,1)
    assert result['searches'][-1]['query']=='4'
    assert not any(r.get('status')=='timeout' for r in result['searches'])
