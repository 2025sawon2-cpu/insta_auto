import copy
import json
import os
from pathlib import Path

import pytest


def test_current_incident_replans_before_real_access_wait(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PIL import Image
    from hotpost import source_finder as finder
    from hotpost import source_preparation as preparation
    from hotpost import source_visual_queries as visual
    from hotpost import source_access_preflight as access
    from hotpost.source_quality import sha256_file
    from hotpost.source_pause_receipts import verified_receipt
    captured = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    state, owner = copy.deepcopy(captured['task']), copy.deepcopy(captured['job'])
    hold = copy.deepcopy(state['source_acquisition']['hold'])
    artifacts = captured['artifacts']
    if isinstance(artifacts, dict):
        artifacts = [dict(v, path=k) if isinstance(v, dict) else dict(path=k, content=v) for k,v in artifacts.items()]
    bundles = []
    for row in artifacts:
        raw = row.get('content', row.get('text'))
        try: value = json.loads(raw) if isinstance(raw,str) else raw
        except ValueError: continue
        if isinstance(value,dict) and value.get('query_plan',{}).get('visual_query_evidence'):
            bundles.append(value)
    assert bundles
    historical = copy.deepcopy(bundles[-1])
    old_plan = historical['query_plan']
    old_receipt = old_plan['visual_query_evidence']
    assert old_receipt['queries'] == []
    text = copy.deepcopy(old_receipt['evidence']['text'])
    transcript = copy.deepcopy(historical['transcript'])
    reference = tmp_path/'reference.mp4'
    reference.write_bytes(b'isolated successful preparation reference')
    frames = []
    for i in range(len(old_receipt['evidence']['frames'])):
        frame = tmp_path/('frame%d.jpg'%i)
        Image.new('RGB',(16,16),(i,20,30)).save(frame)
        frames.append(frame)
    sheet = tmp_path/'sheet.jpg'
    sheet.write_bytes(frames[0].read_bytes())
    original_reference = state['reference_video']
    original_sha = old_receipt['evidence']['reference_sha256']
    def rebound(value):
        if isinstance(value,dict): return {k:rebound(v) for k,v in value.items()}
        if isinstance(value,list): return [rebound(v) for v in value]
        if value == original_reference: return str(reference.resolve())
        if value == original_sha: return sha256_file(reference)
        return value
    state,owner = rebound(state),rebound(owner)
    # Acceptance reads historical manifests independently of the media bundle.
    # Preserve captured contents and every history row; remap only copied
    # references and their corresponding file hashes into isolated storage.
    manifest_paths = {}
    manifest_hashes = {}
    for index,row in enumerate(artifacts):
        original = row.get('path','')
        if not original.replace(chr(92),'/').endswith('/manifest.json'):
            continue
        raw = row.get('content',row.get('text'))
        assert isinstance(raw,str), 'Captured manifest text is required'
        local = tmp_path/'historical-manifests'/str(index)/'manifest.json'
        local.parent.mkdir(parents=True,exist_ok=True)
        local.write_bytes(raw.encode('utf8'))
        assert json.loads(local.read_text('utf8')) == json.loads(raw)
        manifest_paths[original] = str(local.resolve())
        if row.get('sha256'):
            manifest_hashes[row['sha256']] = sha256_file(local)
    assert manifest_paths
    # Only the latest manifest is captured. Keep all historical descriptors,
    # but isolate unavailable files without inventing their contents/approval.
    # Real acceptance retains its existing missing-file branch. This fixture
    # does not prove acceptance against uncaptured historical file contents.
    unavailable = {}
    def register_missing(value):
        if isinstance(value,dict):
            for item in value.values(): register_missing(item)
        elif isinstance(value,list):
            for item in value: register_missing(item)
        elif isinstance(value,str) and value.replace(chr(92),'/').endswith('/manifest.json'):
            if value not in manifest_paths:
                local = tmp_path/'uncaptured-manifests'/str(len(unavailable))/'manifest.json'
                if value not in unavailable:
                    unavailable[value] = str(local.resolve())
    register_missing(state)
    register_missing(owner)
    assert unavailable
    assert all(not Path(path).exists() for path in unavailable.values())
    # Deferred recovery reads candidates even from historical interruptions.
    # Preserve that causal branch using the captured receipt candidate ledger,
    # never an invented empty result or approval. These projections are test
    # inputs, not reconstructed production receipts or historical SHA proofs.
    for entry in state['source_acquisition'].get('interrupted_attempts',[]):
        original = entry.get('manifest_path')
        if original not in unavailable:
            continue
        assert isinstance(entry.get('candidates'),list)
        local = Path(unavailable[original])
        projection = {'shortcode':entry['shortcode'],
            'run_id':entry['run_id'],
            'candidates':copy.deepcopy(entry['candidates'])}
        local.parent.mkdir(parents=True,exist_ok=True)
        if local.exists():
            assert json.loads(local.read_text('utf8')) == projection
        else:
            local.write_text(json.dumps(projection,ensure_ascii=False),'utf8')
        assert json.loads(local.read_text('utf8'))['candidates'] == entry['candidates']
    manifest_paths.update(unavailable)
    def isolated_manifests(value):
        if isinstance(value,dict):
            return {k:isolated_manifests(v) for k,v in value.items()}
        if isinstance(value,list):
            return [isolated_manifests(v) for v in value]
        if isinstance(value,str):
            return manifest_paths.get(value,manifest_hashes.get(value,value))
        return value
    state,owner = isolated_manifests(state),isolated_manifests(owner)
    for row in state['source_acquisition']['rounds']:
        assert row['manifest_path'] in manifest_paths.values(), 'All acceptance manifests must be captured'
    assert state['source_search_manifest_path'] in manifest_paths.values()
    state['reference_duration'] = 20
    settings = Settings(data_dir=tmp_path)
    settings.source_browser_search = True
    settings.source_query_model_enabled = True
    settings.source_match_mode = 'appearance'
    media,_ = preparation.bundle_paths(settings,state['shortcode'],text['caption'],transcript)
    preparation.save_bundle(media.with_suffix('.media.json'),text['caption'],transcript,reference,frames,sheet,
        query_policy='media-only',transcript=transcript,query_plan={},
        visual_product_queries=[],google_vision_terms=[],openclip_product_evidence=[],subject_reference_indices=[])
    # Preserve the causal empty cache; rebind only copied media evidence.
    empty = copy.deepcopy(old_receipt)
    empty['evidence'] = visual.binding(reference,frames,text['caption'],transcript,
        search_minimums=old_receipt['evidence']['search_minimums'],
        subject_hint=old_receipt['evidence']['subject_hint'])
    empty['input_sha256'] = visual.digest(empty['evidence'])
    empty['review']['input_sha256'] = empty['input_sha256']
    assert visual.verify(empty) == []
    cache = tmp_path/'source-visual-queries'/empty['input_sha256']/'receipt.json'
    cache.parent.mkdir(parents=True,exist_ok=True)
    cache.write_text(json.dumps(empty,ensure_ascii=False),'utf8')
    empty_bytes = cache.read_bytes()
    # Install the incident's existing acquisition plan, not only reusable media.
    # Rebind copied media and payload hashes; retain the empty dispatch defect.
    from hotpost.source_policy import run_policy
    from hotpost.source_diversity import acquisition_policy
    acquisition_config = acquisition_policy(state,run_policy(state))
    accepted_path = preparation.acquisition_bundle_path(settings,state['shortcode'],
        text['caption'],transcript,acquisition_config,state['product'])
    accepted_plan = rebound(copy.deepcopy(old_plan))
    accepted_plan['visual_query_evidence'] = copy.deepcopy(empty)
    accepted_plan['query_reference_sha256'] = sha256_file(reference)
    assert visual.plan_queries(accepted_plan) == []
    assert not preparation.reusable_query_contract(accepted_plan,acquisition_config,state['product'],{})
    preparation.save_bundle(accepted_path,text['caption'],transcript,reference,frames,sheet,
        transcript=transcript,query_plan=accepted_plan,
        visual_product_queries=copy.deepcopy(historical.get('visual_product_queries',[])),
        google_vision_terms=copy.deepcopy(historical.get('google_vision_terms',[])),
        openclip_product_evidence=copy.deepcopy(historical.get('openclip_product_evidence',[])),
        subject_reference_indices=copy.deepcopy(historical.get('subject_reference_indices',[])))
    accepted_bytes = accepted_path.read_bytes()
    acceptance_manifest = Path(state['source_search_manifest_path'])
    acceptance_value = json.loads(acceptance_manifest.read_text('utf8'))
    acceptance_value.update(preparation_bundle_path=str(accepted_path.resolve()),
        preparation_bundle_sha256=sha256_file(accepted_path))
    acceptance_manifest.write_text(json.dumps(acceptance_value,ensure_ascii=False),'utf8')
    acceptance_bytes = acceptance_manifest.read_bytes()
    preparation.verify_acceptance(preparation.load_bundle(accepted_path,text['caption'],transcript),
        accepted_path,{'rounds':state['source_acquisition']['rounds']},sha256_file(reference))
    def external_frames(video,destination,*args,**kwargs):
        assert Path(video).resolve() == reference.resolve()
        return list(frames[:kwargs.get('max_frames',len(frames))])
    monkeypatch.setattr(finder,'extract_frames',external_frames)
    proposal = copy.deepcopy(old_receipt['proposal'])
    proposal['observations'] = [dict(id='fixture',text='Two people indoors',frame_ids=['frame-1'])]
    proposal['reference_scenes'] = []
    identity = proposal['subject_identity']
    compact = {'eau de toilette':'EDT','bottle-neck jacquard ribbon':'bottle-neck-jacquard-ribbon'}
    for term in identity['required_terms']:
        term['terms']['en'] = [compact.get(v,v) for v in term['terms']['en']]
    proposal['queries'] = []
    for lang,modifiers in {'en':['','rose','peony','bergamot','white-musk'],
                           'zh':['','玫瑰','牡丹','佛手柑','白麝香']}.items():
        base = ' '.join([identity['product_terms'][lang][0]]+[r['terms'][lang][0] for r in identity['required_terms']])
        for i,modifier in enumerate(modifiers):
            proposal['queries'].append(dict(id=lang+str(i),query=' '.join(filter(None,[modifier,base])),
                language=lang,observation_ids=['fixture'],frame_ids=['frame-1']))
    calls = []
    def external_model(settings,instruction,data,**kwargs):
        calls.append(copy.deepcopy(data))
        if 'proposal_sha256' not in data: return copy.deepcopy(proposal)
        return dict(input_sha256=data['input_sha256'],proposal_sha256=data['proposal_sha256'],
            subject_identity_supported=True,core_identity_complete=True,checks=[dict(
                query_id=q['id'],supported=True,central_product=True,short_noun_phrase=True,
                no_unobserved_claims=True,core_identity_preserved=True,
                reason='Isolated independent response bound to exact input and proposal') for q in data['proposal']['queries']])
    monkeypatch.setattr(finder,'_post',lambda *a: SimpleNamespace(is_video=True,kind='reel',caption=text['caption'],url='https://reference.invalid'))
    monkeypatch.setattr(finder,'_transcript_evidence',lambda *a: copy.deepcopy(transcript))
    class ExternalVerifier:
        error = ''
        available = False
        product_evidence = []
        subject_reference_indices = []
        def __init__(self,*a): pass
    monkeypatch.setattr(finder,'OpenClipVerifier',ExternalVerifier)
    monkeypatch.setattr('hotpost.text_overlay.TextOverlayDetector',lambda *a: SimpleNamespace(note=''))
    monkeypatch.setattr('hotpost.source_planning.cached_enrich_plan',lambda *a,**kw: dict(
        products=[],primary_subject={'name':state['product']},query_evidence=copy.deepcopy(text),
        query_details=[],search_minimums={'en':5,'zh':5}))
    monkeypatch.setattr('hotpost.script_rewriter._generate',external_model)
    observed = []
    def external_routes(settings,providers):
        observed.append(list(providers))
        return [dict(provider=p,status='login_required',attempted=False,reason='isolated unavailable external session') for p in providers]
    monkeypatch.setattr(access,'current_routes',external_routes)
    child = dict(id='isolated-positive-child',task_id=state['id'],kind='collect_sources',
        key='isolated-positive-child',status='running',payload=dict(run_id=state['run_id'],
        round=state['source_acquisition']['round'],planning_recovery_from=owner['id']),
        checkpoint={'_claim_token':'isolated-positive-claim'},claim_token='isolated-positive-claim',
        error='',created=1,updated=1)
    studio = Studio(settings,workers=False)
    try:
        with studio.store.transaction() as db:
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)',(state['id'],state['shortcode'],state.get('revision',0),json.dumps(state),1))
            for row in (owner,child):
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)',(row['id'],state['id'],row['kind'],row['key'],json.dumps(row['payload']),row['status'],json.dumps(row['checkpoint']),row.get('error',''),row.get('created',1),row.get('updated',1)))
        with pytest.raises(access.SourceAccessWaiting):
            studio._collect_sources(studio.store.get(state['id']),child)
        assert len(calls) == 2
        assert len(observed) == 1
        assert cache.read_bytes() == empty_bytes
        assert list(cache.parent.glob('empty-recovery-*/receipt.json'))
        selected = child['checkpoint']['planning_preparation']
        assert Path(selected['path']).resolve() != accepted_path.resolve()
        assert '-replan-' in Path(selected['path']).stem
        assert accepted_path.read_bytes() == accepted_bytes
        assert acceptance_manifest.read_bytes() == acceptance_bytes
        plan = preparation.load_bundle(selected['path'],text['caption'],transcript)['query_plan']
        assert Path(selected['path']).resolve() == preparation.replanning_bundle_path(accepted_path,plan).resolve()
        assert len(visual.plan_queries(plan)) == 10
        assert plan['minimum_query_plan_ready'] is True
        assert selected['job_id'] == child['id']
        assert selected['run_id'] == state['run_id']
        latest = child['checkpoint']['source_attempts'][-1]
        current = studio.store.get(state['id'])
        receipt = verified_receipt(settings.source_dir,latest,current,child)
        manifest = json.loads(Path(latest['manifest_path']).read_text('utf8'))
        assert manifest['status'] == 'prepared'
        assert manifest['preparation_bundle_path'] == selected['path']
        assert manifest['preparation_bundle_sha256'] == selected['sha256']
        assert sha256_file(Path(selected['path'])) == selected['sha256']
        assert receipt['searches'] == []
        assert receipt['candidates'] == []
        assert current['source_acquisition']['hold'] == hold
        assert current['source_acquisition']['rounds'] == state['source_acquisition']['rounds']
        assert child['checkpoint']['source_access_preflight']['ready_routes'] == []
        with studio.store.connect() as db:
            saved = db.execute('SELECT status,checkpoint FROM jobs WHERE id=?',(owner['id'],)).fetchone()
        assert saved['status'] == 'done'
        assert json.loads(saved['checkpoint']) == owner['checkpoint']
        # Resume this exact child after an external session becomes ready.
        # Internal access, ownership, preparation and receipt validators stay real.
        searches = []
        from hotpost.source_coverage import search_scope_for_state
        def ready_routes(settings, providers):
            return [dict(provider=p, status='ready' if p == 'tiktok' else 'login_required',
                attempted=False, reason='isolated external session observation') for p in providers]
        def external_search(s, shortcode, supplied_frames, queries, plan, vision, folder, *args, **kwargs):
            searches.append(copy.deepcopy(plan))
            assert shortcode == state['shortcode']
            assert plan['run_id'] == state['run_id']
            assert plan['search_context'] == search_scope_for_state(current)
            assert len(visual.plan_queries(plan)) == 10
            assert plan['minimum_query_plan_ready'] is True
            assert 'youtube' not in plan['search_strategy']['routes']
            return [], queries, {'notes': []}, [], 5
        monkeypatch.setattr(access, 'current_routes', ready_routes)
        monkeypatch.setattr('hotpost.source_search.discovery.discover', external_search)
        # Reconstruct the worker from persisted bytes, as a later claim does.
        def reload_child():
            with studio.store.connect() as db:
                row = dict(db.execute('SELECT * FROM jobs WHERE id=?',(child['id'],)).fetchone())
            row['payload'] = json.loads(row['payload'])
            row['checkpoint'] = json.loads(row['checkpoint'])
            row['claim_token'] = row['checkpoint']['_claim_token']
            return row
        persisted_child = reload_child()
        assert persisted_child['checkpoint']['planning_preparation'] == selected
        original_checkpoint = copy.deepcopy(persisted_child['checkpoint'])
        for field,value in [('path',str(tmp_path/'outside-preparations.json')),
                            ('sha256','0'*64),('job_id','another-job')]:
            damaged = copy.deepcopy(original_checkpoint)
            damaged['planning_preparation'][field] = value
            with studio.store.transaction() as db:
                db.execute('UPDATE jobs SET checkpoint=? WHERE id=?',
                    (json.dumps(damaged),child['id']))
            invalid = reload_child()
            with pytest.raises(access.SourceAccessWaiting):
                studio._collect_sources(studio.store.get(state['id']),invalid)
            assert searches == []
            assert studio.store.get(state['id'])['source_acquisition']['hold'] == hold
            assert accepted_path.read_bytes() == accepted_bytes
            assert acceptance_manifest.read_bytes() == acceptance_bytes
            with studio.store.transaction() as db:
                db.execute('UPDATE jobs SET checkpoint=? WHERE id=?',
                    (json.dumps(original_checkpoint),child['id']))
        child = reload_child()
        assert child['checkpoint'] == original_checkpoint
        # External metadata becomes unavailable after the acceptance transaction,
        # before discovery. No internal gate or persistence method is mocked.
        post_calls_after_acceptance = []
        def metadata_wait_after_acceptance(*args):
            if not studio.store.get(state['id'])['source_acquisition'].get('hold'):
                post_calls_after_acceptance.append(True)
                raise access.SourceAccessWaiting('isolated external metadata wait after acceptance')
            return SimpleNamespace(is_video=True,kind='reel',caption=text['caption'],url='https://reference.invalid')
        with monkeypatch.context() as interrupted:
            interrupted.setattr(finder,'_post',metadata_wait_after_acceptance)
            with pytest.raises(access.SourceAccessWaiting):
                studio._collect_sources(studio.store.get(state['id']),child)
        assert post_calls_after_acceptance == [True]
        assert searches == []
        accepted_state = studio.store.get(state['id'])
        assert not accepted_state['source_acquisition'].get('hold')
        assert hold in accepted_state['source_acquisition']['hold_history']
        child = reload_child()
        assert child['id'] == 'isolated-positive-child'
        assert child['payload']['run_id'] == state['run_id']
        assert 'planning_recovery_from' not in child['payload']
        assert child['checkpoint']['planning_preparation'] == selected
        assert accepted_path.read_bytes() == accepted_bytes
        assert acceptance_manifest.read_bytes() == acceptance_bytes
        recovered = studio._collect_sources(studio.store.get(state['id']), child)
        assert accepted_path.read_bytes() == accepted_bytes
        assert acceptance_manifest.read_bytes() == acceptance_bytes
        assert len(searches) == 1
        assert len(calls) == 2
        assert recovered['sources'] == []
        completed_path = Path(child['checkpoint']['manifest'])
        completed = json.loads(completed_path.read_text('utf8'))
        assert completed['status'] == 'completed'
        assert completed['preparation_bundle_path'] == selected['path']
        assert completed['preparation_bundle_sha256'] == selected['sha256']
        assert completed['audit_checkpoint'] == 'completed'
        assert completed['execution_audit_available'] is True
        assert completed['run_id'] == state['run_id']
        latest = child['checkpoint']['source_attempts'][-1]
        saved_receipt = verified_receipt(settings.source_dir, latest, studio.store.get(state['id']), child)
        assert saved_receipt['manifest_sha256'] == sha256_file(completed_path)
        assert saved_receipt['studio_job_id'] == child['id']
        assert saved_receipt['candidates'] == []
        assert cache.read_bytes() == empty_bytes
        resumed = studio.store.get(state['id'])
        assert resumed['source_acquisition']['rounds'] == state['source_acquisition']['rounds']
        assert hold in resumed['source_acquisition']['hold_history']
        assert child['checkpoint']['source_access_preflight']['ready_routes'] == ['tiktok']
        with studio.store.connect() as db:
            unchanged = db.execute('SELECT status,checkpoint FROM jobs WHERE id=?', (owner['id'],)).fetchone()
        assert unchanged['status'] == 'done'
        assert json.loads(unchanged['checkpoint']) == owner['checkpoint']
        assert captured == json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    finally:
        studio.close()


def test_current_incident_valid_child_enters_real_preparation(tmp_path, monkeypatch):
    from hotpost import source_finder as finder
    from hotpost.source_quality import sha256_file
    from hotpost.source_pause_receipts import verified_receipt
    captured = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    state = copy.deepcopy(captured['task'])
    owner = copy.deepcopy(captured['job'])
    hold = copy.deepcopy(state['source_acquisition']['hold'])
    reference = tmp_path / 'reference.mp4'
    reference.write_bytes(b'isolated preparation reference')
    original_reference = state['reference_video']
    original_sha = state['source_acquisition']['visual_query_rejection']['reference_sha256']
    def rebound(value):
        if isinstance(value, dict): return {k:rebound(v) for k,v in value.items()}
        if isinstance(value, list): return [rebound(v) for v in value]
        if value == original_reference: return str(reference.resolve())
        if value == original_sha: return sha256_file(reference)
        return value
    state, owner = rebound(state), rebound(owner)
    # Preserve all causal history, done ownership, current hold and round.
    # The failure is injected before any media/history bundle is opened.
    child = dict(id='isolated-valid-child', task_id=state['id'],
        kind='collect_sources', key='isolated-valid-child', status='running',
        payload=dict(run_id=state['run_id'], round=state['source_acquisition']['round'],
                     planning_recovery_from=owner['id']),
        checkpoint={'_claim_token':'isolated-valid-claim'},
        claim_token='isolated-valid-claim', error='', created=1, updated=1)
    studio = Studio(Settings(data_dir=tmp_path), workers=False)
    class ExternalPostUnavailable(RuntimeError): pass
    calls = []
    def external_post(*args):
        calls.append(args)
        raise ExternalPostUnavailable('isolated external metadata service unavailable')
    monkeypatch.setattr(finder, '_post', external_post)
    try:
        with studio.store.transaction() as db:
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)',
                (state['id'],state['shortcode'],state.get('revision',0),json.dumps(state),1))
            for row in (owner,child):
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (row['id'],state['id'],row['kind'],row['key'],json.dumps(row['payload']),
                     row['status'],json.dumps(row['checkpoint']),row.get('error',''),
                     row.get('created',1),row.get('updated',1)))
        with pytest.raises(ExternalPostUnavailable):
            studio._collect_sources(studio.store.get(state['id']),child)
        assert len(calls) == 1
        assert child['checkpoint']['source_attempts']
        descriptor = child['checkpoint']['source_attempts'][-1]
        current = studio.store.get(state['id'])
        receipt = verified_receipt(studio.settings.source_dir,descriptor,current,child)
        manifest = json.loads(Path(descriptor['manifest_path']).read_text('utf8'))
        assert manifest['status'] == 'failed'
        assert manifest['failure']['stage'] == 'preparation'
        assert manifest['execution_audit_available'] is True
        assert receipt['searches'] == []
        assert receipt['candidates'] == []
        assert receipt['studio_job_id'] == child['id']
        assert current['source_acquisition']['hold'] == hold
        assert current['source_acquisition']['rounds'] == state['source_acquisition']['rounds']
        assert 'planning_preparation' not in child['checkpoint']
        with studio.store.connect() as db:
            saved = db.execute('SELECT status,checkpoint FROM jobs WHERE id=?',(owner['id'],)).fetchone()
        assert saved['status'] == 'done'
        assert json.loads(saved['checkpoint']) == owner['checkpoint']
        assert captured == json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    finally:
        studio.close()

from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.source_preparation import PreparationEvidenceWaiting


@pytest.mark.parametrize('defect', ['run', 'round', 'owner'])
def test_actual_collect_entry_rejects_invalid_planning_recovery(tmp_path, defect):
    captured = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    state = copy.deepcopy(captured['task'])
    owner = copy.deepcopy(captured['job'])
    assert owner['id'] == 'job-485595b8bd9e412d'
    assert owner['status'] == 'done'
    assert state['source_acquisition']['hold']['reason'] == 'strategy_exhausted'
    hold = copy.deepcopy(state['source_acquisition']['hold'])
    # The invalid binding must fail before any external media/model/browser I/O.
    # Preserve the incident task/run, original done owner and causal hold.
    # The child has no prior attempts; its empty checkpoint is its normal initial state.
    child = dict(id='isolated-planning-child', task_id=state['id'],
        kind='collect_sources', key='isolated-planning-child', status='running',
        payload=dict(run_id=state['run_id'],
                     round=state['source_acquisition']['round'],
                     planning_recovery_from=owner['id']),
        checkpoint={'_claim_token':'isolated-claim'}, claim_token='isolated-claim',
        error='', created=1, updated=1)
    if defect == 'run':
        child['payload']['run_id'] = 'different-run'
    elif defect == 'round':
        child['payload']['round'] += 1
    else:
        child['payload']['planning_recovery_from'] = 'missing-owner'
    studio = Studio(Settings(data_dir=tmp_path), workers=False)
    state.setdefault('revision', 0)
    with studio.store.transaction() as db:
        db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)',
            (state['id'], state['shortcode'], state['revision'], json.dumps(state), 1))
        for job in (owner, child):
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)',
                (job['id'], state['id'], job['kind'], job['key'],
                 json.dumps(job['payload']), job['status'],
                 json.dumps(job['checkpoint']), job.get('error',''),
                 job.get('created',1), job.get('updated',1)))
    with pytest.raises(PreparationEvidenceWaiting, match='결속') as failure:
        studio._collect_sources(studio.store.get(state['id']), child)
    # The unchanged lifecycle sends this exception to this production dispatch.
    # Exercise its real store write; do not substitute a fake persistence layer.
    from hotpost.source_wait_dispatch import defer_source_wait
    import time
    defer_source_wait(studio.store, child, failure.value, time.time())
    with studio.store.connect() as db:
        deferred = db.execute('SELECT status,checkpoint FROM jobs WHERE id=?',
                              (child['id'],)).fetchone()
    persisted = json.loads(deferred['checkpoint'])
    assert deferred['status'] == 'queued'
    assert persisted['deferred_wait'] is False
    assert persisted['retry_requested'] is True
    assert persisted['auto_retries'] == 1
    assert persisted['not_before'] > 0
    assert 'planning_preparation' not in persisted
    assert studio.store.get(state['id'])['source_search']['status'] == 'queued'
    assert studio.store.get(state['id'])['source_acquisition']['hold'] == hold
    with studio.store.connect() as db:
        saved = db.execute('SELECT status,checkpoint FROM jobs WHERE id=?', (owner['id'],)).fetchone()
    assert saved['status'] == 'done'
    assert json.loads(saved['checkpoint']) == owner['checkpoint']
    assert captured == json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
