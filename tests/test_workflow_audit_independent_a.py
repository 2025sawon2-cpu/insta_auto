"""Independent boundary counterexamples; never use operational state/services."""
import copy
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from hotpost.studio_store import StaleClaim, Conflict, change_claimed
from hotpost.source_search.discovery import discover
from hotpost.source_search.models import Candidate
from hotpost.source_search.strategy import fresh_queries, merge_history
from test_parallel_sources import task, finish
from test_source_strategy import claim_next, round_result


def test_invalid_local_metadata_cannot_starve_fresh_external_search(tmp_path, monkeypatch):
    """No network attempted, but inspected invalid metadata must consume its URL."""
    from hotpost import source_finder as sf
    from hotpost.source_search import library
    from hotpost.source_search.triage import discovery_duration_reasons
    studio, tid, folder = task(tmp_path)
    url = 'https://www.youtube.com/watch?v=metadata-no-duration'
    external = []
    monkeypatch.setattr(library, 'discover', lambda *args: [Candidate(
        url=url, provider='youtube', discovery_meta={'duration':0})])
    def search(provider):
        def invoke(queries, limit, audit, *args):
            external.extend((provider, q) for q in queries)
            audit.extend({'provider':provider, 'query':q, 'status':'no_results'} for q in queries)
            return []
        return invoke
    services = SimpleNamespace(search_local_cache=lambda *a:[], search_local_hints=lambda *a:[],
        _clean_visual_terms=lambda x:x, Candidate=Candidate,
        search_web=search('duckduckgo'), search_bing=search('bing'),
        search_youtube=lambda qs,n,cookies,audit,runtime:search('youtube')(qs,n,audit),
        search_pexels=lambda settings,qs,n,audit:search('pexels')(qs,n,audit))
    studio.settings.source_browser_search = False
    def collect(settings, code, progress, **options):
        candidates, queries, browser, audit, _ = discover(settings,code,[],['mirror'],
            {'products':[]},[],folder,options['previous_searches'],options['exclude_urls'],
            progress,services)
        for candidate in candidates:
            candidate.rejection_reasons = discovery_duration_reasons(candidate, 180)
            assert candidate.rejection_reasons == ['invalid_duration']
            candidate.download_attempted = False
        raw = {'zip_path':str(folder/'sources.zip'), 'search_audit':audit,
            'candidates':[asdict(c) for c in candidates], 'source_policy':settings.source_policy
            if hasattr(settings,'source_policy') else None}
        (folder/'manifest.json').write_text(json.dumps(raw), encoding='utf-8')
        return raw
    monkeypatch.setattr(sf, 'find_sources', collect)
    monkeypatch.setattr(sf, 'extract_frames', lambda *a, **k:[])
    monkeypatch.setattr(sf, 'probe_video', lambda *a:{'duration':30})
    first = claim_next(studio,tid)
    result = studio._collect_source_attempt(studio.store.get(tid), first)
    assert result['attempted_urls'] == []
    finish(studio,first,result)
    before = studio.store.get(tid)['source_acquisition']
    assert not external
    # Network accounting remains zero; inspection prevents the same rejected URL
    # monopolizing the next round, while actual new searches remain authorized.
    assert url in [*before.get('urls',[]), *before.get('inspected_urls',[])]
    second = claim_next(studio,tid)
    result = studio._collect_source_attempt(studio.store.get(tid), second)
    finish(studio,second,result)
    assert ('youtube','mirror') in external
    assert len(studio.store.get(tid)['source_acquisition']['rounds']) == 2


def test_service_wait_recover_preserves_failure_history_and_fences_all_late_writes(tmp_path):
    studio, tid, _ = task(tmp_path)
    old = claim_next(studio,tid)
    # A previous completed search remains consumed across a service wait/restart.
    studio.store.change(tid,lambda s,db:s['source_acquisition'].update(
        queries=[{'provider':'youtube','query':'silver mirror','status':'no_results'}]))
    studio.store.checkpoint(old,{**old['checkpoint'],'request_id':1234})
    old['checkpoint']['request_id'] = 1234
    assert studio.store.defer(old,'model service recovery',0,waiting=True,
        waiting_status='retry_wait') is not False
    studio.store.recover()
    current = studio.store.claim('sources')
    assert current['id'] == old['id'] and current['claim_token'] != old['claim_token']
    assert current['checkpoint']['request_id'] == 1234
    before = copy.deepcopy(studio.store.get(tid))
    events = studio.store.events(tid)
    assert studio.store.finish(old,round_result(0),lambda s,db,r:studio._accept(s,old,r,db)) is False
    assert studio.store.fail(old,'late old worker failure') is False
    assert studio.store.defer(old,'late old worker heartbeat',0,waiting=True) is False
    with pytest.raises(StaleClaim):
        studio.store.checkpoint(old,{'request_id':1})
    with pytest.raises(StaleClaim):
        change_claimed(studio.store,old,lambda s,db:s.update(status='completed'))
    assert studio.store.get(tid) == before and studio.store.events(tid) == events
    finish(studio,current,round_result(0, searches=[
        {'provider':'youtube','query':'silver mirror','status':'service_wait'}]))
    final = studio.store.get(tid)
    assert fresh_queries(['silver mirror'],'youtube',final['source_acquisition']['queries']) == []
    assert final.get('daily_quality',{}).get('repair_round',0) == 0


def test_fresh_scope_survives_old_failures_but_date_and_word_spacing_do_not():
    history = merge_history([{'provider':'youtube','query':'Silver Mirror','status':'no_results',
        'search_scope':{'page':1}, 'job_id':'old', 'date':'2026-10-13'}])
    assert fresh_queries(['  SILVER  MIRROR  '],'youtube',history) == []
    assert fresh_queries(['silver mirror'],'youtube',history,scope={'page':2}) == ['silver mirror']
    assert fresh_queries(['silver mirror'],'tiktok',history) == ['silver mirror']
    assert fresh_queries(['gold mirror'],'youtube',history) == ['gold mirror']
    for status in ('captcha','rate_limited','service_wait','browser_busy','connection_failed'):
        waiting = merge_history([{'provider':'youtube','query':'gold mirror','status':status,'requests':1}])
        assert fresh_queries(['gold mirror'],'youtube',waiting) == ['gold mirror']


def test_restart_migration_consumes_old_inspection_without_spending_access_waits(tmp_path):
    from hotpost.source_search.strategy import restore_history
    old_manifest=tmp_path/'old-manifest.json'
    candidates=[
        {'url':'https://www.youtube.com/watch?v=invalid','download_attempted':False,
            'rejection_reasons':['invalid_duration']},
        {'url':'https://www.youtube.com/watch?v=later','download_attempted':False,
            'rejection_reasons':['platform_budget_exhausted']},
        {'url':'https://www.tiktok.com/@p/video/123','platform':'tiktok',
            'download_attempted':False,'error':'HTTP 429 Too Many Requests',
            'rejection_reasons':['download_failed']},
        {'url':'https://www.youtube.com/watch?v=user-stopped','download_attempted':False,
            'rejection_reasons':['platform_disabled']}]
    old_manifest.write_text(json.dumps({'candidates':candidates}))
    before=old_manifest.read_bytes()
    # Search schema may already be migrated; inspection migration must still run.
    record={'strategy_version':2,'queries':[{'provider':'youtube','query':'mirror','status':'no_results'}],
        'urls':[],'rounds':[{'manifest_path':str(old_manifest)}]}
    history=copy.deepcopy(record['queries'])
    restore_history(record)
    assert record['queries']==history and record['urls']==[]
    assert record['inspected_urls']==['https://www.youtube.com/watch?v=invalid']
    once=copy.deepcopy(record)
    old_manifest.unlink()
    restore_history(record)
    assert record==once  # Missing old receipt never erases already restored history.
    assert before


def test_stale_partial_review_file_cannot_replace_current_generation(tmp_path):
    from hotpost.source_quality import sha256_file
    studio,tid,folder = task(tmp_path)
    old = claim_next(studio,tid)
    base = folder/'review-checkpoint.json'
    base.write_text(json.dumps({'input_key':'real-input','sources':{}}))
    old['checkpoint']['source_visual_review'] = {'input_key':'real-input',
        'path':str(base),'sha256':sha256_file(base)}
    studio.store.checkpoint(old,old['checkpoint'])
    studio.store.recover()
    current = studio.store.claim('sources')
    studio._checkpoint_deferred_review(current,{'sha256':'new-source','path':'new.mp4'})
    live = Path(current['checkpoint']['source_visual_review']['path'])
    before = live.read_bytes()
    with pytest.raises(StaleClaim):
        studio._checkpoint_deferred_review(old,{'sha256':'old-source','path':'old.mp4'})
    assert live.read_bytes() == before
    assert 'old-source' not in json.loads(live.read_text())['sources']
    with studio.store.connect() as db:
        durable=json.loads(db.execute('SELECT checkpoint FROM jobs WHERE id=?',(current['id'],)).fetchone()[0])
    assert durable['source_visual_review']['path'] == str(live.resolve())


def test_browser_worker_partial_results_retained_but_message_heartbeats_expire(tmp_path):
    from hotpost.source_browser_worker import run_bounded
    checkpoint = tmp_path/'checkpoint.json'
    script = '''import json,sys,time
from pathlib import Path
payload=json.load(sys.stdin)
p=Path(payload['checkpoint'])
for i in range(100):
 p.write_text(json.dumps({'message':'heartbeat '+str(i), 'candidates':[{'url':'saved'}],
  'searches':[{'provider':'youtube','query':'mirror','status':'no_results','candidates':0}]}))
 time.sleep(.1)
'''
    result=run_bounded([sys.executable,'-c',script],{'checkpoint':str(checkpoint)},checkpoint,1)
    assert result['candidates'] == [{'url':'saved'}]
    assert any(row['provider']=='browser-worker' and row['status']=='timeout' for row in result['searches'])


def test_old_edit_worker_cannot_overwrite_current_request_before_claim_check(tmp_path, monkeypatch):
    """Durable SQLite fencing must happen before mutable shared runner files."""
    from hotpost.studio_runtime import editing
    studio,tid,folder=task(tmp_path)
    old=claim_next(studio,tid)
    studio.store.recover()
    current=studio.store.claim('sources')
    output=folder/current['id'];output.mkdir()
    request=output/'analyze-request.json'
    current_request={'action':'analyze','output_dir':str(output),'evidence':'current B'}
    request.write_text(json.dumps(current_request))
    before=request.read_bytes()
    launched=[]
    def forbid_launch(*args,**kwargs):
        launched.append(args)
        raise AssertionError('stale claim launched an external runner')
    monkeypatch.setattr(editing.subprocess,'Popen',forbid_launch)
    with pytest.raises(StaleClaim):
        studio._process(studio.store.get(tid),old,'analyze',{'evidence':'old A'})
    assert not launched
    assert request.read_bytes()==before


@pytest.mark.parametrize('receipt', ['wrong-full-request','missing'])
def test_late_result_from_previous_inputs_cannot_satisfy_current_edit(tmp_path, monkeypatch, receipt):
    """Real runner already signs full request; adapter must validate that receipt."""
    from hotpost.studio_runtime import editing
    studio,tid,folder=task(tmp_path)
    old=claim_next(studio,tid)
    studio.store.recover()
    current=studio.store.claim('sources')
    output=folder/current['id'];output.mkdir()
    payload={'evidence':'현재 제품 장면 B'}
    # The durable B checkpoint exists when a delayed A result reaches the same
    # output path. IDs and all artifact hashes remain valid; inputs differ.
    current['checkpoint']['analyze_input']=hashlib.sha256(
        json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    studio.store.checkpoint(current,current['checkpoint'])
    artifact=output/'old-A.jpg';artifact.write_bytes(b'old A actual image')
    result={'status':'completed','preview_path':str(artifact),
        '_artifact_hashes':{str(artifact):hashlib.sha256(artifact.read_bytes()).hexdigest()}}
    if receipt == 'wrong-full-request':
        previous_request={'action':'analyze','output_dir':str(output),'evidence':'이전 제품 장면 A'}
        result['request_sha256']=hashlib.sha256(json.dumps(previous_request,sort_keys=True).encode()).hexdigest()
    (output/'analyze-result.json').write_text(json.dumps(result))
    monkeypatch.setattr(editing.subprocess,'Popen',lambda *a,**k:pytest.fail(
        'unbound old result must be held for inspection before another render'))
    with pytest.raises(Conflict):
        studio._process(studio.store.get(tid),current,'analyze',payload)
    assert artifact.read_bytes()==b'old A actual image'


def test_current_full_request_receipt_with_korean_inputs_can_resume_without_runner(tmp_path, monkeypatch):
    from hotpost.studio_runtime import editing
    studio,tid,folder=task(tmp_path)
    current=claim_next(studio,tid)
    output=folder/current['id'];output.mkdir()
    payload={'evidence':'현재 제품 장면 B'}
    current['checkpoint']['analyze_input']=hashlib.sha256(
        json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    studio.store.checkpoint(current,current['checkpoint'])
    full={'action':'analyze','output_dir':str(output),**payload}
    result={'status':'completed','request_sha256':hashlib.sha256(
        json.dumps(full,sort_keys=True).encode()).hexdigest()}
    (output/'analyze-result.json').write_text(json.dumps(result))
    monkeypatch.setattr(editing.subprocess,'Popen',lambda *a,**k:pytest.fail('valid signed result was repeated'))
    assert studio._process(studio.store.get(tid),current,'analyze',payload)==result


@pytest.mark.parametrize('same_creation_time',[True,False])
def test_runner_reconnect_uses_process_creation_and_real_receipt(tmp_path,monkeypatch,same_creation_time):
    """Real local child: reconnect current PID, never reconnect a reused PID."""
    import psutil
    from hotpost.studio_runtime import editing
    from hotpost.editing_adapter import _atomic_json
    studio,tid,folder=task(tmp_path)
    current=claim_next(studio,tid)
    output=folder/current['id'];output.mkdir()
    request=output/'analyze-request.json';result_path=output/'analyze-result.json'
    payload={'evidence':'실제 로컬 child 영수증'}
    _atomic_json(request,{'action':'analyze','output_dir':str(output),**payload})
    code='''import hashlib,json,sys,time
from pathlib import Path
time.sleep(.6)
request=json.loads(Path(sys.argv[3]).read_text('utf-8'))
result={'status':'completed','request_sha256':hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()}
Path(sys.argv[5]).write_text(json.dumps(result),encoding='utf-8')
'''
    original_popen=subprocess.Popen
    def fixture_command(script):
        return [sys.executable,'-c',script,'auto_capcut.studio_runner','--request',str(request),
            '--result',str(result_path)]
    child=original_popen(fixture_command(code if same_creation_time else 'import time;time.sleep(20)'),
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    spawned=[]
    current['checkpoint'].update(analyze_pid=child.pid,
        analyze_process_created=psutil.Process(child.pid).create_time()+(0 if same_creation_time else 10),
        analyze_input=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest())
    studio.store.checkpoint(current,current['checkpoint'])
    def new_fixture(*args,**kwargs):
        if same_creation_time:pytest.fail('owned live process was launched twice')
        spawned.append(original_popen(fixture_command(code),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
        return spawned[-1]
    monkeypatch.setattr(editing.subprocess,'Popen',new_fixture)
    try:
        result=studio._process(studio.store.get(tid),current,'analyze',payload)
        assert result['status']=='completed'
        assert len(spawned)==(0 if same_creation_time else 1)
        if not same_creation_time:
            assert child.poll() is None  # Unrelated reused PID was neither joined nor killed.
    finally:
        for process in [child,*spawned]:
            if process.poll() is None:process.terminate()
            process.wait(timeout=5)


def test_real_default_legacy_adapter_uses_progress_watch_for_build_and_export(tmp_path,monkeypatch):
    from hotpost.config import Settings
    from hotpost.editing_adapter import AutoCapcutAdapter
    from hotpost import operation_progress
    repo=tmp_path/'renderer';(repo/'auto_capcut').mkdir(parents=True)
    (repo/'auto_capcut'/'job_runner.py').write_text('fixture')
    settings=Settings(data_dir=tmp_path,auto_capcut_root=repo,
        auto_capcut_python=Path(sys.executable),auto_capcut_timeout=3)
    asset=tmp_path/'source.mp4';asset.write_bytes(b'actual local source fixture')
    calls=[]
    def progress_runner(command,**options):
        calls.append(options)
        assert 'timeout' not in options
        request=Path(command[command.index('--request')+1])
        result=Path(command[command.index('--result')+1])
        value=json.loads(request.read_text('utf-8'))
        output={'status':'completed','job_id':value['job_id']}
        if 'export_runner' in command[command.index('-m')+1]:
            Path(value['output_path']).write_bytes(b'fixture'*300)
            output.update(verified=True)
        else:
            output['contract_version']=value['contract_version']
            assert options['env']['PYTHONUTF8']=='1'
        result.write_text(json.dumps(output))
        return subprocess.CompletedProcess(command,0,'','')
    monkeypatch.setattr(operation_progress,'run_progress_command',progress_runner)
    adapter=AutoCapcutAdapter(settings)  # Actual default branch, not injected runner.
    assert adapter.build(job_id='legacy-build',video_paths=[asset],draft_name='fixture')['status']=='completed'
    assert adapter.export(job_id='legacy-export',draft_name='fixture',draft_path=repo)['verified']
    assert [call['idle_seconds'] for call in calls]==[3,1500]


def test_worker_capacity_waits_after_old_retry_count_can_resume_without_content_charge(tmp_path,monkeypatch):
    """Actual worker dispatch/exception/defer, including old >=3 service history."""
    from hotpost.config import Settings
    from hotpost.studio import Studio
    from hotpost.model_service import ModelServiceUnavailable
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('capacity-loop','capacity-loop',prepare=False,
        initial={'script_id':'script','approved_script_id':'script','pending_voice_id':'voice'})
    tid=state['id'];output=studio.folder(tid)/'voice.wav';output.write_bytes(b'received fixture narration')
    with studio.store.transaction() as db:
        jobid=studio.store.enqueue(db,tid,'voice',{'script_id':'script','voice_id':'voice'},'voice:capacity')
    studio.store.checkpoint(jobid,{'service_retries':5,'request_id':2468})
    attempts=[]
    def work(current,job):
        studio.stop.set()  # Exercise exactly one actual worker dispatch each time.
        attempts.append(job['checkpoint'].get('request_id'))
        if len(attempts)<=5:
            raise ModelServiceUnavailable('existing service capacity wait',attempted=len(attempts)>1)
        return {'id':'voice','script_id':'script','path':str(output),
            'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'speed':1,'duration':1}
    monkeypatch.setattr(studio,'_voice',work)
    for index in range(6):
        studio.stop.clear()
        studio._worker('media')
        jobs=studio.store.jobs(tid)
        current=studio.store.get(tid)
        assert current.get('daily_quality',{}).get('repair_round',0)==0
        assert not current.get('error')
        if index<5:
            assert jobs[0]['status']=='queued'
            with studio.store.transaction() as db:
                checkpoint=json.loads(db.execute('SELECT checkpoint FROM jobs WHERE id=?',(jobid,)).fetchone()[0])
                checkpoint['not_before']=0
                db.execute('UPDATE jobs SET checkpoint=? WHERE id=?',(json.dumps(checkpoint),jobid))
        else:
            assert jobs[0]['status']=='done' and current['voice_id']=='voice'
    assert attempts==[2468]*6


def test_real_queue_handoffs_parallel_source_script_to_verified_completion_and_replay(tmp_path):
    """Real state contracts; supplied source/model/media receipts are fixtures."""
    from hotpost.config import Settings
    from hotpost.studio import Studio
    from hotpost.daily_quality import POLICY
    from test_parallel_sources import asset
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('whole-flow','whole-flow',{'protocol':2,'active':True,'stage':'prepare'},
        initial={'daily_quality':{'policy':POLICY,'status':'pending','repair_round':0,'reviews':[]}})
    tid=state['id'];root=studio.folder(tid)
    reference=root/'reference.mp4';reference.write_bytes(b'fixture reference')
    transcript=root/'transcript.json';transcript.write_text('{"speech":[{"text":"fixture"}]}')
    manifest=root/'manifest.json';manifest.write_text('{"candidates":[]}')
    def accept(job,value):
        assert studio.store.finish(job,value,lambda s,db,r:studio._accept(s,job,r,db))
    prepare=studio.store.claim('media');assert prepare['kind']=='prepare'
    accept(prepare,{'original_text':'실제 제품을 보여주는 원문','reference_video':str(reference),
        'reference_duration':4,'transcript_path':str(transcript),'manifest_path':str(manifest),'sources':[]})
    source=studio.store.claim('sources');script=studio.store.claim('scripts')
    assert source['kind']=='collect_sources' and script['kind']=='rewrite'
    accept(script,{'text':'제품이 자연스럽게 등장해요. 댓글에 ‘나도’ 남겨주세요.',
        'script_candidates':[{'text':str(i)} for i in range(3)],'selected_candidate':1})
    voice=studio.store.claim('media');assert voice['kind']=='voice'
    assert voice['payload']['voice_mode']=='personal_clone'
    accept(source,round_result(0,[asset(root,1,core=True),asset(root,2)],
        [{'provider':'youtube','query':'mirror','status':'results','candidates':2}]))
    voicefile=root/'voice.wav';voicefile.write_bytes(b'fixture approved narration')
    accept(voice,{'id':voice['payload']['voice_id'],'script_id':voice['payload']['script_id'],
        'path':str(voicefile),'sha256':hashlib.sha256(voicefile.read_bytes()).hexdigest(),'duration':4,'speed':1})
    editjob=studio.store.claim('media');assert editjob['kind']=='edit'
    assert len(editjob['payload']['source_ids'])==2
    video=root/'complete.mp4';video.write_bytes(b'fixture rendered output')
    plan=root/'complete-plan.json';plan.write_text(json.dumps({'script_text':'제품이 자연스럽게 등장해요.',
        'beats':[{'id':'beat','text':'제품이 자연스럽게 등장해요.'}]}))
    accept(editjob,{'id':editjob['id'],'script_id':editjob['payload']['script_id'],
        'voice_id':editjob['payload']['voice_id'],'preview_path':str(video),'plan_path':str(plan),'duration':4})
    review=studio.store.claim('media');assert review['kind']=='quality_review'
    assert studio.store.get(tid)['status']!='completed'
    accept(review,{'edit_id':editjob['id'],'passed':True,'issues':[],'review_path':'fixture-review.json',
        'policy':POLICY,'render_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),
        'plan_sha256':hashlib.sha256(plan.read_bytes()).hexdigest()})
    complete=studio.store.get(tid)
    assert complete['status']=='completed' and complete['daily_quality']['repair_round']==0
    assert complete['edits'][0]['export_path']==str(video) and complete['edits'][0]['quality_verified']
    assert studio.store.finish(review,{},lambda s,db,r:s.update(status='editing')) is False
    studio.store.recover()
    assert studio.store.claim('media') is None and studio.store.claim('sources') is None
    assert studio.store.get(tid)==complete
