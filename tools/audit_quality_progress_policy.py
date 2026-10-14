"""Read-only appraisal of the handoff targets; never resumes a production."""
import copy
import json
import sqlite3
from pathlib import Path

from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json
from hotpost.quality_progress import ensure, hypothesis, POLICY
from hotpost.scene_requirements import coverage_current

TARGETS=('work-a4602b23ac814fd9','work-aef77132b7f944cc')


def main():
    settings=load_settings()
    path=settings.data_dir/'studio/studio.sqlite3'
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        queue=dict(db.execute("SELECT status,count(*) FROM jobs WHERE status IN ('queued','running') GROUP BY status"))
        rows=[json.loads(db.execute('SELECT state FROM tasks WHERE id=?',(tid,)).fetchone()[0]) for tid in TARGETS]
    receipts=[]
    for original in rows:
        state=copy.deepcopy(original);quality=state.get('daily_quality',{})
        ledger=ensure(state);method=hypothesis(state,'reedit')
        receipts.append({'task_id':state['id'],'status':original['status'],
            'quality_status':quality.get('status'),'historical_pending':quality.get('pending'),
            'repair_usage':quality.get('repair_round',0),'edits':len(state['edits']),
            'automation_active':state.get('automation',{}).get('active'),
            'outstanding':[d['observation'] for d in ledger['defects'].values() if d.get('status')!='resolved'],
            'new_grounded_method':method['grounded'],'current_coverage':coverage_current(state),
            'resume_eligible':bool(method['grounded'] and coverage_current(state)
                and not any(a['key']==method['key'] for a in ledger['attempts'])),
            'best_reviewed_edit_id':(ledger.get('best') or {}).get('edit_id'),
            'runtime_state_written':False,'external_requests':0,'render_calls':0})
    root=settings.data_dir/'quality-progress-policy-20261013';root.mkdir(exist_ok=True)
    _atomic_json(root/'handoff-target-assessment.json',{'policy':POLICY,'queued_running':queue,'targets':receipts})
    print(json.dumps({'policy':POLICY,'queued_running':queue,'assessment_path':str(root/'handoff-target-assessment.json'),
                      'targets':[{'task_id':r['task_id'],'resume_eligible':r['resume_eligible']} for r in receipts]}))


if __name__=='__main__':main()
