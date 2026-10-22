import copy
import inspect
import json
import os
from pathlib import Path

import pytest
from PIL import Image
from hotpost import source_visual_queries as visual
from hotpost.config import Settings


def test_preserved_failed_child_cache_route(tmp_path, monkeypatch):
    captured = json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    incident = copy.deepcopy(captured)
    task, job = incident['task'], incident['job']
    assert job['id'] == 'job-7acdf5827d1d4127'
    assert job['status'] == 'failed'
    assert job['task_id'] == task['id']
    assert job['payload']['run_id'] == task['run_id']
    assert job['payload']['planning_recovery_from'] == 'job-485595b8bd9e412d'
    assert job['checkpoint']['failure_trace']['type'] == 'FileNotFoundError'
    # Preserve the full failed checkpoint and history for the real retry gate.
    # Signed repair verification and durable retry/claim are host-pinned; this
    # incident-specific branch connects that contract to the cache entry below.
    from hotpost.video_agent_actions import _gate, ActionHeld
    from hotpost.video_agent_planning_claim import planning_recovery_candidate
    assert job['checkpoint']['failure_classification']['category'] == 'storage'
    assert task['source_acquisition']['hold']['reason'] == 'strategy_exhausted'
    assert planning_recovery_candidate(task, job) is True
    assert _gate(task, 'retry_repaired', job) is None
    serialized = copy.deepcopy(job)
    serialized['payload'] = json.dumps(serialized['payload'])
    serialized['checkpoint'] = json.dumps(serialized['checkpoint'])
    assert planning_recovery_candidate(task, serialized) is True
    assert _gate(task, 'retry_repaired', serialized) is None
    for field, value in [('task_id', 'other-task'), ('key', 'other-key')]:
        bad = copy.deepcopy(job)
        bad[field] = value
        assert planning_recovery_candidate(task, bad) is False
        with pytest.raises(ActionHeld):
            _gate(task, 'retry_repaired', bad)
    for field, value in [('run_id', 'other-run'), ('round', -1),
                         ('source_policy', {}), ('planning_recovery_from', 'other-parent')]:
        bad = copy.deepcopy(job)
        bad['payload'][field] = value
        assert planning_recovery_candidate(task, bad) is False
        with pytest.raises(ActionHeld):
            _gate(task, 'retry_repaired', bad)
    blocked_job = copy.deepcopy(job)
    blocked_job['checkpoint']['failure_classification']['category'] = 'access_blocked'
    assert planning_recovery_candidate(task, blocked_job) is False
    with pytest.raises(ActionHeld):
        _gate(task, 'retry_repaired', blocked_job)
    for field, value in [('waiting', {'searches':[{'status':'login_required'}]}),
                         ('receipt_wait', {'reason':'unsettled'})]:
        blocked = copy.deepcopy(task)
        blocked['source_acquisition'][field] = value
        assert planning_recovery_candidate(blocked, job) is False
        with pytest.raises(ActionHeld):
            _gate(blocked, 'retry_repaired', job)
    paused = copy.deepcopy(task)
    paused['automation']['paused_by_user'] = True
    with pytest.raises(ActionHeld):
        _gate(paused, 'retry_repaired', job)
    quality_held = copy.deepcopy(task)
    quality_held['daily_quality']['pending'] = 'scene_wait'
    with pytest.raises(ActionHeld):
        _gate(quality_held, 'retry_repaired', job)
    assert task == captured['task'] and job == captured['job']
    owner = dict(task_id=task['id'], job_id=job['id'], run_id=task['run_id'])
    old_key = job['checkpoint']['visual_query_input']['input_sha256']
    assert job['checkpoint']['visual_query_input'] == dict(owner, input_sha256=old_key)
    rows = incident['artifacts']
    if isinstance(rows, dict):
        rows = [dict(v, path=k) if isinstance(v, dict) else dict(path=k, content=v) for k,v in rows.items()]
    def artifact(suffix):
        matches = [r for r in rows if r['path'].replace(chr(92), '/').endswith('/'+suffix)]
        assert len(matches) == 1, suffix
        raw = matches[0].get('content', matches[0].get('text'))
        assert isinstance(raw, str)
        return json.loads(raw)
    historical = artifact(old_key+'/receipt.json')
    empty = 'empty-recovery-'+visual.digest(historical)
    assert empty in job['error']
    prefix = old_key+'/'+empty+'/'
    saved = {name:artifact(prefix+name) for name in (
        'proposal.json', 'review.json', 'identity-correction-proposal.json', 'identity-correction-review.json')}
    original = saved['proposal.json']['proposal']
    invalid = saved['identity-correction-proposal.json']['proposal']
    assert saved['review.json']['proposal_sha256'] == visual.digest(original)
    assert saved['review.json']['subject_identity_supported'] is False
    assert saved['review.json']['core_identity_complete'] is False
    assert saved['identity-correction-review.json']['proposal_sha256'] == visual.digest(invalid)
    assert historical['queries'] == []
    assert historical['approved_query_pool']['ready'] is False
    assert historical['evidence'] == task['source_acquisition']['visual_query_rejection']['evidence']
    assert visual.digest(historical['evidence']) == old_key
    # Local defect projection: historical acquisition ledgers cannot change
    # this content-addressed cache route. Preserve text, all frame IDs, minima,
    # rejected proposals and review flags; remap only external media bytes.
    reference = tmp_path/'reference.mp4'
    reference.write_bytes(b'isolated reference')
    frames = []
    for i in range(len(historical['evidence']['frames'])):
        path = tmp_path/('frame%d.jpg'%i)
        Image.new('RGB',(16,16),(i,20,30)).save(path)
        frames.append(path)
    text = historical['evidence']['text']
    evidence = visual.binding(reference,frames,text['caption'],text,
        search_minimums=historical['evidence']['search_minimums'],subject_hint=historical['evidence']['subject_hint'])
    key = visual.digest(evidence)
    historical.update(evidence=evidence,input_sha256=key)
    historical['review']['input_sha256'] = key
    assert visual.verify(historical) == []
    for value in saved.values():
        value['input_sha256'] = key
    saved['identity-correction-proposal.json']['feedback_sha256'] = visual.digest(dict(
        evidence=evidence,rejected_proposal=original,independent_review=saved['review.json']))
    with pytest.raises(ValueError, match='원문 인용') as rejection:
        visual.validate(invalid,saved['identity-correction-review.json'],evidence)
    feedback = dict(evidence=evidence,rejected_proposal=invalid,
        independent_review=saved['identity-correction-review.json'],validation_error=str(rejection.value))
    settings = Settings(data_dir=tmp_path)
    top = tmp_path/'source-visual-queries'/key
    root = top/('empty-recovery-'+visual.digest(historical))
    root.mkdir(parents=True)
    (top/'receipt.json').write_text(json.dumps(historical,ensure_ascii=False),'utf8')
    for name,value in saved.items():
        (root/name).write_text(json.dumps(value,ensure_ascii=False),'utf8')
    before = {p:p.read_bytes() for p in [top/'receipt.json',*[root/name for name in saved]]}
    legacy_path = root/('validation-recovery-'+visual.digest(feedback))
    actual_mkdir = Path.mkdir
    denied = []
    def external_storage(path,*args,**kwargs):
        if path == legacy_path:
            denied.append(path)
            raise FileNotFoundError(2,'isolated observed nested storage failure',str(path))
        return actual_mkdir(path,*args,**kwargs)
    monkeypatch.setattr(Path,'mkdir',external_storage)
    def forbidden(*args,**kwargs):
        pytest.fail('No external generation before the saved validation/storage gate')
    def run(model):
        return visual.cached_visual_queries(settings,reference,frames,text['caption'],text,model,
            search_minimums=evidence['search_minimums'],subject_hint=evidence['subject_hint'],owner_binding=owner)
    # Restore exactly the previous production storage block in an isolated
    # function, then call the unchanged real public entry. No validator mock.
    source = inspect.getsource(visual._correct_identity_once)
    start = source.index('            legacy_recovery =')
    end = source.index('            def regenerate',start)
    previous = source[:start] + "            recovery = root / ('validation-recovery-' + digest(feedback))\n            recovery.mkdir(parents=True, exist_ok=True)\n" + source[end:]
    namespace = dict(visual.__dict__)
    exec(compile(previous,'<previous-production-storage>','exec'),namespace)
    with monkeypatch.context() as old:
        old.setattr(visual,'_correct_identity_once',namespace['_correct_identity_once'])
        with pytest.raises(FileNotFoundError):
            run(forbidden)
    assert denied == [legacy_path]
    assert all(p.read_bytes() == raw for p,raw in before.items())
    # Fresh isolated model responses, never production approvals. Exact quotes
    # come from the already captured corrected receipt; defining terms remain.
    valid = copy.deepcopy(historical['proposal'])
    valid['observations'] = [dict(id='fixture',text='Isolated frame',frame_ids=['frame-1'])]
    valid['reference_scenes'] = []
    identity = valid['subject_identity']
    assert len(identity['required_terms']) == 4
    compact = {'eau de toilette':'EDT','bottle-neck jacquard ribbon':'bottle-neck-jacquard-ribbon'}
    for term in identity['required_terms']:
        assert term['quote'] in text[term['source']]
        term['terms']['en'] = [compact.get(v,v) for v in term['terms']['en']]
    valid['queries'] = []
    for lang,variants in {'en':['','rose','peony','bergamot','white-musk'],'zh':['','玫瑰','牡丹','佛手柑','白麝香']}.items():
        base = ' '.join([identity['product_terms'][lang][0]]+[r['terms'][lang][0] for r in identity['required_terms']])
        for i,modifier in enumerate(variants):
            valid['queries'].append(dict(id=lang+str(i),query=' '.join(filter(None,[modifier,base])),
                language=lang,observation_ids=['fixture'],frame_ids=['frame-1']))
    calls = []
    def external_model(settings,instruction,data,**kwargs):
        calls.append(copy.deepcopy(data))
        if 'proposal_sha256' not in data:
            assert data['validation_error'] == str(rejection.value)
            assert data['rejected_proposal'] == invalid
            return copy.deepcopy(valid)
        assert data['proposal'] == valid
        assert data['input_sha256'] == key
        return dict(input_sha256=key,proposal_sha256=visual.digest(valid),subject_identity_supported=True,
            core_identity_complete=True,checks=[dict(query_id=q['id'],supported=True,central_product=True,
                short_noun_phrase=True,no_unobserved_claims=True,core_identity_preserved=True) for q in valid['queries']])
    result = run(external_model)
    assert len(calls) == 2
    assert denied == [legacy_path]
    assert len(visual.verify(result)) == 10
    assert result['approved_query_pool']['ready'] is True
    assert all(p.read_bytes() == raw for p,raw in before.items())
    assert (tmp_path/'source-visual-recoveries'/visual.digest(feedback)/'identity-correction-review.json').is_file()
    plan = visual.apply_visual_queries(dict(query_evidence=copy.deepcopy(text),
        search_minimums=evidence['search_minimums'],run_id=owner['run_id']),result,reference_sha256=evidence['reference_sha256'])
    from hotpost.source_search.planner import round_queries
    assert len(round_queries(plan,dict(phase='core_action'))) == 10
    assert plan['minimum_query_plan_ready'] is True
    assert plan['run_id'] == job['payload']['run_id']
    assert run(forbidden) == result
    with pytest.raises(ValueError):
        visual.validate(valid,dict(result['review'],proposal_sha256='0'*64),evidence)
    wrong = copy.deepcopy(plan)
    wrong['query_evidence']['caption'] += ' changed'
    with pytest.raises(ValueError):
        visual.plan_queries(wrong)
    # Ownership registration remains real and rejects another job binding.
    error = visual.VisualQueryRejection('fixture',evidence,root/'proposal.json',root/'review.json',dict(owner,job_id='wrong'))
    assert visual.register_rejection_evidence(task,job,error) is False
    frames[0].write_bytes(b'changed frame')
    with pytest.raises(ValueError):
        visual.verify(result)
    assert job == captured['job'] and task == captured['task']
    assert captured == json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
