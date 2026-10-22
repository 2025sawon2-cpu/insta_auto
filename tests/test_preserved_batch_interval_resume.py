import ast
import copy
import hashlib
import inspect
import json
import os
import textwrap
from pathlib import Path, PureWindowsPath

import pytest
from hotpost.config import Settings
from hotpost.studio_sources import SourceAcquisitionMixin
from hotpost.source_pause_receipts import snapshot, sha, verified_receipt
from hotpost.source_batches import cached_records, review_context
from test_deferred_download_review import Harness, MemoryStore


def saved_incident(tmp_path):
    original = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    fixture = copy.deepcopy(original)
    settings = Settings(data_dir=tmp_path)
    source_root = PureWindowsPath(fixture['job']['checkpoint']['source_attempts'][0]['manifest_path']).parent
    local_root = settings.source_dir / source_root.name
    paths = {}
    def pathmap(value):
        if not isinstance(value, str) or not PureWindowsPath(value).is_absolute():
            return value
        if value not in paths:
            p = PureWindowsPath(value)
            try:
                relative = p.relative_to(source_root)
                target = local_root.joinpath(*relative.parts)
            except ValueError:
                target = tmp_path / 'captured' / hashlib.sha256(value.encode()).hexdigest() / p.name
            paths[value] = str(target.resolve())
        return paths[value]
    def walk(value, mapping):
        if isinstance(value, dict):
            return {mapping(k):walk(v, mapping) for k,v in value.items()}
        if isinstance(value, list):
            return [walk(v, mapping) for v in value]
        return mapping(value) if isinstance(value,str) else value
    fixture = walk(fixture, pathmap)
    rows = original['artifacts']
    rows = list(rows.values()) if isinstance(rows,dict) else rows
    documents = {}
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('content'),str):
            continue
        try:
            value = json.loads(row['content'])
        except ValueError:
            continue
        documents[pathmap(row['path'])] = walk(value,pathmap)
    state,job = fixture['task'],fixture['job']
    replacements = {}
    def standins(value):
        if isinstance(value,list):
            for item in value: standins(item)
        elif isinstance(value,dict):
            for field,digest_field in [('path','sha256'),('source_path','source_sha256')]:
                p = value.get(field); digest = value.get(digest_field)
                if isinstance(p,str) and isinstance(digest,str) and len(digest)==64 and p not in documents:
                    target = Path(p)
                    assert target.is_relative_to(tmp_path)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(('isolated captured file '+p).encode())
                    replacements[digest] = sha(target)
            for item in value.values(): standins(item)
    for document in documents.values(): standins(document)
    reference = Path(state['reference_video'])
    reference.parent.mkdir(parents=True,exist_ok=True)
    reference.write_bytes(b'isolated reference')
    replacements[original['job']['checkpoint']['source_attempts'][0]['reference_sha256']] = sha(reference)
    manifest_path = Path(job['checkpoint']['source_attempts'][0]['manifest_path'])
    manifest = documents[str(manifest_path)]
    for candidate in manifest.get('candidates',[]):
        raw = candidate.get('downloaded_file')
        if not raw: continue
        p = local_root.joinpath(*PureWindowsPath(raw).parts)
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(('isolated media '+raw).encode())
        replacements[candidate['file_sha256']] = sha(p)
    replace = lambda value: replacements.get(value,value)
    state,job = walk(state,replace),walk(job,replace)
    documents = {p:walk(v,replace) for p,v in documents.items()}
    def write(path,value):
        path=Path(path); assert path.is_relative_to(tmp_path)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,ensure_ascii=False),'utf8')
    for p,value in documents.items(): write(p,value)
    saved = job['checkpoint']['source_batch_review']
    batch = Path(saved['manifest'])
    key = str(batch.resolve())+':'+sha(batch)
    cache = documents[saved['path']]
    assert cache['sources']
    cache['input_key']=key
    write(saved['path'],cache)
    saved.update(input_key=key,manifest_sha256=sha(batch),sha256=sha(saved['path']),review_context=review_context(state))
    visual = job['checkpoint']['source_visual_review']
    visual.update(input_key=key,path=saved['path'],sha256=saved['sha256'])
    manifest = documents[str(manifest_path)]
    if manifest.get('batch_review_checkpoint'):
        manifest['batch_review_checkpoint']=copy.deepcopy(saved)
    write(manifest_path,manifest)
    for entry in job['checkpoint']['source_attempts']:
        receipt=snapshot(settings.source_dir,entry,state,job)
        write(entry['receipt_path'],receipt)
        entry['receipt_sha256']=sha(entry['receipt_path'])
        verified_receipt(settings.source_dir,entry,state,job)
        for old in state['source_acquisition'].get('interrupted_attempts',[]):
            if old.get('manifest_path')==entry['manifest_path']:
                old.update(copy.deepcopy(receipt),receipt_path=entry['receipt_path'],receipt_sha256=entry['receipt_sha256'])
    h=Harness(); h.settings=settings; h.root=tmp_path/'studio'; h.root.mkdir()
    h.store=MemoryStore(state)
    records,origins=h._deferred_download_records(state)
    assert records and cached_records(h,job)
    binding={'task_id':state['id'],'run_id':state.get('run_id'),'reference_sha256':sha(reference),
        'original_text':state.get('reviewed_original_text') or state.get('original_text'),
        'product':state.get('product'),'origins':origins}
    key=hashlib.sha256(json.dumps(binding,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    deferred=job['checkpoint']['deferred_source_review']
    value=documents[deferred['path']]
    assert value['sources']=={}
    value['input_key']=key; write(deferred['path'],value)
    deferred.update(input_key=key,sha256=sha(deferred['path']))
    assert (state['id'],job['id'],state['run_id'],job['payload']) == (original['task']['id'],original['job']['id'],original['task']['run_id'],original['job']['payload'])
    return h,state,job,original


def test_preserved_cache_resumes_original_entry(tmp_path,monkeypatch):
    h,state,job,original=saved_incident(tmp_path)
    from hotpost import source_finder,source_functional,source_overlay_review
    frame=tmp_path/'reference.png'
    from PIL import Image
    Image.new('RGB',(1080,1920)).save(frame)
    monkeypatch.setattr(source_finder,'extract_frames',lambda *a,**k:[frame])
    monkeypatch.setattr(source_finder,'find_sources',lambda *a,**k:pytest.fail('Received files must precede external collection'))
    monkeypatch.setattr(source_functional,'reference_review_info',lambda *a:{})
    def external_rejection(*args,**kwargs):
        raise ValueError('isolated fresh external review rejection')
    monkeypatch.setattr(source_overlay_review,'review_source_overlays',external_rejection)
    monkeypatch.setattr(source_functional,'review_function',lambda *a,**k:{'reviewed':False})
    # Reconstruct the old production method by removing only the newly added
    # exception boundary. All entry routing and internal validators remain real.
    tree=ast.parse(textwrap.dedent(inspect.getsource(SourceAcquisitionMixin._review_source_records)))
    class OldBoundary(ast.NodeTransformer):
        def visit_Try(self,node):
            if any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='accepted_interval_frames' for n in ast.walk(ast.Module(body=node.body,type_ignores=[]))):
                return node.body
            return self.generic_visit(node)
    tree=ast.fix_missing_locations(OldBoundary().visit(tree))
    import hotpost.studio_sources as module
    namespace=dict(vars(module)); exec(compile(tree,'preserved-old-production','exec'),namespace)
    before=copy.deepcopy(job)
    before_state=copy.deepcopy(state)
    before_files={p:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    monkeypatch.setattr(h,'_review_source_records',namespace['_review_source_records'].__get__(h,type(h)))
    with pytest.raises(ValueError,match='outside its bound interval'):
        h._collect_sources(state,job)
    monkeypatch.setattr(h,'_review_source_records',SourceAcquisitionMixin._review_source_records.__get__(h,type(h)))
    # Restore the complete isolated input: the old pass can persist earlier
    # rows into the batch cache before encountering the malformed frame.
    for path,raw in before_files.items():
        path.write_bytes(raw)
    state.clear();state.update(copy.deepcopy(before_state))
    job.clear();job.update(copy.deepcopy(before))
    h.store=MemoryStore(state)
    assert all(path.read_bytes()==raw for path,raw in before_files.items())
    assert cached_records(h,job)
    result=h._collect_sources(state,job)
    assert result['local_deferred_review'] and result['visual_review_only']
    bad=[s for s in result['sources'] if s.get('overlay_review_error')=='Accepted function frame is outside its bound interval']
    assert bad and all(s['editing_eligible'] is False for s in bad)
    saved=job['checkpoint']['deferred_source_review']
    assert sha(saved['path'])==saved['sha256']
    persisted=json.loads(Path(saved['path']).read_text('utf8'))
    assert all(persisted['sources'][s['sha256']]['review_outcome']==s['review_outcome'] for s in bad)
    assert job['id']==original['job']['id'] and state['run_id']==original['task']['run_id']
    assert state['sources']==original['task']['sources']


@pytest.mark.parametrize('damage',['task','run','batch_sha','deferred_sha'])
def test_preserved_cache_rejects_invalid_binding(tmp_path,damage):
    h,state,job,_=saved_incident(tmp_path)
    if damage=='task':job['checkpoint']['source_attempts'][0]['task_id']='foreign'
    elif damage=='run':job['checkpoint']['source_attempts'][0]['run_id']='foreign'
    elif damage=='batch_sha':job['checkpoint']['source_batch_review']['sha256']='0'*64
    else:job['checkpoint']['deferred_source_review']['sha256']='0'*64
    with pytest.raises((ValueError,RuntimeError)):
        h._collect_sources(state,job)
    assert state['sources']==[]
