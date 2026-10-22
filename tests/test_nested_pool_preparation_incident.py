import copy
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from hotpost import source_visual_queries as visual
from hotpost import source_preparation as preparation
from hotpost import source_finder as finder
from hotpost import studio_sources
from hotpost.config import Settings


@pytest.mark.parametrize('successful',[False,True])
def test_saved_child_preparation_recovers_nested_pool(tmp_path,monkeypatch,successful):
    captured=json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    task,job=copy.deepcopy(captured['task']),copy.deepcopy(captured['job'])
    assert job['id']=='job-7acdf5827d1d4127'
    assert job['status']=='paused'
    assert job['checkpoint']['failure_trace']['type']=='PreparationEvidenceWaiting'
    assert not job['checkpoint'].get('planning_preparation')
    assert job['payload']['run_id']==task['run_id']
    assert job['payload']['round']==task['source_acquisition']['round']
    assert job['payload']['planning_recovery_from']=='job-485595b8bd9e412d'
    from hotpost.video_agent_actions import _gate,ActionHeld
    from hotpost.video_agent_planning_claim import planning_recovery_candidate
    assert planning_recovery_candidate(task,job)
    assert _gate(task,'retry_repaired',job) is None
    for field,value in [('run_id','foreign'),('round',-1),('source_policy',{}),('planning_recovery_from','foreign')]:
        bad=copy.deepcopy(job);bad['payload'][field]=value
        assert not planning_recovery_candidate(task,bad)
        with pytest.raises(ActionHeld):_gate(task,'retry_repaired',bad)
    for field,value in [('waiting',{'searches':[{'status':'login_required'}]}),('receipt_wait',{'reason':'unsettled'})]:
        bad=copy.deepcopy(task);bad['source_acquisition'][field]=value
        with pytest.raises(ActionHeld):_gate(bad,'retry_repaired',job)
    bad=copy.deepcopy(task);bad['automation']['paused_by_user']=True
    with pytest.raises(ActionHeld):_gate(bad,'retry_repaired',job)
    artifacts=captured['artifacts']
    if isinstance(artifacts,dict):
        artifacts=[dict(v,path=k) if isinstance(v,dict) else dict(path=k,content=v) for k,v in artifacts.items()]
    row=next(r for r in artifacts if '/empty-recovery-' in r['path'].replace(chr(92),'/') and r['path'].replace(chr(92),'/').endswith('/receipt.json'))
    saved=json.loads(row.get('content',row.get('text')))
    assert saved['queries']==[] and not saved['approved_query_pool']['ready']
    assert all(not q['observation_ids'] and not q['frame_ids'] for q in saved['proposal']['queries'])
    reference=tmp_path/'reference.mp4';reference.write_bytes(b'isolated reference')
    frames=[]
    for i in range(len(saved['evidence']['frames'])):
        p=tmp_path/('f%d.jpg'%i);Image.new('RGB',(16,16),(i,20,30)).save(p);frames.append(p)
    text=copy.deepcopy(saved['evidence']['text'])
    evidence=visual.binding(reference,frames,text['caption'],text,search_minimums=saved['evidence']['search_minimums'],subject_hint=saved['evidence']['subject_hint'])
    key=visual.digest(evidence)
    saved.update(evidence=evidence,input_sha256=key);saved['review']['input_sha256']=key
    assert visual.verify(saved)==[]
    root=tmp_path/'source-visual-queries'/key
    nested=root/('empty-recovery-'+visual.digest(saved));nested.mkdir(parents=True)
    for p in (root/'receipt.json',nested/'receipt.json'):p.write_text(json.dumps(saved,ensure_ascii=False),'utf8')
    original={p:p.read_bytes() for p in (root/'receipt.json',nested/'receipt.json')}
    settings=Settings(data_dir=tmp_path)
    settings.source_query_model_enabled=True;settings.source_match_mode='appearance'
    from hotpost.source_policy import run_policy
    from hotpost.source_diversity import acquisition_policy
    state=copy.deepcopy(task);state['reference_video']=str(reference.resolve())
    config=acquisition_policy(state,run_policy(state))
    scope=studio_sources.search_scope_for_state(state);scope['reference_sha256']=preparation.digest(reference)
    history=copy.deepcopy([*state['source_acquisition'].get('rounds',[]),*state['source_acquisition'].get('interrupted_attempts',[])])
    def isolate(value):
        if isinstance(value,dict):return {k:isolate(v) for k,v in value.items()}
        if isinstance(value,list):return [isolate(v) for v in value]
        if isinstance(value,str) and value.replace(chr(92),'/').endswith('/manifest.json'):
            import hashlib
            return str(tmp_path/'absent'/hashlib.sha256(value.encode()).hexdigest()/'manifest.json')
        return value
    # Same task/job/run, round, policy, scope and history reach the real finder
    # from the preserved no-descriptor branch. Historical files not captured
    # here remain absent in isolation; their integrity is not claimed. The
    # unchanged host pinned tests cover signed retry, parking and real claim.
    context=dict(task_id=task['id'],job_id=job['id'],run_id=task['run_id'],search_context=scope,source_policy=config,rounds=isolate(history),expected_reference_sha256=preparation.digest(reference),preparation_only=True)
    sheet=tmp_path/'sheet.jpg';sheet.write_bytes(frames[0].read_bytes())
    accepted=preparation.acquisition_bundle_path(settings,state['shortcode'],text['caption'],text,config,state['product'])
    empty=visual.apply_visual_queries(dict(products=[],query_details=[],query_evidence=text,search_minimums=config['search_minimums']),saved,reference_sha256=preparation.digest(reference))
    empty.update(source_policy=config,run_id=task['run_id'],search_context=scope)
    assert not preparation.reusable_query_contract(empty,config,state['product'],context)
    preparation.save_bundle(accepted,text['caption'],text,reference,frames,sheet,transcript=text,query_plan=empty,visual_product_queries=[],google_vision_terms=[],openclip_product_evidence=[],subject_reference_indices=[])
    accepted_bytes=accepted.read_bytes()
    valid=copy.deepcopy(saved['proposal']);valid['reference_scenes']=[]
    valid['observations']=[dict(id='fixture',text='Isolated frame',frame_ids=['frame-1'])]
    compact={'eau de toilette':'EDT','bottle-neck jacquard ribbon':'bottle-neck-jacquard-ribbon'}
    for term in valid['subject_identity']['required_terms']:
        assert term['quote'] in text[term['source']]
        term['terms']['en']=[compact.get(v,v) for v in term['terms']['en']]
    valid['queries']=[]
    for lang,variants in {'en':['','rose','peony','bergamot','white-musk'],'zh':['','玫瑰','牡丹','佛手柑','白麝香']}.items():
        identity=valid['subject_identity']
        base=' '.join([identity['product_terms'][lang][0]]+[r['terms'][lang][0] for r in identity['required_terms']])
        for i,modifier in enumerate(variants):
            valid['queries'].append(dict(id=lang+str(i),query=' '.join(filter(None,[modifier,base])),language=lang,observation_ids=['fixture'],frame_ids=['frame-1']))
    calls=[]
    def model(settings,instruction,data,**kwargs):
        calls.append(copy.deepcopy(data))
        if 'proposal_sha256' not in data:
            feedback=data['planning_feedback']
            assert feedback['previous_proposal']==saved['proposal']
            assert feedback['independent_review']==saved['review']
            assert feedback['accepted_query_pool']==saved['approved_query_pool']
            return copy.deepcopy(valid if successful else saved['proposal'])
        assert data['input_sha256']==key
        if not successful:return copy.deepcopy(saved['review'])
        return dict(input_sha256=key,proposal_sha256=visual.digest(valid),subject_identity_supported=True,core_identity_complete=True,checks=[dict(query_id=q['id'],supported=True,central_product=True,short_noun_phrase=True,no_unobserved_claims=True,core_identity_preserved=True) for q in valid['queries']])
    class ExternalVerifier:
        error='';available=False;product_evidence=[];subject_reference_indices=[]
        def __init__(self,*a):pass
    monkeypatch.setattr(finder,'_post',lambda *a:SimpleNamespace(is_video=True,kind='reel',caption=text['caption'],url='https://reference.invalid'))
    monkeypatch.setattr(finder,'_transcript_evidence',lambda *a:copy.deepcopy(text))
    monkeypatch.setattr(finder,'OpenClipVerifier',ExternalVerifier)
    monkeypatch.setattr('hotpost.text_overlay.TextOverlayDetector',lambda *a:SimpleNamespace(note=''))
    monkeypatch.setattr('hotpost.source_planning.cached_enrich_plan',lambda *a,**kw:dict(products=[],primary_subject={'name':state['product']},query_evidence=copy.deepcopy(text),query_details=[],search_minimums=config['search_minimums']))
    monkeypatch.setattr('hotpost.script_rewriter._generate',model)
    attempts=[]
    def progress(message,pct):pass
    progress.source_attempt_created=lambda p:attempts.append(Path(p))
    progress.visual_query_input=lambda value:dict(task_id=task['id'],job_id=job['id'],run_id=task['run_id'],input_sha256=value)
    def prepare():
        return finder.find_sources(settings,state['shortcode'],progress,search_request=state.get('source_search_brief',''),search_round=job['payload']['round'],previous_searches=studio_sources.current_search_rows(state),exclude_urls=[*state['source_acquisition'].get('urls',[]),*state['source_acquisition'].get('inspected_urls',[])],search_context=context)
    source=inspect.getsource(visual.cached_visual_queries)
    start=source.index('        if (search_minimums and _empty_recovery is not None')
    end=source.index('        return receipt',start)
    namespace=dict(visual.__dict__)
    exec(compile(source[:start]+source[end:],'<old-cache-route>','exec'),namespace)
    with monkeypatch.context() as old:
        old.setattr(visual,'cached_visual_queries',namespace['cached_visual_queries'])
        with pytest.raises(preparation.PreparationEvidenceWaiting,match='독립 검토 검색 근거'):prepare()
    failure_path=attempts[-1];failure_bytes=failure_path.read_bytes()
    failure=json.loads(failure_bytes)
    assert failure['status']=='failed' and failure['failure']['type']=='PreparationEvidenceWaiting'
    assert failure['search_audit']==[] and failure['candidates']==[] and calls==[]
    if successful:
        result=prepare()
        assert result['preparation_only'] is True and result['run_id']==task['run_id']
        assert result['search_context']==scope
        assert len(visual.plan_queries(result['query_plan']))==10
        assert preparation.reusable_query_contract(result['query_plan'],config,state['product'],context)
        selected=Path(result['preparation_bundle_path'])
        assert selected.resolve()==preparation.replanning_bundle_path(accepted,result['query_plan']).resolve()
        assert selected!=accepted and preparation.digest(selected)==result['preparation_bundle_sha256']
        manifest=json.loads(attempts[-1].read_text('utf8'))
        assert manifest['status']=='prepared' and manifest['audit_checkpoint']=='preparation_complete'
        assert manifest['preparation_bundle_sha256']==preparation.digest(selected)
        assert manifest['search_audit']==[] and manifest['candidates']==[]
    else:
        with pytest.raises(preparation.PreparationEvidenceWaiting,match='독립 검토 검색 근거'):prepare()
    assert len(calls)==2
    def forbidden(*a,**kw):raise AssertionError('bounded recovery must reuse receipt')
    for _ in range(3):
        receipt=visual.cached_visual_queries(settings,reference,frames,text['caption'],text,forbidden,search_minimums=evidence['search_minimums'],subject_hint=evidence['subject_hint'])
        assert len(visual.verify(receipt))==(10 if successful else 0)
    damaged=copy.deepcopy(receipt);damaged['review']['proposal_sha256']='0'*64
    with pytest.raises(ValueError):visual.verify(damaged)
    reference.write_bytes(b'changed')
    with pytest.raises(ValueError):visual.verify(receipt)
    assert failure_path.read_bytes()==failure_bytes
    assert accepted.read_bytes()==accepted_bytes
    assert all(p.read_bytes()==b for p,b in original.items())
    assert len(list((tmp_path/'source-visual-pool-recoveries').glob('*/receipt.json')))==1
    assert not list((tmp_path/'source-visual-pool-recoveries').glob('*/empty-recovery-*'))
    assert task==captured['task'] and job==captured['job']
    assert captured==json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
