"""Deploy current code only after live Studio jobs and server children finish."""
import argparse,json,os,re,signal,subprocess,sys,time
from pathlib import Path
import requests
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.editing_adapter import _atomic_json

ROOT=Path('data/source-recovery-20261012-v1').resolve();RECEIPT=ROOT/'runtime-drain-v5.json'

def ps(script):
    r=subprocess.run(['pwsh','-NoProfile','-Command',script],check=True,capture_output=True,text=True,encoding='utf-8')
    return json.loads(r.stdout or 'null')

def listener():
    return ps("$recoveryListeners = @(Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq 8775 | Select-Object -ExpandProperty OwningProcess -Unique); if ($recoveryListeners.Count -eq 0) { 'null' } elseif ($recoveryListeners.Count -eq 1) { $recoveryListeners[0] | ConvertTo-Json -Compress } else { $recoveryListeners | ConvertTo-Json -Compress }")

def descendant_ids(parent):
    rows=ps('Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name | ConvertTo-Json -Compress')
    found={parent};changed=True
    while changed:
        changed=False
        for row in rows:
            if row['ParentProcessId'] in found and row['ProcessId'] not in found:
                found.add(row['ProcessId']);changed=True
    return sorted(found-{parent})

def main():
    global RECEIPT
    parser=argparse.ArgumentParser();parser.add_argument('--version',default='v5');args=parser.parse_args()
    assert re.fullmatch(r'v[0-9]+',args.version)
    version=args.version;RECEIPT=ROOT/('runtime-drain-'+version+'.json')
    if RECEIPT.exists():
        prior=json.loads(RECEIPT.read_text('utf-8'))
        assert prior.get('restored_at'),'Existing maintenance must be recovered before starting another'
    studio=Studio(load_settings(),workers=False);pid=listener();assert isinstance(pid,int)
    identity=ps(f"Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress")
    assert identity and '-m hotpost serve --no-browser' in identity['CommandLine']
    token='recovery-'+version+'-'+str(time.time_ns());receipt={'started_at':time.time(),'version':version,'old_server_pid':pid,'token':token,'jobs':{},'active':{}}
    with studio.store.transaction() as db:
        for row in db.execute("select id,checkpoint from jobs where status='queued'").fetchall():
            cp=json.loads(row['checkpoint'])
            if cp.get('batch_reservation'):continue
            receipt['jobs'][row['id']]=cp
            held={**cp,'not_before':time.time()+86400,'batch_reservation':token,'batch_original_not_before':cp.get('not_before',0)}
            db.execute('update jobs set checkpoint=? where id=?',(json.dumps(held),row['id']))
        for row in db.execute('select state from tasks').fetchall():
            state=json.loads(row['state']);auto=state.get('automation',{})
            receipt['active'][state['id']]=auto.get('active',False)
            auto.update(active=False,maintenance_token=token);studio.store.save(db,state)
        _atomic_json(RECEIPT,receipt)
    print('Holding queued work; waiting for actual live jobs and server child processes',flush=True)
    try:
        previous=None
        while True:
            with studio.store.connect() as db:
                live=[dict(r) for r in db.execute("select id,task_id,kind,status from jobs where status='running'")]
            children=descendant_ids(pid)
            receipt.update(last_checked_at=time.time(),live_jobs=live,server_child_pids=children)
            _atomic_json(RECEIPT,receipt)
            signature=([(r['id'],r['kind']) for r in live],children)
            if signature!=previous:print('Drain:',len(live),'live jobs;',len(children),'server children',flush=True);previous=signature
            if not live and not children:break
            time.sleep(5)
        assert listener()==pid,'Listener changed during drain; do not terminate a different process'
        os.kill(pid,signal.SIGTERM)
        for _ in range(30):
            if listener() is None:break
            time.sleep(.5)
        assert listener() is None,'Old listener still exists'
        # Do not spawn through a capture-pipe PowerShell: detached children can
        # inherit the capture handle and keep communicate() waiting indefinitely.
        out=Path('data/studio-recovery-server-'+version+'.log').resolve()
        err=Path('data/studio-recovery-server-'+version+'.err.log').resolve()
        with out.open('a',encoding='utf-8') as stdout,err.open('a',encoding='utf-8') as stderr:
            process=subprocess.Popen([sys.executable,'-X','utf8','-u','-m','hotpost','serve','--no-browser','--host','127.0.0.1'],
                cwd=Path.cwd(),stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,close_fds=True,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))
        launcher=process.pid
        for _ in range(60):
            identity=ps(f"Get-CimInstance Win32_Process -Filter 'ProcessId={launcher}' | Select-Object ProcessId | ConvertTo-Json -Compress")
            if identity is None:raise RuntimeError('New server stopped during startup')
            try:
                r=requests.get('http://127.0.0.1:8775/',timeout=3)
                if r.status_code==200:break
            except requests.RequestException:pass
            time.sleep(1)
        else:raise RuntimeError('New server did not confirm readiness; queued work will still be restored')
        receipt.update(new_server_pid=listener(),new_launcher_pid=launcher,restarted_at=time.time())
        print('Fresh runtime listening:',receipt['new_server_pid'],flush=True)
    finally:
        with studio.store.transaction() as db:
            for job_id,original in receipt['jobs'].items():
                row=db.execute('select checkpoint,status from jobs where id=?',(job_id,)).fetchone()
                if row and row['status']=='queued' and json.loads(row['checkpoint']).get('batch_reservation')==token:
                    db.execute('update jobs set checkpoint=? where id=?',(json.dumps(original),job_id))
            for task_id,active in receipt['active'].items():
                state=studio.store.get(task_id,db);auto=state.get('automation',{})
                if auto.get('maintenance_token')!=token:continue
                auto.pop('maintenance_token',None)
                failed=state.get('daily_quality',{}).get('pending') in ('failed','exhausted')
                auto['active']=active and not failed
                if auto['active'] and auto.get('selection_date_kst')=='2026-10-12':
                    live=db.execute("select 1 from jobs where task_id=? and status in ('queued','running')",(task_id,)).fetchone()
                    if not live:
                        from hotpost.studio_sources import source_goal
                        if state.get('daily_quality',{}).get('pending')=='reediting' and source_goal(state,studio.settings.source_min_usable)['ready']:
                            state['daily_quality']['pending']='reedit'
                        studio.advance_workflow(state,db)
                studio.store.save(db,state)
        receipt['restored_at']=time.time();_atomic_json(RECEIPT,receipt)
        print('Queued work and active flags restored; 07:00 schedule was unchanged',flush=True)

if __name__=='__main__':main()
