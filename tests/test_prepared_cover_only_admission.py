import copy
import json

import pytest

from hotpost.quality_progress import QualityProgressHold
from test_quality_cover_preparation_independent import fixture


@pytest.mark.parametrize('copy_available',[True,False])
def test_exact_reviewed_cover_keeps_body_and_uses_normal_guard(tmp_path,monkeypatch,copy_available):
    worker,state,job,document=fixture(tmp_path,monkeypatch)
    state['daily_quality']['feedback']=[{'kind':'cover','reason':'Wrong representative product'}]
    worker.store.change(state['id'],lambda s,db:s['daily_quality'].update(feedback=state['daily_quality']['feedback']))
    evidence=worker.prepare_quality_cover_evidence(state,job)
    state['daily_quality']['cover_repair_evidence']=evidence
    worker.store.change(state['id'],lambda s,db:s['daily_quality'].update(cover_repair_evidence=evidence))
    worker.stages.clear();calls=[]
    monkeypatch.setattr('hotpost.quality_progress.guard_render',lambda s,p,j:calls.append(('guard',copy.deepcopy(p))) or None)
    def copied(studio,s,j,p):
        calls.append(('copy',copy.deepcopy(p)))
        return {'preview_path':'copied.mp4'} if copy_available else None
    monkeypatch.setattr('hotpost.cover_frame_copy.render_if_cover_only',copied)
    def process(s,j,stage,payload):
        assert stage=='render'
        calls.append((stage,copy.deepcopy(payload['plan'])))
        return {'preview_path':'rendered.mp4'}
    worker._process=process
    worker.render_feedback=lambda *a:pytest.fail('Do not discard the reviewed framing by reselecting candidates')
    result=worker._quality_reedit(state,{'id':'repair','task_id':state['id'],'kind':'quality_reedit',
        'payload':{'edit_id':state['edit_id']}})
    assert [c[0] for c in calls]==(['guard','copy'] if copy_available else ['guard','copy','render'])
    expected=json.loads(open(evidence['prepared_plan']['path'],encoding='utf8').read())
    assert all(p==expected for _,p in calls)
    assert result['parent_id']==state['edit_id']
    assert result['quality_repair_round']==4 and state['daily_quality']['repair_round']==3


@pytest.mark.parametrize('block',['pause','method'])
def test_exact_prepared_cover_never_skips_pause_or_method_guard(tmp_path,monkeypatch,block):
    worker,state,job,document=fixture(tmp_path,monkeypatch)
    state['daily_quality']['feedback']=[{'kind':'cover','reason':'Wrong representative product'}]
    worker.store.change(state['id'],lambda s,db:s['daily_quality'].update(feedback=state['daily_quality']['feedback']))
    evidence=worker.prepare_quality_cover_evidence(state,job)
    state['daily_quality']['cover_repair_evidence']=evidence
    worker.store.change(state['id'],lambda s,db:s['daily_quality'].update(cover_repair_evidence=evidence))
    if block=='pause':worker.store.change(state['id'],lambda s,db:s['automation'].update(paused_by_user=True))
    monkeypatch.setattr('hotpost.quality_progress.guard_render',lambda *a:'Same failed output' if block=='method' else None)
    monkeypatch.setattr('hotpost.cover_frame_copy.render_if_cover_only',lambda *a:pytest.fail('Guarded render'))
    with pytest.raises(QualityProgressHold):
        worker._quality_reedit(state,{'id':'repair','task_id':state['id'],'kind':'quality_reedit',
            'payload':{'edit_id':state['edit_id']}})
