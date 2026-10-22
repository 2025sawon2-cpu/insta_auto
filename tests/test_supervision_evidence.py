import json
import hashlib
import os
from pathlib import Path
import sqlite3
import time

from hotpost.supervision_evidence import collect_evidence


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def job(checkpoint=None):
    return {'id': 'job-one', 'task_id': 'work-one', 'kind': 'edit', 'checkpoint': checkpoint or {}}


def test_initial_snapshot_is_idempotent_and_heartbeat_never_progress(tmp_path):
    folder = tmp_path/'studio/work-one/job-one';folder.mkdir(parents=True)
    (folder/'preview.mp4').write_bytes(b'video')
    save(folder/'render-result.json', {'status': 'completed', 'plan': {'x': 1}})
    save(folder/'semantic-plan.json', {'shots': [1]})
    first = collect_evidence(tmp_path, job())
    assert first['progress']['artifact_bytes:.mp4'] == 5
    assert first['progress']['completed:render-result.json'] == 1
    assert first['waits'] == []
    (folder/'render.log').write_text('alive'*1000)
    os.utime(folder/'preview.mp4', None)
    save(folder/'semantic-plan.json', {'shots': [2], 'heartbeat': 9999})
    second = collect_evidence(tmp_path, job({'pid': 123, 'revision': 99999}))
    assert second['progress'] == first['progress']
    (folder/'preview.mp4').write_bytes(b'video-more')
    assert collect_evidence(tmp_path, job())['progress']['artifact_bytes:.mp4'] == 10


def test_failed_nested_or_partial_result_headers_are_not_completed(tmp_path):
    folder = tmp_path/'studio/work-one/job-one'
    save(folder/'failed-result.json', {'status': 'failed'})
    save(folder/'nested-result.json', {'plan': {'status': 'completed'}})
    (folder/'partial-result.json').write_text('{"status":"completed",')
    assert collect_evidence(tmp_path, job())['progress'] == {}


def test_large_studio_result_is_read_selectively_without_loading_plan(tmp_path, monkeypatch):
    path = save(tmp_path/'studio/work-one/job-one/analyze-result.json',
                {'status': 'completed', 'plan': 'x' * 3_000_000})
    original = Path.read_text
    def guarded(self, *args, **kwargs):
        assert self != path
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', guarded)
    assert collect_evidence(tmp_path, job())['progress'] == {'completed:analyze-result.json': 1}


def writing_db(root):
    folder=root/'writing';folder.mkdir()
    db=sqlite3.connect(folder/'jobs.sqlite3')
    db.execute('CREATE TABLE jobs(id TEXT,state TEXT,payload TEXT,result TEXT)')
    db.execute('INSERT INTO jobs VALUES(?,?,?,?)', ('codexlinked','running','SECRET BASE64',None))
    db.execute('INSERT INTO jobs VALUES(?,?,?,?)', ('codexother','queued','SECRET BASE64',None))
    db.commit()
    return db


def test_writing_only_explicit_links_no_payload_or_unrelated_output(tmp_path, monkeypatch):
    db=writing_db(tmp_path)
    save(tmp_path/'writing/codexother/result.json', {'value': 'unrelated'})
    output=save(tmp_path/'writing/codexlinked/result.json', {'value':'real output'})
    original=Path.read_text
    def guarded(self,*args,**kwargs):
        assert self.name not in {'payload.json','result.json'}
        return original(self,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',guarded)
    checkpoint={'supervision_model_job_id':'codexlinked'}
    first=collect_evidence(tmp_path,job(checkpoint))
    assert first['progress']=={} and first['waits']==[]
    db.execute("UPDATE jobs SET state='completed' WHERE id='codexlinked'");db.commit()
    second=collect_evidence(tmp_path,job(checkpoint))
    assert second['progress']=={'writing_output_bytes:codexlinked':output.stat().st_size}
    assert all('codexother' not in str(x) for x in second['references'])
    db.close()


def test_only_current_explicit_waits_not_running_or_text(tmp_path):
    db=writing_db(tmp_path)
    assert collect_evidence(tmp_path,job({'not_before':time.time()-1,'message':'waiting'}))['waits']==[]
    db.execute("UPDATE jobs SET state='queued' WHERE id='codexlinked'");db.commit()
    waits=collect_evidence(tmp_path,job({'studio_job_id':'codexlinked'}))['waits']
    assert [w['kind'] for w in waits]==['model_queue']
    until=time.time()+120
    db.execute('UPDATE jobs SET state=?,result=? WHERE id=?',
               ('failed',json.dumps({'error_reason':'model_capacity','retry_at':until}),'codexlinked'));db.commit()
    waits=collect_evidence(tmp_path,job({'studio_job_id':'codexlinked'}))['waits']
    assert waits[0]['until']==until and waits[0]['kind']=='model_capacity'
    assert collect_evidence(tmp_path,job({'not_before':until}))['waits'][0]['kind']=='scheduled_retry'
    db.close()


def source_setup(root):
    folder=root/'source_jobs/shortcode-123'
    manifest=save(folder/'manifest.json',{'search_audit':[],'candidates':[]})
    worker=save(folder/'browser_debug'/('search-checkpoint-'+'a'*32+'.json'),{})
    entry={'task_id':'work-one','studio_job_id':'job-one','manifest_path':str(manifest),
           'workers':[{'path':str(worker),'settled':False}]}
    return folder,manifest,worker,entry


def test_search_scope_dedup_access_pending_and_pacing(tmp_path):
    folder,manifest,worker,entry=source_setup(tmp_path)
    query={'provider':'tiktok','query':'crochet duck','status':'results','page':1}
    save(worker,{'searches':[query,dict(query,at=1234)],'waiting_until':time.time()+60,
                 'message':'alive','candidates':[{'url':'candidate-only'}]})
    bound=job({'source_attempts':[entry]})
    first=collect_evidence(tmp_path,bound)
    assert len(first['progress'])==1 and first['waits'][0]['kind']=='source_pacing'
    save(worker,{'searches':[query,dict(query,page=2),dict(query,query='other',status='captcha')],
                 'message':'different heartbeat','waiting_until':time.time()-1})
    second=collect_evidence(tmp_path,bound)
    assert len(second['progress'])==2 and second['waits']==[]
    save(worker,{'waiting_until':time.time()+60,'searches':[]})
    entry['workers'][0]['settled']=True
    assert collect_evidence(tmp_path,bound)['waits']==[]


def test_source_bytes_are_real_and_unverified_download_never_verification(tmp_path):
    folder,manifest,worker,entry=source_setup(tmp_path)
    media=folder/'real.mp4';media.write_bytes(b'actual')
    candidate={'url':'https://example.com/video1','downloaded_file':'real.mp4'}
    save(manifest,{'candidates':[candidate,dict(candidate,downloaded_file='missing.mp4')]})
    transfer=save(folder/'video-transfer.json',{'stage':'receiving','covered_bytes':25,'last_progress_at':1})
    bound=job({'source_attempts':[entry]});first=collect_evidence(tmp_path,bound)
    assert sorted(first['progress'].values())==[6,25]
    assert not any(k.startswith('verified') for k in first['progress'])
    save(transfer,{'stage':'new message','covered_bytes':25,'last_progress_at':99999,'media_responses':50})
    assert collect_evidence(tmp_path,bound)['progress']==first['progress']
    candidate['file_sha256']=hashlib.sha256(media.read_bytes()).hexdigest()
    candidate['functional_review']={'reviewed':True,'source_sha256':candidate['file_sha256'],
                                    'evidence_frames':['observed'],'observed_actions':['visible product']}
    save(manifest,{'candidates':[candidate]})
    assert any(k.startswith('file_bound_review') for k in collect_evidence(tmp_path,bound)['progress'])
    media.write_bytes(b'changed')
    assert not any(k.startswith('file_bound_review') for k in collect_evidence(tmp_path,bound)['progress'])


def test_unbound_and_escaping_paths_are_ignored(tmp_path):
    _,_,worker,entry=source_setup(tmp_path)
    save(worker,{'waiting_until':time.time()+60,'searches':[{'provider':'x','query':'x','status':'results'}]})
    entry['studio_job_id']='other-job'
    assert collect_evidence(tmp_path,job({'source_attempts':[entry]}))['progress']=={}
    assert collect_evidence(tmp_path,{'id':'../escape','task_id':'work-one'})['unknown']


def test_unknown_and_malformed_checkpoint_are_conservative(tmp_path):
    for checkpoint in [None, 'invalid JSON', {'studio_job_id': []}, {'source_attempts': 5}]:
        result=collect_evidence(tmp_path,job(checkpoint))
        assert result['unknown'] and result['progress']=={} and result['waits']==[]
        json.dumps(result)


def test_only_bound_unique_model_content_counts_and_retry_ids_do_not_reset(tmp_path):
    db=writing_db(tmp_path)
    folder=tmp_path/'writing/codexlinked/codex-first'
    receipt={'provider':'codex','status':'running','call_id':folder.name,'request_sha256':'a'*64}
    save(folder/'receipt.json',receipt)
    save(folder/'progress.json',{'kind':'model_items','sequence':3,'call_id':folder.name})
    bound=job({'supervision_model_job_id':'codexlinked'})
    first=collect_evidence(tmp_path,bound)
    assert first['progress']=={'model_items:codexlinked:'+('a'*64):3}
    other=folder.parent/'codex-retry'
    save(other/'receipt.json',dict(receipt,call_id=other.name))
    save(other/'progress.json',{'kind':'model_items','sequence':2,'call_id':other.name})
    assert collect_evidence(tmp_path,bound)['progress']==first['progress']
    save(other/'progress.json',{'kind':'model_items','sequence':4,'call_id':other.name})
    assert list(collect_evidence(tmp_path,bound)['progress'].values())==[4]
    save(other/'progress.json',{'kind':'heartbeat','sequence':99999,'call_id':other.name})
    assert collect_evidence(tmp_path,bound)['progress']==first['progress']
    db.close()


def test_evidence_sha_cache_invalidates_but_mtime_is_not_progress(tmp_path):
    from hotpost.supervision_evidence import _cached_digest
    path=save(tmp_path/'studio/work-one/job-one/semantic-plan.json',{'shots':[1]})
    _cached_digest.cache_clear()
    first=collect_evidence(tmp_path,job())
    collect_evidence(tmp_path,job())
    assert _cached_digest.cache_info().hits==1
    save(path,{'shots':[2]})
    second=collect_evidence(tmp_path,job())
    assert second['progress']==first['progress']
    assert second['references'][0]['sha256']!=first['references'][0]['sha256']


def test_older_queued_model_cannot_suspend_current_active_model(tmp_path):
    db=writing_db(tmp_path)
    bound=job({'studio_job_id':'codexother','supervision_model_job_id':'codexlinked'})
    assert collect_evidence(tmp_path,bound)['waits']==[]
    db.close()


def test_completed_model_history_survives_link_clear_without_cache_recount(tmp_path):
    db=writing_db(tmp_path)
    db.execute("UPDATE jobs SET state='completed' WHERE id='codexlinked'");db.commit()
    output=save(tmp_path/'writing/codexlinked/result.json',{'value':'finished between ticks'})
    active=collect_evidence(tmp_path,job({'supervision_model_job_id':'codexlinked'}))
    checkpoint={'supervision_model_job_id':None,'supervision_model_history':['codexlinked']}
    saved=collect_evidence(tmp_path,job(checkpoint))
    assert saved['progress']==active['progress']=={'writing_output_bytes:codexlinked':output.stat().st_size}
    checkpoint['supervision_model_history'].extend(['codexlinked','codexlinked','codexother','../unbound'])
    repeated=collect_evidence(tmp_path,job(checkpoint))
    assert repeated['progress']==saved['progress'] and repeated['waits']==[]
    db.close()


def test_local_wait_requires_current_claim_known_kind_and_future_deadline(tmp_path):
    until=time.time()+120
    value=job({'supervision_wait':{'kind':'local_compute','until':until,'claim':'owned'}})
    value['claim_token']='owned'
    observed=collect_evidence(tmp_path,value)
    assert observed['progress']=={} and observed['waits']==[
        {'kind':'local_compute','until':until,'reference':'checkpoint.supervision_wait'}]
    value['checkpoint']['supervision_wait']['kind']='voice_service_busy'
    assert collect_evidence(tmp_path,value)['waits'][0]['kind']=='voice_service_busy'
    for mutation in [{'claim':'old-owner'},{'until':time.time()-1},{'until':None},{'kind':'arbitrary-wait'}]:
        value['checkpoint']['supervision_wait']={'kind':'local_compute','until':until,'claim':'owned',**mutation}
        assert collect_evidence(tmp_path,value)['waits']==[]
    value.pop('claim_token')
    assert collect_evidence(tmp_path,value)['waits']==[]


def test_voice_progress_requires_exact_claim_and_integer_request_binding(tmp_path):
    until=time.time()+60
    value=job({'request_id':7,'supervision_voice':{'claim':'owned','request_id':7,
              'status':'running','completed_segments':2,'until':until}})
    value['claim_token']='owned'
    first=collect_evidence(tmp_path,value)
    assert first['progress']=={'voice_segments:7':2} and first['waits']==[]
    value['checkpoint']['supervision_voice']['until']=until+20
    assert collect_evidence(tmp_path,value)['progress']==first['progress']
    value['checkpoint']['supervision_voice']['completed_segments']=3
    assert collect_evidence(tmp_path,value)['progress']=={'voice_segments:7':3}
    for mutation in [{'claim':'stale'},{'request_id':8},{'request_id':True},{'request_id':'7'},
                     {'status':'unrecognized'}]:
        value['checkpoint']['supervision_voice']={'claim':'owned','request_id':7,'status':'running',
                                                'completed_segments':2,'until':until,**mutation}
        assert collect_evidence(tmp_path,value)['progress']=={}


def test_only_fresh_bound_queued_voice_suspends_idle(tmp_path):
    until=time.time()+60
    value=job({'request_id':7,'supervision_voice':{'claim':'owned','request_id':7,
              'status':'queued','completed_segments':0,'until':until}})
    value['claim_token']='owned'
    assert collect_evidence(tmp_path,value)['waits']==[
        {'kind':'voice_queue','until':until,'reference':'checkpoint.supervision_voice'}]
    for mutation in [{'until':time.time()-1},{'until':None},{'status':'running'},
                     {'status':'succeeded'},{'claim':'stale'},{'request_id':8}]:
        value['checkpoint']['supervision_voice']={'claim':'owned','request_id':7,'status':'queued',
                                                'completed_segments':0,'until':until,**mutation}
        assert collect_evidence(tmp_path,value)['waits']==[]


def test_voice_output_folder_bytes_are_separate_and_task_scoped(tmp_path):
    folder=tmp_path/'studio/work-one/voice-one';folder.mkdir(parents=True)
    (folder/'original.wav').write_bytes(b'approved-wave')
    edit=tmp_path/'studio/work-one/job-one';edit.mkdir()
    (edit/'other.wav').write_bytes(b'job-wave')
    value=job();value.update(kind='voice',payload={'voice_id':'voice-one'})
    result=collect_evidence(tmp_path,value)
    assert result['progress']['voice_output_bytes:voice-one']==13
    assert result['progress']['artifact_bytes:.wav']==8
    value['payload']['voice_id']='../voice-one'
    assert not any(k.startswith('voice_output') for k in collect_evidence(tmp_path,value)['progress'])
    value['payload']['voice_id']='voice-one';value['kind']='edit'
    assert not any(k.startswith('voice_output') for k in collect_evidence(tmp_path,value)['progress'])
