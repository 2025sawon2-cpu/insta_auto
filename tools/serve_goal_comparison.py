"""Publish the verified new production without starting any production worker."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hotpost.config import load_settings
from hotpost.comparison_share import build_comparison, server_for


def main():
    settings = load_settings()
    database = settings.data_dir / 'studio/studio.sqlite3'
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        rows = db.execute('SELECT state FROM tasks WHERE id=?',
                          ('work-2d881e5afb2043ce',)).fetchall()
    states = [json.loads(row[0]) for row in rows]
    studio = SimpleNamespace(settings=settings, store=SimpleNamespace(list=lambda: states))
    root, assets = build_comparison(studio, ('Dec5bcqyffk',), snapshot_suffix='goal-20261016')
    server = server_for(assets, port=0)
    out = settings.data_dir / 'goal-continuation-20261016'
    out.mkdir(exist_ok=True)
    log = (out / 'cloudflared.log').open('a', encoding='utf-8')
    base = 'http://127.0.0.1:' + str(server.server_address[1])
    tunnel = subprocess.Popen([str(settings.data_dir / 'tools/cloudflared.exe'),
        'tunnel', '--url', base, '--no-autoupdate'], stdout=log, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    (out / 'comparison-server.json').write_text(json.dumps(dict(
        local_url=base, server_pid=os.getpid(), tunnel_pid=tunnel.pid,
        snapshot=str(root), public_files=[p.name for p in assets.values()]), indent=2), 'utf-8')
    server.serve_forever()


if __name__ == '__main__':
    main()
