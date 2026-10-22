import copy, hashlib, importlib.util, json, sys
from pathlib import Path
from uuid import uuid4
import pytest
ROOT=Path(__file__).resolve().parents[1]
from hotpost import video_agent_payload as candidate
CAPTURE=ROOT/'data/writing/codexa65afbaad5c2d2e931d01cdd8241d3fe/payload.json'
RID='repair-1ddf40badf5d4a1180b4fdd29a9c64f1'

def test_actual_failed_diagnostics_delivers_causal_expression_and_correct_reread():
    if not CAPTURE.is_file():pytest.skip('Optional preserved actual diagnostic payload')
    raw=CAPTURE.read_bytes();payload=json.loads(raw)
    wire=candidate.owner_prompt(payload['instruction'],payload['evidence'],[],{})
    value=json.loads(wire)['evidence'];prev=value['previous_steps']
    assert 'StopIteration' in wire and "fixture['artifacts']" in wire
    assert 'test_captured_refresh_received_resume.py:42' in wire
    assert candidate.input_bytes(payload['instruction'],wire,{})<=candidate.MAX_INPUT_BYTES
    assert prev['latest_complete_read']['result']['content']==payload['evidence']['previous_steps'][8]['result']['content']
    readers=[]
    def walk(x):
        if isinstance(x,dict):
            if x.get('failure_summary') and x.get('log_sha256'):
                assert x['diagnostics_read_again']=={'kind':'inspect_repair','repair_id':RID}
                readers.append(x)
            for v in x.values():walk(v)
        elif isinstance(x,list):
            for v in x:walk(v)
    walk(prev)
    assert readers and CAPTURE.read_bytes()==raw

def test_large_command_cannot_consume_failure_context_budget():
    text="    def captured(path):\n>       return next(a['content'] for a in fixture['artifacts'])\n    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nE       StopIteration\n\ntests/test_capture.py:42: StopIteration\nFAILED tests/test_capture.py::test_real"
    value={'repair_id':RID,'tests':[{'log_path':'verified.log','log_sha256':'a'*64,'passed':False,'returncode':1,'command':['x'*10000]*10,'log_excerpt':text*30}]}
    before=copy.deepcopy(value)
    projected=candidate._fit(value,8192,('previous_steps',))
    wire=json.dumps(projected)
    assert "fixture['artifacts']" in wire and 'test_capture.py:42' in wire
    assert value==before and candidate._size(projected)<=8192

def test_summary_deduplicates_and_keeps_utf8_escaping_bound():
    text=('E AssertionError: External call count before=6 after=8\n'+'> quoted\\\"😀\n')*5000
    lines=candidate._failure_summary(text)
    assert len(lines)==len(set(lines))<=24 and candidate._size(lines)<=6144
    assert 'External call count before=6 after=8' in ''.join(lines)

def test_real_writer_actual_failed_payload_keeps_cause_and_saved_original(tmp_path,monkeypatch):
    if not CAPTURE.is_file():pytest.skip('Optional preserved actual diagnostic payload')
    from hotpost import video_agent_payload
    from hotpost.writing import codex_writer,owner_session
    from hotpost.writing.jobs import Jobs
    sys.path.insert(0,str(ROOT/'tests'))
    from test_video_owner_session import response
    raw=CAPTURE.read_bytes();payload=json.loads(raw);before=copy.deepcopy(payload)
    expected={'action':{'kind':'inspect_repair','repair_id':RID,'hypothesis':'Inspect the exact SHA-bound test diagnostics.'}}
    calls=[]
    def transport(binary,cwd,schema,output,thread):
        request=(Path(output).parent/'request.txt').read_bytes();calls.append(len(request))
        assert b'fixture' in request and b'StopIteration' in request and b':42' in request
        assert len(request)<candidate.MAX_INPUT_BYTES
        return response(output,thread or str(uuid4()),text=json.dumps(expected))
    monkeypatch.setattr(codex_writer,'executable',lambda:sys.executable)
    monkeypatch.setattr(owner_session,'command',transport)
    jobs=Jobs(tmp_path/'writing');job=jobs.create('video_agent',payload)
    saved=jobs.root/job['id']/'payload.json';stored=saved.read_bytes()
    jobs.execute(job);finished=jobs.get(job['id'])
    assert finished['state']=='completed',finished.get('error')
    assert finished['result']['value']==expected and len(calls)==1
    assert saved.read_bytes()==stored and CAPTURE.read_bytes()==raw and payload==before
