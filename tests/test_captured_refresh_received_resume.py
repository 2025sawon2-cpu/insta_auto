"""Captured refresh receipt -> actual local review, without media approval.
The host retry/load contract covers admission. This test covers the missing
post-admission connection with the same job identity and unchanged failure.
Old histories remain in the deep copy; only the registered attempt is installed.
Owner filtering must exclude other attempts before their files are accessed.
"""
import copy
import hashlib
import inspect
import json
import os
import textwrap
import time
from pathlib import Path, PureWindowsPath
import pytest
from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.studio_store import StudioStore
from hotpost.studio_runtime import generation
from hotpost.source_pause_receipts import binding, sha, snapshot, verified_receipt, SourceReceiptWaiting
from hotpost.studio_pause import StudioPaused
from hotpost.model_service import ModelServiceUnavailable


def write(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')


def installed(tmp_path):
    fixture=json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    original=copy.deepcopy(fixture)
    task=copy.deepcopy(fixture['task']);job=copy.deepcopy(fixture['job'])
    assert job['id']=='job-3fc62c0446b44f1d'
    assert job['task_id']==task['id'] and job['payload']['run_id']==task['run_id']
    assert job['payload']['search_before_saved_reviews'] is True
    assert not job['checkpoint'].get('refresh_discovery')
    assert not job['checkpoint'].get('parser_repair_context')
    assert not task.get('automation',{}).get('paused_by_user')
    descriptor=job['checkpoint']['source_attempts'][-1]
    def captured(path):
        return json.loads(next(a['content'] for a in fixture['artifacts'] if a.get('path')==path and 'content' in a))
    manifest=captured(descriptor['manifest_path'])
    # The host fixture captures the manifest and worker, not this receipt.
    # Build only the isolated receipt using the unchanged production contract.
    assert descriptor['receipt_sha256']=='24de1e966ecbb3c513745dca64d48cd1653b52f3a69005f151fb1987f65430b6'
    assert all(w.get('settled') is True for w in descriptor['workers'])
    receipt={}
    workers=[captured(w['path']) for w in descriptor['workers']]
    assert manifest['failure']=={'stage':'candidate_verification','type':'SupervisionHold','reason':'user_stopped'}
    assert manifest['status']=='paused'
    assert sum(bool(c.get('downloaded_file')) for c in manifest['candidates'])==3
    settings=Settings(data_dir=tmp_path/'data')
    def remap(value):
        if isinstance(value,dict):return {k:remap(v) for k,v in value.items()}
        if isinstance(value,list):return [remap(v) for v in value]
        if isinstance(value,str) and PureWindowsPath(value).is_absolute():
            parts=PureWindowsPath(value).parts
            return str(tmp_path/'isolated'/Path(*parts[1:]))
        return value
    task=remap(task);job=remap(job);manifest=remap(manifest);receipt=remap(receipt);workers=remap(workers)
    descriptor=job['checkpoint']['source_attempts'][-1]
    root=settings.source_dir/PureWindowsPath(original['job']['checkpoint']['source_attempts'][-1]['manifest_path']).parent.name
    root.mkdir(parents=True,exist_ok=True)
    descriptor['manifest_path']=str(root/'manifest.json')
    descriptor['receipt_path']=str(root/'interrupted-execution-receipt.json')
    reference=Path(task['reference_video']);reference.parent.mkdir(parents=True,exist_ok=True);reference.write_bytes(b'isolated reference')
    replacements={original['job']['checkpoint']['source_attempts'][-1]['reference_sha256']:sha(reference)}
    for candidate in manifest['candidates']:
        if candidate.get('downloaded_file'):
            relative=Path(*PureWindowsPath(candidate['downloaded_file']).parts)
            candidate['downloaded_file']=str(relative)
            media=root/relative;media.parent.mkdir(parents=True,exist_ok=True)
            media.write_bytes(('isolated '+candidate['url']).encode())
            replacements[candidate['file_sha256']]=sha(media)
    def rehash(value):
        if isinstance(value,dict):return {k:rehash(v) for k,v in value.items()}
        if isinstance(value,list):return [rehash(v) for v in value]
        return replacements.get(value,value) if isinstance(value,str) else value
    task=rehash(task);job=rehash(job);manifest=rehash(manifest);receipt=rehash(receipt);workers=rehash(workers)
    descriptor=job['checkpoint']['source_attempts'][-1]
    descriptor['manifest_path']=str(root/'manifest.json');descriptor['receipt_path']=str(root/'interrupted-execution-receipt.json')
    scope=binding(task,job);descriptor.update(scope);manifest['search_context']=scope['search_context']
    write(root/'manifest.json',manifest)
    checkpoints=[]
    for entry,document in zip(descriptor['workers'],workers):
        child=root/'browser_debug'/PureWindowsPath(entry['path']).name
        entry['path']=str(child);write(child,document)
        checkpoints.append({'path':str(child),'sha256':sha(child)})
    receipt=snapshot(settings.source_dir,descriptor,task,job)
    assert receipt['manifest_path']==descriptor['manifest_path']
    assert receipt['manifest_sha256']==sha(root/'manifest.json')
    assert receipt['worker_checkpoints']==checkpoints
    assert receipt['studio_job_id']==job['id']
    assert receipt['run_id']==task['run_id']
    write(descriptor['receipt_path'],receipt);descriptor['receipt_sha256']=sha(descriptor['receipt_path'])
    verified_receipt(settings.source_dir,descriptor,task,job)
    store=StudioStore(tmp_path/'store')
    with store.transaction() as db:
        db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)',(task['id'],task['shortcode'],task.get('revision',0),json.dumps(task),time.time()))
        db.execute('INSERT INTO jobs (id,task_id,kind,key,payload,status,checkpoint,created,updated) VALUES (?,?,?,?,?,?,?,?,?)',(job['id'],task['id'],job['kind'],job['id'],json.dumps(job['payload']),job['status'],json.dumps(job['checkpoint']),time.time(),time.time()))
    studio=Studio.__new__(Studio);studio.settings=settings;studio.store=store
    assert fixture==original
    return studio,task,job,root


def services(monkeypatch,seen,mode):
    def frames(path,folder,**kwargs):
        assert Path(path).is_file()
        return []
    def review(settings,source,folder):
        seen.append(copy.deepcopy(source))
        assert source.get('deferred_download_origin')
        assert sha(source['path'])==source['sha256']
        if mode[0]=='wait':raise ModelServiceUnavailable()
        raise ValueError('An independent visual reviewer and exact intervals are required')
    monkeypatch.setattr('hotpost.source_finder.extract_frames',frames)
    monkeypatch.setattr('hotpost.source_overlay_review.review_source_overlays',review)
    monkeypatch.setattr('hotpost.source_finder.find_sources',lambda *a,**k:pytest.fail('Received files must not trigger another acquisition'))


def explain_permission_failure(test):
    def wrapped(tmp_path,monkeypatch):
        import traceback
        try:
            return test(tmp_path,monkeypatch)
        except PermissionError as exc:
            frames=traceback.extract_tb(exc.__traceback__)[-8:]
            detail='\n'.join(f'{Path(f.filename).name}:{f.lineno} {f.name}: {f.line}' for f in reversed(frames))
            raise AssertionError('Positive recovery blocked; deepest frames first:\n'+detail) from exc
    return wrapped


@explain_permission_failure
def test_received_attempt_completes_real_overlay_gate(tmp_path,monkeypatch):
    from PIL import Image
    from hotpost import source_overlay_review as overlay
    from hotpost.source_mask_review import GEOMETRY
    studio,task,job,root=installed(tmp_path)
    identity=(task['id'],job['id'],task['run_id'])
    protected=copy.deepcopy({k:task.get(k) for k in ('sources','scripts','voices','daily_quality','automation')})
    original_manifest=(root/'manifest.json').read_bytes()
    calls=[]
    def sample(path,digest,folder,windows,*,samples_per_interval,**kwargs):
        assert sha(path)==digest and Path(path).resolve().is_relative_to(tmp_path.resolve())
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        spans=[];frames=[]
        for i,(start,end) in enumerate(windows):
            spans.append({'index':i,'source_start':start,'source_end':end})
            for j in range(samples_per_interval):
                image=folder/f'{i}-{j}.png'
                Image.new('RGB',(1080,1920),(40+i,60+j,80)).save(image)
                stamp=start+(end-start)*(j+1)/(samples_per_interval+1)
                frames.append({'frame_id':f'isolated-{i}-{j}','path':str(image),'sha256':sha(image),'source_timestamp':stamp,'requested_timestamp':stamp,'interval_index':i})
        return {'version':1,'source_path':str(Path(path).resolve()),'source_sha256':digest,'source_duration':40.,'geometry':dict(GEOMETRY),'intervals':spans,'frames':frames}
    def generate(settings,instruction,data,**kwargs):
        purpose=data.get('purpose') if isinstance(data,dict) else None
        calls.append(purpose)
        if purpose=='overlay_region_proposal':
            return {'frames':[{'frame_id':f['frame_id'],'boxes':[]} for f in data['frames']]}
        if purpose=='independent_overlay_review':
            proposal=data['proposal'];evidence=proposal['evidence']
            assert sha(evidence['source_path'])==evidence['source_sha256']
            accepted=[]
            for span in data['review_scope']:
                window=next(w for w in evidence['intervals'] if all(w[k]==v for k,v in span.items()))
                ids=[f['frame_id'] for f in evidence['frames'] if f['interval_index']==window['index']]
                assert set(ids)<=set(data['attached_frame_ids'])
                accepted.append({**span,'mask_indices':[],'frame_ids':ids,'coverage_confirmed':True,'subject_visible':True,'no_overlays_confirmed':True,'reason':'isolated successful independent response'})
            return {'reviewer':'isolated_independent_overlay','proposal_sha256':proposal['proposal_sha256'],'source_sha256':evidence['source_sha256'],'geometry':dict(GEOMETRY),'intervals':accepted,'rejected_intervals':[]}
        # Reaching this external call proves normal functional review follows
        # the completed bounded overlay gate; its rejection is not approval.
        assert isinstance(data,dict) and 'provided_reference_info' in data
        info=data['provided_reference_info']
        assert info['reference_sha256']==sha(task['reference_video'])
        assert info['overview_sha256']==sha(overview)
        assert kwargs.get('media')
        return {'same_core_function':False,'matched_reference_features':[],
            'context_usable':False,'context_usage_limits':[],
            'observed_actions':['Isolated candidate frames do not establish the reference function'],
            'differences':['Reference function and featured identity remain unconfirmed'],
            'featured_product_identity':False,
            'identity_evidence':['Isolated response explicitly declines featured identity'],
            'reason':'isolated downstream content rejection; no media approval'}
    monkeypatch.setattr('hotpost.source_finder.extract_frames',lambda *a,**k:[])
    # Tool discovery belongs to the isolated probe/sampling boundary.
    monkeypatch.setattr('hotpost.source_finder._executable',lambda *a,**k:'isolated-media-tool')
    # Isolate the evidenced external reference probe and overview extraction.
    # The real reference_review_info still hashes both temporary artifacts
    # and binds the original copied task context itself.
    reference=Path(task['reference_video']).resolve()
    reference_digest=sha(reference)
    overview_folder=Path(studio.folder(task['id']))
    overview_folder.mkdir(parents=True,exist_ok=True)
    overview=overview_folder/('source-reference-overview-v2-'+reference_digest[:16]+'.jpg')
    Image.new('RGB',(1440,1704),(40,60,80)).save(overview)
    def reference_probe(path):
        assert Path(path).resolve()==reference
        assert reference.is_relative_to(tmp_path.resolve())
        assert sha(path)==reference_digest
        return {'duration':40.}
    monkeypatch.setattr('hotpost.source_finder.probe_video',reference_probe)
    monkeypatch.setattr(overlay,'_duration',lambda *a:40.)
    monkeypatch.setattr(overlay,'sample_source_frames',sample)
    monkeypatch.setattr('hotpost.script_rewriter._generate',generate)
    monkeypatch.setattr('hotpost.source_finder.find_sources',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('unexpected reacquisition')))
    # Causal ablation: execute the actual production sub-entry with only its
    # newly added own-attempt connection removed. The explicit-search flag
    # makes the pre-existing deferred branch skip review on these same inputs.
    method=Studio._refresh_source_attempt
    body=textwrap.dedent(inspect.getsource(method))
    connection='deferred=self._review_deferred_downloads(state,job,progress,own_attempts_only=True)'
    assert body.count(connection)==1
    namespace=dict(method.__globals__)
    exec(compile(body.replace(connection,'deferred=None'),'<prior-refresh-route>','exec'),namespace)
    with monkeypatch.context() as old:
        old.setattr(Studio,'_refresh_source_attempt',namespace[method.__name__])
        with pytest.raises(Exception):
            studio._refresh_sources(copy.deepcopy(task),copy.deepcopy(job))
    assert not calls
    assert not job['checkpoint'].get('deferred_source_review')
    result=studio._refresh_sources(studio.store.get(task['id']),job)
    assert result['local_deferred_review'] is True and result['sources']
    assert 'overlay_region_proposal' in calls and 'independent_overlay_review' in calls
    assert None in calls, 'The real functional review must reach its external model boundary'
    assert all(s['editing_eligible'] is False for s in result['sources'])
    functional=[s['functional_review'] for s in result['sources'] if s.get('functional_review')]
    assert functional and all(r['reviewed'] is True and r['same_core_function'] is False
        and r['context_usable'] is False for r in functional)
    accepted=[s for s in result['sources'] if s.get('mask_review',{}).get('reviewer')=='isolated_independent_overlay']
    assert accepted
    for source in accepted:
        assert source['mask_review']['source_sha256']==source['sha256']==sha(source['path'])
        assert source['reviewed_intervals']
        assert overlay.accepted_interval_frames(source)
        folder=Path(source['overlay_review_path'])
        assert (folder/'overlay-reviewed.json').is_file()
        proposal=json.loads((folder/'overlay-proposal.json').read_text('utf8'))
        receipt=json.loads((folder/'overlay-receipt.json').read_text('utf8'))
        # Re-run the unchanged validator against persisted positive evidence.
        approved=overlay.approve_masks(proposal,receipt)
        assert approved['reviewed_intervals']==source['reviewed_intervals']
    assert (task['id'],job['id'],task['run_id'])==identity
    assert (root/'manifest.json').read_bytes()==original_manifest
    current=studio.store.get(task['id'])
    assert {k:current.get(k) for k in protected}==protected
    assert not job['checkpoint'].get('refresh_discovery')


def reload_checkpoint(store,job):
    with store.transaction() as db:
        row=db.execute('SELECT checkpoint FROM jobs WHERE id=? AND task_id=?',(job['id'],job['task_id'])).fetchone()
    assert row is not None
    job['checkpoint']=json.loads(row[0])


def test_received_attempt_reaches_normal_review_and_persists_failure(tmp_path,monkeypatch):
    studio,task,job,root=installed(tmp_path)
    protected=copy.deepcopy({k:task.get(k) for k in ('sources','scripts','voices','daily_quality','automation')})
    preflight=copy.deepcopy(job['checkpoint']['source_access_preflight'])
    seen=[];mode=['wait'];services(monkeypatch,seen,mode)
    with pytest.raises(ModelServiceUnavailable):studio._refresh_sources(task,job)
    assert seen and job['checkpoint'].get('deferred_source_review')
    assert not job['checkpoint'].get('refresh_discovery')
    reload_checkpoint(studio.store,job)
    mode[0]='reject'
    result=studio._refresh_sources(studio.store.get(task['id']),job)
    assert result['local_deferred_review'] is True and result['sources']
    assert result['searches']==[]
    assert all(s['editing_eligible'] is False and s.get('overlay_review_error') for s in result['sources'])
    reload_checkpoint(studio.store,job)
    saved=job['checkpoint']['deferred_source_review']
    assert sha(saved['path'])==saved['sha256']
    persisted=json.loads(Path(saved['path']).read_text('utf8'))['sources']
    assert all(persisted[s['sha256']]['editing_eligible'] is False for s in result['sources'])
    current=studio.store.get(task['id'])
    assert {k:current.get(k) for k in protected}==protected
    assert job['checkpoint']['source_access_preflight']==preflight
    assert json.loads((root/'manifest.json').read_text('utf8'))['failure']['type']=='SupervisionHold'


@pytest.mark.parametrize('damage',['owner','run','request','unsettled','receipt','media','pause'])
def test_invalid_received_attempt_cannot_reach_review(tmp_path,monkeypatch,damage):
    studio,task,job,root=installed(tmp_path)
    seen=[];services(monkeypatch,seen,['reject'])
    descriptor=job['checkpoint']['source_attempts'][-1]
    if damage=='owner':descriptor['studio_job_id']='different-job'
    elif damage=='run':job['payload']['run_id']='different-run'
    elif damage=='request':job['payload']['request']='different request'
    elif damage=='unsettled':descriptor['workers'][0]['settled']=False
    elif damage=='receipt':Path(descriptor['receipt_path']).write_text('{}',encoding='utf8')
    elif damage=='media':
        manifest=json.loads((root/'manifest.json').read_text('utf8'))
        candidate=next(c for c in manifest['candidates'] if c.get('downloaded_file') and not c.get('error') and not c.get('rejection_reasons'))
        (root/candidate['downloaded_file']).write_bytes(b'corrupted')
    else:studio.store.change(task['id'],lambda s,db:s.setdefault('automation',{}).update(paused_by_user=True))
    with pytest.raises((SourceReceiptWaiting,StudioPaused)):
        studio._refresh_sources(studio.store.get(task['id']),job)
    assert not seen
