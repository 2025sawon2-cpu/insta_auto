import copy
import json
import os
from pathlib import Path

import pytest

from hotpost import source_visual_queries as visual


def test_captured_saved_correction_recovers_without_inventing_searches(tmp_path, monkeypatch):
    captured = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    incident = copy.deepcopy(captured)
    task, job = incident['task'], incident['job']
    assert job['id'] == 'job-88ced5491a8244ae'
    assert job['task_id'] == task['id']
    assert job['status'] == 'failed'
    assert job['checkpoint']['failure_classification']['retryable'] is False
    rejection = task['source_acquisition']['visual_query_rejection']
    evidence = copy.deepcopy(rejection['evidence'])
    artifacts = incident['artifacts']
    if isinstance(artifacts, dict):
        artifacts = [dict(value, path=key) if isinstance(value, dict) else {'path':key,'content':value} for key,value in artifacts.items()]
    def artifact(name):
        row = next(r for r in artifacts if r['path'].replace(chr(92), '/').endswith('/' + name))
        text = row.get('content', row.get('text'))
        assert isinstance(text, str), 'Host fixture must contain the complete captured artifact text'
        return json.loads(text)
    original = artifact('proposal.json')['proposal']
    original_review = artifact('review.json')
    invalid = artifact('identity-correction-proposal.json')['proposal']
    invalid_review = artifact('identity-correction-review.json')
    # Remap captured media paths; these isolated bytes represent external media I/O.
    reference = tmp_path / 'reference.mp4'
    reference.write_bytes(b'isolated reference fixture')
    evidence['reference_path'] = str(reference.resolve())
    import hashlib
    evidence['reference_sha256'] = hashlib.sha256(reference.read_bytes()).hexdigest()
    for index, frame in enumerate(evidence['frames']):
        path = tmp_path / ('frame-%d.jpg' % index)
        from PIL import Image
        Image.new('RGB', (16, 16), (index, 20, 30)).save(path)
        frame.update(path=str(path.resolve()), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    key = visual.digest(evidence)
    original_review.update(input_sha256=key, proposal_sha256=visual.digest(original))
    invalid_review.update(input_sha256=key, proposal_sha256=visual.digest(invalid))
    from hotpost.config import Settings
    settings = Settings(data_dir=tmp_path)
    owner = dict(task_id=task['id'], job_id=job['id'], run_id=task['run_id'])
    assert owner == rejection['binding']
    frames = [Path(row['path']) for row in evidence['frames']]
    text = evidence['text']
    assert visual.binding(reference, frames, text['caption'], text, search_minimums=evidence['search_minimums'], subject_hint=evidence['subject_hint']) == evidence
    root = tmp_path / 'source-visual-queries' / key
    root.mkdir(parents=True)
    saved = {
        'proposal.json': {'input_sha256':key, 'proposal':original},
        'review.json': original_review,
        'identity-correction-proposal.json': {'input_sha256':key, 'feedback_sha256':visual.digest({'evidence':evidence,'rejected_proposal':original,'independent_review':original_review}), 'proposal':invalid},
        'identity-correction-review.json': invalid_review}
    for name,value in saved.items():
        (root/name).write_text(json.dumps(value,ensure_ascii=False), 'utf8')
    before = {name:(root/name).read_bytes() for name in saved}
    def run(model):
        return visual.cached_visual_queries(settings, reference, frames, text['caption'], text, model, search_minimums=evidence['search_minimums'], subject_hint=evidence['subject_hint'], owner_binding=owner)
    def forbidden(*args, **kwargs):
        pytest.fail('Saved legacy cache must not generate a new response')
    real_correct = visual._correct_identity_once
    def legacy(*args, **kwargs):
        return real_correct(*args, **kwargs, recover_saved=False)
    with monkeypatch.context() as old:
        old.setattr(visual, '_correct_identity_once', legacy)
        with pytest.raises(visual.VisualQueryRejection, match='원문 인용') as failure:
            run(forbidden)
        assert failure.value.receipt['binding'] == owner
    assert not (root/'receipt.json').exists()
    valid = copy.deepcopy(invalid)
    for term in valid['subject_identity']['required_terms']:
        if term.get('source') in evidence['text']:
            source = evidence['text'][term['source']]
            quote = term.get('quote','')
            if quote not in source:
                normalized = ' '.join(quote.split())
                matches = []
                for start in range(len(source)):
                    if source[start].isspace():
                        continue
                    for end in range(start+1,len(source)+1):
                        candidate = source[start:end]
                        if ' '.join(candidate.split()) == normalized:
                            matches.append(candidate)
                        if len(' '.join(candidate.split())) > len(normalized):
                            break
                assert matches, 'Correction must be a verbatim supplied quote'
                term['quote'] = min(matches,key=len)
    # Fresh external responses belong only to this isolated test.
    valid['observations'] = [dict(id='fixture', text='Two people indoors', frame_ids=['frame-1'])]
    valid['reference_scenes'] = []
    valid['queries'] = []
    identity = valid['subject_identity']
    # Equivalent translations in a fresh isolated external proposal; retain every condition.
    compact = {'eau de toilette':'EDT', 'bottle-neck jacquard ribbon':'bottle-neck-jacquard-ribbon'}
    for term in identity['required_terms']:
        term['terms']['en'] = [compact.get(value, value) for value in term['terms']['en']]
    assert len(identity['required_terms']) == len(invalid['subject_identity']['required_terms'])
    assert [term['quote'] for term in identity['required_terms']] == [term['quote'] for term in valid['subject_identity']['required_terms']]
    variants = {'en':['', 'rose', 'peony', 'bergamot', 'white-musk'], 'zh':['', '玫瑰', '牡丹', '佛手柑', '白麝香']}
    for lang, modifiers in variants.items():
        base = ' '.join([identity['product_terms'][lang][0]] + [row['terms'][lang][0] for row in identity['required_terms']])
        for index, modifier in enumerate(modifiers):
            valid['queries'].append(dict(id=lang+str(index), query=' '.join(filter(None, [modifier, base])), language=lang, observation_ids=['fixture'], frame_ids=['frame-1']))
    from hotpost.source_queries import _clean_tiktok_syntax
    from hotpost.source_query_identity import matches_identity
    assert len(valid['queries']) == 10
    assert all(_clean_tiktok_syntax(q['query']) == q['query'] for q in valid['queries'])
    assert all(matches_identity(q['query'], identity) for q in valid['queries'])
    calls = []
    def external_model(settings,instruction,data,**kwargs):
        calls.append(copy.deepcopy(data))
        if 'proposal_sha256' not in data:
            assert data['validation_error']
            assert data['rejected_proposal'] == invalid
            return copy.deepcopy(valid)
        assert data['proposal'] == valid
        return dict(input_sha256=data['input_sha256'], proposal_sha256=data['proposal_sha256'], subject_identity_supported=True, core_identity_complete=True, checks=[dict(query_id=q['id'], supported=True, central_product=True, short_noun_phrase=True, no_unobserved_claims=True, core_identity_preserved=True, reason='Independent isolated response bound to supplied fixture text and frame') for q in valid['queries']])
    # Exercise the actual production entry after the host retry contract has
    # requeued and claimed this same job. No internal validator is replaced.
    from types import SimpleNamespace
    from hotpost.studio import Studio
    from hotpost import source_finder as finder
    from hotpost import source_preparation as preparation
    from hotpost import source_access_preflight as access
    from hotpost.source_pause_receipts import snapshot, verified_receipt
    from hotpost.source_policy import run_policy
    from hotpost.video_agent_actions import repair_has_available_route
    settings.source_browser_search = True
    settings.source_query_model_enabled = True
    settings.source_match_mode = 'appearance'
    studio = Studio(settings, workers=False)
    state = copy.deepcopy(task)
    active = copy.deepcopy(job)
    state.setdefault('revision', 0)
    state.setdefault('created', 1)
    state.setdefault('updated', 1)
    state['reference_video'] = str(reference)
    state['reference_duration'] = 20
    state['sources'] = []
    # Keep the causal access wait, counters, policy, identity and full job
    # checkpoint. Older other-job discovery ledgers cannot alter this gate.
    acquisition = state['source_acquisition']
    acquisition['rounds'] = []
    acquisition['interrupted_attempts'] = []
    assert acquisition['waiting']['searches']
    assert repair_has_available_route(state, active)
    active['status'] = 'running'
    active['claim_token'] = active['checkpoint']['_claim_token']
    from hotpost.source_quality import sha256_file
    from hotpost.source_coverage import search_scope_for_state
    manifest_remap = {}
    for descriptor in active['checkpoint']['source_attempts']:
        old_manifest = descriptor['manifest_path']
        manifest_data = next(r for r in artifacts if r['path'] == old_manifest)
        manifest_data = json.loads(manifest_data.get('content', manifest_data.get('text')))
        attempt_name = old_manifest.replace(chr(92), '/').split('/')[-2]
        folder = settings.source_dir / attempt_name
        folder.mkdir(parents=True, exist_ok=True)
        manifest = folder / 'manifest.json'
        manifest_data['search_context'] = search_scope_for_state(state)
        manifest.write_text(json.dumps(manifest_data, ensure_ascii=False), 'utf8')
        descriptor.update(manifest_path=str(manifest.resolve()),
            reference_sha256=sha256_file(reference),
            search_context=search_scope_for_state(state))
        assert descriptor['workers'] == []
        saved_receipt = snapshot(settings.source_dir, descriptor, state, active)
        receipt_path = folder / 'interrupted-execution-receipt.json'
        receipt_path.write_text(json.dumps(saved_receipt, ensure_ascii=False), 'utf8')
        descriptor.update(receipt_path=str(receipt_path.resolve()),
            receipt_sha256=sha256_file(receipt_path))
        assert verified_receipt(settings.source_dir, descriptor, state, active) == saved_receipt
        manifest_remap[old_manifest] = str(manifest.resolve())
    # Acceptance checks read these references independently of source_attempts.
    # Rebind only the deep-copied fixture; retain the actual captured manifests.
    if state.get('source_search_manifest_path'):
        previous_manifest = state['source_search_manifest_path']
        if previous_manifest not in manifest_remap:
            # Historical acceptance reference is not a current-job receipt.
            # Preserve the exact fields read by verify_acceptance; its old
            # acquisition bundle is distinct from the media-only fixture.
            assert previous_manifest.replace(chr(92), '/').endswith('/DenReaeTiaA-1792416964185293200/manifest.json')
            historical = tmp_path / 'historical-acceptance' / 'manifest.json'
            historical.parent.mkdir(parents=True, exist_ok=True)
            historical_bundle = tmp_path / 'historical-preparation' / '9f107cb79f059f68bedee27a-c460461d-acq-7878fe4e07.json'
            historical.write_text(json.dumps({
                'shortcode': state['shortcode'],
                'caption': text['caption'],
                'preparation_bundle_path': str(historical_bundle.resolve()),
                'preparation_bundle_sha256': '659f21ffb70934c8e58be2e7e01fef1b7601bb8dc7178718f1dc45add483f097'
            }, ensure_ascii=False), 'utf8')
            manifest_remap[previous_manifest] = str(historical.resolve())
        state['source_search_manifest_path'] = manifest_remap[previous_manifest]
    for row in active['checkpoint'].get('refresh_wait_history', []):
        if row.get('manifest_path'):
            previous_manifest = row['manifest_path']
            assert previous_manifest in manifest_remap
            row['manifest_path'] = manifest_remap[previous_manifest]
            if 'manifest_sha256' in row:
                row['manifest_sha256'] = sha256_file(Path(row['manifest_path']))
    # Seed the exact identities directly in the isolated real store. Running
    # status/token are the output of the separately pinned host retry/claim.
    with studio.store.transaction() as db:
        db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)',
            (state['id'], state['shortcode'], state['revision'], json.dumps(state), 1))
        db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)',
            (active['id'], state['id'], active['kind'], active['key'],
             json.dumps(active['payload']), 'running', json.dumps(active['checkpoint']),
             active['error'], active['created'], active['updated']))
    text_transcript = {**text, 'reference_kind':'mixed'}
    monkeypatch.setattr(finder, '_post', lambda *a: SimpleNamespace(
        is_video=True, kind='reel', caption=text['caption'], url='https://reference.invalid'))
    monkeypatch.setattr(finder, '_transcript_evidence', lambda *a: copy.deepcopy(text_transcript))
    # External decoder I/O only; retain all internal review and receipt logic.
    def external_frames(video, destination, *args, **kwargs):
        assert Path(video).resolve() == reference.resolve()
        assert all(frame.is_file() for frame in frames)
        return list(frames[:kwargs.get('max_frames', len(frames))])
    monkeypatch.setattr(finder, 'extract_frames', external_frames)
    sheet = tmp_path / 'sheet.jpg'
    sheet.write_bytes(frames[0].read_bytes())
    media_path, _ = preparation.bundle_paths(settings, state['shortcode'], text['caption'], text_transcript)
    preparation.save_bundle(media_path.with_suffix('.media.json'), text['caption'],
        text_transcript, reference, frames, sheet, query_policy='media-only',
        transcript=text_transcript, query_plan={}, visual_product_queries=[],
        google_vision_terms=[], openclip_product_evidence=[], subject_reference_indices=[])
    class ExternalVerifier:
        error = ''
        available = False
        product_evidence = []
        subject_reference_indices = []
        def __init__(self, *a): pass
    monkeypatch.setattr(finder, 'OpenClipVerifier', ExternalVerifier)
    monkeypatch.setattr('hotpost.text_overlay.TextOverlayDetector',
        lambda *a: SimpleNamespace(note=''))
    # This is a model-service response, not a replacement for validation.
    def external_plan(*args, **kwargs):
        return {'products':[], 'primary_subject':{'name':evidence['subject_hint']},
            'query_evidence':copy.deepcopy(text), 'query_details':[],
            'search_minimums':copy.deepcopy(evidence['search_minimums'])}
    monkeypatch.setattr('hotpost.source_planning.cached_enrich_plan', external_plan)
    observations = copy.deepcopy(active['checkpoint']['source_access_preflight']['observations'])
    monkeypatch.setattr(access, 'current_routes', lambda *a: copy.deepcopy(observations))
    class SearchReached(RuntimeError): pass
    searches = []
    def external_search(s, shortcode, supplied_frames, queries, plan, vision, folder,
                        *args, **kwargs):
        searches.append(copy.deepcopy(plan))
        assert shortcode == state['shortcode']
        assert plan['run_id'] == state['run_id']
        assert plan['search_context'] == search_scope_for_state(state)
        assert len(visual.plan_queries(plan)) == 10
        assert plan['minimum_query_plan_ready'] is True
        assert 'youtube' not in plan['search_strategy']['routes']
        # Isolated external search response: no candidates or approvals.
        return [], queries, {'notes': []}, [], 5
    monkeypatch.setattr('hotpost.source_search.discovery.discover', external_search)
    monkeypatch.setattr('hotpost.script_rewriter._generate', forbidden)
    with monkeypatch.context() as old:
        old.setattr(visual, '_correct_identity_once', legacy)
        with pytest.raises(visual.VisualQueryRejection, match='원문 인용'):
            studio._collect_sources(studio.store.get(state['id']), active)
    assert searches == []
    assert active['checkpoint']['visual_query_input'] == {**owner, 'input_sha256':key}
    assert studio.store.get(state['id'])['source_acquisition']['waiting']['searches']
    monkeypatch.setattr('hotpost.script_rewriter._generate', external_model)
    recovered = studio._collect_sources(studio.store.get(state['id']), active)
    assert len(searches) == 1
    assert recovered['sources'] == []
    completed_manifest = Path(active['checkpoint']['manifest'])
    completed = json.loads(completed_manifest.read_text('utf8'))
    assert completed['status'] == 'completed'
    assert completed['audit_checkpoint'] == 'completed'
    assert completed['execution_audit_available'] is True
    assert completed['run_id'] == task['run_id']
    assert completed['search_context'] == search_scope_for_state(state)
    assert recovered['source_search_manifest_path'] == str(completed_manifest)
    latest = active['checkpoint']['source_attempts'][-1]
    assert latest['studio_job_id'] == job['id']
    saved = verified_receipt(settings.source_dir, latest, studio.store.get(state['id']), active)
    assert saved['manifest_sha256'] == sha256_file(completed_manifest)
    assert saved['candidates'] == []
    assert active['id'] == job['id']
    assert active['payload']['run_id'] == task['run_id']
    assert active['checkpoint']['source_access_preflight']['ready_routes']
    # Login observations remain blocked; recovery only uses observed ready routes.
    assert any(r['provider']=='youtube' and r['status']=='login_required'
        for r in active['checkpoint']['source_access_preflight']['observations'])
    with monkeypatch.context() as blocked:
        blocked.setattr(access, 'current_routes', lambda *a: [
            dict(r, status='login_required') for r in observations])
        with pytest.raises(access.SourceAccessWaiting):
            studio._source_access_gate(studio.store.get(state['id']), active)
    from hotpost.studio_store import StaleClaim
    stale = copy.deepcopy(active)
    stale['claim_token'] = 'wrong-owner'
    with pytest.raises(StaleClaim):
        studio._collect_sources(studio.store.get(state['id']), stale)
    receipt = run(forbidden)
    corrected, review = receipt['proposal'], receipt['review']
    rows = visual.verify(receipt)
    assert len(rows) == 10
    assert receipt['approved_query_pool']['ready'] is True
    assert all(row['count'] >= 5 for row in receipt['approved_query_pool']['languages'].values())
    assert run(forbidden) == receipt
    assert len(calls) == 2
    assert all((root/name).read_bytes() == value for name,value in before.items())
    damaged_review = dict(review, proposal_sha256='invalid')
    with pytest.raises(ValueError,match='SHA'):
        visual.validate(corrected,damaged_review,evidence)
    frames[0].write_bytes(b'changed fixture pixels')
    with pytest.raises(ValueError):
        visual.verify(receipt)
    assert captured == json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
