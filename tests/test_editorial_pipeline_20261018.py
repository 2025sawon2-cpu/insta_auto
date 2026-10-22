"""Actual continuation integration with isolated files and model/process ports.

The real process-result decoder, extension_scope/review_extension, SHA checks,
withdrawal lookup, pause checks and state mutation run here. Popen never starts
a child: it returns a synthetic renderer JSON failure. Overlay and normal
function/portrait model ports return explicitly synthetic reviewed fixtures;
these tests establish orchestration contracts, not actual picture quality.
"""
import copy
import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost.editorial_continuation import review_extension as actual_review_extension
from hotpost.editorial_policy import EditorialWindowGap, policy
from hotpost.quality_progress import QualityProgressHold
from hotpost.source_presentation import POLICY as PORTRAIT_POLICY, review_scope, valid_review
from hotpost.source_quality import editing_ready, sha256_file
from hotpost.studio_pause import StudioPaused
from hotpost.studio_runtime.editing import EditingMixin
from hotpost.studio_store import Conflict


class MemoryStore:
    """Transactional, claim-aware state port; never touches the live SQLite DB."""
    def __init__(self, state):
        self.state=copy.deepcopy(state)
        self.checkpoints=[]
        self.events=[]
        self.claims=[]

    def get(self, task_id):
        assert task_id==self.state['id']
        return copy.deepcopy(self.state)

    def assert_owned(self, job):
        assert job['id']=='same-edit-job' and job['claim_token']=='same-claim'
        self.claims.append(job['id'])

    def checkpoint(self, job, checkpoint):
        self.assert_owned(job)
        self.checkpoints.append(copy.deepcopy(checkpoint))

    def change(self, task_id, fn, *, job):
        self.assert_owned(job)
        current=self.get(task_id)
        fn(current, None)
        self.state=current
        return copy.deepcopy(current)

    def event(self, db, task_id, kind, detail):
        self.events.append((task_id,kind,copy.deepcopy(detail)))


class Editor(EditingMixin):
    def folder(self, task_id):
        path=self.root/task_id
        path.mkdir(parents=True,exist_ok=True)
        return path

    def render_feedback(self, state, job, plan):
        # Keep the real _process JSON failure-to-typed-gap conversion in use.
        return self._process(state,job,'select-shots',{'plan':plan})

    def _review_source_records(self, state, job, candidates, progress):
        # Stub the existing normal source-review port, including its function/
        # portrait model calls. Its actual API returns (records, completion).
        self.normal_reviews.append((job['id'],copy.deepcopy(candidates)))
        progress('synthetic normal function/portrait review',.5)
        candidate=copy.deepcopy(candidates[0])
        frames=copy.deepcopy(candidate['mask_review']['evidence_frames'])
        candidate.update(editing_eligible=True,relevance_review_required=False,
                         presentation_review_required=False,source_role='core')
        candidate['functional_review']=dict(reviewed=True,same_core_function=True,
            source_sha256=candidate['sha256'],observed_actions=['synthetic fixture handling'],
            evidence_frames=frames)
        candidate['presentation_review']=dict(policy=PORTRAIT_POLICY,reviewed=True,
            source_sha256=candidate['sha256'],scope=review_scope(candidate),usable=True,
            quality_usable=True,action_preserved=True,evidence_frames=frames)
        assert editing_ready(candidate) and valid_review(candidate)
        if self.after_review:self.after_review(candidate)
        return [candidate],None

    def _edit(self, state, job):
        # Re-entry is observed here; do not launch analysis/model/render/TTS.
        self.reentered.append((copy.deepcopy(state),copy.deepcopy(job)))
        return {'reentered_same_job':job['id']}


@pytest.fixture
def continuation(tmp_path_factory,monkeypatch):
    # Real atomic receipts include a SHA + nonce filename. Avoid pytest's long
    # per-test folder names hitting Windows MAX_PATH before the contract runs.
    tmp_path=tmp_path_factory.mktemp('ep')
    original=tmp_path/'original.mp4';original.write_bytes(b'synthetic immutable video fixture')
    voice=tmp_path/'approved.wav';voice.write_bytes(b'synthetic approved voice fixture')
    script=tmp_path/'approved.txt';script.write_text('승인 대본은 그대로 유지합니다.',encoding='utf-8')
    source=dict(id='source',path=str(original),sha256=sha256_file(original),source_quality='clean-source',
        editing_eligible=True,video_meta=dict(duration=10.,width=720,height=1280),
        reviewed_intervals=[dict(source_start=2.,source_end=3.)],watermark_masks=[],
        mask_review=dict(source_sha256=sha256_file(original)))
    state=dict(id='task',automation={},scripts=[dict(id='script',path=str(script),text=script.read_text('utf-8'))],
        voices=[dict(id='voice',script_id='script',path=str(voice),sha256=sha256_file(voice),duration=1.45)],
        script_id='script',voice_id='voice',approved_script_id='script',approved_voice_id='voice',
        original_text='보존할 레퍼런스 원문',sources=[source])
    job=dict(id='same-edit-job',task_id='task',kind='edit',claim_token='same-claim',
        checkpoint={},payload=dict(script_id='script',voice_id='voice',source_ids=['source']))
    plan=dict(editorial_policy=policy(),fps=30,sources=copy.deepcopy(state['sources']),
        shots=[dict(id='shot',source_id='source',start=2.,end=3.,path=str(original),sha256=source['sha256'])],
        beats=[dict(id='beat',start=0,end=1.45,options=[dict(shot_id='shot')])])
    diagnostics=dict(failure_reason='reviewed_window_required',window_requests=[
        dict(beat_id='beat',shot_id='shot',source_id='source',required_duration=44/30,
             required_output_frames=44,reviewed_source_window=[2.,3.],required_extra_seconds=44/30-1)])
    editor=Editor();editor.root=tmp_path/'studio';editor.settings=Settings(data_dir=tmp_path/'data')
    editor.store=MemoryStore(state);editor.render_lock=threading.RLock()
    editor.normal_reviews=[];editor.reentered=[];editor.after_review=None
    overlay_calls=[];process_calls=[];extension_calls=[]

    def overlay(settings, source, root, *, intervals, generate=None):
        # Synthetic model response, with real temp frame bytes/SHA and exact
        # interval IDs so the real cached-review verifier remains exercised.
        overlay_calls.append(copy.deepcopy(intervals))
        root=Path(root);root.mkdir(parents=True,exist_ok=True)
        candidate=copy.deepcopy(source)
        rows=[];frames=[]
        for i,(start,end) in enumerate(intervals):
            frame=root/f'frame-{i}.png';frame.write_bytes(f'synthetic pixels {start} {end}'.encode())
            fid=f'frame-{i}'
            frames.append(dict(frame_id=fid,path=str(frame),sha256=sha256_file(frame),
                               source_timestamp=(start+end)/2))
            rows.append(dict(source_start=start,source_end=end,frame_ids=[fid],
                             coverage_confirmed=True,subject_visible=True))
        candidate['reviewed_intervals']=[dict(source_start=a,source_end=z) for a,z in intervals]
        candidate['mask_review']=dict(source_sha256=source['sha256'],intervals=rows,evidence_frames=frames)
        return candidate

    def popen(args, **kwargs):
        # Actual _process request identity is required, including output_dir.
        request=Path(args[args.index('--request')+1]);result=Path(args[args.index('--result')+1])
        value=json.loads(request.read_text('utf-8'));process_calls.append(copy.deepcopy(value))
        fingerprint=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
        result.write_text(json.dumps(dict(status='failed',error='synthetic renderer window shortage',
            error_code='reviewed_window_required',diagnostics=diagnostics,request_sha256=fingerprint)),encoding='utf-8')
        return SimpleNamespace(pid=2147483647,poll=lambda:0)

    def observed_extension(*args,**kwargs):
        # Observation wrapper calls the actual extension API without replacing
        # its signature, receipt, SHA or review/cache behavior.
        extension_calls.append(copy.deepcopy(args[2]))
        return actual_review_extension(*args,**kwargs)

    monkeypatch.setattr('hotpost.source_overlay_review.review_source_overlays',overlay)
    monkeypatch.setattr('hotpost.studio_runtime.editing.subprocess.Popen',popen)
    monkeypatch.setattr('hotpost.editorial_continuation.review_extension',observed_extension)
    return SimpleNamespace(editor=editor,state=copy.deepcopy(state),job=job,plan=plan,
        diagnostics=diagnostics,overlay_calls=overlay_calls,process_calls=process_calls,extension_calls=extension_calls,
        original=original,voice=voice,script=script)


def test_renderer_diagnostics_become_typed_gap_with_unchanged_diagnostics(continuation):
    f=continuation
    with pytest.raises(EditorialWindowGap) as caught:
        f.editor._process(f.state,f.job,'select-shots',{'plan':f.plan})
    assert caught.value.diagnostics==f.diagnostics
    assert f.process_calls[0]['action']=='select-shots'
    assert f.overlay_calls==[] and f.editor.reentered==[]


def test_shortage_reviews_adjacent_original_and_reenters_same_job_preserving_inputs(continuation):
    f=continuation;before=copy.deepcopy(f.state);job_payload=copy.deepcopy(f.job['payload'])
    files={p:p.read_bytes() for p in (f.original,f.voice,f.script)}
    assert f.editor._render_editorial_feedback(f.state,f.job,f.plan)=={'reentered_same_job':'same-edit-job'}
    current=f.editor.store.get('task');source=current['sources'][0]
    assert source['reviewed_intervals'][0]['source_start']==2.
    assert source['reviewed_intervals'][0]['source_end']>=2+44/30
    assert source['path']==before['sources'][0]['path'] and source['sha256']==before['sources'][0]['sha256']
    assert 'retiming' not in source
    for key in ('scripts','voices','script_id','voice_id','approved_script_id','approved_voice_id','original_text'):
        assert current[key]==before[key]
    assert all(p.read_bytes()==raw for p,raw in files.items()) and f.job['payload']==job_payload
    assert len(f.overlay_calls)==len(f.editor.normal_reviews)==len(f.editor.reentered)==1
    resumed,job=f.editor.reentered[0]
    assert resumed['sources']==current['sources'] and job['id']==f.job['id'] and job['claim_token']==f.job['claim_token']
    assert f.editor.store.events[0][1]=='editorial_source_continued'
    assert f.editor.store.events[0][2]['diagnostics']==f.diagnostics


def test_same_physical_scope_cannot_trigger_another_review_or_edit_reentry(continuation):
    f=continuation
    f.editor._render_editorial_feedback(f.state,f.job,f.plan)
    with pytest.raises(QualityProgressHold,match='같은 확장 방법 반복 중지'):
        f.editor._render_editorial_feedback(f.editor.store.get('task'),f.job,f.plan)
    assert len(f.overlay_calls)==len(f.editor.normal_reviews)==len(f.editor.reentered)==1
    assert len(f.editor.store.events)==1
    # Applied scopes are blocked before even opening a cached extension review.
    assert len(f.extension_calls)==1


def test_rejected_physical_scope_is_not_reviewed_again_under_same_job(continuation):
    f=continuation
    f.editor.after_review=lambda candidate:candidate.update(editing_eligible=False)
    for _ in range(2):
        with pytest.raises(QualityProgressHold):
            f.editor._render_editorial_feedback(f.state,f.job,f.plan)
    assert len(f.overlay_calls)==len(f.editor.normal_reviews)==1
    assert f.editor.store.state['sources']==f.state['sources'] and f.editor.reentered==[]


def test_changed_original_before_review_cannot_be_accepted(continuation):
    f=continuation;before=copy.deepcopy(f.editor.store.state)
    f.original.write_bytes(b'changed before extension review')
    with pytest.raises(ValueError,match='source file changed'):
        f.editor._render_editorial_feedback(f.state,f.job,f.plan)
    assert f.editor.store.state==before and f.overlay_calls==[] and f.editor.reentered==[]


def test_changed_original_during_review_cannot_commit_extension(continuation):
    f=continuation;before=copy.deepcopy(f.editor.store.state)
    f.editor.after_review=lambda candidate:f.original.write_bytes(b'changed while review was running')
    with pytest.raises((ValueError,Conflict),match='changed|변경'):
        f.editor._render_editorial_feedback(f.state,f.job,f.plan)
    assert f.editor.store.state==before and f.editor.reentered==[]


def test_concurrent_manual_source_change_wins_over_extension(continuation):
    f=continuation
    def manual(candidate):
        f.editor.store.state['sources'][0]['manual_usage_review']={'editing_eligible':False,'reason':'manual exclusion'}
    f.editor.after_review=manual
    with pytest.raises(Conflict,match='수동 사용 검토가 변경'):
        f.editor._render_editorial_feedback(f.state,f.job,f.plan)
    assert f.editor.store.state['sources'][0]['manual_usage_review']['editing_eligible'] is False
    assert f.editor.store.state['sources'][0]['reviewed_intervals']==f.state['sources'][0]['reviewed_intervals']
    assert f.editor.reentered==[]


def test_concurrent_withdrawal_prevents_new_scope_acceptance(continuation):
    f=continuation
    def withdraw(candidate):
        root=f.editor.settings.data_dir/'source_review_withdrawals';root.mkdir(parents=True)
        (root/(candidate['sha256']+'.json')).write_text(json.dumps(dict(source_sha256=candidate['sha256'],
            intervals=[dict(source_start=3.,source_end=3.3,evidence='synthetic evidence',reason='withdrawn actual scope')])),encoding='utf-8')
    f.editor.after_review=withdraw
    with pytest.raises(Conflict,match='소스 제외 근거가 변경'):
        f.editor._render_editorial_feedback(f.state,f.job,f.plan)
    assert f.editor.store.state['sources']==f.state['sources'] and f.editor.reentered==[]


@pytest.mark.parametrize('when',['before','during'])
def test_user_pause_preserves_state_and_prevents_edit_reentry(continuation,when):
    f=continuation
    if when=='before':f.editor.store.state['automation']['paused_by_user']=True
    else:f.editor.after_review=lambda candidate:f.editor.store.state['automation'].update(paused_by_user=True)
    with pytest.raises(StudioPaused):
        f.editor._render_editorial_feedback(f.state,f.job,f.plan)
    assert f.editor.store.state['sources']==f.state['sources'] and f.editor.reentered==[]
    if when=='before':assert f.overlay_calls==[]


def test_pause_before_commit_can_resume_same_accepted_scope_without_model_repeat(continuation):
    f=continuation
    f.editor.after_review=lambda candidate:f.editor.store.state['automation'].update(paused_by_user=True)
    with pytest.raises(StudioPaused):
        f.editor._render_editorial_feedback(f.state,f.job,f.plan)
    assert f.editor.reentered==[]
    f.editor.store.state['automation']['paused_by_user']=False
    f.editor.after_review=None
    result=f.editor._render_editorial_feedback(f.editor.store.get('task'),f.job,f.plan)
    assert result=={'reentered_same_job':'same-edit-job'}
    assert len(f.overlay_calls)==len(f.editor.normal_reviews)==len(f.editor.reentered)==1


def test_manual_exclusion_after_pause_cannot_be_overwritten_by_accepted_cache(continuation):
    f=continuation
    f.editor.after_review=lambda candidate:f.editor.store.state['automation'].update(paused_by_user=True)
    with pytest.raises(StudioPaused):
        f.editor._render_editorial_feedback(f.state,f.job,f.plan)
    assert len(f.overlay_calls)==len(f.editor.normal_reviews)==1
    f.editor.store.state['automation']['paused_by_user']=False
    manual={'editing_eligible':False,'reason':'manual source exclusion after review paused'}
    f.editor.store.state['sources'][0]['manual_usage_review']=copy.deepcopy(manual)
    f.editor.after_review=None
    with pytest.raises(QualityProgressHold):
        f.editor._render_editorial_feedback(f.editor.store.get('task'),f.job,f.plan)
    current=f.editor.store.get('task')
    assert current['sources'][0]['manual_usage_review']==manual
    assert current['sources'][0]['reviewed_intervals']==f.state['sources'][0]['reviewed_intervals']
    assert len(f.overlay_calls)==len(f.editor.normal_reviews)==len(f.extension_calls)==1
    assert f.editor.reentered==[] and f.editor.store.events==[]
