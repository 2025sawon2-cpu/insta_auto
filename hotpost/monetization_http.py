"""Same-origin post-production API; no raw credentials in GET responses."""
import json
from urllib.parse import urlsplit, parse_qs

from .monetization_store import MonetizationConflict


class MonetizationHTTP:
    def monetization_request(self, service, *, mutation=False):
        path = urlsplit(self.path).path
        if not path.startswith('/api/monetization'):
            return False
        try:
            parts = path.strip('/').split('/')
            if not mutation:
                if parts == ['api', 'monetization', 'connections']:
                    result = service.connections()
                elif parts == ['api', 'monetization', 'inputs']:
                    result = service.inputs(parse_qs(urlsplit(self.path).query).get('task', [''])[0])
                elif len(parts) == 4 and parts[3] == 'preview':
                    result = service.preview(parts[2])
                elif len(parts) == 3:
                    result = {'state': service.get(parts[2])}
                else:
                    self._json({'error': '경로를 찾을 수 없습니다.'}, 404); return True
            else:
                origin = self.headers.get('Origin')
                if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                    self._json({'error': '다른 사이트에서 수익화 요청을 보낼 수 없습니다.'}, 403); return True
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('JSON 요청이 필요합니다.')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16384:
                    raise ValueError('올바르지 않은 요청 크기')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('JSON 객체가 필요합니다.')
                if parts == ['api', 'monetization', 'connections']:
                    result = service.credentials.save(data)
                elif parts == ['api', 'monetization', 'automation']:
                    result = service.store.configure_automation(data.get('enabled'), data.get('account', ''), data.get('discovery_account'))
                elif len(parts) == 4:
                    task, action = parts[2:]
                    if action == 'prepare': result = service.prepare(task, data.get('account') or service.store.automation()['account'])
                    elif action == 'rebind-account': result = service.rebind_account(task, data.get('expected_revision'))
                    elif action == 'run': result = service.run_saved(task)
                    elif action == 'product': result = service.discover_product_saved(task)
                    elif action == 'affiliate': result = service.issue_link(task)
                    elif action == 'caption': result = service.prepare_caption(task, data.get('button_text', ''))
                    elif action == 'littly': result = service.register_littly(task)
                    elif action == 'publish': result = service.publish(task)
                    elif action == 'inspect-littly': result = service.inspect_littly(task, data.get('automation_url', ''))
                    elif action == 'inspect-post': result = service.inspect_post(task, data.get('post_url', ''))
                    elif action == 'inspect-delivery': result = service.inspect_delivery(task)
                    else:
                        self._json({'error': '알 수 없는 후속 작업입니다.'}, 404); return True
                else:
                    self._json({'error': '경로를 찾을 수 없습니다.'}, 404); return True
            self._json(result)
        except MonetizationConflict as exc:
            self._json({'error': str(exc)}, 409)
        except (ValueError, KeyError, TypeError) as exc:
            self._json({'error': str(exc)}, 400)
        except RuntimeError as exc:
            self._json({'error': str(exc)}, 503)
        return True
