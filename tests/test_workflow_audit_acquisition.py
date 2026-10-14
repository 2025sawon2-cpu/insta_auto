"""Observable boundaries: ownership, waiting, received bytes and actual progress."""
import json
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost.storage import Storage
from hotpost.job_queue import JobQueue
from hotpost.operation_progress import run_progress_command, NoProgressTimeout
from hotpost.source_search.strategy import fresh_queries
from test_parallel_sources import task, finish
from test_source_strategy import round_result, claim_next


def test_two_storage_connections_cannot_claim_one_request_and_late_token_cannot_finish(tmp_path):
    first = Storage(tmp_path/'test.db'); second = Storage(tmp_path/'test.db')
    first.create_job('job','source','post')
    assert first.claim_job('job','first')
    assert second.claim_job('job','second') is None
    first.interrupt_running_jobs()
    first.update_job('job',status='queued')
    assert second.claim_job('job','new')
    assert not first.update_running_job('job','first',status='done',result_json='{"old":true}')
    assert not first.update_running_job('job','first',message='late progress')
    assert second.update_running_job('job','new',status='done',result_json='{"new":true}')
    assert first.job_for('job')['result']=={'new':True}
    first.close(); second.close()


def test_second_queue_cannot_interrupt_live_first_owner_and_dispatch_message_is_truthful(tmp_path):
    settings=Settings(data_dir=tmp_path,job_concurrency=1)
    queue=JobQueue(settings); started=threading.Event(); release=threading.Event()
    def worker(code,progress):
        started.set(); release.wait(5)
        return {'studio':{'id':'task','status':'queued'}}
    queue.register('production',worker)
    job=queue.start('production','post')
    assert started.wait(3)
    try:
        with pytest.raises(RuntimeError,match='큐가 실행'):
            JobQueue(settings)
        assert queue.get(job['id'])['status']=='running'
        release.set(); queue.pending.join()
        result=queue.get(job['id'])
        assert result['status']=='done'
        assert '접수 완료' in result['message'] and '두 버전 제작 완료' not in result['message']
        assert result['result']['studio']['id']=='task'
    finally:
        release.set();queue.close()


@pytest.mark.parametrize('status',['captcha','login_required','verification_required','rate_limited','cooldown','connection_failed'])
def test_access_wait_never_becomes_content_failure_and_can_resume_same_scope(tmp_path,status):
    studio,tid,_=task(tmp_path)
    studio.store.change(tid,lambda s,db:s['source_acquisition'].update(no_progress_rounds=2))
    for index in range(4):
        job=claim_next(studio,tid)
        finish(studio,job,round_result(index,searches=[
            {'provider':'tiktok','query':'mirror','status':status},
            {'provider':'youtube','query':'','status':'query_exhausted'}]))
        current=studio.store.get(tid)['source_acquisition']
        assert not current.get('hold') and current['no_progress_rounds']==2
        assert current.get('waiting') and not current['queries']
    assert fresh_queries(['mirror'],'tiktok',current['queries'])==['mirror']
    job=claim_next(studio,tid)
    finish(studio,job,round_result(4,searches=[{'provider':'tiktok','query':'mirror','status':'no_results'}]))
    assert not studio.store.get(tid)['source_acquisition'].get('waiting')
    assert not fresh_queries(['mirror'],'tiktok',studio.store.get(tid)['source_acquisition']['queries'])


def test_distinct_new_failed_search_scopes_remain_available_then_true_exhaustion_stops(tmp_path):
    studio,tid,_=task(tmp_path)
    for index in range(5):
        job=claim_next(studio,tid)
        finish(studio,job,round_result(index))
        assert not studio.store.get(tid)['source_acquisition'].get('hold')
    job=claim_next(studio,tid)
    finish(studio,job,round_result(5,searches=[{'provider':'youtube','query':'','status':'query_exhausted'}]))
    assert studio.store.get(tid)['source_acquisition']['hold']['reason']=='strategy_exhausted'
    studio.store.recover()
    assert claim_next(studio,tid) is None


def test_changing_metadata_logs_without_received_bytes_is_not_progress(tmp_path):
    script="import time\nfor i in range(20):\n print('Destination: random-'+str(i),flush=True);time.sleep(.2)"
    with pytest.raises(NoProgressTimeout):
        run_progress_command([sys.executable,'-c',script],idle_seconds=1,progress_dir=tmp_path)


def test_old_file_does_not_grant_new_process_progress_and_real_decoded_time_does(tmp_path):
    (tmp_path/'old.mp4').write_bytes(b'prior received media')
    with pytest.raises(NoProgressTimeout):
        run_progress_command([sys.executable,'-c','import time;time.sleep(10)'],idle_seconds=1,progress_dir=tmp_path)
    code="import time\nfor i in range(6):\n print('out_time_us='+str(i*1000000),flush=True);time.sleep(.4)"
    assert run_progress_command([sys.executable,'-c',code],idle_seconds=1).returncode==0


def test_partial_reference_receive_preserves_published_file_and_never_enters_cache(tmp_path,monkeypatch):
    from hotpost import source_finder as sf, instagram_video as iv
    settings=Settings(data_dir=tmp_path,collection_source='browser')
    target=tmp_path/'reference.mp4';target.write_bytes(b'existing full original')
    monkeypatch.setattr(iv,'browser_video_url',lambda *a:'https://s.cdninstagram.com/v.mp4')
    monkeypatch.setattr(sf,'request_pause',lambda:None)
    def chunks(_):
        yield b'new partial'
        raise sf.requests.ConnectionError('lost response')
    response=SimpleNamespace(status_code=200,headers={},iter_content=chunks,close=lambda:None)
    monkeypatch.setattr(sf.requests,'get',lambda *a,**k:response)
    with pytest.raises(sf.requests.ConnectionError):sf._download_reference(settings,SimpleNamespace(shortcode='p'),target)
    assert target.read_bytes()==b'existing full original'
    assert not target.with_name('reference.mp4.receiving').exists()


def test_deterministic_download_failure_is_not_retried_but_network_retry_remains(tmp_path,monkeypatch):
    from hotpost import source_finder as sf, operation_progress as op
    from hotpost.source_search.models import Candidate
    from hotpost import login_exchange
    monkeypatch.setattr(sf,'_executable',lambda n:n)
    monkeypatch.setattr(sf,'request_pause',lambda:None)
    monkeypatch.setattr(sf.time,'sleep',lambda n:None)
    monkeypatch.setattr(login_exchange,'downloader_cookies',lambda *a:None)
    calls=[]
    def fail(*a,**k):
        calls.append(1);return subprocess.CompletedProcess([],1,'','ERROR: Unsupported URL')
    monkeypatch.setattr(op,'run_progress_command',fail)
    assert sf.download_candidate(Candidate(url='https://www.bilibili.com/video/BV1test',provider='bilibili'),tmp_path,1,100) is None
    assert len(calls)==1
    monkeypatch.setattr(op,'run_progress_command',lambda *a,**k:calls.append(1) or subprocess.CompletedProcess([],1,'','ERROR: Connection reset'))
    sf.download_candidate(Candidate(url='https://www.bilibili.com/video/BV2test',provider='bilibili'),tmp_path,2,100)
    assert len(calls)==4


def test_windows_schedule_keeps_interactive_ownership_without_total_age_kill():
    from hotpost.scheduler import windows_task_xml
    text=windows_task_xml()
    assert '<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>' in text
    assert '<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>' in text
    assert '<LogonType>InteractiveToken</LogonType>' in text


def test_producer_submission_is_consumed_and_closing_owner_retains_lease_until_drain(tmp_path):
    settings=Settings(data_dir=tmp_path,job_concurrency=1)
    owner=JobQueue(settings); producer=JobQueue(settings,workers=False)
    entered=threading.Event(); release=threading.Event()
    def worker(code,progress):
        entered.set();release.wait(5);return {'json_path':'result.json'}
    owner.register('transcript',worker);producer.register('transcript',worker)
    job=producer.start('transcript','post')
    assert entered.wait(3), 'Consumer must poll submissions from another handler/process'
    closing=threading.Thread(target=owner.close);closing.start()
    try:
        with pytest.raises(RuntimeError):JobQueue(settings)
        assert producer.get(job['id'])['status']=='running'
    finally:
        release.set();closing.join(3);producer.close()
    assert not closing.is_alive()
    restarted=JobQueue(settings)
    try:assert restarted.get(job['id'])['status']=='done'
    finally:restarted.close()


def test_scheduler_binding_failure_does_not_start_or_interrupt_worker_owner(tmp_path,monkeypatch):
    from hotpost import server
    settings=Settings(data_dir=tmp_path)
    existing=server.ThreadingHTTPServer(('127.0.0.1',0),server.SimpleHTTPRequestHandler)
    monkeypatch.setattr(server,'make_handler',lambda *a:pytest.fail('Bind failure must precede managers'))
    try:
        with pytest.raises(OSError):server.serve(settings,existing.server_port)
    finally:existing.server_close()
    assert not (tmp_path/'legacy-queue.lock').exists()


def test_inspected_metadata_failure_is_consumed_without_fabricating_network_attempt():
    from hotpost.source_search.strategy import candidate_ledgers
    result=candidate_ledgers([
        {'url':'https://www.tiktok.com/@u/video/1','download_attempted':False,'rejection_reasons':['invalid_duration']},
        {'url':'https://www.tiktok.com/@u/video/2','download_attempted':False,'error':'429 cooldown','rejection_reasons':['download_failed']},
        {'url':'https://www.tiktok.com/@u/video/3','download_attempted':False,'rejection_reasons':['not_probed']}])
    assert result['inspected_urls']==['https://www.tiktok.com/@u/video/1']
    assert not result['attempted_urls']
    assert result['access_waits'][0]['url'].endswith('/2')


def test_access_pending_candidate_is_recoverable_but_unchanged_confirmed_failure_is_not(tmp_path):
    from hotpost.source_search.triage import deferred_candidates
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'candidates':[
        {'url':'https://www.tiktok.com/@u/video/1','provider':'tiktok','download_attempted':True,'error':'429','rejection_reasons':['download_failed']},
        {'url':'https://www.tiktok.com/@u/video/2','provider':'tiktok','download_attempted':True,'error':'Unsupported URL','rejection_reasons':['download_failed']},
        {'url':'https://www.tiktok.com/@u/video/3','provider':'tiktok','download_attempted':False,'rejection_reasons':['invalid_duration']}]}))
    results=deferred_candidates({'rounds':[{'manifest_path':str(manifest)}]},[],20)
    assert [r.url for r in results]==['https://www.tiktok.com/@u/video/1']
    assert results[0].download_attempted is None and not results[0].error


def test_speech_partial_evidence_survives_failure_without_becoming_completed_transcript(tmp_path,monkeypatch):
    from hotpost import speech_worker
    audio=tmp_path/'audio.wav';audio.write_bytes(b'original audio')
    request=tmp_path/'request.json';result=tmp_path/'result.json'
    request.write_text(json.dumps({'audio':str(audio),'data_dir':str(tmp_path),'model':'fixture'}))
    def speech(settings,path,notes,progress):
        progress({'source':'speech','start':0.,'end':1.,'text':'observed partial'})
        raise RuntimeError('later ASR failure')
    monkeypatch.setattr(speech_worker,'_speech',speech)
    monkeypatch.setattr(sys,'argv',['speech_worker','--request',str(request),'--result',str(result)])
    assert speech_worker.main()==1
    assert 'error' in json.loads(result.read_text('utf-8'))
    assert json.loads((tmp_path/'speech-partial.json').read_text('utf-8'))['status']=='partial'


def test_cli_multi_interface_bind_failure_precedes_manager_and_queue_changes(tmp_path,monkeypatch):
    from hotpost import server
    settings=Settings(data_dir=tmp_path/'state')
    occupied=server.ManagedHTTPServer(('127.0.0.1',0),server.SimpleHTTPRequestHandler)
    calls=[]
    monkeypatch.setattr(server,'make_handler',lambda *a:calls.append(1) or pytest.fail('Managers must not start'))
    try:
        # First interface binds successfully; the second cannot. Both paths
        # must fail before even creating queue recovery or Studio/top watcher.
        with pytest.raises(OSError):server.serve_many(settings,['127.0.0.2','127.0.0.1'],occupied.server_port)
        assert not calls and not (settings.data_dir/'legacy-queue.lock').exists()
        assert not settings.db_path.exists()
    finally:occupied.server_close()


def test_handler_initialization_failure_releases_unstarted_queue_without_recovering_jobs(tmp_path,monkeypatch):
    from hotpost import server
    settings=Settings(data_dir=tmp_path)
    storage=Storage(settings.db_path)
    storage.create_job('old','source','post');storage.update_job('old',status='running');storage.close()
    monkeypatch.setattr(server,'SourceJobManager',lambda *a:(_ for _ in ()).throw(RuntimeError('manager initialization failed')))
    with pytest.raises(RuntimeError,match='manager initialization'):server.serve_many(settings,['127.0.0.1'],0)
    storage=Storage(settings.db_path)
    try:assert storage.job_for('old')['status']=='running'
    finally:storage.close()
    new=JobQueue(settings,autostart=False)
    new.close()


def test_durable_production_is_not_consumed_until_temporary_legacy_worker_replaced(tmp_path):
    settings=Settings(data_dir=tmp_path,job_concurrency=1)
    storage=Storage(settings.db_path);storage.create_job('queued','production','post');storage.close()
    queue=JobQueue(settings,autostart=False)
    queue.register('production',lambda *a:pytest.fail('Temporary legacy worker must not execute'))
    assert not queue._threads and queue.get('queued')['status']=='queued'
    queue.register('production',lambda *a:{'studio':{'id':'new-task','status':'queued'}})
    try:
        queue.start_workers();queue.resume_queued();queue.pending.join()
        assert queue.get('queued')['result']['studio']['id']=='new-task'
    finally:queue.close()


def test_late_handler_initialization_failure_closes_created_studio_after_queue(tmp_path,monkeypatch):
    from hotpost import server
    events=[]
    queue=SimpleNamespace(register=lambda *a:None,
        start_workers=lambda:(_ for _ in ()).throw(RuntimeError('late worker activation failure')),
        resume_queued=lambda:pytest.fail('Activation failed'),close=lambda:events.append('queue'))
    monkeypatch.setattr(server,'JobQueue',lambda *a,**k:queue)
    for name in ('SourceJobManager','TranscriptJobManager','LegacyProductionManager',
                 'PlatformSessionManager','AccountRegistry','ProductionManager'):
        monkeypatch.setattr(server,name,lambda *a:SimpleNamespace())
    studio=SimpleNamespace(close=lambda:events.append('studio'))
    monkeypatch.setattr(server,'Studio',lambda *a:studio)
    with pytest.raises(RuntimeError,match='late worker activation'):
        server.serve_many(Settings(data_dir=tmp_path),['127.0.0.1'],0)
    assert events==['queue','studio']


def test_shared_handler_resources_close_only_after_last_socket_and_accepted_http_request(tmp_path,monkeypatch):
    from hotpost import server
    from http.client import HTTPConnection
    from functools import partial
    events=[];entered=threading.Event();release=threading.Event()
    class Handler(server.SimpleHTTPRequestHandler):
        def do_GET(self):
            entered.set();release.wait(5)
            events.append('request finished')
            self.send_response(204);self.end_headers()
        def log_message(self,*a):pass
    handler=partial(Handler,directory=str(tmp_path))
    handler.resource_lock=threading.Lock();handler.server_count=0
    handler.job_queue=SimpleNamespace(close=lambda:events.append('queue'))
    handler.studio_resource=SimpleNamespace(close=lambda:events.append('studio'))
    monkeypatch.setattr(server,'make_handler',lambda *a:handler)
    servers=server.serve_many(Settings(data_dir=tmp_path),['127.0.0.1','127.0.0.2'],0)
    first,last=servers
    first.server_close();first.server_close()
    assert not events and handler.server_count==1
    serving=threading.Thread(target=last.serve_forever);serving.start()
    def request():
        connection=HTTPConnection(*last.server_address,timeout=5)
        try:connection.request('GET','/');connection.getresponse().read()
        finally:connection.close()
    sending=threading.Thread(target=request);sending.start()
    assert entered.wait(3)
    last.shutdown();serving.join(3)
    closing=threading.Thread(target=last.server_close);closing.start()
    try:
        assert not events and closing.is_alive()
    finally:
        release.set();sending.join(3);closing.join(3)
    assert not closing.is_alive() and events==['request finished','queue','studio']
    last.server_close();assert handler.server_count==0 and events.count('studio')==1


def test_injected_second_thread_start_failure_drains_first_and_preserves_startup_exception(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path,job_concurrency=2)
    original=threading.Thread.start;attempts=[];started=[]
    def faulty(thread):
        attempts.append(thread)
        if len(attempts)==2:
            raise RuntimeError('injected thread startup failure')
        original(thread);started.append(thread)
    monkeypatch.setattr(threading.Thread,'start',faulty)
    with pytest.raises(RuntimeError,match='injected thread startup failure'):
        JobQueue(settings)
    assert len(started)==1 and not started[0].is_alive()
    monkeypatch.setattr(threading.Thread,'start',original)
    restarted=JobQueue(settings,autostart=False)
    restarted.close()
