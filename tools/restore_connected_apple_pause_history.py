"""Explicitly bind reviewed legacy partials to the paused, frozen rank-two job."""
import argparse
import copy
import json
from pathlib import Path
import sqlite3

from hotpost.editing_adapter import _atomic_json
from hotpost.source_pause_receipts import binding, merge_receipt, sha, snapshot, verified_receipt
from hotpost.studio_store import Conflict, StudioStore

ROOT = Path(__file__).resolve().parents[1]
TASK = 'work-8013247e50624ae6'
JOB = 'job-7f6ee6075bf942c5'
REFERENCE = '45fdf3d99b2ce4658dac440f2c6c448aa8e3647b64a358e1b542b3809991261c'
INPUTS = (
    ('Deb2jkPxQ43-1791972634687176900', '19d0df09ce2498589e82d712f8573b27ef88e1b894e964c14d5944565869ae98', (
        ('browser_debug/search-checkpoint-be4cbf8f8d8144c09e5058a3872b3101.json', 'bef37b0d2c1a6edf91bf71d36e2f9de3035a2a05b866b011916645e5c7f9cdfc'),
        ('refinement_debug/search-checkpoint-487f8c21dc124b79a69b6e831db82f94.json', 'b99979a6a64cc4b8e5a5267a7eecf0b593f00a5672f4033ad22926b01022ab7e'),)),
    ('Deb2jkPxQ43-1791973108042226100', 'ef5b30f52ffcba7c9fae8581d4f05f9e8b9e1573fb65abaa13d5d15b13509924', (
        ('refinement_debug/search-checkpoint-dedc4e72e8a54a83bacb43ff01c048e1.json', '2a91458f4d535638c5ae11561b766f0bb35bd9f24f7f12d5fe1ef568a14be61a'),)),
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    source_dir = ROOT/'data/source_jobs'
    with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
        before = json.loads(db.execute('SELECT state FROM tasks WHERE id=?', (TASK,)).fetchone()[0])
        row = db.execute('SELECT payload,checkpoint,status FROM jobs WHERE id=? AND task_id=?', (JOB,TASK)).fetchone()
        if not row or row[2] != 'paused' or not before.get('automation', {}).get('paused_by_user'):
            raise Conflict('Only the paused frozen rank-two job can be repaired.')
    job = {'id':JOB,'task_id':TASK,'payload':json.loads(row[0]),'checkpoint':json.loads(row[1])}
    if sha(before['reference_video']) != REFERENCE or job['payload']['run_id'] != before['run_id']:
        raise Conflict('Frozen reference or run binding changed.')
    entries=[]
    for name, manifest_sha, children in INPUTS:
        manifest=source_dir/name/'manifest.json'
        if sha(manifest)!=manifest_sha or json.loads(manifest.read_text('utf-8'))['status']!='paused':
            raise Conflict('Reviewed immutable partial changed.')
        for relative,expected in children:
            if sha(manifest.parent/relative)!=expected:raise Conflict('Reviewed child trace changed.')
        descriptor={**binding(before,job),'manifest_path':str(manifest.resolve()),
                    'workers':[{'path':str((manifest.parent/relative).resolve()),'settled':True} for relative,_ in children]}
        receipt=snapshot(source_dir,descriptor,before,job)
        entries.append((descriptor,receipt))
    existing=job['checkpoint'].get('source_attempts',[])
    repaired={e.get('manifest_path') for e in existing if e.get('receipt_path')}
    already=all(d['manifest_path'] in repaired for d,_ in entries)
    detail={'task_id':TASK,'studio_job_id':JOB,'reference_sha256':REFERENCE,
            'legacy_binding':'Explicit reviewed reconstruction; not an original automatic ownership receipt.',
            'evidence':'watch-connected-rank2-duplicate-scope-stop-evidence.json',
            'independent_trace':'pause-resume-history-independent-trace.json',
            'entries':[d for d,_ in entries]}
    if args.apply and not already:
        store=StudioStore(ROOT/'data/studio')
        def change(state,db):
            if state!=before or db.execute("SELECT 1 FROM jobs WHERE status IN ('running','queued')").fetchone():
                raise Conflict('State changed or queue is not idle.')
            current=db.execute('SELECT checkpoint,status FROM jobs WHERE id=?',(JOB,)).fetchone()
            if current[0]!=row[1] or current[1]!='paused':raise Conflict('Target job changed.')
            for descriptor,receipt in entries:
                path=Path(descriptor['manifest_path']).parent/'interrupted-execution-receipt.json'
                if path.exists():
                    if json.loads(path.read_text('utf-8'))!=receipt:raise Conflict('Existing receipt differs; preserve it.')
                else:_atomic_json(path,receipt)
                descriptor.update(receipt_path=str(path.resolve()),receipt_sha256=sha(path))
                verified_receipt(source_dir,descriptor,state,job)
                merge_receipt(state['source_acquisition'],{**receipt,'receipt_path':str(path.resolve()),'receipt_sha256':sha(path)})
                job['checkpoint'].setdefault('source_attempts',[]).append(descriptor)
            db.execute('UPDATE jobs SET checkpoint=? WHERE id=?',(json.dumps(job['checkpoint']),JOB))
            state.setdefault('source_execution_corrections',[]).append(detail)
            store.event(db,TASK,'reviewed_interrupted_search_history_restored',detail)
        after=store.change(TASK,change,before['revision'])
        retained=copy.deepcopy(after)
        retained['source_acquisition']=copy.deepcopy(before['source_acquisition'])
        for k in ('source_execution_corrections','revision','updated'):retained.pop(k,None)
        expected=copy.deepcopy(before)
        for k in ('source_execution_corrections','revision','updated'):expected.pop(k,None)
        if retained!=expected:raise AssertionError('Unrelated production fields changed.')
        allowed={'queries','urls','inspected_urls','interrupted_attempts'}
        if {k:v for k,v in after['source_acquisition'].items() if k not in allowed}!={k:v for k,v in before['source_acquisition'].items() if k not in allowed}:
            raise AssertionError('Counters or round/quality history changed.')
    elif already:
        for entry in existing:verified_receipt(source_dir,entry,before,job)
    result={'apply':args.apply,'already_restored':already,'detail':detail,
            'search_rows':sum(len(r['searches']) for _,r in entries),'automatic_resume':False}
    if args.apply and not already:
        (ROOT/'data/rework-top-three-20261014/apple-pause-history-restoration.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='detail'},ensure_ascii=False))


if __name__=='__main__':main()
