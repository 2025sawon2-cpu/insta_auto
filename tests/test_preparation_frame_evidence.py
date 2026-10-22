import base64
import copy
import hashlib
import json

import pytest

from hotpost.video_agent_context import inspect_artifact,snapshot
from hotpost.video_agent_preparation_evidence import preparation_frames,frame_summary
from hotpost.source_search.strategy import image_signature,fresh_frames
from hotpost.source_preparation import payload_key
from test_preparation_query_diagnostics import captured
from test_video_agent_repairs import env,proposal


def test_original_pixels_round_trip_without_changing_scope_consumption(tmp_path):
    studio,state,bundle,reference,frames,register=captured(tmp_path)
    before=copy.deepcopy(studio.store.get(state['id']))
    encoded=preparation_frames(studio,state,include_bytes=True)
    assert len(encoded)==1 and encoded[0]['status']=='captured'
    frame=encoded[0]['frames'][0];raw=base64.b64decode(frame['data_base64'],validate=True)
    assert raw==frames[0].read_bytes() and hashlib.sha256(raw).hexdigest()==frame['sha256']
    relocated=tmp_path/'isolated.jpg';relocated.write_bytes(raw)
    assert image_signature(relocated)==image_signature(frames[0])==frame['image_signature']
    history=[{'provider':'yandex-images','query':'original frame','language':'image','status':'no_results',
        'image_sha256':'a-different-jpeg-sha','image_signature':frame['image_signature'],
        'execution':{'query_submitted':True,'results_observed':True},'requests':[{'at':1}]}]
    assert fresh_frames(frames,'yandex-images',history)==fresh_frames([relocated],'yandex-images',history)==[]
    summary=frame_summary(encoded)
    assert 'data_base64' not in summary[0]['frames'][0] and 'data_base64' in frame
    assert snapshot(studio,state['id'])['preparation_frame_evidence']==summary
    proof=inspect_artifact(studio,state,{'path':str(frames[0])})
    assert proof['sha256']==frame['sha256'] and proof['image_signature']==frame['image_signature']
    assert studio.store.get(state['id'])==before


@pytest.mark.parametrize('damage',['pixels','registration','payload','foreign_frame','budget','count','linked'])
def test_frame_capture_cannot_export_unregistered_changed_foreign_or_unbounded_pixels(tmp_path,monkeypatch,damage):
    from hotpost import video_agent_preparation_evidence as module
    studio,state,bundle,reference,frames,register=captured(tmp_path)
    if damage=='pixels':frames[0].write_bytes(b'changed')
    elif damage=='registration':bundle.write_text('{}','utf8')
    elif damage=='payload':
        value=json.loads(bundle.read_text('utf8'));value['frames']=[]
        bundle.write_text(json.dumps(value),'utf8');register()
    elif damage=='foreign_frame':
        value=json.loads(bundle.read_text('utf8'));foreign=tmp_path/'private.jpg';foreign.write_bytes(frames[0].read_bytes())
        value['frames']=[str(foreign)];value['files'].append({'path':str(foreign),'sha256':hashlib.sha256(foreign.read_bytes()).hexdigest()})
        value['payload_sha256']=payload_key(value);bundle.write_text(json.dumps(value),'utf8');register()
    elif damage=='budget':monkeypatch.setattr(module,'TOTAL_FRAME_BYTES',1)
    elif damage=='count':monkeypatch.setattr(module,'MAX_FRAMES',0)
    elif damage=='linked':
        target=tmp_path/'private.jpg';target.write_bytes(frames[0].read_bytes());frames[0].unlink()
        try:frames[0].symlink_to(target)
        except OSError:pytest.skip('Symlink privilege unavailable')
    rows=preparation_frames(studio,state,include_bytes=True)
    assert not any(row.get('frames') or row.get('status')=='captured' for row in rows)
    with pytest.raises(ValueError):inspect_artifact(studio,state,{'path':str(frames[0])})


def test_replacement_after_diagnostics_is_rejected_before_frame_export(tmp_path,monkeypatch):
    from hotpost.video_agent_context import preparation_query_diagnostics
    studio,state,bundle,reference,frames,register=captured(tmp_path)
    diagnostics=preparation_query_diagnostics(studio,state)
    frames[0].write_bytes(b'changed after diagnostic')
    result=preparation_frames(studio,state,include_bytes=True,diagnostics=diagnostics)
    assert result[0]['status']=='unavailable' and result[0]['frames']==[]


def test_model_incident_navigation_omits_bytes_but_isolated_fixture_keeps_them(env):
    from hotpost.video_agent_repairs import RepairRejected
    fixture={'task':{'id':'task-1'},'job':{'id':'job-1'},'artifacts':[],
        'preparation_frame_evidence':[{'status':'captured','frames':[{'path':'original.jpg',
            'sha256':'original-sha','data_base64':'SECRET-IMMUTABLE-PIXELS'}]}]}
    patch=proposal(env);patch['incident_fixture']=fixture
    rid=env.pipeline.propose_patch(patch);record=env.pipeline._read(rid)
    path=env.pipeline._folder(rid)/'stage'/record['incident_fixture']['relative_path'];before=path.read_bytes()
    for subtree in [[],['preparation_frame_evidence'],['preparation_frame_evidence',0,'frames',0]]:
        result=env.pipeline.inspect_incident(rid,'task-1',subtree)
        assert 'SECRET-IMMUTABLE-PIXELS' not in result['content']
        assert 'data_base64' not in result['content'] and result['fixture_media_bytes_omitted']
    with pytest.raises(RepairRejected):
        env.pipeline.inspect_incident(rid,'task-1',['preparation_frame_evidence',0,'frames',0,'data_base64'])
    assert path.read_bytes()==before and b'SECRET-IMMUTABLE-PIXELS' in before
    with pytest.raises(RepairRejected,match='guards require a separate reviewed change'):
        env.pipeline._path('main','hotpost/video_agent_preparation_evidence.py',edit=True)


def test_owner_proposal_receives_host_pixels_while_review_receives_only_their_metadata(tmp_path):
    from types import SimpleNamespace
    from hotpost.video_agents import VideoAgentManager
    from hotpost.video_agent_context import semantic_fingerprint
    studio,state,bundle,reference,frames,register=captured(tmp_path)
    received=[]
    studio.video_repair_pipeline=SimpleNamespace(propose_patch=lambda patch:received.append(patch) or 'repair',
        repair_material=lambda *args:{'content_fingerprint':'new-code'})
    with studio.store.transaction() as db:
        jid=studio.store.enqueue(db,state['id'],'collect_sources',{'run_id':state['run_id']},'failed-original')
        db.execute("update jobs set status='failed' where id=?",(jid,))
    manager=VideoAgentManager(studio)
    try:
        result=manager.execute(state['id'],{'kind':'propose_patch','_agent_epoch':1,
            'patch':{'binding':{'job_id':jid},'incident_fixture':{'spoofed':'untrusted-model-pixels'}}},
            'capture',semantic_fingerprint(state))
        assert result['status']=='completed'
        patch=received[0]
        fixture=patch['incident_fixture']['preparation_frame_evidence']
        review=patch['incident']['preparation_frame_evidence']
        assert fixture[0]['status']=='captured'
        assert base64.b64decode(fixture[0]['frames'][0]['data_base64'])==frames[0].read_bytes()
        assert review==frame_summary(fixture) and '"data_base64":' not in json.dumps(review)
        assert 'spoofed' not in patch['incident_fixture']
    finally:manager.pool.shutdown(wait=True)
