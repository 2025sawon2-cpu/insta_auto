"""Actual preparation entry: preserved unavailable checkpoint to external planning.
No media approval. Original pixels preserve image scope consumption; host pinned
tests cover signed retry/loading outside this production sub-entry.
"""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
import pytest
from hotpost.studio_sources import SourceAcquisitionMixin
from hotpost.source_preparation import PreparationEvidenceWaiting
from test_source_parser_response_incident import browser_fixture, response, transactional_store, install_registered_bundle


def test_preserved_consumed_plan_reaches_external_planning(tmp_path,monkeypatch):
    from hotpost import source_finder, source_parser_recovery, script_rewriter
    from hotpost.editing_adapter import _atomic_json
    from hotpost.source_preparation import acquisition_bundle_path,payload_key,preflight_preparation
    from hotpost.source_diversity import acquisition_policy
    from hotpost.source_policy import run_policy
    from hotpost.source_search.strategy import fresh_frames
    from hotpost.source_coverage import current_search_rows
    from hotpost.source_visual_queries import digest
    fixture=json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    state=copy.deepcopy(fixture['task']);job=copy.deepcopy(fixture['job'])
    assert job['id']=='job-f0a99c40533f423f'
    assert job['task_id']==state['id'] and job['payload']['run_id']==state['run_id']
    failed=copy.deepcopy(job['checkpoint']['parser_response_recovery']['previous_readiness'])
    assert job['checkpoint']['parser_response_recovery']['status']=='unavailable'
    def relocate(value):
        if isinstance(value,dict):return {k:relocate(v) for k,v in value.items()}
        if isinstance(value,list):return [relocate(v) for v in value]
        if isinstance(value,str) and PureWindowsPath(value).is_absolute():
            return str(tmp_path/'relocated'/hashlib.sha256(value.encode()).hexdigest())
        return value
    state,job=relocate(state),relocate(job)
    assert state['id']==fixture['task']['id'] and job['id']==fixture['job']['id']
    assert state['source_acquisition']['queries']==fixture['task']['source_acquisition']['queries']
    settings,page=browser_fixture(monkeypatch,tmp_path,failed['query'])
    _atomic_json(tmp_path/'search_readiness'/'tiktok.json',failed)
    reference=tmp_path/'reference.mp4';reference.write_bytes(b'isolated reference')
    state['reference_video']=str(reference)
    bundle,caption,raw=install_registered_bundle(fixture,state,job,settings,tmp_path)
    captured={r['sha256']:r for g in fixture['preparation_frame_evidence']
        if g['task_id']==state['id'] and g['run_id']==state['run_id'] for r in g['frames']}
    originals=[json.loads(a['content']) for a in fixture['artifacts']
        if 'content' in a and 'source-preparation-sha-v1' in a['content']]
    original=next(v for v in originals if isinstance(v,dict) and v.get('policy')=='source-preparation-sha-v1')
    changes={}
    for old,new in zip(original['files'],bundle['files']):
        if old['sha256'] not in captured:continue
        row=captured[old['sha256']]
        data=base64.b64decode(row['data_base64'],validate=True)
        assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==old['sha256']
        Path(new['path']).write_bytes(data);changes[new['sha256']]=old['sha256']
    def rewrite(v):
        if isinstance(v,dict):return {k:rewrite(x) for k,x in v.items()}
        if isinstance(v,list):return [rewrite(x) for x in v]
        return changes.get(v,v) if isinstance(v,str) else v
    bundle=rewrite(bundle);state=rewrite(state);job=rewrite(job)
    receipt=bundle['query_plan']['visual_query_evidence']
    receipt['input_sha256']=digest(receipt['evidence']);receipt['review']['input_sha256']=receipt['input_sha256']
    bundle['payload_sha256']=payload_key(bundle)
    path=acquisition_bundle_path(settings,state['shortcode'],caption,raw,acquisition_policy(state,run_policy(state)),state['product'])
    _atomic_json(path,bundle)
    monkeypatch.setattr(source_finder,'_post',lambda *a,**k:SimpleNamespace(caption=caption))
    monkeypatch.setattr(source_finder,'_transcript_evidence',lambda *a,**k:copy.deepcopy(raw))
    # Rebind captured acceptance manifests, never invent search executions.
    for a in fixture['artifacts']:
        try:v=json.loads(a['content'])
        except (KeyError,ValueError,TypeError):continue
        if not isinstance(v,dict) or not v.get('preparation_bundle_path'):continue
        if v.get('shortcode')!=state['shortcode']:continue
        target=Path(relocate(a['path']))
        assert target.is_relative_to(tmp_path)
        v=relocate(v)
        v['preparation_bundle_path']=str(path.resolve());v['preparation_bundle_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        _atomic_json(target,v)
        if state.get('source_search_manifest_path')==a['path']:state['source_search_manifest_path']=str(target)
        for r in state['source_acquisition'].get('rounds',[]):
            if r.get('manifest_path')==a['path']:r['manifest_path']=str(target)
    store=transactional_store(state,job,tmp_path)
    owner=SourceAcquisitionMixin();owner.settings=settings;owner.store=store
    plan,frames=preflight_preparation(settings,state,job)
    assert plan is not None
    assert fresh_frames(frames,'yandex-images',current_search_rows(state))==[]
    before=copy.deepcopy(state);original_bytes=path.read_bytes()
    page.wait_for_timeout=lambda milliseconds:None
    def reload(**kwargs):
        assert kwargs=={'wait_until':'domcontentloaded','timeout':10000}
        payload=response(failed['query'])
        for callback in list(page.listeners):
            callback(SimpleNamespace(status=200,url=payload['response_url'],json=lambda:payload['body']))
    page.reload=reload
    requested=[]
    proposal=copy.deepcopy(receipt['proposal'])
    additions=[]
    for lang,query in [('en','handheld pink ribbed spark fountain'),('zh','手持 粉色手柄 竖纹喷头 喷花器')]:
        relevant=[q for q in proposal['queries'] if q.get('language')==lang
            and any(term in q.get('query','') for term in ('pink','ribbed','粉色','竖纹'))]
        assert len(relevant)>=2
        additions.append({'id':'fresh-'+lang,'query':query,'language':lang,
            'observation_ids':list(dict.fromkeys(o for q in relevant for o in q['observation_ids'])),
            'frame_ids':list(dict.fromkeys(f for q in relevant for f in q['frame_ids']))})
    proposal['queries'].extend(additions)
    assert all(q['query'] not in [r.get('query') for r in current_search_rows(state)] for q in additions)
    class ReviewInterrupted(RuntimeError):pass
    interrupted=[]
    def external(settings,instruction,data,**kwargs):
        requested.append(copy.deepcopy(data))
        if 'proposal_sha256' not in data:
            assert data['planning_feedback']['owner']=={'task_id':state['id'],'job_id':job['id'],'run_id':state['run_id']}
            return copy.deepcopy(proposal)
        assert data['proposal']==proposal and data['proposal_sha256']==digest(proposal)
        if not interrupted:
            interrupted.append(True)
            raise ReviewInterrupted('isolated external review interruption')
        review=copy.deepcopy(receipt['review'])
        review.update(input_sha256=data['input_sha256'],proposal_sha256=data['proposal_sha256'])
        review['checks'].extend({'query_id':q['id'],'supported':True,'central_product':True,
            'short_noun_phrase':True,'no_unobserved_claims':True,'core_identity_preserved':True,
            'reason':'Isolated independent response: conjunction of existing subject-bound color and head observations.'}
            for q in additions)
        return review
    monkeypatch.setattr(script_rewriter,'_generate',external)
    with monkeypatch.context() as old:
        reader=source_parser_recovery.read_response
        old.setattr(source_parser_recovery,'read_response',lambda settings,query,*a:reader(settings,query))
        with pytest.raises(PreparationEvidenceWaiting):owner._prepare_source_queries(state,job,lambda *a:None)
    assert requested==[]
    with pytest.raises(ReviewInterrupted):
        owner._prepare_source_queries(store.get(state['id']),job,lambda *a:None)
    persisted=store.reload(job)
    assert persisted['parser_response_recovery']['status']=='response_validated'
    assert not persisted.get('parser_repair_context')
    assert not persisted.get('planning_preparation')
    assert path.read_bytes()==original_bytes
    job['checkpoint']=copy.deepcopy(persisted)
    owner._prepare_source_queries(store.get(state['id']),job,lambda *a:None)
    assert len(requested)==3
    assert sum('proposal_sha256' not in r for r in requested)==1
    assert requested[1]==requested[2]
    saved=store.reload(job)
    selected=saved['planning_preparation']
    assert selected['task_id']==state['id'] and selected['job_id']==job['id']
    assert selected['run_id']==state['run_id'] and Path(selected['path'])!=path
    assert hashlib.sha256(Path(selected['path']).read_bytes()).hexdigest()==selected['sha256']
    restored=copy.deepcopy(job);restored['checkpoint']=copy.deepcopy(saved)
    new_plan,new_frames=preflight_preparation(settings,store.get(state['id']),restored)
    from hotpost.source_visual_queries import plan_queries
    approved=plan_queries(new_plan)
    assert all(any(r['query']==q['query'] for r in approved) for q in additions)
    assert new_frames==frames
    assert 'tiktok' in owner._source_access_gate(store.get(state['id']),restored)
    assert store.jobs(state['id'])[0]['id']==fixture['job']['id']
    assert saved['parser_response_recovery']['status']=='response_validated'
    assert saved['parser_response_recovery']['job_id']==fixture['job']['id']
    assert path.read_bytes()==original_bytes
    assert store.get(state['id'])['sources']==before['sources']
