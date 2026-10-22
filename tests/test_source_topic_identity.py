"""Method-led topics retain known identity, old evidence and independent gates."""
import copy
import json

import pytest

from hotpost import source_visual_queries as visual
from hotpost.source_preparation import reusable_query_contract
from hotpost.source_query_identity import matches_identity
from test_source_visual_query_minima_v5 import setup, model, plan


def food_proposal():
    return {
        'topic_reason': 'Known wakame soup; additive is undisclosed and must not be inferred.',
        'subject_identity': {'version': 'core-product-identity-v2', 'kind': 'category',
            'product_terms': {'en': ['wakame soup'], 'zh': ['裙带菜汤'], 'ko': ['미역국']},
            'required_terms': []},
        'observations': [{'id': 'observed', 'text': 'Green leaves in soup.', 'frame_ids': ['frame-1']}],
        'queries': [{'id': lang, 'query': query, 'language': lang,
                     'observation_ids': ['observed'], 'frame_ids': ['frame-1']}
                    for lang, query in [('en', 'wakame soup'), ('zh', '裙带菜汤'), ('ko', '미역국')]],
    }


def test_method_contract_reaches_both_roles_without_inventing_unknown_ingredient(tmp_path):
    settings, reference, frames = setup(tmp_path)
    calls = []
    receipt = visual.cached_visual_queries(settings, reference, frames,
        '미역국, 이름이 공개되지 않은 비법재료', {}, model(food_proposal(), calls),
        search_minimums={'en': 5, 'zh': 5}, subject_hint='미역국')
    assert len(calls) == 2 and all(visual.TOPIC_IDENTITY_PROMPT in prompt for prompt in calls)
    assert receipt['search_identity']['required_terms'] == []
    assert len(receipt['queries']) == 3
    assert not receipt['approved_query_pool']['ready']  # No fabricated quota expansion.
    identity = receipt['search_identity']
    assert matches_identity('裙带菜汤', identity)
    assert not matches_identity('海带汤', identity)
    assert not matches_identity('seaweed soup', identity)


def test_current_contract_keeps_independent_identity_rejection(tmp_path):
    settings, reference, frames = setup(tmp_path)
    base = model(food_proposal(), [])
    def reject(settings, instruction, data, **kwargs):
        result = base(settings, instruction, data, **kwargs)
        if 'proposal_sha256' in data:
            result['subject_identity_supported'] = False
        return result
    with pytest.raises(ValueError, match='독립 검토'):
        visual.cached_visual_queries(settings, reference, frames, '미역국', {}, reject,
            search_minimums={'en': 5, 'zh': 5})


def test_old_failed_cache_preserved_and_new_contract_needs_fresh_review(tmp_path, monkeypatch):
    settings, reference, frames = setup(tmp_path)
    old_contract = visual.search_contract
    value = food_proposal()
    def reject(settings, instruction, data, **kwargs):
        result = model(value, [])(settings, instruction, data, **kwargs)
        if 'proposal_sha256' in data:
            result['core_identity_complete'] = False
        return result
    with monkeypatch.context() as patch:
        patch.setattr(visual, 'search_contract', lambda minima=None:
            {**old_contract(minima), 'identity_prompt_revision': 'reference-topic-and-scene-intent-v5'})
        with pytest.raises(ValueError, match='독립 검토'):
            visual.cached_visual_queries(settings, reference, frames, '미역국', {}, reject,
                search_minimums={'en': 5, 'zh': 5})
    old_files = {p: p.read_bytes() for p in (tmp_path/'source-visual-queries').rglob('*.json')}
    assert len(old_files) == 2 and not any(p.name == 'receipt.json' for p in old_files)
    calls = []
    receipt = visual.cached_visual_queries(settings, reference, frames, '미역국', {},
        model(value, calls), search_minimums={'en': 5, 'zh': 5})
    assert len(calls) == 2
    assert all(p.read_bytes() == data for p, data in old_files.items())
    assert all(p.parent.name != receipt['input_sha256'] for p in old_files)


@pytest.mark.parametrize('revision', ['v4', 'v5'])
@pytest.mark.parametrize('fault', [None, 'run', 'context', 'sha', 'policy', 'hint', 'review', 'missing'])
def test_old_active_receipt_only_reused_for_same_valid_run(tmp_path, monkeypatch, revision, fault):
    settings, reference, frames = setup(tmp_path)
    current = visual.search_contract
    with monkeypatch.context() as patch:
        patch.setattr(visual, 'search_contract', lambda minima=None:
            {**current(minima), 'identity_prompt_revision': 'reference-topic-and-scene-intent-' + revision})
        receipt = visual.cached_visual_queries(settings, reference, frames, '미역국', {},
            model(food_proposal(), []), search_minimums={'en': 5, 'zh': 5}, subject_hint='미역국')
        document = plan(receipt)
    policy = {'version': 6, 'search_minimums': {'en': 5, 'zh': 5}}
    context = {'run_id': 'active', 'search_context': {'reference_sha256': receipt['evidence']['reference_sha256'],
               'product': '미역국', 'reference_text_sha256': 'stable-text'}}
    document.update(source_policy=copy.deepcopy(policy), **copy.deepcopy(context))
    hint = '미역국'
    if fault == 'run': context['run_id'] = 'new-run'
    elif fault == 'context': context['search_context']['product'] = '다시마국'
    elif fault == 'sha': document['query_reference_sha256'] = 'wrong'
    elif fault == 'policy': policy['version'] = 5
    elif fault == 'hint': hint = '다시마국'
    elif fault == 'review': document['visual_query_evidence']['review']['core_identity_complete'] = False
    elif fault == 'missing': document['visual_query_evidence'].pop('review')
    before = json.dumps(document, sort_keys=True)
    assert reusable_query_contract(document, policy, hint, context) is (fault is None)
    assert json.dumps(document, sort_keys=True) == before
