import copy
import json
import os
from pathlib import Path

from hotpost.config import Settings
from hotpost.studio import Studio


def test_preserved_done_round_schedules_preparation_without_releasing_hold(tmp_path):
    captured = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    import hashlib
    reference = tmp_path / 'reference.mp4'
    reference.write_bytes(b'isolated scheduling reference')
    replacement_sha = hashlib.sha256(reference.read_bytes()).hexdigest()
    original_path = captured['task']['reference_video']
    original_sha = captured['task']['source_acquisition']['visual_query_rejection']['reference_sha256']
    def remap(value):
        if isinstance(value, dict):
            return {k: remap(v) for k, v in value.items()}
        if isinstance(value, list):
            return [remap(v) for v in value]
        if isinstance(value, str):
            if value == original_path:
                return str(reference.resolve())
            if value == original_sha:
                return replacement_sha
        return value
    state = remap(copy.deepcopy(captured['task']))
    job = remap(copy.deepcopy(captured['job']))
    assert state['id'] == captured['task']['id']
    assert job['id'] == captured['job']['id']
    assert state['run_id'] == captured['task']['run_id']
    assert job['status'] == 'done'
    assert job['task_id'] == state['id']
    assert job['payload']['run_id'] == state['run_id']
    assert state['source_acquisition']['hold']['reason'] == 'strategy_exhausted'
    original_hold = copy.deepcopy(state['source_acquisition']['hold'])
    studio = Studio(Settings(data_dir=tmp_path), workers=False)
    try:
        with studio.store.transaction() as db:
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)',
                (state['id'],state['shortcode'],state.get('revision',0),json.dumps(state),1))
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)',
                (job['id'],state['id'],job['kind'],job['key'],json.dumps(job['payload']),
                 job['status'],json.dumps(job['checkpoint']),job['error'],job['created'],job['updated']))
            before = dict(db.execute('SELECT * FROM jobs WHERE id=?',(job['id'],)).fetchone())
            studio.ensure_source_collection(state,db)
            rows = db.execute('SELECT * FROM jobs WHERE task_id=? AND id<>?',
                              (state['id'],job['id'])).fetchall()
            assert len(rows) == 1
            payload = json.loads(rows[0]['payload'])
            assert rows[0]['status'] == 'queued'
            assert payload['planning_recovery_from'] == job['id']
            assert payload['run_id'] == state['run_id']
            assert state['source_acquisition']['hold'] == original_hold
            assert dict(db.execute('SELECT * FROM jobs WHERE id=?',(job['id'],)).fetchone()) == before
            studio.ensure_source_collection(state,db)
            assert db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 2
        assert captured == json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    finally:
        studio.close()
