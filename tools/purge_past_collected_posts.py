"""Explicit one-time purge; retain the named fresh posts and their dependencies.

Default is a local manifest only. --apply removes only inventoried, bounded paths.
No worker, collection, or external service is started by this tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
KST = timezone(timedelta(hours=9))
TODAY_CODES = {'DeNb4AsSgGw', 'DeOhQMSzm5N', 'DeNgZSYAaQc', 'DeOZa4ulJ0J'}
VOICE_DATA = ROOT.parent / 'VoiceBench' / 'data'
CAPCUT_ROOT = Path.home() / 'AppData/Local/CapCut/User Data/Projects/com.lveditor.draft'


def read(path):
    return json.loads(path.read_text('utf-8'))


def write(path, value):
    tmp = path.with_name(path.name + '.purge-tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    tmp.replace(path)


def values(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from values(v)
    elif isinstance(value, list):
        for v in value:
            yield from values(v)
    elif isinstance(value, str):
        yield value


def request_ids(value):
    result = set()
    if isinstance(value, dict):
        if type(value.get('request_id')) is int:
            result.add(value['request_id'])
        for v in value.values():
            result.update(request_ids(v))
    elif isinstance(value, list):
        for v in value:
            result.update(request_ids(v))
    return result


def connect(path):
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    return db


def bounded(path, allowed):
    """Check the final absolute target and every ancestor before deletion."""
    absolute = Path(os.path.abspath(path))
    resolved = absolute.resolve()
    roots = [r.resolve() for r in allowed]
    if not any(resolved != r and resolved.is_relative_to(r) for r in roots):
        raise ValueError(f'Out-of-scope deletion: {absolute}')
    current = absolute
    while current != current.parent:
        if current.is_symlink() or current.is_junction():
            raise ValueError(f'Link or junction in deletion path: {current}')
        if current in roots:
            break
        current = current.parent
    return resolved


def bytes_at(path):
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file())


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def placeholders(items):
    return ','.join('?' for _ in items)


def inventory(keep):
    with connect(DATA / 'hotpost.db') as db:
        started = db.execute('SELECT started_at FROM runs ORDER BY id DESC LIMIT 1').fetchone()[0]
        day_start = datetime(2026, 10, 9, tzinfo=KST).timestamp()
        fresh = {r[0] for r in db.execute('''SELECT p.shortcode FROM posts p
            JOIN hot_detections h USING(shortcode) WHERE p.taken_at>=? AND p.taken_at<=?
            AND h.detected_at>=? AND h.detected_at<?''', (started - 86400, started, day_start, day_start + 86400))}
        if fresh != TODAY_CODES or not keep or not keep <= fresh:
            raise ValueError('Fresh-post selection changed; re-inventory before applying')
        old_codes = {r[0] for r in db.execute('SELECT shortcode FROM posts')} - keep
    with connect(DATA / 'studio/studio.sqlite3') as db:
        tasks = [json.loads(r[0]) for r in db.execute('SELECT state FROM tasks')]
        kept_tasks = [t for t in tasks if t['shortcode'] in keep]
        old_tasks = [t for t in tasks if t['shortcode'] not in keep]
        old_task_ids = {t['id'] for t in old_tasks}
        kept_task_ids = {t['id'] for t in kept_tasks}
        jobs = [dict(r) for r in db.execute('SELECT * FROM jobs')]

    protected = set()
    for name in ('source_jobs', 'transcripts'):
        for p in (DATA / name).iterdir():
            if any(p.name == code or p.name.startswith(code + '-') for code in keep):
                protected.add(p.resolve())
    protected.update((DATA / 'studio' / task_id).resolve() for task_id in kept_task_ids)
    # These files belong to the explicit four fresh-post experiment.
    if keep == TODAY_CODES:
        protected.update({(DATA / 'public_comparisons').resolve(), (DATA / 'selected-four-research').resolve()})

    writing_ids = set()
    keep_voice_ids = set()
    old_voice_ids = set()
    native_old = set()
    for task in kept_tasks:
        keep_voice_ids.update(request_ids(task))
    for task in old_tasks:
        old_voice_ids.update(request_ids(task))
        for edit in task.get('edits', []):
            p = edit.get('draft_path')
            if p:
                path = bounded(Path(p), [CAPCUT_ROOT])
                if path.parent != CAPCUT_ROOT.resolve() or not re.fullmatch(r'Studio-job-[a-f0-9]{16}', path.name):
                    raise ValueError('Unrecognized native project')
                if path.exists():
                    native_old.add(path)
    seeds = list(kept_tasks)
    for job in jobs:
        content = [json.loads(job['payload']), json.loads(job['checkpoint'])]
        if job['task_id'] in kept_task_ids:
            seeds.extend(content)
            keep_voice_ids.update(request_ids(content))
        else:
            old_voice_ids.update(request_ids(content))

    # Follow saved JSON dependencies, including internal writing receipts.
    scanned = set()
    def ingest(value):
        for text in values(value):
            writing_ids.update(re.findall(r'codex[0-9a-f]{32}', text))
            if len(text) > 3 and text[1:3] in {':\\', ':/'}:
                p = Path(text)
                if not p.exists():
                    continue
                p = p.resolve()
                for name in ('source_jobs', 'transcripts', 'studio', 'writing', 'selected-four-research'):
                    base = (DATA / name).resolve()
                    if p.is_relative_to(base) and p != base:
                        child = base / p.relative_to(base).parts[0]
                        owned = (name == 'writing' or name == 'selected-four-research'
                                 or (name == 'studio' and child.name in kept_task_ids)
                                 or (name in {'source_jobs','transcripts'} and any(child.name.startswith(c+'-') for c in keep)))
                        if child.is_dir() and owned:
                            protected.add(child)
                        elif p.is_file():
                            # A reused frame/clip does not protect the old post's
                            # entire original, script, voice, and export folder.
                            protected.add(p)
                        break
    for seed in seeds:
        ingest(seed)
    while True:
        before = (len(protected), len(writing_ids))
        for jid in writing_ids.copy():
            folder = DATA / 'writing' / jid
            if folder.is_dir():
                protected.add(folder.resolve())
        for path in protected.copy():
            for p in (path.rglob('*.json') if path.is_dir() else []):
                if p in scanned:
                    continue
                scanned.add(p)
                if p.stat().st_size > 10_000_000:
                    continue
                try:
                    ingest(read(p))
                except (ValueError, UnicodeError):
                    pass
        if before == (len(protected), len(writing_ids)):
            break
    for path in protected:
        base = (DATA / 'writing').resolve()
        if path.is_relative_to(base):
            writing_ids.add(path.relative_to(base).parts[0])
    old_voice_ids -= keep_voice_ids
    deletion = set()
    roots = [DATA, ROOT / 'web/thumbs', VOICE_DATA / 'artifacts', CAPCUT_ROOT]
    protected_dirs = {p for p in protected if p.is_dir()}
    protected_ancestors = {parent for p in protected for parent in p.parents}
    def prune(p):
        pr=p.resolve()
        if pr in protected or any(k in pr.parents for k in protected_dirs):
            return
        if pr in protected_ancestors:
            if p.is_dir():
                for child in p.iterdir():
                    prune(child)
            return
        deletion.add(pr)
    for name in ('source_jobs', 'transcripts', 'studio', 'writing', 'editing_jobs', 'productions'):
        base = DATA / name
        for p in base.iterdir():
            if p.name.endswith(('.sqlite3', '.sqlite3-wal', '.sqlite3-shm', '.lock')) or p.name == '.gitkeep':
                continue
            prune(p)
    for p in (ROOT / 'web/thumbs').iterdir():
        if p.name != '.gitkeep' and p.stem not in keep:
            deletion.add(p.resolve())
    for name in ('collection-window-test', 'remotion-qa'):
        p = DATA / name
        if p.exists():
            deletion.add(p.resolve())
    for name in ('daily_collect.log', 'operational.log', 'studio-worker.log'):
        deletion.update(p.resolve() for p in DATA.glob(name + '*'))
    if keep != TODAY_CODES:
        deletion.add((DATA / 'public_comparisons').resolve())
        # Some vendor clips used by a retained reel live in this shared folder.
        for p in (DATA / 'selected-four-research').iterdir():
            prune(p)
        deletion.update(p.resolve() for p in DATA.glob('selected-four-share*'))

    voice_jobs, voice_prompts = set(), set()
    with connect(VOICE_DATA / 'voicebench.sqlite3') as db:
        for rid in old_voice_ids:
            for r in db.execute('SELECT job_id,prompt_id FROM studio_segments WHERE request_id=?', (rid,)):
                voice_jobs.add(r['job_id']); voice_prompts.add(r['prompt_id'])
            for p in (VOICE_DATA / 'artifacts/studio').glob(f'request-{rid}*'):
                if re.match(rf'request-{rid}(?:\D|$)', p.name):
                    deletion.add(p.resolve())
        # Include failed quality-control attempts for the same old prompt.
        for pid in voice_prompts:
            if db.execute('SELECT 1 FROM studio_segments WHERE prompt_id=? AND request_id NOT IN (' + placeholders(old_voice_ids) + ')', (pid, *old_voice_ids)).fetchone():
                raise ValueError('An old voice prompt is shared with a retained request')
            voice_jobs.update(r[0] for r in db.execute('SELECT id FROM jobs WHERE prompt_id=?', (pid,)))
        for jid in voice_jobs:
            if db.execute('SELECT 1 FROM studio_segments WHERE job_id=? AND request_id NOT IN (' + placeholders(old_voice_ids) + ')', (jid, *old_voice_ids)).fetchone():
                raise ValueError('A voice job is shared with a retained request')
            if db.execute('SELECT 1 FROM comparisons WHERE left_run_id IN (SELECT id FROM runs WHERE job_id=?) OR right_run_id IN (SELECT id FROM runs WHERE job_id=?)', (jid,jid)).fetchone():
                raise ValueError('A voice comparison references an old request')
            for r in db.execute('SELECT output_path FROM runs WHERE job_id=?', (jid,)):
                if r[0] and Path(r[0]).exists():
                    deletion.add(bounded(Path(r[0]), [VOICE_DATA / 'artifacts/outputs']))
    deletion.update(native_old)
    deletion = {p for p in deletion if p.exists()}
    # Validate all targets before removing anything, including subtree links.
    for p in deletion:
        bounded(p, roots)
        if p.is_dir():
            for child in p.rglob('*'):
                if child.is_symlink() or child.is_junction():
                    raise ValueError(f'Linked subtree: {child}')
    critical = {}
    for t in kept_tasks:
        names = [t.get('reference_video')]
        names.extend(t.get('reference_images', []))
        names.extend(e.get('export_path') for e in t.get('edits', []))
        for name in names:
            if name and Path(name).is_file():
                critical[str(Path(name).resolve())] = sha(Path(name))
    return dict(keep=sorted(keep), old_codes=sorted(old_codes), old_tasks=sorted(old_task_ids),
                writing_ids=sorted(writing_ids), old_voice_ids=sorted(old_voice_ids),
                voice_jobs=sorted(voice_jobs), voice_prompts=sorted(voice_prompts),
                native_old=sorted(map(str, native_old)), critical=critical,
                deletion=[{'path':str(p), 'bytes':bytes_at(p)} for p in sorted(deletion)],
                collection_started_at=started)


def apply(plan):
    keep = plan['keep']
    # Settings retain the user's global stop request; no services are started.
    from hotpost.config import load_settings
    settings = load_settings()
    if settings.production_enabled or settings.studio_auto_top_enabled:
        raise ValueError('Production must remain stopped during the purge')
    import psutil
    if any(p.info['name'].lower()=='capcut.exe' for p in psutil.process_iter(['name'])):
        raise ValueError('Close CapCut before pruning its generated project registry')
    with connect(DATA / 'studio/studio.sqlite3') as db:
        if db.execute("SELECT 1 FROM jobs WHERE status IN ('running','queued')").fetchone():
            raise ValueError('Active jobs must be stopped first')
    removed_bytes = removed_files = 0
    for index,item in enumerate(plan['deletion'],1):
        p = bounded(Path(item['path']), [DATA, ROOT / 'web/thumbs', VOICE_DATA / 'artifacts', CAPCUT_ROOT])
        if not p.exists():
            continue
        removed_files += sum(1 for x in p.rglob('*') if x.is_file()) if p.is_dir() else 1
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        removed_bytes += item['bytes']
        if index % 500 == 0:
            print(json.dumps({'removed_targets':index,'freed_bytes':removed_bytes}),flush=True)
    print('File removal complete; pruning stored records',flush=True)
    with connect(DATA / 'hotpost.db') as db:
        deleted_rows = {}
        for table in ('snapshots', 'metric_observations', 'hot_view_tracking', 'hot_detections', 'jobs', 'posts'):
            deleted_rows[table] = db.execute('DELETE FROM ' + table + ' WHERE shortcode NOT IN (' + placeholders(keep) + ')', keep).rowcount
        # Notification bodies may contain removed-post captions and IDs.
        for r in db.execute('SELECT id,key FROM notifications').fetchall():
            if not any(code in r['key'] for code in keep):
                db.execute('DELETE FROM notifications WHERE id=?', (r['id'],))
        db.commit()
        db.execute('VACUUM')
    with connect(DATA / 'studio/studio.sqlite3') as db:
        ids = plan['old_tasks']
        if ids:
            for table, col in (('events','task_id'), ('jobs','task_id'), ('tasks','id')):
                db.execute('DELETE FROM ' + table + ' WHERE ' + col + ' IN (' + placeholders(ids) + ')', ids)
        for r in db.execute('SELECT run_key,selection FROM automatic_runs').fetchall():
            rows = [v for v in json.loads(r['selection']) if v.get('shortcode') in keep]
            if rows:
                db.execute('UPDATE automatic_runs SET selection=? WHERE run_key=?', (json.dumps(rows,ensure_ascii=False),r['run_key']))
            else:
                db.execute('DELETE FROM automatic_runs WHERE run_key=?', (r['run_key'],))
        db.commit(); db.execute('PRAGMA wal_checkpoint(TRUNCATE)'); db.execute('VACUUM')
    with connect(DATA / 'writing/jobs.sqlite3') as db:
        ids = plan['writing_ids']
        db.execute('DELETE FROM jobs WHERE id NOT IN (' + placeholders(ids) + ')', ids)
        db.commit(); db.execute('VACUUM')
    with connect(VOICE_DATA / 'voicebench.sqlite3') as db:
        for rid in plan['old_voice_ids']:
            db.execute('DELETE FROM studio_segments WHERE request_id=?', (rid,))
            db.execute('DELETE FROM studio_requests WHERE id=?', (rid,))
        for jid in plan['voice_jobs']:
            if db.execute('SELECT 1 FROM comparisons WHERE left_run_id IN (SELECT id FROM runs WHERE job_id=?) OR right_run_id IN (SELECT id FROM runs WHERE job_id=?)', (jid,jid)).fetchone():
                raise ValueError('Voice comparison unexpectedly references a removed request')
            db.execute('DELETE FROM runs WHERE job_id=?', (jid,))
            db.execute('DELETE FROM jobs WHERE id=?', (jid,))
        for pid in plan['voice_prompts']:
            if not db.execute('SELECT 1 FROM studio_segments WHERE prompt_id=?', (pid,)).fetchone():
                db.execute('DELETE FROM prompts WHERE id=?', (pid,))
        db.commit(); db.execute('VACUUM')
    if plan['native_old']:
        p = CAPCUT_ROOT / 'root_meta_info.json'
        meta = read(p); names = {Path(x).name for x in plan['native_old']}
        removed = [d for d in meta['all_draft_store'] if d.get('draft_name') in names]
        removed_ids = {d['draft_id'] for d in removed}
        meta['all_draft_store'] = [d for d in meta['all_draft_store'] if d not in removed]
        if isinstance(meta.get('draft_ids'), list):
            meta['draft_ids'] = [i for i in meta['draft_ids'] if i not in removed_ids]
        write(p, meta)
    # Keep original detection/score evidence; do not rescore with the erased baseline.
    report = read(DATA / 'report.json')
    report['posts'] = [p for p in report['posts'] if p['shortcode'] in keep]
    posts = report['posts']; hot = [p for p in posts if p.get('tier',0)>=1]
    owners = {p['username'] for p in posts}
    report['accounts'] = [a for a in report['accounts'] if a['username'] in owners]
    from hotpost.report import _median, write_report
    for a in report['accounts']:
        pp = [p for p in posts if p['username']==a['username']]
        hh = [p for p in pp if p.get('tier',0)>=1]
        a.update(posts_analyzed=len(pp), posts_recent=len(pp), hot_recent=len(hh),
                 hot_7d=sum(p.get('age_hours',999)<=168 for p in hh),
                 median_likes=_median([p.get('likes') for p in pp]),
                 median_comments=_median([p.get('comments') for p in pp]),
                 median_views=_median([p.get('views') for p in pp if p['kind'] in {'reel','video'}]),
                 reel_share=round(sum(p['kind'] in {'reel','video'} for p in pp)/len(pp),2),
                 best_recent=max(pp,key=lambda p:p.get('multiplier',0))['shortcode'],
                 last_post_at=max(p['taken_at'] for p in pp))
    report['topics'] = []
    report['acquisition_candidates'] = [p for p in report.get('acquisition_candidates',[]) if p['shortcode'] in keep]
    report['notes'] = []
    report['collection_started_at'] = plan['collection_started_at']
    report['summary'].update(accounts=len(owners), posts=len(posts), hot=len(hot),
        confirmed_hot=sum(p['assessment']['status']=='confirmed' for p in hot),
        provisional_hot=sum(p['assessment']['status']=='provisional' for p in hot),
        hot_24h=sum(p.get('age_hours',999)<=24 for p in hot),
        hot_7d=sum(p.get('age_hours',999)<=168 for p in hot),
        reels=sum(p['kind'] in {'reel','video'} for p in posts),
        hot_today=sum(bool(p.get('hot_today')) for p in posts),
        benchmark_consumed=sum(bool(p.get('benchmark_consumed')) for p in posts))
    report['local_purge'] = {'at':time.time(),'retained_shortcodes':keep,'prior_scores_preserved':True}
    write_report(settings, report)
    for name, digest in plan['critical'].items():
        if not Path(name).is_file() or sha(Path(name)) != digest:
            raise ValueError('A retained final/reference changed: ' + name)
    for path in (DATA/'hotpost.db', DATA/'studio/studio.sqlite3', DATA/'writing/jobs.sqlite3', VOICE_DATA/'voicebench.sqlite3'):
        with connect(path) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Database integrity failure')
    return dict(deleted_posts=deleted_rows['posts'],deleted_studio_tasks=len(plan['old_tasks']),
                deleted_files=removed_files,freed_bytes=removed_bytes,retained=keep,
                verified_critical_files=len(plan['critical']))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--keep',nargs='+',required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    plan=inventory(set(args.keep))
    path=DATA/'purge-past-20261009-manifest.json'
    write(path, plan)
    print(json.dumps({'keep':plan['keep'],'delete_posts':len(plan['old_codes']),
        'delete_tasks':len(plan['old_tasks']),'delete_targets':len(plan['deletion']),
        'delete_bytes':sum(p['bytes'] for p in plan['deletion']),
        'keep_writing_jobs':len(plan['writing_ids']),'delete_voice_requests':len(plan['old_voice_ids']),
        'delete_native_drafts':len(plan['native_old'])},ensure_ascii=False),flush=True)
    if args.apply:
        receipt=apply(plan)
        original=DATA/'purge-past-20261009-original-manifest.json'
        if original.exists():
            first=read(original)
            receipt['freed_bytes']=sum(p['bytes'] for p in first['deletion'] if not Path(p['path']).exists())
        write(DATA/'purge-past-20261009-receipt.json',receipt)
        print(json.dumps(receipt,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
