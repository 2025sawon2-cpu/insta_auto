import json
import threading
import pytest
from hotpost.config import Settings
from hotpost.studio_adapter import StudioAdapter
from hotpost.writing import pipeline
from hotpost.writing.contract import snapshot
from hotpost.writing.jobs import Jobs

REFERENCE='차문에 끼워서 컵을 놓고 휴대폰을 세울 수 있어요. 댓글에 홀더 남겨주세요.'
DRAFT='컵 놓을 자리가 모자라요? 문 쪽에 걸어 음료 자리를 하나 늘려요. 폰도 세워둘 수 있어요. 댓글에 나도 남겨주세요.'


def test_model_orphan_recovery_requires_exclusive_worker_lease(tmp_path):
    from hotpost.production import file_lock
    jobs=Jobs(tmp_path);job=jobs.create('video_agent',{'evidence':{},'instruction':'test'})
    jobs.update(job['id'],state='running')
    with file_lock(tmp_path/'worker.lock'):
        assert jobs.recover_abandoned(job['id'],[])=='owned_by_active_writer'
        assert jobs.get(job['id'])['state']=='running'
    assert jobs.recover_abandoned(job['id'],[])=='recovered'
    assert jobs.get(job['id'])['state']=='interrupted'


def test_model_orphan_watch_uses_actual_content_not_heartbeat(tmp_path):
    jobs=Jobs(tmp_path);job=jobs.create('video_agent',{'evidence':{},'instruction':'test'})
    path=tmp_path/job['id']/'codex-test'/'events.jsonl';path.parent.mkdir()
    path.write_text(json.dumps({'type':'heartbeat'}))
    before=jobs.progress_receipt(job['id'])
    path.write_text(json.dumps({'type':'heartbeat'})+'\n'+json.dumps({'type':'heartbeat'}))
    assert jobs.progress_receipt(job['id'])==before
    path.write_text(json.dumps({'type':'item.completed','item':{'text':'new model reasoning'}}))
    assert jobs.recover_abandoned(job['id'],before)=='progress_resumed'
    assert jobs.get(job['id'])['state']=='queued'


def test_orphan_script_cannot_permanently_block_new_video_owner(tmp_path,monkeypatch):
    jobs=Jobs(tmp_path);old=jobs.create('script',{});jobs.update(old['id'],state='running')
    new=jobs.create('video_agent',{'instruction':'recover','evidence':{}});clock=[1000]
    monkeypatch.setattr('hotpost.writing.jobs.time.time',lambda:clock[0])
    monkeypatch.setattr(jobs,'active_children',lambda jid:jid==old['id'])
    restored=[]
    def recover(jid,progress):
        restored.append(jid);jobs.update(jid,state='interrupted');return 'recovered'
    monkeypatch.setattr(jobs,'_recover_without_owner',recover)
    monkeypatch.setattr(jobs,'execute',lambda j:jobs.update(j['id'],state='completed',result={'value':{}}))
    jobs.work();assert jobs.get(new['id'])['state']=='queued' and not restored
    clock[0]+=901;jobs.work()
    assert restored==[old['id']] and jobs.get(new['id'])['state']=='completed'

def run(tmp_path, monkeypatch, replies):
    calls=[]
    def chat(instruction, data, schema, check, state):
        assert state['purpose'] == 'script_writing'
        calls.append((instruction,json.loads(data)))
        value=replies[len(calls)-1]
        if isinstance(value,Exception):raise value
        return value
    monkeypatch.setattr(pipeline.codex_writer,'chat',chat)
    value=pipeline._generate_single({'reference_script':REFERENCE,'writing_contract':snapshot()},tmp_path,lambda:None,lambda *a:None)
    return value,calls,json.loads((tmp_path/'writing-audit.json').read_text('utf-8'))

def test_per_variant_review_is_bounded_and_preserves_clean_draft(tmp_path,monkeypatch):
    result,calls,audit=run(tmp_path,monkeypatch,[{'text':DRAFT},{'issues':[]}])
    assert len(calls)==2 and len(result['scripts'])==1
    assert result['scripts'][0]['text']==DRAFT and not audit['repair']['attempted']
    assert all(snapshot()['prompt'] in instruction for instruction,_ in calls)
    assert 'sources' not in calls[0][1]

def test_repair_bounded_and_worse_copy_does_not_replace_original(tmp_path,monkeypatch):
    result,calls,audit=run(tmp_path,monkeypatch,[{'text':DRAFT},
        {'issues':[{'quote':'음료 자리를 하나 늘려요','reason':'문장을 다듬어 주세요'}]},
        {'text':REFERENCE},{'preferred':1,'reason':'잘못된 모델 선호','issues':[]}])
    assert len(calls)==4 and result['scripts'][0]['text']==DRAFT
    assert audit['repair']['attempted'] and not audit['repair']['accepted']


@pytest.mark.parametrize('mode', ['benchmark', 'self_shot'])
def test_flexible_structure_reaches_generation_review_repair_and_comparison(tmp_path, monkeypatch, mode):
    # Four sentences merge hook/context and resolution/empathy. The contract
    # must reach every model stage without code splitting or padding the draft.
    draft = ('꺼내 둔 물건이 늘었는데 조리대는 넓어졌어요! '
             '시트에 자석 수납함을 붙이니 바로 집어 쓸 수 있어서 편한 거 있죠? '
             '좋은 점을 다시 말해요. 댓글에 나도 남겨주세요.')
    revised = draft.replace('좋은 점을 다시 말해요. ', '')
    replies = iter([{'text': draft},
                    {'issues': [{'quote': '좋은 점을 다시 말해요.', 'reason': '공감 뒤 반복 삭제'}]},
                    {'text': revised}, {'preferred': 1, 'reason': '반복 제거', 'issues': []}])
    contract = snapshot('self_shot' if mode == 'self_shot' else None)
    calls = []
    def chat(instruction, data, schema, check, state):
        calls.append(instruction)
        assert contract['prompt'] in instruction
        assert '후킹 → 상황 설정 → 문제 해소 → 공감 → CTA' in instruction
        assert '별도 문장 없이 문제 해소로 넘어간다' in instruction
        assert '욕구 충족과 후킹에서 생긴 의문의 해소' in instruction
        assert '고정된 갈등·전개 순서를 강제하지 않는다' not in instruction
        assert '원작의 메커니즘·흐름을 유지' not in instruction
        return next(replies)
    monkeypatch.setattr(pipeline.codex_writer, 'chat', chat)
    monkeypatch.setattr(pipeline, 'review', lambda text, *args, **kwargs: {
        'text': text, 'integrity_review': {'issues': []},
        'naturalness_review': {'issues': []}, 'quality_summary': {'issues': []}})
    result = pipeline._generate_single({
        'reference_script': '자석 수납함을 붙일 수 있는 시트',
        'generation_mode': mode, 'writing_contract': contract},
        tmp_path, lambda: None, lambda *args: None)
    assert len(calls) == 4
    assert result['scripts'][0]['text'] == revised
    audit = json.loads((tmp_path/'writing-audit.json').read_text('utf-8'))
    assert audit['initial_text'] == draft and audit['repair']['accepted']

def test_review_failure_is_advisory_and_retains_text(tmp_path,monkeypatch):
    result,calls,_=run(tmp_path,monkeypatch,[{'text':DRAFT},RuntimeError('offline')])
    assert len(calls)==2 and result['scripts'][0]['text']==DRAFT
    assert result['scripts'][0]['quality_summary']['status']=='not_evaluated'
    assert result['warnings']


def test_copy_repair_receives_the_actual_copied_quote_and_reference_span(tmp_path, monkeypatch):
    result,calls,audit=run(tmp_path,monkeypatch,[{'text':REFERENCE}, {'issues':[]},
        {'text':DRAFT}, {'preferred':1,'reason':'Copied wording was rewritten with the same function','issues':[]}])
    assert len(calls)==4
    findings=calls[2][1]['findings']['integrity']
    copy_findings=[f for f in findings if f['severity']=='copy']
    assert copy_findings
    assert all(f['quote'] in REFERENCE and f['source_quote'] in REFERENCE for f in copy_findings)
    assert result['scripts'][0]['text']==DRAFT and audit['repair']['accepted']


def test_editorial_repair_keeps_quote_connected_to_its_reason(tmp_path, monkeypatch):
    issue={'quote':'음료 자리를 하나 늘려요','reason':'같은 동작의 표현을 더 자연스럽게 바꿔 주세요'}
    result,calls,_=run(tmp_path,monkeypatch,[{'text':DRAFT}, {'issues':[issue]},
        {'text':DRAFT}, {'preferred':0,'reason':'No verified improvement','issues':[]}])
    assert calls[2][1]['findings']['editorial']==[issue]
    assert result['scripts'][0]['text']==DRAFT

def test_empty_draft_is_technical_failure(tmp_path,monkeypatch):
    with pytest.raises(ValueError,match='빈 대본'):run(tmp_path,monkeypatch,[{'text':' '}])


def test_short_nonempty_reference_reaches_codex_without_length_gate(tmp_path,monkeypatch):
    calls=[]
    def chat(instruction,data,schema,check,state):
        calls.append(json.loads(data))
        if len(calls)==1:return {'text':'설치하기 번거롭죠? 펼쳐서 바로 쓸 수 있어요. 댓글에 나도 남겨주세요.'}
        if len(calls)==2:return {'issues':[]}
        if len(calls)==3:return {'text':'설치가 번거롭죠? 펼쳐 놓으면 바로 쓸 수 있어요. 댓글에 나도 남겨주세요.'}
        return {'preferred':0,'reason':'원고 보존','issues':[]}
    monkeypatch.setattr(pipeline.codex_writer,'chat',chat)
    result=pipeline._generate_single({'reference_script':'펼치면 끝이에요!','writing_contract':snapshot()},tmp_path,lambda:None,lambda *a:None)
    assert result['scripts'] and calls[0]['reference']=='펼치면 끝이에요!'

def test_queue_durable_and_does_not_duplicate_active_work(tmp_path,monkeypatch):
    jobs=Jobs(tmp_path);job=jobs.create('script',{'reference':'fixture'})
    entered=threading.Event();release=threading.Event();calls=[]
    def execute(item):
        calls.append(item['id']);entered.set();release.wait(5)
        jobs.update(item['id'],state='completed',result={'fixture':True})
    monkeypatch.setattr(jobs,'execute',execute)
    jobs.start();assert entered.wait(3)
    duplicate=Jobs(tmp_path)
    monkeypatch.setattr(duplicate,'execute',lambda _:pytest.fail('duplicate worker'))
    duplicate.start()
    assert duplicate.create('script',{'reference':'fixture'})['id']==job['id']
    release.set()
    from hotpost.writing.jobs import _threads
    _threads[str(jobs.path.resolve())].join(4)
    assert calls==[job['id']]
    assert Jobs(tmp_path).get(job['id'])['result']=={'fixture':True}

def test_surviving_child_is_not_marked_interrupted_or_relaunched(tmp_path,monkeypatch):
    jobs=Jobs(tmp_path);job=jobs.create('script',{})
    jobs.update(job['id'],state='running')
    monkeypatch.setattr(jobs,'active_children',lambda _:True)
    monkeypatch.setattr(jobs,'execute',lambda _:pytest.fail('duplicate'))
    jobs.work()
    assert jobs.get(job['id'])['state']=='running'

def test_archived_job_read_without_external_service(tmp_path):
    adapter=StudioAdapter(Settings(data_dir=tmp_path))
    target=adapter.jobs.root/'legacy'/'a123.json';target.parent.mkdir()
    target.write_text(json.dumps({'id':'a123','state':'completed','result':{'scripts':[{'text':DRAFT}]}}),'utf-8')
    assert adapter.get('a123')['result']['scripts'][0]['text']==DRAFT
