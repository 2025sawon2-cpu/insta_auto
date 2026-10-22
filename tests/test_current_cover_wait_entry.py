import copy
import inspect
import json
import os
from pathlib import Path

import pytest

from hotpost.daily_quality import DailyQualityMixin
from hotpost.studio_workflow import WorkflowMixin
from hotpost import daily_quality_routing


class Queue:
    def __init__(self):
        self.rows=[]
    def enqueue(self,db,task,kind,payload,key):
        self.rows.append((task,kind,copy.deepcopy(payload),key))
        return 'isolated-preparation'


class Worker(DailyQualityMixin,WorkflowMixin):
    pass


def captured(tmp_path):
    incident=json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    mapping={}
    def remap(value):
        if isinstance(value,dict):return {k:remap(v) for k,v in value.items()}
        if isinstance(value,list):return [remap(v) for v in value]
        if isinstance(value,str) and len(value)>2 and value[1]==':' and value[2]==chr(92):
            if value not in mapping:mapping[value]=str(tmp_path/('unavailable-'+str(len(mapping))))
            return mapping[value]
        return value
    return remap(copy.deepcopy(incident))


def test_existing_done_review_reaches_preparation(tmp_path,monkeypatch):
    incident=captured(tmp_path);state=incident['task'];job=incident['job']
    assert job['status']=='done' and job['kind']=='quality_review'
    assert state['daily_quality']['pending']=='scene_wait'
    assert job['payload']['edit_id']==state['edit_id']
    before=copy.deepcopy(state);original_job=copy.deepcopy(job)
    worker=Worker();worker.store=Queue()
    # Recover the precise old route by removing only the new scheduling block.
    source=inspect.getsource(daily_quality_routing.advance_daily_quality)
    start=source.index('    from .quality_progress import valid_cover_evidence')
    end=source.index('    key=f',start)
    old_source=source[:start]+source[end:]
    old_source=old_source.replace(' and coverage_current(state) and cover_ready:', ' and coverage_current(state):')
    namespace=dict(daily_quality_routing.__dict__)
    exec(compile(old_source,'preserved-old-routing','exec'),namespace)
    with monkeypatch.context() as patch:
        patch.setattr(daily_quality_routing,'advance_daily_quality',namespace['advance_daily_quality'])
        worker.advance_workflow(copy.deepcopy(state),None)
    assert worker.store.rows==[]
    worker.advance_workflow(state,None)
    assert len(worker.store.rows)==1
    task,kind,payload,key=worker.store.rows[0]
    assert task==before['id'] and kind=='refresh_sources'
    assert payload['daily_quality_repair'] is True
    for field in ('id','run_id','script_id','voice_id','edit_id'):
        assert state[field]==before[field]
    for field in ('reviews','feedback','reviewed_edit_id'):
        assert state['daily_quality'].get(field)==before['daily_quality'].get(field)
    assert job==original_job
    assert state['daily_quality']['status']!='passed'


@pytest.mark.parametrize('guard',['pause','hold','waiting','receipt_wait','content','narration'])
def test_current_holds_remain_authoritative(tmp_path,guard):
    state=captured(tmp_path)['task']
    if guard=='pause':state['automation']['paused_by_user']=True
    elif guard=='content':state['editorial_content_hold']={'reason':'retained'}
    elif guard=='narration':state['daily_quality']['narration_context_hold']={'reason':'retained'}
    else:state.setdefault('source_acquisition',{})[guard]={'reason':'retained'}
    worker=Worker();worker.store=Queue()
    worker.advance_workflow(state,None)
    assert worker.store.rows==[]
    assert state['daily_quality']['pending']=='scene_wait'
