"""Local follow-up UI without launching/resuming any production worker."""
from contextlib import closing
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import sys
import os
import argparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hotpost.config import load_settings
from hotpost.monetization import Monetization
from hotpost.monetization_http import MonetizationHTTP


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        raise ValueError('올바르지 않은 포트')
    settings = load_settings()
    def get_task(task_id):
        with closing(sqlite3.connect((settings.data_dir / 'studio/studio.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)) as db:
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            raise ValueError('완성 작업을 찾을 수 없습니다.')
        return json.loads(row[0])
    service = Monetization(settings, get_task)

    class Handler(MonetizationHTTP, SimpleHTTPRequestHandler):
        def log_message(self, *args): pass
        def _json(self, value, status=200):
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            if not self.monetization_request(service):
                if self.path.startswith('/api/'):
                    self.send_error(404)
                else:
                    super().do_GET()
        def do_POST(self):
            if not self.monetization_request(service, mutation=True): self.send_error(404)

    server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(Handler, directory=str(settings.web_dir)))
    out = settings.data_dir / 'goal-continuation-20261016'
    out.mkdir(exist_ok=True)
    (out / 'monetization-server.json').write_text(json.dumps({
        'local_url': 'http://127.0.0.1:' + str(server.server_address[1]) + '/monetization.html',
        'pid': os.getpid(), 'production_workers': False}), 'utf-8')
    try:
        server.serve_forever()
    finally:
        server.server_close()
        service.close()


if __name__ == '__main__': main()
