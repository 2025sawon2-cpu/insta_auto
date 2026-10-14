"""Independent counterexamples for the durable quality progress contract."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from hotpost import quality_progress as progress
from test_daily_quality import ready as daily_ready


def plan(source_name='a', *, beat_id='beat-1', cover='제품 궁금증'):
    return {'script_text':'제품을 실제로 사용하는 이야기', 'voice':{'sha256':'approved-voice'},
        'sources':[{'id':source_name,'sha256':source_name+'-sha','original_sha256':source_name+'-parent',
                    'origin_url':'https://www.youtube.com/watch?v='+source_name}],
        'shots':[{'id':'shot','source_id':source_name,'start':2,'end':4}],
        'beats':[{'id':beat_id,'text':'얼룩이 사라지는 제품 효과','selected_shot_id':'shot',
                  'source_start':2,'source_end':4,'start':0,'end':2}],
        'cover_spec':{'lines':[cover,'어떻게 다를까요?'],'source':{'source_sha256':'cover-sha','timestamp':2}}}


def store_plan(tmp_path, state, document, edit_id):
    path=tmp_path/(edit_id+'.json')
    path.write_text(json.dumps(document,ensure_ascii=False),encoding='utf-8')
    state['edits'].append({'id':edit_id,'plan_path':str(path)})
    state['edit_id']=edit_id
    return {'edit_id':edit_id,'render_sha256':hashlib.sha256(edit_id.encode()).hexdigest(),
            'plan_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'passed':False,
            'issues':[{'kind':'scene_gap','beat_id':document['beats'][0]['id'],
                       'reason':'별도 도구의 효과가 제품 단독 효과로 보임'}]}


def fixture(tmp_path, *, round_number=3):
    state={'edits':[], 'edit_id':None, 'sources':[], 'automation':{'active':True},
           'daily_quality':{'repair_round':round_number,'max_repairs':3,'reviews':[],
                            'render_accounting':[{'repair_charge':1,'repair_round_after':round_number}]}}
    document=plan()
    review=store_plan(tmp_path,state,document,'baseline')
    state['daily_quality']['feedback']=copy.deepcopy(review['issues'])
    progress.observe(state,review)
    return state,document,review


def bind_replacement(state, source_name='b'):
    source=plan(source_name)['sources'][0]
    state['sources'].append(source)
    issue=copy.deepcopy(state['daily_quality']['feedback'][0])
    state['daily_quality']['scene_requirements']={'ready':True,'requirements':[
        {**issue,'covered':True,'matches':[{'source_id':source['id'],'source_sha256':source['sha256'],
            'source_start':2,'source_end':4,'proof_mode':'direct_state','supporting_frame_ids':['new-effect-frame']}]}]}


def test_migration_is_idempotent_and_preserves_exhausted_manual_stop(tmp_path):
    state,_,review=fixture(tmp_path)
    state['daily_quality'].pop('progress_policy')
    state['daily_quality'].update(reviews=[review],pending='exhausted')
    state['automation'].update(active=False,paused_by_user=True)
    usage=copy.deepcopy(state['daily_quality']['render_accounting'])
    progress.ensure(state);once=copy.deepcopy(state);progress.ensure(state)
    assert state==once
    assert progress.permit(state,'quality_reedit',reserve=True,job_id='fourth') is None
    assert state['daily_quality']['pending']=='exhausted'
    assert state['daily_quality']['repair_round']==3
    assert state['daily_quality']['render_accounting']==usage
    assert not state['automation']['active'] and state['automation']['paused_by_user']


def test_fourth_repair_with_actual_new_relevant_method_is_allowed_without_reset(tmp_path):
    state,_,_=fixture(tmp_path);bind_replacement(state)
    usage=copy.deepcopy(state['daily_quality']['render_accounting'])
    assert progress.permit(state,'quality_reedit',reserve=True,job_id='fourth')
    assert progress.guard_render(state,plan('b'),'fourth') is None
    assert state['daily_quality']['repair_round']==3
    assert state['daily_quality']['render_accounting']==usage


def test_actual_new_youtube_video_is_distinct_despite_shared_watch_path():
    a=plan('a')['sources'][0];b=plan('b')['sources'][0]
    a.pop('original_sha256');b.pop('original_sha256')
    assert progress.origin(a) != progress.origin(b)


def test_known_same_parent_different_repost_url_is_same_lineage():
    original=plan('a')['sources'][0]
    repost={**original,'id':'new-id','sha256':'reencoded','origin_url':'https://www.tiktok.com/@seller/video/999'}
    assert progress.origin(original)==progress.origin(repost)


def test_a_b_a_reencoded_cycle_is_blocked_while_new_b_is_allowed(tmp_path):
    state,original,_=fixture(tmp_path)
    assert progress.guard_render(state,plan('b'),'attempt-b') is None
    returned=copy.deepcopy(original)
    returned['sources'][0].update(id='reencoded-a',sha256='reencoded-new-sha',path='renamed.mp4')
    returned['shots'][0]['source_id']='reencoded-a'
    returned['beats'][0].update(id='beat-77',start=8,end=10)
    assert progress.guard_render(state,returned,'attempt-a-again') is not None


def test_moving_beat_and_rewording_reason_keeps_defect_identity(tmp_path):
    state,document,review=fixture(tmp_path)
    moved=copy.deepcopy(document);moved['beats'][0].update(id='beat-77',start=8,end=10)
    updated=store_plan(tmp_path,state,moved,'moved')
    updated['issues'][0]['reason']='도구 후처리를 스프레이 효과라고 오해함'
    old=progress.finding(review['issues'][0],document)['id']
    current=progress.finding(updated['issues'][0],moved)['id']
    assert current==old
    assert not progress.observe(state,updated)['improved']
    assert len(state['daily_quality']['progress_policy']['defects'])==1


def test_unrelated_cover_change_cannot_resolve_unchanged_body_defect(tmp_path):
    state,document,_=fixture(tmp_path)
    updated=copy.deepcopy(document);updated['cover_spec']['lines'][0]='다른 표지 문구'
    review=store_plan(tmp_path,state,updated,'cover-only');review.update(passed=True,issues=[])
    row=progress.observe(state,review)
    assert row['conflict'] and not row['passed'] and not row['improved']
    assert state['daily_quality']['progress_policy']['best']['edit_id']=='baseline'
    assert state['daily_quality']['progress_policy']['decision']['action']=='recheck'


def test_duplicate_completion_does_not_duplicate_decisions_attempts_or_history(tmp_path):
    state,_,review=fixture(tmp_path);before=copy.deepcopy(state)
    assert progress.observe(state,copy.deepcopy(review))['duplicate']
    assert state==before
    restarted=json.loads(json.dumps(state,ensure_ascii=False))
    progress.ensure(restarted);progress.observe(restarted,copy.deepcopy(review))
    assert restarted==before


def test_confirmed_failed_same_job_is_not_permitted_again(tmp_path):
    state,_,_=fixture(tmp_path);bind_replacement(state)
    method=progress.permit(state,'quality_reedit',reserve=True,job_id='same-job')
    attempt=next(a for a in state['daily_quality']['progress_policy']['attempts'] if a['key']==method['key'])
    attempt['status']='failed'
    assert progress.permit(state,'quality_reedit',reserve=True,job_id='same-job') is None


def test_failed_actual_render_same_job_is_not_replayed(tmp_path):
    state,_,_=fixture(tmp_path)
    assert progress.guard_render(state,plan('b'),'same-job') is None
    attempt=state['daily_quality']['progress_policy']['attempts'][-1]
    attempt.update(status='failed')
    assert progress.guard_render(state,plan('b'),'same-job') is not None


def test_unrelated_new_source_does_not_ground_reedit(tmp_path):
    state,_,_=fixture(tmp_path)
    state['sources'].append(plan('unrelated')['sources'][0])
    state['daily_quality']['scene_requirements']={'ready':True,'requirements':[]}
    assert progress.permit(state,'quality_reedit',job_id='unrelated') is None
    assert state['daily_quality']['repair_round']==3


def test_important_regression_does_not_replace_best_output(tmp_path):
    state,_,_=fixture(tmp_path)
    review=store_plan(tmp_path,state,plan('b'),'regressed')
    review['issues']=[{'kind':'watermark','beat_id':'beat-1','reason':'읽히는 판매자 로고가 새로 나타남'}]
    result=progress.observe(state,review)
    assert result['resolved'] and result['introduced'] and not result['improved']
    assert state['daily_quality']['progress_policy']['best']['edit_id']=='baseline'


def test_actual_crop_identity_ignores_evidence_paths_policy_and_review_prose():
    original=plan()
    original['cover_spec']['source']['cover_crop_evidence']={
        'policy':'crop-contract-v1','source_sha256':'cover-source','timestamp':2,
        'original_frame_sha256':'original-frame','image_sha256':'actual-cropped-pixels',
        'crop':[.2,.3,.8,.9],'watermark_masks':[],
        'original_frame_path':'previous/frame.png','native_frame_path':'previous/native.png',
        'binding_sha256':'binding-contract-v1','geometry_requires_independent_review':True}
    restated=copy.deepcopy(original)
    restated['cover_spec']['source']['cover_crop_evidence'].update(
        policy='crop-contract-v2',original_frame_path='new-name/frame.png',
        native_frame_path='new-name/native.png',binding_sha256='binding-contract-v2')
    assert progress.projection(original)==progress.projection(restated)


def test_missing_plan_cannot_create_verified_best_or_completion(tmp_path):
    state,_,_=fixture(tmp_path)
    state['edits'].append({'id':'lost-plan','plan_path':str(tmp_path/'missing.json')})
    state['edit_id']='lost-plan'
    review={'edit_id':'lost-plan','render_sha256':'other-output','plan_sha256':'lost-plan-hash',
            'passed':True,'issues':[]}
    result=progress.observe(state,review)
    assert not result.get('passed')
    assert state['daily_quality']['progress_policy']['best']['edit_id']=='baseline'


def test_same_cropped_pixels_with_different_masks_is_actual_cover_change():
    original=plan();original['cover_spec']['source']['cover_crop_evidence']={
        'source_sha256':'source','timestamp':2,'image_sha256':'pixels','crop':[.2,.3,.8,.9],
        'watermark_masks':[]}
    changed=copy.deepcopy(original)
    changed['cover_spec']['source']['cover_crop_evidence']['watermark_masks']=[{
        'source_start':1,'source_end':3,'rectangle':{'width':.2,'height':.1},'strength':.8}]
    assert progress.projection(original)!=progress.projection(changed)


def test_caption_pcm_repair_uses_approved_voice_and_allows_once(tmp_path):
    state,document,review=fixture(tmp_path)
    state['daily_quality'].pop('progress_policy')
    review['issues']=[{'kind':'caption_sync','beat_id':'','reason':'AAC packet gap shifts captions'}]
    review['audio_timing_audit']={'passed':False,
        'method':'decoded-sample-count-and-waveform-time-correlation-v1',
        'duration_delta_seconds':-2.043,
        'anchors':[{'voice_time':5,'render_time':2.957,'offset_seconds':-2.043,'correlation':.95}]}
    state['daily_quality']['feedback']=copy.deepcopy(review['issues'])
    progress.observe(state,review)
    state['daily_quality']['reviews'].append(review)
    fixed=copy.deepcopy(document);fixed['audio_timing_repair']=True
    fixed['quality_audio_repair']={'method':'approved-voice-pcm-clock',
        'voice_sha256':document['voice']['sha256'],
        'audit':{k:review['audio_timing_audit'][k] for k in ('method','duration_delta_seconds','anchors')}}
    assert fixed['voice']['sha256']==document['voice']['sha256']
    assert progress.guard_render(state,fixed,'pcm-fix') is None
    assert progress.guard_render(state,fixed,'pcm-again') is not None


def test_caption_metadata_bool_without_failed_clock_evidence_cannot_reopen_render(tmp_path):
    state,document,review=fixture(tmp_path)
    state['daily_quality'].pop('progress_policy')
    review['issues']=[{'kind':'caption_sync','beat_id':'','reason':'audio synchronization finding'}]
    state['daily_quality']['feedback']=copy.deepcopy(review['issues'])
    progress.observe(state,review)
    metadata_only=copy.deepcopy(document);metadata_only['audio_timing_repair']=True
    assert progress.guard_render(state,metadata_only,'metadata-only') is not None


def test_caption_repair_dictionary_without_actual_audit_cannot_reopen_render(tmp_path):
    state,document,review=fixture(tmp_path)
    state['daily_quality'].pop('progress_policy')
    review['issues']=[{'kind':'caption_sync','beat_id':'','reason':'audio synchronization finding'}]
    state['daily_quality']['feedback']=copy.deepcopy(review['issues'])
    progress.observe(state,review)
    fabricated=copy.deepcopy(document);fabricated['audio_timing_repair']=True
    fabricated['quality_audio_repair']={'method':'approved-voice-pcm-clock',
        'voice_sha256':document['voice']['sha256'],
        'audit':{'method':None,'duration_delta_seconds':None,'anchors':None}}
    assert progress.guard_render(state,fabricated,'empty-audit') is not None


def test_accept_fourth_real_render_counts_one_usage_and_replay_is_free(tmp_path):
    from hotpost.studio_runtime.lifecycle import LifecycleMixin
    state,_,_=fixture(tmp_path)
    state['approved_voice_id']='voice';state['automation']['active']=False
    state['runs']=[]
    before=copy.deepcopy(state['daily_quality']['render_accounting'])
    job={'id':'fourth','kind':'quality_reedit','payload':{'voice_id':'voice','edit_id':'baseline'}}
    result={'id':'fourth','script_id':'script','voice_id':'voice','preview_path':'durable-render.mp4'}
    worker=LifecycleMixin();worker._accept(state,job,result)
    assert state['daily_quality']['repair_round']==4
    assert state['daily_quality']['render_accounting'][:-1]==before
    assert state['daily_quality']['render_accounting'][-1]['repair_charge']==1
    accepted=copy.deepcopy(state);worker._accept(state,job,copy.deepcopy(result))
    assert state==accepted


def test_no_render_has_no_usage_or_defect_progress(tmp_path):
    from hotpost.studio_runtime.lifecycle import LifecycleMixin
    state,_,_=fixture(tmp_path)
    state['approved_voice_id']='voice';state['automation']['active']=False
    state['runs']=[]
    before=copy.deepcopy(state['daily_quality'])
    job={'id':'held','kind':'quality_reedit','payload':{'voice_id':'voice','edit_id':'baseline'}}
    LifecycleMixin()._accept(state,job,{'no_render':True})
    assert state['daily_quality']['repair_round']==before['repair_round']
    assert state['daily_quality']['render_accounting']==before['render_accounting']
    assert state['daily_quality']['progress_policy']==before['progress_policy']


def test_user_stop_during_plan_preflight_is_not_failed_content_method(tmp_path):
    from types import SimpleNamespace
    from hotpost.studio_runtime.lifecycle import LifecycleMixin
    from hotpost.studio_store import StudioStore
    state,_,_=fixture(tmp_path);bind_replacement(state)
    state['automation']['active']=False
    store=StudioStore(tmp_path/'user-stop-store')
    created,_=store.create('user-stop','제품',prepare=False,initial=state)
    task=created['id']
    store.change(task,lambda s,db:store.enqueue(db,task,'quality_reedit',{},'stop-during-plan'))

    class Once:
        count=0
        def is_set(self):
            self.count+=1
            return self.count>1
        def wait(self,*args):pass

    class Worker(LifecycleMixin):
        def _quality_reedit(self,state,job):
            store.change(task,lambda s,db:s['automation'].update(paused_by_user=True))
            raise progress.QualityProgressHold('사용자 중지 유지')

    worker=Worker();worker.store=store;worker.stop=Once()
    worker.settings=SimpleNamespace(studio_daily_quality_max_repairs=3)
    worker._worker()
    after=store.get(task)
    assert after['automation']['paused_by_user']
    assert after['daily_quality']['repair_round']==3
    assert all(a.get('status')!='failed' for a in after['daily_quality']['progress_policy']['attempts']
               if a.get('job_id'))


@pytest.mark.parametrize('service_wait',[False,True])
def test_fourth_worker_queue_runs_or_waits_without_spending_content_failure(tmp_path,service_wait):
    from types import SimpleNamespace
    from hotpost.model_service import ModelServiceUnavailable
    from hotpost.studio_runtime.lifecycle import LifecycleMixin
    from hotpost.studio_store import StudioStore
    state,_,_=fixture(tmp_path);bind_replacement(state)
    state.update(approved_voice_id='voice',runs=[])
    state['automation']['active']=False
    store=StudioStore(tmp_path/'fourth-worker-store')
    created,_=store.create('fourth-worker','제품',prepare=False,initial=state)
    task=created['id']
    store.change(task,lambda s,db:store.enqueue(db,task,'quality_reedit',
        {'voice_id':'voice','edit_id':'baseline'},'actual-fourth-worker'))
    calls=[]

    class Once:
        count=0
        def is_set(self):self.count+=1;return self.count>1
        def wait(self,*args):pass

    class Worker(LifecycleMixin):
        def _quality_reedit(self,state,job):
            calls.append(job['id'])
            if service_wait:raise ModelServiceUnavailable(attempted=False)
            assert progress.guard_render(state,plan('b'),job['id']) is None
            return {'id':job['id'],'script_id':'script','voice_id':'voice','preview_path':'worker-render.mp4'}

    worker=Worker();worker.store=store;worker.stop=Once()
    worker.settings=SimpleNamespace(studio_daily_quality_max_repairs=3)
    worker._worker()
    after=store.get(task);jobs=store.jobs(task)
    assert len(calls)==1
    assert after['daily_quality']['repair_round']==(3 if service_wait else 4)
    assert jobs[0]['status']==('queued' if service_wait else 'done')
    assert all(a.get('status')!='failed' for a in after['daily_quality']['progress_policy']['attempts'] if a.get('job_id'))
    if service_wait:
        assert len(after['daily_quality']['render_accounting'])==1
        assert after['status']=='retry_wait'


def test_repeated_queue_reservation_retains_one_original_job_and_attempt(tmp_path):
    from test_render_contract_queue_independent import fixture as queue_fixture,schedule
    worker,task=queue_fixture(tmp_path,counter=3)
    first=schedule(worker,task)
    identity=worker.store.jobs(task)[0]['id']
    method=first['daily_quality']['progress_policy']['attempts'][0]['key']
    for _ in range(3):
        current=schedule(worker,task)
        assert current['daily_quality']['pending']=='reediting'
        assert current['daily_quality']['repair_round']==3
        assert len(worker.store.jobs(task))==1
        assert current['daily_quality']['progress_policy']['attempts'][0]['key']==method
    claimed=worker.store.claim(task_id=task)
    assert claimed['id']==identity
    worker.store.recover();schedule(worker,task)
    assert worker.store.claim(task_id=task)['id']==identity


def test_store_duplicate_review_and_source_completion_preserve_progress_and_history(tmp_path):
    from hotpost.daily_quality import DailyQualityMixin
    from hotpost.studio_runtime.lifecycle import LifecycleMixin
    from hotpost.studio_store import StudioStore
    from test_cover_scope_recovery import Acceptance,recollection_state,refresh_result
    state,_,_=fixture(tmp_path)
    review=store_plan(tmp_path,state,plan('b'),'new-reviewed')
    review.update(passed=True,issues=[],review_path='new-review.json')
    preview=tmp_path/'new-preview.mp4';preview.write_bytes(b'actual duplicate-review fixture media')
    state['edits'][-1]['preview_path']=str(preview)
    review['render_sha256']=hashlib.sha256(preview.read_bytes()).hexdigest()
    review['plan_sha256']=hashlib.sha256(Path(state['edits'][-1]['plan_path']).read_bytes()).hexdigest()
    state['automation']['active']=False
    store=StudioStore(tmp_path/'duplicate-review-store')
    created,_=store.create('review-duplicate','제품',prepare=False,initial=state)
    task=created['id']
    store.change(task,lambda s,db:store.enqueue(db,task,'quality_review',{'edit_id':review['edit_id']},'review-once'))
    job=store.claim(task_id=task)

    class Reviewer(DailyQualityMixin,LifecycleMixin):
        def advance_workflow(self,*args):pass

    reviewer=Reviewer()
    store.finish(job,review,lambda s,db,r:reviewer._accept(s,job,r,db))
    before=store.get(task)
    restarted=StudioStore(tmp_path/'duplicate-review-store');restarted.recover()
    restarted.finish(job,copy.deepcopy(review),lambda s,db,r:reviewer._accept(s,job,r,db))
    after=restarted.get(task)
    assert after['daily_quality']==before['daily_quality']
    assert after['edits']==before['edits'] and after['runs']==before['runs']

    source_state=recollection_state(tmp_path)
    source_store=StudioStore(tmp_path/'duplicate-source-store')
    made,_=source_store.create('source-duplicate','제품',prepare=False,initial=source_state)
    source_task=made['id']
    source_store.change(source_task,lambda s,db:source_store.enqueue(db,source_task,'refresh_sources',
        {'daily_quality_repair':True},'source-once'))
    source_job=source_store.claim(task_id=source_task);acceptor=Acceptance(tmp_path)
    result=refresh_result([])
    source_store.finish(source_job,result,lambda s,db,r:acceptor._accept(s,source_job,r,db))
    source_before=source_store.get(source_task)
    source_store.recover()
    source_store.finish(source_job,copy.deepcopy(result),lambda s,db,r:acceptor._accept(s,source_job,r,db))
    source_after=source_store.get(source_task)
    assert source_after['daily_quality']==source_before['daily_quality']
    assert source_after['source_acquisition']==source_before['source_acquisition']


def test_actual_dense_disagreement_confirmation_reuses_model_receipt(tmp_path):
    import subprocess
    from types import SimpleNamespace
    from hotpost.daily_quality import DailyQualityMixin
    state,document,_=fixture(tmp_path)
    video=tmp_path/'dense-evidence.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=108x192:rate=30',
                    '-t','2','-pix_fmt','yuv420p',str(video)],check=True,capture_output=True)
    result=store_plan(tmp_path,state,document,'disagreement')
    result.update(passed=True,issues=[],render_sha256=hashlib.sha256(video.read_bytes()).hexdigest())
    root=tmp_path/'confirmation';root.mkdir()
    reviewer=DailyQualityMixin();reviewer.settings=SimpleNamespace()
    prompts=[]
    def generate(settings,instruction,evidence,media=None):
        prompts.append(evidence)
        assert evidence['purpose']=='quality_disagreement_dense_confirmation'
        assert len([entry for entry in media if 'inlineData' in entry])==5
        return {'passed':True,'issues':[]}
    confirmed=reviewer._confirm_quality_disagreement(state,document,video,root,result,generate)
    assert confirmed['evidence_recheck'] and confirmed['passed']
    frames=confirmed['recheck_evidence']['frames']
    assert len(frames)==5 and len({f['timestamp'] for f in frames})==5
    for frame in frames:
        assert hashlib.sha256(__import__('pathlib').Path(frame['path']).read_bytes()).hexdigest()==frame['sha256']
    again=reviewer._confirm_quality_disagreement(state,document,video,root,result,generate)
    assert again['passed'] and len(prompts)==1
    assert again['recheck_key']==confirmed['recheck_key']


def test_explicit_exhausted_resume_requires_new_actual_method_and_preserves_history(tmp_path):
    state,document,_=fixture(tmp_path)
    state['daily_quality'].update(pending='exhausted',status='needs_attention')
    state['automation'].update(active=False,paused_by_user=True)
    state['daily_quality']['feedback']=[{'kind':'cover','reason':'표지에서 답을 미리 공개함'}]
    # Same selected cover cannot justify reopening a historical stopped task.
    state['daily_quality']['thumbnail_lines']=document['cover_spec']['lines']
    before=copy.deepcopy(state['daily_quality']['render_accounting'])
    assert not progress.resume_assessment(state)
    assert state['daily_quality']['pending']=='exhausted'
    assert state['automation']['paused_by_user'] and not state['automation']['active']
    state['daily_quality']['thumbnail_lines']=['제품의 새로운 질문','어떤 촉감일까요?']
    assert progress.resume_assessment(state)
    assert state['daily_quality']['pending']=='reedit'
    assert state['daily_quality']['stop_history'][-1]['pending']=='exhausted'
    assert state['daily_quality']['repair_round']==3
    assert state['daily_quality']['render_accounting']==before
    assert state['automation']['paused_by_user'] and not state['automation']['active']


def test_quality_review_reuses_same_actual_evidence_after_review_code_change(daily_ready,monkeypatch):
    from pathlib import Path
    from hotpost import daily_quality
    studio,task=daily_ready
    state=studio.store.get(task);script=state['scripts'][0];voice=state['voices'][0];edit=state['edits'][0]
    voice['spoken_text']=script['text']
    document=json.loads(Path(edit['plan_path']).read_text('utf-8'))
    document['voice']=copy.deepcopy(voice)
    document['cover_spec']={'lines':['제품의 질문','어떤 촉감일까요?'],'font':{'font_family':'Do Hyeon'}}
    Path(edit['plan_path']).write_text(json.dumps(document,ensure_ascii=False),encoding='utf-8')
    draft_root=studio.folder(task)/'portable';draft_root.mkdir()
    draft={'tracks':[{'name':'cover-line-'+str(i),'segments':[{'material_id':'cover-'+str(i),
              'target_timerange':{'start':0,'duration':33333}}]} for i in (1,2)],
        'materials':{'texts':[{'id':'cover-'+str(i),'shadow_smoothing':2.4} for i in (1,2)]}}
    (draft_root/'draft_content.json').write_text(json.dumps(draft),encoding='utf-8')
    edit['portable_draft_path']=str(draft_root)
    prior={'edit_id':edit['id'],'passed':False,'issues':[{'kind':'cover','reason':'표지가 답을 공개함'}],
        'render_sha256':hashlib.sha256(Path(edit['preview_path']).read_bytes()).hexdigest(),
        'plan_sha256':hashlib.sha256(Path(edit['plan_path']).read_bytes()).hexdigest(),
        'review_contract_sha256':'older-review-contract','review_path':'older-review.json'}
    state['daily_quality']['reviews']=[prior]
    monkeypatch.setattr(daily_quality,'REVIEW_INSTRUCTION',daily_quality.REVIEW_INSTRUCTION+' A code contract revision.')
    monkeypatch.setattr('hotpost.script_rewriter._generate',lambda *a,**k:pytest.fail('Same actual evidence must not be re-questioned'))
    output=studio._quality_review(state,{'id':'new-review-id','payload':{'edit_id':edit['id']}})
    assert output['reused_evidence_review'] and not output['passed']
    assert output['issues']==prior['issues']
    assert output['render_sha256']==prior['render_sha256']


def test_user_pause_stops_automatic_quality_collection_and_retains_manual_source_request(tmp_path):
    from hotpost.studio_store import StudioStore
    state,_,_=fixture(tmp_path)
    state['automation'].update(protocol=2,active=False,paused_by_user=True)
    store=StudioStore(tmp_path/'paused-source-store')
    made,_=store.create('paused-sources','제품',prepare=False,initial=state)
    task=made['id']
    def enqueue(s,db):
        store.enqueue(db,task,'refresh_sources',{'daily_quality_repair':True},'auto-quality-sources')
        store.enqueue(db,task,'refresh_sources',{'request':'명시적인 추가 검색'},'manual-sources')
    store.change(task,enqueue)
    manual=store.claim('sources',task_id=task)
    assert manual and not manual['payload'].get('daily_quality_repair')
    automatic=next(j for j in store.jobs(task) if j['id']!=manual['id'])
    assert automatic['status']=='paused'
    before=store.get(task)
    store.recover()
    after=store.get(task)
    assert after['daily_quality']==before['daily_quality']
    assert after['automation']['paused_by_user'] and not after['automation']['active']


def test_late_old_render_completion_cannot_select_old_output_or_reset_terminal_method(tmp_path):
    from hotpost.studio_runtime.lifecycle import LifecycleMixin
    state,_,_=fixture(tmp_path)
    state.update(approved_voice_id='voice',status='completed')
    state['automation']['active']=False
    state['edits'].append({'id':'current-completed','script_id':'script','voice_id':'voice',
                           'preview_path':'current.mp4','quality_verified':True,'export_verified':True})
    state['edit_id']='current-completed'
    progress.ensure(state)['attempts'].append({'key':'historical-method','stage':'render','job_id':'old-job',
        'edit_id':'baseline','status':'failed','defects':[]})
    before=copy.deepcopy(state)
    job={'id':'old-job','kind':'quality_reedit','payload':{'voice_id':'voice','edit_id':'baseline'}}
    LifecycleMixin()._accept(state,job,copy.deepcopy(state['edits'][0]))
    assert state==before
    progress.finish_attempt(state,job,{'id':'baseline'})
    assert state['daily_quality']['progress_policy']['attempts'][-1]['status']=='failed'
