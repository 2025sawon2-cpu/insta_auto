"""Reference-account membership without collection or production workers."""
import json
from urllib.parse import unquote, urlparse


class AccountRegistryHTTP:
    def account_registry_request(self, registry):
        path = urlparse(self.path).path
        if path != '/api/accounts' and not path.startswith('/api/accounts/'):
            return False
        write = self.command not in ('GET', 'HEAD')
        if write:
            self.close_connection = True
            origin = self.headers.get('Origin')
            if origin and urlparse(origin).netloc != self.headers.get('Host'):
                self._json({'error': '다른 사이트에서의 계정 변경 요청은 허용하지 않습니다.'}, 403)
                return True
        try:
            if self.command in ('GET', 'HEAD') and path == '/api/accounts':
                items = registry.list()
                self._json({'accounts': items, 'count': len(items), 'source': 'git_file',
                            'file': registry.settings.influencer_file.name})
            elif self.command == 'POST' and path == '/api/accounts':
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    raise ValueError('잘못된 요청 크기')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('JSON 객체로 요청하세요.')
                account, note = body.get('account', ''), body.get('note', '')
                if not isinstance(account, str) or not isinstance(note, str):
                    raise ValueError('계정과 메모는 문자로 입력하세요.')
                item, created = registry.add(account, note)
                self._json({'account': item, 'created': created}, 201 if created else 200)
            elif self.command == 'DELETE' and path.startswith('/api/accounts/'):
                changed = registry.delete(unquote(path.removeprefix('/api/accounts/')))
                self._json({'deleted': changed}, 200 if changed else 404)
            else:
                self._json({'error': '지원하지 않는 계정 관리 요청입니다.'}, 405)
        except (ValueError, OSError) as error:
            self._json({'error': str(error)}, 400 if write else 409)
        return True
