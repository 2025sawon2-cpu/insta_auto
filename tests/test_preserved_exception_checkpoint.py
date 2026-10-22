"""Preserved incident checkpoint recovery, never production approval.

The causal input is the original generic RuntimeError receipt plus exact
owner/run/claim/parser readiness. This sub-entry never reads media history;
keep it in the copied task without opening production paths. The unchanged
native-reader integration covers browser events and subsequent collection.
"""
import copy
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode

from hotpost.config import Settings
from hotpost.studio_store import StudioStore
from hotpost import source_parser_recovery as recovery
from hotpost.source_search.readiness import readiness_record


def test_preserved_generic_failure_persists_then_accepts_fresh_response(tmp_path,monkeypatch):
    original=json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    incident=copy.deepcopy(original)
    task,job=incident['task'],incident['job']
    assert task['id']==job['task_id']
    assert task['run_id']==job['payload']['run_id']
    assert job['id']=='job-30789cffdc5c4d21'
    old=copy.deepcopy(job['checkpoint']['parser_response_recovery'])
    assert old['status']=='unavailable' and old['error_type']=='RuntimeError'
    assert 'error_frames' not in old
    readiness=copy.deepcopy(job['checkpoint']['parser_repair_context']['observations'][0]['readiness'])
    assert old['previous_readiness']==readiness
    settings=Settings(data_dir=tmp_path,source_browser_search=True,source_browser_existing_window_only=True)
    store=StudioStore(tmp_path/'isolated-store')
    job['status']='running'
    job['claim_token']=job['checkpoint']['_claim_token']
    with store.transaction() as db:
        db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)',
            (task['id'],task['shortcode'],task['revision'],json.dumps(task),1))
        db.execute('INSERT INTO jobs(id,task_id,kind,key,payload,status,checkpoint,error,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (job['id'],job['task_id'],job['kind'],job['key'],json.dumps(job['payload']),
             'running',json.dumps(job['checkpoint']),'',1,1))
    saved=tmp_path/'search_readiness'/'tiktok.json'
    saved.parent.mkdir(parents=True)
    saved.write_text(json.dumps(readiness),encoding='utf8')
    before=saved.read_bytes()
    calls=[]
    def unavailable(*args,**kwargs):
        calls.append('failure')
        raise RuntimeError('private cookie and service URL must not be persisted')
    monkeypatch.setattr(recovery,'read_response',unavailable)
    assert recovery.recover_response(settings,store,task,job) is False
    def persisted():
        with store.connect() as db:
            return json.loads(db.execute('SELECT checkpoint FROM jobs WHERE id=?',(job['id'],)).fetchone()[0])
    failed=copy.deepcopy(persisted()['parser_response_recovery'])
    assert failed==job['checkpoint']['parser_response_recovery']
    assert failed['status']=='unavailable' and failed['error_type']=='RuntimeError'
    assert 1<=len(failed['error_frames'])<=8
    assert failed['error_frames'][-1]['function']=='unavailable'
    assert all(set(row)=={'module','function','line'} for row in failed['error_frames'])
    assert 'private cookie' not in json.dumps(failed)
    assert failed['previous_readiness']==readiness
    assert failed['query_submitted'] is False and failed['grants_media_approval'] is False
    assert saved.read_bytes()==before
    def fresh(settings,query,before_refresh):
        calls.append('fresh')
        assert query==readiness['query']
        before_refresh()
        now=time.time()
        return {'http_status':200,'observation_started_at':now,'received_at':now,
            'page_url':'https://www.tiktok.com/search?'+urlencode({'q':query}),
            'response_url':'https://www.tiktok.com/api/search/item/full/?'+urlencode({'keyword':query}),
            'body':{'status_code':0,'item_list':[{'id':'123456789',
                'author':{'uniqueId':'isolated_fixture'},'desc':'isolated response',
                'video':{'width':720,'height':1280,'duration':12},'stats':{}}]}}
    monkeypatch.setattr(recovery,'read_response',fresh)
    # Invalid ownership and manual access remain rejected before external I/O.
    for damage in ('wrong_run','manual'):
        invalid=copy.deepcopy(job)
        if damage=='wrong_run':invalid['payload']['run_id']='foreign-run'
        else:invalid['checkpoint']['parser_repair_context']['observations'][0]['manual_gate_active']=True
        assert recovery.recover_response(settings,store,task,invalid) is False
        assert calls==['failure']
        assert persisted()['parser_response_recovery']==failed
        assert saved.read_bytes()==before
    assert recovery.recover_response(settings,store,task,job) is True
    accepted=persisted()['parser_response_recovery']
    assert accepted==job['checkpoint']['parser_response_recovery']
    assert accepted['status']=='response_validated'
    assert accepted['task_id']==original['task']['id']
    assert accepted['job_id']==original['job']['id']
    assert accepted['run_id']==original['task']['run_id']
    assert accepted['previous_readiness']==readiness
    assert accepted['query_submitted'] is False and accepted['grants_media_approval'] is False
    assert 'error_frames' not in accepted
    assert readiness_record(tmp_path,'tiktok')['recovery']==accepted
    assert calls==['failure','fresh']
    assert store.get(task['id'])['sources']==original['task']['sources']
    assert store.get(task['id'])['daily_quality']==original['task']['daily_quality']
    assert original==json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
