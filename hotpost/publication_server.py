"""Publication drafts and reference accounts, independent of retired Studio."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlparse

from .account_registry_http import AccountRegistryHTTP
from .accounts import AccountRegistry
from .config import load_settings
from .post_preparation import PostPreparation
from .post_preparation_http import PostPreparationHTTP


def make_publication_handler(settings, snapshot=None, review_dir=None):
    accounts = AccountRegistry(settings)
    service = PostPreparation(settings)
    snapshot = dict(snapshot or {})

    class Handler(AccountRegistryHTTP, PostPreparationHTTP, SimpleHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def _body(self, body, kind='application/json; charset=utf-8', status=200):
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        def _json(self, value, status=200):
            self._body(json.dumps(value, ensure_ascii=False).encode('utf8'), status=status)

        def do_GET(self):
            if self.account_registry_request(accounts):
                return
            if self.post_preparation_request(service, head=self.command == 'HEAD'):
                return
            path = urlparse(self.path).path
            if path == '/api/health':
                self._json({'mode': 'publication', 'production_workers': 0, 'collection_workers': 0,
                            'reference_accounts': True})
            elif path in ('/data.js', '/api/report'):
                report = json.loads(settings.report_path.read_text('utf8'))
                if report.get('ranking_mode') == 'views_per_follower_72h':
                    from .reference_registry import load
                    from .daily_ranking import public_production
                    registry = load(settings.data_dir / 'reference-status.json')
                    for post in report['posts']:
                        production = registry['posts'].get(post['shortcode'], {}).get('production', {})
                        post['production'] = public_production(post['shortcode'], production)
                if path == '/api/report':
                    self._json(report)
                else:
                    self._body(('window.HOTPOST_REPORT = '+json.dumps(report, ensure_ascii=False)+';').encode('utf8'),
                               'application/javascript; charset=utf-8')
            elif review_dir and path in ('/ui-review/post-thumbnail-update.jpg', '/ui-review/yellow-mask-12.5.jpg',
                                         '/ui-review/post-preparation-content.jpg', '/ui-review/post-preparation.jpg'):
                self._body((Path(review_dir)/Path(path).name).read_bytes(), 'image/jpeg')
            elif self.path in snapshot:
                self._json(snapshot[self.path])
            elif path.startswith('/api/'):
                self._json({'error': '게시물 준비와 레퍼런스 계정 관리만 연결되어 있습니다.'}, 404)
            elif self.command == 'HEAD':
                super().do_HEAD()
            else:
                super().do_GET()

        def do_HEAD(self):
            self.do_GET()

        def do_POST(self):
            if self.account_registry_request(accounts):
                return
            if urlparse(self.path).path.endswith('/coupang-link'):
                if self.post_preparation_request(service, coupang=True):
                    return
            if self.post_preparation_request(service, thumbnail=True):
                return
            self._blocked()

        def do_PUT(self):
            if self.account_registry_request(accounts):
                return
            if self.post_preparation_request(service, write=True):
                return
            self._blocked()

        def do_DELETE(self):
            if not self.account_registry_request(accounts):
                self._blocked()

        def _blocked(self):
            self.close_connection = True
            self._json({'error': '제작·수집은 중지되어 있습니다. 게시물 준비와 계정 관리만 가능합니다.'}, 405)

        do_PATCH = _blocked

    return partial(Handler, directory=str(settings.web_dir))


class PublicationServer(ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8776)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--review-dir', type=Path)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text('utf8')) if args.snapshot else {}
    handler = make_publication_handler(load_settings(), snapshot, args.review_dir)
    server = PublicationServer((args.host, args.port), handler)
    print(f'Publication dashboard on {args.port}; production/collection workers=0', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
