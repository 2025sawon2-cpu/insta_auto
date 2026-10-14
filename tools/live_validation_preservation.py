"""Record and compare the pre-existing studio state without starting workers."""
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/live-validation-20261014'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def states():
    with sqlite3.connect((ROOT / 'data/studio/studio.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        tasks = {r[0]: r[1] for r in db.execute('select id,state from tasks')}
        jobs = {r[0]: list(r) for r in db.execute('select * from jobs')}
    return tasks, jobs


def paths(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from paths(item)
    elif isinstance(value, list):
        for item in value:
            yield from paths(item)
    elif isinstance(value, str) and len(value) < 600:
        try:
            candidate = Path(value)
            if not candidate.is_absolute():
                candidate = ROOT / candidate
            if candidate.is_file() and candidate.suffix.lower() in {'.mp4', '.wav', '.mp3', '.json', '.txt', '.jpg', '.png'}:
                yield candidate.resolve()
        except (OSError, ValueError):
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['baseline', 'verify'])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_path = OUT / 'preservation-baseline.json'
    tasks, jobs = states()
    if args.mode == 'baseline':
        if baseline_path.exists():
            raise ValueError('Existing baseline is immutable; do not overwrite it.')
        active = [j for j in jobs.values() if 'running' in j or 'queued' in j]
        if active:
            raise ValueError('Pre-existing active jobs must be audited before starting.')
        files = set(p for raw in tasks.values() for p in paths(json.loads(raw)))
        result = {'at': datetime.now().astimezone().isoformat(), 'tasks': tasks, 'jobs': jobs,
                  'files': {str(p): {'size': p.stat().st_size, 'sha256': digest(p)} for p in sorted(files)}}
        for source in (ROOT / 'data/hotpost.db', ROOT / 'data/studio/studio.sqlite3'):
            with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as db:
                with sqlite3.connect(OUT / (source.name + '.before')) as backup:
                    db.backup(backup)
        baseline_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'tasks': len(tasks), 'jobs': len(jobs), 'hashed_files': len(files)}, ensure_ascii=False))
    else:
        before = json.loads(baseline_path.read_text(encoding='utf-8'))
        changed_tasks = [key for key, raw in before['tasks'].items() if tasks.get(key) != raw]
        changed_jobs = [key for key, row in before['jobs'].items() if jobs.get(key) != row]
        changed_files = [name for name, item in before['files'].items()
                         if not Path(name).is_file() or digest(Path(name)) != item['sha256']]
        result = {'at': datetime.now().astimezone().isoformat(), 'changed_old_tasks': changed_tasks,
                  'changed_old_jobs': changed_jobs, 'changed_old_files': changed_files,
                  'new_task_ids': [key for key in tasks if key not in before['tasks']],
                  'preserved': not (changed_tasks or changed_jobs or changed_files)}
        target = OUT / ('preservation-check-' + datetime.now().strftime('%H%M%S') + '.json')
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
