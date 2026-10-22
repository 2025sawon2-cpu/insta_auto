import copy
import pytest
from hotpost import source_visual_queries as visual
from hotpost.source_preparation import reusable_query_contract
from hotpost.source_coverage import search_scope_for_state
from hotpost.studio_automation import refresh_resolved_subject
from test_source_visual_query_minima_v5 import setup,proposal,model,plan


def fixture(tmp_path,monkeypatch):
    settings,reference,frames=setup(tmp_path)
    state={'id':'task','run_id':'run','product':'재킷','original_text':'의류 소개',
           'reference_video':str(reference)}
    current=visual.search_contract
    with monkeypatch.context() as patch:
        patch.setattr(visual,'search_contract',lambda minimums=None:
            {**current(minimums),'identity_prompt_revision':'reference-topic-and-scene-intent-v4'} if minimums else None)
        receipt=visual.cached_visual_queries(settings,reference,frames,'재킷',{},model(proposal(),[]),
            search_minimums={'en':5,'zh':5},subject_hint='재킷')
        document=plan(receipt)
    policy={'version':6,'search_minimums':{'en':5,'zh':5}}
    context={'run_id':'run','search_context':search_scope_for_state(state)}
    document.update(source_policy=policy,**context)
    return state,document,policy,context


def test_valid_active_plan_reused_without_mutating_original_receipt(tmp_path,monkeypatch):
    state,document,policy,context=fixture(tmp_path,monkeypatch)
    before=copy.deepcopy(document)
    assert reusable_query_contract(document,policy,'재킷',context)
    assert document==before


@pytest.mark.parametrize('fault',['run','product','text','reference','policy','hint','receipt','pixels'])
def test_old_prompt_reuse_rejects_changed_scope_or_evidence(tmp_path,monkeypatch,fault):
    state,document,policy,context=fixture(tmp_path,monkeypatch)
    context=copy.deepcopy(context);policy=copy.deepcopy(policy);hint='재킷'
    if fault=='run':context['run_id']='new'
    elif fault in {'product','text','reference'}:
        context['search_context'][{'product':'product','text':'reference_text_sha256','reference':'reference_sha256'}[fault]]='changed'
    elif fault=='policy':policy['version']=5
    elif fault=='hint':hint='바지'
    elif fault=='receipt':document['visual_query_evidence']['review']['proposal_sha256']='changed'
    elif fault=='pixels':
        from pathlib import Path
        Path(state['reference_video']).write_bytes(b'changed')
    assert not reusable_query_contract(document,policy,hint,context)


def test_grounded_label_is_stable_but_bad_or_stale_evidence_cannot_freeze_it(tmp_path,monkeypatch):
    state,document,_,_=fixture(tmp_path,monkeypatch)
    document['primary_subject']={'name':'의류','source':'speech','quote':'의류 소개'}
    manifest={'product_evidence':document}
    assert not refresh_resolved_subject(state,manifest) and state['product']=='재킷'
    document['run_id']='old'
    assert refresh_resolved_subject(state,manifest) and state['product']=='의류'
    state['product']='재킷';document['run_id']='run'
    document['visual_query_evidence']['review']['proposal_sha256']='changed'
    assert refresh_resolved_subject(state,manifest) and state['product']=='의류'
