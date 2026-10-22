"""Actual native reader boundary; diagnostic only, never production approval."""
import copy
import json
import os
from pathlib import Path
from contextlib import nullcontext
from types import SimpleNamespace
from urllib.parse import urlencode
from hotpost.config import Settings
from hotpost import source_browser_runtime as browser
from hotpost.source_parser_recovery import read_response


def test_preserved_query_receives_native_event(tmp_path, monkeypatch):
    original = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    incident = copy.deepcopy(original)
    task, job = incident['task'], incident['job']
    assert task['id'] == job['task_id']
    assert task['run_id'] == job['payload']['run_id']
    assert job['id'] == 'job-30789cffdc5c4d21'
    readiness = job['checkpoint']['parser_repair_context']['observations'][0]['readiness']
    query = readiness['query']
    settings = Settings(data_dir=tmp_path, source_browser_search=True,
                        source_browser_existing_window_only=True)
    listeners = []
    events = []
    class Element:
        def inner_text(self, **kwargs): return 'Wallpaper repair search results'
        def count(self): return 0
        def is_visible(self, **kwargs): return False
        def all(self): return []
        @property
        def first(self): return self
    class Page:
        url = 'https://www.tiktok.com/search?' + urlencode({'q': query})
        def locator(self, *args, **kwargs): return Element()
        def get_by_role(self, *args, **kwargs): return Element()
        def get_by_text(self, *args, **kwargs): return Element()
        def evaluate(self, *args, **kwargs): return False
        def requests(self): return []
        def on(self, event, callback):
            assert event == 'response'
            listeners.append(callback)
        def remove_listener(self, event, callback):
            assert event == 'response'
            listeners.remove(callback)
        def wait_for_timeout(self, milliseconds):
            assert milliseconds == 250
            if not events:
                events.append(query)
                response = SimpleNamespace(status=200,
                    url='https://www.tiktok.com/api/search/item/full/?' + urlencode({'keyword':query}),
                    json=lambda: {'status_code':0,'item_list':[{'id':'123456789',
                        'author':{'uniqueId':'isolated_fixture'},'desc':'isolated response',
                        'video':{'width':720,'height':1280,'duration':12},'stats':{}}]})
                for callback in list(listeners): callback(response)
    page = Page()
    monkeypatch.setattr(browser, 'browser_lease', lambda settings: nullcontext())
    monkeypatch.setattr(browser, 'attach_browser', lambda pw, settings: object())
    monkeypatch.setattr(browser, 'existing_page', lambda context, settings, provider: page)
    monkeypatch.setattr('playwright.sync_api.sync_playwright', lambda: nullcontext(object()))
    response = read_response(settings, query)
    assert response['http_status'] == 200
    assert response['page_url'] == page.url
    assert response['observation_started_at'] <= response['received_at']
    assert events == [query]
    assert listeners == []
    assert incident == original

    from hotpost.studio_store import StudioStore
    from hotpost.source_parser_recovery import recover_response
    from hotpost.source_search.readiness import readiness_record
    # The immutable incident remains untouched. Only its isolated copy runs.
    store = StudioStore(tmp_path / 'isolated-store')
    job['status'] = 'running'
    job['claim_token'] = job['checkpoint']['_claim_token']
    with store.transaction() as db:
        db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)',
            (task['id'], task['shortcode'], task['revision'], json.dumps(task), 1))
        db.execute('INSERT INTO jobs(id,task_id,kind,key,payload,status,checkpoint,error,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (job['id'],job['task_id'],job['kind'],job['id'],json.dumps(job['payload']),
             'running',json.dumps(job['checkpoint']),'',1,1))
    saved_path = tmp_path / 'search_readiness' / 'tiktok.json'
    saved_path.parent.mkdir(parents=True, exist_ok=True)
    saved_path.write_text(json.dumps(readiness), encoding='utf8')
    events.clear()
    matching_page_url = page.url
    page.url = 'https://www.tiktok.com/search?' + urlencode({'q': query + ' unrelated'})
    assert recover_response(settings, store, task, job) is False
    failed_receipt = copy.deepcopy(job['checkpoint']['parser_response_recovery'])
    assert failed_receipt['status'] == 'unavailable'
    assert failed_receipt['observation_reason'] == 'owned_page_query_mismatch'
    assert failed_receipt['job_id'] == original['job']['id']
    assert failed_receipt['grants_media_approval'] is False
    assert readiness_record(tmp_path, 'tiktok') == readiness
    with store.connect() as db:
        failed_checkpoint = json.loads(db.execute(
            'SELECT checkpoint FROM jobs WHERE id=?', (job['id'],)).fetchone()[0])
    assert failed_checkpoint['parser_response_recovery'] == failed_receipt
    assert events == []
    page.url = matching_page_url
    assert recover_response(settings, store, task, job) is True
    receipt = job['checkpoint']['parser_response_recovery']
    assert receipt['status'] == 'response_validated'
    assert receipt['task_id'] == original['task']['id']
    assert receipt['job_id'] == original['job']['id']
    assert receipt['run_id'] == original['task']['run_id']
    assert receipt['previous_readiness'] == readiness
    assert receipt['grants_media_approval'] is False
    assert receipt['query_submitted'] is False
    with store.connect() as db:
        persisted = json.loads(db.execute('SELECT checkpoint FROM jobs WHERE id=?',
            (job['id'],)).fetchone()[0])
    assert persisted['parser_response_recovery'] == receipt
    assert readiness_record(tmp_path, 'tiktok')['recovery'] == receipt
    assert store.get(task['id'])['sources'] == original['task']['sources']
    assert store.get(task['id'])['daily_quality'] == original['task']['daily_quality']
    assert listeners == []

    from hotpost.source_access_preflight import check_access, SourceAccessWaiting
    import pytest
    # Preserve the queued incident's old context, while external saved readiness
    # changes. Never copy the old value back to obtain a successful recovery.
    job['checkpoint'] = copy.deepcopy(original['job']['checkpoint'])
    job['claim_token'] = job['checkpoint']['_claim_token']
    changed = copy.deepcopy(readiness)
    changed['at'] = 1792477701.4271672
    saved_path.write_text(json.dumps(changed), encoding='utf8')
    store.checkpoint(job, job['checkpoint'])
    events.clear()
    profile = settings.source_browser_profile_dir
    profile.mkdir(parents=True, exist_ok=True)
    (profile / 'hotpost-live-session-v1').write_text('isolated', encoding='utf8')
    context = SimpleNamespace(pages=[page])
    pw = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=lambda *a, **k:
        SimpleNamespace(contexts=[context])))
    monkeypatch.setattr('playwright.sync_api.sync_playwright', lambda: nullcontext(pw))
    monkeypatch.setattr(browser, 'endpoint', lambda settings: 'http://isolated.invalid')
    monkeypatch.setattr(browser, 'attach_browser', lambda *a: context)
    def existing(context, settings, provider):
        if provider == 'tiktok': return page
        raise LookupError('tab_missing')
    monkeypatch.setattr(browser, 'existing_page', existing)
    # The immutable task keeps no_progress_rounds and every access/quality hold.
    assert store.get(task['id'])['source_acquisition']['no_progress_rounds'] > 0
    assert recover_response(settings, store, task, job) is False
    assert events == [] and readiness_record(tmp_path, 'tiktok') == changed
    with pytest.raises(SourceAccessWaiting):
        check_access(settings, store.get(task['id']), job)
    current = job['checkpoint']['parser_repair_context']['observations'][0]
    assert current['readiness'] == changed
    assert current['manual_gate_active'] is False
    assert recover_response(settings, store, task, job) is True
    assert check_access(settings, store.get(task['id']), job) == ['tiktok']
    assert job['checkpoint']['parser_response_recovery']['previous_readiness'] == changed
    assert job['checkpoint']['parser_response_recovery']['job_id'] == original['job']['id']
    assert job['checkpoint']['parser_response_recovery']['grants_media_approval'] is False
    assert readiness_record(tmp_path, 'tiktok')['previous_failure'] == changed
    assert store.get(task['id'])['sources'] == original['task']['sources']
    assert store.get(task['id'])['daily_quality'] == original['task']['daily_quality']
    assert listeners == []

    import base64
    import hashlib
    from pathlib import PureWindowsPath
    from hotpost import source_preparation as preparation, source_finder
    from hotpost.source_policy import run_policy
    from hotpost.source_diversity import acquisition_policy
    from hotpost.studio_sources import SourceAcquisitionMixin
    # Exercise the real production gate with the preserved invalid old query
    # contract and original frame pixels. Prior tests cover signed host retry;
    # this test supplies no retry, search, source or quality approval.
    documents = []
    for artifact in original['artifacts']:
        try: value = json.loads(artifact['content'])
        except (KeyError, TypeError, ValueError): continue
        if isinstance(value, dict) and value.get('policy') == 'source-preparation-sha-v1':
            documents.append(value)
    assert documents
    bundle = copy.deepcopy(next(v for v in documents
        if v.get('query_plan', {}).get('run_id') == task['run_id']))
    captured = {}
    def collect(value):
        if isinstance(value, dict):
            if all(k in value for k in ('path', 'sha256', 'data_base64')):
                raw = base64.b64decode(value['data_base64'])
                assert hashlib.sha256(raw).hexdigest() == value['sha256']
                captured[value['sha256']] = raw
            for child in value.values(): collect(child)
        elif isinstance(value, list):
            for child in value: collect(child)
    collect(original)
    frame_rows = {row['path']: row for row in bundle['files']}
    assert all(frame_rows[p]['sha256'] in captured for p in bundle['frames'])
    substitutions = {}
    root = tmp_path / 'production-gate-media'
    root.mkdir()
    for index, row in enumerate(bundle['files']):
        target = root / str(index)
        if row['path'] == bundle['reference']:
            raw = b'isolated reference for hash binding'
        elif row['sha256'] in captured:
            raw = captured[row['sha256']]
        else:
            assert row['path'] == bundle['sheet']
            raw = captured[frame_rows[bundle['frames'][0]]['sha256']]
        target.write_bytes(raw)
        substitutions[row['path']] = str(target.resolve())
        substitutions[row['sha256']] = hashlib.sha256(raw).hexdigest()
    substitutions[task['reference_video']] = substitutions[bundle['reference']]
    def rewrite(value):
        if isinstance(value, dict): return {k:rewrite(v) for k,v in value.items()}
        if isinstance(value, list): return [rewrite(v) for v in value]
        if isinstance(value, str):
            if value in substitutions: return substitutions[value]
            if PureWindowsPath(value).is_absolute():
                return str(root / hashlib.sha256(value.encode()).hexdigest())
        return value
    isolated_task = rewrite(copy.deepcopy(original['task']))
    isolated_job = rewrite(copy.deepcopy(original['job']))
    isolated_job['status'] = 'running'
    isolated_job['claim_token'] = isolated_job['checkpoint']['_claim_token']
    bundle = rewrite(bundle)
    bundle['payload_sha256'] = preparation.payload_key(bundle)
    evidence = bundle['query_plan']['visual_query_evidence']['evidence']['text']
    caption = evidence['caption']
    transcript = copy.deepcopy(bundle['transcript'])
    # Bind only the isolated bundle metadata to the exact external text supplied.
    # The historical query contract and original frame pixels remain unchanged.
    assert caption == evidence['caption'] and transcript == bundle['transcript']
    bundle['evidence_key'] = preparation.evidence_key(caption, transcript)
    bundle['payload_sha256'] = preparation.payload_key(bundle)
    destination = preparation.acquisition_bundle_path(settings, isolated_task['shortcode'],
        caption, transcript, acquisition_policy(isolated_task, run_policy(isolated_task)),
        isolated_task['product'])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(bundle), encoding='utf8')
    monkeypatch.setattr(source_finder, '_post', lambda *a: SimpleNamespace(
        caption=caption, is_video=True, kind='video', shortcode=isolated_task['shortcode']))
    monkeypatch.setattr(source_finder, '_transcript_evidence', lambda *a: copy.deepcopy(transcript))
    store.change(task['id'], lambda s, db: s.update(copy.deepcopy(isolated_task)))
    store.checkpoint(isolated_job, isolated_job['checkpoint'])
    saved_path.write_text(json.dumps(changed), encoding='utf8')
    events.clear()
    plan, frames = preparation.preflight_preparation(settings, store.get(task['id']), isolated_job)
    assert plan is None  # Old invalid query evidence cannot become approval.
    assert frames and [p.read_bytes() for p in frames] == [
        Path(p).read_bytes() for p in bundle['frames']]
    owner = SourceAcquisitionMixin()
    owner.settings = settings
    owner.store = store
    from hotpost import source_topic_queries as topic
    actual_topic = topic.cached_topic_queries
    model_calls = []
    def current_topic(settings, reference, frames, caption, transcript, **kwargs):
        proposal = {'observations': [], 'subject_identity': {
            'version': 'core-product-identity-v2', 'kind': 'category',
            'product_terms': {'en': ['wallpaper'], 'zh': ['墙纸'], 'ko': ['벽지']},
            'required_terms': []}, 'queries': [
                {'id': lang, 'query': phrase, 'language': lang,
                 'viewpoint': 'product', 'semantic_key': 'wallpaper_repair',
                 'text_quotes': [{'source': 'caption', 'quote': '벽지'}],
                 'frame_ids': []}
                for lang, phrase in [('en', 'wallpaper repair'), ('zh', '墙纸 修补')]]}
        assert '벽지' in caption
        def generate(s, instruction, data, **options):
            model_calls.append(copy.deepcopy(data))
            if 'proposal_sha256' not in data:
                return copy.deepcopy(proposal)
            return {'input_sha256': data['input_sha256'],
                'proposal_sha256': data['proposal_sha256'], 'search_only': True,
                'subject_identity_supported': True, 'core_identity_complete': True,
                'known_subject_identity_complete': True,
                'checks': [{'query_id': q['id'], **dict.fromkeys(topic.FLAGS, True)}
                           for q in proposal['queries']]}
        return actual_topic(settings, reference, frames, caption, transcript,
                            generate, **kwargs)
    monkeypatch.setattr(topic, 'cached_topic_queries', current_topic)
    old_bundle_bytes = destination.read_bytes()
    def progress(*args): pass
    prepared_state = owner._prepare_source_queries(
        store.get(task['id']), isolated_job, progress)
    selected = isolated_job['checkpoint']['planning_preparation']
    assert selected['task_id'] == original['task']['id']
    assert selected['job_id'] == original['job']['id']
    assert selected['run_id'] == original['task']['run_id']
    assert Path(selected['path']).resolve() != destination.resolve()
    assert destination.read_bytes() == old_bundle_bytes
    accepted, accepted_frames = preparation.preflight_preparation(
        settings, prepared_state, isolated_job)
    assert accepted is not None and accepted_frames
    assert accepted['query_selection_policy'] == topic.POLICY
    assert model_calls and not store.get(task['id'])['sources']
    ready = owner._source_access_gate(store.get(task['id']), isolated_job)
    assert 'tiktok' in ready
    recovered = isolated_job['checkpoint']['parser_response_recovery']
    assert recovered['previous_readiness'] == changed
    assert recovered['job_id'] == original['job']['id']
    assert recovered['run_id'] == original['task']['run_id']
    assert recovered['grants_media_approval'] is False
    assert events == [query] and listeners == []
    assert store.get(task['id'])['sources'] == original['task']['sources']
    assert store.get(task['id'])['daily_quality'] == original['task']['daily_quality']
    assert original == json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))

    # Install captured historical manifests omitted by the earlier isolation.
    # Keep exact bytes and hashes; never invent a receipt or candidate approval.
    for prior in original['task']['source_acquisition'].get('interrupted_attempts', []):
        original_path = prior['manifest_path']
        matches = [a for a in original['artifacts']
                   if PureWindowsPath(a.get('path', '')) == PureWindowsPath(original_path)
                   and isinstance(a.get('content'), str)]
        assert len(matches) == 1, 'Exact captured interrupted manifest required'
        raw = matches[0]['content'].encode('utf8')
        assert hashlib.sha256(raw).hexdigest() == prior['manifest_sha256']
        target = Path(rewrite(original_path)).resolve()
        assert target.is_relative_to(tmp_path.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == prior['manifest_sha256']

    # Resume the original checkpoint through the actual collection entry.
    # Signed parking/retry/load remains covered by the pinned host tests.
    resumed_job = rewrite(copy.deepcopy(original['job']))
    resumed_job['status'] = 'running'
    resumed_job['claim_token'] = resumed_job['checkpoint']['_claim_token']
    store.change(task['id'], lambda s, db: s.update(copy.deepcopy(isolated_task)))
    store.checkpoint(resumed_job, resumed_job['checkpoint'])
    saved_path.write_text(json.dumps(changed), encoding='utf8')
    events.clear()
    actual_find = source_finder.find_sources
    reached = []
    # Deliberate external-I/O stop, not a failed production attempt.
    # Real finder Exceptions still fail with their original traceback below.
    class AcquisitionBoundary(BaseException): pass
    def acquisition(settings, shortcode, progress=None, **kwargs):
        context = kwargs.get('search_context') or {}
        if context.get('preparation_only'):
            return actual_find(settings, shortcode, progress, **kwargs)
        assert context['task_id'] == original['task']['id']
        assert context['job_id'] == original['job']['id']
        assert context['run_id'] == original['task']['run_id']
        assert context['planning_preparation'] == resumed_job['checkpoint']['planning_preparation']
        assert 'tiktok' in context['ready_routes']
        reached.append(copy.deepcopy(context))
        try:
            return actual_find(settings, shortcode, progress, **kwargs)
        except AcquisitionBoundary:
            raise
        except Exception:
            # Expose the initial isolated failure before collection cleanup can
            # replace it with a secondary receipt-preservation exception.
            import traceback
            pytest.fail('Initial finder failure:\n' + traceback.format_exc(), pytrace=False)
    from hotpost import browser_search as browser_search_module
    searches = []
    def external_search(settings, frames, queries, limit, root, **options):
        assert frames and queries
        assert Path(root).resolve().is_relative_to(tmp_path.resolve())
        assert 'tiktok' in options['routes']
        assert options['provider_queries']['tiktok']
        assert options['search_minimums'] == {'en': 5, 'zh': 5}
        assert options['search_identity']
        searches.append(copy.deepcopy(options['provider_queries']))
        raise AcquisitionBoundary('isolated external browser search boundary')
    monkeypatch.setattr(browser_search_module, 'browser_search', external_search)
    monkeypatch.setattr(source_finder, 'find_sources', acquisition)
    with pytest.raises(AcquisitionBoundary):
        owner._collect_sources(store.get(task['id']), resumed_job)
    assert len(reached) == 1 and len(searches) == 1
    assert resumed_job['id'] == original['job']['id']
    assert resumed_job['checkpoint']['parser_response_recovery']['previous_readiness'] == changed
    assert events == [query] and listeners == []
    with store.connect() as db:
        persisted = json.loads(db.execute('SELECT checkpoint FROM jobs WHERE id=?',
            (resumed_job['id'],)).fetchone()[0])
    assert persisted['parser_response_recovery'] == resumed_job['checkpoint']['parser_response_recovery']
    assert store.get(task['id'])['sources'] == original['task']['sources']
    assert store.get(task['id'])['daily_quality'] == original['task']['daily_quality']
    assert destination.read_bytes() == old_bundle_bytes
    assert original == json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
