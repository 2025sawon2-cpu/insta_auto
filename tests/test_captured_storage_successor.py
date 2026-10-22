import copy
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

import pytest
from hotpost.config import Settings
from hotpost.source_pause_receipts import verified_receipt, SourceReceiptWaiting
from hotpost.source_search.readiness import readiness_blocked, readiness_record
from hotpost.source_search.strategy import fresh_queries
from hotpost.source_access_preflight import check_access, observe_routes, SourceAccessWaiting
from test_source_pause_history import Harness
from hotpost.studio_store import StudioStore


@pytest.mark.parametrize('damage', [None, 'worker', 'task', 'login', 'run', 'reference', 'submit_intent'])
def test_captured_original_receipt_successor(tmp_path, damage):
    original = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    fixture = copy.deepcopy(original)
    state, job = fixture['task'], fixture['job']
    rows = fixture['artifacts']
    if isinstance(rows, dict):
        rows = [dict(v, path=k) if isinstance(v, dict) else dict(path=k, content=v) for k,v in rows.items()]
    texts = {r['path']:r['content'] for r in rows if isinstance(r,dict) and isinstance(r.get('content'),str)}
    accepted = next(r for r in state['source_acquisition']['interrupted_attempts']
        if r.get('receipt_sha256') == 'a41f23b58b061a9f645e02a2ec6168676ea2283ce15f1fb47025032ae6fe7f82')
    receipt_path = accepted['receipt_path']
    digest = lambda text:hashlib.sha256(text.encode('utf8')).hexdigest()
    if receipt_path not in texts:
        pytest.fail('Captured causal receipt missing: ' + receipt_path + '; captured paths: ' + repr(sorted(texts)), pytrace=False)
    assert receipt_path in texts
    assert digest(texts[receipt_path]) == accepted['receipt_sha256']
    receipt = json.loads(texts[receipt_path])
    required = [receipt['manifest_path'], *[w['path'] for w in receipt['worker_checkpoints']]]
    missing = [p for p in required if p not in texts]
    if missing:
        pytest.fail('Captured registered evidence missing: ' + repr(missing), pytrace=False)
    assert not missing
    assert digest(texts[required[0]]) == receipt['manifest_sha256']
    for w in receipt['worker_checkpoints']:
        assert digest(texts[w['path']]) == w['sha256']
    assert receipt['studio_job_id'] == 'job-ab4c02837a2d4eca'
    settings = Settings(data_dir=tmp_path, source_browser_search=True)
    root = PureWindowsPath(receipt['manifest_path']).parent
    local_root = (settings.source_dir/root.name).resolve()
    reference = tmp_path/'reference.mp4'
    reference.write_bytes(b'isolated captured reference')
    substitutions = {str(root).replace(chr(92),chr(92)*2):str(local_root),
        str(root):str(local_root), receipt['reference_sha256']:hashlib.sha256(reference.read_bytes()).hexdigest()}
    def transform(value):
        if isinstance(value,dict):return {transform(k):transform(v) for k,v in value.items()}
        if isinstance(value,list):return [transform(v) for v in value]
        if isinstance(value,str):
            import re
            # Match the original text once: replacement paths can themselves
            # contain the production data prefix in the isolated Windows stage.
            pattern = '|'.join(re.escape(key) for key in sorted(substitutions,key=len,reverse=True))
            return re.sub(pattern,lambda match:substitutions[match.group(0)],value)
        return value
    def local(raw):return local_root.joinpath(*PureWindowsPath(raw).relative_to(root).parts).resolve()
    def write(path,value):
        assert path.is_relative_to(tmp_path.resolve())
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,ensure_ascii=False),'utf8')
        return hashlib.sha256(path.read_bytes()).hexdigest()
    # Map every captured data path before running the real preparation gate.
    data_root = root.parent.parent
    substitutions[str(data_root).replace(chr(92),chr(92)*2)] = str(tmp_path.resolve())
    substitutions[str(data_root)] = str(tmp_path.resolve())
    from hotpost.source_preparation import payload_key
    bundles = []
    for raw, text in texts.items():
        try:value = json.loads(text)
        except ValueError:continue
        if isinstance(value,dict) and value.get('policy') == 'source-preparation-sha-v1':
            assert digest(text) == next(r['sha256'] for r in rows if r.get('path') == raw)
            bundles.append((raw,value))
    assert bundles, 'Captured preparation bundle is required for the production gate'
    for raw, value in bundles:
        for item in value['files']:
            target = Path(transform(item['path']))
            assert target.is_relative_to(tmp_path.resolve())
            target.parent.mkdir(parents=True,exist_ok=True)
            content = reference.read_bytes() if item['path'] == value['reference'] else b'isolated preparation frame' + item['path'].encode()
            target.write_bytes(content)
            substitutions[item['sha256']] = hashlib.sha256(content).hexdigest()
        mapped = transform(value)
        mapped['payload_sha256'] = payload_key(mapped)
        substitutions[digest(texts[raw])] = write(Path(transform(raw)),mapped)
    # Original text hashes above precede path/reference rebinding in a deep copy.
    if damage == 'submit_intent':
        causal_query = next(r['readiness']['query'] for r in job['checkpoint']['parser_repair_context']['observations'] if r['provider']=='tiktok')
        def mark(value):
            if isinstance(value,dict):
                if value.get('provider')=='tiktok' and value.get('query')==causal_query and value.get('status')=='page_unresolved':
                    value.setdefault('execution',{})['submit_intent']=True
                for child in value.values():mark(child)
            elif isinstance(value,list):
                for child in value:mark(child)
        mark(state);mark(receipt)
    for raw in required:
        document = json.loads(texts[raw])
        if damage == 'submit_intent':mark(document)
        substitutions[digest(texts[raw])] = write(local(raw),transform(document))
    mapped_receipt = transform(receipt)
    assert Path(mapped_receipt['manifest_path']).resolve() == local(required[0])
    assert Path(mapped_receipt['manifest_path']).resolve().parent.parent == settings.source_dir.resolve()
    receipt_sha = write(local(receipt_path),mapped_receipt)
    substitutions[accepted['receipt_sha256']] = receipt_sha
    state,job,accepted = transform(state),transform(job),transform(accepted)
    state['reference_video'] = str(reference.resolve())
    # This production sub-entry depends on this exact receipt and current gate.
    # Other rounds are independent; pinned host retry/ownership tests cover them.
    state['source_acquisition']['interrupted_attempts'] = [accepted]
    assert not job['checkpoint'].get('source_attempts')
    owned = {**accepted,'workers':[dict(path=w['path'],settled=True) for w in accepted['worker_checkpoints']]}
    owner = {'id':accepted['studio_job_id'],'payload':{'run_id':accepted['run_id'],'request':accepted.get('source_request','')}}
    assert verified_receipt(settings.source_dir,owned,state,owner) == mapped_receipt
    saved = next(r['readiness'] for r in job['checkpoint']['parser_repair_context']['observations'] if r['provider']=='tiktok')
    query = saved['query']
    write(tmp_path/'search_readiness'/'tiktok.json',saved)
    assert readiness_blocked(tmp_path,'tiktok')
    assert fresh_queries([query],'tiktok',state['source_acquisition']['queries']) == []
    immutable = {local(p):local(p).read_bytes() for p in [receipt_path,*required]}
    h = Harness()
    h.settings = settings
    # Seed only the isolated database; preserve the captured causal identity.
    store_root = tmp_path/'isolated-studio'
    h.store = StudioStore(store_root)
    state.setdefault('revision', 0)
    job['claim_token'] = job['checkpoint']['_claim_token']
    with h.store.transaction() as db:
        db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)',
            (state['id'], state['shortcode'], state['revision'], json.dumps(state,ensure_ascii=False), 0))
        db.execute('INSERT INTO jobs(id,task_id,kind,key,payload,status,checkpoint,error,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (job['id'], state['id'], job['kind'], 'isolated-captured:'+job['id'],
             json.dumps(job['payload']), 'running', json.dumps(job['checkpoint']), '', 0, 0))
    h.store.assert_owned(job)
    if damage == 'worker':local(required[1]).write_text('{}','utf8')
    if damage == 'task':job['checkpoint']['parser_repair_context']['task_id'] = 'foreign'
    if damage == 'run':job['checkpoint']['parser_repair_context']['run_id'] = 'foreign'
    if damage == 'reference':reference.write_bytes(b'changed current reference')
    if damage == 'login':
        write(tmp_path/'search_cooldowns'/'tiktok.json',{'reason':'login_required','requires_verification':True,'until':0})
    if damage in {'worker','task','run'}:
        with pytest.raises(SourceReceiptWaiting):h._restore_source_attempt_history(state,job)
        assert readiness_blocked(tmp_path,'tiktok')
    else:
        if damage in {'reference','submit_intent'}:
            h._restore_source_attempt_history(state,job)
            assert readiness_blocked(tmp_path,'tiktok')
            assert not readiness_record(tmp_path,'tiktok').get('storage_failure_recovery')
            assert original == json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
            return
        returned = h._restore_source_attempt_history(state,job)
        # Reopen the real on-disk store: a returned copy is not persistence proof.
        h.store = StudioStore(store_root)
        restored = h.store.get(state['id'])
        assert restored['source_acquisition'] == returned['source_acquisition']
        h.store.assert_owned(job)
        if damage == 'login':
            assert readiness_blocked(tmp_path,'tiktok')
            with pytest.raises(SourceAccessWaiting):check_access(settings,restored,job)
        else:
            assert not readiness_blocked(tmp_path,'tiktok')
            recovery = readiness_record(tmp_path,'tiktok')['storage_failure_recovery']
            assert recovery['receipt_sha256'] == receipt_sha
            assert recovery['previous_readiness'] == saved
            assert recovery['job_id'] == original['job']['id']
            assert fresh_queries([query],'tiktok',restored['source_acquisition']['queries']) == [query]
            resolutions = restored['source_acquisition']['search_resolutions']
            assert any(r.get('receipt_sha256') == receipt_sha
                and r.get('basis') == 'settled_worker_pre_input_checkpoint_failure'
                and r.get('previous',{}).get('query') == query for r in resolutions)
            persisted_rows = [r for r in restored['source_acquisition']['queries']
                if r.get('provider') == 'tiktok' and r.get('query') == query]
            assert persisted_rows
            assert all(r['execution'].get('resolution') == 'confirmed_not_submitted'
                and r['execution'].get('resolution_receipt_sha256') == receipt_sha
                for r in persisted_rows)
            class Body:
                def inner_text(self, **kwargs):return 'Search products and videos'
            class Page:
                url = 'https://www.tiktok.com/search'
                def locator(self, selector):
                    assert selector == 'body'
                    return Body()
            def observe(settings, providers):return observe_routes(settings,['tiktok'],context=object())
            from types import SimpleNamespace
            from hotpost.source_preparation import preflight_preparation
            manifest = json.loads(local(required[0]).read_text('utf8'))
            caption = manifest.get('caption','')
            from hotpost.source_preparation import evidence_key
            preparation_path = Path(manifest['preparation_bundle_path'])
            assert preparation_path.resolve().is_relative_to(tmp_path.resolve())
            assert hashlib.sha256(preparation_path.read_bytes()).hexdigest() == manifest['preparation_bundle_sha256']
            preparation = json.loads(preparation_path.read_text('utf8'))
            transcript = copy.deepcopy(preparation['transcript'])
            if preparation['evidence_key'] != evidence_key(caption,transcript):
                # Production appends a space and OCR only to processed screen_text;
                # the immutable key still binds the original external response.
                assert transcript.get('reference_kind') not in {'screen_text','mixed'}
                processed = transcript.get('screen_text','')
                assert isinstance(processed,str)
                matches = []
                for index, character in enumerate(processed):
                    if character != ' ':continue
                    candidate = {**transcript,'screen_text':processed[:index]}
                    if evidence_key(caption,candidate) == preparation['evidence_key']:
                        matches.append(candidate)
                assert len(matches) == 1, 'Captured raw transcript must match its immutable evidence SHA uniquely'
                transcript = matches[0]
            assert preparation['evidence_key'] == evidence_key(caption,transcript)
            preserved_plan = copy.deepcopy(restored['source_acquisition']['core_search_plan'])
            assert preserved_plan
            # A fresh external review double binds the isolated media, never
            # rewrites an accepted historical receipt or a production approval.
            from hotpost import source_visual_queries as visual
            from hotpost.source_query_identity import checked_identity
            from hotpost.source_policy import run_policy
            from hotpost.source_diversity import acquisition_policy
            from hotpost.source_coverage import search_scope_for_state
            from hotpost.source_preparation import acquisition_bundle_path, save_bundle
            policy = acquisition_policy(restored,run_policy(restored))
            candidate_plan = copy.deepcopy(preparation['query_plan'])
            proposal = copy.deepcopy(candidate_plan['visual_query_evidence']['proposal'])
            frames = [Path(p) for p in preparation['frames']]
            evidence = visual.binding(Path(preparation['reference']),frames,caption,
                preparation['transcript'],search_minimums=policy['search_minimums'],
                subject_hint=restored['product'])
            def external_review_double(data):
                assert data['proposal_sha256'] == visual.digest(proposal)
                assert data['input_sha256'] == visual.digest(evidence)
                return {**data,'subject_identity_supported':True,'core_identity_complete':True,
                    'checks':[{'query_id':q['id'],'supported':True,'central_product':True,
                        'short_noun_phrase':True,'no_unobserved_claims':True,
                        'core_identity_preserved':True,'reason':'isolated external review response'}
                        for q in proposal['queries']]}
            review = external_review_double({'input_sha256':visual.digest(evidence),
                'proposal_sha256':visual.digest(proposal)})
            approved = visual.validate(proposal,review,evidence)
            identity = checked_identity(proposal['subject_identity'])
            pool = visual.query_pool_report(approved,policy['search_minimums'],identity)
            assert pool['ready'], pool
            fresh = {'policy':evidence['policy'],'input_sha256':visual.digest(evidence),
                'evidence':evidence,'proposal':proposal,'review':review,'queries':approved,
                'search_identity':identity,'approved_query_pool':pool}
            assert visual.verify(fresh) == approved
            candidate_plan.update(query_evidence=copy.deepcopy(evidence['text']),
                source_policy=copy.deepcopy(policy),search_minimums=copy.deepcopy(policy['search_minimums']),
                run_id=restored['run_id'],search_context=search_scope_for_state(restored))
            candidate_plan = visual.apply_visual_queries(candidate_plan,fresh,
                reference_sha256=evidence['reference_sha256'])
            preserved_preparation = preparation_path.read_bytes()
            assert 'planning_preparation' not in job['checkpoint']
            model_calls=[]
            def generate(settings,instruction,data,**kwargs):
                model_calls.append(copy.deepcopy(data))
                if 'proposal_sha256' in data:return external_review_double(data)
                if 'frames' in data:
                    assert data == evidence
                    return copy.deepcopy(proposal)
                return {'queries':[],'tiktok_queries':[]}
            from contextlib import ExitStack
            external = ExitStack()
            external.enter_context(patch('hotpost.script_rewriter._generate',side_effect=generate))
            external.enter_context(patch('hotpost.source_finder.OpenClipVerifier',return_value=SimpleNamespace(error='',product_evidence=[],subject_reference_indices=[])))
            external.enter_context(patch('hotpost.text_overlay.TextOverlayDetector',return_value=SimpleNamespace(note='')))
            external.enter_context(patch('hotpost.visual_media.frame_inline_data',return_value={'mimeType':'image/jpeg','data':'isolated'}))
            with external, patch('hotpost.source_finder._post',return_value=SimpleNamespace(caption=caption,is_video=True)), patch('hotpost.source_finder._transcript_evidence',return_value=transcript), patch('hotpost.source_browser_runtime.existing_page',return_value=Page()), patch('hotpost.source_access_preflight.current_routes',side_effect=observe):
                plan, frames = preflight_preparation(settings,restored,job)
                assert plan is None and frames
                # Reproduce the original block before using restored readiness.
                original_checkpoint = copy.deepcopy(job['checkpoint'])
                restored_readiness = copy.deepcopy(readiness_record(tmp_path,'tiktok'))
                write(tmp_path/'search_readiness'/'tiktok.json',saved)
                assert readiness_blocked(tmp_path,'tiktok')
                with pytest.raises(SourceAccessWaiting):h._source_access_gate(restored,job)
                job['checkpoint'] = original_checkpoint
                h.store.checkpoint(job,job['checkpoint'])
                write(tmp_path/'search_readiness'/'tiktok.json',restored_readiness)
                assert not readiness_blocked(tmp_path,'tiktok')
                assert 'planning_preparation' not in job['checkpoint']
                def progress(message,pct):h.store.checkpoint(job,job['checkpoint'])
                # Actual production sub-entry acquires and registers preparation;
                # the collection caller invokes it immediately before the gate.
                restored=h._prepare_source_queries(h.store.get(state['id']),job,progress)
                plan,frames=preflight_preparation(settings,restored,job)
                assert plan is not None and frames
                assert model_calls
                selected=job['checkpoint']['planning_preparation']
                assert selected['job_id']==original['job']['id']
                assert selected['task_id']==original['task']['id']
                assert selected['run_id']==original['task']['run_id']
                assert Path(selected['path']).resolve()!=preparation_path.resolve()
                assert hashlib.sha256(Path(selected['path']).read_bytes()).hexdigest()==selected['sha256']
                assert preparation_path.read_bytes()==preserved_preparation
                # The same production gate must reject the preserved old readiness.
                write(tmp_path/'search_readiness'/'tiktok.json',saved)
                before_gate = copy.deepcopy(job['checkpoint'])
                with pytest.raises(SourceAccessWaiting):h._source_access_gate(restored,job)
                job['checkpoint'] = before_gate
                write(tmp_path/'search_readiness'/'tiktok.json',{**saved,'recheck_requested':True,'storage_failure_recovery':recovery})
                assert h._source_access_gate(h.store.get(state['id']),job) == ['tiktok']
            after_gate = StudioStore(store_root).get(state['id'])
            retained_plan = after_gate['source_acquisition']['core_search_plan']
            assert retained_plan['context'] == preserved_plan['context']
            assert retained_plan['queries'] == preserved_plan['queries']
            assert retained_plan['identity'] == preserved_plan['identity']
            assert set(retained_plan['routes']) >= set(preserved_plan['routes'])
            assert after_gate['source_acquisition'].get('core_fallback') == restored['source_acquisition'].get('core_fallback')
            assert (restored['id'],job['id'],restored['run_id']) == (original['task']['id'],original['job']['id'],original['task']['run_id'])
        assert all(p.read_bytes()==raw for p,raw in immutable.items())
    assert original == json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
