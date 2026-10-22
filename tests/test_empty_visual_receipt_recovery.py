import copy
import json
import os
from pathlib import Path

from hotpost import source_visual_queries as visual
from hotpost.config import Settings


def test_captured_empty_receipt_requests_fresh_independent_evidence(tmp_path):
    captured = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    incident = copy.deepcopy(captured)
    artifacts = incident['artifacts']
    if isinstance(artifacts, dict):
        artifacts = [dict(v, path=k) if isinstance(v, dict) else dict(path=k, content=v) for k, v in artifacts.items()]
    manifests = [json.loads(r.get('content', r.get('text'))) for r in artifacts
                 if r['path'].replace(chr(92), '/').endswith('/manifest.json')]
    manifest = next(m for m in manifests if (m.get('product_evidence') or {}).get('visual_query_evidence'))
    receipt = copy.deepcopy(manifest['product_evidence']['visual_query_evidence'])
    assert receipt['queries'] == []
    evidence = receipt['evidence']
    reference = tmp_path / 'reference.mp4'
    reference.write_bytes(b'isolated reference')
    from PIL import Image
    frames = []
    for i, row in enumerate(evidence['frames']):
        p = tmp_path / ('frame%d.jpg' % i)
        Image.new('RGB', (16, 16), (i, 20, 30)).save(p)
        frames.append(p)
    text = evidence['text']
    rebound = visual.binding(reference, frames, text['caption'], text,
        search_minimums=evidence['search_minimums'], subject_hint=evidence['subject_hint'])
    receipt['evidence'] = rebound
    key = visual.digest(rebound)
    receipt['input_sha256'] = key
    receipt['review']['input_sha256'] = key
    assert visual.verify(receipt) == []
    settings = Settings(data_dir=tmp_path)
    root = tmp_path / 'source-visual-queries' / key
    root.mkdir(parents=True)
    saved = root / 'receipt.json'
    saved.write_text(json.dumps(receipt, ensure_ascii=False), 'utf8')
    before = saved.read_bytes()
    calls = []
    proposal = copy.deepcopy(receipt['proposal'])
    observation = proposal['observations'][0]
    assert observation['frame_ids']
    assert proposal['queries']
    for q in proposal['queries']:
        q['observation_ids'] = [observation['id']]
        q['frame_ids'] = list(observation['frame_ids'])
    def external_model(settings, instruction, data, **kwargs):
        calls.append(copy.deepcopy(data))
        if 'proposal_sha256' not in data:
            return copy.deepcopy(proposal)
        return dict(input_sha256=data['input_sha256'],
            proposal_sha256=data['proposal_sha256'],
            subject_identity_supported=True, core_identity_complete=True,
            checks=[dict(query_id=q['id'], supported=True, central_product=True,
                short_noun_phrase=True, no_unobserved_claims=True,
                core_identity_preserved=True, reason='Isolated independently bound external response')
                for q in proposal['queries']])
    owner = dict(task_id=incident['task']['id'], job_id=incident['job']['id'],
                 run_id=incident['task']['run_id'])
    result = visual.cached_visual_queries(settings, reference, frames, text['caption'], text,
        external_model, search_minimums=evidence['search_minimums'],
        subject_hint=evidence['subject_hint'], owner_binding=owner)
    assert len(calls) == 2
    assert visual.verify(result)
    assert saved.read_bytes() == before
    assert result['approved_query_pool']['ready'] is False
    # A nonempty independently checked pool is still insufficient preparation
    # when the preserved policy requires five distinct nouns per language.
    from hotpost.source_policy import run_policy
    from hotpost.source_diversity import acquisition_policy
    from hotpost.source_preparation import reusable_query_contract
    policy = acquisition_policy(incident['task'], run_policy(incident['task']))
    plan = visual.apply_visual_queries({
        'source_policy': policy,
        'search_minimums': policy['search_minimums'],
        'query_evidence': copy.deepcopy(text),
        'query_details': []}, result,
        reference_sha256=rebound['reference_sha256'])
    assert visual.plan_queries(plan)
    assert plan['minimum_query_plan_ready'] is False
    assert reusable_query_contract(plan, policy, evidence['subject_hint'], {}) is False
    # Preserve a valid but insufficient receipt as the primary cache. The old
    # empty-only branch returned it without requesting fresh external evidence.
    saved.write_text(json.dumps(result, ensure_ascii=False), 'utf8')
    partial_before = saved.read_bytes()
    calls.clear()
    partial_key = visual.digest(result)
    recovered = visual.cached_visual_queries(settings, reference, frames,
        text['caption'], text, external_model,
        search_minimums=evidence['search_minimums'],
        subject_hint=evidence['subject_hint'], owner_binding=owner)
    assert len(calls) == 2
    assert visual.verify(recovered)
    assert saved.read_bytes() == partial_before
    assert (root / ('empty-recovery-' + partial_key) / 'receipt.json').is_file()
    # An insufficient fresh response remains insufficient; never manufacture
    # quota readiness or recurse indefinitely to obtain an approval.
    assert recovered['approved_query_pool']['ready'] is False
    calls.clear()
    assert visual.cached_visual_queries(settings, reference, frames,
        text['caption'], text, external_model,
        search_minimums=evidence['search_minimums'],
        subject_hint=evidence['subject_hint'], owner_binding=owner) == recovered
    assert calls == []
    assert owner['job_id'] == captured['job']['id']
    assert incident['task']['source_acquisition']['hold'] == captured['task']['source_acquisition']['hold']
    assert captured == json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
