import copy
import hashlib
import json
from pathlib import Path

import pytest
from hotpost.config import Settings
from hotpost.daily_quality import POLICY, validate_report, repetition_metrics, QualitySceneGap
from hotpost.studio import Studio
from hotpost.studio_workflow import snapshot

@pytest.fixture
def ready(tmp_path):
    settings=Settings(data_dir=tmp_path,source_min_usable=1)
    studio=Studio(settings,workers=False)
    # Existing quality/cache/recovery tests exercise a saved pre-minimum-five
    # run. Freeze its legacy v4 contract at creation, not the new v5 default.
    legacy_policy={'version':4,'minimum_total':1,'platform_minimums':{},
        'editorial_policy':'normal-speed-editorial-v1','allow_source_reuse':True,
        'duration_requirement':'preference','core_duration_requirement':'preference'}
    state,_=studio.store.create('quality-fixture','테스트 제품',
        automation={'active':True,'protocol':2,'selection_mode':'manual','stage':'edit'},prepare=False,
        initial={'source_policy':copy.deepcopy(legacy_policy),
            'daily_quality':{'policy':POLICY,'max_repairs':3,'repair_round':0,'status':'pending','reviews':[]}})
    root=studio.folder(state['id']);voice=root/'voice.wav';voice.write_bytes(b'voice')
    video=root/'preview.mp4';video.write_bytes(b'old result')
    plan=root/'plan.json';plan.write_text('{}')
    src=root/'source.mp4';src.write_bytes(b'source');sha=hashlib.sha256(b'source').hexdigest()
    def init(s,db):
        s.update(original_text='원본 제품 설명',source_policy=copy.deepcopy(legacy_policy),
            sources=[{'id':'source','path':str(src),'sha256':sha,'source_quality':'clean-source','editing_eligible':True,
                'functional_review':{'reviewed':True,'same_core_function':True,'source_sha256':sha,
                    'observed_actions':['제품 실제 동작'],'evidence_frames':['frame.jpg']}}])
        studio._script(s,'새 제품 후킹 대본','automatic_codex')
        s['approved_script_id']=s['script_id']
        plan.write_text(json.dumps({'script_text':'새 제품 후킹 대본',
            'beats':[{'id':'b1','text':'새 제품 후킹 대본'}]}),encoding='utf-8')
        v={'id':'voice','script_id':s['script_id'],'path':str(voice),'sha256':hashlib.sha256(b'voice').hexdigest()}
        e={'id':'old-edit','script_id':s['script_id'],'voice_id':'voice','preview_path':str(video),'plan_path':str(plan)}
        s.update(voices=[v],voice_id='voice',approved_voice_id='voice',edits=[e],edit_id='old-edit')
        snapshot(s);studio.advance_workflow(s,db)
    studio.store.change(state['id'],init)
    return studio,state['id']

def finish(studio,task,value):
    job=studio.store.claim(task_id=task);assert job
    if job['kind']=='quality_review':
        state=studio.store.get(task)
        edit=next(e for e in state['edits'] if e['id']==value['edit_id'])
        value.setdefault('render_sha256',hashlib.sha256(Path(edit.get('export_path') or edit['preview_path']).read_bytes()).hexdigest())
        value.setdefault('plan_sha256',hashlib.sha256(Path(edit['plan_path']).read_bytes()).hexdigest())
    studio.store.finish(job,value,lambda s,db,r:studio._accept(s,job,r,db))
    return job

def passed(edit):return {'edit_id':edit,'passed':True,'issues':[],'review_path':'review.json','policy':POLICY}
def issue(edit,kind='scene_gap'):
    return {'edit_id':edit,'passed':False,'issues':[{'kind':kind,'beat_id':'b1','reason':'실제 접는 동작이 아닌 펼치는 장면','search_query':'카트 다리 접기'}],'policy':POLICY}

def test_completed_render_waits_for_actual_review_before_completion(ready):
    studio,task=ready;s=studio.store.get(task)
    assert s['status']=='quality_review' and s['automation']['stage']=='quality_review'
    assert finish(studio,task,passed('old-edit'))['kind']=='quality_review'
    s=studio.store.get(task)
    assert s['status']=='completed' and s['edits'][0]['quality_verified']
    assert s['edits'][0]['export_path'].endswith('preview.mp4')


@pytest.mark.parametrize('paused',[False,True])
def test_internal_quality_failure_preserves_owner_authority_and_user_pause(ready,paused):
    studio,task=ready
    job=studio.store.claim(task_id=task)
    before=studio.store.get(task)
    if paused:
        studio.store.change(task,lambda s,db:s['automation'].update(active=False,paused_by_user=True))
    studio.store.fail(job,ValueError('internal placement computation failed'))
    studio.fail_daily_quality(job,ValueError('internal placement computation failed'))
    current=studio.store.get(task)
    assert current['automation']['active'] is (not paused)
    assert current['daily_quality']['pending']=='failed'
    assert current['daily_quality']['failed_job_id']==job['id']
    assert current['edits']==before['edits'] and current['voices']==before['voices']
    from hotpost.video_agent_actions import capabilities
    available=capabilities(studio,current)
    assert ('retry_repaired' in available) is (not paused)


@pytest.mark.parametrize('paused',[False,True])
def test_explicit_quality_retry_resumes_failure_but_preserves_user_pause(ready,paused):
    studio,task=ready
    job=studio.store.claim(task_id=task)
    studio.store.fail(job,ValueError('technical cover guard'))
    def stopped(s,db):
        s.update(status='attention',error='technical cover guard')
        s['automation'].update(active=False,paused_by_user=paused)
        s['daily_quality'].update(status='needs_attention',pending='failed')
    studio.store.change(task,stopped)
    studio.action(task,'retry',{'job_id':job['id']})
    current=studio.store.get(task)
    assert current['status']=='quality_review' and not current['error']
    assert current['automation']['active'] is (not paused)
    assert current['daily_quality']['pending']=='quality_review'
    if paused:
        assert studio.store.claim(task_id=task) is None
    else:
        finish(studio,task,passed('old-edit'))
        assert studio.store.get(task)['status']=='completed'


@pytest.mark.parametrize('paused',[False,True])
def test_narration_hold_keeps_owner_diagnosis_alive_without_releasing_evidence_hold(ready,paused):
    from hotpost.scene_narration_prepare import NarrationContextHold
    from hotpost.video_agent_actions import capabilities
    studio,task=ready;job=studio.store.claim(task_id=task)
    if paused:studio.store.change(task,lambda s,db:s['automation'].update(active=False,paused_by_user=True))
    studio.handle_narration_context_hold(job,NarrationContextHold([{'reason':'Actual mapping unresolved'}]))
    state=studio.store.get(task)
    assert state['automation']['active'] is (not paused)
    assert state['daily_quality']['narration_context_hold']['job_id']==job['id']
    assert state['daily_quality']['pending']=='scene_wait'
    assert not capabilities(studio,state)


def test_old_quality_retry_cannot_overwrite_a_new_video_version(ready):
    from hotpost.studio_store import Conflict
    studio,task=ready
    job=studio.store.claim(task_id=task);studio.store.fail(job,ValueError('old failure'))
    studio.store.change(task,lambda s,db:s.update(edit_id='new-edit',approved_voice_id='new-voice',status='editing'))
    before=studio.store.get(task)
    with pytest.raises(Conflict,match='이전 영상·음성'):
        studio.action(task,'retry',{'job_id':job['id']})
    assert studio.store.get(task)==before
    assert next(j for j in studio.store.jobs(task) if j['id']==job['id'])['status']=='failed'


@pytest.mark.parametrize('kind',['scene_gap','cover'])
def test_old_cover_preparation_cannot_replace_a_new_body_repair(kind):
    from types import SimpleNamespace
    from hotpost.daily_quality import DailyQualityMixin
    from hotpost.quality_progress import QualityProgressHold
    state={'id':'task','script_id':'script','voice_id':'voice','sources':[], 'edits':[],
        'daily_quality':{'feedback':[{'kind':kind}],
            'cover_repair_evidence':{'prepared_plan':{'scope':'old-voice','path':'old-plan'}}}}
    old=copy.deepcopy(state)
    calls=[]
    def fresh(current,job):calls.append(current['voice_id']);return {'id':job['id']}
    facade=SimpleNamespace(_edit=fresh)
    job={'id':'repair','payload':{'edit_id':'current-body'}}
    if kind=='cover':
        with pytest.raises(QualityProgressHold):DailyQualityMixin._quality_reedit(facade,state,job)
        assert not calls
    else:
        result=DailyQualityMixin._quality_reedit(facade,state,job)
        assert calls==['voice'] and result['parent_id']=='current-body'
    assert state==old

def test_recollect_reedit_recheck_survives_restart_and_preserves_old_edit(ready):
    studio,task=ready;old=copy.deepcopy(studio.store.get(task)['edits'])
    finish(studio,task,issue('old-edit'))
    studio=Studio(studio.settings,workers=False);studio.store.recover()
    source=copy.deepcopy(studio.store.get(task)['sources'][0])
    new_file=studio.folder(task)/'new-source.mp4';new_file.write_bytes(b'new fixture source')
    digest=hashlib.sha256(new_file.read_bytes()).hexdigest()
    source.update(id='new',path=str(new_file),sha256=digest,
                  reviewed_intervals=[{'source_start':1,'source_end':3}])
    source['functional_review']['source_sha256']=digest
    from PIL import Image
    frames=[]
    for fid,stamp,color in [('first',1,(10,20,30)),('last',3,(30,20,10))]:
        frame=studio.folder(task)/(fid+'-replacement.jpg')
        Image.new('RGB',(32,32),color).save(frame)
        frames.append({'frame_id':fid,'source_timestamp':stamp,'path':str(frame),
                       'sha256':hashlib.sha256(frame.read_bytes()).hexdigest()})
    source['functional_review']['evidence_frames']=[f['path'] for f in frames]
    source['mask_review']={'source_sha256':digest,'reviewer':'independent-fixture',
        'proposal_sha256':hashlib.sha256(b'fixture-proposal').hexdigest(),'evidence_frames':frames}
    from hotpost.source_frame_timing import timing_from_probe
    source['mask_review']['native_frame_timing']=timing_from_probe({'streams':[{'duration':4}],
        'frames':[{'best_effort_timestamp_time':t,'pkt_duration_time':.04} for t in (1,1.04,3,3.04)]},digest)
    from hotpost.scene_requirements import input_signature, requirements_key, POLICY as SCENE_POLICY
    current=studio.store.get(task)
    candidate_state={**current,'sources':[*current['sources'],source]}
    signature=input_signature(candidate_state)
    from hotpost.scene_requirement_context import build_scene_requirement_context
    context=build_scene_requirement_context(candidate_state,current['daily_quality']['feedback'])
    assert context['verified'],context['holds']
    requirements=[{**r,'covered':True,'source_ids':['new'],'matches':[{'source_id':'new',
        'source_sha256':digest,'source_start':1,'source_end':3,'evidence_frame_ids':['first','last'],
        'proof_mode':'direct_state',
        'supporting_frame_ids':['first'],'supporting_reason':'Actual required action is visible'}],
        'coverage_reason':'Fixture replacement demonstrates the required action'}
        for r in current['daily_quality']['feedback']]
    job=finish(studio,task,{'sources':[source],'source_search_manifest_path':'manifest.json','searches':[],
        'scene_requirements':{'ready':True,'signature':signature,'policy':SCENE_POLICY,
            'context_signature':context['signature'],'narration_context':context,
            'requirements_key':requirements_key(current),'requirements':requirements}})
    assert job['kind']=='refresh_sources' and job['payload']['daily_quality_repair']
    s=studio.store.get(task);assert s['daily_quality']['pending']=='reediting'
    edit=copy.deepcopy(old[0]);edit['id']='new-edit'
    new_plan=studio.folder(task)/'new-plan.json'
    new_plan.write_text(json.dumps({'script_text':'새 제품 후킹 대본','sources':[source],
        'shots':[{'id':'new-shot','source_id':'new'}],
        'beats':[{'id':'b1','text':'새 제품 후킹 대본','selected_shot_id':'new-shot',
                  'source_start':1,'source_end':3}]}),encoding='utf-8')
    edit['plan_path']=str(new_plan)
    assert finish(studio,task,edit)['kind']=='quality_reedit'
    assert studio.store.get(task)['status']=='quality_review'
    finish(studio,task,passed('new-edit'))
    s=studio.store.get(task)
    assert s['status']=='completed' and s['edits'][0]==old[0] and len(s['edits'])==2
    assert len([j for j in studio.store.jobs(task) if j['kind']=='refresh_sources'])==1

def test_usage_three_does_not_complete_or_stop_a_new_grounded_search(ready):
    studio,task=ready
    studio.store.change(task,lambda s,db:s['daily_quality'].update(repair_round=3))
    finish(studio,task,issue('old-edit'))
    s=studio.store.get(task)
    assert s['status']=='source_wait' and s['automation']['active']
    assert s['daily_quality']['repair_round']==3 and len(s['edits'])==1
    assert [j['kind'] for j in studio.store.jobs(task) if j['status']=='queued']==['refresh_sources']
    assert not s['edits'][0].get('quality_verified')

def test_cover_only_repairs_without_external_recollection(ready):
    studio,task=ready;r=issue('old-edit','cover');r['thumbnail_lines']=['제품의 반전','두 줄 후킹']
    finish(studio,task,r)
    s=studio.store.get(task)
    assert s['daily_quality']['thumbnail_lines']==r['thumbnail_lines']
    assert [j['kind'] for j in studio.store.jobs(task) if j['status']=='queued']==['quality_reedit']


def test_new_approved_source_does_not_reuse_paused_reedit_queue_key(ready):
    studio,task=ready
    report=issue('old-edit','cover');report['thumbnail_lines']=['제품을 다시 보는 이유','무엇이 숨었을까요?']
    finish(studio,task,report)
    old=next(j for j in studio.store.jobs(task) if j['status']=='queued')
    def recovered(s,db):
        db.execute("update jobs set status='paused' where id=?",(old['id'],))
        source=copy.deepcopy(s['sources'][0]);source['id']='new-action'
        source['sha256']=hashlib.sha256(b'new actual action').hexdigest()
        source['functional_review']['source_sha256']=source['sha256']
        s['sources'].append(source);s['daily_quality']['pending']='reedit'
        s['daily_quality']['thumbnail_lines']=['새 사용 장면의 궁금증','왜 이 모양일까요?']
        script=next(x for x in s['scripts'] if x['id']==s['script_id'])
        studio.advance_daily_quality(s,db,script,s['voices'][0],s['edits'][0])
    studio.store.change(task,recovered)
    queued=[j for j in studio.store.jobs(task) if j['status']=='queued']
    assert len(queued)==1 and queued[0]['id']!=old['id']
    assert queued[0]['kind']=='quality_reedit'

def test_pre_render_cover_proposal_preserves_actual_output_and_waits_for_evidence(ready):
    studio,task=ready;before=studio.store.get(task);job=studio.store.claim(task_id=task)
    lines=['제품에 남는 질문','두 번째 문구']
    studio.handle_daily_scene_gap(job,QualitySceneGap(issue('old-edit','cover')['issues'],thumbnail_lines=lines))
    after=studio.store.get(task)
    assert after['script_id']==before['script_id'] and after['voice_id']==before['voice_id']
    assert after['edits']==before['edits'] and after['voices']==before['voices']
    assert after['daily_quality'].get('thumbnail_lines')==before['daily_quality'].get('thumbnail_lines')
    assert after['daily_quality']['reviews']==before['daily_quality']['reviews']
    assert after['daily_quality']['repair_round']==before['daily_quality']['repair_round']
    assert after['daily_quality'].get('render_accounting')==before['daily_quality'].get('render_accounting')
    assert after['daily_quality']['preparation_failures'][0]['thumbnail_proposal']==lines
    assert after['daily_quality']['pending']=='scene_wait'
    assert studio.store.claim(task_id=task) is None

@pytest.mark.parametrize('usable',[True,False])
def test_targeted_local_source_review_only_releases_reedit_when_coverage_is_ready(ready,usable):
    studio,task=ready;before=studio.store.get(task)
    source=copy.deepcopy(before['sources'][0]);source['editing_eligible']=usable
    source['video_meta']={'duration':45,'width':1080,'height':1920}
    def accept(state,db):
        state['automation']['active']=False
        state['daily_quality']['pending']='recollecting'
        studio.accept_source_round(state,{'id':'local-review','payload':{'daily_quality_repair':True}},
            {'round':0,'sources':[source],'source_search_manifest_path':'local-received-manifest.json',
             'visual_review_only':True,'searches':[]},db)
    studio.store.change(task,accept)
    assert studio.store.get(task)['daily_quality']['pending']==('reedit' if usable else 'recollecting')


def test_inflight_source_result_cannot_undo_a_later_manual_denial(ready):
    studio,task=ready;source=copy.deepcopy(studio.store.get(task)['sources'][0])
    source.update(editing_eligible=True,video_meta={'duration':45,'width':1080,'height':1920})
    def accept(state,db):
        state['automation']['active']=False
        state['sources'][0]['manual_usage_review']={'editing_eligible':False,'reason':'Mixed unrelated footage seen after review started.'}
        studio.accept_source_round(state,{'id':'local-review','payload':{}},
            {'round':0,'sources':[source],'source_search_manifest_path':'local.json','visual_review_only':True,'searches':[]},db)
    studio.store.change(task,accept)
    current=studio.store.get(task)['sources'][0]
    assert current['manual_usage_review']['editing_eligible'] is False
    assert current['editing_eligible'] is False


def test_replay_metric_uses_actual_original_time_after_slow_motion():
    slow={'id':'slow','sha256':'slow','original_sha256':'parent','original_interval':{'start':10,'end':12},
        'video_meta':{'duration':4},'retiming':{'method':'ffmpeg-setpts','playback_rate':.5,
            'source_sha256':'slow','original_sha256':'parent','full_decode_passed':True}}
    plan={'duration':3,'sources':[slow,{'id':'normal','sha256':'parent'}],
        'shots':[{'id':'a','source_id':'slow'},{'id':'b','source_id':'normal'}],
        'beats':[{'selected_shot_id':'a','source_start':0,'source_end':2,'start':0,'end':2},
                 {'selected_shot_id':'b','source_start':10.5,'source_end':11.5,'start':2,'end':3}]}
    assert repetition_metrics(plan)['same_source_time_replay_seconds']==.5

def test_script_fact_triggers_fresh_three_proposal_job_not_old_ranking(ready):
    studio,task=ready
    finish(studio,task,issue('old-edit','script_fact'))
    job=studio.store.claim(task_id=task)
    assert job['kind']=='rewrite' and job['payload']['quality_rewrite'] and job['payload']['generation_key']
    assert '실제 접는' in studio.store.get(task)['rewrite_instructions']

def test_quality_rewrite_produces_a_fresh_voice_even_when_old_run_job_is_done(ready):
    studio,task=ready
    before=studio.store.get(task);old_run=before['run_id']
    with studio.store.transaction() as db:
        voice_job=studio.store.enqueue(db,task,'voice',{'script_id':before['script_id']},'voice:'+old_run)
        db.execute("update jobs set status='done' where id=?",(voice_job,))
    finish(studio,task,issue('old-edit','script_fact'))
    rewrite=studio.store.claim(task_id=task)
    studio.store.finish(rewrite,{'text':'새 제품 대본입니다.'},lambda s,db,r:studio._accept(s,rewrite,r,db))
    state=studio.store.get(task)
    new_run=next(r for r in state['runs'] if r['id']==state['run_id'])
    old=next(r for r in state['runs'] if r['id']==old_run)
    assert new_run['id']!=old_run and new_run['parent_id']==old_run
    assert old['status']=='superseded' and old['artifacts']['script_id']==before['script_id']
    queued=next(j for j in studio.store.jobs(task) if j['kind']=='voice' and j['status']=='queued')
    with studio.store.connect() as db:
        payload=json.loads(db.execute('select payload from jobs where id=?',(queued['id'],)).fetchone()[0])
    assert payload['script_id']==state['script_id']
    assert queued['id']!=voice_job
    assert state['voices'][0]['id']=='voice' and state['edits'][0]['id']=='old-edit'

@pytest.mark.parametrize('kind',['script_clarity','voice_consistency'])
def test_new_feedback_narration_issues_generate_fresh_variants(ready,kind):
    studio,task=ready
    finish(studio,task,issue('old-edit',kind))
    queued=studio.store.claim(task_id=task)
    assert queued['kind']=='rewrite' and queued['payload']['quality_rewrite']

def test_caption_clock_only_does_not_recollect(ready):
    studio,task=ready
    finish(studio,task,issue('old-edit','caption_sync'))
    assert studio.store.claim(task_id=task)['kind']=='quality_reedit'

def test_watermark_finding_requests_alternative_sources(ready):
    studio,task=ready
    finish(studio,task,issue('old-edit','watermark'))
    assert studio.store.claim(task_id=task)['kind']=='refresh_sources'

def test_old_edit_is_not_reviewed_for_new_narration(ready):
    studio,task=ready
    with studio.store.transaction() as db:
        s=studio.store.get(task,db);studio._script(s,'다른 새 대본','automatic_codex')
        assert studio.advance_daily_quality(s,db,s['scripts'][-1],s['voices'][0],s['edits'][0]) is False

def test_pre_render_selection_failure_preserves_real_repetition_and_waits(ready):
    studio,task=ready
    finish(studio,task,issue('old-edit','repetition'))
    before=studio.store.get(task);job=studio.store.claim(task_id=task)
    studio.handle_daily_scene_gap(job,QualitySceneGap(issue('old-edit')['issues']))
    after=studio.store.get(task);q=after['daily_quality'];old=before['daily_quality']
    for key in ('reviews','feedback','repair_round'):
        assert q[key]==old[key]
    for key in ('defects','reviews','best'):
        assert q['progress_policy'][key]==old['progress_policy'][key]
    assert q.get('render_accounting')==old.get('render_accounting')
    assert after['edits']==before['edits'] and after['voices']==before['voices']
    assert q['preparation_failures'][0]['failure_reason']==issue('old-edit')['issues']
    assert q['pending']=='scene_wait' and studio.store.claim(task_id=task) is None

@pytest.mark.parametrize('response',[
    {'passed':False,'issues':[]}, {'passed':True,'issues':[{'kind':'scene_gap','beat_id':'unknown','reason':'wrong'}]},
    {'passed':'yes','issues':[]}, {'passed':True,'issues':[],'thumbnail_lines':['one']}])
def test_invalid_or_unbound_review_cannot_pass(response):
    with pytest.raises(ValueError):validate_report(response,{'b1'})

def test_same_original_different_derivatives_do_not_hide_replay():
    p={'duration':4,'sources':[{'id':'a','sha256':'one','original_sha256':'parent','original_interval':{'start':10}},
        {'id':'b','sha256':'two','original_sha256':'parent','original_interval':{'start':11}}],
       'shots':[{'id':'s1','source_id':'a'},{'id':'s2','source_id':'b'}],
       'beats':[{'selected_shot_id':'s1','source_start':0,'source_end':2,'start':0,'end':2},
                {'selected_shot_id':'s2','source_start':0,'source_end':2,'start':2,'end':4}]}
    r=repetition_metrics(p)
    assert r['same_source_time_replay_seconds']==1 and r['parent_files']==1
    assert not r['visual_repeat_detection_complete']

def test_activation_date_does_not_backfill_today(monkeypatch,tmp_path):
    from hotpost.studio_automation import enqueue_top
    from hotpost.daily_hot import date_key
    import time
    s=Settings(data_dir=tmp_path,studio_auto_top_enabled=True,studio_auto_start_date_kst='2099-01-01')
    assert enqueue_top(s,{'posts':[]},'today')==[]

@pytest.fixture
def narration_receipts(tmp_path):
    original=tmp_path/'synthesis.wav';original.write_bytes(b'original synthesis')
    processed=tmp_path/'trimmed.wav';processed.write_bytes(b'trimmed pauses')
    voice={'id':'v1','script_id':'s1','spoken_text':'제품 설명. 댓글에 나도 남겨주세요.',
           'path':str(original),'sha256':hashlib.sha256(original.read_bytes()).hexdigest()}
    state={'scripts':[{'id':'s1','text':voice['spoken_text']}],'voices':[voice]}
    edit={'script_id':'s1','voice_id':'v1'}
    plan={'script_text':voice['spoken_text'],'voice_source':copy.deepcopy(voice),
          'voice':{**voice,'path':str(processed),'sha256':hashlib.sha256(processed.read_bytes()).hexdigest()}}
    return state,edit,plan

def test_older_whole_script_synthesis_can_be_checked_after_pause_trimming(narration_receipts):
    from hotpost.daily_quality import verify_narration_version
    verify_narration_version(*narration_receipts)

@pytest.mark.parametrize('change',['script','spoken_text','voice_id','original_file','declared_hash'])
def test_narration_check_rejects_stale_or_replaced_receipts(narration_receipts,change):
    from hotpost.daily_quality import verify_narration_version
    state,edit,plan=narration_receipts
    if change=='script':plan['script_text']='다른 대본'
    elif change=='spoken_text':state['voices'][0]['spoken_text']='다른 음성 대본'
    elif change=='voice_id':plan['voice_source']['id']='other'
    elif change=='original_file':Path(state['voices'][0]['path']).write_bytes(b'replaced')
    elif change=='declared_hash':plan['voice']['script_sha256']='wrong'
    with pytest.raises(ValueError,match='버전'):
        verify_narration_version(state,edit,plan)


@pytest.mark.parametrize('fault', [None, 'missing_run', 'other_voice', 'other_script',
                                  'wrong_input', 'wrong_mapping', 'malformed', 'duplicate', 'source_text'])
def test_saved_pronunciation_mapping_is_bound_to_synthesis_run(narration_receipts, fault):
    from hotpost.daily_quality import verify_narration_version
    state, edit, plan = narration_receipts
    original = state['scripts'][0]['text'].replace('나도', '‘나도’')
    state['scripts'][0]['text'] = plan['script_text'] = original
    state['voices'][0]['script_sha256'] = hashlib.sha256(original.encode()).hexdigest()
    run = {'id':'saved', 'inputs':{'script_text':original,
            'pronunciations':[{'from':'‘나도’','to':'나도'}]},
           'artifacts':{'script_id':'s1','voice_id':'v1'}}
    state['runs'] = [run]
    state['run_id'] = 'unrelated-current-run'
    if fault == 'missing_run': state['runs'] = []
    elif fault == 'other_voice': run['artifacts']['voice_id'] = 'other'
    elif fault == 'other_script': run['artifacts']['script_id'] = 'other'
    elif fault == 'wrong_input': run['inputs']['script_text'] = 'changed'
    elif fault == 'wrong_mapping': run['inputs']['pronunciations'][0]['to'] = '다른말'
    elif fault == 'malformed': run['inputs']['pronunciations'] = [{'from':'','to':'나도'}]
    elif fault == 'duplicate': state['runs'].append(copy.deepcopy(run))
    elif fault == 'source_text': plan['voice_source']['spoken_text'] = original
    if fault is None:
        verify_narration_version(state, edit, plan)
    else:
        with pytest.raises(ValueError, match='버전'):
            verify_narration_version(state, edit, plan)
