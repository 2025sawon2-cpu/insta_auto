import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from types import SimpleNamespace

import pytest

from hotpost import video_agent_repairs as repairs
from hotpost.studio_store import StudioStore
from hotpost.video_agent_context import semantic_fingerprint, job_method_fingerprint


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


@pytest.fixture
def env(tmp_path):
    main, renderer = tmp_path/'main', tmp_path/'renderer'
    for root, package in ((main, 'hotpost'), (renderer, 'auto_capcut')):
        write(root/package/'__init__.py', '')
        write(root/'pytest.ini', '[pytest]\ntestpaths = tests\n')
        write(root/'tests/test_existing.py', 'def test_existing():\n    assert True\n')
    write(main/'hotpost/calculation.py', 'def combine(a, b):\n    return a - b\n')
    write(main/'hotpost/dirty_user_work.py', '# existing uncommitted user work\nVALUE = 42\n')
    write(main/'data/secret.json', '{"do_not_copy": true}')
    pipeline = repairs.VideoRepairPipeline(main, renderer, tmp_path/'receipts',
        interpreters={'main':sys.executable, 'renderer':sys.executable},
        regression_tests={'main':['tests/test_existing.py']},
        independent_reviewer=lambda request: {'approved':True, 'preserves_quality_guards':True,
            'recovers_current_incident':True,
            'regression_meaningful':True, 'binding_sha256':request['binding_sha256'],
            'reviewer_call_id':'independent-model-call', 'reason':'Regression covers the observed defect.'})
    store = StudioStore(tmp_path/'data/studio')
    state = {'id':'task-1', 'automation':{'active':True}}
    with store.connect() as db:
        db.execute('INSERT INTO tasks VALUES(?,?,?,?,?)', ('task-1','reference',1,json.dumps(state),time.time()))
        db.execute('CREATE TABLE video_agents(task_id TEXT PRIMARY KEY,epoch INTEGER,record TEXT,updated REAL)')
        db.execute('INSERT INTO video_agents VALUES(?,?,?,?)', ('task-1',3,'{}',time.time()))
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)', ('job-1','task-1','edit','failed-method','{}','failed',
            json.dumps({'video_agent_input_fingerprint':semantic_fingerprint(state)}),'original failure',0,0))
    return SimpleNamespace(main=main, renderer=renderer, pipeline=pipeline, store=store, state=state)


def proposal(env, *, body='def combine(a, b):\n    return a + b\n', test=None):
    row = env.pipeline.inspect_code('main','hotpost/calculation.py')
    with env.store.connect() as db:job=db.execute('select kind,payload,checkpoint from jobs where id=?',('job-1',)).fetchone()
    return dict(task_id='task-1',job_id='job-1',input_fingerprint=semantic_fingerprint(env.state),job_fingerprint=job_method_fingerprint(job),agent_epoch=3,
        planner_call_id='planner-model-call',reason='Addition incorrectly subtracts second input.',
        files=[{**row,'content':body}, {'repo':'main','path':'tests/test_new_regression.py',
            'base_sha256':None,'content':test or 'from hotpost.calculation import combine\ndef test_addition():\n    assert combine(7, 2) == 9\n'}])


def ready(env):
    repair_id = env.pipeline.propose_patch(proposal(env))
    result = env.pipeline.test_patch(repair_id)
    assert result['status'] == 'tests_passed', Path(result['tests'][0]['log_path']).read_text('utf-8')
    review = env.pipeline.review_patch(repair_id)
    return repair_id, review


def test_owner_test_and_rejected_review_return_verified_feedback_without_extra_read(env):
    from hotpost.video_agents import VideoAgentManager
    from hotpost.config import Settings
    studio=SimpleNamespace(store=env.store,settings=Settings(data_dir=env.store.root.parent),video_repair_pipeline=env.pipeline)
    manager=VideoAgentManager(studio)
    try:
        manager._save('task-1',3,{'repair_evidence_used':['read']*6,'idle_decisions':25})
        bad=env.pipeline.propose_patch(proposal(env,body='def combine(a,b):\n    return a-b\n'))
        failed=manager.execute('task-1',{'kind':'test_patch','repair_id':bad,'_agent_epoch':3},'test',semantic_fingerprint(env.state))
        assert failed['status']=='tests_failed'
        assert 'FAILED' in failed['diagnostics']['tests'][0]['log_excerpt']
        assert failed['diagnostics']['tests'][0]['log_sha256']
        good=env.pipeline.propose_patch(proposal(env))
        passed=manager.execute('task-1',{'kind':'test_patch','repair_id':good,'_agent_epoch':3},'test2',semantic_fingerprint(env.state))
        assert passed['status']=='tests_passed'
        env.pipeline.reviewer=lambda request:{'approved':False,'preserves_quality_guards':True,
            'regression_meaningful':False,'recovers_current_incident':False,
            'binding_sha256':request['binding_sha256'],'reviewer_call_id':'independent',
            'reason':'Missing current successor recovery connection.'}
        rejected=manager.execute('task-1',{'kind':'review_patch','repair_id':good,'_agent_epoch':3},'review',semantic_fingerprint(env.state))
        assert rejected['status']=='error' and rejected['type']=='RepairRejected'
        assert 'Missing current successor' in json.dumps(rejected['diagnostics']['review_rejection'])
        with pytest.raises(repairs.RepairRejected):
            manager.execute('task-1',{'kind':'test_patch','repair_id':bad,'_agent_epoch':4},'stale',semantic_fingerprint(env.state))
        with env.store.connect() as db:
            record=json.loads(db.execute('select record from video_agents where task_id=?',('task-1',)).fetchone()[0])
            assert len(record['repair_evidence_used'])==6
            assert db.execute('select status from jobs where id=?',('job-1',)).fetchone()[0]=='failed'
    finally:manager.pool.shutdown(wait=True)


def test_restage_keeps_content_identity_and_current_draft_context(env):
    from hotpost.video_agent_memory import repair_packet
    first=env.pipeline.propose_patch(proposal(env))
    second=env.pipeline.propose_patch({**proposal(env),'prior_repair_id':first,'files':[]})
    material=env.pipeline.repair_material(second,'task-1')
    assert first!=second
    assert material['content_fingerprint']==env.pipeline.repair_material(first,'task-1')['content_fingerprint']
    evidence={'id':'task-1','owner_epoch':3,'jobs':[{'id':'job-1'}],
        'memory_index':[{'kind':'propose_patch','repair_id':second}],
        'code_map':{'cause':'hotpost/calculation.py'}}
    packet=repair_packet(SimpleNamespace(video_repair_pipeline=env.pipeline),evidence)
    source=next(row for row in packet if row['path']=='hotpost/calculation.py')
    assert 'return a + b' in source['content'] and source['source']=='staged_repair'
    assert source['repair_id']==second
    assert 'return a - b' in (env.main/'hotpost/calculation.py').read_text('utf8')
    assert any(row['path']=='tests/test_new_regression.py' for row in packet)
    evidence['owner_epoch']=4
    assert all(row.get('source')!='staged_repair' for row in repair_packet(SimpleNamespace(video_repair_pipeline=env.pipeline),evidence))
    with pytest.raises(repairs.RepairRejected):env.pipeline.repair_material(second,'other-task')
    changed=env.pipeline.propose_patch({**proposal(env,body='def combine(a, b):\n    return b + a\n'),'prior_repair_id':second})
    assert env.pipeline.repair_material(changed,'task-1')['content_fingerprint']!=material['content_fingerprint']


def test_current_staged_worker_keeps_both_entry_and_tail_in_bounded_packet(env):
    from hotpost.video_agent_memory import repair_packet
    body='def combine(a, b):\n    return a + b\n'+'# preserved diagnostic context\n'*2000+'# tail acceptance contract\n'
    rid=env.pipeline.propose_patch(proposal(env,body=body))
    evidence={'id':'task-1','owner_epoch':3,'jobs':[{'id':'job-1'}],
        'memory_index':[{'kind':'propose_patch','repair_id':rid}]}
    packet=repair_packet(SimpleNamespace(video_repair_pipeline=env.pipeline),evidence)
    source=next(r for r in packet if r['path']=='hotpost/calculation.py')
    assert source['content']==body and source['offset']==0 and source['next_offset'] is None
    assert len(packet)<=8 and sum(len(r['content']) for r in packet)<=180000
    evidence['jobs']=[{'id':'other-job'}]
    assert not repair_packet(SimpleNamespace(video_repair_pipeline=env.pipeline),evidence)
    evidence['jobs']=[{'id':'job-1'}]
    record=env.pipeline._read(rid);record['status']='applied';env.pipeline._save(record)
    assert not repair_packet(SimpleNamespace(video_repair_pipeline=env.pipeline),evidence)


def test_late_draft_file_packet_keeps_changed_worker_under_shared_budget(env):
    from hotpost.video_agent_memory import staged_packet
    body='def combine(a, b):\n    return a + b\n'+'# padding\n'*6000
    value=proposal(env,body=body)
    value['files']=value['files'][:1]
    for index in range(6):
        value['files'].append({'repo':'main','path':f'tests/test_context_{index}.py',
            'base_sha256':None,'content':'# padding\n'*1400+'def test_context():\n    assert True\n'})
    path='hotpost/worker.py'
    old='# retained worker header\n'+'# padding\n'*7000+'def dispatch():\n    return "old route"\n'+'# tail\n'*2500
    write(env.main/path,old)
    inspected=env.pipeline.inspect_code('main',path)
    new=inspected['content'].replace('"old route"','"recovered route"')
    value['files'].append({**inspected,'content':new})
    rid=env.pipeline.propose_patch(value)
    evidence={'id':'task-1','owner_epoch':3,'jobs':[{'id':'job-1'}],
        'memory_index':[{'kind':'propose_patch','repair_id':rid}]}
    packet=staged_packet(env.pipeline,evidence)
    worker=next(row for row in packet if row['path']==path)
    assert worker['offset']>0 and 'return "recovered route"' in worker['content']
    assert worker['content']==new[worker['offset']:worker['offset']+len(worker['content'])]
    assert len(packet)==8 and sum(len(row['content']) for row in packet)<=180000
    assert worker['sha256']==hashlib.sha256(new.encode()).hexdigest()
    # A current read location takes priority; stale content locations do not.
    read={'kind':'inspect_repair','repo':'main','path':path,'offset':20000,
          'staged_sha256':worker['sha256']}
    evidence['memory_index'].append(read)
    selected=next(row for row in staged_packet(env.pipeline,evidence) if row['path']==path)
    assert selected['offset']==20000
    read['staged_sha256']='stale'
    selected=next(row for row in staged_packet(env.pipeline,evidence) if row['path']==path)
    assert 'return "recovered route"' in selected['content']
    # No source application or production change is involved in packet reads.
    assert (env.main/path).read_text('utf8')==old


def test_manager_full_resubmission_cannot_renew_progress_by_omitting_prior(env):
    from hotpost.video_agents import VideoAgentManager
    from hotpost.config import Settings
    studio=SimpleNamespace(store=env.store,settings=Settings(data_dir=env.store.root.parent),
                           video_repair_pipeline=env.pipeline)
    manager=VideoAgentManager(studio)
    try:
        results=[]
        for n,body in enumerate(['def combine(a, b):\n    return a + b\n']*2+
                                 ['def combine(a, b):\n    return b + a\n',
                                  'def combine(a, b):\n    return a + b\n']):
            patch=proposal(env,body=body)
            action={'kind':'propose_patch','_agent_epoch':3,'job_id':'job-1','patch':patch}
            result=manager.execute('task-1',action,str(n),semantic_fingerprint(env.state))
            manager._save('task-1',3,{}, {'action':action,'result':result},str(n))
            results.append(result)
        assert len({r['repair_id'] for r in results})==4
        assert [r['code_changed'] for r in results]==[True,False,True,False]
        # A newer historical draft belongs to a now-finished, non-target job.
        with env.store.connect() as db:
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',('job-done','task-1','edit','older-method','{}','done','{}','',1,1))
        other=env.pipeline.propose_patch({**proposal(env,body='def combine(a, b):\n    return a * b\n'),'job_id':'job-done'})
        manager._save('task-1',3,{}, {'action':{'kind':'propose_patch','job_id':'job-done'},
            'result':{'status':'completed','repair_id':other}},'historical-other')
        payloads=[]
        manager.jobs=SimpleNamespace(create=lambda kind,payload,key:payloads.append(payload) or {'id':'model'},start=lambda:None)
        manager.step('task-1')
        assert any(r.get('source')=='staged_repair' for r in payloads[0]['evidence']['repair_packet'])
        drafts=[r for r in payloads[0]['evidence']['repair_packet'] if r.get('source')=='staged_repair']
        assert {r['repair_id'] for r in drafts}=={results[-1]['repair_id']}
        assert not payloads[0]['evidence'].get('allowed_actions')  # Normal planning, before forced diagnosis.
    finally:manager.pool.shutdown(wait=True)


def test_lf_proposal_targets_crlf_source_without_rewriting_untouched_lines(env):
    path=env.main/'hotpost/calculation.py'
    original=b'# preserve outside\r\ndef combine(a, b):\r\n    return a - b\r\n# untouched tail\r\n'
    path.write_bytes(original)
    value=proposal(env);row=value['files'][0];row.pop('content')
    row['replacements']=[{'old':'def combine(a, b):\n    return a - b',
                          'new':'def combine(a, b):\n    return a + b'}]
    rid=env.pipeline.propose_patch(value)
    result=env.pipeline.inspect_staged_file(rid,'task-1','main','hotpost/calculation.py')
    assert result['content'].encode()==original.replace(b'return a - b',b'return a + b')
    assert path.read_bytes()==original
    row['base_sha256']='0'*64
    with pytest.raises(repairs.RepairRejected,match='base SHA'):env.pipeline.propose_patch(value)


@pytest.mark.parametrize('content,old',[
    ('x\r\ny\r\nx\r\ny','x\ny'),
    ('x\r\n  y','x\n y'),
    ('x\r\ny','x\nz'),
])
def test_eol_equivalence_keeps_ambiguity_and_other_context_rejections(content,old):
    with pytest.raises(repairs.RepairRejected,match='exactly once'):
        repairs._replace_exact_source(content,old,'replacement')


@pytest.mark.parametrize('extended_root',[False,True])
def test_host_incident_fixture_runs_in_isolation_and_cannot_be_mutated(env,extended_root):
    if extended_root:
        if os.name!='nt':pytest.skip('Windows extended root')
        env.pipeline.receipts=Path(repairs._test_temp_path(env.pipeline.receipts))
    original={'task':{'id':'task-1','sources':[{'id':'actual-source','rejected':True}],
        'source_acquisition':{'rounds':[{'round':i} for i in range(202)]}},
        'job':{'id':'job-1','checkpoint':{'source_attempts':[{'search_context':{'product':''}}]}},'artifacts':[]}
    test='''import json, os
from pathlib import Path
import pytest
from hotpost.calculation import combine
def test_actual_incident(tmp_path):
    p=Path(os.environ['HOTPOST_REPAIR_INCIDENT'])
    data=json.loads(p.read_text('utf8'))
    assert len(data['task']['source_acquisition']['rounds'])==202
    assert data['task']['sources'][0]['id']=='actual-source'
    assert data['job']['checkpoint']['source_attempts'][0]['search_context']['product']==''
    assert combine(7,2)==9
    long_file=tmp_path/('x'*120)/('y'*120)/'preserved.json'
    long_file.parent.mkdir(parents=True)
    long_file.write_text('actual evidence','utf8')
    assert long_file.read_text('utf8')=='actual evidence'
    for operation in (lambda:p.write_text('{}'),lambda:p.unlink(),lambda:p.rename(tmp_path/'moved.json')):
        with pytest.raises(PermissionError,match='read-only'):operation()
    if os.name=='nt':
        ordinary=str(p)
        if ordinary.startswith(chr(92)*2+'?'+chr(92)):ordinary=ordinary[4:]
        alias=Path(chr(92)*2+'?'+chr(92)+ordinary)
        assert alias.read_bytes()==p.read_bytes()
        for q in [Path(ordinary),alias]:
            for operation in (lambda:q.write_text('{}'),lambda:q.unlink(),lambda:q.rename(tmp_path/'moved.json')):
                with pytest.raises(PermissionError,match='read-only'):operation()
    assert json.loads(p.read_text('utf8'))==data
    with pytest.raises(PermissionError,match='absolute mutation paths'):
        os.open('incident.json',os.O_WRONLY|os.O_CREAT)
    if os.open in os.supports_dir_fd:
        fd=os.open(p.parent,os.O_RDONLY)
        try:
            with pytest.raises(PermissionError,match='absolute mutation paths'):
                os.open('incident.json',os.O_WRONLY,dir_fd=fd)
        finally:os.close(fd)
'''
    p=proposal(env,test=test);p['incident_fixture']=original
    rid=env.pipeline.propose_patch(p);record=env.pipeline._read(rid)
    captured=env.pipeline._folder(rid)/'stage'/record['incident_fixture']['relative_path']
    assert json.loads(captured.read_text('utf8'))==original
    result=env.pipeline.test_patch(rid)
    assert result['status']=='tests_passed',Path(result['tests'][0]['log_path']).read_text('utf8')
    request=env.pipeline.review_request(rid)
    assert request['incident_fixture']['sha256']==hashlib.sha256(captured.read_bytes()).hexdigest()
    env.pipeline.review_patch(rid)
    captured.write_text('{}','utf8')
    with pytest.raises(repairs.RepairRejected,match='fixture changed'):
        env.pipeline.review_request(rid)


def test_owned_incident_subtree_navigation_is_bound_paginated_and_read_only(env):
    fixture={'task':{'id':'task-1','sources':[{'id':'source-1','attempted_policy':'current','details':'x'*30000}]},
        'job':{'id':'job-1','task_id':'task-1'},'artifacts':[]}
    p=proposal(env);p['incident_fixture']=fixture;rid=env.pipeline.propose_patch(p)
    record=env.pipeline._read(rid);file=env.pipeline._folder(rid)/'stage'/record['incident_fixture']['relative_path'];before=file.read_bytes()
    result=env.pipeline.inspect_incident(rid,'task-1',['task','sources',0,'attempted_policy'])
    assert json.loads(result['content'])=='current' and result['historical_evidence']
    assert result['sha256']==hashlib.sha256(before).hexdigest()
    head=env.pipeline.inspect_incident(rid,'task-1',['task','sources',0],limit=999999)
    assert len(head['content'])==24000 and head['next_offset']==24000
    tail=env.pipeline.inspect_incident(rid,'task-1',['task','sources',0],offset=head['next_offset'])
    assert json.loads(head['content']+tail['content'])==fixture['task']['sources'][0]
    for path in [['task','missing'],['task','sources',-1],['task','sources',True],'../other']:
        with pytest.raises(repairs.RepairRejected):env.pipeline.inspect_incident(rid,'task-1',path)
    with pytest.raises(repairs.RepairRejected,match='another video'):env.pipeline.inspect_incident(rid,'foreign',[])
    assert file.read_bytes()==before
    file.write_text('{}','utf8')
    with pytest.raises(repairs.RepairRejected,match='fixture changed'):env.pipeline.inspect_incident(rid,'task-1',[])


def test_incident_fixture_requires_exact_identity_and_new_capture_on_restage(env):
    for task,job in [('other','job-1'),('task-1','other')]:
        p=proposal(env);p['incident_fixture']={'task':{'id':task},'job':{'id':job}}
        with pytest.raises(repairs.RepairRejected,match='exact task and job'):env.pipeline.propose_patch(p)
    p=proposal(env);p['incident_fixture']={'task':{'id':'task-1','version':1},'job':{'id':'job-1'}}
    rid=env.pipeline.propose_patch(p)
    p.pop('files');p['prior_repair_id']=rid;p['incident_fixture']['task']['version']=2
    new=env.pipeline.propose_patch(p)
    captured=env.pipeline._folder(new)/'stage/.repair-evidence/incident.json'
    assert json.loads(captured.read_text('utf8'))['task']['version']==2
    assert env.pipeline._read(new)['status']=='staged'
    assert repairs._harness({})==repairs._HARNESS


def test_extended_fixture_harness_cannot_read_outside_stage(env):
    outside=env.main/'data/secret.json'
    test=f'''import os
from pathlib import Path
import pytest
def test_no_external_access():
    p={str(outside)!r}
    if os.name=='nt':p=chr(92)*2+'?'+chr(92)+p
    with pytest.raises(PermissionError,match='outside isolated roots'):Path(p).read_text()
    assert True
'''
    p=proposal(env,test=test);p['incident_fixture']={'task':{'id':'task-1'},'job':{'id':'job-1'}}
    rid=env.pipeline.propose_patch(p)
    result=env.pipeline.test_patch(rid)
    assert result['status']=='tests_passed',Path(result['tests'][0]['log_path']).read_text('utf8')


def test_fixture_audit_skips_memory_events_and_retains_all_guarded_branches(tmp_path):
    import ast
    import pathlib
    functions={}
    for version in (2,3):
        source=repairs._harness({'incident_fixture':{'sandbox_version':version}})
        tree=ast.parse(source)
        audit=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='audit')
        calls=[]
        def canonical(path):
            calls.append(str(path))
            return Path(path).resolve()
        ns={'os':os,'pathlib':pathlib,'root':tmp_path,'allowed_reads':[tmp_path],
            'canonical':canonical,'inside':lambda *a:False}
        exec(compile(ast.Module(body=[audit],type_ignores=[]),'<audit-regression>','exec'),ns)
        functions[version]=(ns['audit'],calls)
        ns['audit']('builtins.id',(123,))
        assert bool(calls) is (version==2)
    audit,calls=functions[3]
    for event in ('builtins.id','object.__getattr__','exec','marshal.loads'):
        audit(event,())
    assert calls==[]
    # Every prior protected event still reaches the same denial path.
    protected={
        'open':(str(tmp_path/'file'),'r',os.O_RDONLY),
        **{e:(str(tmp_path/'file'),) for e in ('os.remove','os.rmdir','os.mkdir','os.chmod','os.utime','os.listdir','os.scandir')},
        **{e:(str(tmp_path/'a'),str(tmp_path/'b')) for e in ('os.rename','os.link','os.symlink')},
        **{e:() for e in ('subprocess.Popen','os.system','os.posix_spawn','ctypes.dlopen','socket.__new__','socket.connect')}}
    for event,args in protected.items():
        for version in (2,3):
            with pytest.raises(PermissionError):functions[version][0](event,args)


def test_repair_timeout_retains_test_name_and_stack_without_approval(env):
    test='import time\ndef test_stalled_external_mock():\n    assert True\n    time.sleep(30)\n'
    rid=env.pipeline.propose_patch(proposal(env,test=test))
    result=env.pipeline.test_patch(rid,timeout_seconds=3)
    assert result['status']=='tests_failed' and result['tests'][0]['returncode'] is None
    log=Path(result['tests'][0]['log_path']).read_text('utf8')
    assert 'Pinned regression timeout' in log and 'test_stalled_external_mock' in log
    assert 'Timeout (' in log and 'test_new_regression.py' in log
    with pytest.raises(repairs.RepairRejected,match='passing pinned tests'):env.pipeline.review_request(rid)


def test_staged_file_inspection_reads_own_exact_draft_and_rejects_tampering(env):
    p=proposal(env);rid=env.pipeline.propose_patch(p)
    name='tests/test_new_regression.py'
    assert not (env.main/name).exists()
    r=env.pipeline.inspect_staged_file(rid,'task-1','main',name,offset=5,limit=12)
    assert r['content']==p['files'][1]['content'][5:17] and r['next_offset']==17
    assert r['base_sha256'] is None and r['sha256']==hashlib.sha256(p['files'][1]['content'].encode()).hexdigest()
    assert r['source']=='staged_repair'
    from hotpost.video_agents import VideoAgentManager
    studio=SimpleNamespace(store=env.store,settings=SimpleNamespace(data_dir=env.store.root.parent),video_repair_pipeline=env.pipeline)
    manager=VideoAgentManager(studio)
    try:
        actual=manager.execute('task-1',{'kind':'inspect_repair','repair_id':rid,'repo':'main','path':name,'offset':5,'limit':12},'read',semantic_fingerprint(env.state))
        assert actual==r
    finally:manager.pool.shutdown(wait=True)
    with pytest.raises(repairs.RepairRejected,match='another video'):
        env.pipeline.inspect_staged_file(rid,'foreign','main',name)
    for path in ['../repair.json','hotpost/dirty_user_work.py']:
        with pytest.raises(repairs.RepairRejected,match='listed'):
            env.pipeline.inspect_staged_file(rid,'task-1','main',path)
    with pytest.raises(repairs.RepairRejected,match='integers'):
        env.pipeline.inspect_staged_file(rid,'task-1','main',name,offset=True)
    (env.pipeline._folder(rid)/'stage/main'/name).write_text('changed','utf8')
    with pytest.raises(repairs.RepairRejected,match='Staged inputs changed'):
        env.pipeline.inspect_staged_file(rid,'task-1','main',name)


def test_dependency_restage_preserves_exact_code_and_integration_tests_but_not_approval(env):
    rid,_=ready(env);old=env.pipeline._read(rid)
    write(env.main/'hotpost/dirty_user_work.py','VALUE = 43\n')
    diagnostics=env.pipeline.diagnostics(rid,'task-1')
    assert diagnostics['dependency_changes']['count']==1
    assert diagnostics['dependency_changes']['files'][0]['path']=='main/hotpost/dirty_user_work.py'
    assert 'prior_repair_id='+rid in diagnostics['dependency_recovery']
    with pytest.raises(repairs.RepairRejected,match='prior_repair_id'):
        env.pipeline.apply_patch(rid,store=env.store)
    p=proposal(env);p.pop('files');p['prior_repair_id']=rid
    new=env.pipeline.propose_patch(p);record=env.pipeline._read(new)
    assert record['files']==old['files'] and record['new_tests']==old['new_tests']
    assert record['snapshot_hashes']!=old['snapshot_hashes']
    assert record['status']=='staged' and not record.get('review') and not record.get('tests')
    assert env.pipeline.test_patch(new)['status']=='tests_passed'


@pytest.mark.parametrize('changed',['source','task','epoch','job'])
def test_restage_cannot_copy_new_source_or_foreign_owner(env,changed):
    rid=env.pipeline.propose_patch(proposal(env));p=proposal(env);p.pop('files');p['prior_repair_id']=rid
    if changed=='source':write(env.main/'hotpost/calculation.py','def combine(a,b): return a*b\n')
    elif changed=='task':p['task_id']='other'
    elif changed=='epoch':p['agent_epoch']=4
    else:p['job_id']='changed'
    with pytest.raises(repairs.RepairRejected):env.pipeline.propose_patch(p)


@pytest.mark.parametrize('mode',['new_test','replace_test','replace_source','full_test'])
def test_revision_retains_unlisted_draft_and_revalidates_without_prior_approval(env,mode):
    rid,_=ready(env);before=env.pipeline._read(rid)
    p=proposal(env);p['prior_repair_id']=rid
    if mode=='new_test':
        p['files']=[{'repo':'main','path':'tests/test_extra.py','base_sha256':None,
            'content':'from hotpost.calculation import combine\ndef test_extra():\n    assert combine(8, 2)==10\n'}]
    elif mode=='full_test':
        p['files']=[{'repo':'main','path':'tests/test_new_regression.py','base_sha256':None,
            'content':'from hotpost.calculation import combine\ndef test_addition():\n    assert combine(8, 3)==11\n'}]
    elif mode=='replace_test':
        p['files']=[{'repo':'main','path':'tests/test_new_regression.py','base_sha256':None,
            'replacements':[{'old':'combine(7, 2) == 9','new':'combine(8, 3) == 11'}]}]
    else:
        row=before['files'][0]
        p['files']=[{'repo':'main','path':row['path'],'base_sha256':row['base_sha256'],
            'replacements':[{'old':'return a + b','new':'return sum((a, b))'}]}]
    new=env.pipeline.propose_patch(p);record=env.pipeline._read(new)
    assert record['prior_repair_id']==rid and record['status']=='staged'
    assert not record.get('tests') and not record.get('review')
    assert env.pipeline._read(rid)==before
    assert (env.main/'hotpost/calculation.py').read_text()=='def combine(a, b):\n    return a - b\n'
    supplied={r['path'] for r in p['files']}
    for row in before['files']:
        if row['path'] not in supplied:assert row in record['files']
    with pytest.raises(repairs.RepairRejected):env.pipeline.apply_patch(new,store=env.store)
    result=env.pipeline.test_patch(new)
    assert result['status']=='tests_passed',Path(result['tests'][0]['log_path']).read_text('utf8')
    assert not env.pipeline.ready_to_apply(new)


@pytest.mark.parametrize('damage',['tamper','live','base','duplicate','existing_test'])
def test_revision_cannot_bypass_stage_or_existing_file_guards(env,damage):
    rid=env.pipeline.propose_patch(proposal(env));p=proposal(env);p['prior_repair_id']=rid
    p['files']=[{'repo':'main','path':'tests/test_new_regression.py','base_sha256':None,
        'replacements':[{'old':'combine(7, 2) == 9','new':'combine(8, 3) == 11'}]}]
    if damage=='tamper':write(env.pipeline._folder(rid)/'stage/main/tests/test_new_regression.py','assert True\n')
    elif damage=='live':write(env.main/'hotpost/calculation.py','def combine(a,b):return a*b\n')
    elif damage=='base':p['files'][0]['base_sha256']='wrong'
    elif damage=='duplicate':p['files']*=2
    else:p['files']=[{'repo':'main','path':'tests/test_existing.py','base_sha256':repairs._sha((env.main/'tests/test_existing.py').read_bytes()),'content':'assert True\n'}]
    with pytest.raises(repairs.RepairRejected):env.pipeline.propose_patch(p)


def test_restage_current_input_requires_fresh_tests_and_review(env):
    rid,_=ready(env);p=proposal(env);p.pop('files');p['prior_repair_id']=rid
    p['input_fingerprint']='current-host-input'
    new=env.pipeline.propose_patch(p);record=env.pipeline._read(new)
    assert record['binding']['input_fingerprint']=='current-host-input'
    assert record['status']=='staged' and not record.get('tests') and not record.get('review')
    assert env.pipeline.ready_to_apply(new) is False


def test_review_binds_unchanged_recovery_contract_and_executed_pinned_tests(env):
    write(env.main/'hotpost/video_agent_actions.py','def execute():\n    return "verified host retry"\n')
    write(env.main/'hotpost/video_agent_runtime.py','def resume_loaded_repairs():\n    return "parked only"\n')
    write(env.main/'hotpost/video_agent_repairs.py','def verified_repair():\n    return "signature and loaded-code checks"\n')
    p=proposal(env);p['incident']={'job':{'id':'job-1','status':'failed'}}
    rid=env.pipeline.propose_patch(p);record=env.pipeline._read(rid)
    context={r['path']:r for r in record['recovery_context']}
    assert set(context)=={'hotpost/video_agent_actions.py','hotpost/video_agent_runtime.py','hotpost/video_agent_repairs.py','tests/test_existing.py'}
    assert 'def verified_repair' in context['hotpost/video_agent_repairs.py']['content']
    for path,row in context.items():
        assert row['sha256']==record['snapshot_hashes']['main/'+path]
        assert row['sha256']==repairs._sha(row['content'].encode('utf8'))
    assert context['tests/test_existing.py']['pinned_test'] is True
    assert context['hotpost/video_agent_actions.py']['pinned_test'] is False
    assert env.pipeline.test_patch(rid)['status']=='tests_passed'
    request=env.pipeline.review_request(rid)
    assert request['recovery_context']==record['recovery_context']
    assert 'tests/test_existing.py' in request['tests'][0]['tests']
    env.pipeline.review_patch(rid)
    record=env.pipeline._read(rid)
    record['recovery_context'][0]['content']='changed context'
    env.pipeline._save(record)
    with pytest.raises(repairs.RepairRejected,match='Missing or changed signed'):
        env.pipeline.apply_patch(rid,store=env.store)


def test_recovery_context_explicitly_marks_missing_or_overbudget_contract(env):
    write(env.main/'hotpost/video_agent_actions.py','#'+('x'*160001)+'\n')
    p=proposal(env);p['incident']={'job':{'id':'job-1'}}
    rid=env.pipeline.propose_patch(p)
    context={r['path']:r for r in env.pipeline._read(rid)['recovery_context']}
    assert 'budget' in context['hotpost/video_agent_actions.py']['omitted_reason']
    assert 'content' not in context['hotpost/video_agent_actions.py']
    assert 'Not in' in context['hotpost/video_agent_repairs.py']['omitted_reason']
    assert context['tests/test_existing.py']['content']


def test_planning_child_pins_executes_and_supplies_the_host_recovery_contract(env):
    source='def planning_recovery_candidate():\n    return "current owner and retained hold"\n'
    write(env.main/'hotpost/video_agent_planning_claim.py',source)
    expected=(env.main/'hotpost/video_agent_planning_claim.py').read_bytes().decode('utf8')
    trusted='tests/test_video_agent_planning_claim.py'
    write(env.main/trusted,'def test_host_recovery():\n    assert False, "host regression must actually execute"\n')
    p=proposal(env);p['incident']={'job':{'id':'job-1','kind':'collect_sources','status':'failed',
        'payload':{'planning_recovery_from':'job-parent'},'checkpoint':{'failure_classification':{'category':'storage'}}}}
    rid=env.pipeline.propose_patch(p);record=env.pipeline._read(rid)
    assert any(row['path']==trusted for row in record['pinned_tests'])
    context={row['path']:row for row in record['recovery_context']}
    assert context['hotpost/video_agent_planning_claim.py']['content']==expected
    assert context[trusted]['pinned_test'] is True
    assert env.pipeline.test_patch(rid)['status']=='tests_failed'
    with pytest.raises(repairs.RepairRejected,match='passing pinned tests'):env.pipeline.review_request(rid)
    write(env.main/trusted,'def test_host_recovery():\n    assert True\n')
    new=env.pipeline.propose_patch(p)
    assert env.pipeline.test_patch(new)['status']=='tests_passed'
    request=env.pipeline.review_request(new)
    assert trusted in request['tests'][0]['tests']
    assert any(row.get('content')==expected for row in request['recovery_context'])


def test_planning_recovery_guard_is_protected_and_missing_host_test_is_not_silently_omitted(env):
    source='def planning_recovery_candidate():\n    return False\n'
    write(env.main/'hotpost/video_agent_planning_claim.py',source)
    p=proposal(env);p['files'][0]={'repo':'main','path':'hotpost/video_agent_planning_claim.py',
        'base_sha256':repairs._sha((env.main/'hotpost/video_agent_planning_claim.py').read_bytes()),'content':source.replace('False','True')}
    with pytest.raises(repairs.RepairRejected):env.pipeline.propose_patch(p)
    p=proposal(env);p['incident']={'job':{'kind':'collect_sources','payload':json.dumps({'planning_recovery_from':'parent'})}}
    with pytest.raises(repairs.RepairRejected,match='Pinned regression'):env.pipeline.propose_patch(p)


def test_legacy_signed_repair_cannot_apply_after_job_method_change(env):
    p=proposal(env);p.pop('job_fingerprint')
    rid=env.pipeline.propose_patch(p);env.pipeline.test_patch(rid);env.pipeline.review_patch(rid)
    with env.store.transaction() as db:db.execute('update jobs set payload=? where id=?',('{"changed_method":true}','job-1'))
    with pytest.raises(repairs.RepairRejected,match='Legacy repair'):
        env.pipeline.apply_patch(rid,store=env.store)


@pytest.mark.parametrize('hold',[{'status':'completed'},{'automation':{'active':True,'consumed_by_daily_policy':True}},
    {'automation':{'active':True,'pause_reason':'save-script'}},{'source_acquisition':{'hold':{'reason':'captcha'}}},
    {'editorial_content_hold':{'reason':'review'}},{'source_acquisition':{'receipt_wait':{'status':'unsettled'}}}])
def test_code_apply_rechecks_current_production_authority(env,hold):
    env.state.update(hold)
    with env.store.transaction() as db:
        db.execute('update tasks set state=? where id=?',(json.dumps(env.state),'task-1'))
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps({'video_agent_input_fingerprint':semantic_fingerprint(env.state)}),'job-1'))
    rid,_=ready(env)
    with pytest.raises(repairs.RepairRejected):env.pipeline.apply_patch(rid,store=env.store)


def test_checkpoint_only_access_block_prevents_code_application(env):
    with env.store.transaction() as db:
        cp=json.loads(db.execute('select checkpoint from jobs where id=?',('job-1',)).fetchone()[0])
        cp['failure_classification']={'category':'access_blocked'}
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),'job-1'))
    rid,_=ready(env)
    with pytest.raises(repairs.RepairRejected,match='Access-blocked'):
        env.pipeline.apply_patch(rid,store=env.store)


def test_internal_contract_repair_applies_without_clearing_other_platform_login(env):
    env.state.update(run_id='run',source_acquisition={'waiting':{'at':10,'searches':[{'provider':'youtube','status':'login_required'}]}})
    cp={'video_agent_input_fingerprint':semantic_fingerprint(env.state),'failure_classification':{'category':'input_validation'},
        'source_access_preflight':{'ready_routes':['tiktok'],'observations':[{'provider':'tiktok','status':'ready','reason':'current_existing_page_observed','observed_at':20}]}}
    cp['failure_classification']['signature_material']={'exception_type':'hotpost.source_visual_queries.VisualQueryRejection','stage':'collect_sources'}
    cp['failure_trace']={'type':'VisualQueryRejection','stage':'collect_sources','frames':[{'function':'cached_visual_queries'}]}
    with env.store.transaction() as db:
        db.execute('update tasks set state=? where id=?',(json.dumps(env.state),'task-1'))
        db.execute("update jobs set kind='collect_sources',payload=?,checkpoint=? where id=?",(json.dumps({'run_id':'run'}),json.dumps(cp),'job-1'))
    rid,_=ready(env);env.pipeline.apply_patch(rid,store=env.store)
    assert env.store.get('task-1')['source_acquisition']==env.state['source_acquisition']


def test_parked_job_can_restage_changed_input_and_resume_with_new_signed_repair(env):
    from hotpost.video_agent_actions import execute
    from hotpost.video_agents import VideoAgentManager
    env.state.update(revision=1,status='source_wait',scripts=[],voices=[],edits=[],sources=[],daily_quality={'pending':'failed'})
    fp=semantic_fingerprint(env.state)
    with env.store.transaction() as db:
        db.execute('update tasks set state=? where id=?',(json.dumps(env.state),'task-1'))
        cp={'video_agent_input_fingerprint':fp}
        cp['video_agent_job_fingerprint']=job_method_fingerprint({'kind':'edit','payload':{},'checkpoint':cp})
        db.execute("update jobs set status='queued',checkpoint=? where id=?",(json.dumps(cp),'job-1'))
    rid,_=ready(env)
    studio=SimpleNamespace(store=env.store,settings=SimpleNamespace(data_dir=env.store.root.parent),video_repair_pipeline=env.pipeline)
    action={'kind':'park_for_repair','job_id':'job-1','repair_id':rid,'_agent_epoch':3,'hypothesis':'Apply tested repair'}
    assert execute(studio,'task-1',action,'park',fp)['parked']
    env.store.change('task-1',lambda s,db:s.update(original_text='new approved reference information'))
    current=env.store.get('task-1');manager=VideoAgentManager(studio)
    try:
        result=manager.execute('task-1',{'kind':'propose_patch','job_id':'job-1','_agent_epoch':3,
            'patch':{'prior_repair_id':rid,'reason':'Revalidate the exact repair against current approved input'}},'restage',semantic_fingerprint(current))
        new=result['repair_id'];assert env.pipeline.test_patch(new)['status']=='tests_passed'
        original_reviewer=env.pipeline.reviewer
        def review_existing_incident(request):
            assert request['incident']['task']['original_text']==current['original_text']
            assert request['incident']['job']['id']=='job-1' and request['incident']['job']['status']=='paused'
            assert request['incident']['job']['checkpoint']['video_agent_park_receipt']['repair']['repair_id']==rid
            return original_reviewer(request)
        env.pipeline.reviewer=review_existing_incident
        review=env.pipeline.review_patch(new)
        applied=env.pipeline.apply_patch(new,store=env.store,review_id=review['review_id'])
        studio.loaded_code_receipts={new:{**applied,'process_id':os.getpid(),'loaded_at':time.time()}}
        result=execute(studio,'task-1',{'kind':'retry_repaired','job_id':'job-1','repair_id':new,
            '_agent_epoch':3,'hypothesis':'Resume newly reviewed current inputs'},'retry',semantic_fingerprint(current))
        assert result['status']=='queued'
        with env.store.connect() as db:
            cp=json.loads(db.execute('select checkpoint from jobs where id=?',('job-1',)).fetchone()[0])
        assert cp['video_agent_park_receipt']['repair']['repair_id']==rid
    finally:manager.pool.shutdown(wait=True)


def test_rejection_reason_and_verified_test_logs_are_available_only_to_owner(env):
    rid=env.pipeline.propose_patch(proposal(env));env.pipeline.test_patch(rid)
    def reject(request):
        execution=request['test_execution']
        assert execution['success_exit_code']==73 and 'raise SystemExit(73' in execution['harness_source']
        assert 'passed' in execution['logs'][0]['log_excerpt']
        return {'approved':False,'reason':'Add an integration test for the actual resume path'}
    env.pipeline.reviewer=reject
    with pytest.raises(repairs.RepairRejected):env.pipeline.review_patch(rid)
    diagnostic=env.pipeline.diagnostics(rid,'task-1')
    assert diagnostic['review_rejection']['reason']=='Add an integration test for the actual resume path'
    assert diagnostic['test_success_exit_code']==73 and 'passed' in diagnostic['tests'][0]['log_excerpt']
    assert 'signature' not in diagnostic and 'review' not in diagnostic
    with pytest.raises(repairs.RepairRejected,match='another video'):env.pipeline.diagnostics(rid,'task-other')


def test_quiesced_coordinator_preserves_other_queued_jobs_during_common_repair(env):
    import threading
    rid,review=ready(env)
    with env.store.connect() as db:
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',('other-job','other-video','collect_sources','other-method',
            '{}','queued','{}','',0,0))
    with pytest.raises(repairs.RepairRejected,match='queues must be idle'):
        env.pipeline.apply_patch(rid,store=env.store,review_id=review['review_id'])
    gate=threading.Event();gate.set();env.store.video_agents=SimpleNamespace(maintenance=gate)
    assert env.pipeline.apply_patch(rid,store=env.store,review_id=review['review_id'])['status']=='applied'
    with env.store.connect() as db:assert db.execute("select status from jobs where id='other-job'").fetchone()[0]=='queued'


def test_quiesced_coordinator_still_rejects_any_running_production(env):
    import threading
    rid,review=ready(env);gate=threading.Event();gate.set();env.store.video_agents=SimpleNamespace(maintenance=gate)
    with env.store.connect() as db:
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',('other-job','other-video','collect_sources','other-method',
            '{}','running','{}','',0,0))
    with pytest.raises(repairs.RepairRejected,match='queues must be idle'):
        env.pipeline.apply_patch(rid,store=env.store,review_id=review['review_id'])


def test_persistent_maintenance_blocks_claims_in_another_process(env):
    import subprocess
    task,_=env.store.create('other','Other',{'active':True})
    barrier=env.store.root/'agent-maintenance.json';barrier.write_text('{"repair_id":"test"}')
    code='from pathlib import Path; from hotpost.studio_store import StudioStore; print(StudioStore(Path('+repr(str(env.store.root))+')).claim())'
    result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode==0 and result.stdout.strip()=='None'
    barrier.unlink();assert StudioStore(env.store.root).claim()['task_id']==task['id']


def test_interrupted_apply_restores_exact_original_before_fresh_process(env):
    rid=env.pipeline.propose_patch(proposal(env));record=env.pipeline._read(rid);row=record['files'][0]
    target=env.main/row['path'];original=target.read_bytes()
    backup=env.pipeline._folder(rid)/'backups/main'/row['path'];backup.parent.mkdir(parents=True);backup.write_bytes(original)
    target.write_bytes(row['content'].encode('utf8'));record['status']='applying';env.pipeline._save(record)
    (env.store.root/'agent-maintenance.json').write_text(json.dumps({'repair_id':rid}))
    repairs.recover_partial_apply(env.pipeline,env.store,record)
    assert target.read_bytes()==original
    barrier=json.loads((env.store.root/'agent-maintenance.json').read_text('utf8'))
    assert barrier['phase']=='restored_restart_required'
    recovered=env.pipeline._read(rid)
    assert recovered['status']=='apply_failed'
    from hotpost.video_agent_runtime import restored_process_ready
    assert not restored_process_ready(env.pipeline,recovered,recovered['restored_at']-1)


def test_stale_timestamp_valid_bytecode_requires_another_fresh_import(tmp_path):
    import importlib.util
    import py_compile
    from hotpost.video_agent_runtime import source_module_current
    path=tmp_path/'example.py';path.write_text('VALUE = 1\n');before=path.stat()
    cache=Path(py_compile.compile(str(path),doraise=True))
    path.write_text('VALUE = 2\n');os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
    def load(verified=False):
        from hotpost.source_loader import SourceLoader
        spec=importlib.util.spec_from_file_location('example',path,loader=SourceLoader('example',str(path)) if verified else None)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module
    stale=load();assert stale.VALUE==1
    assert not source_module_current(stale,path)
    cache.unlink()
    assert not source_module_current(stale,path)
    fresh=load(True);assert fresh.VALUE==2 and source_module_current(fresh,path)
    py_compile.compile(str(path),doraise=True)
    assert not source_module_current(stale,path)


def test_new_policy_regression_is_allowed_without_weakening_production_guards(env):
    patch=proposal(env);patch['files'][1]['path']='tests/test_policy_transition_guard.py'
    assert env.pipeline.propose_patch(patch).startswith('repair-')


@pytest.mark.parametrize('change',['input','job','legacy'])
def test_old_repair_cannot_spend_tests_or_review_on_different_incident(env,change):
    rid,_=ready(env);called=[]
    env.pipeline.reviewer=lambda request:called.append(request) or {}
    with env.store.transaction() as db:
        if change=='input':
            state={**env.state,'run_id':'new-run'}
            db.execute("UPDATE tasks SET state=? WHERE id='task-1'",(json.dumps(state),))
        if change=='job':db.execute("UPDATE jobs SET payload=? WHERE id='job-1'",(json.dumps({'run_id':'new-run'}),))
    if change=='legacy':
        record=env.pipeline._read(rid);record['binding'].pop('job_fingerprint');env.pipeline._save(record)
    with pytest.raises(repairs.RepairRejected,match='Historical repair'):
        env.pipeline.review_patch(rid,guard=lambda:env.pipeline.authorized(rid,'task-1',3,env.store))
    assert called==[] and env.pipeline._read(rid)['status']=='reviewed'


@pytest.mark.parametrize('operation',['test','review'])
def test_changed_owner_during_long_operation_cannot_commit_receipt(env,monkeypatch,operation):
    rid,_=ready(env);before=env.pipeline._read(rid)
    def change_owner():
        with env.store.connect() as db:db.execute("UPDATE video_agents SET epoch=4 WHERE task_id='task-1'")
    guard=lambda:env.pipeline.authorized(rid,'task-1',3,env.store)
    if operation=='test':
        original=repairs.subprocess.run
        def run(*args,**kwargs):
            result=original(*args,**kwargs);change_owner();return result
        monkeypatch.setattr(repairs.subprocess,'run',run)
        call=lambda:env.pipeline.test_patch(rid,guard=guard)
    else:
        original=env.pipeline.reviewer
        def review(request):
            result=original(request);change_owner();return result
        env.pipeline.reviewer=review
        call=lambda:env.pipeline.review_patch(rid,guard=guard)
    with pytest.raises(repairs.RepairRejected,match='owner changed'):call()
    assert env.pipeline._read(rid)==before
    for row in before['tests']:
        assert hashlib.sha256(Path(row['log_path']).read_bytes()).hexdigest()==row['log_sha256']


@pytest.mark.parametrize('path', ['../data/file.py','hotpost/../../data/file.py','hotpost\\file.py',
    '/hotpost/file.py','C:/secret.py','hotpost/.hidden.py','hotpost/credentials.py','data/file.py'])
def test_inspection_rejects_escape_and_sensitive_paths(env,path):
    with pytest.raises(repairs.RepairRejected): env.pipeline.inspect_code('main',path)


@pytest.mark.parametrize('name', ['video_agents.py','video_agent_actions.py','studio.py','config.py','server.py','source_policy.py',
    'writing/jobs.py','writing/codex_writer.py'])
def test_control_plane_cannot_be_patched(env,name):
    patch=proposal(env); patch['files'][0]['path']='hotpost/'+name
    with pytest.raises(repairs.RepairRejected): env.pipeline.propose_patch(patch)


def test_existing_validation_guard_cannot_be_weakened(env):
    write(env.main/'hotpost/calculation.py','def validate_input(a):\n    assert a > 0\n')
    with pytest.raises(repairs.RepairRejected,match='validation'):
        env.pipeline.propose_patch(proposal(env,body='def validate_input(a):\n    return True\n'))


def test_snapshot_keeps_dirty_source_excludes_data_and_preserves_live(env):
    before=(env.main/'hotpost/calculation.py').read_bytes()
    repair_id=env.pipeline.propose_patch(proposal(env))
    stage=env.pipeline._folder(repair_id)/'stage/main'
    assert (stage/'hotpost/dirty_user_work.py').read_bytes()==(env.main/'hotpost/dirty_user_work.py').read_bytes()
    assert not (stage/'data').exists()
    assert (env.main/'hotpost/calculation.py').read_bytes()==before
    assert not (env.main/'tests/test_new_regression.py').exists()


def test_actual_subprocess_test_review_apply_and_loaded_receipt(env):
    repair_id,review=ready(env)
    applied=env.pipeline.apply_patch(repair_id,store=env.store,review_id=review['review_id'])
    assert applied['restart_required']
    assert 'return a + b' in (env.main/'hotpost/calculation.py').read_text()
    assert (env.pipeline._folder(repair_id)/'backups/main/hotpost/calculation.py').read_text()=='def combine(a, b):\n    return a - b\n'
    studio=SimpleNamespace(video_repair_pipeline=env.pipeline)
    job={'id':'job-1','task_id':'task-1','kind':'edit','payload':{},'checkpoint':{'video_agent_input_fingerprint':semantic_fingerprint(env.state)}}
    action={'repair_id':repair_id,'_agent_epoch':3}
    assert repairs.verified_repair(studio,env.state,action,job) is False
    studio.loaded_code_receipt={**applied,'process_id':os.getpid(),'loaded_at':time.time()}
    verified=repairs.verified_repair(studio,env.state,action,job)
    assert verified['repair_id']==repair_id
    assert verified['review_binding_sha256']==review['review_id']
    assert verified['files']==sorted(applied['files'],key=repairs._json)
    # Another video applied a later, disjoint repair. This video's loaded proof
    # must survive instead of being replaced by the global latest marker.
    studio.loaded_code_receipts={repair_id:studio.loaded_code_receipt}
    studio.loaded_code_receipt={'repair_id':'other-video-repair','process_id':os.getpid()}
    assert repairs.verified_repair(studio,env.state,action,job)['repair_id']==repair_id
    assert not repairs.verified_repair(studio,env.state,{'repair_id':'other-video-repair','_agent_epoch':3},job)
    job['checkpoint']['video_agent_input_fingerprint']='changed'
    assert repairs.verified_repair(studio,env.state,action,job) is False


def quality_incident(env):
    feedback=[{'kind':'cover','reason':'Actual face in cover'}]
    env.state.update(revision=1,shortcode='reference',run_id='run-1',status='source_wait',script_id='script-1',voice_id='voice-1',edit_id='edit-1',
        daily_quality={'pending':'scene_wait','status':'needs_attention','reviewed_edit_id':'edit-1',
            'feedback':feedback,'reviews':[{'edit_id':'edit-1','passed':False,'issues':feedback}]})
    payload={k:env.state[k] for k in ('script_id','voice_id','edit_id')}
    with env.store.transaction() as db:
        db.execute('UPDATE tasks SET state=? WHERE id=?',(json.dumps(env.state),'task-1'))
        db.execute("UPDATE jobs SET status='done',kind='quality_review',payload=?,checkpoint=? WHERE id='job-1'",
            (json.dumps(payload),json.dumps({'video_agent_input_fingerprint':semantic_fingerprint(env.state)})))


def source_incident(env):
    env.state.update(revision=1,shortcode='reference',run_id='run-1',status='source_wait',
        source_goal={'ready':False},source_search_manifest_path='registered-manifest.json',
        source_acquisition={'hold':{'reason':'strategy_exhausted','details':['No usable approved search plan']},
            'rounds':[{'job_id':'job-1','round':6,'run_id':'run-1','manifest_path':'registered-manifest.json'}]})
    with env.store.transaction() as db:
        db.execute('UPDATE tasks SET state=? WHERE id=?',(json.dumps(env.state),'task-1'))
        db.execute("UPDATE jobs SET status='done',kind='collect_sources',payload=?,checkpoint=? WHERE id='job-1'",
            (json.dumps({'round':6,'run_id':'run-1'}),json.dumps({'manifest':'registered-manifest.json',
                'video_agent_input_fingerprint':semantic_fingerprint(env.state)})))


@pytest.mark.parametrize('clears_hold',[False,True])
def test_done_source_signed_continuation_preserves_hold_and_history(env,clears_hold):
    import copy
    from hotpost.video_agent_actions import execute
    source_incident(env);original=copy.deepcopy(env.state['source_acquisition'])
    rid,review=ready(env);applied=env.pipeline.apply_patch(rid,store=env.store,review_id=review['review_id'])
    def advance(s,db):
        env.store.enqueue(db,s['id'],'collect_sources',{'run_id':'run-1','repair_planning':True},'new-planning')
        if clears_hold:s['source_acquisition'].pop('hold')
    studio=SimpleNamespace(store=env.store,video_repair_pipeline=env.pipeline,_advance_auto=advance,
        loaded_code_receipt={**applied,'process_id':os.getpid(),'loaded_at':time.time()})
    action={'kind':'continue_repaired','job_id':'job-1','repair_id':rid,'_agent_epoch':3,'hypothesis':'Obtain new planning evidence before resolving internal strategy hold'}
    result=execute(studio,'task-1',action,'continue-source',semantic_fingerprint(env.state))
    assert result['status']==('held' if clears_hold else 'queued')
    assert env.store.get('task-1')['source_acquisition']==original
    with env.store.connect() as db:
        assert db.execute("SELECT status FROM jobs WHERE id='job-1'").fetchone()[0]=='done'
        assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==(1 if clears_hold else 2)


@pytest.mark.parametrize('change',['run','round','job','manifest','payload_run','captcha','waiting','receipt','cooldown','ready','foreign'])
def test_done_source_context_rejects_unbound_or_access_waits(env,change):
    from hotpost.video_agent_actions import source_recovery_job
    source_incident(env)
    with env.store.connect() as db:job=dict(db.execute("SELECT * FROM jobs WHERE id='job-1'").fetchone())
    if change=='run':env.state['run_id']='different'
    if change=='round':env.state['source_acquisition']['rounds'][-1]['round']=7
    if change=='job':env.state['source_acquisition']['rounds'][-1]['job_id']='different'
    if change=='manifest':env.state['source_search_manifest_path']='different'
    if change=='payload_run':job['payload']=json.dumps({'round':6,'run_id':'old'})
    if change=='captcha':env.state['source_acquisition']['hold']['reason']='captcha'
    if change=='waiting':env.state['source_acquisition']['waiting']={'searches':[{'status':'login_required'}]}
    if change=='receipt':env.state['source_acquisition']['receipt_wait']={'pending':True}
    if change=='cooldown':job['checkpoint']=json.dumps({'manifest':'registered-manifest.json','not_before':time.time()+999})
    if change=='ready':env.state['source_goal']['ready']=True
    if change=='foreign':job['task_id']='other'
    assert not source_recovery_job(env.state,job)


def test_done_quality_context_signed_apply_load_continue_preserves_original(env):
    from hotpost.video_agent_actions import execute
    quality_incident(env)
    rid,review=ready(env)
    applied=env.pipeline.apply_patch(rid,store=env.store,review_id=review['review_id'])
    studio=SimpleNamespace(store=env.store,video_repair_pipeline=env.pipeline,
        _advance_auto=lambda s,db:env.store.enqueue(db,s['id'],'refresh_sources',{'daily_quality_repair':True},'quality-preparation'))
    action={'kind':'continue_repaired','job_id':'job-1','repair_id':rid,'_agent_epoch':3,'hypothesis':'Resume corrected quality evidence routing'}
    fp=semantic_fingerprint(env.state)
    assert execute(studio,'task-1',action,'before-load',fp)['status']=='held'
    studio.loaded_code_receipt={**applied,'process_id':os.getpid(),'loaded_at':time.time()}
    with env.store.connect() as db:old=dict(db.execute("SELECT * FROM jobs WHERE id='job-1'").fetchone())
    result=execute(studio,'task-1',action,'after-load',fp)
    assert result['status']=='queued' and len(result['job_ids'])==1
    assert execute(studio,'task-1',action,'after-load',fp)==result
    with env.store.connect() as db:assert dict(db.execute("SELECT * FROM jobs WHERE id='job-1'").fetchone())==old
    assert env.store.get('task-1')['daily_quality']==env.state['daily_quality']


@pytest.mark.parametrize('change',['passed','other_edit','other_task','other_script','inactive','paused','access','content','narration','exhausted'])
def test_done_quality_apply_cannot_use_stale_or_held_context(env,change):
    quality_incident(env)
    if change=='passed':env.state['daily_quality']['reviews'][-1]['passed']=True
    if change=='other_edit':env.state['daily_quality']['reviewed_edit_id']='different'
    if change=='other_script':env.state['script_id']='different'
    if change=='inactive':env.state['automation']['active']=False
    if change=='paused':env.state['automation']['paused_by_user']=True
    if change=='access':env.state['source_acquisition']={'waiting':{'searches':[{'status':'captcha'}]}}
    if change=='content':env.state['editorial_content_hold']={'reason':'preserved'}
    if change=='narration':env.state['daily_quality']['narration_context_hold']={'reason':'preserved'}
    if change=='exhausted':env.state['daily_quality']['pending']='exhausted'
    with env.store.transaction() as db:
        db.execute('UPDATE tasks SET state=? WHERE id=?',(json.dumps(env.state),'task-1'))
        db.execute('UPDATE jobs SET checkpoint=? WHERE id=?',(json.dumps({'video_agent_input_fingerprint':semantic_fingerprint(env.state)}),'job-1'))
        if change=='other_task':db.execute("UPDATE jobs SET task_id='foreign' WHERE id='job-1'")
    rid,_=ready(env)
    with pytest.raises(repairs.RepairRejected):env.pipeline.apply_patch(rid,store=env.store)


@pytest.mark.parametrize('behavior',['noop','approve','resurrect','mutate_old','clear_feedback','change_review','remove_review','change_reviewed_edit'])
def test_done_quality_continuation_rolls_back_invalid_workflow(env,behavior):
    from hotpost.video_agent_actions import execute
    quality_incident(env);rid,_=ready(env)
    applied=env.pipeline.apply_patch(rid,store=env.store)
    def advance(s,db):
        if behavior=='noop':s['daily_quality']['pending']='reedit';return
        env.store.enqueue(db,s['id'],'refresh_sources',{},'new')
        if behavior=='approve':s['daily_quality']['status']='passed'
        if behavior=='resurrect':db.execute("UPDATE jobs SET status='queued' WHERE id='job-1'")
        if behavior=='mutate_old':db.execute("UPDATE jobs SET error='cleared' WHERE id='job-1'")
        if behavior=='clear_feedback':s['daily_quality']['feedback']=[]
        if behavior=='change_review':s['daily_quality']['reviews'][-1]['passed']=True
        if behavior=='remove_review':s['daily_quality']['reviews']=[]
        if behavior=='change_reviewed_edit':s['daily_quality']['reviewed_edit_id']='other'
    studio=SimpleNamespace(store=env.store,video_repair_pipeline=env.pipeline,_advance_auto=advance,
        loaded_code_receipt={**applied,'process_id':os.getpid(),'loaded_at':time.time()})
    act={'kind':'continue_repaired','job_id':'job-1','repair_id':rid,'_agent_epoch':3,'hypothesis':'Test transactional rollback'}
    assert execute(studio,'task-1',act,'attempt',semantic_fingerprint(env.state))['status']=='held'
    assert env.store.get('task-1')['daily_quality']==env.state['daily_quality']
    with env.store.connect() as db:
        assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==1
        assert db.execute("SELECT status FROM jobs WHERE id='job-1'").fetchone()[0]=='done'


@pytest.mark.parametrize('historical_status',['applied','review_rejected'])
def test_applied_history_cannot_be_overwritten_by_new_test_or_review(env,historical_status):
    rid,_=ready(env);env.pipeline.apply_patch(rid,store=env.store)
    record=env.pipeline._read(rid);record['status']=historical_status;env.pipeline._save(record)
    before=(env.pipeline._folder(rid)/'repair.json').read_bytes()
    env.pipeline.reviewer=lambda request:pytest.fail('Applied history must not reach a new reviewer')
    for operation in (env.pipeline.test_patch,env.pipeline.review_patch):
        with pytest.raises(repairs.RepairRejected,match='Applied'):operation(rid)
        assert (env.pipeline._folder(rid)/'repair.json').read_bytes()==before


@pytest.mark.parametrize('operation',['test','review'])
def test_apply_during_external_test_or_review_preserves_applied_receipt(env,monkeypatch,operation):
    rid,_=ready(env);applied=[]
    other=repairs.VideoRepairPipeline(env.main,env.renderer,env.pipeline.receipts,
        interpreters=env.pipeline.interpreters,regression_tests=env.pipeline.regressions)
    assert other._record_lock is env.pipeline._record_lock
    def apply():
        other.apply_patch(rid,store=env.store)
        applied.append((env.pipeline._folder(rid)/'repair.json').read_bytes())
    if operation=='test':
        original=repairs.subprocess.run
        def run(*a,**kw):
            result=original(*a,**kw);apply();return result
        monkeypatch.setattr(repairs.subprocess,'run',run)
        call=env.pipeline.test_patch
    else:
        original=env.pipeline.reviewer
        def review(request):
            result=original(request);apply();return result
        env.pipeline.reviewer=review;call=env.pipeline.review_patch
    with pytest.raises(repairs.RepairRejected,match='Applied repair history changed'):call(rid)
    assert applied and (env.pipeline._folder(rid)/'repair.json').read_bytes()==applied[0]
    assert env.pipeline.applied_receipt(rid)['status']=='applied'


def test_failed_regression_cannot_review_or_apply(env):
    repair_id=env.pipeline.propose_patch(proposal(env,body='def combine(a, b):\n    return a - b\n'))
    assert env.pipeline.test_patch(repair_id)['status']=='tests_failed'
    with pytest.raises(repairs.RepairRejected): env.pipeline.review_patch(repair_id)
    with pytest.raises(repairs.RepairRejected): env.pipeline.apply_patch(repair_id,store=env.store)


def test_exact_replacement_retains_source_sha_and_independent_test_gate(env):
    patch=proposal(env);row=patch['files'][0];row.pop('content')
    row['replacements']=[{'old':'return a - b','new':'return a + b'}]
    rid=env.pipeline.propose_patch(patch)
    assert env.pipeline.test_patch(rid)['status']=='tests_passed'
    assert 'return a - b' in (env.main/'hotpost/calculation.py').read_text()


@pytest.mark.parametrize('old',['missing',''])
def test_nonmatching_replacement_does_not_stage_a_repair(env,old):
    patch=proposal(env);row=patch['files'][0];row.pop('content')
    row['replacements']=[{'old':old,'new':'return a + b'}]
    with pytest.raises(repairs.RepairRejected):env.pipeline.propose_patch(patch)


@pytest.mark.parametrize('change',['source','test_log','signature','epoch','paused','inactive','queued','writer'])
def test_changed_evidence_or_nonidle_ownership_blocks_apply(env,change):
    repair_id,review=ready(env)
    if change=='source': write(env.main/'hotpost/dirty_user_work.py','# newer untracked edit\n')
    if change=='test_log': Path(env.pipeline._read(repair_id)['tests'][0]['log_path']).write_text('fake passed')
    if change=='signature':
        record=env.pipeline._read(repair_id);record['review']['signature']='0'*64;env.pipeline._save(record)
    if change in {'epoch','paused','inactive','queued'}:
        with env.store.connect() as db:
            if change=='epoch': db.execute('UPDATE video_agents SET epoch=4')
            elif change=='queued': db.execute("INSERT INTO jobs VALUES('busy','task-1','edit','busy','{}','queued','{}','',0,0)")
            else:
                state=env.state.copy();state['automation']={'active':change!='inactive','paused_by_user':change=='paused'}
                db.execute('UPDATE tasks SET state=?',(json.dumps(state),))
    if change=='writer':
        path=env.store.root.parent/'writing/jobs.sqlite3';path.parent.mkdir()
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE jobs(state TEXT)');db.execute("INSERT INTO jobs VALUES('running')")
    with pytest.raises(repairs.RepairRejected): env.pipeline.apply_patch(repair_id,store=env.store)
    assert 'return a - b' in (env.main/'hotpost/calculation.py').read_text()


def test_partial_apply_rolls_back_dirty_bytes_and_preserves_untracked(env,monkeypatch):
    repair_id,_=ready(env)
    original=repairs._source_replace
    new_test=env.main/'tests/test_new_regression.py'
    def fail_new_test(path,data,expected):
        if path==new_test: raise OSError('simulated write failure')
        return original(path,data,expected)
    monkeypatch.setattr(repairs,'_source_replace',fail_new_test)
    with pytest.raises(OSError): env.pipeline.apply_patch(repair_id,store=env.store)
    assert 'return a - b' in (env.main/'hotpost/calculation.py').read_text()
    assert 'VALUE = 42' in (env.main/'hotpost/dirty_user_work.py').read_text()
    assert not new_test.exists()
    assert env.pipeline._read(repair_id)['status']=='apply_failed'


def test_editor_save_between_check_and_handoff_is_preserved(tmp_path,monkeypatch):
    path=tmp_path/'source.py';path.write_bytes(b'base')
    original=os.rename
    def editor_then_rename(source,dest):
        if source==path:source.write_bytes(b'editor save')
        return original(source,dest)
    monkeypatch.setattr(os,'rename',editor_then_rename)
    with pytest.raises(repairs.RepairRejected,match='Concurrent source'):
        repairs._source_replace(path,b'patch',hashlib.sha256(b'base').hexdigest())
    assert path.read_bytes()==b'editor save'


def test_editor_recreates_path_after_handoff_is_never_overwritten(tmp_path,monkeypatch):
    path=tmp_path/'source.py';path.write_bytes(b'base');original=os.link
    def editor_then_install(source,dest):
        if str(source).endswith('.candidate'):path.write_bytes(b'editor save')
        return original(source,dest)
    monkeypatch.setattr(os,'link',editor_then_install)
    with pytest.raises(FileExistsError):
        repairs._source_replace(path,b'patch',hashlib.sha256(b'base').hexdigest())
    assert path.read_bytes()==b'editor save'
    assert any(p.read_bytes()==b'base' for p in tmp_path.glob('*.preserved'))


def test_process_exit_immediately_after_source_handoff_recovers_before_import(tmp_path):
    import subprocess
    from hotpost.source_loader import restore_missing_sources
    path=tmp_path/'source.py';path.write_bytes(b'VALUE = 7\n')
    code='''import os,sys,hashlib
from pathlib import Path
from hotpost.video_agent_repairs import _source_replace
path=Path(sys.argv[1]);base=hashlib.sha256(path.read_bytes()).hexdigest()
original=os.rename
def crash(source,dest):
    original(source,dest)
    os._exit(91)
os.rename=crash
_source_replace(path,b'VALUE = 8\\n',base)
'''
    result=subprocess.run([sys.executable,'-c',code,str(path)],cwd=Path(__file__).resolve().parents[1])
    assert result.returncode==91 and not path.exists()
    restore_missing_sources(tmp_path)
    assert path.read_bytes()==b'VALUE = 7\n'


def test_audit_harness_rejects_live_filesystem_access(env):
    secret=env.main/'data/secret.json'
    regression=f'from pathlib import Path\ndef test_no_live_access():\n    assert Path({str(secret)!r}).read_text()\n'
    repair_id=env.pipeline.propose_patch(proposal(env,test=regression))
    result=env.pipeline.test_patch(repair_id)
    assert result['status']=='tests_failed'
    assert 'outside isolated roots' in Path(result['tests'][0]['log_path']).read_text('utf-8')


def test_same_model_call_cannot_independently_approve(env):
    repair_id=env.pipeline.propose_patch(proposal(env));env.pipeline.test_patch(repair_id)
    old=env.pipeline.reviewer
    env.pipeline.reviewer=lambda request:{**old(request),'reviewer_call_id':'planner-model-call'}
    with pytest.raises(repairs.RepairRejected,match='Independent reviewer'):env.pipeline.review_patch(repair_id)


def test_premature_successful_process_exit_is_not_a_passing_test(env):
    regression='import os\ndef test_early_exit():\n    assert True\n    os._exit(0)\n'
    repair_id=env.pipeline.propose_patch(proposal(env,test=regression))
    assert env.pipeline.test_patch(repair_id)['status']=='tests_failed'


def test_stage_tampering_cannot_retain_review(env):
    repair_id,_=ready(env)
    write(env.pipeline._folder(repair_id)/'stage/main/hotpost/extra.py','print("injected")\n')
    with pytest.raises(repairs.RepairRejected,match='Unexpected executable'):
        env.pipeline.apply_patch(repair_id,store=env.store)


def test_completed_apply_is_idempotent_after_missing_restart_marker(env):
    repair_id,review=ready(env)
    first=env.pipeline.apply_patch(repair_id,store=env.store,review_id=review['review_id'])
    with env.store.connect() as db:
        db.execute('UPDATE video_agents SET epoch=4')
    # Read-only recovery does not apply the patch a second time or require an
    # obsolete agent epoch; it authenticates exactly the already completed write.
    assert env.pipeline.apply_patch(repair_id,store=env.store,review_id=review['review_id'])==first
    assert env.pipeline.applied_receipt(repair_id)==first
    write(env.main/'hotpost/calculation.py','# subsequent user work\n')
    with pytest.raises(repairs.RepairRejected,match='no longer matches'):
        env.pipeline.apply_patch(repair_id,store=env.store)


def test_applied_recovery_rejects_forged_review_and_partial_apply(env):
    repair_id,_=ready(env)
    with pytest.raises(repairs.RepairRejected,match='completed apply'):
        env.pipeline.applied_receipt(repair_id)
    env.pipeline.apply_patch(repair_id,store=env.store)
    record=env.pipeline._read(repair_id);record['review']['signature']='0'*64;env.pipeline._save(record)
    with pytest.raises(repairs.RepairRejected,match='authenticated'):
        env.pipeline.applied_receipt(repair_id)


def test_only_exact_reviewed_unchanged_repair_is_ready_to_park(env):
    repair_id=env.pipeline.propose_patch(proposal(env))
    assert env.pipeline.ready_to_apply(repair_id) is False
    env.pipeline.test_patch(repair_id)
    assert env.pipeline.ready_to_apply(repair_id) is False
    env.pipeline.review_patch(repair_id)
    assert env.pipeline.ready_to_apply(repair_id)['binding']['job_id']=='job-1'
    write(env.main/'hotpost/dirty_user_work.py','# changed after review\n')
    assert env.pipeline.ready_to_apply(repair_id) is False


@pytest.mark.parametrize('recovers',[None,False,1,'true',True])
def test_signed_review_requires_recovery_of_host_captured_existing_incident(env,recovers):
    p=proposal(env);p['incident']={'task':{'id':'task-1'},'job':{'id':'job-1','error':'Persisted invalid receipt'},'expected_source_attempt_binding':{'product':'new'},'old_descriptor':{'product':''}}
    rid=env.pipeline.propose_patch(p);assert env.pipeline.test_patch(rid)['status']=='tests_passed'
    original=env.pipeline.reviewer
    def review(request):
        assert request['incident']==p['incident'] and 'prevention only' in request['instruction']
        result={**original(request),'recovers_current_incident':recovers}
        if recovers is None:result.pop('recovers_current_incident')
        return result
    env.pipeline.reviewer=review
    if recovers is not True:
        with pytest.raises(repairs.RepairRejected,match='did not approve'):env.pipeline.review_patch(rid)
    else:
        result=env.pipeline.review_patch(rid)
        changed=env.pipeline._read(rid);changed['incident']['job']['error']='hidden';env.pipeline._save(changed)
        with pytest.raises(repairs.RepairRejected,match='signed independent review'):
            env.pipeline.apply_patch(rid,store=env.store,review_id=result['review_id'])


def test_live_runtime_requires_legacy_unapplied_repairs_to_restage_incident(env):
    rid,result=ready(env);env.pipeline.require_incident=True
    with pytest.raises(repairs.RepairRejected,match='prior_repair_id='+rid):
        env.pipeline.apply_patch(rid,store=env.store,review_id=result['review_id'])
    assert env.pipeline._read(rid)['status']=='reviewed'
    assert (env.main/'hotpost/calculation.py').read_text('utf8').endswith('a - b\n')



def test_incident_requirement_preserves_prior_applied_signed_restart_receipt(env):
    rid,review=ready(env)
    expected=env.pipeline.apply_patch(rid,store=env.store,review_id=review['review_id'])
    env.pipeline.require_incident=True
    assert env.pipeline.applied_receipt(rid)==expected



def test_review_attaches_unchanged_staged_validator_and_signs_context(env):
    guard=env.main/'hotpost/source_guard.py';write(guard,'def verify_binding(value):\n    return value == "original"\n')
    p=proposal(env);p['incident']={'job':{'checkpoint':{'failure_trace':{'frames':[{'path':str(guard),'function':'verify_binding'}]}}}}
    p['review_context']=[{'repo':'main','path':'../private.py'}]
    rid=env.pipeline.propose_patch(p);context=env.pipeline._read(rid)['review_context']
    assert len(context)==1 and context[0]['path']=='hotpost/source_guard.py'
    assert context[0]['content']==guard.read_bytes().decode('utf8') and context[0]['sha256']==hashlib.sha256(guard.read_bytes()).hexdigest()
    assert env.pipeline.test_patch(rid)['status']=='tests_passed'
    review=env.pipeline.review_patch(rid)
    assert env.pipeline.review_request(rid)['review_context']==context
    record=env.pipeline._read(rid);record['review_context'][0]['content']='forged validator';env.pipeline._save(record)
    with pytest.raises(repairs.RepairRejected,match='signed independent review'):
        env.pipeline.apply_patch(rid,store=env.store,review_id=review['review_id'])
    assert guard.read_bytes().decode('utf8')==context[0]['content']
