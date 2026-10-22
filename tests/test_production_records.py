import hashlib
import json
from pathlib import Path

import pytest

from hotpost.studio_store import StudioStore
from hotpost.production_records import flush


def source_state(store, code='search'):
    state,_=store.create(code,code,prepare=False)
    searches=[
        {'query':'camping cart','language':'en','provider':'tiktok','status':'results','candidates':3,
         'execution':{'query_submitted':True,'query_url_matched':True,'actual_input_value':'camping cart','submitted_at':1000}},
        {'query':'camping cart','language':'en','provider':'tiktok','status':'no_results','candidates':0,
         'execution':{'query_submitted':True,'query_url_matched':True,'actual_input_value':'camping cart','submitted_at':1100}},
        {'query':'折叠车','language':'zh','provider':'bilibili','status':'login_required','candidates':0,
         'execution':{'query_submitted':False,'query_url_matched':False}},
    ]
    store.change(state['id'],lambda s,db:s.update(run_id='run-1',source_acquisition={
        'queries':searches,'rounds':[{'run_id':'run-1','job_id':'source-job','searches':searches}]}))
    return state['id']


def test_actual_submissions_retries_and_pre_submit_stop_are_separate(tmp_path):
    store=StudioStore(tmp_path);source_state(store);flush(store)
    paths=list((tmp_path/'production-records').rglob('source-search-*.md'))
    assert len(paths)==1
    text=paths[0].read_text('utf-8')
    assert '고유 검색어 수: 1 / 확인된 제출 시도 수: 2' in text
    assert '미제출: 折叠车' in text and 'login_required' in text
    assert '1970-01-01T09:16:40+09:00' in text
    assert 'source-job:0' in text and 'source-job:1' in text
    assert '생성·선정 원본 계약 미확인' in text
    assert '과거 병합 이력만 존재' not in text


def test_failed_projection_retains_outbox_and_restart_recovers_without_search(tmp_path,monkeypatch):
    store=StudioStore(tmp_path);source_state(store)
    original=Path.write_text
    def fail_write(path,*args,**kwargs):
        if path.suffix=='.tmp':raise OSError('fixture filesystem unavailable')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'write_text',fail_write)
    flush(store)
    with store.connect() as db:assert db.execute('SELECT pending FROM production_record_outbox').fetchone()[0]==1
    monkeypatch.setattr(Path,'write_text',original)
    restarted=StudioStore(tmp_path);flush(restarted)
    with restarted.connect() as db:assert db.execute('SELECT pending FROM production_record_outbox').fetchone()[0]==0
    assert list((tmp_path/'production-records').rglob('*.md'))


def test_rollback_cannot_publish_unaccepted_searches(tmp_path):
    store=StudioStore(tmp_path);state,_=store.create('rollback','Rollback',prepare=False)
    def rejected(s,db):
        s.update(run_id='run',source_acquisition={'queries':[{'query':'not accepted'}]})
        store.save(db,s)
        raise ValueError('acceptance rejected')
    with pytest.raises(ValueError):store.change(state['id'],rejected)
    flush(store)
    assert not list((tmp_path/'production-records').rglob('*.md'))


def test_plan_and_actual_input_keep_original_language_and_strings(tmp_path):
    store=StudioStore(tmp_path);tid=source_state(store)
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'query_plan':{'query_owner':{'task_id':tid,'run_id':'run-1'},
        'query_details':[{'language':'zh','query':'四态 露营车','viewpoint':'伞'}]}}),encoding='utf-8')
    store.change(tid,lambda s,db:s.update(source_search_manifest_path=str(manifest)))
    flush(store)
    text=next((tmp_path/'production-records').rglob('*.md')).read_text('utf-8')
    assert '四态 露营车' in text and 'camping cart' in text
    assert '선정·실제 제출은 아래 증거 참조' in text


def test_concurrent_new_state_cannot_be_acknowledged_by_old_projection(tmp_path,monkeypatch):
    from hotpost import production_records
    store=StudioStore(tmp_path);tid=source_state(store)
    original=production_records.render;changed=[]
    def change_during_render(state):
        if not changed:
            changed.append(True)
            store.change(tid,lambda s,db:s.update(status='newer-current-state'))
        return original(state)
    monkeypatch.setattr(production_records,'render',change_during_render)
    flush(store)
    with store.connect() as db:assert db.execute('SELECT pending FROM production_record_outbox').fetchone()[0]==1
    flush(store)
    text=next((tmp_path/'production-records').rglob('*.md')).read_text('utf-8')
    assert 'newer-current-state' in text


def test_actual_manifest_shape_preserves_generated_rejected_and_candidate_stages(tmp_path):
    from types import SimpleNamespace
    from hotpost.production_records import write_attempt,write_proposal
    owner={'task_id':'work-actual','run_id':'run','job_id':'job'}
    proposal={'queries':[{'id':'chosen','language':'en','query':'camping cart','viewpoint':'usage'},
                         {'id':'excluded','language':'zh','query':'露营车','viewpoint':'context'}]}
    proposal_path=tmp_path/'proposal.json';proposal_path.write_text(json.dumps({'proposal':proposal}),encoding='utf-8')
    settings=SimpleNamespace(data_dir=tmp_path)
    write_proposal(settings,owner,proposal_path)
    assert '생성 기록' in next((tmp_path/'studio'/'production-records').rglob('query-proposal-*.md')).read_text('utf-8')
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({**owner,'query_details':[{'language':'en','query':'camping cart'}],
        'product_evidence':{'query_owner':owner,'visual_query_evidence':{'owner':owner,'proposal':proposal}},
        'search_audit':[],'candidates':[{'url':'https://example.test/video','query':'camping cart',
            'platform':'tiktok','downloaded_file':'','selected_for_zip':False,'rejection_reasons':['not received']}]}),encoding='utf-8')
    write_attempt(settings,manifest)
    text=next((tmp_path/'studio'/'production-records').rglob('source-attempt-*.md')).read_text('utf-8')
    assert 'camping cart' in text and '露营车' in text and '미선정' in text
    assert 'https://example.test/video' in text and 'not received' in text
    assert '제출 시도 수: 0' in text
