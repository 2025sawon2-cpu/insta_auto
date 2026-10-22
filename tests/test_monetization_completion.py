"""Completion must be atomic, forward-only and bound to the finished media."""
import json
import sqlite3

import pytest

from hotpost.config import Settings
from hotpost.monetization import Monetization
from hotpost.studio_store import StudioStore


def finished_fixture(tmp_path):
    store = StudioStore(tmp_path / 'studio')
    video = tmp_path / 'final.mp4'; video.write_bytes(b'reviewed-video')
    plan = tmp_path / 'timeline.json'; plan.write_text('{}', 'utf-8')
    # This handoff fixture represents a saved pre-diversity export, not a new
    # v6 production. Quality-policy enforcement has separate integration tests.
    initial = dict(edit_id='edit', script_id='script', source_policy={},
        scripts=[dict(id='script', text='제품 소개')],
        edits=[dict(id='edit', export_verified=True, export_path=str(video), plan_path=str(plan))])
    state, _ = store.create('Reference', 'product', prepare=False, initial=initial)
    return store, state, video, initial


def test_completion_and_outbox_rollback_in_same_transaction_and_no_backfill(tmp_path):
    store, state, _, initial = finished_fixture(tmp_path)
    with pytest.raises(RuntimeError):
        with store.transaction() as db:
            current = store.get(state['id'], db)
            current['status'] = 'completed'; store.save(db, current)
            assert db.execute('SELECT count(*) FROM postproduction_outbox').fetchone()[0] == 1
            raise RuntimeError('interrupted video transaction')
    assert store.get(state['id'])['status'] == 'preparing'
    assert store.postproduction_pending() == []
    store.change(state['id'], lambda s, db: s.update(status='completed'))
    assert len(store.postproduction_pending()) == 1
    # A completed historical task inserted before activation and later normal
    # metadata edits must not schedule another product request.
    historical, _ = store.create('Historical', 'old', prepare=False, initial={**initial, 'status': 'completed'})
    store.change(historical['id'], lambda s, db: s.update(message='metadata only'))
    StudioStore(store.root)
    assert len(store.postproduction_pending()) == 1


def test_missing_connections_wait_without_browser_or_external_effect(tmp_path):
    store, state, _, _ = finished_fixture(tmp_path)
    store.change(state['id'], lambda s, db: s.update(status='completed'))
    def browser(_):
        pytest.fail('No browser action before readiness')
    service = Monetization(Settings(data_dir=tmp_path), store, completion_store=store, browser_factory=browser)
    service.store.configure_automation(True, 'ouraccount')
    service.completion_tick(); service.completion_tick()
    pending = store.postproduction_pending()[0]
    assert pending['status'] == 'waiting_connections'
    current = service.store.get(state['id'])
    assert current['stage'] == 'product' and current['status'] == 'ready'
    assert service.store.effects(current) == []
    assert store.get(state['id'])['status'] == 'completed'


def test_media_changed_after_completion_cannot_automatically_dispatch(tmp_path):
    store, state, video, _ = finished_fixture(tmp_path)
    store.change(state['id'], lambda s, db: s.update(status='completed'))
    video.write_bytes(b'changed-video')
    service = Monetization(Settings(data_dir=tmp_path), store, completion_store=store)
    service.store.configure_automation(True, 'ouraccount')
    service.completion_tick()
    assert store.postproduction_pending() == []
    with store.connect() as db:
        assert db.execute('SELECT status FROM postproduction_outbox').fetchone()[0] == 'superseded'
    assert service.store.get(state['id']) is None


def reference_database(tmp_path):
    with sqlite3.connect(tmp_path / 'hotpost.db') as db:
        db.execute('CREATE TABLE posts(shortcode TEXT,caption TEXT)')
        db.execute('INSERT INTO posts VALUES(?,?)', ('Reference', '댓글에 “키티” 남겨주세요'))


def test_dispatched_handoff_with_no_worker_is_recovered_not_dropped(tmp_path):
    store, state, _, _ = finished_fixture(tmp_path)
    store.change(state['id'], lambda s, db: s.update(status='completed'))
    store.postproduction_update(state['id'], 'edit', 'dispatched')
    reference_database(tmp_path)
    service = Monetization(Settings(data_dir=tmp_path), store, completion_store=store)
    service.store.configure_automation(True, 'ouraccount')
    service.connections = lambda: {'coupang': {'configured': True, 'eligible': True}, 'existing_browser_connected': True}
    calls = []
    def resumed(task_id, account, keyword):
        calls.append((task_id, keyword))
        service.store.change(task_id, {'stage': 'awaiting_post'})
        return {'accepted': True}
    service.run = resumed
    service.completion_tick(); service.completion_tick()
    assert calls == [(state['id'], '나도')]
    assert store.postproduction_pending() == []
    with store.connect() as db:
        assert db.execute('SELECT status FROM postproduction_outbox').fetchone()[0] == 'done'


def test_live_endpoint_but_login_preflight_waits_without_consuming_attempt(tmp_path):
    store, state, _, _ = finished_fixture(tmp_path)
    store.change(state['id'], lambda s, db: s.update(status='completed'))
    reference_database(tmp_path)
    class Browser:
        def preflight(self, *args): raise ValueError('현재 로그인 필요')
    service = Monetization(Settings(data_dir=tmp_path), store, completion_store=store,
                           browser_factory=lambda _: Browser())
    service.store.configure_automation(True, 'ouraccount')
    service.credentials.save(dict(access_key='test', secret_key='test', account_ref='mine', eligible=True))
    service.connections = lambda: {'coupang': {'configured': True, 'eligible': True}, 'existing_browser_connected': True}
    service.completion_tick(); service.completion_tick()
    assert store.postproduction_pending()[0]['status'] == 'waiting_connections'
    assert service.store.effects(service.store.get(state['id'])) == []
