"""Append an exact correction and a newly reviewed window to paused rank one.

No browser/model call, job reset, render, or automatic resume is performed.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from hotpost import quality_progress as progress
from hotpost.scene_requirements import coverage_current
from hotpost.studio_store import Conflict, StudioStore

ROOT = Path(__file__).resolve().parents[1]
TASK = 'work-1672e441725d4445'
JOB = 'job-6f574ce9e7b84e6b'
EDIT = 'job-bd4f60ab7a7846fe'
RUN = 'run-15e0dac2368b46da'
BAD = '383d18ae1ddcdf6c366572d1e7fc234ad5ce63cb8bb6c479ebc0dabefe144731'
ACTUAL = '05af1d16e1bc331419e1d6ba899a4ae41233a766375f477a0dea6397c036575c'
DEFECT = '5439d6c1aa49385d0a733e35d4b8f71ec9f96c494be475cc5457f1d2e6667d25'
METHOD = '7e4d831fcd89246f0a1037dff76e7c462b79d65331516c6cc33edd4b3a284ab1'
RECEIPT_SHA = '658354283779b0aca658de41f5d0a4012abc8241490381b89cc10a4c020701eb'
OPERATION = 'rank1-preparation-classification-and-official-window-20261014-v1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(state, job, official, proof, receipt_sha):
    original = copy.deepcopy(state)
    q = state['daily_quality']; ledger = q['progress_policy']
    if any(r.get('operation') == OPERATION for r in q.get('observation_repairs', [])):
        return None
    if (not state.get('automation', {}).get('paused_by_user') or state['run_id'] != RUN
            or state['edit_id'] != EDIT or job['status'] != 'done'
            or len(state['edits']) != 1 or len(state['sources']) != 18
            or state['script_id'] != 'script-154ca25eacea4418'
            or state['voice_id'] != 'voice-run-15e0dac2368b46da'):
        raise Conflict('The exact paused rank-one inputs changed.')
    edit = state['edits'][0]
    if (sha(state['reference_video']) != '4ea495289e851872e7ef985cedcca1b7fcf4e77e53aec10bec9afced4b2e8a12'
            or sha(edit['plan_path']) != proof['selected_edit_plan_sha256']
            or sha(edit['preview_path']) != 'a4d6f396c4af63707b557894ac851f98393cc73eb707ba76702ec0b37130835d'
            or sha(state['voices'][0]['path']) != state['voices'][0]['sha256']
            or sha(proof['path']) != proof['source_sha256']):
        raise Conflict('Frozen media binding changed.')
    for frame in proof['available_approved_frames']:
        if sha(frame['path']) != frame['sha256']: raise Conflict('Approved frame changed.')
    actual = [r for r in q['reviews'] if not r.get('pre_render_scene_gap')]
    synthetic = [r for r in q['reviews'] if r.get('pre_render_scene_gap')]
    if len(actual) != 1 or len(synthetic) != 1 or actual[0]['edit_id'] != EDIT:
        raise Conflict('Review baseline is no longer the reviewed two-row history.')
    raw = synthetic[0]
    identity = progress.digest([raw.get('render_sha256') or raw['edit_id'],
        progress.projection(progress.load_plan(state, raw['edit_id'])), True, raw.get('evidence_recheck', False)])
    bad = [r for r in ledger['reviews'] if r['identity'] == identity]
    if identity != BAD or len(bad) != 1 or ledger['best']['identity'] != ACTUAL:
        raise Conflict('The original no-render observation cannot be uniquely identified.')
    correction = {'operation': OPERATION, 'review_identity': BAD, 'classification': 'preparation_only',
        'previous': copy.deepcopy(bad[0]), 'raw_report': copy.deepcopy(raw),
        'job_id': JOB, 'official_review_sha256': receipt_sha, 'at': time.time()}
    ledger.setdefault('observation_corrections', []).append(correction)
    q['feedback'] = copy.deepcopy(actual[0]['issues'])
    for did, defect in ledger['defects'].items():
        if did == DEFECT:
            target_status = 'unresolved'
        elif defect.get('first_seen') == BAD and all(h.get('review') == BAD for h in defect.get('history', [])):
            target_status = 'preparation_only'
        else:
            continue
        defect.setdefault('history', []).append({'operation': OPERATION, 'at': time.time(),
            'status': target_status, 'previous_status': defect.get('status'), 'corrected_observation': BAD})
        defect['status'] = target_status
    progress.record_preparation_failure(state, job, raw['issues'], thumbnail_lines=raw.get('thumbnail_lines'))
    for attempt in ledger['attempts']:
        if attempt.get('job_id') == JOB:
            attempt.setdefault('status_corrections', []).append({'operation': OPERATION,
                'previous': copy.deepcopy({k:v for k,v in attempt.items() if k != 'status_corrections'}),
                'status': 'preparation_failed', 'at': time.time()})
            attempt['status'] = 'preparation_failed'
    if official['effective_feedback'] != q['feedback'] or len(official['actual_calls']) != 1:
        raise Conflict('Official review was not bound to the actual defect.')
    previous_coverage = copy.deepcopy(q.get('scene_requirements'))
    q['scene_requirements'] = copy.deepcopy(official['receipt'])
    if not coverage_current(state): raise Conflict('New official window is stale or invalid.')
    method = progress.hypothesis(state, 'reedit')
    if method['key'] != METHOD or not method['grounded'] or not progress.resume_assessment(state):
        raise Conflict('The new material does not authorize a different repair method.')
    q.setdefault('observation_repairs', []).append({'operation': OPERATION,
        'previous_feedback': original['daily_quality']['feedback'],
        'previous_coverage': previous_coverage, 'previous_status': original['daily_quality']['status'],
        'previous_pending': original['daily_quality'].get('pending'),
        'official_review_sha256': receipt_sha, 'method_key': method['key'],
        'actual_render_count': 0, 'automatic_resume': False, 'at': time.time()})
    # Only effective quality fields and appended corrections may change.
    for key in original:
        if key not in {'daily_quality', 'message', 'status'} and state.get(key) != original[key]:
            raise AssertionError('Unrelated task field changed: ' + key)
    for key in ('reviews', 'repair_round', 'max_repairs', 'render_accounting'):
        if q.get(key) != original['daily_quality'].get(key): raise AssertionError('QA history/accounting changed.')
    for key in ('reviews', 'best', 'legacy'):
        if ledger.get(key) != original['daily_quality']['progress_policy'].get(key):
            raise AssertionError('Raw ledger/best history changed.')
    if [r['identity'] for r in progress.actual_review_rows(ledger)] != [ACTUAL]:
        raise AssertionError('Effective actual comparison basis changed.')
    return {'operation': OPERATION, 'task_id': TASK, 'method_key': method['key'],
        'corrected_identity': BAD, 'actual_baseline_identity': ACTUAL,
        'official_review_sha256': receipt_sha, 'no_new_render': True, 'automatic_resume': False}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    out = ROOT/'data/rework-top-three-20261014'
    proof_path = out/'rank1-repair-slot-review-input.json'
    official_path = out/'rank1-official-slot-review.json'
    if sha(official_path) != RECEIPT_SHA: raise Conflict('Official review file changed.')
    official = json.loads(official_path.read_text('utf-8'))
    proof = json.loads(proof_path.read_text('utf-8'))
    if sha(proof_path) != official['slot_review_input_sha256']: raise Conflict('Review input changed.')
    with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
        before = json.loads(db.execute('SELECT state FROM tasks WHERE id=?', (TASK,)).fetchone()[0])
        row = db.execute('SELECT payload,checkpoint,status FROM jobs WHERE id=? AND task_id=?', (JOB,TASK)).fetchone()
    if not row: raise Conflict('Original repair job missing.')
    job = {'id': JOB, 'payload': json.loads(row[0]), 'checkpoint': json.loads(row[1]), 'status': row[2]}
    candidate = copy.deepcopy(before)
    detail = prepare(candidate, job, official, proof, RECEIPT_SHA)
    if args.apply and detail:
        destination = out/'rank1-observation-correction-applied.json'
        if destination.exists(): raise Conflict('Existing operation report must be preserved.')
        store = StudioStore(ROOT/'data/studio')
        def change(state, db):
            if state != before or db.execute("SELECT 1 FROM jobs WHERE status IN ('running','queued')").fetchone():
                raise Conflict('State changed or global queue is not idle.')
            if tuple(db.execute('SELECT payload,checkpoint,status FROM jobs WHERE id=?', (JOB,)).fetchone()) != row:
                raise Conflict('Original repair job changed.')
            # Revalidate actual bytes at the transaction boundary.
            if sha(official_path) != RECEIPT_SHA or sha(proof_path) != official['slot_review_input_sha256']:
                raise Conflict('Review bytes changed before commit.')
            fresh = copy.deepcopy(state)
            committed = prepare(fresh, job, official, proof, RECEIPT_SHA)
            state.clear(); state.update(fresh)
            store.event(db, TASK, 'no_render_observation_corrected_with_official_window', committed)
        after = store.change(TASK, change, before['revision'])
        result = {'apply': True, 'already_corrected': False, 'detail': detail,
            'revision_before': before['revision'], 'revision_after': after['revision']}
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        result = {'apply': args.apply, 'already_corrected': detail is None, 'detail': detail}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
