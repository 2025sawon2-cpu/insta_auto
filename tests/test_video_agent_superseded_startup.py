import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from hotpost import video_agent_runtime as runtime
from hotpost import video_agent_repairs as repairs
from test_video_agent_repairs import env, ready


@pytest.mark.parametrize('fault',[None,'missing_marker','unauthenticated','barrier'])
def test_authenticated_superseded_source_does_not_crash_or_authorize_retry(env,monkeypatch,fault):
    rid,review=ready(env)
    receipt=env.pipeline.apply_patch(rid,store=env.store,review_id=review['review_id'])
    # Fixture represents a previously cold-loaded repair, whose apply barrier
    # was already cleared before the later, separately reviewed source change.
    (env.store.root/'agent-maintenance.json').unlink()
    record_path=env.pipeline.receipts/rid/'repair.json'
    original=record_path.read_bytes()
    (env.main/'hotpost/calculation.py').write_text('def combine(a,b):\n    return a*b\n','utf8')
    marker=env.store.root/'agent-restart.json';marker.write_text(json.dumps(receipt),'utf8')
    if fault=='missing_marker':
        marker.unlink()
        (env.store.root/'agent-loaded.json').write_text(json.dumps(receipt),'utf8')
        (env.store.root/'agent-loaded-repairs.json').write_text(json.dumps({rid:receipt}),'utf8')
    if fault=='unauthenticated':
        record=json.loads(original);record['review']['signature']='invalid'
        record_path.write_text(json.dumps(record),'utf8');original=record_path.read_bytes()
    if fault=='barrier':
        (env.store.root/'agent-maintenance.json').write_text(json.dumps({'repair_id':rid,'phase':'applied'}),'utf8')
    before=env.store.get(env.state['id']);marker_bytes=marker.read_bytes() if marker.exists() else None
    monkeypatch.setattr(repairs,'VideoRepairPipeline',lambda *a,**k:env.pipeline)
    app=SimpleNamespace(store=env.store,settings=SimpleNamespace(auto_capcut_root=env.renderer,auto_capcut_python=sys.executable))
    manager=SimpleNamespace(request_restart=lambda *a:pytest.fail('No restart loop for obsolete source'))
    resumed=[];monkeypatch.setattr(runtime,'resume_loaded_repairs',lambda *a:resumed.append(a[0].loaded_code_receipts))
    if fault=='unauthenticated':
        with pytest.raises(repairs.RepairRejected,match='authenticated'):runtime.configure(app,manager)
        assert not (env.store.root/'agent-loaded.json').exists()
    elif fault=='barrier':
        with pytest.raises(RuntimeError,match='barrier'):runtime.configure(app,manager)
        assert (env.store.root/'agent-maintenance.json').exists()
    else:
        with pytest.raises(repairs.AppliedSourceChanged):env.pipeline.applied_receipt(rid)
        runtime.configure(app,manager)
        assert app.loaded_code_receipt is None and app.loaded_code_receipts=={}
        assert all(not proof for proof in resumed)
        assert app.superseded_code_receipts[0]['repair_id']==rid
        loaded=json.loads((env.store.root/'agent-loaded.json').read_text('utf8'))
        assert loaded['status']=='no_current_applied_repair' and 'repair_id' not in loaded
        # Repeating startup cannot turn the historical marker into authority.
        runtime.configure(app,manager)
        assert all(not proof for proof in resumed) and app.loaded_code_receipts=={}
        assert json.loads((env.store.root/'agent-loaded-repairs.json').read_text('utf8'))=={}
    assert record_path.read_bytes()==original
    assert (marker.read_bytes() if marker.exists() else None)==marker_bytes
    assert env.store.get(env.state['id'])==before
    with env.store.connect() as db:assert db.execute("select status from jobs where id='job-1'").fetchone()[0]=='failed'


def test_current_older_owner_proof_is_retained_when_latest_source_was_superseded(tmp_path,monkeypatch):
    source=Path(runtime.__file__);root=source.parents[1]
    from hotpost.studio_store import StudioStore
    store=StudioStore(tmp_path/'studio');receipts=tmp_path/'receipts'
    current={'repair_id':'repair-older-current','status':'applied','applied_at':1,
        'binding':{'task_id':'other-task'},'files':[{'repo':'main','path':'hotpost/video_agent_runtime.py',
        'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}]}
    obsolete={**copy.deepcopy(current),'repair_id':'repair-latest-superseded','applied_at':2,'binding':{'task_id':'stale-task'}}
    for item in [current,obsolete]:
        folder=receipts/item['repair_id'];folder.mkdir(parents=True)
        (folder/'repair.json').write_text(json.dumps(item),'utf8')
    def authenticate(rid):
        if rid==obsolete['repair_id']:raise repairs.AppliedSourceChanged('source changed')
        assert rid==current['repair_id'];return copy.deepcopy(current)
    pipeline=SimpleNamespace(receipts=receipts,roots={'main':root},applied_receipt=authenticate)
    monkeypatch.setattr(repairs,'VideoRepairPipeline',lambda *a,**k:pipeline)
    app=SimpleNamespace(store=store,settings=SimpleNamespace(auto_capcut_root=tmp_path,auto_capcut_python=sys.executable))
    resumed=[];monkeypatch.setattr(runtime,'resume_loaded_repairs',lambda *a:resumed.append(set(a[0].loaded_code_receipts)))
    runtime.configure(app,SimpleNamespace(request_restart=lambda *a:pytest.fail('already cold loaded')))
    assert set(app.loaded_code_receipts)=={current['repair_id']}
    assert app.loaded_code_receipt['repair_id']==current['repair_id']
    assert resumed==[{current['repair_id']}]
    assert app.superseded_code_receipts[0]['binding']==obsolete['binding']
