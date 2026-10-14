import json,sys,time
import pytest
from hotpost.writing import codex_writer
from hotpost import model_service

ACTUAL=[{'type':'error','message':'exceeded retry limit, last status: 429 Too Many Requests'},
        {'type':'turn.failed','error':{'message':'exceeded retry limit, last status: 429 Too Many Requests'}}]


def test_exact_terminal_cli_429_and_nested_error_are_typed():
    result=codex_writer.classify_service_failure(ACTUAL,now=100)
    assert result=={'reason':'model_rate_limit','http_status':429,'event_indices':[0,1], 'retry_after_values':[], 'provider_retry_at':None}


@pytest.mark.parametrize('events',[
    [{'type':'item.completed','item':{'text':'exceeded retry limit, last status: 429 Too Many Requests'}}],
    [{'type':'turn.completed','message':'HTTP 429 Too Many Requests'}],
    [{'type':'error','message':'제품 설명에 429라는 숫자가 있음'}],
    [{'type':'error','error':{'data':{'text':'HTTP 429 Too Many Requests'}}}],
    [{'type':'error','status_code':True}],
    [{'type':'error','status_code':'429products'}],
    [{'type':'error','message':'source quote: exceeded retry limit, last status: 429 Too Many Requests'}],
])
def test_source_body_model_output_or_unknown_status_are_not_service_evidence(events):
    assert codex_writer.classify_service_failure(events,now=100) is None


@pytest.mark.parametrize('value,expected',[('120',220),(120,220),('Thu, 01 Jan 1970 00:03:20 GMT',200),
    (True,None),(-4,None),('unknown-unit',None),({'seconds':90},None),(float('inf'),None)])
def test_retry_after_only_parses_explicit_http_or_seconds(value,expected):
    result=codex_writer.classify_service_failure([{'type':'turn.failed','error':{'status_code':429,'headers':{'Retry-After':value}}}],now=100)
    assert result['provider_retry_at']==expected
    assert result['retry_after_values']==[value]


def test_capacity_gate_never_shortens_existing_or_provider_cooldown(tmp_path,monkeypatch):
    monkeypatch.setattr(model_service.time,'time',lambda:100)
    monkeypatch.setattr(model_service.random,'uniform',lambda *a:1)
    assert model_service.capacity_failure(tmp_path,retry_at=400)==400
    assert model_service.capacity_failure(tmp_path,retry_at=200)==400
    with model_service.database(tmp_path) as db:
        row=db.execute('select failures,retry_at from capacity').fetchone()
    assert row==(2,400)
    with pytest.raises(model_service.ModelServiceUnavailable) as held:model_service.before_call(tmp_path)
    assert held.value.retry_at==400 and held.value.attempted is False


def process_command(events, *, success=False):
    def command(binary,directory,schema,output,**kwargs):
        code='import json,sys;'
        if success:code+=f'open({str(output)!r},"w").write(json.dumps({{"text":"ok"}}));'
        for event in events:code+=f'print(json.dumps({event!r}),flush=True);'
        code+='sys.exit('+('0' if success else '1')+')'
        return [sys.executable,'-c',code]
    return command


def test_terminal_429_holds_once_preserves_event_receipt_and_prevents_resubmission(tmp_path,monkeypatch):
    monkeypatch.setattr(codex_writer,'executable',lambda:sys.executable)
    monkeypatch.setattr(codex_writer,'command',process_command(ACTUAL))
    state={'directory':tmp_path,'calls':[]}
    with pytest.raises(model_service.ModelServiceUnavailable):codex_writer.chat('rules','data',None,lambda:None,state)
    assert len(state['calls'])==1 and state['calls'][0]['error_reason']=='model_rate_limit'
    raw=list(tmp_path.glob('codex-*/events.jsonl'))[0].read_bytes()
    with pytest.raises(model_service.ModelServiceUnavailable) as held:codex_writer.chat('rules','data',None,lambda:None,state)
    assert held.value.attempted is False and len(state['calls'])==1
    assert list(tmp_path.glob('codex-*/events.jsonl'))[0].read_bytes()==raw


def test_completed_response_is_reused_despite_intermediate_429(tmp_path,monkeypatch):
    monkeypatch.setattr(codex_writer,'executable',lambda:sys.executable)
    monkeypatch.setattr(codex_writer,'command',process_command([ACTUAL[0],{'type':'turn.completed'}],success=True))
    state={'directory':tmp_path,'calls':[]}
    assert codex_writer.chat('rules','data',None,lambda:None,state)=='ok'
    assert len(state['calls'])==1 and state['calls'][0]['status']=='completed'
    with model_service.database(tmp_path) as db:assert db.execute('select failures from capacity').fetchone()[0]==0



def test_api_specific_retry_field_has_no_assumed_units():
    result=codex_writer.classify_service_failure([{'type':'turn.failed','error':{'status_code':429,'retry_after':120000,'retryAfter':120000}}],now=100)
    assert result['provider_retry_at'] is None


def test_existing_capacity_message_uses_same_typed_transport_boundary():
    assert codex_writer.classify_service_failure([{'type':'turn.failed','error':{'message':'model is at capacity'}}])['reason']=='model_capacity'
    assert codex_writer.classify_service_failure([{'type':'item.completed','item':{'text':'model is at capacity'}}]) is None
