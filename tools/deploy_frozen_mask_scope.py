"""Replace only the verified idle app; preserve Chrome, voice and every row."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import psutil
import requests

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/rework-top-three-20261014/mask-scope-deployment-v2'
IDENTITIES={24632:1791979801.6769564,35072:1791979801.7121067,
    27700:1791935853.9890325,17392:1791937467.8343894}

def main():
    assert not OUT.exists(),'Preserve existing deployment; recover its exact state explicitly'
    OUT.mkdir()
    def rows():
        with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
            assert not db.execute("select 1 from jobs where status in ('queued','running')").fetchone()
            return {t:json.loads(s) for t,s in db.execute('select id,state from tasks')}
    def journal():
        with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
            return {table:list(db.execute('select * from '+table+' order by rowid'))
                for table in ('tasks','jobs','events')}
    states=rows()
    before=journal()
    for task in ['work-1672e441725d4445','work-8013247e50624ae6']:
        assert states[task]['automation']['paused_by_user'] and not states[task]['automation']['active']
    assert states['work-8b16890d03794af1']['revision']==1422
    for pid,creation in IDENTITIES.items():
        assert abs(psutil.Process(pid).create_time()-creation)<.01
    assert psutil.Process(35072).cmdline()[-6:]==['-m','hotpost','serve','--no-browser','--host','127.0.0.1']
    assert psutil.Process(35072).ppid()==24632
    assert Path(psutil.Process(35072).cwd()).resolve()==ROOT
    assert psutil.Process(24632).cmdline()[-6:]==['-m','hotpost','serve','--no-browser','--host','127.0.0.1']
    paths=[ROOT/'hotpost'/p for p in ['daily_quality.py','quality_progress.py','mask_application_evidence.py',
        'source_mask_review.py','source_overlay_review.py']]
    # Locate the external renderer from its configured process adapter.
    from hotpost.config import load_settings
    settings=load_settings()
    external=Path(settings.auto_capcut_root)
    paths.extend([external/'auto_capcut/core'/p for p in ['studio_masks.py','studio_render.py']])
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    receipt={'old_identities':IDENTITIES,'code_sha256':hashes,'started_at':time.time(),
        'task_mutations':0,'chrome_restarts':0,'voice_restarts':0}
    def save():(OUT/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
    save()
    receipt['owned_process_exit']={}
    for pid in [35072,24632]:
        try:process=psutil.Process(pid)
        except psutil.NoSuchProcess:
            assert pid==24632
            receipt['owned_process_exit'][str(pid)]='already_settled_after_owned_child_exit'
            continue
        assert abs(process.create_time()-IDENTITIES[pid])<.01
        process.terminate()
        process.wait(timeout=10)
        receipt['owned_process_exit'][str(pid)]='terminated_exact_identity'
    assert rows()==states
    assert journal()==before
    with (OUT/'server.log').open('wb') as stdout,(OUT/'server.err.log').open('wb') as stderr:
        process=subprocess.Popen([sys.executable,'-X','utf8','-u','-m','hotpost','serve',
            '--no-browser','--host','127.0.0.1'],cwd=ROOT,stdin=subprocess.DEVNULL,
            stdout=stdout,stderr=stderr,close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
    receipt.update(new_launcher_pid=process.pid)
    save()
    for _ in range(45):
        assert process.poll() is None,'New app stopped; preserve logs'
        try:
            if requests.get('http://127.0.0.1:8775/',timeout=1).status_code==200:break
        except requests.RequestException:pass
        time.sleep(.5)
    else:raise RuntimeError('New app readiness not confirmed')
    matches=[p for p in psutil.Process(process.pid).children(recursive=True)
        if p.cmdline()[-6:]==['-m','hotpost','serve','--no-browser','--host','127.0.0.1']]
    assert len(matches)==1
    receipt.update(new_server_pid=matches[0].pid,new_server_creation=matches[0].create_time(),
        new_launcher_creation=psutil.Process(process.pid).create_time(),ready_at=time.time())
    assert rows()==states
    assert journal()==before
    for pid in [27700,17392]:assert abs(psutil.Process(pid).create_time()-IDENTITIES[pid])<.01
    assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    save()
    print(json.dumps({k:v for k,v in receipt.items() if k!='code_sha256'}),flush=True)

if __name__=='__main__':main()
