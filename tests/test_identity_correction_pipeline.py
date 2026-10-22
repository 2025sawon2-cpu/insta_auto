import copy
import hashlib
import json
import tempfile
from pathlib import Path
import pytest
from hotpost import source_visual_queries as visual
from hotpost.source_query_identity import matches_identity
from test_source_visual_query_minima_v5 import setup, proposal, model


@pytest.fixture
def pipeline_path():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(dir=root, prefix='i') as directory:
        path = Path(directory)
        assert path.parent == root
        yield path


def corrected_proposal():
    value=proposal()
    value['subject_identity']['kind']='feature'
    value['subject_identity']['required_terms']=[{
        'kind':'feature','terms':{'en':['stand collar'],'zh':['立领'],'ko':['세워진 칼라']},
        'source':'visual','observation_ids':['observed']}]
    for row in value['queries']:
        term='stand collar' if row['language']=='en' else '立领'
        if term not in row['query']:
            row['query']=term+(' ' if row['language']=='en' else '')+row['query']
    return value


@pytest.mark.parametrize('fault',[None,'identity','sha','unsupported','binding'])
def test_actual_correction_and_failure_provenance(pipeline_path,fault):
    settings,reference,frames=setup(pipeline_path)
    original=proposal();corrected=corrected_proposal()
    assert original!=corrected
    owner={'task_id':'task','job_id':'job','run_id':'run'}
    calls=[];snapshots={}
    def generate(settings,instruction,data,**kwargs):
        calls.append(copy.deepcopy(data))
        n=len(calls)
        if n==1:return copy.deepcopy(original)
        if n==2:
            result=model(original,[])(settings,instruction,data,**kwargs)
            result.update(core_identity_complete=False,topic_reason='Missing defining stand collar / 立领 feature observed in frame-1')
            return result
        root=pipeline_path/'source-visual-queries'/visual.digest(data['evidence'])
        if n==3:
            assert data['rejected_proposal']==original
            assert data['independent_review']['core_identity_complete'] is False
            snapshots.update({name:(root/name).read_bytes() for name in ['proposal.json','review.json']})
            return copy.deepcopy(corrected)
        assert n==4
        assert data['proposal']==corrected
        result=model(corrected,[],reject=[corrected['queries'][0]['id']] if fault=='unsupported' else [])(settings,instruction,data,**kwargs)
        if fault=='identity':result['core_identity_complete']=False
        if fault=='sha':result['proposal_sha256']='wrong'
        return result
    def run(gen=generate):
        return visual.cached_visual_queries(settings,reference,frames,'재킷',{},gen,
            search_minimums={'en':5,'zh':5},owner_binding=owner)
    if fault=='binding':
        def interrupt(settings,instruction,data,**kwargs):
            if len(calls)==2:raise RuntimeError('service unavailable')
            return generate(settings,instruction,data,**kwargs)
        with pytest.raises(RuntimeError,match='service unavailable'):run(interrupt)
        root=next((pipeline_path/'source-visual-queries').iterdir())
        snapshots.update({name:(root/name).read_bytes() for name in ['proposal.json','review.json']})
        (root/'identity-correction-proposal.json').write_text(json.dumps(
            {'input_sha256':root.name,'feedback_sha256':'wrong','proposal':corrected}),encoding='utf-8')
    if fault in (None,'unsupported'):
        receipt=run();root=pipeline_path/'source-visual-queries'/receipt['input_sha256']
        assert len(calls)==4
        assert receipt['proposal']==corrected
        assert receipt['search_identity']['required_terms']==corrected['subject_identity']['required_terms']
        rows=visual.verify(receipt)
        assert all(matches_identity(row['query'],receipt['search_identity']) for row in rows)
        assert not matches_identity('front zip jacket',receipt['search_identity'])
        assert len(rows)==(9 if fault=='unsupported' else 10)
        assert receipt['approved_query_pool']['ready'] is (fault is None)
        if fault=='unsupported':
            rejected=corrected['queries'][0]
            assert all(row['query']!=rejected['query'] for row in rows)
            pool=receipt['approved_query_pool']['languages'][rejected['language']]
            assert pool['count']==4 and pool['minimum']==5 and pool['ready'] is False
        def forbidden(*a,**k):raise AssertionError('completed cache called model')
        assert run(forbidden)==receipt
    else:
        with pytest.raises(visual.VisualQueryRejection) as caught:run()
        error=caught.value
        root=pipeline_path/'source-visual-queries'/error.receipt['input_sha256']
        assert not (root/'receipt.json').exists()
        assert len(calls)==(2 if fault=='binding' else 4)
        diagnostics=error.receipt['correction_diagnostics']
        assert len(diagnostics)==(1 if fault=='binding' else 2)
        for row in diagnostics:
            assert hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()==row['sha256']
        if fault!='binding':
            assert json.loads(Path(diagnostics[0]['path']).read_text('utf-8'))['proposal']==corrected
            failed_review=json.loads(Path(diagnostics[1]['path']).read_text('utf-8'))
            if fault=='sha':assert failed_review['proposal_sha256']=='wrong'
            else:assert failed_review['core_identity_complete'] is False
        state={'id':'task','run_id':'run','reference_video':str(reference)}
        job={'id':'job','task_id':'task','payload':{'run_id':'run'},
             'checkpoint':{'visual_query_input':{**owner,'input_sha256':error.receipt['input_sha256']}}}
        assert visual.register_rejection_evidence(state,job,error) is True
        assert state['source_acquisition']['visual_query_rejection']['correction_diagnostics']==diagnostics
        assert 'search_identity' not in state
        Path(diagnostics[-1]['path']).write_text('{}',encoding='utf-8')
        clean={'id':'task','run_id':'run','reference_video':str(reference)}
        assert visual.register_rejection_evidence(clean,job,error) is False
        assert 'source_acquisition' not in clean
    assert snapshots
    for name,before in snapshots.items():assert (root/name).read_bytes()==before


def test_service_wait_reuses_changed_correction_proposal(pipeline_path):
    settings,reference,frames=setup(pipeline_path)
    original=proposal();corrected=corrected_proposal();calls=[]
    def generate(settings,instruction,data,**kwargs):
        calls.append(copy.deepcopy(data))
        if len(calls)==1:return copy.deepcopy(original)
        if len(calls)==2:
            result=model(original,[])(settings,instruction,data,**kwargs)
            result['core_identity_complete']=False
            return result
        if len(calls)==3:return copy.deepcopy(corrected)
        raise RuntimeError('service unavailable')
    def run(gen):
        return visual.cached_visual_queries(settings,reference,frames,'재킷',{},gen,search_minimums={'en':5,'zh':5})
    with pytest.raises(RuntimeError,match='service unavailable'):run(generate)
    assert len(calls)==4
    root=next((pipeline_path/'source-visual-queries').iterdir())
    before={name:(root/name).read_bytes() for name in ['proposal.json','review.json','identity-correction-proposal.json']}
    resumed=[]
    receipt=run(model(corrected,resumed))
    assert len(resumed)==1
    assert receipt['proposal']==corrected and corrected!=original
    assert len(visual.verify(receipt))==10
    for name,data in before.items():assert (root/name).read_bytes()==data
