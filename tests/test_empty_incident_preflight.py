import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

from hotpost import source_preparation as preparation
from hotpost import source_finder as finder
from hotpost.config import Settings
from hotpost.source_policy import run_policy
from hotpost.source_diversity import acquisition_policy
from hotpost.source_visual_queries import search_contract


def test_preserved_empty_plan_requests_replanning(tmp_path, monkeypatch):
    captured = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    incident = copy.deepcopy(captured)
    state, job = incident['task'], incident['job']
    assert job['task_id'] == state['id']
    assert job['payload']['run_id'] == state['run_id']
    hold = copy.deepcopy(state['source_acquisition']['hold'])
    artifacts = incident['artifacts']
    if isinstance(artifacts, dict):
        artifacts = [dict(v, path=k) if isinstance(v, dict) else {'path': k, 'content': v} for k, v in artifacts.items()]
    manifests = []
    for row in artifacts:
        if row.get('path', '').replace(chr(92), '/').endswith('/manifest.json'):
            raw = row.get('content', row.get('text'))
            value = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(value, dict) and value.get('product_evidence', {}).get('visual_query_evidence', {}).get('queries') == []:
                manifests.append(value)
    assert manifests
    saved = manifests[-1]
    plan = copy.deepcopy(saved['product_evidence'])
    plan['query_details'] = copy.deepcopy(saved.get('query_details', []))
    assert plan['visual_query_evidence']['queries'] == []
    assert plan['minimum_query_plan_ready'] is False
    settings = Settings(data_dir=tmp_path)
    policy = acquisition_policy(state, run_policy(state))
    evidence = plan['visual_query_evidence']['evidence']
    assert all(evidence.get(k) == v for k, v in search_contract(policy['search_minimums']).items())
    assert evidence['subject_hint'] == state['product']
    # These exact causal fields made the old current-contract branch return
    # True without reading media or checking the empty dispatch pool.
    caption = saved['caption']
    transcript = copy.deepcopy(evidence['text'])
    transcript.setdefault('reference_kind', 'mixed')
    reference = tmp_path / 'reference.mp4'
    reference.write_bytes(b'isolated reference stand-in')
    frame = tmp_path / 'frame.jpg'
    frame.write_bytes(b'isolated frame stand-in')
    sheet = tmp_path / 'sheet.jpg'
    sheet.write_bytes(b'isolated sheet stand-in')
    state['reference_video'] = str(reference)
    # Original receipts remain read-only. Only the deep-copy paths are remapped.
    state['source_acquisition']['rounds'] = []
    state.pop('source_search_manifest_path', None)
    path = preparation.acquisition_bundle_path(settings, state['shortcode'], caption, transcript, policy, state['product'])
    preparation.save_bundle(path, caption, transcript, reference, [frame], sheet, query_plan=plan, transcript=transcript)
    before = path.read_bytes()
    monkeypatch.setattr(finder, '_post', lambda *a: SimpleNamespace(caption=caption))
    monkeypatch.setattr(finder, '_transcript_evidence', lambda *a: copy.deepcopy(transcript))
    result, frames = preparation.preflight_preparation(settings, state, job)
    assert result is None
    assert frames == [frame]
    assert path.read_bytes() == before
    assert state['source_acquisition']['hold'] == hold
    assert job == captured['job']
    assert captured == json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))


def test_replanning_save_preserves_accepted_bundle(tmp_path):
    reference=tmp_path/'reference.mp4'
    frame=tmp_path/'frame.jpg'
    sheet=tmp_path/'sheet.jpg'
    for path in (reference,frame,sheet):
        path.write_bytes(path.name.encode())
    caption='captured caption'
    transcript={'speech':'perfume','reference_kind':'mixed'}
    original=tmp_path/'accepted-acquisition.json'
    preparation.save_bundle(original,caption,transcript,reference,[frame],sheet,
        transcript=transcript,query_plan={'query_details':[]})
    before=original.read_bytes()
    plan={'query_details':[{'query':'perfume','language':'en'}]}
    replacement=preparation.replanning_bundle_path(original,plan)
    assert replacement != original
    assert len(replacement.stem) == len(original.stem) + len('-replan-') + 16
    assert len(preparation.payload_key({'query_plan':plan})) == 64
    assert replacement == preparation.replanning_bundle_path(original,plan)
    assert replacement != preparation.replanning_bundle_path(original,{'query_details':[]})
    preparation.save_bundle(replacement,caption,transcript,reference,[frame],sheet,
        transcript=transcript,query_plan=plan)
    assert original.read_bytes() == before
    assert preparation.load_bundle(replacement,caption,transcript)['query_plan'] == plan
    assert preparation.load_bundle(original,caption,transcript)['query_plan']['query_details'] == []
