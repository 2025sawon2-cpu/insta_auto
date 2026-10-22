import copy
import json
import os
from pathlib import Path


def test_insufficient_text_recovery_is_bounded_and_preserves_responses(tmp_path):
    from types import SimpleNamespace
    from PIL import Image
    from hotpost import source_visual_queries as visual
    from hotpost.source_text_query_receipts import cached_text_receipt, verify_text_receipt
    captured = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    artifact = next(row for row in captured['artifacts'] if row.get('sha256') ==
        'b32e45bae5f0646a2d9e1b33872098774b1669855a2a7a41d68bb43734a5ba66')
    assert artifact['truncated'] is False
    parent = copy.deepcopy(json.loads(artifact['content']))
    assert parent['queries'] == []
    assert len(parent['search_identity']['required_terms']) == 4
    reference = tmp_path/'reference.mp4'
    reference.write_bytes(b'isolated reference bytes')
    frames = []
    for index in range(len(parent['evidence']['frames'])):
        frame = tmp_path/('frame%d.jpg' % index)
        Image.new('RGB',(16,16),(index,20,30)).save(frame)
        frames.append(frame)
    text = copy.deepcopy(parent['evidence']['text'])
    transcript = {key:text.get(key,'') for key in ('speech','screen_text')}
    parent['evidence'] = visual.binding(reference,frames,text['caption'],transcript,
        search_minimums=parent['evidence']['search_minimums'],
        subject_hint=parent['evidence']['subject_hint'])
    parent['input_sha256'] = visual.digest(parent['evidence'])
    parent['review']['input_sha256'] = parent['input_sha256']
    assert visual.verify(parent) == []
    original_parent = copy.deepcopy(parent)
    job = captured['job']
    owner = dict(task_id=job['task_id'],job_id=job['id'],run_id=job['payload']['run_id'])
    calls = []
    def external_model(settings,instruction,data,**kwargs):
        calls.append(copy.deepcopy(data))
        if 'proposal_sha256' not in data:
            return {'queries':[]}
        return dict(input_sha256=data['input_sha256'],proposal_sha256=data['proposal_sha256'],
            text_search_only=True,core_identity_complete=True,checks=[])
    settings = SimpleNamespace(data_dir=tmp_path)
    receipt = cached_text_receipt(settings,parent,owner,external_model)
    assert len(calls) == 4
    assert 'recovery_feedback' not in calls[0]
    assert calls[2]['recovery_feedback']['original_input_sha256'] == visual.digest(calls[0])
    assert receipt['evidence']['owner'] == owner
    assert verify_text_receipt(receipt,parent) == []
    assert receipt['approved_query_pool']['ready'] is False
    files = {p:p.read_bytes() for p in (tmp_path/'source-text-query-receipts').rglob('*.json')}
    assert len(files) == 6
    def forbidden(*args,**kwargs):
        raise AssertionError('Repeated shortage must not create another model attempt')
    assert cached_text_receipt(settings,parent,owner,forbidden) == receipt
    assert {p:p.read_bytes() for p in files} == files
    assert set((tmp_path/'source-text-query-receipts').rglob('*.json')) == set(files)
    assert parent == original_parent
    assert captured == json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
import pytest
from hotpost.source_visual_queries import digest
from hotpost.source_text_query_receipts import checked_rows


def test_preserved_incident_identity_cannot_be_shortened_to_evade_syntax():
    from hotpost.source_queries import _clean_tiktok_syntax
    from hotpost.source_query_identity import matches_identity
    incident = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    job = incident['job']
    assert job['id'] == 'job-7acdf5827d1d4127'
    assert job['task_id'] == 'work-56d49cbfc5a64c1c'
    assert job['payload']['run_id'] == 'run-a202941b1cda4131'
    assert job['checkpoint']['internal_evidence_wait'] is True
    assert 'planning_preparation' not in job['checkpoint']
    artifact = incident['artifacts'][0]
    assert artifact['sha256'] == '15ab392091ee0574269ab8c082d62720bfc255d3e0548f0eb504b49146d8ba73'
    assert artifact['truncated'] is False
    proposal = json.loads(artifact['content'])['proposal']
    identity = copy.deepcopy(proposal['subject_identity'])
    original = next(q['query'] for q in proposal['queries'] if q['language'] == 'en')
    assert original == 'Dior floral eau de toilette perfume bottle-neck jacquard ribbon'
    assert len(identity['required_terms']) == 4
    assert len(original.split()) == 9
    assert matches_identity(original, identity)
    assert _clean_tiktok_syntax(original) == ''
    shortened = 'Dior eau de toilette perfume'
    assert _clean_tiktok_syntax(shortened) == shortened
    assert not matches_identity(shortened, identity)
    assert incident['job'] == job


def test_translation_extension_preserves_every_original_condition_and_review_binding():
    from hotpost.source_text_query_receipts import reviewed_search_identity
    original = dict(version='core-product-identity-v2', kind='branded',
        product_terms=dict(en=['perfume'],zh=['香水'],ko=['향수']),
        required_terms=[dict(kind='brand',source='caption',quote='Dior',
            terms=dict(en=['Dior'],zh=['Dior'],ko=['디올']))])
    evidence = dict(text={'caption':'Dior 향수'},search_identity=original)
    proposal = dict(search_identity=copy.deepcopy(original))
    proposal['search_identity']['product_terms']['en'].append('fragrance')
    review = dict(input_sha256=digest(evidence),proposal_sha256=digest(proposal),
        identity_aliases_supported=True,subject_identity_supported=True,core_identity_complete=True)
    result = reviewed_search_identity(proposal,review,evidence)
    assert result['required_terms'] == original['required_terms']
    assert result['product_terms']['en'] == ['perfume','fragrance']
    assert evidence['search_identity'] == original
    for mutation in ('remove_condition','replace_product','change_quote','unreviewed'):
        bad = copy.deepcopy(proposal); verdict = copy.deepcopy(review)
        if mutation == 'remove_condition':bad['search_identity']['required_terms'] = []
        elif mutation == 'replace_product':bad['search_identity']['product_terms']['en'] = ['fragrance']
        elif mutation == 'change_quote':bad['search_identity']['required_terms'][0]['quote'] = '향수'
        else:verdict['identity_aliases_supported'] = False
        verdict['proposal_sha256'] = digest(bad)
        with pytest.raises(ValueError):reviewed_search_identity(bad,verdict,evidence)
    changed = copy.deepcopy(review);changed['input_sha256'] = '0'*64
    with pytest.raises(ValueError):reviewed_search_identity(proposal,changed,evidence)


def test_text_checks_do_not_accept_visual_links_or_changed_quotes():
    identity = dict(version='core-product-identity-v2', kind='category',
        product_terms=dict(en=['perfume'], zh=['香水'], ko=['향수']), required_terms=[])
    evidence = dict(text={'caption':'향수 장미'}, search_identity=identity)
    proposal = dict(queries=[dict(id='q', query='rose perfume', language='en',
        text_quotes=[dict(source='caption', quote='향수 장미')])])
    flags = dict(supported=True, central_product=True, short_noun_phrase=True,
        no_unobserved_claims=True, core_identity_preserved=True, quoted_modifiers_supported=True)
    def review(p):
        return dict(input_sha256=digest(evidence), proposal_sha256=digest(p),
            text_search_only=True, core_identity_complete=True, checks=[dict(query_id='q', **flags)])
    rows = checked_rows(proposal, review(proposal), evidence)
    assert len(rows) == 1 and rows[0]['role'] == 'text_product'
    assert 'frame_ids' not in rows[0]
    for field, value in [('frame_ids',['frame-1']), ('text_quotes',[dict(source='caption',quote='invented')])]:
        damaged = copy.deepcopy(proposal);damaged['queries'][0][field] = value
        with pytest.raises(ValueError):checked_rows(damaged, review(damaged), evidence)
    bad = review(proposal);bad['proposal_sha256'] = '0'*64
    with pytest.raises(ValueError):checked_rows(proposal,bad,evidence)
    bad = review(proposal);bad['checks'][0]['quoted_modifiers_supported'] = False
    assert checked_rows(proposal,bad,evidence) == []


@pytest.mark.parametrize('modifier', ['silicone', 'leather', 'cordura', 'cotton', 'down', 'metal'])
def test_unquoted_material_cannot_be_approved_by_model_flags(modifier):
    identity = dict(version='core-product-identity-v2', kind='category',
        product_terms=dict(en=['perfume'], zh=['香水'], ko=['향수']), required_terms=[])
    evidence = dict(text={'caption':'향수 장미'}, search_identity=identity)
    proposal = dict(queries=[dict(id='q', query=modifier+' perfume', language='en',
        text_quotes=[dict(source='caption', quote='향수 장미')])])
    review = dict(input_sha256=digest(evidence), proposal_sha256=digest(proposal),
        text_search_only=True, core_identity_complete=True, checks=[dict(query_id='q',
            supported=True, central_product=True, short_noun_phrase=True,
            no_unobserved_claims=True, core_identity_preserved=True, quoted_modifiers_supported=True)])
    assert checked_rows(proposal, review, evidence) == []
