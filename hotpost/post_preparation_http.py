"""Publication drafts and explicitly requested thumbnails; no production queue."""
import json
import mimetypes
import re
from urllib.parse import parse_qs, urlparse
from .post_preparation import DraftConflict


class PostPreparationHTTP:
    def post_preparation_request(self, service, *, write=False, head=False, thumbnail=False, coupang=False):
        parsed = urlparse(self.path)
        if not parsed.path.startswith('/api/post-preparations/'):
            return False
        # Invalid writes can be rejected before their body is read.
        # Close this connection so leftover bytes cannot become another request.
        if write or thumbnail or coupang:
            self.close_connection = True
        if thumbnail or coupang:
            action = 'coupang-link' if coupang else 'thumbnail'
            match = re.fullmatch(r'/api/post-preparations/([A-Za-z0-9_-]{1,100})/' + action, parsed.path)
            if not match:
                self._json({'error': '썸네일 반영 경로를 확인하세요.'}, 404)
                return True
        else:
            match = re.fullmatch(r'/api/post-preparations/([A-Za-z0-9_-]{1,100})(?:/media/(reference|final|cover))?', parsed.path)
        if not match:
            self._json({'error': '게시물을 찾을 수 없습니다.'}, 404)
            return True
        code, kind = (match.group(1), None) if thumbnail or coupang else match.groups()
        try:
            if write or thumbnail or coupang:
                if kind:
                    self._json({'error': '초안만 저장할 수 있습니다.'}, 405)
                    return True
                origin = self.headers.get('Origin')
                if origin and urlparse(origin).netloc != self.headers.get('Host'):
                    self._json({'error': '다른 사이트에서의 저장 요청은 허용하지 않습니다.'}, 403)
                    return True
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 64000:
                    raise ValueError('입력 크기를 확인하세요.')
                payload = json.loads(self.rfile.read(length))
                result = (service.start_coupang_link(code, payload) if coupang else
                          service.start_thumbnail(code, payload) if thumbnail else service.save(code, payload))
                self._json(result, 202 if thumbnail or coupang else 200)
            elif kind:
                self._post_preparation_media(service.media(code, kind, parse_qs(parsed.query).get('v', [None])[0]), code, kind,
                                             parse_qs(parsed.query).get('download') == ['1'], head)
            else:
                self._json(service.get(code))
        except DraftConflict as exc:
            self._json({'error': str(exc)}, 409)
        except FileNotFoundError as exc:
            self._json({'error': str(exc)}, 404)
        except (ValueError, TypeError, KeyError) as exc:
            self._json({'error': str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        return True

    def _post_preparation_media(self, path, code, kind, download, head):
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        requested = self.headers.get('Range')
        if requested:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
            if not match or not any(match.groups()):
                return self._post_preparation_range_error(size)
            left, right = match.groups()
            if left:
                start = int(left)
                end = min(int(right), size - 1) if right else size - 1
            else:
                if int(right) == 0:
                    return self._post_preparation_range_error(size)
                start = max(0, size - int(right))
            if start >= size or start > end:
                return self._post_preparation_range_error(size)
            status = 206
        self.send_response(status)
        self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        if download:
            self.send_header('Content-Disposition', f'attachment; filename="{code}-{kind}{path.suffix}"')
        self.end_headers()
        if not head:
            with path.open('rb') as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = stream.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

    def _post_preparation_range_error(self, size):
        self.send_response(416)
        self.send_header('Content-Range', f'bytes */{size}')
        self.send_header('Content-Length', '0')
        self.end_headers()
