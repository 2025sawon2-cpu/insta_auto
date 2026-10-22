"""Read-only production baseline and compact status for the reference audit."""
import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'data/reference-process-audit-20261019'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--selected', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    from hotpost.config import load_settings
    settings = load_settings()
    result = {'observed_at': time.time()}
    result['settings'] = {k: str(v) if isinstance(v, Path) else v for k, v in vars(settings).items()
                          if k.startswith(('source_', 'studio_', 'auto_capcut_', 'voicebench_'))
                          and not any(s in k for s in ('key', 'token', 'cookie', 'password', 'secret'))}
    with sqlite3.connect(f'file:{settings.data_dir / "studio/studio.sqlite3"}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        states = [json.loads(r[0]) for r in db.execute('select state from tasks')]
        result['jobs'] = [dict(r) for r in db.execute("select id,task_id,kind,status,error,updated,checkpoint from jobs where status in ('queued','running')")]
        result['tasks'] = [{k: s.get(k) for k in ('id','shortcode','title','status','run_id','edit_id','message','error')}
                           | {'edits':len(s.get('edits',[])), 'runs':len(s.get('runs',[])),
                              'completed_runs': sum(r.get('status')=='completed' for r in s.get('runs',[])),
                              'automation_active':s.get('automation',{}).get('active'),
                              'daily_quality_status':s.get('daily_quality',{}).get('status')}
                           for s in states]
    with sqlite3.connect(f'file:{settings.db_path}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        posts = [dict(r) for r in db.execute("select * from posts where kind in ('reel','video') order by first_seen desc")]
        used = {s['shortcode'] for s in states if s.get('edits') or any(r.get('status')=='completed' for r in s.get('runs',[]))}
        existing = {s['shortcode']: s['id'] for s in states}
        result['unproduced'] = [{k:p.get(k) for k in ('shortcode','kind','caption','first_seen','taken_at','video_url')}
                                 | {'task_id':existing.get(p['shortcode'])}
                                 for p in posts if p['shortcode'] not in used]
    if args.baseline:
        paths = {}
        for repo in (ROOT, ROOT.parent / 'auto_capcut'):
            paths[repo.name] = {'git_status':subprocess.check_output(['git','status','--short'],cwd=repo,text=True,encoding='utf-8'), 'files':{}}
            for suffix in ('*.py','*.md','*.js','*.jsx'):
                for file in repo.rglob(suffix):
                    relative = file.relative_to(repo)
                    if any(p in {'.git','.venv','data','node_modules','.runtime','works','.pytest_cache'} for p in relative.parts):
                        continue
                    paths[repo.name]['files'][str(relative)] = hashlib.sha256(file.read_bytes()).hexdigest()
        result['baseline']=paths
    name='baseline.json' if args.baseline else 'status.json'
    path = OUT/name
    if args.baseline and path.exists():
        raise RuntimeError('Baseline already exists; preserve it')
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    production=OUT/'production.json'
    selected=json.loads(production.read_text('utf8')).get('task_id') if production.exists() else None
    if args.selected:
        state=next((s for s in states if s['id']==selected),{})
        (OUT/'selected-state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),'utf8')
        print(json.dumps({k:state.get(k) for k in ('product','reference_video','transcript_path','source_search',
              'source_goal','source_search_manifest_path','script_id','voice_id','edit_id')},ensure_ascii=False))
        for row in result['jobs']:
            if row['task_id']==selected:
                cp=json.loads(row['checkpoint'])
                print(json.dumps({'job':row['id'],'kind':row['kind'],'checkpoint':cp},ensure_ascii=False)[:5500])
    print(json.dumps({'receipt':str(path),'active_jobs':[
        {k:r[k] for k in ('id','task_id','kind','status','updated','error')} for r in result['jobs']],
        'selected_task':[s for s in result['tasks'] if s['id']==selected],
        'task_count':len(states),'unproduced_count':len(result['unproduced'])},ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
