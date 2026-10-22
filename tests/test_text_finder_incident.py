import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image


def test_original_child_text_preparation_without_tiktok_syntax_bypass(tmp_path, monkeypatch):
    from hotpost import source_finder as finder, source_preparation as preparation
    from hotpost import source_visual_queries as visual, studio_sources
    from hotpost.config import Settings
    from hotpost.source_queries import tiktok_product_queries, _clean_tiktok_syntax
    from hotpost.source_text_query_receipts import plan_text_queries
    captured = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    task, job = copy.deepcopy(captured['task']), copy.deepcopy(captured['job'])
    assert job['id'] == 'job-7acdf5827d1d4127'
    assert job['task_id'] == task['id']
    assert job['checkpoint']['internal_evidence_wait'] is True
    assert not job['checkpoint'].get('planning_preparation')
    assert job['payload']['planning_recovery_from'] == 'job-485595b8bd9e412d'
    assert job['payload']['run_id'] == task['run_id']
    hold = copy.deepcopy(task['source_acquisition']['hold'])
    row = next(r for r in captured['artifacts'] if r.get('sha256') ==
        'b32e45bae5f0646a2d9e1b33872098774b1669855a2a7a41d68bb43734a5ba66')
    assert row['truncated'] is False
    saved = copy.deepcopy(json.loads(row['content']))
    assert saved['queries'] == []
    identity = copy.deepcopy(saved['search_identity'])
    assert len(identity['required_terms']) == 4
    reference = tmp_path/'reference.mp4'; reference.write_bytes(b'isolated reference')
    frames = []
    for i in range(len(saved['evidence']['frames'])):
        p = tmp_path/('f%d.jpg' % i)
        Image.new('RGB',(16,16),(i,20,30)).save(p); frames.append(p)
    text = copy.deepcopy(saved['evidence']['text'])
    evidence = visual.binding(reference,frames,text['caption'],text,
        search_minimums=saved['evidence']['search_minimums'],subject_hint=saved['evidence']['subject_hint'])
    saved.update(evidence=evidence,input_sha256=visual.digest(evidence))
    saved['review']['input_sha256'] = saved['input_sha256']
    assert visual.verify(saved) == []
    settings = Settings(data_dir=tmp_path)
    settings.source_query_model_enabled = True
    settings.source_match_mode = 'appearance'
    state = copy.deepcopy(task); state['reference_video'] = str(reference.resolve())
    from hotpost.source_policy import run_policy
    from hotpost.source_diversity import acquisition_policy
    config = acquisition_policy(state,run_policy(state))
    scope = studio_sources.search_scope_for_state(state)
    def isolate(value):
        if isinstance(value,dict):return {k:isolate(v) for k,v in value.items()}
        if isinstance(value,list):return [isolate(v) for v in value]
        if isinstance(value,str) and value.replace(chr(92),'/').endswith('/manifest.json'):
            return str(tmp_path/'absent'/hashlib.sha256(value.encode()).hexdigest()/'manifest.json')
        return value
    # Preserve history descriptors; only path availability is isolated. The
    # preparation sub-entry checks historical acceptance, not deferred search.
    # Signed retry/claim/access transitions remain covered by host pinned tests.
    context = dict(task_id=task['id'],job_id=job['id'],run_id=task['run_id'],
        source_policy=config,search_context=scope,preparation_only=True,
        expected_reference_sha256=preparation.digest(reference),
        rounds=isolate(copy.deepcopy([*state['source_acquisition'].get('rounds',[]),
            *state['source_acquisition'].get('interrupted_attempts',[])])))
    root = tmp_path/'source-visual-queries'/saved['input_sha256']
    root.mkdir(parents=True)
    cache = root/'receipt.json'; cache.write_text(json.dumps(saved,ensure_ascii=False),'utf8')
    # Supply fresh honest empty visual responses when the bounded visual
    # recovery is requested. No product observation is fabricated.
    calls = []
    base = 'Dior floral eau de toilette perfume bottle-neck jacquard ribbon'
    assert _clean_tiktok_syntax(base) == ''
    queries = []
    for lang, words in {'en':['','rose','peony','bergamot','white musk'],
                        'zh':['','玫瑰','牡丹','佛手柑','白麝香']}.items():
        noun = base if lang == 'en' else 'Dior 花香调淡香水 瓶颈提花缎带 香水'
        for i, modifier in enumerate(words):
            word = ' '.join(filter(None,[modifier,noun]))
            assert len(word) <= 80
            # Quote the complete original caption, preserving its newlines.
            queries.append(dict(id=lang+str(i),query=word,language=lang,
                text_quotes=[dict(source='caption',quote=text['caption'])]))
    def model(settings,instruction,data,**kwargs):
        calls.append(copy.deepcopy(data))
        if data.get('contract') == 'quoted-text-search-v1':
            return dict(queries=copy.deepcopy(queries))
        if data.get('evidence',{}).get('contract') == 'quoted-text-search-v1':
            return dict(input_sha256=data['input_sha256'],proposal_sha256=data['proposal_sha256'],
                text_search_only=True,core_identity_complete=True,checks=[dict(query_id=q['id'],
                    supported=True,central_product=True,short_noun_phrase=True,
                    no_unobserved_claims=True,core_identity_preserved=True,
                    quoted_modifiers_supported=True) for q in data['proposal']['queries']])
        if 'proposal_sha256' not in data:return copy.deepcopy(saved['proposal'])
        verdict = copy.deepcopy(saved['review'])
        verdict.update(input_sha256=data['input_sha256'],proposal_sha256=data['proposal_sha256'])
        return verdict
    sheet = tmp_path/'sheet.jpg'; sheet.write_bytes(frames[0].read_bytes())
    accepted = preparation.acquisition_bundle_path(settings,state['shortcode'],text['caption'],text,config,state['product'])
    empty = visual.apply_visual_queries(dict(products=[],query_details=[],query_evidence=text,
        search_minimums=config['search_minimums']),saved,reference_sha256=preparation.digest(reference))
    empty.update(source_policy=config,run_id=task['run_id'],search_context=scope)
    preparation.save_bundle(accepted,text['caption'],text,reference,frames,sheet,transcript=text,
        query_plan=empty,visual_product_queries=[],google_vision_terms=[],
        openclip_product_evidence=[],subject_reference_indices=[])
    original = {cache:cache.read_bytes(),accepted:accepted.read_bytes()}
    class ExternalVerifier:
        error=''; available=False; product_evidence=[]; subject_reference_indices=[]
        def __init__(self,*a):pass
    monkeypatch.setattr(finder,'_post',lambda *a:SimpleNamespace(is_video=True,kind='reel',caption=text['caption'],url='https://reference.invalid'))
    monkeypatch.setattr(finder,'_transcript_evidence',lambda *a:copy.deepcopy(text))
    monkeypatch.setattr(finder,'OpenClipVerifier',ExternalVerifier)
    monkeypatch.setattr('hotpost.text_overlay.TextOverlayDetector',lambda *a:SimpleNamespace(note=''))
    monkeypatch.setattr('hotpost.source_planning.cached_enrich_plan',lambda *a,**kw:dict(products=[],primary_subject={'name':state['product']},query_evidence=copy.deepcopy(text),query_details=[],search_minimums=config['search_minimums']))
    monkeypatch.setattr('hotpost.script_rewriter._generate',model)
    attempts = []
    def progress(message,pct):pass
    progress.source_attempt_created = lambda p:attempts.append(Path(p))
    # Exercise the actual production callback: owner return and checkpoint SHA
    # are distinct contracts. Persistence I/O alone is isolated to a JSON file.
    runtime_job = copy.deepcopy(job)
    checkpoint_path = tmp_path/'captured-checkpoint.json'
    def checkpoint(current, value):
        assert current['id'] == job['id']
        checkpoint_path.write_text(json.dumps(value,ensure_ascii=False),'utf8')
    runtime = SimpleNamespace(settings=settings,store=SimpleNamespace(checkpoint=checkpoint))
    def capture_progress(message,pct):pass
    studio_sources.SourceAcquisitionMixin._bind_source_attempt_progress(
        runtime,state,runtime_job,capture_progress)
    progress.visual_query_input = capture_progress.visual_query_input
    expected_owner = {k:context[k] for k in ('task_id','job_id','run_id')}
    assert progress.visual_query_input(saved['input_sha256']) == expected_owner
    assert json.loads(checkpoint_path.read_text('utf8'))['visual_query_input'] == {
        **expected_owner,'input_sha256':saved['input_sha256']}
    def prepare():
        return finder.find_sources(settings,state['shortcode'],progress,search_round=job['payload']['round'],
            previous_searches=studio_sources.current_search_rows(state),search_context=context)
    # Remove only the new text orchestration block to execute the previous
    # production route. All preparation and evidence validators remain real.
    source = inspect.getsource(finder._find_sources)
    start = source.index('    if (settings.source_query_model_enabled and not reuse_plan')
    end = source.index('    from .source_search.planner import grounded_actions',start)
    namespace = dict(finder.__dict__)
    exec(compile(source[:start]+source[end:],'<previous-finder-route>','exec'),namespace)
    with monkeypatch.context() as old:
        old.setattr(finder,'_find_sources',namespace['_find_sources'])
        with pytest.raises(preparation.PreparationEvidenceWaiting,match='독립 검토 검색 근거'):prepare()
    failed = attempts[-1]; failed_bytes = failed.read_bytes()
    assert json.loads(failed_bytes)['failure']['type'] == 'PreparationEvidenceWaiting'
    # Change bytes after the real callback persisted the original input SHA.
    # Fresh external responses cannot make that captured input match new media.
    original_reference_bytes = reference.read_bytes()
    def changed_after_capture(value):
        owner = capture_progress.visual_query_input(value)
        reference.write_bytes(b'changed after production input capture')
        return owner
    with monkeypatch.context() as invalid_capture:
        invalid_capture.setattr(progress,'visual_query_input',changed_after_capture)
        with pytest.raises(preparation.PreparationEvidenceWaiting,match='현재 작업·실행 결속'):prepare()
    reference.write_bytes(original_reference_bytes)
    invalid_path = attempts[-1]
    invalid_bytes = invalid_path.read_bytes()
    assert json.loads(invalid_bytes)['failure']['type'] == 'PreparationEvidenceWaiting'
    result = prepare()
    assert invalid_path.read_bytes() == invalid_bytes
    assert result['preparation_only'] is True
    persisted = json.loads(checkpoint_path.read_text('utf8'))['visual_query_input']
    assert persisted == {**expected_owner,'input_sha256':saved['input_sha256']}
    assert runtime_job['id'] == job['id']
    plan = result['query_plan']
    assert plan['query_owner'] == {k:context[k] for k in ('task_id','job_id','run_id')}
    assert plan['search_identity'] == identity
    assert len(plan_text_queries(plan)) == 10
    assert preparation.reusable_query_contract(plan,config,state['product'],context)
    dispatched = tiktok_product_queries(plan)
    assert dispatched == [q['query'] for q in queries if q['language'] == 'zh']
    assert len(dispatched) == 5
    assert all(_clean_tiktok_syntax(q) == q for q in dispatched)
    assert all(_clean_tiktok_syntax(q['query']) == '' for q in queries if q['language'] == 'en')
    from hotpost.source_search.planner import round_queries
    assert len(round_queries(plan,{'phase':'core_action'})) == 10
    manifest = json.loads(attempts[-1].read_text('utf8'))
    assert manifest['status'] == 'prepared'
    assert manifest['search_audit'] == [] and manifest['candidates'] == []
    assert failed.read_bytes() == failed_bytes
    assert all(p.read_bytes() == b for p,b in original.items())
    bad = copy.deepcopy(context); bad['job_id'] = 'foreign'
    assert not preparation.reusable_query_contract(plan,config,state['product'],bad)
    bad_plan = copy.deepcopy(plan); bad_plan['text_query_evidence']['review']['proposal_sha256'] = '0'*64
    with pytest.raises(ValueError):plan_text_queries(bad_plan)
    assert task['source_acquisition']['hold'] == hold
    assert task == captured['task'] and job == captured['job']
    assert captured == json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
