import copy
import hashlib
import inspect
import json
import os
import textwrap
from pathlib import Path

import pytest

from hotpost import source_finder, source_presentation as sp
from test_source_pause_history import Harness, MemoryStore
from hotpost.config import Settings


class SearchReached(Exception):
    pass


class JsonSnapshotStore(MemoryStore):
    @staticmethod
    def clone(value):
        return json.loads(json.dumps(value, ensure_ascii=False))

    def __init__(self, state):
        self.state = self.clone(state)
        self.checkpoints = []
        self.stale = False
        assert self.state == state
        assert self.state is not state

    def change(self, task, fn, **kwargs):
        from hotpost.studio_store import StaleClaim
        if self.stale:
            raise StaleClaim('old worker')
        assert task == self.state['id']
        fn(self.state, None)
        return self.clone(self.state)

    def get(self, task):
        assert task == self.state['id']
        return self.clone(self.state)


def isolated_incident(tmp_path):
    original = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    fixture = copy.deepcopy(original)
    paths = {}
    hashes = {}
    def visit(value):
        if isinstance(value, dict):
            return {k: visit(v) for k, v in value.items()}
        if isinstance(value, list):
            return [visit(v) for v in value]
        if isinstance(value, str) and len(value) > 2 and value[1:3] == ':\\':
            if value not in paths:
                suffix = Path(value.replace('\\', '/')).suffix
                paths[value] = str(tmp_path / ('asset-' + str(len(paths)) + suffix))
            return paths[value]
        return value
    fixture = visit(fixture)
    def materialize(value):
        if isinstance(value, dict):
            path = value.get('path')
            if path in paths.values():
                target = Path(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(value.get('content'), str):
                    target.write_text(value['content'], encoding='utf8')
                elif not target.exists():
                    target.write_bytes(('isolated media ' + path).encode())
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                for key in ('sha256', 'file_sha256', 'source_sha256'):
                    old = value.get(key)
                    if isinstance(old, str) and len(old) == 64:
                        hashes[old] = digest
            for child in value.values():
                materialize(child)
        elif isinstance(value, list):
            for child in value:
                materialize(child)
    materialize(fixture)
    reference = Path(fixture['task']['reference_video'])
    reference.write_bytes(b'isolated reference footage')
    # Preserve the incident's reference-to-review binding in this isolated copy.
    hashes['3cb721c0a58bef3b070f2e719bfe769e294271b64b037d186d0dd19aa5470e41'] = hashlib.sha256(reference.read_bytes()).hexdigest()
    for source in fixture['task']['sources']:
        target = Path(source['path'])
        if not target.exists():
            target.write_bytes(source['id'].encode())
        hashes[source['sha256']] = hashlib.sha256(target.read_bytes()).hexdigest()
    def rebind(value):
        if isinstance(value, dict):
            return {hashes.get(k, k): rebind(v) for k, v in value.items()}
        if isinstance(value, list):
            return [rebind(v) for v in value]
        if isinstance(value, str):
            return hashes.get(value, value)
        return value
    return original, rebind(fixture)


@pytest.mark.parametrize('access_status', ['ready', 'login_required'])
@pytest.mark.parametrize('legacy', [True, False])
def test_original_job_collection_entry(tmp_path, monkeypatch, legacy, access_status):
    original, fixture = isolated_incident(tmp_path)
    state, job = fixture['task'], fixture['job']
    assert state['id'] == 'work-33fa1ca3d69641b9'
    assert job['id'] == 'job-73ccb8061c334e3a'
    assert state['run_id'] == job['payload']['run_id'] == original['task']['run_id']
    h = Harness()
    h.settings = Settings(data_dir=tmp_path)
    h.store = JsonSnapshotStore(state)
    h.folder(state['id']).mkdir(parents=True, exist_ok=True)
    from types import SimpleNamespace
    from hotpost import source_access_preflight
    def post_response(settings, shortcode):
        assert shortcode == original['task']['shortcode']
        assert settings.data_dir == tmp_path
        return SimpleNamespace(caption=state['original_text'], shortcode=shortcode)
    def transcript_response(settings, shortcode):
        assert shortcode == original['task']['shortcode']
        return {'speech':state['original_text'], 'screen_text':''}
    monkeypatch.setattr(source_finder, '_post', post_response)
    monkeypatch.setattr(source_finder, '_transcript_evidence', transcript_response)
    def browser_observation(settings, providers):
        assert 'tiktok' in providers
        return [{'provider':'tiktok', 'status':access_status,
                 'query':'', 'attempted':False,
                 'reason':'isolated external browser observation'}]
    monkeypatch.setattr(source_access_preflight, 'current_routes', browser_observation)
    if legacy:
        code = textwrap.dedent(inspect.getsource(sp.needs_pending_presentation_review))
        needle = "review.get('policy') in {REVIEW_POLICY, core_policy}"
        assert needle in code
        namespace = dict(sp.__dict__)
        exec(compile(code.replace(needle, "review.get('policy') == REVIEW_POLICY"), '<old-selector>', 'exec'), namespace)
        monkeypatch.setattr(sp, 'needs_pending_presentation_review', namespace['needs_pending_presentation_review'])
    denied = [s for s in state['sources'] if s.get('editing_eligible') is False
              and (s.get('functional_review') or {}).get('same_core_function') is False
              and (s.get('functional_review') or {}).get('context_usable') is False]
    assert denied
    for source in denied:
        assert sp.needs_pending_presentation_review(source) is legacy
    searches = []
    def find(settings, shortcode, progress, **kwargs):
        progress.check_cancel()
        assert shortcode == state['shortcode']
        assert kwargs['search_round'] == job['payload']['round']
        assert kwargs['search_context']['run_id'] == state['run_id']
        searches.append(kwargs)
        raise SearchReached
    monkeypatch.setattr(source_finder, 'find_sources', find)
    # Only external decoding/model/search I/O is replaced. All incident history,
    # production collection routing and internal validation remain real.
    def extract(path, output, **kwargs):
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        frames = []
        for i in range(3):
            frame = output / ('frame_%03d.jpg' % i)
            frame.write_bytes(b'isolated decoded frame')
            frames.append(frame)
        return frames
    monkeypatch.setattr(source_finder, 'extract_frames', extract)
    monkeypatch.setattr(source_finder, 'probe_video', lambda path: {'duration': 20., 'width': 720, 'height': 1280})
    from hotpost import visual_media, script_rewriter
    monkeypatch.setattr(visual_media, 'frame_inline_data', lambda path: {'mimeType':'image/jpeg', 'data':'aXNvbGF0ZWQ='})
    monkeypatch.setattr(visual_media, 'review_frame_data', lambda path: {'mimeType':'image/jpeg', 'data':'aXNvbGF0ZWQ='})
    def generate(settings, instruction, payload, **kwargs):
        return {'same_core_function':False, 'context_usable':False,
                'featured_product_identity':False, 'identity_evidence':['isolated unrelated candidate'],
                'observed_actions':['isolated unrelated activity'],
                'context_usage_limits':[], 'differences':['different use'],
                'reason':'isolated fresh external rejection'}
    monkeypatch.setattr(script_rewriter, '_generate', generate)
    reference_sha = hashlib.sha256(Path(state['reference_video']).read_bytes()).hexdigest()
    (h.folder(state['id']) / ('source-reference-overview-v2-' + reference_sha[:16] + '.jpg')).write_bytes(b'isolated overview')
    if legacy:
        result = h._collect_source_attempt(state, job)
        assert result['visual_review_only'] is True
        assert searches == []
    elif access_status == 'login_required':
        with pytest.raises(source_access_preflight.SourceAccessWaiting):
            h._collect_source_attempt(state, job)
        assert searches == []
        observations = job['checkpoint']['source_access_preflight']['observations']
        assert observations[0]['status'] == 'login_required'
        assert job['checkpoint']['source_access_preflight']['ready_routes'] == []
    else:
        with pytest.raises(SearchReached):
            h._collect_source_attempt(state, job)
        assert len(searches) == 1
        assert job['checkpoint']['source_access_preflight']['ready_routes'] == ['tiktok']
    assert job['id'] == original['job']['id']
    assert state['run_id'] == original['task']['run_id']
    assert original == json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))


@pytest.mark.parametrize('damage', ['hash', 'evidence', 'policy', 'manual', 'file'])
def test_core_rejection_still_requires_bound_evidence(tmp_path, damage):
    from test_source_rejected_local_pending import rejected
    from hotpost.source_core_priority import REVIEW_POLICY
    source = rejected(tmp_path)
    source['functional_review']['policy'] = REVIEW_POLICY
    assert sp.needs_pending_presentation_review(source) is False
    if damage == 'hash': source['functional_review']['source_sha256'] = '0' * 64
    if damage == 'evidence': source['functional_review']['evidence_frames'] = []
    if damage == 'policy': source['functional_review']['policy'] = 'obsolete'
    if damage == 'manual': source['manual_usage_review'] = {'editing_eligible':True}
    if damage == 'file': Path(source['path']).write_bytes(b'changed media')
    assert sp.needs_pending_presentation_review(source) is True
