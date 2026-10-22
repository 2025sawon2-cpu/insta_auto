import copy
import json
from types import SimpleNamespace
import pytest
from test_source_topic_queries import topic_case
from hotpost import source_topic_queries as topic
from hotpost.source_topic_replanning import acquire_topic_queries
from hotpost.source_visual_queries import digest, VisualQueryRejection


def saved_failure(c):
    c.owner.update(task_id='work-8b984aff50a04fa4',job_id='job-7282529de3cd420d',run_id='run-6d352751db6b4c3b')
    evidence=topic.binding(c.reference,[c.frame],c.caption,{},search_minimums={'en':5,'zh':5},subject_hint='향수',owner_binding=c.owner)
    bad=copy.deepcopy(c.proposal)
    bad['observations']=[{'id':'o3','text':'brand on box','frame_ids':[evidence['frames'][0]['id']]}]
    bad['subject_identity']['required_terms'][0].update(source='visual',observation_ids=['o3'])
    review=copy.deepcopy(c.review)
    review.update(input_sha256=digest(evidence),proposal_sha256=digest(bad),core_identity_complete=False,known_subject_identity_complete=False)
    root=c.tmp_path/'source-topic-query-receipts'/digest({'evidence':evidence,'owner':c.owner})
    root.mkdir(parents=True)
    for name,value in [('proposal.json',{'input_sha256':digest(evidence),'proposal':bad}),('review.json',review)]:
        (root/name).write_text(json.dumps(value),encoding='utf8')
    return evidence,bad,review,root


def invoke(c,entry,external):
    return entry(SimpleNamespace(data_dir=c.tmp_path),c.reference,[c.frame],c.caption,{},external,search_minimums={'en':5,'zh':5},subject_hint='향수',owner_binding=c.owner)


def test_saved_failure_requests_new_proposal_and_new_bound_review(topic_case):
    c=topic_case;evidence,bad,old_review,root=saved_failure(c)
    before={p.name:p.read_bytes() for p in root.iterdir()}
    with pytest.raises(VisualQueryRejection):
        invoke(c,topic.cached_topic_queries,lambda *a,**k:pytest.fail('old cache blocks generation'))
    fresh=copy.deepcopy(bad)
    fresh['subject_identity']['required_terms'][0].update(source='caption',quote='디올 향수')
    calls=[]
    def external(settings,instruction,data,**kwargs):
        calls.append(copy.deepcopy(data))
        assert settings.data_dir==c.tmp_path
        if 'proposal_sha256' not in data:
            assert data['planning_feedback']['rejected_proposal']==bad
            assert 'exact literal quote' in instruction
            return copy.deepcopy(fresh)
        review=copy.deepcopy(old_review)
        review.update(input_sha256=data['input_sha256'],proposal_sha256=data['proposal_sha256'])
        assert review['proposal_sha256']!=old_review['proposal_sha256']
        return review
    receipt=invoke(c,acquire_topic_queries,external)
    assert receipt['owner']==c.owner and len(topic.verify(receipt))==10
    assert receipt['approved_query_pool']['ready'] and len(calls)==2
    assert all((root/name).read_bytes()==value for name,value in before.items())
    assert invoke(c,acquire_topic_queries,lambda *a,**k:pytest.fail('reuse verified recovery'))==receipt


def test_failed_new_proposal_is_persisted_without_more_generation(topic_case):
    c=topic_case;evidence,bad,review,root=saved_failure(c);calls=[]
    def external(settings,instruction,data,**kwargs):
        calls.append(data)
        return copy.deepcopy(review if 'proposal_sha256' in data else bad)
    for _ in range(2):
        with pytest.raises(VisualQueryRejection):invoke(c,acquire_topic_queries,external)
    assert len(calls)==2 and not (root/'receipt.json').exists()


@pytest.mark.parametrize('fault',['input','review_hash','unsupported'])
def test_invalid_failure_cannot_request_new_generation(topic_case,fault):
    c=topic_case;evidence,bad,review,root=saved_failure(c)
    path=root/('proposal.json' if fault=='input' else 'review.json')
    value=json.loads(path.read_text('utf8'))
    if fault=='input':value['input_sha256']='0'*64
    if fault=='review_hash':value['proposal_sha256']='0'*64
    if fault=='unsupported':value['subject_identity_supported']=False
    path.write_text(json.dumps(value),encoding='utf8')
    with pytest.raises(ValueError):invoke(c,acquire_topic_queries,lambda *a,**k:pytest.fail('invalid binding'))
    assert not (root/'provenance-replanning').exists()
