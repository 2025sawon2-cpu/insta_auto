"""Exact producer-selected failed topic JSON is diagnostic evidence only."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.source_visual_queries import digest

from hotpost import video_agent_context as context


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False),'utf8')


@pytest.fixture
def setup(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('topic','Topic',{'active':True},prepare=False)
    state=studio.store.change(state['id'],lambda s,db:s.update(run_id='run-topic'))
    with studio.store.transaction() as db:
        jid=studio.store.enqueue(db,state['id'],'refresh_sources',{'run_id':state['run_id']},'topic-diagnostic')
    owner={'task_id':state['id'],'job_id':jid,'run_id':state['run_id']}
    evidence={'policy':'natural-topic-search-v1','owner':owner,'text':{'caption':'original'},'frames':[]}
    key=digest(evidence);cache=tmp_path/'source-topic-query-receipts'/digest({'evidence':evidence,'owner':owner})
    proposal={'queries':[],'observations':[]}
    review={'input_sha256':key,'proposal_sha256':digest(proposal),'core_identity_complete':False,'reason':'unknown SKU'}
    write(cache/'proposal.json',{'input_sha256':key,'proposal':proposal})
    write(cache/'review.json',review)
    cp={'visual_query_input':{**owner,'input_sha256':key}}
    error=f'Natural search observation binding differs | proposal_path={cache/"proposal.json"} | review_path={cache/"review.json"}'
    def save_cp(cp=cp,error=error,payload=None):
        with studio.store.transaction() as db:
            db.execute('UPDATE jobs SET checkpoint=?,error=? WHERE id=?',(json.dumps(cp),error,jid))
            if payload is not None:db.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps(payload),jid))
    save_cp()
    return dict(locals())


def test_failed_pair_is_inspectable_and_listed_without_changing_any_original(setup,monkeypatch):
    s=setup;studio=s['studio'];state=s['state'];cache=s['cache']
    original={p:p.read_bytes() for p in cache.iterdir()};before=studio.store.get(state['id'])
    with studio.store.connect() as db:db_before=[tuple(r) for r in db.execute('SELECT * FROM jobs')]
    def no_glob(path,*a,**kw):raise AssertionError('Topic cache tree must never be scanned')
    monkeypatch.setattr(Path,'glob',no_glob);monkeypatch.setattr(Path,'rglob',no_glob)
    allowed=context.visual_query_artifact_paths(studio,state,job_id=s['jid'])
    assert allowed=={str(p.resolve()) for p in original}
    captured=context.incident_artifacts(studio,state,{'id':s['jid'],'checkpoint':s['cp'],'error':s['error']},max_files=24)
    for path,raw in original.items():
        proof=context.inspect_artifact(studio,state,{'path':str(path)})
        assert proof['sha256']==hashlib.sha256(raw).hexdigest()
        assert next(r for r in captured if r['path']==str(path.resolve()))['content']==raw.decode('utf8')
    assert studio.store.get(state['id'])==before
    with studio.store.connect() as db:assert [tuple(r) for r in db.execute('SELECT * FROM jobs')]==db_before
    assert all(p.read_bytes()==raw for p,raw in original.items())


@pytest.mark.parametrize('fault',['task','job','run','payload_run','input','proposal_input','review_input',
    'proposal_digest','unregistered_copy','private_name','deep_path','traversal','oversize','missing_review'])
def test_topic_diagnostic_authority_cannot_move_to_other_context_or_json(setup,fault):
    s=setup;cp=copy.deepcopy(s['cp']);cache=s['cache'];target=cache/'proposal.json'
    if fault in {'task','job','run','input'}:
        cp['visual_query_input'][{'input':'input_sha256'}.get(fault,fault+'_id')]='0'*64 if fault=='input' else 'other'
        s['save_cp'](cp)
    elif fault=='payload_run':s['save_cp'](payload={'run_id':'other'})
    elif fault=='proposal_input':write(target,{'input_sha256':'0'*64,'proposal':s['proposal']})
    elif fault=='review_input':write(cache/'review.json',{**s['review'],'input_sha256':'0'*64})
    elif fault=='proposal_digest':write(cache/'review.json',{**s['review'],'proposal_sha256':'0'*64})
    elif fault=='unregistered_copy':
        target=cache.parent/('0'*64)/'proposal.json'
        write(target,{'input_sha256':s['key'],'proposal':s['proposal']})
        write(target.with_name('review.json'),s['review'])
    elif fault=='private_name':target=cache/'private.json';write(target,{'secret':'unrelated'})
    elif fault=='deep_path':target=cache/'nested/proposal.json';write(target,{'secret':'unrelated'})
    elif fault=='traversal':target=cache/'alias/../proposal.json'
    elif fault=='oversize':write(target,{'input_sha256':s['key'],'proposal':s['proposal'],'padding':'x'*300000})
    elif fault=='missing_review':(cache/'review.json').unlink()
    with pytest.raises(ValueError,match='증거 파일'):
        context.inspect_artifact(s['studio'],s['state'],{'path':str(target)})


def test_exact_owned_receipt_requires_evidence_owner_and_directory_digest(setup):
    s=setup;cache=s['cache'];s['save_cp'](error='')
    receipt={'input_sha256':s['key'],'owner':s['owner'],'evidence':s['evidence'],
        'proposal':s['proposal'],'review':s['review']}
    write(cache/'receipt.json',receipt)
    assert context.inspect_artifact(s['studio'],s['state'],{'path':str(cache/'receipt.json')})['status']=='completed'
    assert context.inspect_artifact(s['studio'],s['state'],{'path':str(cache/'proposal.json')})['status']=='completed'
    receipt['owner']={**s['owner'],'job_id':'other'};write(cache/'receipt.json',receipt)
    with pytest.raises(ValueError,match='증거 파일'):
        context.inspect_artifact(s['studio'],s['state'],{'path':str(cache/'receipt.json')})


def test_owned_topic_json_never_follows_path_in_its_body(setup,tmp_path):
    s=setup;private=tmp_path/'private.json';write(private,{'private':'unrelated'})
    s['proposal']['private_path']=str(private)
    write(s['cache']/'proposal.json',{'input_sha256':s['key'],'proposal':s['proposal']})
    write(s['cache']/'review.json',{**s['review'],'proposal_sha256':digest(s['proposal'])})
    assert context.inspect_artifact(s['studio'],s['state'],{'path':str(s['cache']/'proposal.json')})['status']=='completed'
    with pytest.raises(ValueError,match='증거 파일'):
        context.inspect_artifact(s['studio'],s['state'],{'path':str(private)})


def test_failure_trace_alone_lists_exact_producer_pair(setup):
    s=setup;cp=copy.deepcopy(s['cp']);cp['failure_trace']={'message':s['error']}
    s['save_cp'](cp,error='')
    assert context.visual_query_artifact_paths(s['studio'],s['state'],job_id=s['jid'])=={
        str((s['cache']/name).resolve()) for name in ('proposal.json','review.json')}


def test_topic_alias_or_reparse_component_is_never_authority(setup,monkeypatch):
    s=setup;original=Path.is_symlink
    monkeypatch.setattr(Path,'is_symlink',lambda path:path==s['cache'] or original(path))
    with pytest.raises(ValueError,match='증거 파일'):
        context.inspect_artifact(s['studio'],s['state'],{'path':str(s['cache']/'proposal.json')})
