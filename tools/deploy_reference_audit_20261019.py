"""Reload this checkout's idle Hotpost service and record imported source hashes."""
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import requests

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/reference-process-audit-20261019/deployment'
MODULES=['hotpost.reference_scene_roles','hotpost.source_visual_queries','hotpost.source_queries',
         'hotpost.source_query_identity','hotpost.source_search.triage',
         'hotpost.source_overlay_review','hotpost.source_overlay_repair',
         'hotpost.studio_sources','hotpost.studio_automation','hotpost.source_preparation','hotpost.source_finder',
         'hotpost.source_search.planner','hotpost.source_batches','hotpost.source_functional',
         'hotpost.source_policy','hotpost.studio_runtime.generation','hotpost.studio_runtime.editing']

def ps(code):
    return json.loads(subprocess.check_output(['pwsh','-NoProfile','-Command',code],text=True,encoding='utf8') or 'null')

def main():
    import argparse
    global OUT
    parser=argparse.ArgumentParser()
    parser.add_argument('--followup',action='store_true')
    parser.add_argument('--continuity',action='store_true')
    parser.add_argument('--inventory-caller',action='store_true')
    parser.add_argument('--mechanism',action='store_true')
    parser.add_argument('--final-verification',action='store_true')
    args=parser.parse_args()
    previous='core-source-priority-20261019\\deployment\\boot.py'
    if args.followup:
        previous='reference-process-audit-20261019\\deployment\\boot.py'
        OUT=OUT.with_name('deployment-final')
    if args.continuity:
        previous='reference-process-audit-20261019\\deployment-final\\boot.py'
        OUT=OUT.with_name('deployment-continuity')
    if args.inventory_caller:
        previous='reference-process-audit-20261019\\deployment-continuity\\boot.py'
        OUT=OUT.with_name('deployment-inventory-caller')
    if args.mechanism:
        previous='reference-process-audit-20261019\\deployment-inventory-caller\\boot.py'
        OUT=OUT.with_name('deployment-mechanism')
    if args.final_verification:
        previous='reference-process-audit-20261019\\deployment-mechanism\\boot.py'
        OUT=OUT.with_name('deployment-verified')
    sys.path.insert(0,str(ROOT))
    from hotpost.config import load_settings
    from hotpost.voicebench_adapter import VoiceBenchAdapter
    settings=load_settings()
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'receipt.json').exists():raise RuntimeError('Deployment receipt already exists')
    identity=ps("Get-NetTCPConnection -State Listen -LocalPort 8775 | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Get-CimInstance Win32_Process -Filter ('ProcessId='+$_) } | Select-Object ProcessId,CommandLine,CreationDate | ConvertTo-Json -Compress")
    assert isinstance(identity,dict) and str(ROOT) in identity['CommandLine']
    assert previous in identity['CommandLine']
    old_pid=identity['ProcessId']
    children=ps(f"@(Get-CimInstance Win32_Process | Where-Object ParentProcessId -eq {old_pid} | Select-Object ProcessId,Name) | ConvertTo-Json -Compress")
    assert not children, 'Active server children; leave running'
    health=VoiceBenchAdapter(settings).default_voice_status()
    assert health['active_requests']==0 and not any(health['queue'].values())
    expected={name:hashlib.sha256((ROOT/(name.replace('.','/')+'.py')).read_bytes()).hexdigest() for name in MODULES}
    (OUT/'expected.json').write_text(json.dumps(expected,indent=2),'utf8')
    boot="""import hashlib,importlib,json,os,runpy,sys,time
from pathlib import Path
OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
sys.path.insert(0,str(ROOT))
loaded={}
for name,stamp in json.loads((OUT/'expected.json').read_text('utf8')).items():
    module=importlib.import_module(name);path=Path(module.__file__)
    actual=hashlib.sha256(path.read_bytes()).hexdigest();assert actual==stamp,name
    loaded[name]={'path':str(path),'sha256':actual}
(OUT/'loaded.json').write_text(json.dumps({'pid':os.getpid(),'at':time.time(),'modules':loaded},indent=2),'utf8')
sys.argv=['hotpost','serve','--no-browser','--host','127.0.0.1','--port','8775']
runpy.run_module('hotpost',run_name='__main__')
"""
    (OUT/'boot.py').write_text(boot,'utf8')
    # Keep the writer and Studio queues locked while proving idleness and stopping
    # the verified owner. No state, queued job or historical run is rewritten.
    connections=[]
    try:
        for path in (settings.data_dir/'studio/studio.sqlite3',settings.data_dir/'writing/jobs.sqlite3'):
            db=sqlite3.connect(path,timeout=5);connections.append(db);db.execute('BEGIN IMMEDIATE')
            columns={r[1] for r in db.execute('pragma table_info(jobs)')}
            column='status' if 'status' in columns else 'state'
            assert not db.execute(f"select 1 from jobs where {column} in ('queued','running') limit 1").fetchone(),str(path)
        check=ps(f"Get-CimInstance Win32_Process -Filter 'ProcessId={old_pid}' | Select-Object ProcessId,CommandLine,CreationDate | ConvertTo-Json -Compress")
        assert check==identity
        (OUT/'before.json').write_text(json.dumps({'server':identity,'voice_health':health,'at':time.time()},ensure_ascii=False,indent=2),'utf8')
        os.kill(old_pid,signal.SIGTERM)
    finally:
        for db in connections:db.rollback();db.close()
    for _ in range(40):
        try:requests.get('http://127.0.0.1:8775/api/criteria',timeout=.5)
        except requests.RequestException:break
        time.sleep(.25)
    with (OUT/'stdout.log').open('ab') as stdout,(OUT/'stderr.log').open('ab') as stderr:
        process=subprocess.Popen([sys.executable,'-u','-X','utf8',str(OUT/'boot.py')],cwd=ROOT,
            stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
    for _ in range(80):
        if process.poll() is not None:raise RuntimeError('New server exited; inspect deployment logs')
        try:
            response=requests.get('http://127.0.0.1:8775/api/criteria',timeout=1)
            if response.status_code==200:break
        except requests.RequestException:pass
        time.sleep(.5)
    else:raise RuntimeError('New service readiness unconfirmed')
    loaded=json.loads((OUT/'loaded.json').read_text('utf8'))
    receipt={'old_pid':old_pid,'new_pid':loaded['pid'],'launcher_pid':process.pid,'at':time.time(),
             'loaded':loaded,'health':requests.get('http://127.0.0.1:8775/api/production-health',timeout=40).json(),
             'voice_restarted':False,'reason':'VoiceBench code unchanged; idle and healthy'}
    (OUT/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:v for k,v in receipt.items() if k!='loaded'},ensure_ascii=False))

if __name__=='__main__':main()
