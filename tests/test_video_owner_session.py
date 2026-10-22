import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from hotpost.writing import codex_writer,owner_session


BINDING={'task_id':'work-0123456789abcdef','run_id':'run-0123456789abcdef','epoch':1}


def state(root,name,**binding):
    return {'directory':root/name,'calls':[],'purpose':'video_agent',
            'owner_conversation':{**BINDING,**binding}}


def response(output,thread,*,text='ok',error=None,exit_code=1):
    if error is not None:
        return [sys.executable,'-c',f'import sys;sys.stderr.write({error!r});sys.exit({exit_code})']
    code='import json;from pathlib import Path;'
    code+=f'Path({str(output)!r}).write_text(json.dumps({dict(text=text)!r}),encoding="utf8");'
    for event in [{'type':'thread.started','thread_id':thread},{'type':'turn.completed','usage':{}}]:
        code+=f'print(json.dumps({event!r}),flush=True);'
    return [sys.executable,'-c',code]


def test_real_bridge_reuses_exact_owner_and_separates_run_epoch_task(tmp_path,monkeypatch):
    calls=[]
    def transport(binary,cwd,schema,output,thread):
        calls.append((str(cwd),thread));return response(output,thread or str(uuid4()))
    monkeypatch.setattr(codex_writer,'executable',lambda:sys.executable)
    monkeypatch.setattr(owner_session,'command',transport)
    first=state(tmp_path,'first');second=state(tmp_path,'second')
    assert codex_writer.chat('rules','first',None,lambda:None,first)=='ok'
    thread=first['calls'][0]['owner_conversation']['thread_id']
    assert codex_writer.chat('rules','followup',None,lambda:None,second)=='ok'
    assert calls[0][1] is None and calls[1][1]==thread and calls[0][0]==calls[1][0]
    for n,change in enumerate([{'epoch':2},{'run_id':'run-aaaaaaaaaaaaaaaa'},{'task_id':'work-bbbbbbbbbbbbbbbb'}]):
        codex_writer.chat('rules','separate',None,lambda:None,state(tmp_path,str(n),**change))
        assert calls[-1][1] is None and calls[-1][0]!=calls[0][0]


def test_missing_rollout_recovers_once_without_resetting_production_evidence(tmp_path,monkeypatch):
    calls=[];thread=str(uuid4())
    def transport(binary,cwd,schema,output,saved):
        calls.append(saved)
        if saved:return response(output,saved,error=f'Error: thread/resume: thread/resume failed: no rollout found for thread id {saved} (code -32600)\n')
        return response(output,thread if len(calls)==1 else str(uuid4()))
    monkeypatch.setattr(codex_writer,'executable',lambda:sys.executable)
    monkeypatch.setattr(owner_session,'command',transport)
    codex_writer.chat('rules','first',None,lambda:None,state(tmp_path,'first'))
    next_state=state(tmp_path,'next')
    assert codex_writer.chat('rules','host durable evidence',None,lambda:None,next_state)=='ok'
    assert calls==[None,thread,None]
    assert next_state['calls'][0]['error_type']=='MissingOwnerConversation'
    archived=list((tmp_path/'owner-sessions').glob('*/missing-*.json'))
    assert len(archived)==1 and json.loads(archived[0].read_text('utf8'))['thread_id']==thread


def test_auth_failure_never_resets_or_substitutes_owner_conversation(tmp_path,monkeypatch):
    calls=[];thread=str(uuid4())
    def transport(binary,cwd,schema,output,saved):
        calls.append(saved)
        return response(output,thread,error='Unauthorized: login required' if saved else None)
    monkeypatch.setattr(codex_writer,'executable',lambda:sys.executable)
    monkeypatch.setattr(owner_session,'command',transport)
    codex_writer.chat('rules','first',None,lambda:None,state(tmp_path,'first'))
    with pytest.raises(RuntimeError):codex_writer.chat('rules','second',None,lambda:None,state(tmp_path,'second'))
    assert calls==[None,thread]
    record=next((tmp_path/'owner-sessions').glob('*/session.json'))
    assert json.loads(record.read_text('utf8'))['thread_id']==thread
    assert not list((tmp_path/'owner-sessions').glob('*/missing-*.json'))


@pytest.mark.parametrize('exit_code',[2,7])
def test_missing_error_text_with_different_exit_code_cannot_reset_session(tmp_path,monkeypatch,exit_code):
    calls=[];thread=str(uuid4())
    def transport(binary,cwd,schema,output,saved):
        calls.append(saved)
        error=f'Error: thread/resume: thread/resume failed: no rollout found for thread id {saved} (code -32600)\n' if saved else None
        return response(output,thread,error=error,exit_code=exit_code)
    monkeypatch.setattr(codex_writer,'executable',lambda:sys.executable)
    monkeypatch.setattr(owner_session,'command',transport)
    codex_writer.chat('rules','first',None,lambda:None,state(tmp_path,'first'))
    record=next((tmp_path/'owner-sessions').glob('*/session.json'));before=record.read_bytes()
    with pytest.raises(RuntimeError):codex_writer.chat('rules','second',None,lambda:None,state(tmp_path,'second'))
    assert calls==[None,thread] and record.read_bytes()==before
    assert not list((tmp_path/'owner-sessions').glob('*/missing-*.json'))


def test_context_rejects_wrong_identity_and_concurrent_use(tmp_path):
    value=state(tmp_path,'one')
    with owner_session.conversation(value) as context:
        with pytest.raises(ValueError):
            with owner_session.conversation(state(tmp_path,'two')):pass
        thread=str(uuid4());owner_session.accept(context,[{'type':'thread.started','thread_id':thread}],'first')
    with owner_session.conversation(value) as context:
        with pytest.raises(ValueError,match='different'):
            owner_session.accept(context,[{'type':'thread.started','thread_id':str(uuid4())}],'wrong')
        assert json.loads(context['path'].read_text('utf8'))['thread_id']==thread
    with pytest.raises(ValueError):
        with owner_session.conversation(state(tmp_path,'bad',task_id='../other')):pass


def test_review_and_format_repair_remain_independent_ephemeral_calls(tmp_path,monkeypatch):
    persistent=[];ephemeral=[];thread=str(uuid4())
    def owner_transport(binary,cwd,schema,output,saved):
        persistent.append(saved);return response(output,thread,text='{"ok":true,}')
    def plain_transport(binary,cwd,schema,output,**kw):
        ephemeral.append(cwd);return response(output,str(uuid4()),text='{"ok":true}')
    monkeypatch.setattr(codex_writer,'executable',lambda:sys.executable)
    monkeypatch.setattr(owner_session,'command',owner_transport)
    monkeypatch.setattr(codex_writer,'command',plain_transport)
    schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']}
    value=state(tmp_path,'owner')
    assert codex_writer.chat('rules','data',schema,lambda:None,value)=={'ok':True}
    assert persistent==[None] and len(ephemeral)==1 and '_owner_context' not in value
    review=state(tmp_path,'review');review['purpose']='repair_review'
    assert codex_writer.chat('independent','data',schema,lambda:None,review)=={'ok':True}
    assert len(persistent)==1 and len(ephemeral)==2


def test_both_owner_commands_keep_read_only_no_tools_or_model_override():
    for thread in [None,str(uuid4())]:
        args=owner_session.command('codex','context','schema','output',thread)
        assert '--ephemeral' not in args and '--ignore-user-config' in args
        assert args[args.index('--sandbox')+1]=='read-only' and 'shell_tool' in args
        assert 'web_search="disabled"' in args and 'approval_policy="never"' in args
        assert '-m' not in args and '--last' not in args and '--dangerously-bypass-approvals-and-sandbox' not in args
        assert ('resume' in args)==(thread is not None)


def test_jobs_passes_host_conversation_binding_only_to_owner(tmp_path,monkeypatch):
    from hotpost.writing.jobs import Jobs
    seen=[]
    def chat(instruction,prompt,schema,check,st,**kwargs):
        seen.append(st.copy());return {'action':{'kind':'wait','hypothesis':'named dependency'}}
    monkeypatch.setattr(codex_writer,'chat',chat)
    jobs=Jobs(tmp_path)
    for kind in ['video_agent','repair_review']:
        job=jobs.create(kind,{'instruction':'test','evidence':{},'owner_conversation':BINDING})
        jobs.execute(job)
        assert jobs.get(job['id'])['state']=='completed'
    assert seen[0]['owner_conversation']==BINDING and 'owner_conversation' not in seen[1]


@pytest.mark.parametrize('tamper',[None,'digest','binding','unrelated_failure'])
def test_missing_resume_result_survives_db_commit_crash_only_with_exact_replacement(tmp_path,monkeypatch,tamper):
    from hotpost.writing.jobs import Jobs
    thread=str(uuid4());calls=[]
    answer=json.dumps({'action':{'kind':'wait','hypothesis':'confirmed service dependency'}})
    def transport(binary,cwd,schema,output,saved):
        calls.append(saved)
        if saved:return response(output,saved,error=f'Error: thread/resume: thread/resume failed: no rollout found for thread id {saved} (code -32600)\n')
        return response(output,thread if len(calls)==1 else str(uuid4()),text=answer)
    monkeypatch.setattr(codex_writer,'executable',lambda:sys.executable)
    monkeypatch.setattr(owner_session,'command',transport)
    jobs=Jobs(tmp_path);payload={'instruction':'test','evidence':{},'owner_conversation':BINDING}
    first=jobs.create('video_agent',payload);jobs.execute(first)
    assert jobs.get(first['id'])['state']=='completed'
    second=jobs.create('video_agent',payload);jobs.update(second['id'],state='running')
    update=jobs.update
    def crash(jid,**values):
        if jid==second['id'] and values.get('state')=='completed':raise SystemExit('simulated DB commit crash')
        return update(jid,**values)
    monkeypatch.setattr(jobs,'update',crash)
    with pytest.raises(SystemExit):jobs.execute(second)
    folder=tmp_path/second['id'];saved=json.loads((folder/'result.json').read_text('utf8'))
    if tamper:
        for path in folder.glob('codex-*/receipt.json'):
            receipt=json.loads(path.read_text('utf8'))
            if tamper=='digest':receipt['decoded_value_sha256']='wrong'
            elif tamper=='binding':receipt['owner_conversation']['binding']['task_id']='work-ffffffffffffffff'
            elif receipt.get('status')=='failed':receipt['error_type']='OtherTransportFailure'
            path.write_text(json.dumps(receipt),'utf8')
            for i,row in enumerate(saved['inference']['calls']):
                if row['call_id']==receipt['call_id']:saved['inference']['calls'][i]=receipt
        (folder/'result.json').write_text(json.dumps(saved),'utf8')
    resumed=Jobs(tmp_path).get(second['id'])
    assert resumed['state']==('running' if tamper else 'completed')
    assert calls==[None,thread,None]  # No repeated inference or production action.
    if tamper is None:assert resumed['result']['value']==json.loads(answer)


@pytest.mark.parametrize('corrupt',[b'not json',json.dumps({'binding':{'task_id':'another'},'thread_id':str(uuid4())}).encode()])
def test_corrupt_registry_is_preserved_and_never_resumes_foreign_thread(tmp_path,corrupt):
    value=state(tmp_path,'one')
    with owner_session.conversation(value) as context:
        path=context['path'];path.write_bytes(corrupt)
    with owner_session.conversation(value) as context:
        assert context['thread_id'] is None and context['binding']==BINDING
        assert context['reset_reason']=='invalid_local_conversation_registry'
        archives=list(path.parent.glob('invalid-*.json'))
        assert len(archives)==1 and archives[0].read_bytes()==corrupt
