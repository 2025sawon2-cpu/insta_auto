import copy
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath

import pytest
from hotpost.config import Settings
from hotpost.source_pause_receipts import SourceReceiptWaiting, verified_receipt, sha
from test_source_pause_history import Harness, MemoryStore


def captured(tmp_path):
    fixture = copy.deepcopy(json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8')))
    entry = fixture['job']['checkpoint']['source_attempts'][0]
    original_root = PureWindowsPath(entry['manifest_path']).parent
    settings = Settings(data_dir=tmp_path)
    root = settings.source_dir / original_root.name
    reference = tmp_path / 'reference.mp4'
    reference.write_bytes(b'isolated external reference fixture')
    original_reference = fixture['task']['reference_video']
    old_sha = entry['reference_sha256']
    new_sha = sha(reference)
    def mapped(value):
        if not isinstance(value, str): return value
        if value == original_reference: return str(reference)
        if value == old_sha: return new_sha
        try: relative = PureWindowsPath(value).relative_to(original_root)
        except ValueError: return value
        return str(root.joinpath(*relative.parts))
    def walk(value):
        if isinstance(value, dict): return {k:walk(v) for k,v in value.items()}
        if isinstance(value, list): return [walk(v) for v in value]
        return mapped(value)
    artifacts = fixture['artifacts']
    rows = artifacts.values() if isinstance(artifacts, dict) else artifacts
    for artifact in rows:
        if not isinstance(artifact, dict): continue
        original, text = artifact.get('path'), artifact.get('content')
        if not original or not isinstance(text, str): continue
        target = Path(mapped(original))
        if str(target) == original: continue
        assert target.is_relative_to(tmp_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try: text = json.dumps(walk(json.loads(text)), ensure_ascii=False)
        except ValueError: pass
        target.write_text(text, encoding='utf8')
    state, job = walk(fixture['task']), walk(fixture['job'])
    manifest = Path(job['checkpoint']['source_attempts'][0]['manifest_path'])
    data = json.loads(manifest.read_text('utf8'))
    replacements = {}
    for candidate in data.get('candidates', []):
        raw = candidate.get('downloaded_file')
        if not raw: continue
        media = root.joinpath(*PureWindowsPath(raw).parts).resolve()
        assert media.is_relative_to(root.resolve())
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(('isolated media ' + raw).encode())
        if candidate.get('file_sha256'):
            replacements[candidate['file_sha256']] = sha(media)
    def rehash(value):
        if isinstance(value, dict): return {replacements.get(k,k):rehash(v) for k,v in value.items()}
        if isinstance(value, list): return [rehash(v) for v in value]
        return replacements.get(value,value) if isinstance(value,str) else value
    state, job, data = rehash(state), rehash(job), rehash(data)
    # An isolated external cache with no approved rows forces real local review.
    # It cannot grant source eligibility, and internal cache validation stays real.
    from hotpost.source_batches import review_context
    batch = root/'batch-0002.json'
    batch.write_text(json.dumps({k:v for k,v in data.items() if k != 'batch_review_checkpoint'},ensure_ascii=False),'utf8')
    cache = root/'source-review-isolated.json'
    key = str(batch.resolve()) + ':' + sha(batch)
    cache.write_text(json.dumps({'input_key':key,'sources':{}}),'utf8')
    saved = {'manifest':str(batch.resolve()),'manifest_sha256':sha(batch),
             'path':str(cache.resolve()),'sha256':sha(cache),'input_key':key,
             'review_context':review_context(state)}
    data['batch_review_checkpoint'] = copy.deepcopy(saved)
    manifest.write_text(json.dumps(data,ensure_ascii=False),'utf8')
    job['checkpoint']['source_batch_review'] = copy.deepcopy(saved)
    job['checkpoint']['source_visual_review'] = copy.deepcopy(saved)
    assert job['checkpoint']['source_attempts'][0]['search_context']['product'] == ''
    h = Harness(); h.settings = settings; h.store = MemoryStore(state)
    return h,state,job,fixture


def test_captured_binding_recovery_is_atomic(tmp_path):
    h,s,j,f = captured(tmp_path)
    entry = j['checkpoint']['source_attempts'][0]
    assert (s['id'],j['id']) == (f['task']['id'],f['job']['id'])
    with pytest.raises(SourceReceiptWaiting): verified_receipt(h.settings.source_dir,entry,s,j)
    h._preserve_source_attempt_history(s,j)
    receipt = verified_receipt(h.settings.source_dir,entry,s,j)
    assert (receipt['task_id'],receipt['studio_job_id']) == (s['id'],j['id'])
    assert entry['descriptor_recovery']['previous_descriptor']['search_context']['product'] == ''
    assert all(not e.get('descriptor_recovery') or e.get('receipt_path') for cp in h.store.checkpoints for e in cp.get('source_attempts',[]))
    raw = Path(entry['receipt_path']).read_bytes()
    h._preserve_source_attempt_history(s,j)
    assert Path(entry['receipt_path']).read_bytes() == raw


@pytest.mark.parametrize('damage',['task','job','run','unsettled','foreign_worker','no_audit','wrong_manifest_context'])
def test_invalid_binding_stays_held(tmp_path,damage):
    h,s,j,f = captured(tmp_path)
    e = j['checkpoint']['source_attempts'][0]
    if damage == 'task': e['task_id']='foreign'
    elif damage == 'job': e['studio_job_id']='foreign'
    elif damage == 'run': e['run_id']='foreign'
    elif damage == 'unsettled': e['workers'][0]['settled']=False
    elif damage == 'foreign_worker': e['workers'][0]['path']=str(tmp_path/'foreign.json')
    else:
        p=Path(e['manifest_path']); d=json.loads(p.read_text('utf8'))
        if damage == 'no_audit': d['execution_audit_available']=False
        else: d['search_context']['product']='foreign'
        p.write_text(json.dumps(d),'utf8')
    with pytest.raises(SourceReceiptWaiting): h._collect_sources(s,j)
    assert not e.get('descriptor_recovery') and not e.get('receipt_path')
    assert h.store.state['sources'] == f['task']['sources']


def test_original_collect_reaches_preserved_media_review(tmp_path,monkeypatch):
    h,s,j,f = captured(tmp_path)
    from hotpost import source_finder
    from hotpost.source_pause_receipts import snapshot
    original_preserve = h._preserve_source_attempt_history
    def old_preserve(state,job):
        for entry in job['checkpoint']['source_attempts']:
            snapshot(h.settings.source_dir,entry,state,job)
    monkeypatch.setattr(h,'_preserve_source_attempt_history',old_preserve)
    with pytest.raises(SourceReceiptWaiting): h._collect_sources(s,j)
    assert not j['checkpoint']['source_attempts'][0].get('receipt_path')
    monkeypatch.setattr(h,'_preserve_source_attempt_history',original_preserve)
    class ReviewMediaReached(Exception): pass
    seen=[]
    def external_frames(path,folder,**kwargs):
        assert Path(path).is_relative_to(tmp_path)
        seen.append((s['id'],j['id']))
        raise ReviewMediaReached
    monkeypatch.setattr(source_finder,'extract_frames',external_frames)
    with pytest.raises(ReviewMediaReached): h._collect_sources(s,j)
    assert seen == [(f['task']['id'],f['job']['id'])]
    assert j['checkpoint'].get('deferred_source_review')
    assert h.store.state['source_acquisition']['interrupted_attempts']
    assert h.store.state['sources'] == f['task']['sources']


def test_stale_checkpoint_rolls_back_descriptor(tmp_path):
    from hotpost.studio_store import StaleClaim
    h,s,j,f = captured(tmp_path)
    entry=j['checkpoint']['source_attempts'][0]
    before=copy.deepcopy(entry)
    h.store.stale=True
    with pytest.raises(StaleClaim): h._preserve_source_attempt_history(s,j)
    assert entry == before
