"""Deploy independently verified initial cover admission while completed outputs stay frozen."""
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
OUT=ROOT/'data/rework-top-three-20261014/initial-cover-deployment-v1'
OWNED={18672:1791986834.457994,36312:1791986834.4365563}
PRESERVED={27700:1791935853.9890325,17392:1791937467.8343894}
TAIL=['-m','hotpost','serve','--no-browser','--host','127.0.0.1']

def main():
    assert not OUT.exists()
    def journal():
        with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
            assert not db.execute("select 1 from jobs where status in ('queued','running')").fetchone()
            return {t:list(db.execute('select * from '+t+' order by rowid')) for t in ['tasks','jobs','events']}
    before=journal()
    with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        states={t:json.loads(s) for t,s in db.execute('select id,state from tasks')}
    for task,rev in [('work-1672e441725d4445',1496),('work-8b16890d03794af1',1422)]:
        assert states[task]['status']=='completed' and states[task]['revision']==rev
    assert states['work-8013247e50624ae6']['automation']['paused_by_user']
    for pid,stamp in {**OWNED,**PRESERVED}.items():assert abs(psutil.Process(pid).create_time()-stamp)<.01
    for pid in OWNED:assert psutil.Process(pid).cmdline()[-6:]==TAIL
    assert psutil.Process(18672).ppid()==36312 and Path(psutil.Process(18672).cwd()).resolve()==ROOT
    with sqlite3.connect((ROOT/'data/writing/jobs.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        assert not db.execute("select 1 from jobs where state in ('queued','running')").fetchone()
    paths=[ROOT/'hotpost'/p for p in ['cover_selection.py','initial_prepared_render.py','studio_workflow.py','studio_runtime/editing.py','cover_product_crop.py']]
    from hotpost.config import load_settings
    paths.append(load_settings().auto_capcut_root/'auto_capcut/core/studio_cover.py')
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    proof=ROOT/'data/rework-top-three-20261014/rank2-initial-preparation-cloned-db-independent.json'
    registration=ROOT/'data/rework-top-three-20261014/rank2-initial-cover-preparation-v2-copy/prepared-render-receipt.json'
    assert hashlib.sha256(registration.read_bytes()).hexdigest()=='f05b352436abf809bad3e94853104888fd9c283c6f63e5d165f6a374ecc05295'
    from hotpost.initial_prepared_render import from_state
    from_state(states['work-8013247e50624ae6'])
    assert 'PASS' in proof.read_text('utf-8').upper()
    OUT.mkdir()
    receipt={'old_owned':OWNED,'preserved':PRESERVED,'code_sha256':hashes,'started_at':time.time(),
        'task_mutations':0,'browser_restarts':0,'voice_restarts':0,'exits':{},
        'independent_review_sha256':hashlib.sha256(proof.read_bytes()).hexdigest(),
        'registration_sha256':hashlib.sha256(registration.read_bytes()).hexdigest()}
    def save():(OUT/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
    save()
    assert journal()==before
    with sqlite3.connect((ROOT/'data/writing/jobs.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        assert not db.execute("select 1 from jobs where state in ('queued','running')").fetchone()
    for pid,stamp in OWNED.items():
        try:process=psutil.Process(pid)
        except psutil.NoSuchProcess:
            assert pid==36312;receipt['exits'][str(pid)]='already_settled';continue
        assert abs(process.create_time()-stamp)<.01
        process.terminate();process.wait(timeout=10);receipt['exits'][str(pid)]='terminated_exact_identity'
    assert journal()==before
    with (OUT/'server.log').open('wb') as out,(OUT/'server.err.log').open('wb') as err:
        process=subprocess.Popen([sys.executable,'-X','utf8','-u',*TAIL],cwd=ROOT,stdin=subprocess.DEVNULL,
            stdout=out,stderr=err,close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
    receipt['new_launcher_pid']=process.pid;save()
    for _ in range(45):
        assert process.poll() is None
        try:
            if requests.get('http://127.0.0.1:8775/',timeout=1).status_code==200:break
        except requests.RequestException:pass
        time.sleep(.5)
    else:raise RuntimeError('New app readiness not confirmed')
    children=[p for p in psutil.Process(process.pid).children(recursive=True) if p.cmdline()[-6:]==TAIL]
    assert len(children)==1 and journal()==before
    for pid,stamp in PRESERVED.items():assert abs(psutil.Process(pid).create_time()-stamp)<.01
    assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    receipt.update(new_server_pid=children[0].pid,new_server_creation=children[0].create_time(),
        new_launcher_creation=psutil.Process(process.pid).create_time(),ready_at=time.time())
    save();print(json.dumps({k:v for k,v in receipt.items() if k!='code_sha256'}))

if __name__=='__main__':main()
