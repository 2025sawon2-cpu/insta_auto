"""Exercise the writer entry point, including its real response decoder."""
import json
import pytest
from hotpost.writing import codex_writer
from hotpost.writing.jobs import Jobs
from hotpost.video_agent_memory import REPAIR_TOOLS, REPAIR_EVIDENCE_TOOLS


@pytest.mark.parametrize('restricted', [False, True])
@pytest.mark.parametrize('kind', sorted(REPAIR_TOOLS | REPAIR_EVIDENCE_TOOLS))
def test_writer_accepts_host_repair_actions(tmp_path, monkeypatch, restricted, kind):
    # Air-tent returned valid continue_repaired JSON after a verified applied
    # repair; the ordinary writer enum rejected it before host validation.
    action={'kind':kind,'hypothesis':'Preserve failed QA and continue through verified repair.',
            'job_id':'job-94bace5b057040a7',
            'repair_id':'repair-870ba6b1e3b44fba9034fcda309b8d2a','evidence':[]}
    raw=json.dumps({'text':json.dumps({'action':action})})
    def external_response(instruction, prompt, schema, check, state, **kwargs):
        check()
        return codex_writer.decode(raw,schema)
    monkeypatch.setattr(codex_writer,'chat',external_response)
    jobs=Jobs(tmp_path)
    evidence={'allowed_actions':sorted(REPAIR_TOOLS | REPAIR_EVIDENCE_TOOLS)} if restricted else {}
    job=jobs.create('video_agent',{'instruction':'choose one action','evidence':evidence})
    jobs.execute(job)
    saved=jobs.get(job['id'])
    assert saved['state']=='completed',saved.get('error')
    assert saved['result']['value']=={'action':action}


@pytest.mark.parametrize('kind,evidence', [
    ('invented_action',{}),
    ('continue_repaired',{'allowed_actions':['inspect_code']}),
    ('invented_action',{'allowed_actions':['invented_action','inspect_code']}),
])
def test_writer_retains_unknown_and_restricted_action_rejection(tmp_path,monkeypatch,kind,evidence):
    raw=json.dumps({'text':json.dumps({'action':{'kind':kind,'hypothesis':'test'}})})
    monkeypatch.setattr(codex_writer,'chat',lambda instruction,prompt,schema,*a,**kw:codex_writer.decode(raw,schema))
    jobs=Jobs(tmp_path);job=jobs.create('video_agent',{'instruction':'test','evidence':evidence})
    jobs.execute(job)
    assert jobs.get(job['id'])['state']=='failed'


@pytest.mark.parametrize('kind,expected',[('inspect_code','completed'),('invented_action','failed')])
def test_literal_working_note_newlines_reach_real_writer_schema(tmp_path,monkeypatch,kind,expected):
    value={'action':{'kind':kind,'hypothesis':'Inspect preserved recovery worker.',
                    'repo':'main','path':'hotpost/source_finder.py','offset':45000,'limit':14000},
           'working_notes':'원인 확인\n기존 번들 보존\r\n다음 단계\t수정 검증'}
    # The actual failed owner response had valid outer JSON but raw linebreaks
    # inside working_notes. Its model format-repair returned the same bytes.
    inner=json.dumps(value,ensure_ascii=False).replace('\\n','\n').replace('\\r','\r').replace('\\t','\t')
    with pytest.raises(json.JSONDecodeError):json.loads(inner)
    raw=json.dumps({'text':inner})
    monkeypatch.setattr(codex_writer,'chat',lambda instruction,prompt,schema,*a,**kw:codex_writer.decode(raw,schema))
    jobs=Jobs(tmp_path);job=jobs.create('video_agent',{'instruction':'test','evidence':{}})
    jobs.execute(job);saved=jobs.get(job['id'])
    assert saved['state']==expected
    if expected=='completed':assert saved['result']['value']==value


def test_multiline_source_and_quoted_backslashes_keep_exact_values():
    value={'content':'def run():\n    return "C:\\\\source\\\\file"\n','literal':'\\n stays two characters'}
    encoded=json.dumps(value).replace('():\\n','():\n')
    assert codex_writer.structured_json(encoded)==value


@pytest.mark.parametrize('raw',['{"x":"a\x00b"}','{"x":"a\\\nb"}','{"x":"a\nb",}'])
def test_encoding_repair_does_not_accept_other_malformed_json(raw):
    with pytest.raises(json.JSONDecodeError):codex_writer.structured_json(raw)
