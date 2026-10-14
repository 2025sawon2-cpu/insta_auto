import copy
import threading
from types import SimpleNamespace

import pytest

from hotpost.model_service import ModelServiceUnavailable
from hotpost.studio_runtime.lifecycle import LifecycleMixin


class Store:
    def __init__(self,worker,state,job):self.worker=worker;self.state=state;self.job=job;self.changes=0
    def claim(self,lane):
        job=self.job;self.job=None
        if not job:self.worker.stop.set()
        return job
    def get(self,identity):return copy.deepcopy(self.state)
    def change(self,identity,callback):
        callback(self.state,None);self.changes+=1;return copy.deepcopy(self.state)
    def checkpoint(self,*args):pass
    def finish(self,*args):self.worker.stop.set()
    def defer(self,job,message,seconds,**kwargs):
        self.state.update(status=kwargs['waiting_status'],message=message)
        self.worker.stop.set()


def fixture(kind,status='retry_wait'):
    worker=LifecycleMixin();worker.stop=threading.Event()
    worker.settings=SimpleNamespace(studio_daily_quality_max_repairs=3)
    state={'id':'task','status':status,'message':'모델 처리 용량 부족','error':'preserved-error',
        'error_history':[{'stage':'old','reason':'preserved'}],
        'sources':[],'script_id':'script','automation':{'active':False,'paused_by_user':False},
        'daily_quality':{'repair_round':2,'max_repairs':3,'scene_no_progress':2,'collection_attempt':4}}
    if kind=='quality_reedit':
        state['daily_quality'].update(feedback=[{'kind':'cover','reason':'표지가 질문의 답을 공개함'}],
            thumbnail_lines=['제품의 새 질문','이 촉감은 어떨까요?'])
    job={'id':'job','task_id':'task','kind':kind,'payload':{},'checkpoint':{'service_retries':2}}
    worker.store=Store(worker,state,job)
    return worker,state,job


@pytest.mark.parametrize('kind,expected',[('quality_review','quality_review'),
    ('quality_reedit','editing'),('refresh_sources','source_wait')])
def test_claimed_eligible_model_retry_reports_actual_stage_and_preserves_history_and_limits(monkeypatch,kind,expected):
    worker,state,job=fixture(kind);before=copy.deepcopy(state);seen=[]
    monkeypatch.setattr('hotpost.scene_requirements.repair_render_signature',lambda state:'actual-input')
    def run(actual,job):
        seen.append(copy.deepcopy(actual));worker.stop.set();return {}
    setattr(worker,'_'+kind,run)
    worker._worker('media')
    assert seen[0]['status']==expected and '다시 진행 중' in seen[0]['message']
    for key in ('error','error_history','automation'):
        assert seen[0][key]==before[key]
    for key,value in before['daily_quality'].items():
        assert seen[0]['daily_quality'][key]==value
    assert job['checkpoint']['service_retries']==2
    assert worker.store.changes==(2 if kind=='quality_reedit' else 1)
    if kind=='quality_reedit':
        attempts=seen[0]['daily_quality']['progress_policy']['attempts']
        assert len(attempts)==1 and attempts[0]['status']=='planned'


def test_still_blocked_service_restores_wait_without_consuming_actual_retry_or_quality_cap():
    worker,state,job=fixture('quality_review');before=copy.deepcopy(state);seen=[]
    def run(actual,job):
        seen.append(actual['status']);raise ModelServiceUnavailable(attempted=False)
    worker._quality_review=run
    worker._worker('media')
    assert seen==['quality_review'] and state['status']=='retry_wait'
    assert job['checkpoint']['service_retries']==2
    assert state['daily_quality']==before['daily_quality'] and state['automation']==before['automation']
    assert state['error_history']==before['error_history']


@pytest.mark.parametrize('status',['paused','source_wait','quality_review'])
def test_actual_retry_resume_does_not_replace_unrelated_or_user_stopped_status(status):
    worker,state,job=fixture('quality_review',status);before=copy.deepcopy(state)
    worker._quality_review=lambda *a:{}
    worker._worker('media')
    assert state==before and worker.store.changes==0


def test_no_eligible_claim_leaves_wait_state_untouched():
    worker,state,job=fixture('quality_review');worker.store.job=None;before=copy.deepcopy(state)
    worker._worker('media')
    assert state==before and worker.store.changes==0


def test_user_status_change_at_commit_is_preserved():
    worker,state,job=fixture('quality_review');snapshot=copy.deepcopy(state)
    state.update(status='paused',message='사용자 중지')
    worker._resume_claimed_retry_phase(snapshot,job)
    assert state['status']=='paused' and state['message']=='사용자 중지'
