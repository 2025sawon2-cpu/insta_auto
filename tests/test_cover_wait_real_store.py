import copy
import inspect
import json
import runpy
from pathlib import Path

from hotpost.studio_store import StudioStore
from hotpost import daily_quality_routing


def test_captured_done_qa_real_queue_and_persistence(tmp_path, monkeypatch):
    helpers=runpy.run_path(str(Path(__file__).with_name('test_current_cover_wait_entry.py')))
    incident=helpers['captured'](tmp_path)
    state=incident['task']; job=incident['job']
    assert job['status']=='done' and job['kind']=='quality_review'
    assert state['daily_quality']['pending']=='scene_wait'
    assert job['task_id']==state['id']
    assert job['payload']['edit_id']==state['edit_id']
    store=StudioStore(tmp_path/'studio')
    with store.connect() as db:
        db.execute('INSERT INTO tasks VALUES(?,?,?,?,?)',(state['id'],state['shortcode'],state['revision'],json.dumps(state),state['updated']))
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',(job['id'],job['task_id'],job['kind'],job['key'],json.dumps(job['payload']),job['status'],json.dumps(job['checkpoint']),job['error'],job['created'],job['updated']))
        original=dict(db.execute('SELECT * FROM jobs WHERE id=?',(job['id'],)).fetchone())
    worker=helpers['Worker']();worker.store=store
    source=inspect.getsource(daily_quality_routing.advance_daily_quality)
    start=source.index('    from .quality_progress import valid_cover_evidence')
    end=source.index('    key=f',start)
    old=source[:start]+source[end:]
    old=old.replace(' and coverage_current(state) and cover_ready:', ' and coverage_current(state):')
    namespace=dict(daily_quality_routing.__dict__)
    exec(compile(old,'preserved-old-routing','exec'),namespace)
    with monkeypatch.context() as patch:
        patch.setattr(daily_quality_routing,'advance_daily_quality',namespace['advance_daily_quality'])
        store.change(state['id'],worker.advance_workflow)
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==1
    assert store.get(state['id'])['daily_quality']['pending']=='scene_wait'
    before=copy.deepcopy(store.get(state['id']))
    store.change(state['id'],worker.advance_workflow)
    saved=store.get(state['id'])
    with store.connect() as db:
        assert dict(db.execute('SELECT * FROM jobs WHERE id=?',(job['id'],)).fetchone())==original
        rows=db.execute('SELECT * FROM jobs WHERE id<>?',(job['id'],)).fetchall()
        assert len(rows)==1
        row=dict(rows[0])
        assert row['task_id']==state['id']
        assert row['kind']=='refresh_sources' and row['status']=='queued'
        assert json.loads(row['payload'])['daily_quality_repair'] is True
        assert row['key'].endswith(':refresh_sources:'+state['edit_id'])
    assert saved['daily_quality']['pending']=='recollecting'
    assert saved['automation']['stage']=='refresh_sources'
    assert saved['daily_quality']['status']!='passed'
    for key in ('reviews','feedback','reviewed_edit_id'):
        assert saved['daily_quality'].get(key)==before['daily_quality'].get(key)
    for key in ('id','run_id','script_id','voice_id','edit_id'):
        assert saved[key]==before[key]
    store.change(state['id'],worker.advance_workflow)
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==2
        assert dict(db.execute('SELECT * FROM jobs WHERE id=?',(job['id'],)).fetchone())==original
