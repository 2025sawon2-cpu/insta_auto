import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from hotpost.retry_budget import reserve
from hotpost.retry_policy import classify_failure
from hotpost.operation_progress import NoProgressTimeout
from hotpost.model_service import ModelServiceUnavailable
from hotpost.studio_store import StudioStore


def fixture(tmp_path):
    store = StudioStore(tmp_path)
    state, _ = store.create('budget', 'budget', prepare=False, initial={
        'script_id': 's1', 'scripts': [{'id': 's1', 'text': 'same script'}],
        'voice_id': 'v1', 'voices': [{'id': 'v1', 'sha256': 'audio-sha'}],
        'sources': [{'id': 'source1', 'sha256': 'video-sha',
                     'reviewed_intervals': [{'source_start': 1, 'source_end': 4}]}]})
    return store, state


def job(state, name='job1', payload=None):
    return {'id': name, 'task_id': state['id'], 'kind': 'edit',
            'payload': payload or {}, 'checkpoint': {}}


def failure():
    return classify_failure(ConnectionResetError('network'), stage='edit')


@pytest.mark.parametrize('field', ['watermark_masks', 'reviewed_intervals'])
def test_nullable_source_lists_do_not_reset_retry_identity(tmp_path, field):
    store, state = fixture(tmp_path)
    state['sources'][0][field] = None
    assert reserve(store, job(state, 'nullable'), failure(), state)
    state['sources'][0][field] = []
    assert reserve(store, job(state, 'empty'), failure(), state)
    state['sources'][0].pop(field)
    assert not reserve(store, job(state, 'absent'), failure(), state)
    assert len({r['fingerprint'] for r in rows(store)}) == 1


def rows(store):
    with store.connect() as db:
        return [dict(r) for r in db.execute('SELECT * FROM retry_budget_attempts ORDER BY id')]


def test_new_job_claim_and_restart_cannot_reset_two_retry_limit(tmp_path):
    store, state = fixture(tmp_path)
    first = job(state)
    assert reserve(store, first, failure(), state)
    restarted = StudioStore(tmp_path)
    assert reserve(restarted, job(state, 'job2'), failure(), state)
    third = job(state, 'job3')
    assert not reserve(restarted, third, failure(), state)
    assert third['checkpoint']['retry_budget']['used'] == 2
    assert third['checkpoint']['retry_budget']['fingerprint'] == first['checkpoint']['retry_budget']['fingerprint']
    assert len(rows(store)) == 3 and sum(r['reserved'] for r in rows(store)) == 2


def test_concurrent_atomic_cap_is_two_and_all_attempts_are_recorded(tmp_path):
    store, state = fixture(tmp_path)
    def invoke(index):
        return reserve(store, job(state, str(index)), failure(), state)
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(invoke, range(20)))
    assert sum(outcomes) == 2
    assert len(rows(store)) == 20 and sum(r['reserved'] for r in rows(store)) == 2


@pytest.mark.parametrize('change', ['script_text', 'voice_sha', 'source_sha', 'interval', 'payload', 'repair',
                                   'original_text', 'product'])
def test_meaningfully_changed_input_has_its_own_budget(tmp_path, change):
    store, state = fixture(tmp_path)
    assert reserve(store, job(state, 'a'), failure(), state)
    assert reserve(store, job(state, 'b'), failure(), state)
    changed = copy.deepcopy(state)
    next_job = job(changed, 'c')
    if change == 'script_text': changed['scripts'][0]['text'] = 'new content'
    elif change == 'voice_sha': changed['voices'][0]['sha256'] = 'new-audio'
    elif change == 'source_sha': changed['sources'][0]['sha256'] = 'new-video'
    elif change == 'interval': changed['sources'][0]['reviewed_intervals'][0]['source_end'] = 5
    elif change == 'payload': next_job['payload']['start_time'] = 2.5
    elif change == 'repair': next_job['payload']['repair_input_signature'] = 'actual-new-repair'
    elif change == 'original_text': changed['original_text'] = 'corrected reference content'
    elif change == 'product': changed['product'] = 'corrected product'
    assert reserve(store, next_job, failure(), changed)


def test_volatile_payload_output_ids_and_source_paths_do_not_create_new_budget(tmp_path):
    store, state = fixture(tmp_path)
    for i in range(3):
        payload = {'job_id': str(i), 'run_id': str(i), 'created_at': i, 'retry_count': i,
                   'edit_id': 'new-output-' + str(i), 'output_path': 'file' + str(i),
                   'options': {'claim_token': str(i), 'source_start': 1}}
        changed = copy.deepcopy(state)
        changed['sources'][0].update(id='new-id-' + str(i), path='new-path-' + str(i))
        assert reserve(store, job(state, str(i), payload), failure(), changed) is (i < 2)


def test_nonretryable_and_service_waits_never_consume_budget(tmp_path):
    store, state = fixture(tmp_path)
    for exc in [NoProgressTimeout(), ModelServiceUnavailable(), ValueError('503')]:
        assert not reserve(store, job(state), classify_failure(exc), state)
    assert reserve(store, job(state, 'a'), failure(), state)
    assert reserve(store, job(state, 'b'), failure(), state)
    assert sum(r['reserved'] for r in rows(store)) == 2
    assert len(rows(store)) == 5


def test_unknown_or_service_category_cannot_request_budget_with_boolean_only(tmp_path):
    store, state = fixture(tmp_path)
    for category in ['service_wait', 'service_capacity', 'no_progress', 'unrecognized']:
        classification = {**failure(), 'category': category}
        assert not reserve(store, job(state), classification, state)
    assert not any(r['reserved'] for r in rows(store))


def test_changed_retry_after_and_message_do_not_reset_budget(tmp_path):
    store, state = fixture(tmp_path)
    for i in range(3):
        classified = classify_failure(ConnectionResetError('caption ' + str(i)), stage='edit')
        classified['retry_after_seconds'] = 15 * i
        assert reserve(store, job(state, str(i)), classified, state) is (i < 2)


def test_current_claim_diagnostic_persisted_duplicate_and_stale_claim_blocked(tmp_path):
    store, state = fixture(tmp_path)
    with store.transaction() as db:
        identifier = store.enqueue(db, state['id'], 'edit', {}, 'first')
    first = store.claim(job_id=identifier)
    assert reserve(store, first, failure(), state)
    assert not reserve(store, first, failure(), state)
    assert first['checkpoint']['retry_budget']['reason'] == 'duplicate_reservation'
    with store.connect() as db:
        checkpoint = json.loads(db.execute('SELECT checkpoint FROM jobs WHERE id=?', (identifier,)).fetchone()[0])
    assert checkpoint['retry_budget'] == first['checkpoint']['retry_budget']
    store.recover()
    current = store.claim(job_id=identifier)
    assert not reserve(store, first, failure(), state)
    assert first['checkpoint']['retry_budget']['reason'] == 'stale_claim'
    assert reserve(store, current, failure(), state)
    store.recover()
    third = store.claim(job_id=identifier)
    assert not reserve(store, third, failure(), state)
    assert third['checkpoint']['retry_budget']['reason'] == 'budget_exhausted'
    assert sum(r['reserved'] for r in rows(store)) == 2


def test_same_bytes_source_reordering_and_selected_id_mapping_are_stable(tmp_path):
    store, state = fixture(tmp_path)
    state['sources'].append({'id': 'source2', 'sha256': 'video2'})
    first = job(state, 'first', {'source_ids': ['source1', 'source2']})
    assert reserve(store, first, failure(), state)
    changed = copy.deepcopy(state)
    changed['sources'].reverse()
    changed['sources'][0]['id'] = 'renamed'
    second = job(changed, 'second', {'source_ids': ['renamed', 'source1']})
    assert reserve(store, second, failure(), changed)
    assert first['checkpoint']['retry_budget']['fingerprint'] == second['checkpoint']['retry_budget']['fingerprint']
