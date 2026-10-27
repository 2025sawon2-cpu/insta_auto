"""Setup settings are writable only from the installed machine's local UI."""
import ipaddress
import json
from urllib.parse import urlsplit

from .installation_settings import read, save, SetupConflict


class InstallationHTTP:
    def installation_can_save(self):
        host = urlsplit('http://'+self.headers.get('Host','')).hostname
        return (host in {'localhost','127.0.0.1','::1'}
                and ipaddress.ip_address(self.client_address[0]).is_loopback
                and not any(self.headers.get(k) for k in ('CF-Connecting-IP','X-Forwarded-For','Forwarded')))

    def installation_request(self, settings):
        if urlsplit(self.path).path != '/api/installation':
            return False
        writable = self.installation_can_save()
        if self.command in ('GET','HEAD'):
            self._json({**read(settings.data_dir),'can_save':writable})
            return True
        self.close_connection = True
        if self.command != 'PUT':
            self._json({'error':'지원하지 않는 설정 요청입니다.'},405)
            return True
        origin = urlsplit(self.headers.get('Origin',''))
        if not writable or origin.scheme not in ('http','https') or origin.netloc != self.headers.get('Host'):
            self._json({'error':'초기 설정 저장은 설치한 PC의 로컬 화면에서 진행해 주세요.'},403)
            return True
        try:
            size = int(self.headers.get('Content-Length','0'))
            if not 0 < size <= 8192:
                raise ValueError('설정 입력 크기를 확인하세요.')
            payload = json.loads(self.rfile.read(size))
            self._json({**save(settings.data_dir,payload),'can_save':True})
        except SetupConflict as error:
            self._json({'error':str(error)},409)
        except (ValueError,TypeError) as error:
            self._json({'error':str(error)},400)
        return True
