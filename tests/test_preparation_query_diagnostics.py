import copy
import hashlib
import json
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.video_agent_context import preparation_query_diagnostics, snapshot
from hotpost.source_preparation import save_bundle, payload_key
from hotpost.source_policy import run_policy
from hotpost.source_diversity import acquisition_policy
from hotpost import source_visual_queries as visual
from test_source_visual_query_minima_v5 import setup, proposal, model, plan


def captured(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('fixture','Fixture',{'active':True},prepare=False)
    root=studio.settings.source_dir/'fixture-123';root.mkdir(parents=True)
    _,reference,frames=setup(root)
    state=studio.store.change(state['id'],lambda s,db:s.update(
        run_id='run-original',product='재킷',reference_video=str(reference)))
    policy=acquisition_policy(state,run_policy(state))
    receipt=visual.cached_visual_queries(studio.settings,reference,frames,'재킷',{},
        model(proposal(),[]),search_minimums=policy['search_minimums'],subject_hint='재킷')
    document=plan(receipt);document['source_policy']=policy
    bundle=tmp_path/'source-preparations'/'fixture'/'prepared.json'
    save_bundle(bundle,'재킷',{},reference,frames,frames[0],query_plan=document)
    manifest=root/'manifest.json'
    def register():
        manifest.write_text(json.dumps({'shortcode':'fixture','preparation_bundle_path':str(bundle),
            'preparation_bundle_sha256':hashlib.sha256(bundle.read_bytes()).hexdigest()}),'utf8')
    register()
    state=studio.store.change(state['id'],lambda s,db:s.update(source_search_manifest_path=str(manifest)))
    return studio,state,bundle,reference,frames,register


@pytest.mark.parametrize('fault',[None,'pixels','review','payload','manifest_sha','hint','foreign_media','growing_media'])
def test_registered_original_query_diagnostic_uses_real_validators_without_mutation(tmp_path,fault,monkeypatch):
    studio,state,bundle,reference,frames,register=captured(tmp_path)
    value=json.loads(bundle.read_text('utf8'))
    if fault=='pixels':frames[0].write_bytes(b'changed')
    if fault=='review':value['query_plan']['visual_query_evidence']['review']['proposal_sha256']='wrong'
    if fault=='hint':state['product']='different'
    if fault=='foreign_media':
        evidence=value['query_plan']['visual_query_evidence']['evidence']
        foreign=tmp_path/'private.mp4';foreign.write_bytes(reference.read_bytes())
        value['files'][0]['path']=str(foreign);evidence['reference_path']=str(foreign)
    if fault in {'review','foreign_media','payload'}:
        value['payload_sha256']=payload_key(value) if fault!='payload' else 'wrong'
        bundle.write_text(json.dumps(value),'utf8');register()
    if fault=='manifest_sha':bundle.write_text('{}','utf8')
    if fault=='growing_media':
        original=Path.stat
        def changed_size(path,*args,**kwargs):
            result=original(path,*args,**kwargs)
            if path==reference:
                from types import SimpleNamespace
                return SimpleNamespace(st_size=max(0,result.st_size-1),st_mode=result.st_mode)
            return result
        monkeypatch.setattr(Path,'stat',changed_size)
    before_state=copy.deepcopy(studio.store.get(state['id']))
    before={p:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file() and p.suffix not in {'.sqlite3','-wal','-shm'}}
    result=preparation_query_diagnostics(studio,state)
    if fault=='manifest_sha':assert result==[]
    else:
        assert len(result)==1
        row=result[0]
        if fault is None:
            assert row['status']=='reusable' and row['media_sha_checked'],row
            assert row['current_query_contract'] is True
            assert 'not a new production plan or approval' in row['fixture_guidance']
            assert snapshot(studio,state['id'])['original_preparation_query_diagnostics']==result
        else:assert row['status']!='reusable' and not row.get('fixture_guidance')
    assert studio.store.get(state['id'])==before_state
    assert all(p.read_bytes()==raw for p,raw in before.items())


def test_diagnostic_does_not_follow_linked_media(tmp_path):
    studio,state,bundle,reference,frames,register=captured(tmp_path)
    data=frames[0].read_bytes();target=tmp_path/'outside.jpg';target.write_bytes(data)
    frames[0].unlink()
    try:frames[0].symlink_to(target)
    except OSError:pytest.skip('symlink privilege unavailable')
    result=preparation_query_diagnostics(studio,state)
    assert result[0]['status']=='unverified' and 'Linked' in result[0]['reason']


@pytest.mark.parametrize('mutation',['grow','replace'])
def test_changes_before_semantic_pass_cannot_escape_bound_or_be_reported_valid(tmp_path,monkeypatch,mutation):
    studio,state,bundle,reference,frames,register=captured(tmp_path)
    from hotpost import source_preparation
    original=source_preparation.reusable_query_contract
    calls=[]
    def validate(*args,**kwargs):
        assert kwargs=={'verify_files':False}
        if mutation=='grow':
            with frames[0].open('ab') as stream:stream.write(b'changed')
        else:
            replacement=frames[0].with_suffix('.replacement')
            replacement.write_bytes(frames[0].read_bytes());replacement.replace(frames[0])
        # Real semantic validation cannot reopen media; failure must come from
        # the final binding check, rather than another unlimited content read.
        def forbidden(*args,**kwargs):pytest.fail('unbounded media reread')
        with monkeypatch.context() as patch:
            patch.setattr('hotpost.source_quality.sha256_file',forbidden)
            result=original(*args,**kwargs);calls.append(result);return result
    monkeypatch.setattr(source_preparation,'reusable_query_contract',validate)
    result=preparation_query_diagnostics(studio,state)
    assert calls==[True]
    assert result[0]['status']=='unverified' and 'changed during diagnostic' in result[0]['reason']


def test_shared_media_budget_is_not_renewed_for_each_file(tmp_path,monkeypatch):
    studio,state,bundle,reference,frames,register=captured(tmp_path)
    from hotpost import video_agent_context as context
    monkeypatch.setattr(context,'PREPARATION_DIAGNOSTIC_MEDIA_BYTES',reference.stat().st_size)
    original=Path.open;opened=[]
    def tracked(path,*args,**kwargs):
        if path in [reference,*frames]:opened.append(path)
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',tracked)
    result=preparation_query_diagnostics(studio,state)
    assert opened==[reference]
    assert result[0]['status']=='unverified' and 'budget' in result[0]['reason']


def test_bundle_replacement_after_registered_discovery_is_not_an_original_plan(tmp_path,monkeypatch):
    studio,state,bundle,reference,frames,register=captured(tmp_path)
    from hotpost import video_agent_context as context
    original=context._preparation_artifact_bindings
    def swap(*args,**kwargs):
        bindings=original(*args,**kwargs)
        value=json.loads(bundle.read_text('utf8'))
        value['transcript']={'screen_text':'different internally consistent bundle'}
        value['payload_sha256']=payload_key(value)
        bundle.write_text(json.dumps(value),'utf8')
        return bindings
    monkeypatch.setattr(context,'_preparation_artifact_bindings',swap)
    result=preparation_query_diagnostics(studio,state)
    assert result[0]['status']=='unverified' and 'Registered bundle SHA changed' in result[0]['reason']
    assert not result[0].get('fixture_guidance')


def test_descriptor_creation_time_representation_difference_is_not_a_file_change(tmp_path,monkeypatch):
    studio,state,*_=captured(tmp_path)
    import os
    from types import SimpleNamespace
    original=os.fstat
    def descriptor(fd):
        value=original(fd)
        return SimpleNamespace(**{k:getattr(value,k) for k in ('st_dev','st_ino','st_size','st_mtime_ns')},
                               st_ctime_ns=value.st_mtime_ns+123)
    monkeypatch.setattr(os,'fstat',descriptor)
    assert preparation_query_diagnostics(studio,state)[0]['status']=='reusable'
