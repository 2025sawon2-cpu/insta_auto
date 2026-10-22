import copy
import inspect
import json
import os
import textwrap
from pathlib import Path

import pytest
from test_deferred_download_review import fixture
from hotpost.source_pause_receipts import sha
from hotpost.studio_sources import SourceAcquisitionMixin
from hotpost import source_overlay_review as overlay


def test_captured_causal_receipt_resumes_original_entry(tmp_path, monkeypatch):
    incident = copy.deepcopy(json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8')))
    assert incident['job']['error'] == 'Accepted function frame is outside its bound interval'
    artifacts = incident['artifacts']
    artifacts = artifacts.values() if isinstance(artifacts, dict) else artifacts
    cache = next(json.loads(a['content']) for a in artifacts
                 if isinstance(a, dict) and a.get('path') == incident['job']['checkpoint']['source_batch_review']['path'])
    causal = None
    for row in cache['sources'].values():
        receipt = row.get('mask_review') or {}
        for frame in receipt.get('evidence_frames', []):
            stamp = frame.get('source_timestamp')
            windows = receipt.get('intervals', [])
            if isinstance(stamp, (int, float)) and any(w['source_start'] <= stamp < w['source_end'] for w in windows) and any(frame.get('frame_id') in w.get('frame_ids', []) and not w['source_start'] <= stamp < w['source_end'] for w in windows):
                causal = copy.deepcopy(row)
                break
        if causal is not None:
            break
    assert causal is not None, 'Captured incident must supply the actual causal defect'
    h, minimal, job, candidates, manifest, calls, portrait = fixture(tmp_path, monkeypatch)
    state = copy.deepcopy(incident['task'])
    state['sources'] = copy.deepcopy(incident['task'].get('sources', []))
    assert state['sources'] == []
    isolated_manifest = json.loads(manifest.read_text('utf8'))
    isolated_manifest['shortcode'] = state['shortcode']
    manifest.write_text(json.dumps(isolated_manifest, ensure_ascii=False), encoding='utf8')
    state['reference_video'] = minimal['reference_video']
    # A minimal local receipt preserves the deferred route, original identity,
    # source exclusions and the causal cached review. Historical searches cannot
    # affect accepted_interval_frames after this local batch has been selected.
    state['source_acquisition'] = copy.deepcopy(minimal['source_acquisition'])
    state['source_acquisition']['rounds'][0].update(run_id=state['run_id'], job_id=incident['job']['id'])
    job = copy.deepcopy(incident['job'])
    job['checkpoint'] = {}
    assert job['payload']['run_id'] == state['run_id']
    from test_deferred_download_review import MemoryStore
    h.store = MemoryStore(state)
    native_overlay = overlay.review_source_overlays
    original_frames = overlay.accepted_interval_frames
    bad_sha = candidates[3]['file_sha256']
    preserved = []
    def external_overlay(settings, source, folder):
        if source['sha256'] != bad_sha:
            return native_overlay(settings, source, folder)
        value = copy.deepcopy(causal)
        value.update(path=source['path'], sha256=source['sha256'], origin_url=source['origin_url'],
                     deferred_download_origin=source['deferred_download_origin'], functional_review=None,
                     relevance_review_required=True)
        value['mask_review']['source_sha256'] = source['sha256']
        for index, frame in enumerate(value['mask_review']['evidence_frames']):
            path = tmp_path / ('captured-frame-%s.png' % index)
            path.write_bytes(('isolated frame %s' % index).encode())
            frame.update(path=str(path), sha256=sha(path))
        preserved.append(copy.deepcopy(value['mask_review']))
        return value
    monkeypatch.setattr(overlay, 'review_source_overlays', external_overlay)
    # Execute the old production method through the same public entry point,
    # removing only this repair's exception boundary in an isolated function.
    import hotpost.studio_sources as module
    repaired = SourceAcquisitionMixin._review_source_records
    code = textwrap.dedent(inspect.getsource(repaired))
    start = code.index('                try:\n                    candidate_frames = accepted_interval_frames(source)')
    end = code.index('            else:\n                candidate_frames = extract_frames', start)
    old_code = code[:start] + '                candidate_frames = accepted_interval_frames(source)\n' + code[end:]
    namespace = dict(vars(module))
    exec(old_code, namespace)
    before_state, before_job = copy.deepcopy(state), copy.deepcopy(job)
    monkeypatch.setattr(SourceAcquisitionMixin, '_review_source_records', namespace['_review_source_records'])
    with pytest.raises(ValueError, match='outside its bound interval'):
        h._collect_sources(state, job)
    monkeypatch.setattr(SourceAcquisitionMixin, '_review_source_records', repaired)
    state, job = before_state, before_job
    h.store = MemoryStore(state)
    result = h._collect_sources(state, job)
    assert (state['id'], job['id'], job['payload']['run_id']) == (incident['task']['id'], incident['job']['id'], incident['task']['run_id'])
    assert result['local_deferred_review'] and result['review_completion']['deferred_sources'] == 0
    bad = next(s for s in result['sources'] if s['sha256'] == bad_sha)
    assert bad['mask_review'] == preserved[-1]
    assert bad['editing_eligible'] is False
    assert 'outside its bound interval' in bad['overlay_review_error']
    assert ('functional', bad_sha) not in calls
    saved = job['checkpoint']['deferred_source_review']
    assert sha(saved['path']) == saved['sha256']
    persisted = json.loads(Path(saved['path']).read_text('utf8'))['sources'][bad_sha]
    assert persisted['review_outcome'] == bad['review_outcome']
    assert persisted['editing_eligible'] is False
    assert any(s.get('presentation_review', {}).get('usable') for s in result['sources'] if s['sha256'] != bad_sha)
    job['checkpoint'] = copy.deepcopy(h.store.checkpoints[-1])
    again = h._collect_sources(state, job)
    assert next(s for s in again['sources'] if s['sha256'] == bad_sha)['editing_eligible'] is False
    changed = copy.deepcopy(bad)
    changed['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='source changed'):
        original_frames(changed)
