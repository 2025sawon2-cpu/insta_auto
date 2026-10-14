"""Independent B: counterexamples at production/quality/export boundaries.

All files and services are isolated. These checks do not certify real picture
quality or the live TTS service; they test receipt and state contracts.
"""
import copy
import hashlib
import json
import subprocess
import shutil
import runpy
import sys
import threading
import time
from types import SimpleNamespace
from pathlib import Path

import pytest

from hotpost import quality_progress as progress
from hotpost.daily_quality import POLICY, verified_quality_export
from hotpost.studio_runtime.editing import EditingMixin
from test_quality_progress_independent import fixture, plan, store_plan, bind_replacement
from test_production import workflow, selection
from test_daily_quality import ready, passed
from test_voicebench_adapter import Response, Session, _settings, valid_wav
from hotpost.voicebench_adapter import VoiceBenchAdapter


def test_subframe_interval_shift_does_not_reopen_failed_same_picture(tmp_path):
    state, baseline, _ = fixture(tmp_path)
    shifted = copy.deepcopy(baseline)
    shifted['beats'][0]['source_start'] += .001
    shifted['beats'][0]['source_end'] += .001
    assert progress.guard_render(state, shifted, 'new-queue-id') is not None


def test_actual_disjoint_interval_can_supply_new_action_evidence(tmp_path):
    state, baseline, _ = fixture(tmp_path)
    other = copy.deepcopy(baseline)
    other['beats'][0].update(source_start=8, source_end=10)
    assert progress.guard_render(state, other, 'actual-other-action') is None


def test_caption_clock_change_is_render_change_but_not_voice_resynthesis(tmp_path):
    state, baseline, review = fixture(tmp_path)
    state['daily_quality'].pop('progress_policy')
    baseline['cues'] = [{'text':'제품 효과','start':0,'end':2}]
    review = store_plan(tmp_path, state, baseline, 'caption-baseline')
    review['issues'] = [{'kind':'caption_sync','beat_id':'beat-1','reason':'자막이 실제 음성보다 늦음'}]
    state['daily_quality']['feedback'] = review['issues']
    progress.observe(state, review)
    repaired = copy.deepcopy(baseline)
    repaired['cues'][0].update(start=.25, end=2.25)
    assert progress.guard_render(state, repaired, 'caption-fix') is None
    fixed = store_plan(tmp_path, state, repaired, 'caption-fixed')
    fixed.update(issues=[], passed=True)
    result = progress.observe(state, fixed)
    assert result['passed'] and not result['conflict']
    assert repaired['voice'] == baseline['voice']


def test_cover_fix_does_not_resolve_unmodified_caption_clock(tmp_path):
    state, baseline, review = fixture(tmp_path)
    state['daily_quality'].pop('progress_policy')
    review['issues'] = [{'kind':'caption_sync','beat_id':'beat-1','reason':'음성 시간과 다름'}]
    state['daily_quality']['feedback'] = review['issues']
    progress.observe(state, {**review, 'render_sha256':'different-initial-review'})
    changed = copy.deepcopy(baseline)
    changed['cover_spec']['lines'] = ['새 궁금증','어떻게?']
    result = store_plan(tmp_path, state, changed, 'cover-only')
    result.update(issues=[], passed=True)
    observed = progress.observe(state, result)
    assert observed['conflict'] and not observed['passed']


def test_fewer_defects_with_important_regression_cannot_replace_best(tmp_path):
    state, baseline, _ = fixture(tmp_path)
    prior_best = copy.deepcopy(state['daily_quality']['progress_policy']['best'])
    review = store_plan(tmp_path, state, plan('b'), 'new-body')
    review.update(issues=[{'kind':'script_fact','beat_id':'beat-1','reason':'미확인 치료 효과 추가'}])
    row = progress.observe(state, review)
    assert row['introduced'] and not row['improved']
    assert state['daily_quality']['progress_policy']['best'] == prior_best


def test_repeated_model_prose_and_frame_ids_do_not_reopen_failure(tmp_path):
    state, _, _ = fixture(tmp_path)
    bind_replacement(state)
    method = progress.permit(state, 'reedit', reserve=True, job_id='first')
    next(a for a in state['daily_quality']['progress_policy']['attempts'] if a['key']==method['key'])['status']='failed'
    match = state['daily_quality']['scene_requirements']['requirements'][0]['matches'][0]
    match.update(supporting_frame_ids=['renamed-frame'], supporting_reason='다르게 표현한 동일 근거')
    assert progress.permit(state, 'reedit', job_id='different-id') is None


def test_service_wait_and_restart_reuse_reserved_method_without_failure_charge(tmp_path):
    state, _, _ = fixture(tmp_path)
    bind_replacement(state)
    progress.permit(state, 'reedit', reserve=True, job_id='owned-job')
    saved = json.loads(json.dumps(state))
    before_usage = copy.deepcopy(saved['daily_quality']['render_accounting'])
    assert progress.permit(saved, 'reedit', job_id='owned-job')
    assert saved['daily_quality']['render_accounting'] == before_usage
    assert saved['daily_quality']['repair_round'] == 3


def test_real_new_repair_is_allowed_after_four_more_changes(tmp_path):
    state, _, _ = fixture(tmp_path, round_number=19)
    for number in range(4):
        other = plan('new-'+str(number))
        assert progress.guard_render(state, other, 'job-'+str(number)) is None
        review = store_plan(tmp_path, state, other, 'job-'+str(number))
        progress.observe(state, review)
    assert state['daily_quality']['repair_round'] == 19


def test_receipt_belongs_to_actual_current_export_and_plan(tmp_path):
    media=tmp_path/'final.mp4'; media.write_bytes(b'old-reviewed-picture')
    document=tmp_path/'plan.json'; document.write_bytes(b'{"old":true}')
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    edit={'id':'edit','export_path':str(media),'plan_path':str(document),'quality_verified':True}
    state={'daily_quality':{'policy':POLICY,'status':'passed','reviewed_edit_id':'edit',
        'reviews':[{'edit_id':'edit','passed':True,'render_sha256':sha(media),'plan_sha256':sha(document)}]}}
    assert verified_quality_export(state,edit)
    media.write_bytes(b'same-id-but-replaced-picture')
    assert not verified_quality_export(state,edit)
    media.write_bytes(b'old-reviewed-picture')
    document.write_bytes(b'{"changed":true}')
    assert not verified_quality_export(state,edit)


def test_missing_artifact_is_not_completed_on_restart(tmp_path):
    path=tmp_path/'lost.mp4'
    with pytest.raises(ValueError):
        EditingMixin._process_artifacts({'status':'completed','export_path':str(path)})


def test_changed_artifact_is_not_reused_on_restart(tmp_path):
    path=tmp_path/'final.mp4'; path.write_bytes(b'original')
    result={'status':'completed','export_path':str(path)}
    result['_artifact_hashes']=EditingMixin._process_artifacts(result)
    path.write_bytes(b'replaced')
    with pytest.raises(ValueError): EditingMixin._process_artifacts(result)


def test_registered_draft_receipt_requires_actual_draft_content_on_restart(tmp_path):
    draft=tmp_path/'registered-draft';draft.mkdir()
    with pytest.raises(ValueError):
        EditingMixin._process_artifacts({'status':'completed','draft_path':str(draft)})


def test_manual_completed_result_cannot_hide_lost_draft(workflow):
    manager, job, _, _, editor = workflow
    manager.run(job['id'],'rewrite')
    manager.select(job['id'],selection())
    first=manager.run(job['id'],'build')
    content=Path(first['editing']['draft_path'])/'draft_content.json'
    content.unlink()
    result=manager.run(job['id'],'build')
    assert result['status']=='blocked'
    assert len(editor.calls)==1


def test_manual_old_result_from_other_range_is_not_reused(workflow):
    manager, job, _, voice, editor = workflow
    manager.run(job['id'],'rewrite')
    manager.select(job['id'],selection())
    manager.run(job['id'],'build')
    loaded=manager.get(job['id'])
    manager.save(loaded,editing=None)
    result_dir=manager.settings.editing_dir/(job['id']+'-v1'); result_dir.mkdir(parents=True)
    (result_dir/'result.json').write_text(json.dumps({'status':'completed', 'job_id':job['id']+'-v1',
        'script_sha256':loaded['script_sha256'], 'source_ranges':[[50,52]], 'draft_path':'old-draft'}),'utf-8')
    result=manager.run(job['id'],'build')
    assert result.get('editing',{}).get('draft_path')!='old-draft'
    assert len(voice.calls)==1


def test_persisted_tts_id_resumes_without_second_whole_script_submission(tmp_path):
    class Resume(Session):
        def post(self,*args,**kwargs): pytest.fail('Existing request must not be resubmitted')
    session=Resume(valid_wav())
    result=VoiceBenchAdapter(_settings(tmp_path),session=session,sleep=lambda _:None).synthesize(
        '전체 대본을 한 번만 합성',tmp_path/'data'/'voice.wav',request_id=17)
    assert result['voicebench_request_id']==17 and session.posts==0


def test_waiting_tts_then_real_segment_progress_survives_total_elapsed(tmp_path,monkeypatch):
    from hotpost import operation_progress
    clock=[0]
    monkeypatch.setattr(operation_progress.time,'monotonic',lambda:clock[0])
    class QueueThenProgress(Session):
        def get(self,url,**kwargs):
            if url.endswith('/audio'): return Response(content=self.wav)
            self.gets+=1
            if self.gets<4: return Response({'id':17,'status':'queued','completed_segments':0})
            return Response({'id':17,'status':'succeeded' if self.gets==7 else 'running',
                'completed_segments':self.gets-4,'segment_count':3})
    session=QueueThenProgress(valid_wav())
    VoiceBenchAdapter(_settings(tmp_path),session=session,sleep=lambda _:clock.__setitem__(0,clock[0]+6)).synthesize(
        '실제 대본',tmp_path/'data'/'voice.wav')
    assert clock[0]>40 and session.posts==1


def test_actual_25fps_native_exposure_subframe_equivalence_and_new_frame(tmp_path):
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:pytest.skip('local ffmpeg unavailable')
    video=tmp_path/'native25.mp4'
    subprocess.run([ffmpeg,'-v','error','-y','-f','lavfi','-i',
        'testsrc2=size=80x120:rate=25:duration=2','-c:v','libx264','-pix_fmt','yuv420p',str(video)],
        check=True,capture_output=True,timeout=30)
    source={'id':'native','path':str(video),'sha256':hashlib.sha256(video.read_bytes()).hexdigest(),
        'video_meta':{'fps':25},'origin_url':'https://www.youtube.com/watch?v=native25'}
    original=progress.window(source,.2,1.2)
    unchanged=progress.window(source,.201,1.201)
    other=progress.window(source,.24,1.24)
    assert original['native_render_exposure']
    assert progress.same_window(original,unchanged)
    assert not progress.same_window(original,other)


def test_ledger_from_before_caption_projection_retains_failed_output_block(tmp_path):
    state, baseline, _=fixture(tmp_path)
    ledger=state['daily_quality']['progress_policy']
    # Recreate the persisted v1 projection before the subtitle field was added;
    # this is still the same render, not new caption correction evidence.
    for row in ledger['reviews']:
        row['output'].pop('caption_timeline',None)
    for attempt in ledger['attempts']:
        attempt['output'].pop('caption_timeline',None)
        attempt['key']=progress.digest(['render',attempt['output']])
    state=json.loads(json.dumps(state))
    assert progress.guard_render(state,baseline,'after-service-upgrade') is not None


def test_quality_accept_cannot_complete_file_changed_after_review(ready):
    studio,task=ready
    state=studio.store.get(task);edit=state['edits'][0]
    result=passed(edit['id'])
    result.update(render_sha256=hashlib.sha256(Path(edit['preview_path']).read_bytes()).hexdigest(),
        plan_sha256=hashlib.sha256(Path(edit['plan_path']).read_bytes()).hexdigest())
    job=studio.store.claim(task_id=task)
    Path(edit['preview_path']).write_bytes(b'unreviewed replacement arrived late')
    try:
        studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
    except ValueError:
        pass
    current=studio.store.get(task)
    assert current['status']!='completed'
    assert not current['edits'][0].get('quality_verified')


def test_quality_accept_cannot_complete_plan_changed_after_review(ready):
    studio,task=ready
    state=studio.store.get(task);edit=state['edits'][0]
    result=passed(edit['id'])
    result.update(render_sha256=hashlib.sha256(Path(edit['preview_path']).read_bytes()).hexdigest(),
        plan_sha256=hashlib.sha256(Path(edit['plan_path']).read_bytes()).hexdigest())
    job=studio.store.claim(task_id=task)
    Path(edit['plan_path']).write_text('{"script_text":"different late plan"}','utf-8')
    try:
        studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
    except ValueError:
        pass
    current=studio.store.get(task)
    assert current['status']!='completed'


def test_reserved_recovery_cannot_bypass_confirmed_rewrite_failure(ready,monkeypatch):
    studio,task=ready
    called=[]
    def queue(state,db):
        db.execute("DELETE FROM jobs WHERE task_id=?",(task,))
        quality=state['daily_quality']
        quality.update(pending='rewriting',feedback=[{'kind':'script_fact','beat_id':'b1',
            'reason':'기존에 확정 실패한 동일 사실 보완'}])
        progress.permit(state,'rewrite',reserve=True,job_id='confirmed-failed-rewrite')
        progress.finish_attempt(state,{'id':'confirmed-failed-rewrite'},failed=True)
        studio.store.enqueue(db,task,'rewrite',{'quality_rewrite':True},'retry-by-recovery')
    studio.store.change(task,queue)
    monkeypatch.setattr('hotpost.config.load_settings',lambda:studio.settings)
    monkeypatch.setattr('hotpost.studio.Studio',lambda *args,**kwargs:studio)
    monkeypatch.setattr(studio,'_rewrite',lambda state,job:called.append(job['id']) or {})
    monkeypatch.setattr(studio,'_accept',lambda *args:None)
    monkeypatch.setattr(sys,'argv',['run_reserved_recovery_job.py','--code','quality-fixture','--kind','rewrite'])
    try:
        runpy.run_path(str(Path(__file__).resolve().parents[1]/'tools'/'run_reserved_recovery_job.py'),run_name='__main__')
    except (ValueError,RuntimeError):
        pass
    assert called==[], 'Recovery invoked the same confirmed failed writing method'


def test_copy_removal_is_not_new_fact_regression_just_because_quote_moves():
    from hotpost.writing.script_integrity import inspect
    from hotpost.writing.pipeline import repair_preserves_integrity
    reference='이 제품은 삼 초면 접을 수 있어요. 책상 위에 흩어진 잡동사니들을 한 번에 모아서 정리할 수 있어요.'
    before='이 제품은 삼십 초면 접을 수 있어요. 책상 위에 흩어진 잡동사니들을 한 번에 모아서 정리할 수 있어요.'
    after='삼십 초면 이 제품을 접을 수 있어서 책상 위 잡동사니를 치워요.'
    old=inspect(reference,before);new=inspect(reference,after)
    assert {i['code'] for i in old['issues']}=={'quantity_changed','copied_body'}
    assert [i['code'] for i in new['issues']]==['quantity_changed']
    assert repair_preserves_integrity({'integrity_review':old},{'integrity_review':new})


def test_new_incorrect_quantity_cannot_hide_behind_same_defect_code():
    from hotpost.writing.script_integrity import inspect
    from hotpost.writing.pipeline import repair_preserves_integrity
    reference='이 제품은 삼 초면 접을 수 있어요.'
    before='이 제품은 삼십 초면 접을 수 있어요.'
    after='이 제품은 삼백 초면 접을 수 있어요.'
    old=inspect(reference,before);new=inspect(reference,after)
    assert not repair_preserves_integrity({'integrity_review':old},{'integrity_review':new})


def test_normal_quality_completion_then_duplicate_and_restart_preserve_state(ready):
    studio,task=ready
    state=studio.store.get(task);edit=state['edits'][0]
    result=passed(edit['id'])
    result.update(render_sha256=hashlib.sha256(Path(edit['preview_path']).read_bytes()).hexdigest(),
        plan_sha256=hashlib.sha256(Path(edit['plan_path']).read_bytes()).hexdigest())
    job=studio.store.claim(task_id=task)
    assert studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
    completed=studio.store.get(task)
    assert completed['status']=='completed'
    assert verified_quality_export(completed,completed['edits'][0])
    assert studio.store.finish(job,result,lambda s,db,r:pytest.fail('Duplicate completion applied')) is False
    studio.store.recover()
    assert studio.store.get(task)==completed
    assert studio.store.claim('production',task_id=task) is None


def test_saved_runner_response_cannot_bind_to_new_request_with_same_job_id(tmp_path):
    class Port(EditingMixin):
        def folder(self,task): return tmp_path
    port=Port();port.settings=SimpleNamespace()
    folder=tmp_path/'same-job';folder.mkdir()
    payload={'edit_id':'same-edit','launch':False,'plan_path':'new-plan.json'}
    old_request={'action':'register','output_dir':str(folder),'edit_id':'same-edit',
        'launch':False,'plan_path':'old-plan.json'}
    (folder/'register-result.json').write_text(json.dumps({'status':'completed',
        'request_sha256':hashlib.sha256(json.dumps(old_request,sort_keys=True).encode()).hexdigest()}),'utf-8')
    job={'id':'same-job','checkpoint':{'register_input':hashlib.sha256(
        json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}}
    with pytest.raises(ValueError):
        port._process({'id':'same-task'},job,'register',payload)


def _complete_quality_fixture(studio,task):
    state=studio.store.get(task);edit=state['edits'][0]
    result=passed(edit['id'])
    result.update(render_sha256=hashlib.sha256(Path(edit['preview_path']).read_bytes()).hexdigest(),
        plan_sha256=hashlib.sha256(Path(edit['plan_path']).read_bytes()).hexdigest())
    job=studio.store.claim('production',task_id=task)
    assert job['kind']=='quality_review'
    assert studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
    assert studio.store.get(task)['status']=='completed'


def test_completed_quality_pauses_preexisting_automatic_collection_without_erasing_history(ready):
    studio,task=ready
    studio.store.change(task,lambda s,db:studio.store.enqueue(db,task,'collect_sources',
        {'round':0,'run_id':s['run_id'],'source_policy':s['source_policy']},'preexisting-parallel-source'))
    with studio.store.transaction() as db:
        original=dict(db.execute("SELECT * FROM jobs WHERE task_id=? AND kind='collect_sources'",(task,)).fetchone())
        checkpoint={'request_id':456,'consumed_scope':'existing scope','not_before':0}
        db.execute('UPDATE jobs SET checkpoint=? WHERE id=?',(json.dumps(checkpoint),original['id']))
    _complete_quality_fixture(studio,task)
    assert studio.store.claim('sources',task_id=task) is None
    with studio.store.connect() as db:
        retained=dict(db.execute('SELECT * FROM jobs WHERE id=?',(original['id'],)).fetchone())
    assert retained['status']=='paused'
    assert retained['payload']==original['payload']
    assert json.loads(retained['checkpoint'])==checkpoint
    assert studio.store.get(task)['status']=='completed'


def test_completed_quality_missing_pool_goal_does_not_create_new_collection_round(ready):
    from hotpost.studio_sources import source_goal
    studio,task=ready
    _complete_quality_fixture(studio,task)
    assert source_goal(studio.store.get(task),studio.settings.source_min_usable)['ready'] is False
    before=studio.store.jobs(task)
    studio.store.change(task,lambda s,db:studio.ensure_source_collection(s,db))
    assert studio.store.jobs(task)==before
    assert studio.store.get(task)['status']=='completed'


def test_completed_quality_still_allows_explicit_manual_refresh(ready):
    studio,task=ready
    _complete_quality_fixture(studio,task)
    assert studio.store.claim('sources',task_id=task) is None
    studio.action(task,'refresh-sources',{'request':'사용자가 요청한 새로운 실제 제품 구도'})
    job=studio.store.claim('sources',task_id=task)
    assert job['kind']=='refresh_sources'
    assert not job['payload'].get('daily_quality_repair')
    assert studio.store.get(task)['status']=='completed'


def test_running_collection_arriving_after_quality_complete_preserves_media_and_new_assets(ready):
    from test_parallel_sources import asset
    from test_source_strategy import round_result
    studio,task=ready
    studio.store.change(task,lambda s,db:studio.store.enqueue(db,task,'collect_sources',
        {'round':0,'run_id':s['run_id'],'source_policy':s['source_policy']},'running-parallel-source'))
    running=studio.store.claim('sources',task_id=task)
    assert running['kind']=='collect_sources'
    _complete_quality_fixture(studio,task)
    completed=studio.store.get(task)
    export=Path(completed['edits'][0]['export_path'])
    original_bytes=export.read_bytes()
    incoming=asset(studio.folder(task),787,core=True)
    assert studio.store.finish(running,round_result(0,[incoming]),lambda s,db,r:studio._accept(s,running,r,db))
    after=studio.store.get(task)
    assert after['status']=='completed'
    assert after['edit_id']==completed['edit_id'] and after['edits']==completed['edits']
    assert after['daily_quality']==completed['daily_quality']
    assert export.read_bytes()==original_bytes
    assert any(s['sha256']==incoming['sha256'] for s in after['sources'])
    assert after['source_acquisition']['rounds'][-1]['job_id']==running['id']
    assert studio.store.claim('sources',task_id=task) is None
    assert studio.store.claim('production',task_id=task) is None


@pytest.mark.parametrize('failure',['start_workers','resume_queued'])
def test_late_server_activation_failure_closes_started_studio_owner(tmp_path,monkeypatch,failure):
    from hotpost import server
    from hotpost.studio import Studio as ActualStudio
    from hotpost.job_queue import JobQueue
    from hotpost.config import Settings
    settings=Settings(data_dir=tmp_path,studio_auto_top_enabled=False)
    created=[]
    class FailingQueue(JobQueue):
        def start_workers(self):
            if failure=='start_workers':raise RuntimeError('fault injected final activation')
        def resume_queued(self):
            if failure=='resume_queued':raise RuntimeError('fault injected queue resumption')
    def make_studio(settings):
        studio=ActualStudio(settings);created.append(studio);return studio
    monkeypatch.setattr(ActualStudio,'_worker',lambda self,lane=None:self.stop.wait())
    monkeypatch.setattr(server,'JobQueue',FailingQueue)
    monkeypatch.setattr(server,'Studio',make_studio)
    for name in ('SourceJobManager','TranscriptJobManager','LegacyProductionManager',
                 'PlatformSessionManager','AccountRegistry','ProductionManager'):
        monkeypatch.setattr(server,name,lambda *a,**k:object())
    try:
        with pytest.raises(RuntimeError,match='fault injected'):
            server.serve_many(settings,['127.0.0.1'],0)
        assert len(created)==1
        assert created[0].stop.is_set(), 'Socket setup failure left an active Studio owner'
        assert created[0]._lease is None or created[0]._lease.closed
    finally:
        for studio in created:
            studio.stop.set()
            if studio._lease and not studio._lease.closed:studio._lease.close()


def test_studio_close_drains_running_work_before_releasing_lease_and_allows_restart(tmp_path,monkeypatch):
    from hotpost.studio import Studio
    from hotpost.config import Settings
    settings=Settings(data_dir=tmp_path,studio_auto_top_enabled=False)
    release=threading.Event();all_started=threading.Event();completed=[];active=[];lock=threading.Lock()
    def worker(self,lane=None):
        with lock:
            active.append(lane)
            if len(active)==3:all_started.set()
        release.wait(5)
        (self.store.root/(lane+'-finished.bin')).write_bytes(b'completed owned work')
        with lock:completed.append(lane)
    monkeypatch.setattr(Studio,'_worker',worker)
    original=Studio(settings)
    closer=None;follower=None;restarted=None
    try:
        assert all_started.wait(2)
        closer=threading.Thread(target=original.close);closer.start()
        assert original.stop.wait(2)
        follower=Studio(settings)
        assert follower._lease is None, 'Ownership released before running jobs finished'
        assert closer.is_alive() and not completed
        release.set();closer.join(3)
        assert not closer.is_alive() and sorted(completed)==['media','scripts','sources']
        restarted=Studio(settings)
        assert restarted._lease is not None
        restarted.close()
    finally:
        release.set();original.stop.set()
        if closer:closer.join(3)
        for studio in (original,follower,restarted):
            if studio and studio._lease and not studio._lease.closed:studio._lease.close()


def test_access_receipts_preserve_distinct_requests_and_cannot_unconsume_failed_scope():
    from hotpost.source_search.strategy import merge_history,fresh_queries,consumed_scope
    failed={'provider':'tiktok','query':'빨간 패딩','status':'no_results','requests':[{'operation':'search','at':1}]}
    one={'provider':'tiktok','query':'빨간 패딩','status':'rate_limited','http_status':429,
        'reason':'current throttling','requests':[{'operation':'search','at':2}]}
    two={**one,'requests':[{'operation':'search','at':3}]}
    history=merge_history([failed],[one],[two],[copy.deepcopy(one)])
    assert len(history)==3
    assert sum(consumed_scope(r) for r in history)==1
    assert sum(r.get('http_status')==429 for r in history)==2
    assert fresh_queries(['빨간 패딩'],'tiktok',history)==[]
    assert fresh_queries(['빨간 패딩'],'tiktok',history,scope={'cursor':'ACTUAL-NEXT-CURSOR'})==['빨간 패딩']
    waits=merge_history([one],[two])
    assert fresh_queries(['빨간 패딩'],'tiktok',waits)==['빨간 패딩']


def test_multi_interface_server_closes_studio_only_after_last_socket(tmp_path,monkeypatch):
    from hotpost import server
    from hotpost.studio import Studio as ActualStudio
    from hotpost.config import Settings
    settings=Settings(data_dir=tmp_path,studio_auto_top_enabled=False)
    studios=[]
    def create(settings):
        studio=ActualStudio(settings);studios.append(studio);return studio
    monkeypatch.setattr(ActualStudio,'_worker',lambda self,lane=None:self.stop.wait())
    monkeypatch.setattr(server,'Studio',create)
    for name in ('SourceJobManager','TranscriptJobManager','LegacyProductionManager',
                 'PlatformSessionManager','AccountRegistry','ProductionManager'):
        monkeypatch.setattr(server,name,lambda *a,**k:object())
    servers=server.serve_many(settings,['127.0.0.1','127.0.0.2'],0)
    queue=servers[0].RequestHandlerClass.job_queue
    try:
        assert len(studios)==1
        servers[0].server_close()
        assert not studios[0].stop.is_set() and not queue._closed
        servers[1].server_close()
        assert studios[0].stop.is_set() and queue._closed
        assert studios[0]._lease is None or studios[0]._lease.closed
        servers[1].server_close()
    finally:
        for server in servers:server.server_close()
        for studio in studios:
            studio.stop.set()
            if studio._lease and not studio._lease.closed:studio._lease.close()


def test_queue_thread_creation_fault_does_not_strand_lease(tmp_path,monkeypatch):
    from hotpost.job_queue import JobQueue
    from hotpost.config import Settings
    settings=Settings(data_dir=tmp_path)
    queue=JobQueue(settings,autostart=False)
    monkeypatch.setattr(threading.Thread,'start',lambda self:(_ for _ in ()).throw(RuntimeError('fault injected thread resource limit')))
    try:
        with pytest.raises(RuntimeError,match='fault injected'):
            queue.start_workers()
        queue.close()
        assert queue._lease is None or queue._lease.closed
        restarted=JobQueue(settings,autostart=False)
        restarted.close()
    finally:
        if queue._lease and not queue._lease.closed:queue._lease.close()


def _service_settings(tmp_path,monkeypatch):
    from hotpost import studio_services as service
    from hotpost.config import Settings
    from hotpost.voicebench_adapter import VoiceBenchAdapter
    root=tmp_path/'separate-voice-service'
    python=root/'.venv'/('Scripts/python.exe' if service.os.name=='nt' else 'bin/python')
    python.parent.mkdir(parents=True);python.touch()
    data=tmp_path/'client';data.mkdir()
    monkeypatch.setattr(VoiceBenchAdapter,'_api_key',lambda self:'isolated-test-key')
    settings=Settings(data_dir=data,voicebench_root=root,voicebench_url='http://127.0.0.1:18767')
    command=[str(python),'-X','utf8','-m','voicebench','--host','127.0.0.1','--port','18767']
    receipt=root/'.runtime'/'hotpost-startup-18767.json';receipt.parent.mkdir()
    receipt.write_text(json.dumps({'pid':321,'process_created':123.0,'command':command,'cwd':str(root)}),'utf-8')
    return service,settings,command,receipt


def test_uninspectable_owned_cold_service_defers_without_new_process_or_key_receipt(tmp_path,monkeypatch):
    import requests
    from hotpost.model_service import ModelServiceUnavailable
    service,settings,command,receipt=_service_settings(tmp_path,monkeypatch)
    original=receipt.read_bytes()
    def refused(*a,**k):raise requests.ConnectionError('startup not listening yet')
    monkeypatch.setattr(service.requests,'Session',lambda:SimpleNamespace(get=refused))
    monkeypatch.setattr(service.psutil,'Process',lambda pid:(_ for _ in ()).throw(service.psutil.AccessDenied(pid)))
    monkeypatch.setattr(service.subprocess,'Popen',lambda *a,**k:pytest.fail('Unknown ownership must not duplicate service'))
    with pytest.raises(ModelServiceUnavailable) as held:
        service.ensure_local(settings,'voice')
    assert held.value.attempted is False
    assert receipt.read_bytes()==original and b'isolated-test-key' not in original


@pytest.mark.parametrize('code,body',[(401,{}),(403,{}),(200,{'service':'another-app'}),(302,{})])
def test_service_auth_wrong_app_and_redirect_are_configuration_failure_not_wait(tmp_path,monkeypatch,code,body):
    from hotpost.model_service import ModelServiceUnavailable
    service,settings,_,_=_service_settings(tmp_path,monkeypatch)
    monkeypatch.setattr(service.requests,'Session',lambda:SimpleNamespace(get=lambda *a,**k:Response(body,status=code)))
    monkeypatch.setattr(service.subprocess,'Popen',lambda *a,**k:pytest.fail('Configuration fault must not launch another service'))
    with pytest.raises(RuntimeError) as failure:service.ensure_local(settings,'voice')
    assert not isinstance(failure.value,ModelServiceUnavailable)


def test_existing_owned_startup_wait_resumes_after_exact_service_health_arrives(tmp_path,monkeypatch):
    import requests
    from hotpost.model_service import ModelServiceUnavailable
    service,settings,command,receipt=_service_settings(tmp_path,monkeypatch)
    healthy=[False]
    def get(*a,**k):
        assert k['allow_redirects'] is False
        if not healthy[0]:raise requests.ConnectionError('service still loading')
        return Response({'service':'VoiceBench External TTS API'})
    monkeypatch.setattr(service.requests,'Session',lambda:SimpleNamespace(get=get))
    monkeypatch.setattr(service.psutil,'Process',lambda pid:SimpleNamespace(
        is_running=lambda:True,create_time=lambda:123.0,cmdline=lambda:command,cwd=lambda:str(settings.voicebench_root)))
    monkeypatch.setattr(service.subprocess,'Popen',lambda *a,**k:pytest.fail('Existing cold service must not be relaunched'))
    with pytest.raises(ModelServiceUnavailable) as first:service.ensure_local(settings,'voice')
    assert first.value.attempted is False
    healthy[0]=True
    service.ensure_local(settings,'voice')


def test_dead_same_startup_cannot_be_launched_again_on_each_automatic_retry(tmp_path,monkeypatch):
    import requests
    service,settings,command,receipt=_service_settings(tmp_path,monkeypatch)
    receipt.unlink()
    launches=[];clock=[0]
    monkeypatch.setattr(service.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(service.time,'sleep',lambda _:clock.__setitem__(0,clock[0]+1))
    def refused(*a,**k):raise requests.ConnectionError('service never bound')
    monkeypatch.setattr(service.requests,'Session',lambda:SimpleNamespace(get=refused))
    monkeypatch.setattr(service.subprocess,'Popen',lambda *a,**k:launches.append(1) or SimpleNamespace(pid=321,poll=lambda:1))
    monkeypatch.setattr(service.psutil,'Process',lambda pid:SimpleNamespace(
        is_running=lambda:False,create_time=lambda:123.0,cmdline=lambda:command,cwd=lambda:str(settings.voicebench_root)))
    for _ in range(2):
        try:service.ensure_local(settings,'voice')
        except RuntimeError:pass
    assert len(launches)==1, 'Unchanged confirmed-dead startup was relaunched by automatic retry'


def test_unattempted_service_wait_after_explicit_retry_does_not_reuse_old_failure_cap(ready,monkeypatch):
    from hotpost.model_service import ModelServiceUnavailable
    studio,task=ready
    with studio.store.transaction() as db:
        row=db.execute("SELECT id,checkpoint FROM jobs WHERE task_id=? AND kind='quality_review'",(task,)).fetchone()
        checkpoint=json.loads(row['checkpoint']);checkpoint.update(service_retries=3,request_id=6789)
        db.execute("UPDATE jobs SET checkpoint=?,status='failed',error='past attempted service failures' WHERE id=?",(json.dumps(checkpoint),row['id']))
    studio.store.change(task,lambda s,db:s.update(status='attention',error='past attempted service failures'))
    studio.action(task,'retry',{'job_id':row['id']})
    before=studio.store.get(task)['daily_quality']
    def wait(state,job):
        studio.stop.set()
        raise ModelServiceUnavailable('cold owned service has not attempted this request',attempted=False)
    monkeypatch.setattr(studio,'_quality_review',wait)
    studio._worker('production')
    current=studio.store.get(task)
    assert current['daily_quality']==before
    job=next(j for j in studio.store.jobs(task) if j['id']==row['id'])
    assert job['status']=='queued'
    assert current['status']=='retry_wait'
    with studio.store.transaction() as db:
        checkpoint=json.loads(db.execute('SELECT checkpoint FROM jobs WHERE id=?',(row['id'],)).fetchone()[0])
        assert checkpoint['service_retries']==3 and checkpoint['request_id']==6789
        checkpoint['not_before']=0
        db.execute('UPDATE jobs SET checkpoint=? WHERE id=?',(json.dumps(checkpoint),row['id']))
    def review_after_service_ready(state,job):
        assert state['status']=='quality_review'
        assert job['checkpoint']['request_id']==6789
        studio.stop.set()
        edit=state['edits'][0];result=passed(edit['id'])
        result.update(render_sha256=hashlib.sha256(Path(edit['preview_path']).read_bytes()).hexdigest(),
            plan_sha256=hashlib.sha256(Path(edit['plan_path']).read_bytes()).hexdigest())
        return result
    studio.stop.clear()
    monkeypatch.setattr(studio,'_quality_review',review_after_service_ready)
    studio._worker('production')
    assert studio.store.get(task)['status']=='completed'
    assert next(j for j in studio.store.jobs(task) if j['id']==row['id'])['status']=='done'


@pytest.mark.parametrize('kind',['prepare','voice','edit','quality_reedit','export','collect_sources'])
def test_disabled_photo_setting_blocks_old_queued_content_work_without_quality_charge(tmp_path,monkeypatch,kind):
    from hotpost.config import Settings
    from hotpost.studio import Studio
    studio=Studio(Settings(data_dir=tmp_path,photo_production_enabled=False),workers=False)
    source=tmp_path/'old-photo-source.bin';source.write_bytes(b'preserved original photo')
    voice=tmp_path/'old-photo-voice.wav';voice.write_bytes(b'preserved approved personal voice')
    state,_=studio.store.create('historical_photo','Old photo work',prepare=False,
        automation={'protocol':2,'active':True,'selection_mode':'manual'},initial={
            'creation_mode':'photo_post','sources':[{'id':'photo','path':str(source),'sha256':'historical'}],
            'daily_quality':{'policy':POLICY,'repair_round':8,'pending':'reediting','status':'needs_attention',
                'reviews':[{'edit_id':'historical','passed':False,'issues':[]}],'render_accounting':[{'repair_charge':1}]},
            'source_acquisition':{'round':5,'queries':[{'provider':'old','query':'kept','status':'no_results'}]}})
    task=state['id']
    studio.store.change(task,lambda s,db:studio.store.enqueue(db,task,kind,{},'old-photo-'+kind))
    before=studio.store.get(task)
    monkeypatch.setattr(studio,'_'+kind,lambda *a:pytest.fail('Disabled photo content work must not call service/renderer'))
    original_fail=studio.store.fail
    def stop_after_policy_block(job,error):
        studio.stop.set()
        return original_fail(job,error)
    monkeypatch.setattr(studio.store,'fail',stop_after_policy_block)
    studio._worker()
    after=studio.store.get(task)
    assert after['daily_quality']==before['daily_quality']
    assert after['source_acquisition']==before['source_acquisition']
    assert after['sources']==before['sources'] and after['runs']==before['runs']
    assert source.read_bytes()==b'preserved original photo'
    assert voice.read_bytes()==b'preserved approved personal voice'
    assert len(studio.store.jobs(task))==1
    assert studio.store.jobs(task)[0]['status']=='failed'


@pytest.mark.parametrize('kind',['voice','edit','export','quality_reedit'])
def test_reserved_recovery_obeys_disabled_photo_policy_before_service_and_method_accounting(tmp_path,monkeypatch,kind):
    from hotpost.config import Settings
    from hotpost.studio import Studio
    settings=Settings(data_dir=tmp_path,photo_production_enabled=False)
    studio=Studio(settings,workers=False)
    original=tmp_path/'original-photo.bin';original.write_bytes(b'original preserved')
    state,_=studio.store.create('reserved_old_photo','Old photo',prepare=False,
        automation={'protocol':2,'active':True,'selection_mode':'manual'},initial={
            'creation_mode':'photo_post','daily_quality':{'policy':POLICY,'status':'needs_attention',
                'repair_round':5,'pending':'reediting','reviews':[],'render_accounting':[{'repair_charge':1}]},
            'sources':[{'id':'photo','path':str(original),'sha256':'preserved'}]})
    task=state['id']
    studio.store.change(task,lambda s,db:studio.store.enqueue(db,task,kind,{},'reserved-photo-'+kind))
    before=studio.store.get(task);calls=[]
    monkeypatch.setattr('hotpost.config.load_settings',lambda:settings)
    monkeypatch.setattr('hotpost.studio.Studio',lambda *a,**k:studio)
    monkeypatch.setattr(studio,'_'+kind,lambda *a:calls.append(kind) or {})
    monkeypatch.setattr(studio,'_accept',lambda *a:None)
    monkeypatch.setattr(sys,'argv',['run_reserved_recovery_job.py','--code','reserved_old_photo','--kind',kind])
    try:runpy.run_path(str(Path(__file__).resolve().parents[1]/'tools'/'run_reserved_recovery_job.py'),run_name='__main__')
    except (ValueError,RuntimeError):pass
    after=studio.store.get(task)
    assert calls==[]
    assert after['daily_quality']==before['daily_quality']
    assert after['runs']==before['runs'] and after['sources']==before['sources']
    assert original.read_bytes()==b'original preserved'


@pytest.mark.parametrize('stage,status',[('status',429),('status',503),('status',None),
    ('audio',429),('audio',503),('audio',None)])
def test_tts_status_and_audio_transfer_wait_preserves_id_and_resumes_without_resubmission(tmp_path,stage,status):
    import requests
    from hotpost.model_service import ModelServiceUnavailable
    broken=[True];ids=[]
    class Transfer(Session):
        def post(self,url,**kwargs):
            self.posts+=1
            return Response({'id':17,'status':'queued' if stage=='status' else 'succeeded'})
        def get(self,url,**kwargs):
            is_audio=url.endswith('/audio')
            if broken[0] and (is_audio==(stage=='audio')):
                if status is None:raise requests.ReadTimeout('temporary transfer silence')
                response=requests.Response();response.status_code=status;response.url=url
                response.headers['Retry-After']='120';response._content=b'{}'
                return response
            return Response(content=self.wav) if is_audio else Response({'id':17,'status':'succeeded'})
    session=Transfer(valid_wav());settings=_settings(tmp_path)
    target=settings.data_dir/'voice.wav';target.parent.mkdir();target.write_bytes(b'preserved old voice')
    adapter=VoiceBenchAdapter(settings,session=session,sleep=lambda _:None)
    start=time.time()
    with pytest.raises(ModelServiceUnavailable) as wait:
        adapter.synthesize('실제 대본',target,on_submitted=ids.append)
    assert wait.value.attempted is False
    if status is not None:assert wait.value.retry_at>=start+119
    assert ids==[17] and session.posts==1 and target.read_bytes()==b'preserved old voice'
    broken[0]=False
    result=adapter.synthesize('실제 대본',target,request_id=ids[-1],on_submitted=ids.append)
    assert result['voicebench_request_id']==17 and session.posts==1
    assert target.read_bytes()==session.wav


@pytest.mark.parametrize('status',[401,403])
def test_tts_authentication_failure_does_not_become_auto_service_wait(tmp_path,status):
    import requests
    from hotpost.model_service import ModelServiceUnavailable
    class Auth(Session):
        def get(self,url,**kwargs):
            response=requests.Response();response.status_code=status;response.url=url;response._content=b'{}'
            return response
    session=Auth(valid_wav());settings=_settings(tmp_path)
    with pytest.raises(RuntimeError) as blocked:
        VoiceBenchAdapter(settings,session=session,sleep=lambda _:None).synthesize('실제 대본',settings.data_dir/'voice.wav',request_id=17)
    assert not isinstance(blocked.value,ModelServiceUnavailable)
    assert session.posts==0


def test_manual_unknown_tts_submission_reuses_stable_generation_key_on_retry(workflow,monkeypatch):
    from hotpost.model_service import ModelServiceUnavailable
    manager,job,_,_,_=workflow
    manager.run(job['id'],'rewrite');manager.select(job['id'],selection())
    clock=[1000.0]
    monkeypatch.setattr('hotpost.production.time.time',lambda:clock[0])
    keys=[]
    class UnknownThenKnown:
        def synthesize(self,text,target,request_id=None,on_submitted=None,generation_key=None,**kwargs):
            keys.append(generation_key)
            if len(keys)==1:
                raise ModelServiceUnavailable('POST accepted but response lost',attempted=False)
            on_submitted(17);target.write_bytes(valid_wav())
            return {'output_path':str(target),'voicebench_request_id':17}
    manager.voice=UnknownThenKnown()
    first=manager.run(job['id'],'build')
    assert not first.get('voicebench_request_id')
    assert first['status']=='service_wait' and first['service_retry_at']>clock[0]
    files={str(p):p.read_bytes() for p in manager.folder(job['id']).rglob('*') if p.is_file()}
    early=manager.run(job['id'],'build')
    assert early==first and len(keys)==1
    assert {str(p):p.read_bytes() for p in manager.folder(job['id']).rglob('*') if p.is_file()}==files
    clock[0]=first['service_retry_at']+.01
    second=manager.run(job['id'],'build')
    assert len(keys)==2 and keys[0] and keys[0]==keys[1]
    assert second['status']=='draft_ready' and second['voicebench_request_id']==17


def test_chunked_audio_transfer_resumes_existing_request_without_new_post(tmp_path):
    import requests
    from hotpost.model_service import ModelServiceUnavailable
    interrupted=[True];ids=[]
    class Chunked(Session):
        def post(self,url,**kwargs):
            self.posts+=1;return Response({'id':17,'status':'succeeded'})
        def get(self,url,**kwargs):
            if url.endswith('/audio'):
                if interrupted[0]:raise requests.exceptions.ChunkedEncodingError('response body interrupted')
                return Response(content=self.wav)
            return Response({'id':17,'status':'succeeded'})
    settings=_settings(tmp_path);target=settings.data_dir/'voice.wav'
    target.parent.mkdir();target.write_bytes(b'preserved old approved voice')
    session=Chunked(valid_wav());adapter=VoiceBenchAdapter(settings,session=session,sleep=lambda _:None)
    with pytest.raises(ModelServiceUnavailable) as waiting:
        adapter.synthesize('실제 대본',target,on_submitted=ids.append)
    assert waiting.value.attempted is False
    assert ids==[17] and session.posts==1 and target.read_bytes()==b'preserved old approved voice'
    interrupted[0]=False
    assert adapter.synthesize('실제 대본',target,request_id=17)['voicebench_request_id']==17
    assert session.posts==1 and target.read_bytes()==session.wav


def test_authenticated_ready_resolves_old_startup_failure_without_erasing_failure_evidence(tmp_path,monkeypatch):
    import requests
    service,settings,command,receipt=_service_settings(tmp_path,monkeypatch)
    old=json.loads(receipt.read_text('utf-8'));old.update(status='failed',exit_code=11)
    receipt.write_text(json.dumps(old),'utf-8')
    healthy=[True];launches=[]
    def get(*a,**k):
        if not healthy[0]:raise requests.ConnectionError('later service restart required')
        return Response({'service':'VoiceBench External TTS API'})
    def process(pid):
        if pid==321:raise service.psutil.NoSuchProcess(pid)
        return SimpleNamespace(is_running=lambda:True,create_time=lambda:456.0,
            cmdline=lambda:command,cwd=lambda:str(settings.voicebench_root))
    def launch(*a,**k):
        launches.append(a[0]);healthy[0]=True
        return SimpleNamespace(pid=444,poll=lambda:None)
    monkeypatch.setattr(service.requests,'Session',lambda:SimpleNamespace(get=get))
    monkeypatch.setattr(service.psutil,'Process',process)
    monkeypatch.setattr(service.subprocess,'Popen',launch)
    service.ensure_local(settings,'voice')
    assert json.loads(receipt.read_text('utf-8'))['status']=='ready'
    history=json.loads(receipt.read_text('utf-8'))['startup_failure_history']
    assert any(item.get('pid')==321 and item.get('exit_code')==11 for item in history)
    assert not launches
    healthy[0]=False
    service.ensure_local(settings,'voice')
    assert len(launches)==1
    assert json.loads(receipt.read_text('utf-8'))['startup_failure_history']==history
