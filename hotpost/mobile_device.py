"""Explicit Android control through an existing WireGuard route, never a web API."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import xml.etree.ElementTree as ET


class MobileError(ValueError):
    pass


def run(args, *, input=None, timeout=30):
    result = subprocess.run([str(a) for a in args], input=input, capture_output=True,
                            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise MobileError('장치 명령이 실패했습니다: '+result.stderr.decode('utf8', 'replace')[-600:])
    return result.stdout


@dataclass
class DeviceConfig:
    phone_ip: str = ''
    adb_port: int = 0
    vpn_network: str = '10.9.0.0/24'
    android_serial: str = ''

    def validate(self):
        if not self.phone_ip or not self.adb_port:
            raise MobileError('휴대폰의 WireGuard IP와 ADB 연결 포트가 필요합니다.')
        try:
            ip = ipaddress.ip_address(self.phone_ip)
            network = ipaddress.ip_network(self.vpn_network)
        except ValueError as exc:
            raise MobileError('IP와 WireGuard 대역을 확인하세요.') from exc
        if (ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified
                or not network.is_private or ip not in network or type(self.adb_port) is not int
                or not 1 <= self.adb_port <= 65535):
            raise MobileError('WireGuard 사설 대역 안의 휴대폰 IP와 올바른 포트가 필요합니다.')
        return self

    @property
    def endpoint(self):
        self.validate()
        return f'{self.phone_ip}:{self.adb_port}'

    @classmethod
    def load(cls, path):
        path = Path(path)
        return cls(**json.loads(path.read_text('utf8'))) if path.exists() else cls()

    def save(self, path):
        self.validate()
        atomic_json(Path(path), asdict(self))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf8')
    os.replace(temporary, path)


@contextmanager
def phone_lock(folder):
    """Kernel lock, released after process death; only one phone action at a time."""
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/'phone.lock').open('a+b') as stream:
        stream.seek(0); stream.write(b'0'); stream.flush(); stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise MobileError('다른 휴대폰 작업이 진행 중입니다.') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def wireguard_route(ip):
    if os.name != 'nt':
        raise MobileError('이 PC용 경로 검증은 Windows WireGuard 인터페이스를 사용합니다.')
    # ip has already been parsed as IPv4, not interpolated user shell syntax.
    ip = str(ipaddress.IPv4Address(ip))
    script = ('[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); '
              f'$r=Find-NetRoute -RemoteIPAddress {ip} -ErrorAction Stop; '
              '$a=Get-NetAdapter -InterfaceIndex ($r | Select-Object -Last 1).InterfaceIndex -ErrorAction Stop; '
              '$a | Select-Object Name,InterfaceDescription,Status | ConvertTo-Json -Compress')
    value = json.loads(run(['powershell.exe', '-NoProfile', '-Command', script]).decode('utf8', 'replace').lstrip('\ufeff'))
    if 'wireguard' not in value.get('InterfaceDescription', '').lower() or value.get('Status') != 'Up':
        raise MobileError('휴대폰 IP로 가는 활성 WireGuard 경로가 확인되지 않습니다.')
    return value


class AdbDevice:
    def __init__(self, config, executable=None):
        self.config = config.validate()
        if executable is None:
            from adbutils import adb_path
            executable = adb_path()
        self.executable = executable

    def command(self, *args, device=True, **kwargs):
        prefix = [self.executable] + (['-s', self.config.endpoint] if device else [])
        return run(prefix+list(args), **kwargs)

    def preflight(self):
        route = wireguard_route(self.config.phone_ip)
        try:
            with socket.create_connection((self.config.phone_ip, self.config.adb_port), timeout=4):
                pass
        except OSError as exc:
            raise MobileError('WireGuard 경로는 있지만 휴대폰 ADB 포트에 닿지 않습니다. 무선 디버깅과 연결 포트를 확인하세요.') from exc
        return route

    def pair(self, port, code):
        self.preflight_pair(port)
        if not re.fullmatch(r'\d{6}', code):
            raise MobileError('휴대폰에 표시된 일회용 6자리 페어링 코드가 필요합니다.')
        # Code goes to stdin, never command line, config, or receipt.
        try:
            answer = self.command('pair', f'{self.config.phone_ip}:{int(port)}', device=False,
                                  input=(code+'\n').encode(), timeout=30)
        except (MobileError, subprocess.TimeoutExpired) as exc:
            raise MobileError('ADB 페어링이 완료되지 않았습니다. 폰의 현재 코드/페어링 포트를 확인하세요.') from exc
        if b'Successfully paired' not in answer:
            raise MobileError('ADB 페어링 성공 응답이 없습니다.')
        return {'paired': True}

    def preflight_pair(self, port):
        if type(port) is not int or not 1 <= port <= 65535:
            raise MobileError('올바른 페어링 포트를 입력하세요.')
        wireguard_route(self.config.phone_ip)
        try:
            with socket.create_connection((self.config.phone_ip, port), timeout=4):
                pass
        except OSError as exc:
            raise MobileError('휴대폰 페어링 포트에 닿지 않습니다.') from exc

    def connect(self):
        route = self.preflight()
        result = self.command('connect', self.config.endpoint, device=False).decode('utf8', 'replace')
        if 'connected to' not in result:
            raise MobileError('ADB 연결이 승인되지 않았습니다. 휴대폰 페어링/인증을 확인하세요.')
        if self.command('get-state').strip() != b'device':
            raise MobileError('휴대폰이 offline/unauthorized 상태입니다.')
        serial = self.command('shell', 'getprop', 'ro.serialno').decode().strip()
        if not serial or (self.config.android_serial and serial != self.config.android_serial):
            raise MobileError('등록된 휴대폰과 실제 장치가 다릅니다.')
        return {'connected': True, 'endpoint': self.config.endpoint, 'android_serial': serial,
                'android_version': self.command('shell', 'getprop', 'ro.build.version.release').decode().strip(),
                'route': route}

    def push(self, local, remote, digest):
        if not re.fullmatch(r'/sdcard/Movies/Hotpost/[a-f0-9]{32}/(?:final\.mp4|cover\.png)', remote):
            raise MobileError('허용된 휴대폰 영상 폴더가 아닙니다.')
        self.command('shell', 'mkdir', '-p', remote.rsplit('/', 1)[0])
        self.command('push', str(local), remote, timeout=240)
        actual = self.command('shell', 'toybox', 'sha256sum', remote).decode().split()[0]
        if actual != digest:
            raise MobileError('휴대폰에 전송된 파일 SHA가 다릅니다.')
        self.command('shell', 'am', 'broadcast', '-a', 'android.intent.action.MEDIA_SCANNER_SCAN_FILE', '-d', 'file://'+remote)

    def video_uri(self, remote):
        # Remote is generated internally and checked by push(), never a user path.
        if not re.fullmatch(r'/sdcard/Movies/Hotpost/[a-f0-9]{32}/final\.mp4', remote):
            raise MobileError('올바른 전송 영상 경로가 아닙니다.')
        result = self.command('shell', 'content', 'query', '--uri', 'content://media/external/video/media',
                              '--projection', '_id', '--where', '"_data=\''+remote+'\'"').decode('utf8', 'replace')
        ids = re.findall(r'_id=(\d+)\b', result)
        if len(ids) != 1:
            raise MobileError('갤러리의 전송 영상 등록을 확인하지 못했습니다. 잠시 후 transfer를 다시 확인하세요.')
        return 'content://media/external/video/media/'+ids[0]

    def open_video(self, uri, package):
        if not re.fullmatch(r'content://media/external/video/media/\d+', uri) or package not in ('com.instagram.android','com.instagram.basel'):
            raise MobileError('허용된 영상 공유 대상이 아닙니다.')
        answer = self.command('shell', 'am', 'start', '-a', 'android.intent.action.SEND', '-t', 'video/mp4',
                              '--eu', 'android.intent.extra.STREAM', uri, '--grant-read-uri-permission', '-p', package)
        if b'Error:' in answer or b'Exception' in answer:
            raise MobileError('이 앱 버전이 영상 공유 인텐트를 열지 못했습니다. inspect로 실제 화면 경로를 확인하세요.')


def parse_screen(xml):
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise MobileError('현재 Android 화면 구조를 읽지 못했습니다.') from exc
    nodes = []
    for element in root.iter('node'):
        a = element.attrib
        bounds = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', a.get('bounds',''))
        if not bounds or a.get('enabled','true') != 'true' or a.get('visible-to-user','true') == 'false':
            continue
        x,y,r,b = map(int,bounds.groups())
        if r <= x or b <= y:
            continue
        nodes.append({'index':len(nodes),'text':a.get('text',''),'description':a.get('content-desc',''),
                      'resource_id':a.get('resource-id',''),'class':a.get('class',''),
                      'package':a.get('package',''),'bounds':[x,y,r,b]})
    return nodes


class AndroidUI:
    def __init__(self, endpoint):
        import uiautomator2 as u2
        self.device = u2.connect(endpoint)

    def screen(self):
        xml = self.device.dump_hierarchy()
        package = self.device.app_current()['package']
        nodes = parse_screen(xml)
        # A status-bar clock tick is not a changed composer; app content/bounds are.
        relevant = [n for n in nodes if n['package']!='com.android.systemui']
        fingerprint = json.dumps({'package':package,'nodes':relevant},ensure_ascii=False,sort_keys=True)
        return {'xml':xml,'sha256':hashlib.sha256(fingerprint.encode()).hexdigest(),
                'package':package,'nodes':nodes}

    def capture(self, folder, label):
        folder.mkdir(parents=True, exist_ok=True)
        screen = self.screen()
        self.device.screenshot(str(folder/(label+'.png')))
        (folder/(label+'.xml')).write_text(screen['xml'],'utf8')
        atomic_json(folder/(label+'.json'), {k:v for k,v in screen.items() if k!='xml'})
        return screen

    def tap(self, node):
        x,y,r,b = node['bounds']
        self.device.click((x+r)//2,(y+b)//2)

    def set_text(self, node, text):
        selector = {'className':node['class']}
        if node['resource_id']:
            selector['resourceId'] = node['resource_id']
        else:
            selector['text'] = node['text']
        control = self.device(**selector)
        if control.count != 1:
            raise MobileError('한글 본문을 입력할 작성칸 하나를 확인하지 못했습니다.')
        control.set_text(text, timeout=5)  # Unicode JSON-RPC; never adb input text.
        if control.get_text() != text:
            raise MobileError('입력된 한글/이모지 본문이 원문과 다릅니다.')

    def open_app(self, package):
        if package not in ('com.instagram.android','com.instagram.basel'):
            raise MobileError('Instagram/Edits만 제어합니다.')
        self.device.app_start(package)
