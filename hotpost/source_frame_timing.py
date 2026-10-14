"""Read actual decoded frame exposure; never infer duration from output/average FPS."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

from .operation_progress import ProgressWatch
from .source_quality import sha256_file

POLICY='native-decoded-frame-exposure-v1'
_CACHE={}


def timing_from_probe(probe,source_sha256):
    stream=(probe.get('streams') or [{}])[0];container=probe.get('format') or {}
    def number(value):
        try:value=float(value)
        except (TypeError,ValueError):return None
        return value if math.isfinite(value) else None
    origin=number(stream.get('start_time') or container.get('start_time') or 0)
    duration=number(stream.get('duration') or container.get('duration'))
    rows=[]
    if origin is not None and duration is not None and duration>0:
        native=[]
        for frame in probe.get('frames',[]):
            timestamp=number(frame.get('best_effort_timestamp_time'))
            if timestamp is None:continue
            packet_duration=number(frame.get('duration_time'))
            if packet_duration is None:packet_duration=number(frame.get('pkt_duration_time'))
            native.append((timestamp-origin,packet_duration))
        native.sort(key=lambda row:row[0])
        for index,(start,packet_duration) in enumerate(native):
            # Duplicate timestamps and absent final duration are ambiguous.
            if any(abs(start-other[0])<1e-7 for other in native[max(0,index-1):index]+native[index+1:index+2]):continue
            if index+1<len(native):end=native[index+1][0];basis='next_decoded_pts'
            elif packet_duration is not None and packet_duration>0:end=start+packet_duration;basis='decoded_duration'
            else:continue
            if 0<=start<end<=duration+1e-5:
                rows.append({'start':start,'end':min(end,duration),'end_basis':basis})
    value={'policy':POLICY,'source_sha256':source_sha256,'source_duration':duration,'frames':rows}
    value['metadata_sha256']=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
    return value


def probe_native_timing(path,source_sha256,ffprobe=None,idle_seconds=120):
    path=Path(path)
    if not path.is_file() or sha256_file(path)!=source_sha256:raise ValueError('Native frame timing source identity changed')
    key=(str(path.resolve()),source_sha256)
    if key in _CACHE:return _CACHE[key]
    executable=ffprobe or shutil.which('ffprobe')
    if not executable:raise RuntimeError('ffprobe required for actual coded frame exposure')
    command=[str(executable),'-v','error','-select_streams','v:0','-show_frames',
        '-show_entries','stream=start_time,duration:format=duration,start_time:frame=best_effort_timestamp_time,pkt_duration_time,duration_time',
        '-of','json',str(path)]
    flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
        encoding='utf-8',errors='replace',**flags)
    output={'stdout':[],'stderr':[]};counter=[0];seen=set();lock=threading.Lock()
    watch=ProgressWatch(idle_seconds,'native source frame metadata')
    def consume(stream,kind):
        for line in iter(stream.readline,''):
            with lock:
                output[kind].append(line)
                match=re.search(r'"best_effort_timestamp_time"\s*:\s*"([-+\d.eE]+)"',line)
                if kind=='stdout' and match:
                    value=float(match[1])
                    if math.isfinite(value) and value not in seen:seen.add(value);counter[0]+=1
    readers=[threading.Thread(target=consume,args=(getattr(process,key),key),daemon=True) for key in output]
    for reader in readers:reader.start()
    try:
        while process.poll() is None or any(reader.is_alive() for reader in readers):
            with lock:watch.observe('distinct_native_frame_pts',counter[0])
            watch.check();time.sleep(.05)
        if process.returncode:raise RuntimeError('Native frame probe failed: '+''.join(output['stderr'])[-300:])
        proof=timing_from_probe(json.loads(''.join(output['stdout'])),source_sha256)
        if sha256_file(path)!=source_sha256:raise ValueError('Native frame timing source identity changed')
        _CACHE[key]=proof
        return proof
    finally:
        if process.poll() is None:
            from .writing.codex_writer import stop_owned
            stop_owned(process)
        for reader in readers:reader.join(timeout=1)
        for stream in (process.stdout,process.stderr):stream.close()


def frame_exposure(frame,source_sha256,timing):
    if not timing or timing.get('policy')!=POLICY or timing.get('source_sha256')!=source_sha256:return None
    proof={k:v for k,v in timing.items() if k!='metadata_sha256'}
    if hashlib.sha256(json.dumps(proof,sort_keys=True).encode()).hexdigest()!=timing.get('metadata_sha256'):return None
    timestamp=frame.get('source_timestamp')
    if type(timestamp) not in (int,float) or not math.isfinite(timestamp):return None
    matches=[row for row in timing.get('frames',[]) if abs(row['start']-timestamp)<=1e-5]
    if len(matches)!=1:return None
    row=matches[0]
    return {**row,'policy':POLICY,'source_sha256':source_sha256,'metadata_sha256':timing['metadata_sha256']}
