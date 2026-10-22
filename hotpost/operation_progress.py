"""Detect silence since useful progress; never allocate a total execution budget."""
import os
from pathlib import Path
import subprocess
import time
import threading
import re
import json


class NoProgressTimeout(TimeoutError):
    pass


class ProgressWatch:
    def __init__(self, idle_seconds, stage='operation', clock=None, *, step='', completed=0, total=0):
        self.clock = clock or time.monotonic
        self.idle_seconds = max(1, float(idle_seconds))
        self.stage = stage
        self.step = step
        self.completed = int(completed or 0)
        self.total = int(total or 0)
        self.last_progress = self.clock()
        self.updated_at = time.time()
        self.high_water = {}

    def reset(self, stage=None, *, step=None, completed=None, total=None):
        if stage:
            self.stage = stage
        if step is not None:
            self.step = step
        if completed is not None:
            self.completed = int(completed)
        if total is not None:
            self.total = int(total)
        self.last_progress = self.clock()
        self.updated_at = time.time()

    def observe(self, key, value):
        """Only an increasing counter advances the watch, not duplicate data/heartbeats."""
        if value > self.high_water.get(key, 0):
            self.high_water[key] = value
            self.reset()
            return True
        return False

    def stage_summary(self):
        return {'stage': self.stage, 'step': self.step, 'completed': self.completed,
                'total': self.total, 'updated_at': self.updated_at}

    def check(self):
        if self.clock() - self.last_progress >= self.idle_seconds:
            raise NoProgressTimeout(f'{self.stage} · 응답 또는 유효 진전이 중단되었습니다.')


def run_progress_command(command, idle_seconds=120, progress_dir=None, *, cwd=None, env=None):
    """Observe growing output files and meaningful process output, not elapsed runtime."""
    watch = ProgressWatch(idle_seconds, '외부 파일 처리')
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    output={'stdout':[],'stderr':[]};milestones=set();counters={};lock=threading.Lock()
    def media_files():
        if progress_dir:
            for path in Path(progress_dir).rglob('*'):
                if path.is_file() and path.suffix.lower() in {'.part', '.mp4', '.webm', '.mkv', '.tmp'}:
                    yield path
    def file_key(path):
        # Publishing the same received bytes under a final filename is not
        # another transfer. Metadata (.ytdl) is not media progress either.
        return str(path.with_suffix('')) if path.suffix.lower() == '.part' else str(path)
    for path in media_files():
        try:watch.high_water[file_key(path)] = path.stat().st_size
        except FileNotFoundError:pass
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True,encoding='utf-8',errors='replace',cwd=cwd,env=env,**options)
    def consume(stream,key):
        for line in iter(stream.readline,''):
            with lock:
                output[key].append(line)
                milestone = re.search(r'Extracting URL|Downloading (?:webpage|JSON|[^\n]*player|m3u8)|Destination:|Merging formats',line)
                if milestone:
                    # Changing URLs/job IDs in repeated metadata logs does not
                    # manufacture an unbounded sequence of completed stages.
                    milestones.add('Downloading player' if 'player' in milestone[0] else milestone[0])
                # FFmpeg's machine-readable progress is useful even during
                # decoding to /dev/null, where no output file can grow.
                match = re.fullmatch(r'(frame|out_time_us|total_size)=\s*(\d+)\s*', line)
                if key == 'stdout' and match:
                    name, value = match[1], int(match[2])
                    counters[name] = max(counters.get(name, 0), value)
                if key == 'stdout' and line.lstrip().startswith('{'):
                    try:
                        event = json.loads(line)
                        percent = event.get('percent')
                        if event.get('event') == 'progress' and isinstance(percent,(int,float)) and not isinstance(percent,bool):
                            counters['runner_percent'] = max(counters.get('runner_percent',0), percent)
                    except (ValueError,AttributeError):pass
    readers=[threading.Thread(target=consume,args=(getattr(process,k),k),daemon=True) for k in output]
    for reader in readers:reader.start()
    try:
        while process.poll() is None:
            with lock:
                watch.observe('completed_handoffs',len(milestones))
                for key, value in counters.items():
                    watch.observe(('ffmpeg', key), value)
            for p in media_files():
                try:watch.observe(file_key(p), p.stat().st_size)
                except FileNotFoundError:pass
            watch.check()
            time.sleep(.25)
        for reader in readers:reader.join(timeout=1)
        return subprocess.CompletedProcess(command, process.returncode,
            ''.join(output['stdout']), ''.join(output['stderr']))
    finally:
        if process.poll() is None:
            from .writing.codex_writer import stop_owned
            stop_owned(process)
        for reader in readers:reader.join(timeout=1)
        for stream in (process.stdout,process.stderr):stream.close()


def watch_browser_transfer(context, page, watch, allowed_url, max_bytes=None, transfer_identity=None):
    """Observe in-flight bytes of the selected media, including a single long response."""
    if not hasattr(context, 'new_cdp_session'):
        return lambda: None
    session = context.new_cdp_session(page)
    transfers = {}
    def response(event):
        value = event.get('response', {})
        if value.get('status') in (200, 206) and value.get('mimeType', '').lower() in (
                'video/mp4', 'application/mp4', 'application/vnd.yt-ump'):
            headers = {k.lower(): str(v) for k,v in value.get('headers', {}).items()}
            transfers[event['requestId']] = [value.get('url', ''), headers.get('content-range', ''), 0]
    def data(event):
        item = transfers.get(event.get('requestId'))
        if item:
            item[2] += max(0, event.get('dataLength', 0))
            if allowed_url(item[0]):
                if max_bytes is not None and item[2]>max_bytes:
                    raise ValueError('수신 영상 크기 제한 초과')
                identity = transfer_identity(item[0]) if transfer_identity else item[0]
                if identity is not None:
                    watch.observe((identity, item[1]), item[2])
    session.on('Network.responseReceived', response)
    session.on('Network.dataReceived', data)
    session.send('Network.enable')
    def close():
        try:
            session.detach()
        except Exception:
            pass
    return close
