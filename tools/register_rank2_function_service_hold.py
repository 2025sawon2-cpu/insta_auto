"""Bind a known terminal 429 to the shared gate once; no model/task execution."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from hotpost.editing_adapter import _atomic_json
from hotpost.writing.codex_writer import classify_service_failure
from hotpost.model_service import capacity_failure
from hotpost.writing.jobs import Jobs

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/rework-top-three-20261014/rank2-bounded-cooking-v1'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    dest=OUT/'function-service-recovery-registration.json'
    if dest.exists():raise RuntimeError('Prior gate registration exists; do not register the same failure twice')
    hold_path=OUT/'function-service-hold.json';hold=json.loads(hold_path.read_text('utf-8'))
    binding=json.loads((OUT/'input-binding.json').read_text('utf-8'))
    assert hold['function_original_submission']['binding']==binding
    assert json.loads((OUT/'function-submission.json').read_text('utf-8'))==hold['function_original_submission']
    assert not (OUT/'function.json').exists() and not (OUT/'portrait-submission.json').exists()
    for path,digest in hold['raw_files'].items():assert sha(path)==digest
    with sqlite3.connect((ROOT/'data/writing/jobs.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        assert not db.execute("select 1 from jobs where state in ('queued','running')").fetchone()
        row=db.execute('select state,payload,result from jobs where id=?',(hold['writing_job_id'],)).fetchone()
        assert row[0]=='failed' and hashlib.sha256(row[1].encode()).hexdigest()==hold['payload_sha256']
        assert json.loads(row[2])==hold['original_job_result']
    assert not Jobs(ROOT/'data/writing').active_children(hold['writing_job_id'])
    event_path=next(Path(p) for p in hold['raw_files'] if p.endswith('events.jsonl'))
    events=[json.loads(line) for line in event_path.read_text('utf-8').splitlines() if line.strip()]
    assert any(e.get('type')=='turn.failed' for e in events) and not any(e.get('type')=='turn.completed' for e in events)
    classification=classify_service_failure(events)
    assert classification and classification['http_status']==429
    paths=[ROOT/'hotpost'/p for p in ['writing/codex_writer.py','model_service.py',
        'source_functional.py','visual_media.py','studio_adapter.py']]
    receipt={'state':'registering','binding':binding,'hold_sha256':sha(hold_path),
        'classification':classification,'code_sha256':{str(p):sha(p) for p in paths},
        'started_at':time.time(),'model_calls':0,'task_mutations':0,'preserved_original_failed_job':True,
        'maximum_recovery_probes':1}
    _atomic_json(dest,receipt)
    retry_at=capacity_failure(event_path.parent.parent,retry_at=classification.get('provider_retry_at'))
    receipt.update(state='registered',retry_at=retry_at,registered_at=time.time())
    _atomic_json(dest,receipt)
    print(json.dumps({'state':'registered','retry_at':retry_at,'seconds_until_probe':max(0,retry_at-time.time()),
        'maximum_probes':1,'model_calls':0}),flush=True)

if __name__=='__main__':main()
