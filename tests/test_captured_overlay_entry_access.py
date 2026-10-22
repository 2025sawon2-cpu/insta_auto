import copy
import hashlib
import inspect
import json
import os
import textwrap
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost import scene_requirements, source_finder, source_access_preflight
from hotpost.source_overlay_review import POLICY
from hotpost.source_preparation import payload_key
from test_source_pause_history import Harness, MemoryStore


def test_captured_settled_failure_reaches_real_access_from_collect(tmp_path, monkeypatch):
    original = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    fixture = copy.deepcopy(original)
    settings = Settings(data_dir=tmp_path)
    settings.source_browser_search = True
    rows = fixture['artifacts']
    if isinstance(rows, dict):
        rows = [dict(v, path=k) if isinstance(v, dict) else dict(path=k, content=v) for k, v in rows.items()]
    documents = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get('content'), str):
            try:
                documents[row['path']] = json.loads(row['content'])
            except ValueError:
                pass
    state, job = fixture['task'], fixture['job']
    manifest_raw = state.get('source_search_manifest_path') or state['manifest_path']
    assert manifest_raw in documents, 'Captured existing manifest is required'
    source_root = PureWindowsPath(manifest_raw).parent
    local_root = settings.source_dir / source_root.name
    paths = {}
    def pathmap(value):
        if not isinstance(value, str) or not PureWindowsPath(value).is_absolute():
            return value
        if value not in paths:
            p = PureWindowsPath(value)
            try:
                target = local_root.joinpath(*p.relative_to(source_root).parts)
            except ValueError:
                target = tmp_path / 'other' / hashlib.sha256(value.encode()).hexdigest()[:16] / p.name
            paths[value] = str(target.resolve())
        return paths[value]
    def walk(value, transform):
        if isinstance(value, dict):
            return {transform(k): walk(v, transform) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v, transform) for v in value]
        return transform(value) if isinstance(value, str) else value
    state, job = walk(state, pathmap), walk(job, pathmap)
    documents = {pathmap(p): walk(v, pathmap) for p, v in documents.items()}
    replacements = {}
    def media(raw, old_sha=None, content=None):
        p = Path(raw)
        assert p.is_relative_to(tmp_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.is_file():
            p.write_bytes(content or ('isolated media ' + str(p)).encode())
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if old_sha:
            replacements[old_sha] = digest
        return p
    def standins(value):
        if isinstance(value, list):
            for row in value:
                standins(row)
        elif isinstance(value, dict):
            for field, hashfield in [('path', 'sha256'), ('source_path', 'source_sha256')]:
                raw, digest = value.get(field), value.get(hashfield)
                if isinstance(raw, str) and PureWindowsPath(raw).is_absolute() and raw not in documents and isinstance(digest, str) and len(digest) == 64:
                    media(raw, digest)
            for row in value.values():
                standins(row)
    standins(state)
    for document in documents.values():
        standins(document)
    manifest = documents[pathmap(manifest_raw)]
    reference = media(state['reference_video'], content=b'isolated preserved reference')
    for document in documents.values():
        scope = document.get('search_context') if isinstance(document, dict) else None
        if scope and scope.get('reference_sha256'):
            replacements[scope['reference_sha256']] = hashlib.sha256(reference.read_bytes()).hexdigest()
    for raw, document in documents.items():
        if not isinstance(document, dict):
            continue
        if document.get('reference_frames'):
            parent = Path(raw).parent
            media(parent / 'reference.mp4', content=reference.read_bytes())
            media(parent / 'reference_contact_sheet.jpg')
            for frame in document['reference_frames']:
                media(parent / frame)
        for candidate in document.get('candidates', []):
            if candidate.get('downloaded_file'):
                media(Path(raw).parent / candidate['downloaded_file'], candidate.get('file_sha256'))
    replace = lambda value: replacements.get(value, value)
    state, job = walk(state, replace), walk(job, replace)
    documents = {p: walk(v, replace) for p, v in documents.items()}
    def write(raw, value):
        p = Path(raw)
        assert p.is_relative_to(tmp_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value, ensure_ascii=False), 'utf8')
    # Rebind only isolated media receipts. Original fixture stays read-only.
    for raw, document in documents.items():
        if isinstance(document, dict) and 'payload_sha256' in document:
            document['payload_sha256'] = payload_key(document)
        write(raw, document)
    for raw, document in documents.items():
        if isinstance(document, dict) and document.get('preparation_bundle_path') in documents:
            document['preparation_bundle_sha256'] = hashlib.sha256(Path(document['preparation_bundle_path']).read_bytes()).hexdigest()
            write(raw, document)
    failures = [s for s in state['sources'] if s.get('overlay_review_error') and s.get('overlay_review_attempted_policy') == POLICY and s.get('overlay_review_attempted_sha256') == s.get('sha256') and s.get('mask_review') and s.get('reviewed_intervals')]
    assert failures
    assert all(s['editing_eligible'] is False for s in failures)
    before = copy.deepcopy(failures)
    for source in failures:
        assert scene_requirements.clear_cached_review_errors(source) is False
    assert failures == before
    # Reconstruct only the old causal condition; retain transient handling.
    code = textwrap.dedent(inspect.getsource(scene_requirements.clear_cached_review_errors))
    assert 'not settled_overlay_failure and ' in code
    namespace = dict(vars(scene_requirements))
    exec(code.replace('not settled_overlay_failure and ', '', 1), namespace)
    old_source = copy.deepcopy(failures[0])
    assert namespace['clear_cached_review_errors'](old_source)
    assert 'overlay_review_error' not in old_source
    assert Path(state.get('source_search_manifest_path') or state['manifest_path']).is_file()
    caption = manifest.get('caption', '')
    transcript = copy.deepcopy(manifest.get('transcript') or {})
    monkeypatch.setattr(source_finder, '_post', lambda *a: SimpleNamespace(caption=caption))
    monkeypatch.setattr(source_finder, '_transcript_evidence', lambda *a: copy.deepcopy(transcript))
    h = Harness()
    h.settings = settings
    h.store = MemoryStore(state)
    observed = []
    def external_observation(settings, providers):
        observed.append(list(providers))
        return [dict(provider=p, status='login_required', reason='isolated external login observation') for p in providers]
    monkeypatch.setattr(source_access_preflight, 'current_routes', external_observation)
    # Actual collection, restoration, deferred selection, inventory routing,
    # preparation checks and check_access all run without replacement.
    with pytest.raises(source_access_preflight.SourceAccessWaiting):
        h._collect_source_attempt(state, job)
    assert len(observed) == 1, 'Must pass preserved preparation and reach actual access observation'
    access = job['checkpoint']['source_access_preflight']
    assert access['ready_routes'] == []
    assert all(r['status'] == 'login_required' for r in access['observations'])
    current = h.store.get(state['id'])
    for source in before:
        retained = next(s for s in current['sources'] if s['id'] == source['id'])
        assert retained == source
        assert retained['editing_eligible'] is False
    assert (state['id'], job['id'], state['run_id'], job['payload']) == (original['task']['id'], original['job']['id'], original['task']['run_id'], original['job']['payload'])
    assert original == json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
