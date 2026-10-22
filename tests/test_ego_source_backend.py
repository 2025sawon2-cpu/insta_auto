import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace
import pytest
from hotpost import ego_source_backend as ego
from hotpost.config import Settings
from hotpost.source_access_preflight import SourceAccessWaiting

TASK='work-93c36341bdac46b4'
LIVE=Path('C:/Codex/인스타자동화/insta_auto')


@pytest.fixture
def configured(tmp_path):
    path=tmp_path/'binding.json'
    path.write_text(json.dumps({'spaceId':6,'authorizedTaskIds':[TASK],
                               'pages':{'tiktok':'p1','bilibili':'p2','youtube':'p3'}}),'utf-8')
    s=Settings(data_dir=tmp_path/'data',source_ego_binding=str(path))
    s.source_dir.mkdir(parents=True)
    return s


def scoped(settings, task=TASK):
    return ego._OWNER.set((settings,{'task_id':task,'job_id':'job-test','run_id':'run-test'}))


@pytest.mark.parametrize('task',[None,'work-other',''])
def test_scope_denied_before_any_transport(configured,monkeypatch,task):
    monkeypatch.setattr(ego,'_invoke',lambda *a,**k:pytest.fail('unscoped transport'))
    with pytest.raises(SourceAccessWaiting):ego.current_routes(configured,['tiktok'],task)


def test_preflight_uses_ego_without_chrome_and_marks_unsupported(configured,monkeypatch):
    from hotpost import source_access_preflight as native,source_browser_runtime as old
    monkeypatch.setattr(old,'endpoint',lambda *a:pytest.fail('legacy Chrome touched'))
    monkeypatch.setattr(ego,'_invoke',lambda *a,**k:{'routes':{'tiktok':{'status':'ready','reason':'ego_current_page_observed'}}})
    rows=native.current_routes(configured,['tiktok','bilibili','youtube'],task_id=TASK)
    assert [r['status'] for r in rows]==['ready','not_attempted','not_attempted']
    assert not any(r['attempted'] for r in rows)


@pytest.mark.parametrize('status',['captcha_review_pending','login_required','rate_limited'])
def test_actual_access_failure_retained_and_never_ready(configured,monkeypatch,status):
    monkeypatch.setattr(ego,'_invoke',lambda *a,**k:{'routes':{'tiktok':{'status':status,'reason':'test_capture','screenshot':'capture.png'}}})
    rows=ego.current_routes(configured,['tiktok'],TASK)
    assert rows[0]['status']!='ready'
    saved=json.loads((configured.data_dir/'search_cooldowns/tiktok.json').read_text('utf-8'))
    assert saved['reason']==status and saved['ego_evidence']['screenshot']=='capture.png'


def test_saved_captcha_is_not_cleared_by_ready_page(configured,monkeypatch):
    p=configured.data_dir/'search_cooldowns/tiktok.json';p.parent.mkdir(parents=True)
    p.write_text(json.dumps({'reason':'captcha','requires_verification':True}),'utf-8')
    original=p.read_bytes()
    monkeypatch.setattr(ego,'_invoke',lambda *a,**k:{'routes':{'tiktok':{'status':'ready'}}})
    assert ego.current_routes(configured,['tiktok'],TASK)[0]['status']=='verification_required'
    assert p.read_bytes()==original


def test_owner_decorator_blocks_missing_binding_and_indexed_fallback(configured):
    called=[]
    @ego.owner_bound
    def operation(settings,*args,**kwargs):called.append(True);return 1
    with pytest.raises(SourceAccessWaiting):operation(configured,'code')
    configured.source_browser_search=False
    with pytest.raises(SourceAccessWaiting):operation(configured,'code',search_context={'task_id':TASK,'job_id':'j','run_id':'r'})
    assert not called


def test_disabled_backend_preserves_original_worker_path(tmp_path,monkeypatch):
    from hotpost import source_browser_worker as worker, source_browser_runtime as old
    s=Settings(data_dir=tmp_path)
    monkeypatch.setattr(old,'endpoint',lambda *a:'unchanged-legacy-endpoint')
    monkeypatch.setattr(worker,'run_bounded',lambda *a,**k:{'legacy_path':True})
    monkeypatch.setattr(ego,'search',lambda *a,**k:pytest.fail('ego called while disabled'))
    assert worker.isolated_search(s,[],[],1,tmp_path)['legacy_path']


def test_search_receipt_is_real_submission_and_preserves_worker_hooks(configured,tmp_path,monkeypatch):
    from hotpost import source_browser_worker as worker
    from hotpost.source_attempts import search_execution
    captured=[];registered=[];settled=[]
    def transport(settings,task,operation,**kw):
        assert task==TASK and operation=='search'
        captured.append(kw['query'])
        return {'status':'results','execution':{'query_submitted':True,'query_url_matched':True,
                'input_value':kw['query'],'result_url':'https://www.tiktok.com/search?q='+kw['query']},
                'result_method':'ego_visible_search_cards',
                'candidates':[{'url':'https://www.tiktok.com/@test/video/1234567890123456789','title':'untrusted card'}]}
    monkeypatch.setattr(ego,'_invoke',transport)
    progress=lambda *args:None
    progress.source_worker_checkpoint=registered.append;progress.source_worker_settled=settled.append
    token=scoped(configured)
    try:
        result=worker.isolated_search(configured,[],['running leg warmers'],10,tmp_path/'browser_debug',
                    routes=['tiktok','youtube'],progress=progress)
    finally:ego._OWNER.reset(token)
    assert captured==['running leg warmers']
    assert registered==settled and len(registered)==1
    assert registered[0].name.startswith('search-checkpoint-')
    assert json.loads(registered[0].read_text('utf-8'))['candidates']==result['candidates']
    assert search_execution(result['searches'][0])['query_submitted']
    assert result['searches'][1]['status']=='not_attempted'


def test_consumed_query_not_repeated_and_long_query_not_sent(configured,tmp_path,monkeypatch):
    monkeypatch.setattr(ego,'_invoke',lambda *a,**k:pytest.fail('used/long query resubmitted'))
    token=scoped(configured)
    try:
        prior=[{'provider':'tiktok','query':'running leg warmers','language':'en','status':'results',
                'execution':{'query_submitted':True,'query_url_matched':True},'result_method':'ego_visible_search_cards'}]
        result=ego.search(configured,['running leg warmers'],10,tmp_path/'browser_debug',prior,routes=['tiktok'])
        assert not result['candidates']
        try:ego.search(configured,['one two three four five six seven eight nine ten eleven twelve'],10,tmp_path/'long',routes=['tiktok'])
        except SourceAccessWaiting:pass
    finally:ego._OWNER.reset(token)


def test_download_ego_only_then_normal_native_probe_chain(configured,tmp_path,monkeypatch):
    from hotpost import source_finder as finder
    candidate=finder.Candidate(url='https://www.tiktok.com/@test/video/1234567890123456789',provider='ego-tiktok')
    received=b'\0\0\0\x18ftyp'+b'mp42'+b'isolated fake bytes; native decoder has not approved this'
    def transport(settings,task,operation,**kwargs):
        assert operation=='download';Path(kwargs['target']).write_bytes(received)
        return {'status':'received','attempted':True,'navigation_started':True,'bytes':len(received),
                'meta':{'id':'1234567890123456789','source_url':candidate.url},
                'sha256':hashlib.sha256(received).hexdigest()}
    monkeypatch.setattr(ego,'_invoke',transport)
    monkeypatch.setattr(finder,'probe_video',lambda *a:pytest.fail('no cache probe expected'))
    monkeypatch.setattr(finder,'SOURCE_COOLDOWNS',{})
    monkeypatch.setattr('hotpost.source_collection_access.collection_disabled',lambda *a,**k:False)
    target_dir=configured.source_dir/'code-123/videos';target_dir.mkdir(parents=True)
    token=scoped(configured)
    try:path=finder.download_candidate(candidate,target_dir,1,1)
    finally:ego._OWNER.reset(token)
    assert path.read_bytes()==received and candidate.download_attempted is True
    assert candidate.selected_for_zip is False and candidate.source_quality=='unknown'
    assert candidate.acquisition=='existing-browser-playback'


def test_transport_unknown_completion_blocks_replay(configured,monkeypatch):
    monkeypatch.setattr(ego.shutil,'which',lambda *a:'isolated-ego-exe')
    calls=[]
    def failed(*a,**k):calls.append(a);raise OSError('isolated transport failure')
    monkeypatch.setattr(ego.subprocess,'Popen',failed)
    with pytest.raises(SourceAccessWaiting):ego._invoke(configured,TASK,'observe',providers=['tiktok'])
    with pytest.raises(SourceAccessWaiting):ego._invoke(configured,TASK,'observe',providers=['tiktok'])
    assert len(calls)==1


def test_preserved_queued_running_task_collect_entry_reaches_external_acquisition(tmp_path,monkeypatch):
    """Read actual bound originals; only isolated state/job writes and CLI I/O doubles."""
    from hotpost import source_finder, studio_store
    from hotpost.studio_sources import SourceAcquisitionMixin
    from test_source_parser_response_incident import transactional_store
    db=sqlite3.connect((LIVE/'data/studio/studio.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    state=json.loads(db.execute('select state from tasks where id=?',(TASK,)).fetchone()[0])
    raw=dict(db.execute('select * from jobs where id=?',('job-6c9319fecf3f4fa9',)).fetchone());db.close()
    assert raw['status']=='queued', 'Integration snapshot requires the original queued claim, never SQL force-running'
    job={**raw,'payload':json.loads(raw['payload']),'checkpoint':json.loads(raw['checkpoint'])}
    original=copy.deepcopy(job)
    bundle=json.loads(Path(job['checkpoint']['planning_preparation']['path']).read_text('utf-8'))
    s=Settings(data_dir=LIVE/'data')
    binding_path=tmp_path/'ego-binding.json';binding_path.write_text(json.dumps({'spaceId':6,'authorizedTaskIds':[TASK],'pages':{'tiktok':'p1'}}),'utf-8')
    s.source_ego_binding=str(binding_path)
    caption=bundle['query_plan']['visual_query_evidence']['evidence']['text']['caption']
    monkeypatch.setattr(source_finder,'_post',lambda *a,**k:SimpleNamespace(caption=caption))
    # Keep actual native transcript reading: replanning bundle screen_text is not
    # the original source transcription used by its immutable evidence_key.
    monkeypatch.setattr(ego,'_invoke',lambda *a,**k:{'routes':{'tiktok':{'status':'ready','reason':'ego_current_page_observed'}}})
    # The human's explicit restart permits the normal one-time readiness
    # recheck. Preserve/copy that external state; do not write the live record.
    from hotpost.source_search import readiness
    read_record=readiness.readiness_record
    saved_path=LIVE/'data/search_readiness/tiktok.json'
    saved_bytes=saved_path.read_bytes()
    isolated_readiness=tmp_path/'access-state/search_readiness/tiktok.json'
    isolated_readiness.parent.mkdir(parents=True)
    isolated_readiness.write_bytes(saved_bytes)
    assert readiness.request_readiness_recheck(tmp_path/'access-state','tiktok')
    monkeypatch.setattr(readiness,'readiness_record',lambda data_dir,provider:read_record(tmp_path/'access-state',provider))
    # Pure external acquisition stop; all internal history/preparation/identity/access validators run.
    class AcquisitionReached(RuntimeError):pass
    calls=[]
    def boundary(settings,code,progress,**kwargs):
        context=kwargs['search_context'];calls.append(context)
        assert context['task_id']==TASK and context['job_id']==job['id'] and context['run_id']==state['run_id']
        assert 'tiktok' in context['ready_routes']
        assert context['planning_preparation']==original['checkpoint']['planning_preparation']
        raise AcquisitionReached()
    monkeypatch.setattr(source_finder,'find_sources',boundary)
    store=transactional_store(state,job,tmp_path)
    # Advance wall clock past its preserved normal not_before; actual claim does the state transition.
    fixed=max(time.time(),job['checkpoint'].get('not_before',0)+1)
    monkeypatch.setattr(studio_store.time,'time',lambda:fixed)
    claimed=store.claim('sources',task_id=TASK,job_id=job['id'])
    assert claimed and claimed['id']==original['id']
    owner=SourceAcquisitionMixin();owner.settings=s;owner.store=store
    with pytest.raises(AcquisitionReached):owner._collect_sources(store.get(TASK),claimed)
    assert len(calls)==1
    current=store.get(TASK)
    assert not current['sources'] and not current['edits']
    assert current['run_id']==state['run_id']
    assert saved_path.read_bytes()==saved_bytes


@pytest.mark.parametrize('status,returncode,late',[('started',0,False),('received',2,False),('browser_busy',0,True)])
def test_nonfinal_nonzero_late_result_never_clears_pending(configured,monkeypatch,status,returncode,late):
    monkeypatch.setattr(ego.shutil,'which',lambda *a:'isolated-ego-exe')
    calls=[]
    def launch(*a,**k):
        calls.append(a)
        reqpath=next((configured.data_dir/'ego_transport/space6').glob('*/request.json'))
        req=json.loads(reqpath.read_text('utf-8'))
        result={'task_id':TASK,'spaceId':6,'status':status,'mayHaveLateEffects':late,
                'bridge_sha256':req['bridge_sha256'],'owner_context':req['owner_context']}
        Path(req['result_path']).write_text(json.dumps(result),'utf-8')
        return SimpleNamespace(poll=lambda:returncode,returncode=returncode)
    monkeypatch.setattr(ego.subprocess,'Popen',launch)
    with pytest.raises(SourceAccessWaiting):ego._invoke(configured,TASK,'observe',providers=['tiktok'])
    with pytest.raises(SourceAccessWaiting):ego._invoke(configured,TASK,'observe',providers=['tiktok'])
    assert len(calls)==1


@pytest.mark.parametrize('status',['user_control','space_unavailable'])
def test_user_control_and_missing_space_halt_same_binding(configured,monkeypatch,status):
    monkeypatch.setattr(ego.shutil,'which',lambda *a:'isolated-ego-exe')
    calls=[]
    def launch(*a,**k):
        calls.append(a);reqpath=next((configured.data_dir/'ego_transport/space6').glob('*/request.json'))
        req=json.loads(reqpath.read_text('utf-8'))
        Path(req['result_path']).write_text(json.dumps({'task_id':TASK,'spaceId':6,'status':status,
            'bridge_sha256':req['bridge_sha256'],'owner_context':req['owner_context']}),'utf-8')
        return SimpleNamespace(poll=lambda:0,returncode=0)
    monkeypatch.setattr(ego.subprocess,'Popen',launch)
    assert ego._invoke(configured,TASK,'observe',providers=['tiktok'])['status']==status
    with pytest.raises(SourceAccessWaiting):ego._invoke(configured,TASK,'observe',providers=['tiktok'])
    assert len(calls)==1


def test_pause_terminates_only_owned_cli_and_prevents_replay(configured,monkeypatch):
    from hotpost.studio_pause import StudioPaused
    monkeypatch.setattr(ego.shutil,'which',lambda *a:'isolated-ego-exe')
    state={'terminated':False,'launched':0}
    class Child:
        returncode=None
        def poll(self):return self.returncode
        def terminate(self):state['terminated']=True;self.returncode=-1
        def wait(self,timeout=None):return self.returncode
    def launch(*a,**k):state['launched']+=1;return Child()
    def cancel():
        if state['launched']:raise StudioPaused('isolated native user pause')
    monkeypatch.setattr(ego,'_cancel',cancel)
    monkeypatch.setattr(ego.subprocess,'Popen',launch)
    with pytest.raises(StudioPaused):ego._invoke(configured,TASK,'observe',providers=['tiktok'])
    with pytest.raises(SourceAccessWaiting):ego._invoke(configured,TASK,'observe',providers=['tiktok'])
    assert state=={'terminated':True,'launched':1}


def test_submitted_but_unresolved_search_blocks_new_keyword(configured,tmp_path,monkeypatch):
    calls=[]
    def transport(*a,**k):
        calls.append(k)
        return {'status':'browser_busy','reason':'query_url_mismatch',
                'execution':{'query_submitted':True,'query_url_matched':False}}
    monkeypatch.setattr(ego,'_invoke',transport)
    token=scoped(configured)
    try:
        with pytest.raises(SourceAccessWaiting):ego.search(configured,['running leg warmers'],10,tmp_path/'a',routes=['tiktok'])
        with pytest.raises(SourceAccessWaiting):ego.search(configured,['winter thigh warmers'],10,tmp_path/'b',routes=['tiktok'])
    finally:ego._OWNER.reset(token)
    assert len(calls)==1
    saved=json.loads((configured.data_dir/'search_readiness/tiktok.json').read_text('utf-8'))
    assert saved['parser_revision']=='ego-visible-search-v1' and saved['recheck_requested'] is False


def test_download_sha_mismatch_and_existing_target_never_publish_or_overwrite(configured,monkeypatch):
    from hotpost.source_search.models import Candidate
    p=configured.source_dir/'code-1/videos/video.mp4';p.parent.mkdir(parents=True)
    candidate=Candidate(url='https://www.tiktok.com/@test/video/1234567890123456789',provider='ego-tiktok')
    def transport(*a,**k):
        Path(k['target']).write_bytes(b'\0\0\0\x18ftypmp42-isolated')
        return {'status':'received','sha256':'wrong','bytes':21,'attempted':True}
    monkeypatch.setattr(ego,'_invoke',transport)
    token=scoped(configured)
    try:
        with pytest.raises(SourceAccessWaiting):ego.download(candidate,p,1024)
        assert not p.exists()
        p.write_bytes(b'preserve current job file')
        monkeypatch.setattr(ego,'_invoke',lambda *a,**k:pytest.fail('existing target redownloaded'))
        with pytest.raises(SourceAccessWaiting):ego.download(candidate,p,1024)
        assert p.read_bytes()==b'preserve current job file'
    finally:ego._OWNER.reset(token)


def test_same_rate_evidence_does_not_extend_cooldown(configured):
    row={'status':'rate_limited','rate_event':'same-observed-response','retry_after':600}
    ego._retain_access(configured,'tiktok',row)
    path=configured.data_dir/'search_cooldowns/tiktok.json';original=path.read_bytes()
    ego._retain_access(configured,'tiktok',row)
    assert path.read_bytes()==original


def test_receipt_other_video_never_publishes(configured,monkeypatch):
    from hotpost.source_search.models import Candidate
    candidate=Candidate(url='https://www.tiktok.com/@test/video/1234567890123456789',provider='ego-tiktok')
    target=configured.source_dir/'code-1/videos/exact.mp4';target.parent.mkdir(parents=True)
    received=b'\0\0\0\x18ftypmp42-wrong-video'
    def transport(*a,**k):
        Path(k['target']).write_bytes(received)
        return {'status':'received','bytes':len(received),'sha256':hashlib.sha256(received).hexdigest(),
                'meta':{'id':'9876543210123456789','source_url':'https://www.tiktok.com/@other/video/9876543210123456789'}}
    monkeypatch.setattr(ego,'_invoke',transport)
    token=scoped(configured)
    try:
        with pytest.raises(SourceAccessWaiting):ego.download(candidate,target,1024)
        assert not target.exists()
    finally:ego._OWNER.reset(token)
