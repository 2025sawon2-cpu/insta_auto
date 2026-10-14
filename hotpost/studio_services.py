"""Start configured local services through their own entrypoints and environments."""
from __future__ import annotations

import os
import json
import subprocess
import time
from pathlib import Path
from contextlib import contextmanager, ExitStack
from urllib.parse import urlsplit

import requests
import psutil

from .editing_adapter import _atomic_json
from .model_service import ModelServiceUnavailable
from .production import file_lock


@contextmanager
def _startup_lease(path, kind):
    with ExitStack() as stack:
        try:
            stack.enter_context(file_lock(path))
        except ValueError as exc:
            raise ModelServiceUnavailable(f'{kind} 서비스 시작 소유권 대기',attempted=False) from exc
        yield


def _owned_startup(receipt_path, command, root):
    """A PID alone is not ownership: bind the exact launched service identity."""
    try:
        receipt=json.loads(receipt_path.read_text('utf-8'))
        if receipt.get('command')!=command or receipt.get('cwd')!=str(root.resolve()):
            return False
        if receipt.get('status')=='failed':
            return 'exited'
        try:
            process=psutil.Process(receipt['pid'])
        except psutil.NoSuchProcess:
            return 'exited' if receipt.get('status') in {'starting','starting_unknown'} else False
        if receipt.get('process_created') is None:
            if process.cmdline()!=command or Path(process.cwd()).resolve()!=root.resolve():
                return False
            return None if process.is_running() else 'exited'
        same=(process.create_time()==receipt['process_created'] and process.cmdline()==command
              and Path(process.cwd()).resolve()==root.resolve())
        if same and not process.is_running():
            return 'exited' if receipt.get('status')=='starting' else False
        return same and process.is_running()
    except (PermissionError, psutil.AccessDenied):
        return None  # Unknown live ownership must not cause another launch.
    except psutil.NoSuchProcess:
        return 'exited' if receipt.get('status') in {'starting','starting_unknown'} else False
    except (OSError, ValueError, KeyError, TypeError, psutil.Error):
        return False


def ensure_local(settings, kind):
    if kind == 'script':
        from .writing.codex_writer import executable
        executable()
        return
    url = settings.voicebench_url
    parsed = urlsplit(url)
    # Remote deployments remain managed by their owner.
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.path not in ('', '/'):
        return
    root = Path(settings.voicebench_root).expanduser().resolve()
    session = requests.Session()
    session.trust_env = False
    headers = {}
    environment = os.environ.copy()
    from .voicebench_adapter import VoiceBenchAdapter
    key = VoiceBenchAdapter(settings)._api_key()
    headers['Authorization'] = 'Bearer ' + key
    environment['VOICEBENCH_EXTERNAL_API_KEY'] = key
    path = '/v1/health'
    expected = 'VoiceBench External TTS API'
    port = str(parsed.port or 80)
    python = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    command=[str(python),'-X','utf8','-m','voicebench','--host','127.0.0.1','--port',port]
    runtime=root/'.runtime'
    receipt=runtime/f'hotpost-startup-{port}.json'

    def mark_ready():
        if receipt.is_file():
            with _startup_lease(runtime/f'hotpost-startup-{port}.lock',kind):
                saved=json.loads(receipt.read_text('utf-8'))
                # Authenticated health resolves an old failure only for this
                # configured launch contract; it is not evidence of old PID life.
                if saved.get('command')!=command or saved.get('cwd')!=str(root.resolve()):
                    return
                ownership=_owned_startup(receipt,command,root)
                if saved.get('status')=='failed' or ownership is True or ownership is None or ownership=='exited':
                    if saved.get('status')=='failed':
                        failure={k:saved[k] for k in ('pid','process_created','launched_at','reason','exit_code') if k in saved}
                        failure['resolved_at']=time.time()
                        saved.setdefault('startup_failure_history',[]).append(failure)
                    saved['status']='ready'
                    saved['ready_observed_at']=time.time()
                    _atomic_json(receipt,saved)

    def ready():
        try:
            response = session.get(url.rstrip('/') + path, headers=headers, timeout=3, allow_redirects=False)
        except requests.Timeout:
            # A cold service can accept the connection before its startup has
            # finished. Keep waiting without launching another process.
            return None
        except requests.ConnectionError:
            return False
        if response.status_code != 200:
            raise RuntimeError(f'{kind} 연결 주소의 서비스 또는 인증 설정을 확인하세요.')
        try:
            value=response.json()
        except ValueError as exc:
            raise RuntimeError(f'{kind} 연결 주소의 서비스 응답 설정을 확인하세요.') from exc
        if not isinstance(value,dict) or value.get('service')!=expected:
            raise RuntimeError(f'{kind} 연결 주소의 서비스 또는 인증 설정을 확인하세요.')
        return True

    initial = ready()
    if initial:
        mark_ready()
        return
    launched=None
    if initial is False:
        if not python.is_file():
            raise RuntimeError(f'{kind} 서비스 실행 환경이 없습니다. 해당 프로젝트의 설치 절차를 완료하세요.')
        # The configured service root is shared even when clients have different
        # Hotpost data directories. This metadata never stores the API key/env.
        runtime.mkdir(parents=True,exist_ok=True)
        with _startup_lease(runtime/f'hotpost-startup-{port}.lock',kind):
            ownership=_owned_startup(receipt,command,root)
            if ownership=='exited':
                raise RuntimeError(f'{kind} 서비스의 직전 시작이 종료되었습니다. 같은 설정으로 자동 재실행하지 않고 환경·로그 확인이 필요합니다.')
            if ownership is not False:
                raise ModelServiceUnavailable(f'{kind} 서비스의 기존 시작 프로세스 준비 대기', attempted=False)
            # Another initializer may have become ready since the first GET.
            current=ready()
            if current:
                return
            if current is False:
                failure_history=[]
                if receipt.is_file():
                    previous=json.loads(receipt.read_text('utf-8'))
                    if previous.get('command')==command and previous.get('cwd')==str(root.resolve()):
                        failure_history=previous.get('startup_failure_history',[])
                with (settings.data_dir / f'{kind}-service.log').open('a', encoding='utf-8') as log:
                    child=subprocess.Popen(command,cwd=root,env=environment,stdout=log,stderr=log,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                base_receipt={'service':'voicebench','pid':child.pid,'process_created':None,
                    'command':command,'cwd':str(root.resolve()),'launched_at':time.time(),
                    'startup_failure_history':failure_history}
                try:
                    created=psutil.Process(child.pid).create_time()
                except psutil.NoSuchProcess as exc:
                    _atomic_json(receipt,{**base_receipt,'status':'failed','reason':'exited_before_identity',
                        'exit_code':child.poll()})
                    raise RuntimeError(f'{kind} 서비스 시작 프로세스가 종료되었습니다. 실행 환경·서비스 로그를 확인하세요.') from exc
                except psutil.Error as exc:
                    _atomic_json(receipt,{**base_receipt,'status':'starting_unknown','reason':'process_identity_unconfirmed'})
                    raise ModelServiceUnavailable(f'{kind} 서비스 시작 프로세스의 소유권 확인 대기',attempted=False) from exc
                _atomic_json(receipt,{**base_receipt,'process_created':created,'status':'starting'})
                launched=child
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if ready():
            mark_ready()
            return
        if launched is not None and launched.poll() is not None:
            saved=json.loads(receipt.read_text('utf-8'))
            saved.update(status='failed',exit_code=launched.poll())
            _atomic_json(receipt,saved)
            raise RuntimeError(f'{kind} 서비스 시작 프로세스가 종료되었습니다. 같은 설정의 자동 시작을 보류합니다.')
        time.sleep(1)
    raise ModelServiceUnavailable(f'{kind} 서비스 첫 응답을 제한 시간 안에 확인하지 못했습니다. 시작 결과를 보존하고 준비를 기다립니다.',attempted=False)
