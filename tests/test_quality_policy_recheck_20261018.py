"""Independent guards for one explicit, immutable-input policy recheck.

These tests use temporary Studio stores with workers disabled. The media boundary
tests stop at an explicit decode sentinel; fixture bytes are never fake-decoded.
"""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from hotpost import daily_quality
from hotpost.studio_store import Conflict
from test_daily_quality import ready as daily_ready
from test_quality_progress_independent import _quality_review_cache_fixture


def rows(studio, task):
    with studio.store.connect() as db:
        return [dict(row) for row in db.execute(
            'SELECT * FROM jobs WHERE task_id=? ORDER BY id', (task,))]


@pytest.fixture
def stopped(daily_ready):
    studio, task = daily_ready
    job = studio.store.claim(task_id=task)
    assert job['kind'] == 'quality_review'
    studio.store.fail(job, ValueError('preserved visual transport failure'))

    def pause(state, db):
        source_job = studio.store.enqueue(db, task, 'refresh_sources',
            {'daily_quality_repair': True}, 'preserved-paused-search')
        db.execute("UPDATE jobs SET status='paused' WHERE id=?", (source_job,))
        state.update(status='attention', error='preserved visual transport failure')
        state['automation'].update(active=False, paused_by_user=False)
        state['daily_quality'].update(status='needs_attention', pending='failed',
            error='preserved visual transport failure', failed_job_id=job['id'],
            failed_job_kind='quality_review',
            feedback=[{'kind': 'scene_gap', 'beat_id': 'b1', 'reason': 'prior finding'}],
            reviews=[{'edit_id': 'old-edit', 'passed': False, 'issues': ['prior raw result']}])
    studio.store.change(task, pause)
    state = studio.store.get(task)
    edit = state['edits'][0]
    request = {'reason': 'clarified whole-montage policy; independently review actual output',
        'edit_id': edit['id'],
        'render_sha256': hashlib.sha256(Path(edit['preview_path']).read_bytes()).hexdigest(),
        'plan_sha256': hashlib.sha256(Path(edit['plan_path']).read_bytes()).hexdigest()}
    return studio, task, request


def reject_unchanged(studio, task, request, error=Conflict):
    state_before, jobs_before = studio.store.get(task), rows(studio, task)
    with pytest.raises(error):
        studio.action(task, 'recheck-quality', request)
    assert studio.store.get(task) == state_before
    assert rows(studio, task) == jobs_before


def test_recheck_queues_one_new_review_and_preserves_failed_and_paused_work(stopped):
    studio, task, request = stopped
    before, old_jobs = studio.store.get(task), rows(studio, task)
    studio.action(task, 'recheck-quality', request)
    state, jobs = studio.store.get(task), rows(studio, task)
    assert len(jobs) == len(old_jobs) + 1
    assert [j for j in jobs if j['id'] in {r['id'] for r in old_jobs}] == old_jobs
    new = next(j for j in jobs if j['id'] not in {r['id'] for r in old_jobs})
    payload = json.loads(new['payload'])
    assert new['kind'] == 'quality_review' and new['status'] == 'queued'
    assert payload['explicit_policy_recheck'] is True
    assert payload['render_sha256'] == request['render_sha256']
    assert payload['plan_sha256'] == request['plan_sha256']
    assert payload['review_contract_sha256'] == hashlib.sha256(daily_quality.REVIEW_INSTRUCTION.encode()).hexdigest()
    for key in ('sources', 'scripts', 'voices', 'edits', 'runs', 'script_id', 'voice_id', 'edit_id'):
        assert state[key] == before[key]
    quality = state['daily_quality']
    assert quality['reviews'] == before['daily_quality']['reviews']
    assert quality['feedback'] == before['daily_quality']['feedback']
    assert quality['repair_round'] == before['daily_quality']['repair_round']
    assert quality['recheck_history'][-1]['prior'] == {
        key: before['daily_quality'].get(key)
        for key in ('status', 'pending', 'error', 'failed_job_id', 'failed_job_kind')}
    assert state['status'] == 'quality_review'
    assert state['automation']['active'] and not state['automation']['paused_by_user']
    claimed = studio.store.claim(task_id=task)
    assert claimed['id'] == new['id']
    assert next(j for j in rows(studio, task) if j['kind'] == 'refresh_sources')['status'] == 'paused'


@pytest.mark.parametrize('change', ['reason', 'edit_id', 'render_sha256', 'plan_sha256', 'revision'])
def test_recheck_rejects_stale_or_incomplete_request_atomically(stopped, change):
    studio, task, request = stopped
    request[change] = ('   ' if change == 'reason' else -1 if change == 'revision' else 'stale')
    reject_unchanged(studio, task, request, ValueError if change == 'reason' else Conflict)


def test_recheck_rejects_task_without_quality_contract(stopped):
    studio, task, request = stopped
    studio.store.change(task, lambda s, db: s['daily_quality'].update(policy='not-daily-review'))
    reject_unchanged(studio, task, request, ValueError)


@pytest.mark.parametrize('status', ['queued', 'running'])
def test_recheck_does_not_overlap_any_active_task_work(stopped, status):
    studio, task, request = stopped
    def active(state, db):
        jid = studio.store.enqueue(db, task, 'refresh_sources', {}, 'active-search')
        db.execute('UPDATE jobs SET status=? WHERE id=?', (status, jid))
    studio.store.change(task, active)
    reject_unchanged(studio, task, request)


@pytest.mark.parametrize('token', [None, 100.0, '101.0'])
def test_recheck_does_not_clear_an_unacknowledged_user_pause(stopped, token):
    studio, task, request = stopped
    studio.store.change(task, lambda s, db: s['automation'].update(
        paused_by_user=True, paused_at=101.0, pause_reason='user stop'))
    if token is not None:
        request['resume_pause_token'] = token
    reject_unchanged(studio, task, request)


def test_exact_pause_token_only_resumes_new_qa_not_historical_search(stopped):
    studio, task, request = stopped
    studio.store.change(task, lambda s, db: s['automation'].update(
        paused_by_user=True, paused_at=101.0, pause_reason='user stop'))
    request['resume_pause_token'] = 101.0
    old_jobs = rows(studio, task)
    studio.action(task, 'recheck-quality', request)
    assert not studio.store.get(task)['automation']['paused_by_user']
    assert [j for j in rows(studio, task) if j['id'] in {r['id'] for r in old_jobs}] == old_jobs


@pytest.mark.parametrize('status', ['done', 'failed', 'paused', 'superseded', 'cancelled'])
def test_same_render_and_policy_recheck_is_never_revived_or_repeated(stopped, status):
    studio, task, request = stopped
    studio.action(task, 'recheck-quality', request)
    def settle(state, db):
        db.execute("UPDATE jobs SET status=? WHERE task_id=? AND key LIKE 'quality-policy-recheck:%'", (status, task))
    studio.store.change(task, settle)
    reject_unchanged(studio, task, request)


def test_actual_policy_change_can_enqueue_an_independent_new_recheck(stopped, monkeypatch):
    studio, task, request = stopped
    studio.action(task, 'recheck-quality', request)
    studio.store.change(task, lambda s, db: db.execute(
        "UPDATE jobs SET status='done' WHERE task_id=? AND status='queued'", (task,)))
    monkeypatch.setattr(daily_quality, 'REVIEW_INSTRUCTION', daily_quality.REVIEW_INSTRUCTION + ' New clarified policy.')
    studio.action(task, 'recheck-quality', request)
    rechecks = [j for j in rows(studio, task) if j['key'].startswith('quality-policy-recheck:')]
    assert len(rechecks) == 2 and len({j['key'] for j in rechecks}) == 2
    assert len(studio.store.get(task)['daily_quality']['recheck_history']) == 2


def recheck_job(edit, prior):
    return {'id': 'explicit-fresh-review', 'payload': {
        'edit_id': edit['id'], 'explicit_policy_recheck': True,
        'render_sha256': prior['render_sha256'], 'plan_sha256': prior['plan_sha256'],
        'review_contract_sha256': prior['review_contract_sha256'], 'reason': 'actual independent re-evaluation'}}


@pytest.mark.parametrize('changed', ['render_sha256', 'plan_sha256', 'review_contract_sha256'])
def test_worker_rejects_recheck_inputs_or_policy_changed_after_enqueue(daily_ready, monkeypatch, changed):
    studio, state, edit, prior = _quality_review_cache_fixture(daily_ready)
    job = recheck_job(edit, prior)
    job['payload'][changed] = 'stale-enqueue-binding'
    preserved = copy.deepcopy(prior)
    monkeypatch.setattr(daily_quality.subprocess, 'run', lambda *a, **k: pytest.fail('Stale request must stop before media decode'))
    monkeypatch.setattr('hotpost.script_rewriter._generate', lambda *a, **k: pytest.fail('Stale request cannot call a model'))
    with pytest.raises((ValueError, Conflict)):
        studio._quality_review(state, job)
    assert state['daily_quality']['reviews'] == [preserved]


def test_explicit_recheck_freshly_evaluates_even_a_bound_previous_false_receipt(daily_ready, monkeypatch):
    studio, state, edit, prior = _quality_review_cache_fixture(daily_ready)
    preserved = copy.deepcopy(prior)

    class FreshActualMediaReview(RuntimeError):
        pass

    calls = []
    def decode(command, **kwargs):
        assert command == ['ffmpeg', '-v', 'error', '-xerror', '-i', edit['preview_path'], '-f', 'null', '-']
        assert kwargs == {'check': True, 'capture_output': True}
        calls.append(command)
        raise FreshActualMediaReview('fresh actual-media path selected; no fake decode')
    monkeypatch.setattr(daily_quality.subprocess, 'run', decode)
    monkeypatch.setattr('hotpost.script_rewriter._generate', lambda *a, **k: pytest.fail('Model must follow real decode'))
    with pytest.raises(FreshActualMediaReview, match='fresh actual-media path selected'):
        studio._quality_review(state, recheck_job(edit, prior))
    assert len(calls) == 1
    assert state['daily_quality']['reviews'] == [preserved]


def test_same_edit_explicit_false_result_settles_to_hold_without_a_pending_ghost(stopped):
    """Acceptance-only test: the independent fresh decode path is tested above."""
    studio, task, request = stopped
    finding = {'kind': 'cover', 'beat_id': '', 'reason': 'actual cover still exposes the answer', 'search_query': ''}
    prior = {'edit_id': request['edit_id'], 'passed': False, 'issues': [finding],
        'render_sha256': request['render_sha256'], 'plan_sha256': request['plan_sha256'],
        'policy': daily_quality.POLICY, 'review_path': 'preserved-prior-review.json',
        'review_contract_sha256': hashlib.sha256(daily_quality.REVIEW_INSTRUCTION.encode()).hexdigest()}

    def prior_review(state, db):
        state['daily_quality'].update(reviews=[copy.deepcopy(prior)],
            reviewed_edit_id=request['edit_id'], feedback=[finding])
        state['daily_quality'].pop('progress_policy', None)
    studio.store.change(task, prior_review)
    studio.action(task, 'recheck-quality', request)
    job = studio.store.claim(task_id=task)
    assert job['payload']['explicit_policy_recheck']
    before_count = len(rows(studio, task))
    result = {**copy.deepcopy(prior), 'review_path': 'independent-new-review.json'}
    assert studio.store.finish(job, result, lambda s, db, value: studio._accept(s, job, value, db))
    state = studio.store.get(task)
    quality = state['daily_quality']
    assert quality['status'] == 'needs_attention' and quality['pending'] == 'scene_wait'
    assert state['status'] != 'quality_review'
    assert quality['progress_policy']['decision']['action'] == 'stop_method'
    assert quality['reviews'] == [prior]
    assert quality['feedback'] == [finding]
    assert quality['repair_round'] == 0
    jobs = rows(studio, task)
    assert len(jobs) == before_count
    assert next(j for j in jobs if j['id'] == job['id'])['status'] == 'done'
    assert not any(j['status'] in {'running', 'queued'} for j in jobs)
    assert next(j for j in jobs if j['kind'] == 'refresh_sources')['status'] == 'paused'
