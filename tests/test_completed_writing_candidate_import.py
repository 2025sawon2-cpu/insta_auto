import copy
import json
import sqlite3

import pytest

from hotpost.script_candidate_versions import add_candidate, digest
from hotpost.source_quality import sha256_file
from hotpost.studio_store import StudioStore, Conflict
from hotpost.writing.contract import snapshot, receipt


@pytest.fixture
def completed(tmp_path):
    store = StudioStore(tmp_path/'studio')
    state, _ = store.create('fixture', '제품', {'protocol': 2, 'active': False})
    video = tmp_path/'reference.mp4'; video.write_bytes(b'bound original')
    state = store.change(state['id'], lambda s, db: s.update(
        original_text='검토한 화면 본문', reference_video=str(video), status='paused',
        script_id='old-script', voice_id='old-voice', scripts=[{'id':'old-script','text':'old'}],
        voices=[{'id':'old-voice'}], script_candidates=[{'text':'old candidate'}]))
    job = 'codex'+'a'*32
    root = tmp_path/'writing'; (root/job).mkdir(parents=True)
    contract = snapshot()
    payload = {'reference_script':state['original_text'], 'reference_video_sha256':sha256_file(video),
               'writing_contract':contract}
    (root/job/'payload.json').write_text(json.dumps(payload,ensure_ascii=False),'utf-8')
    text = '몸을 받쳐 씻기고 발톱도 손질해요. 댓글에 ‘나도’ 남겨주세요.'
    candidate = {'text':text,'variant_number':1,'writing_contract':receipt(contract),
        'thumbnail_lines':['몸 받치랴 씻기랴','손이 모자랐다면'],'bias':'자기참조 효과',
        'quality_summary':{'script_sha256':digest(text),'issues':[]}}
    result = {'flow':'three-variants-v1','writing_contract':receipt(contract),'scripts':[candidate]}
    with sqlite3.connect(root/'jobs.sqlite3') as db:
        db.execute('create table jobs(id text,kind text,state text,result text)')
        db.execute('insert into jobs values(?,?,?,?)',(job,'script','completed',json.dumps(result)))
    return store, state, job, root, result


def test_import_preserves_thumbnail_provenance_and_selected_artifacts(completed):
    store, state, job, _, _ = completed
    jobs = store.jobs(state['id'])
    request = {'writing_job_id':job,'variant_number':1,'revision':state['revision']}
    after = add_candidate(store,state['id'],request)
    c = after['script_candidates'][-1]
    assert c['thumbnail_lines']==['몸 받치랴 씻기랴','손이 모자랐다면']
    assert c['writing_job_id']==job and c['bias']=='자기참조 효과'
    assert not c['user_approved']
    for key in ['script_id','voice_id','scripts','voices','status','automation']:
        assert after[key]==state[key]
    assert store.jobs(state['id'])==jobs
    assert add_candidate(store,state['id'],request)==after


def test_same_narration_variants_keep_metadata_and_legacy_import_identity(completed):
    store, state, job, root, result = completed
    second = copy.deepcopy(result['scripts'][0])
    second.update(variant_number=2, thumbnail_lines=['다른 시청 동기','두 번째 안'], bias='별도 효과')
    result['scripts'].append(second)
    with sqlite3.connect(root/'jobs.sqlite3') as db:
        db.execute('update jobs set result=?',(json.dumps(result),))
    first = add_candidate(store,state['id'],{'writing_job_id':job,'variant_number':1})
    c = first['script_candidates'][-1]
    old_identity = digest(c['reference_sha256']+'\n'+c['writing_contract']['sha256']+'\n'+c['text']+'\n'+job)
    def legacy(s, db):
        s['script_candidates'][-1]['revision_id'] = old_identity
        s['script_candidate_revisions'][-1]['revision_id'] = old_identity
    first = store.change(state['id'], legacy)
    assert add_candidate(store,state['id'],{'writing_job_id':job,'variant_number':1}) == first
    after = add_candidate(store,state['id'],{'writing_job_id':job,'variant_number':2})
    assert len(after['script_candidates']) == 3
    one,two = after['script_candidates'][-2:]
    assert one['revision_id'] == old_identity != two['revision_id']
    assert one['thumbnail_lines'] != two['thumbnail_lines']
    assert two['bias'] == '별도 효과'
    assert add_candidate(store,state['id'],{'writing_job_id':job,'variant_number':2}) == after


@pytest.mark.parametrize('damage',['running','text_sha','contract','reference','video','client_text'])
def test_invalid_or_changed_job_cannot_modify_production(completed, damage):
    store, state, job, root, result = completed
    request = {'writing_job_id':job,'variant_number':1}
    if damage=='running':
        with sqlite3.connect(root/'jobs.sqlite3') as db:db.execute("update jobs set state='running'")
    elif damage in {'text_sha','contract'}:
        changed=copy.deepcopy(result)
        if damage=='text_sha':changed['scripts'][0]['text']='altered'
        else:changed['writing_contract']['sha256']='b'*64
        with sqlite3.connect(root/'jobs.sqlite3') as db:db.execute('update jobs set result=?',(json.dumps(changed),))
    elif damage=='reference':
        state=store.change(state['id'],lambda s,db:s.update(reviewed_original_text='changed'))
    elif damage=='video':
        from pathlib import Path
        Path(state['reference_video']).write_bytes(b'changed')
    else:request['text']='different client text'
    with pytest.raises((ValueError,Conflict)):
        add_candidate(store,state['id'],request)
    assert store.get(state['id'])==state
