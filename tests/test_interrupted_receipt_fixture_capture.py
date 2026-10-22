"""A recovery fixture must contain its own verified interrupted receipt."""
import copy
import hashlib
import json

import pytest

from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.source_pause_receipts import binding,snapshot,sha
from hotpost.video_agent_context import incident_artifacts


@pytest.fixture
def captured(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('capture','Capture',{'active':True},prepare=False)
    reference=tmp_path/'reference.mp4';reference.write_bytes(b'original reference')
    state=studio.store.change(state['id'],lambda s,db:s.update(run_id='current-run',reference_video=str(reference)))
    with studio.store.transaction() as db:
        jid=studio.store.enqueue(db,state['id'],'refresh_sources',{'run_id':state['run_id'],'search_before_saved_reviews':True},'capture')
    job={'id':jid,'task_id':state['id'],'kind':'refresh_sources','payload':{'run_id':state['run_id'],'search_before_saved_reviews':True}}
    folder=studio.settings.source_dir/'capture-123';folder.mkdir(parents=True)
    manifest=folder/'manifest.json'
    scope=binding(state,job)
    manifest.write_text(json.dumps({**scope,'job_id':folder.name,'shortcode':'capture','search_audit':[],'candidates':[]}),'utf8')
    worker=folder/'browser_debug'/('search-checkpoint-'+'a'*32+'.json');worker.parent.mkdir()
    worker.write_text(json.dumps({'searches':[],'candidates':[]}),'utf8')
    descriptor={**scope,'manifest_path':str(manifest),'workers':[{'path':str(worker),'settled':True}]}
    receipt=folder/'interrupted-execution-receipt.json'
    receipt.write_text(json.dumps(snapshot(studio.settings.source_dir,descriptor,state,job)),'utf8')
    descriptor.update(receipt_path=str(receipt),receipt_sha256=sha(receipt))
    def row():
        with studio.store.transaction() as db:
            db.execute('update jobs set checkpoint=? where id=?',(json.dumps({'source_attempts':[descriptor]}),jid))
            return dict(db.execute('select * from jobs where id=?',(jid,)).fetchone())
    return studio,state,descriptor,receipt,manifest,worker,row


def test_current_receipt_is_complete_even_at_one_file_budget(captured):
    studio,state,d,receipt,manifest,worker,row=captured
    job=row();before=studio.store.get(state['id']);original=receipt.read_bytes()
    result=incident_artifacts(studio,state,job,max_files=1)
    assert len(result)==1 and result[0]['path']==str(receipt.resolve())
    assert result[0]['content']==original.decode('utf8') and not result[0]['truncated']
    assert result[0]['sha256']==hashlib.sha256(original).hexdigest()
    full=incident_artifacts(studio,state,job,max_characters=4000000,max_files=24)
    assert {str(p.resolve()) for p in (receipt,manifest,worker)}<={r['path'] for r in full}
    assert studio.store.get(state['id'])==before and receipt.read_bytes()==original


@pytest.mark.parametrize('fault',['task','job','run','receipt_digest','manifest_digest','worker_digest','unsettled'])
def test_missing_or_foreign_integrity_never_grants_fixture_receipt(captured,fault):
    studio,state,d,receipt,manifest,worker,row=captured
    if fault in {'task','job','run'}:d[{'task':'task_id','job':'studio_job_id','run':'run_id'}[fault]]='other'
    if fault=='receipt_digest':d['receipt_sha256']='0'*64
    if fault=='manifest_digest':manifest.write_text('{}','utf8')
    if fault=='worker_digest':worker.write_text('{"changed":true}','utf8')
    if fault=='unsettled':d['workers'][0]['settled']=False
    result=incident_artifacts(studio,state,row())
    assert str(receipt.resolve()) not in {r['path'] for r in result}
