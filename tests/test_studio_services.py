from types import SimpleNamespace

import pytest
import requests

from hotpost.config import Settings
from hotpost.studio_services import ensure_local

@pytest.fixture(autouse=True)
def fake_voice_key(monkeypatch):
    from hotpost.voicebench_adapter import VoiceBenchAdapter
    monkeypatch.setattr(VoiceBenchAdapter, '_api_key', lambda self: 'fixture-key')


def test_healthy_service_is_not_restarted(tmp_path, monkeypatch):
    from hotpost import studio_services as service
    monkeypatch.setattr(service.requests, 'Session', lambda: SimpleNamespace(
        get=lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {'service':'VoiceBench External TTS API'})))
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: pytest.fail('must not restart'))
    ensure_local(Settings(data_dir=tmp_path, voicebench_url='http://127.0.0.1:18767'), 'voice')


def test_wrong_service_never_launches_over_occupied_port(tmp_path, monkeypatch):
    from hotpost import studio_services as service
    monkeypatch.setattr(service.requests, 'Session', lambda: SimpleNamespace(
        get=lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {'service':'other-app'})))
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: pytest.fail('must not launch'))
    with pytest.raises(RuntimeError, match='설정'):
        ensure_local(Settings(data_dir=tmp_path), 'voice')


def test_remote_deployment_is_not_started_locally(monkeypatch):
    from hotpost import studio_services as service
    monkeypatch.setattr(service.requests, 'Session', lambda: pytest.fail('not a local service'))
    ensure_local(Settings(voicebench_url='http://10.9.0.20:18765'), 'voice')


def test_local_voice_launch_uses_own_environment(tmp_path, monkeypatch):
    from hotpost import studio_services as service
    root=tmp_path/'VoiceBench'
    python=root/'.venv'/('Scripts/python.exe' if service.os.name=='nt' else 'bin/python')
    python.parent.mkdir(parents=True); python.touch()
    attempts=[]; launches=[]
    def get(*a, **k):
        attempts.append(1)
        if len(attempts)<=2: raise requests.ConnectionError()
        if len(attempts)==3: raise requests.ReadTimeout()
        return SimpleNamespace(status_code=200, json=lambda: {'service':'VoiceBench External TTS API'})
    monkeypatch.setattr(service.requests, 'Session', lambda: SimpleNamespace(get=get))
    monkeypatch.setattr(service.subprocess, 'Popen', lambda args,**kwargs: launches.append((args,kwargs)) or SimpleNamespace(pid=1718,poll=lambda:None))
    monkeypatch.setattr(service.psutil,'Process',lambda pid:SimpleNamespace(create_time=lambda:123.0,
        is_running=lambda:True,cmdline=lambda:launches[0][0],cwd=lambda:str(root)))
    monkeypatch.setattr(service.time, 'sleep', lambda _: None)
    ensure_local(Settings(data_dir=tmp_path, voicebench_root=root, voicebench_url='http://127.0.0.1:18767'), 'voice')
    args,kwargs=launches[0]
    assert args[0]==str(python) and args[-1]=='18767' and 'voicebench' in args
    assert kwargs['cwd']==root
    assert len(launches)==1 and len(attempts)==4


def test_slow_existing_service_is_awaited_without_duplicate_launch(tmp_path, monkeypatch):
    from hotpost import studio_services as service
    attempts=[]
    def get(*a, **k):
        attempts.append(1)
        if len(attempts)==1: raise requests.ReadTimeout()
        return SimpleNamespace(status_code=200, json=lambda: {'service':'VoiceBench External TTS API'})
    monkeypatch.setattr(service.requests, 'Session', lambda: SimpleNamespace(get=get))
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: pytest.fail('must not launch a duplicate'))
    ensure_local(Settings(data_dir=tmp_path), 'voice')
    assert len(attempts)==2


def test_unresponsive_service_stops_after_bounded_wait(tmp_path, monkeypatch):
    from hotpost import studio_services as service
    def get(*a, **k): raise requests.ReadTimeout()
    ticks=iter([0, 1, 61])
    monkeypatch.setattr(service.requests, 'Session', lambda: SimpleNamespace(get=get))
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: pytest.fail('must not launch a duplicate'))
    monkeypatch.setattr(service.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(service.time, 'sleep', lambda _: None)
    from hotpost.model_service import ModelServiceUnavailable
    with pytest.raises(ModelServiceUnavailable, match='제한 시간') as wait:
        ensure_local(Settings(data_dir=tmp_path), 'voice')
    assert wait.value.attempted is False


def test_script_checks_cli_without_external_service(tmp_path,monkeypatch):
    from hotpost import studio_services as service
    from hotpost.writing import codex_writer
    monkeypatch.setattr(codex_writer, 'executable', lambda: 'codex.exe')
    monkeypatch.setattr(service.requests, 'Session', lambda: pytest.fail('external service'))
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: pytest.fail('legacy service'))
    ensure_local(Settings(data_dir=tmp_path), 'script')


def startup_fixture(tmp_path, monkeypatch):
    from hotpost import studio_services as service
    root=tmp_path/'VoiceBench'
    python=root/'.venv'/('Scripts/python.exe' if service.os.name=='nt' else 'bin/python')
    python.parent.mkdir(parents=True);python.touch()
    data=tmp_path/'client-data';data.mkdir()
    settings=Settings(data_dir=data,voicebench_root=root,voicebench_url='http://127.0.0.1:18767')
    processes={};launches=[]
    def launch(command,**kwargs):
        pid=1718+len(launches);launches.append((command,kwargs))
        processes[pid]=SimpleNamespace(is_running=lambda:True,create_time=lambda:123.0,
            cmdline=lambda:list(command),cwd=lambda:str(root))
        return SimpleNamespace(pid=pid,poll=lambda:None)
    monkeypatch.setattr(service.subprocess,'Popen',launch)
    monkeypatch.setattr(service.psutil,'Process',lambda pid:processes[pid])
    return settings, processes, launches, launch


def test_live_cold_child_is_preserved_across_clients_without_second_launch(tmp_path, monkeypatch):
    import json
    from dataclasses import replace
    from hotpost import studio_services as service
    from hotpost.model_service import ModelServiceUnavailable
    settings,processes,launches,_=startup_fixture(tmp_path,monkeypatch)
    def refused(*a,**k):raise requests.ConnectionError()
    monkeypatch.setattr(service.requests,'Session',lambda:SimpleNamespace(get=refused))
    clock=[0];monkeypatch.setattr(service.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(service.time,'sleep',lambda _:clock.__setitem__(0,clock[0]+1))
    with pytest.raises(ModelServiceUnavailable) as first:
        ensure_local(settings,'voice')
    assert not first.value.attempted and clock[0]==60 and len(launches)==1
    other_data=tmp_path/'second-client';other_data.mkdir()
    with pytest.raises(ModelServiceUnavailable) as second:
        ensure_local(replace(settings,data_dir=other_data),'voice')
    assert not second.value.attempted and len(launches)==1
    receipt=(settings.voicebench_root/'.runtime'/'hotpost-startup-18767.json').read_text('utf-8')
    assert 'fixture-key' not in receipt and 'EXTERNAL_API_KEY' not in receipt
    value=json.loads(receipt)
    assert value['pid']==1718 and value['process_created']==123.0


@pytest.mark.parametrize('changed',['created','command','cwd'])
def test_recycled_or_unrelated_pid_does_not_count_as_owned_cold_child(tmp_path, monkeypatch, changed):
    from hotpost import studio_services as service
    from hotpost.editing_adapter import _atomic_json
    settings,processes,launches,_=startup_fixture(tmp_path,monkeypatch)
    root=settings.voicebench_root
    command=[str(root/'.venv'/('Scripts/python.exe' if service.os.name=='nt' else 'bin/python')),
             '-X','utf8','-m','voicebench','--host','127.0.0.1','--port','18767']
    receipt=root/'.runtime'/'hotpost-startup-18767.json';receipt.parent.mkdir()
    _atomic_json(receipt,{'pid':777,'process_created':123.0,'command':command,'cwd':str(root)})
    processes[777]=SimpleNamespace(is_running=lambda:True,create_time=lambda:999.0 if changed=='created' else 123.0,
        cmdline=lambda:command+['unrelated'] if changed=='command' else command,
        cwd=lambda:str(tmp_path/'other') if changed=='cwd' else str(root))
    attempts=[]
    def get(*a,**k):
        attempts.append(1)
        if len(attempts)<=2:raise requests.ConnectionError()
        return SimpleNamespace(status_code=200,json=lambda:{'service':'VoiceBench External TTS API'})
    monkeypatch.setattr(service.requests,'Session',lambda:SimpleNamespace(get=get))
    ensure_local(settings,'voice')
    assert len(launches)==1

def test_two_initializers_use_one_os_startup_lease(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from hotpost import studio_services as service
    from hotpost.model_service import ModelServiceUnavailable
    settings,_,launches,launch=startup_fixture(tmp_path,monkeypatch)
    entering=Event();release=Event();healthy=[False]
    def slow_launch(command,**kwargs):
        entering.set()
        assert release.wait(3)
        child=launch(command,**kwargs);healthy[0]=True
        return child
    def get(*a,**k):
        if not healthy[0]:raise requests.ConnectionError()
        return SimpleNamespace(status_code=200,json=lambda:{'service':'VoiceBench External TTS API'})
    monkeypatch.setattr(service.subprocess,'Popen',slow_launch)
    monkeypatch.setattr(service.requests,'Session',lambda:SimpleNamespace(get=get))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(ensure_local,settings,'voice')
        assert entering.wait(2)
        try:
            second=pool.submit(ensure_local,settings,'voice')
            with pytest.raises(ModelServiceUnavailable) as waiting:second.result(timeout=2)
            assert not waiting.value.attempted
        finally:release.set()
        first.result(timeout=3)
    assert len(launches)==1


def test_missing_environment_remains_configuration_error(tmp_path,monkeypatch):
    from hotpost import studio_services as service
    from hotpost.model_service import ModelServiceUnavailable
    def refused(*a,**k):raise requests.ConnectionError()
    monkeypatch.setattr(service.requests,'Session',lambda:SimpleNamespace(get=refused))
    monkeypatch.setattr(service.subprocess,'Popen',lambda *a,**k:pytest.fail('missing environment must not launch'))
    with pytest.raises(RuntimeError,match='환경') as failure:
        ensure_local(Settings(data_dir=tmp_path,voicebench_root=tmp_path/'missing'),'voice')
    assert not isinstance(failure.value,ModelServiceUnavailable)


def test_confirmed_startup_exit_is_not_relaunched_on_each_retry(tmp_path,monkeypatch):
    from hotpost import studio_services as service
    from hotpost.model_service import ModelServiceUnavailable
    settings,_,launches,launch=startup_fixture(tmp_path,monkeypatch)
    def exited(command,**kwargs):
        child=launch(command,**kwargs)
        child.poll=lambda:2
        return child
    def refused(*a,**k):raise requests.ConnectionError()
    monkeypatch.setattr(service.subprocess,'Popen',exited)
    monkeypatch.setattr(service.requests,'Session',lambda:SimpleNamespace(get=refused))
    for _ in range(2):
        with pytest.raises(RuntimeError,match='종료') as failure:ensure_local(settings,'voice')
        assert not isinstance(failure.value,ModelServiceUnavailable)
    assert len(launches)==1


def test_starting_receipt_with_confirmed_dead_pid_is_configuration_hold(tmp_path,monkeypatch):
    import json
    from hotpost import studio_services as service
    from hotpost.editing_adapter import _atomic_json
    settings,_,launches,_=startup_fixture(tmp_path,monkeypatch)
    root=settings.voicebench_root
    command=[str(root/'.venv'/('Scripts/python.exe' if service.os.name=='nt' else 'bin/python')),
             '-X','utf8','-m','voicebench','--host','127.0.0.1','--port','18767']
    receipt=root/'.runtime'/'hotpost-startup-18767.json';receipt.parent.mkdir()
    _atomic_json(receipt,{'status':'starting','pid':777,'process_created':123.0,'command':command,'cwd':str(root)})
    def missing(pid):raise service.psutil.NoSuchProcess(pid)
    def refused(*a,**k):raise requests.ConnectionError()
    monkeypatch.setattr(service.psutil,'Process',missing)
    monkeypatch.setattr(service.requests,'Session',lambda:SimpleNamespace(get=refused))
    with pytest.raises(RuntimeError,match='직전 시작'):ensure_local(settings,'voice')
    assert not launches
    # A real healthy response clears a historical startup failure; time alone
    # cannot do that. This does not claim the old PID is still alive.
    monkeypatch.setattr(service.requests,'Session',lambda:SimpleNamespace(get=lambda *a,**k:SimpleNamespace(
        status_code=200,json=lambda:{'service':'VoiceBench External TTS API'})))
    ensure_local(settings,'voice')
    assert json.loads(receipt.read_text('utf-8'))['status']=='ready'


def test_four_actual_capacity_failures_then_unattempted_wait_can_resume_without_quality_charge(tmp_path,monkeypatch):
    import copy
    import threading
    from hotpost.studio_store import StudioStore
    from hotpost.studio_runtime.lifecycle import LifecycleMixin
    from hotpost.model_service import ModelServiceUnavailable
    from hotpost.daily_quality import POLICY
    from hotpost import studio_services as service
    clock=[1000.0]
    monkeypatch.setattr(service.time,'time',lambda:clock[0])
    store=StudioStore(tmp_path/'isolated-worker')
    task,_=store.create('capacity-phase','capacity',prepare=False,
        initial={'daily_quality':{'policy':POLICY,'repair_round':7,'render_accounting':[],
                                  'pending':'reediting','status':'repair','reviews':[]}})
    with store.transaction() as db:
        store.enqueue(db,task['id'],'quality_review',{},'capacity-review')
    before=copy.deepcopy(store.get(task['id'])['daily_quality'])
    calls=[]
    class Worker(LifecycleMixin):
        def _quality_review(self,state,job):
            calls.append(job['id'])
            if len(calls)<=5:
                raise ModelServiceUnavailable('shared capacity gate',retry_at=clock[0]+5,
                                              attempted=len(calls)<=4)
            return {'phase_succeeded':True}
        def _accept(self,state,job,result,db):
            state['status']='phase_succeeded';self.stop.set()
    worker=Worker();worker.store=store;worker.stop=threading.Event();worker.settings=Settings(data_dir=tmp_path)
    claim=store.claim
    def scoped_claim(*args,**kwargs):
        result=claim(*args,**kwargs)
        if result is None:worker.stop.set()
        return result
    monkeypatch.setattr(store,'claim',scoped_claim)
    for number in range(6):
        worker.stop.clear();worker._worker('media')
        assert store.get(task['id'])['daily_quality']==before
        if number<5:
            assert store.jobs(task['id'])[0]['status']=='queued'
            assert store.get(task['id'])['status']=='retry_wait'
        clock[0]+=10
    with store.connect() as db:
        row=db.execute('SELECT status,checkpoint FROM jobs').fetchone()
        import json
        assert row['status']=='done' and json.loads(row['checkpoint'])['service_retries']==4
    assert len(calls)==6 and len(set(calls))==1


@pytest.mark.parametrize('identity_error', ['exited', 'denied'])
def test_identity_failure_immediately_after_launch_is_durable_and_never_respawns(tmp_path, monkeypatch, identity_error):
    import json
    from hotpost import studio_services as service
    from hotpost.model_service import ModelServiceUnavailable
    settings, _, launches, _ = startup_fixture(tmp_path, monkeypatch)
    def refused(*args, **kwargs):
        raise requests.ConnectionError()
    def unavailable_identity(pid):
        if identity_error == 'exited':
            raise service.psutil.NoSuchProcess(pid)
        raise service.psutil.AccessDenied(pid)
    monkeypatch.setattr(service.requests, 'Session', lambda: SimpleNamespace(get=refused))
    monkeypatch.setattr(service.psutil, 'Process', unavailable_identity)
    for _ in range(2):
        with pytest.raises(RuntimeError) as failure:
            ensure_local(settings, 'voice')
        if identity_error == 'denied':
            assert isinstance(failure.value, ModelServiceUnavailable)
            assert not failure.value.attempted
        else:
            assert not isinstance(failure.value, ModelServiceUnavailable)
    assert len(launches) == 1
    receipt = json.loads((settings.voicebench_root/'.runtime'/'hotpost-startup-18767.json').read_text('utf-8'))
    assert receipt['status'] == ('failed' if identity_error == 'exited' else 'starting_unknown')
    assert receipt['process_created'] is None
    assert receipt['reason'] == ('exited_before_identity' if identity_error == 'exited' else 'process_identity_unconfirmed')
    assert 'fixture-key' not in json.dumps(receipt)


def test_authenticated_manual_recovery_resolves_failed_startup_and_allows_later_legitimate_start(tmp_path, monkeypatch):
    import json
    from hotpost import studio_services as service
    from hotpost.editing_adapter import _atomic_json
    settings, _, launches, _ = startup_fixture(tmp_path, monkeypatch)
    root=settings.voicebench_root
    command=[str(root/'.venv'/('Scripts/python.exe' if service.os.name=='nt' else 'bin/python')),
             '-X','utf8','-m','voicebench','--host','127.0.0.1','--port','18767']
    receipt=root/'.runtime'/'hotpost-startup-18767.json';receipt.parent.mkdir()
    _atomic_json(receipt,{'status':'failed','pid':777,'process_created':123.0,'command':command,
                         'cwd':str(root),'reason':'exited_before_identity','exit_code':2})
    healthy=[True]
    def get(*args,**kwargs):
        if not healthy[0]:raise requests.ConnectionError()
        return SimpleNamespace(status_code=200,json=lambda:{'service':'VoiceBench External TTS API'})
    monkeypatch.setattr(service.requests,'Session',lambda:SimpleNamespace(get=get))
    ensure_local(settings,'voice')
    saved=json.loads(receipt.read_text('utf-8'))
    assert saved['status']=='ready' and not launches
    assert saved['startup_failure_history'][0]['pid']==777
    assert saved['startup_failure_history'][0]['exit_code']==2
    healthy[0]=False
    # The old launch exited, then the manually restored service also stopped.
    # The historical failed identity is not an eternal launch prohibition.
    lookup=service.psutil.Process
    def processes(pid):
        if pid==777:raise service.psutil.NoSuchProcess(pid)
        return lookup(pid)
    monkeypatch.setattr(service.psutil,'Process',processes)
    launch=service.subprocess.Popen
    def start(command,**kwargs):
        child=launch(command,**kwargs);healthy[0]=True;return child
    monkeypatch.setattr(service.subprocess,'Popen',start)
    ensure_local(settings,'voice')
    assert len(launches)==1
    current=json.loads(receipt.read_text('utf-8'))
    assert current['status']=='ready' and current['pid']!=777
    assert current['startup_failure_history']==saved['startup_failure_history']


def test_authenticated_health_does_not_resolve_failed_receipt_for_another_launch_contract(tmp_path, monkeypatch):
    import json
    from hotpost import studio_services as service
    from hotpost.editing_adapter import _atomic_json
    settings, _, launches, _ = startup_fixture(tmp_path, monkeypatch)
    receipt=settings.voicebench_root/'.runtime'/'hotpost-startup-18767.json';receipt.parent.mkdir()
    saved={'status':'failed','pid':777,'command':['another-service'],'cwd':str(tmp_path/'other')}
    _atomic_json(receipt,saved)
    monkeypatch.setattr(service.requests,'Session',lambda:SimpleNamespace(get=lambda *a,**k:SimpleNamespace(
        status_code=200,json=lambda:{'service':'VoiceBench External TTS API'})))
    ensure_local(settings,'voice')
    assert json.loads(receipt.read_text('utf-8'))==saved and not launches
