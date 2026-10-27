import importlib.util
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest


ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'skills/hotpost-mobile-upload/scripts/preflight.py'
spec=importlib.util.spec_from_file_location('mobile_upload_preflight',SCRIPT)
preflight=importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def test_fresh_install_audit_creates_no_state_or_login_claim(tmp_path,monkeypatch):
    monkeypatch.setattr('hotpost.config.load_settings',lambda **kwargs:SimpleNamespace(data_dir=tmp_path/'absent'))
    result=preflight.inspect(ROOT)
    assert result['read_only'] and not result['installation_saved']
    assert not result['installation']['configured'] and not result['installation']['login_verified']
    assert result['devices']==result['jobs']==result['next_post_slots']==[]
    assert not (tmp_path/'absent').exists()
    with pytest.raises(ValueError):preflight.inspect(tmp_path)


def test_saved_setup_and_cross_device_attempts_reused_without_mutation(tmp_path,monkeypatch):
    monkeypatch.setattr('hotpost.config.load_settings',lambda **kwargs:SimpleNamespace(data_dir=tmp_path))
    values={'publication_accounts':['my.brand'],'discovery_account':'product.reader',
            'storefront_url':'https://influencers.coupang.com/s/own-store','collection':'내 상품'}
    (tmp_path/'monetization').mkdir()
    with sqlite3.connect(tmp_path/'monetization/state.sqlite3') as db:
        db.execute('CREATE TABLE configuration(name TEXT,value TEXT)')
        db.execute('INSERT INTO configuration VALUES(?,?)',('installation',json.dumps({'revision':2,'values':values})))
        db.execute('CREATE TABLE next_post_slots(account TEXT,task_id TEXT,status TEXT)')
        db.execute('INSERT INTO next_post_slots VALUES(?,?,?)',('my.brand','job2','ready'))
    (tmp_path/'.mobile-device.json').write_text(json.dumps({'phone_ip':'10.9.0.2','adb_port':12345,'android_serial':'phone1'}))
    (tmp_path/'mobile-devices').mkdir()
    (tmp_path/'mobile-devices/phone2.json').write_text(json.dumps({'phone_ip':'10.9.0.3','adb_port':23456,'android_serial':'phone2'}))
    (tmp_path/'mobile-reels').mkdir()
    with sqlite3.connect(tmp_path/'mobile-reels/jobs.sqlite3') as db:
        db.execute('CREATE TABLE jobs(id TEXT,phase TEXT,value TEXT)')
        for job,phase,device,code in [('job1','submitted','primary','video1'),('job2','unknown','phone2','video1'),
                                      ('job3','prepared','phone2','video2')]:
            value={'package':{'shortcode':code,'account':'my.brand','device_id':device},
                   'share_attempted_at':123 if phase!='prepared' else None,'upstream_hold':{'reason':'pending'}}
            if job=='job1':value['pinned_comment_publication']={'status':'pinned','pin_verified':True}
            db.execute('INSERT INTO jobs VALUES(?,?,?)',(job,phase,json.dumps(value)))
    before={p.relative_to(tmp_path):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result=preflight.inspect(ROOT,'video1')
    assert result['installation_saved'] and result['installation']['values']==values
    assert result['installation']['configured'] and not result['installation']['login_verified']
    assert len(result['devices'])==2 and all(not d['live_connection_checked'] for d in result['devices'])
    assert len(result['jobs'])==2 and all(j['must_not_resubmit'] for j in result['jobs'])
    by_id={j['job']:j for j in result['jobs']}
    assert by_id['job1']['pinned_comment_verified'] and by_id['job1']['pinned_comment_status']=='pinned'
    assert not by_id['job2']['pinned_comment_verified'] and by_id['job2']['pinned_comment_status']=='not_verified'
    assert result['next_post_slots']==[{'account':'my.brand','task_id':'job2','status':'ready'}]
    assert before=={p.relative_to(tmp_path):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_real_config_loader_in_new_process_does_not_create_data_or_web(tmp_path):
    import os
    import subprocess
    import sys
    result=subprocess.run([sys.executable,'-X','utf8',str(SCRIPT),'--repo',str(ROOT)],
        cwd=ROOT,env={**os.environ,'HOTPOST_DATA_DIR':str(tmp_path/'missing-data'),
                      'HOTPOST_WEB_DIR':str(tmp_path/'missing-web')},capture_output=True,text=True,encoding='utf8')
    assert result.returncode==0,result.stderr
    value=json.loads(result.stdout)
    assert value['read_only'] and not value['installation']['configured']
    assert not list(tmp_path.iterdir())
