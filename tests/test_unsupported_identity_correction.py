import copy
import hashlib
import pytest
from hotpost import source_visual_queries as visual
from hotpost.source_query_identity import matches_identity
from test_source_visual_query_minima_v5 import setup, proposal, model
from test_identity_correction_pipeline import pipeline_path, corrected_proposal


@pytest.mark.parametrize('fault',[None,'unsupported','incomplete','sha'])
def test_unsupported_initial_identity_requires_fresh_independent_approval(pipeline_path,fault):
    settings,reference,frames=setup(pipeline_path)
    original=proposal();corrected=corrected_proposal()
    assert original!=corrected
    calls=[];before={}
    def generate(settings,instruction,data,**kwargs):
        calls.append(copy.deepcopy(data))
        n=len(calls)
        if n==1:return copy.deepcopy(original)
        if n==2:
            result=model(original,[])(settings,instruction,data,**kwargs)
            result.update(subject_identity_supported=False,core_identity_complete=False,
                          topic_reason='Missing defining stand collar observed in frame-1')
            return result
        root=pipeline_path/'source-visual-queries'/visual.digest(data['evidence'])
        if n==3:
            assert data['rejected_proposal']==original
            assert data['independent_review']['subject_identity_supported'] is False
            assert data['independent_review']['core_identity_complete'] is False
            before.update({name:(root/name).read_bytes() for name in ['proposal.json','review.json']})
            return copy.deepcopy(corrected)
        assert n==4
        assert data['proposal']==corrected
        result=model(corrected,[])(settings,instruction,data,**kwargs)
        if fault=='unsupported':result['subject_identity_supported']=False
        if fault=='incomplete':result['core_identity_complete']=False
        if fault=='sha':result['proposal_sha256']='wrong'
        return result
    def run(gen=generate):
        return visual.cached_visual_queries(settings,reference,frames,'재킷',{},gen,
                                           search_minimums={'en':5,'zh':5})
    if fault is None:
        receipt=run()
        root=pipeline_path/'source-visual-queries'/receipt['input_sha256']
        assert receipt['proposal']==corrected
        assert receipt['review']['subject_identity_supported'] is True
        assert receipt['review']['core_identity_complete'] is True
        rows=visual.verify(receipt)
        assert len(rows)==10
        assert receipt['approved_query_pool']['ready'] is True
        assert all(matches_identity(row['query'],receipt['search_identity']) for row in rows)
        assert not matches_identity('front zip jacket',receipt['search_identity'])
        def forbidden(*a,**k):raise AssertionError('Completed cache must not regenerate')
        assert run(forbidden)==receipt
    else:
        with pytest.raises(visual.VisualQueryRejection) as caught:run()
        rejection=caught.value
        root=pipeline_path/'source-visual-queries'/rejection.receipt['input_sha256']
        assert not (root/'receipt.json').exists()
        diagnostics=rejection.receipt['correction_diagnostics']
        assert len(diagnostics)==2
        for row in diagnostics:
            from pathlib import Path
            assert hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()==row['sha256']
        with pytest.raises(visual.VisualQueryRejection):run()
    assert len(calls)==4
    assert before
    for name,value in before.items():assert (root/name).read_bytes()==value
