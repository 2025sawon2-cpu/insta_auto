import hashlib
import json
from types import SimpleNamespace

import pytest

from hotpost import studio_sources
from hotpost.source_visual_queries import VisualQueryRejection, digest


def setup_case(tmp_path):
    reference=tmp_path/'reference.mp4'
    reference.write_bytes(b'fixed reference')
    evidence={'reference_sha256':hashlib.sha256(reference.read_bytes()).hexdigest(),
              'text':{'speech':'fixed input'}}
    key=digest(evidence)
    proposal={'observations':[],'queries':[]}
    p=tmp_path/'proposal.json';r=tmp_path/'review.json'
    p.write_text(json.dumps({'input_sha256':key,'proposal':proposal}),encoding='utf-8')
    r.write_text(json.dumps({'input_sha256':key,'proposal_sha256':digest(proposal),
                            'subject_identity_supported':False}),encoding='utf-8')
    owner={'task_id':'task-one','job_id':'job-one','run_id':'run-one'}
    error=VisualQueryRejection(ValueError('identity rejected'),evidence,p,r,owner)
    state={'id':'task-one','run_id':'run-one','reference_video':str(reference)}
    job={'id':'job-one','task_id':'task-one','kind':'collect_sources',
         'payload':{'run_id':'run-one'},'checkpoint':{}}
    return state,job,error,r,key


def source_class():
    matches=[v for v in vars(studio_sources).values() if isinstance(v,type)
             and v.__module__==studio_sources.__name__
             and 'handle_source_error' in v.__dict__]
    assert len(matches)==1
    return matches[0]


@pytest.mark.parametrize('mismatch',[None,'task','run','job','input','tamper'])
def test_real_error_handler_only_registers_current_owned_input(tmp_path,monkeypatch,mismatch):
    state,job,error,review,key=setup_case(tmp_path)
    failed=[];checkpoints=[]
    store=SimpleNamespace(get=lambda task:state,
        checkpoint=lambda j,c:checkpoints.append(dict(c)),
        fail=lambda j,e:failed.append(e))
    agent=SimpleNamespace(store=store)
    cls=source_class()
    progress=lambda *args:None
    cls._bind_source_attempt_progress(agent,state,job,progress)
    assert progress.visual_query_input(key)==error.receipt['binding']
    assert checkpoints[-1]['visual_query_input']['input_sha256']==key
    if mismatch=='task':state['id']='other-task';job['task_id']='other-task'
    if mismatch=='run':state['run_id']='other-run';job['payload']['run_id']='other-run'
    if mismatch=='job':job['id']='other-job'
    if mismatch=='input':job['checkpoint']['visual_query_input']['input_sha256']='different'
    if mismatch=='tamper':review.write_text('{}',encoding='utf-8')
    monkeypatch.setattr(studio_sources,'change_claimed',lambda s,j,fn:fn(state,None))
    monkeypatch.setattr('hotpost.retry_budget.reserve',lambda *args:False)
    cls.handle_source_error(agent,job,error)
    assert failed==[error]
    registered=state.get('source_acquisition',{}).get('visual_query_rejection')
    assert bool(registered)==(mismatch is None)
    assert 'search_identity' not in state
    if registered:
        assert registered['input_sha256']==key
        assert registered['binding']==error.receipt['binding']
        assert registered['files'][1]['sha256']==hashlib.sha256(review.read_bytes()).hexdigest()


def test_saved_review_input_sha_is_checked_even_with_matching_file_hash(tmp_path):
    from hotpost.source_visual_queries import register_rejection_evidence
    state,job,error,review,key=setup_case(tmp_path)
    job['checkpoint']['visual_query_input']={**error.receipt['binding'],'input_sha256':key}
    data=json.loads(review.read_text('utf-8'));data['input_sha256']='wrong'
    review.write_text(json.dumps(data),encoding='utf-8')
    error.receipt['files'][1]['sha256']=hashlib.sha256(review.read_bytes()).hexdigest()
    assert register_rejection_evidence(state,job,error) is False
    assert 'source_acquisition' not in state
