"""Serve immutable, verified outputs from the frozen 2026-10-14 top three."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from hotpost.comparison_share import LABELS, build_comparison, server_for
from hotpost.config import load_settings

CODES = ('DebVFJ8vOCY', 'Deb2jkPxQ43', 'DebLqa-T1kq')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8820)
    parser.add_argument('--completed-only', action='store_true')
    args = parser.parse_args()
    settings = load_settings()
    with sqlite3.connect((settings.data_dir/'studio/studio.sqlite3').resolve().as_uri()+'?mode=ro', uri=True) as db:
        states = [json.loads(row[0]) for row in db.execute('SELECT state FROM tasks')]
    codes = CODES
    if args.completed_only:
        completed = {s['shortcode'] for s in states if s.get('status') == 'completed'}
        codes = tuple(c for c in CODES if c in completed)
    if not codes:
        raise ValueError('No completed output in the frozen top three.')
    LABELS.update(dict(zip(CODES, ('밥도그', '사과 요리', '스팀청소기'))))
    # Read-only snapshot facade: no Studio workers, task writes or resumes.
    studio = SimpleNamespace(settings=settings, store=SimpleNamespace(list=lambda: states))
    root, assets = build_comparison(studio, codes=codes, snapshot_suffix='top-three-20261014')
    server = server_for(assets, port=args.port)
    receipt = {'pid': os.getpid(), 'url': f'http://127.0.0.1:{args.port}/',
               'codes': list(codes), 'root': str(root), 'files': list(assets),
               'read_only': True, 'complete_three': codes == CODES}
    target = settings.data_dir/'rework-top-three-20261014'/f'comparison-{args.port}.json'
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
