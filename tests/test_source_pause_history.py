import copy
import json
import sys
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.source_pause_receipts import (SourceReceiptWaiting, binding, snapshot,
    sha, merge_receipt, verified_receipt)
from hotpost.source_search.strategy import fresh_queries, fresh_frames, image_sha256
from hotpost.studio_pause import StudioPaused, pause_scope, bind_progress, active_receipt_hook
from hotpost.source_browser_worker import run_bounded
from hotpost.studio_sources import SourceAcquisitionMixin
from hotpost.studio_runtime.generation import GenerationMixin
from hotpost.studio_runtime.media import MediaMixin
from hotpost.studio_store import StaleClaim


class MemoryStore:
    def __init__(self,state):self.state=copy.deepcopy(state);self.checkpoints=[];self.stale=False
    def change(self,task,fn,**kwargs):
        if self.stale:raise StaleClaim('old worker')
        assert task==self.state['id']
        fn(self.state,None);return copy.deepcopy(self.state)
    def checkpoint(self,job,value):
        if self.stale:raise StaleClaim('old worker')
        self.checkpoints.append(copy.deepcopy(value))
    def get(self,task):return copy.deepcopy(self.state)


class Harness(SourceAcquisitionMixin,GenerationMixin):
    _source_records=staticmethod(MediaMixin._source_records)
    def folder(self,task):return self.settings.data_dir/'studio'/task


def setup(tmp_path):
    h=Harness();h.settings=Settings(data_dir=tmp_path)
    root=h.settings.source_dir/'apple-123';root.mkdir(parents=True)
    state={'id':'task','shortcode':'apple','run_id':'run','sources':[],
           'automation':{'active':False},'scripts':[{'text':'preserve'}],'voices':[{'request_id':228}],
           'source_acquisition':{'round':2,'bounded_rounds':1,'no_progress_rounds':1,'queries':[],'rounds':[]}}
    job={'id':'collect','task_id':'task','kind':'collect_sources','payload':{'run_id':'run','round':2},'checkpoint':{}}
    manifest=root/'manifest.json';manifest.write_text(json.dumps({'job_id':root.name,'shortcode':'apple',
        'status':'paused','audit_checkpoint':'planned','search_audit':[],'candidates':[]}),encoding='utf-8')
    h.store=MemoryStore(state)
    progress=lambda *a:None
    h._bind_source_attempt_progress(state,job,progress)
    progress.source_attempt_created(manifest)
    return h,state,job,manifest,progress


def worker(progress,manifest,rows,folder='browser_debug'):
    p=manifest.parent/folder/('search-checkpoint-'+'a'*32+'.json');p.parent.mkdir()
    progress.source_worker_checkpoint(p)
    p.write_text(json.dumps({'searches':rows,'candidates':[]}),encoding='utf-8')
    progress.source_worker_settled(p)
    return p


def result(query='apple'):
    return {'provider':'youtube','query':query,'status':'results','language':'en','candidates':2,
        'requests':[{'operation':'visible_search_input_enter','at':123}],
        'execution':{'query_submitted':True,'query_url_matched':True,'actual_input_value':query}}


@pytest.mark.parametrize('phase',['browser_debug','refinement_debug'])
def test_pause_recovers_exact_child_before_manifest_has_audit_and_preserves_accounting(tmp_path,phase):
    h,state,job,m,p=setup(tmp_path);raw=m.read_bytes();w=worker(p,m,[result()],phase)
    before=copy.deepcopy(h.store.state)
    h._preserve_source_attempt_history(state,job)
    restored=h._restore_source_attempt_history(state,job)
    record=restored['source_acquisition']
    assert fresh_queries(['apple'],'youtube',record['queries'])==[]
    assert record['rounds']==before['source_acquisition']['rounds']
    for k in ('round','bounded_rounds','no_progress_rounds'):assert record[k]==before['source_acquisition'][k]
    assert restored['voices']==before['voices'] and restored['scripts']==before['scripts'] and restored['sources']==[]
    assert m.read_bytes()==raw and sha(w)==record['interrupted_attempts'][0]['worker_checkpoints'][0]['sha256']
    h._preserve_source_attempt_history(state,job);again=h._restore_source_attempt_history(state,job)
    assert again['source_acquisition']==record


def test_submitted_unknown_is_pending_and_parser_upgrade_does_not_retransmit(tmp_path):
    h,s,j,m,p=setup(tmp_path)
    row=result();row.update(status='started',parser_revision='old');row['execution']['query_url_matched']=False
    worker(p,m,[row]);h._preserve_source_attempt_history(s,j);s=h._restore_source_attempt_history(s,j)
    assert fresh_queries(['apple'],'youtube',s['source_acquisition']['queries'])==[]


def test_unsubmitted_intent_does_not_consume_but_same_parser_is_held(tmp_path):
    h,s,j,m,p=setup(tmp_path)
    from hotpost.source_search.readiness import parser_revision
    revision=parser_revision('tiktok')
    row={'provider':'tiktok','query':'사과','language':'ko','status':'page_unresolved',
         'parser_revision':revision,'stage':'locate_search_input','execution':{'query_submitted':False,'query_url_matched':False}}
    worker(p,m,[row]);h._preserve_source_attempt_history(s,j);s=h._restore_source_attempt_history(s,j)
    from hotpost.source_attempts import search_execution
    assert not search_execution(s['source_acquisition']['queries'][0])['consumed']
    assert fresh_queries(['사과'],'tiktok',s['source_acquisition']['queries'])==[]


def test_image_sha_and_result_page_scopes_survive_pause(tmp_path):
    h,s,j,m,p=setup(tmp_path)
    frame=tmp_path/'frame.jpg';frame.write_bytes(b'unchanged image')
    row={'provider':'yandex-images','query':'frame.jpg','language':'image','image_sha256':image_sha256(frame),
         'status':'image_upload_unknown','page':1,'requests':[{'operation':'image_upload','at':123}],
         'execution':{'query_submitted':True,'query_url_matched':False}}
    worker(p,m,[row]);h._preserve_source_attempt_history(s,j);s=h._restore_source_attempt_history(s,j)
    assert fresh_frames([frame],'yandex-images',s['source_acquisition']['queries'])==[]
    assert s['source_acquisition']['queries'][0]['page']==1


@pytest.mark.parametrize('damage',['missing_child','unsettled','foreign_child','wrong_short','malformed_manifest'])
def test_unverifiable_pause_holds_without_silent_replay(tmp_path,damage):
    h,s,j,m,p=setup(tmp_path);w=worker(p,m,[result()]);d=j['checkpoint']['source_attempts'][0]
    if damage=='missing_child':w.unlink()
    if damage=='unsettled':d['workers'][0]['settled']=False
    if damage=='foreign_child':d['workers'][0]['path']=str(tmp_path/'foreign.json')
    if damage=='wrong_short':m.write_text(json.dumps({'job_id':m.parent.name,'shortcode':'other'}),'utf-8')
    if damage=='malformed_manifest':m.write_text('{','utf-8')
    with pytest.raises(SourceReceiptWaiting):h._preserve_source_attempt_history(s,j)
    assert h.store.state['source_acquisition']['receipt_wait']['status']=='receipt_wait'
    assert h.store.state['source_acquisition']['queries']==[]


@pytest.mark.parametrize('damage',['foreign_receipt','receipt_tamper','manifest_tamper','child_tamper','extra_worker','different_task','different_run','different_job'])
def test_resume_rejects_tamper_or_foreign_binding(tmp_path,damage):
    h,s,j,m,p=setup(tmp_path);w=worker(p,m,[result()]);h._preserve_source_attempt_history(s,j)
    d=j['checkpoint']['source_attempts'][0]
    if damage=='foreign_receipt':
        f=tmp_path/'foreign.json';f.write_bytes(Path(d['receipt_path']).read_bytes());d['receipt_path']=str(f)
    if damage=='receipt_tamper':Path(d['receipt_path']).write_text('{}','utf-8')
    if damage=='manifest_tamper':m.write_text('{}','utf-8')
    if damage=='child_tamper':w.write_text('{}','utf-8')
    if damage=='extra_worker':d['workers'].append({'path':str(w.with_name('search-checkpoint-'+'b'*32+'.json')),'settled':True})
    if damage=='different_task':s['id']='other'
    if damage=='different_run':j['payload']['run_id']='other'
    if damage=='different_job':j['id']='other'
    with pytest.raises(SourceReceiptWaiting):h._restore_source_attempt_history(s,j)


def test_app_death_active_pointer_is_hold_not_new_attempt(tmp_path):
    h,s,j,m,p=setup(tmp_path)
    with pytest.raises(SourceReceiptWaiting):h._restore_source_attempt_history(s,j)
    assert len(j['checkpoint']['source_attempts'])==1
    assert h.store.state['source_acquisition']['receipt_wait']['status']=='receipt_wait'


def test_stale_claim_cannot_register_or_accept_receipt(tmp_path):
    h,s,j,m,p=setup(tmp_path);worker(p,m,[result()]);h.store.stale=True
    with pytest.raises(StaleClaim):h._preserve_source_attempt_history(s,j)
    assert h.store.state['source_acquisition']['queries']==[]
    assert not (m.parent/'interrupted-execution-receipt.json').exists()


@pytest.mark.parametrize('kind',['collect_sources','refresh_sources'])
def test_collect_and_refresh_pause_catch_accept_actual_history(tmp_path,monkeypatch,kind):
    h,s,j,m,p=setup(tmp_path);j['kind']=kind;worker(p,m,[result()])
    def stop(*a):raise StudioPaused('stop')
    target='_collect_source_attempt' if kind=='collect_sources' else '_refresh_source_attempt'
    monkeypatch.setattr(h,target,stop)
    with pytest.raises(StudioPaused):
        (h._collect_sources if kind=='collect_sources' else h._refresh_sources)(s,j)
    assert h.store.state['source_acquisition']['queries'][0]['query']=='apple'
    assert h.store.state['source_acquisition']['round']==2


def test_named_hooks_survive_bound_and_unbound_lambdas_and_worker_shutdown(tmp_path):
    h,s,j,m,p=setup(tmp_path)
    cp=m.parent/'refinement_debug'/('search-checkpoint-'+'c'*32+'.json');cp.parent.mkdir()
    cp.write_text(json.dumps({'searches':[result()],'message':'same'}),'utf-8')
    ticks=[]
    def check():
        ticks.append(1)
        if len(ticks)>1:raise StudioPaused('stop')
    p.check_cancel=check
    nested=bind_progress(lambda *a:None,bind_progress(lambda *a:None,p))
    assert nested.source_worker_checkpoint is p.source_worker_checkpoint
    with pytest.raises(StudioPaused),pause_scope(nested):
        # Deliberately unbound lambda: thread-local hook is the fallback.
        run_bounded([sys.executable,'-c','import sys,time;sys.stdin.read();time.sleep(30)'],{},cp,5,lambda *a:None)
    assert j['checkpoint']['source_attempts'][0]['workers'][0]['settled']
    assert active_receipt_hook('source_worker_checkpoint') is None
    h._preserve_source_attempt_history(s,j)
    assert h.store.state['source_acquisition']['queries'][0]['query']=='apple'


def test_received_unselected_partial_resumes_local_review_without_approval_or_download(tmp_path,monkeypatch):
    h,s,j,m,p=setup(tmp_path)
    video=m.parent/'video.mp4';video.write_bytes(b'received actual bytes')
    data=json.loads(m.read_text());data['candidates']=[{'url':'https://www.youtube.com/shorts/id',
        'downloaded_file':'video.mp4','file_sha256':sha(video),'preview_file':'preview.jpg',
        'selected_for_zip':False,'download_attempted':True,'source_quality':'clean-source',
        'video_meta':{'duration':5,'width':360,'height':640},'relevance_review_required':True,'rejection_reasons':[]}]
    m.write_text(json.dumps(data),'utf-8');h._preserve_source_attempt_history(s,j);s=h._restore_source_attempt_history(s,j)
    rows,origins=h._deferred_download_records(s)
    assert len(rows)==1 and rows[0]['sha256']==sha(video)
    assert not rows[0].get('editing_eligible') and not rows[0].get('functional_review')
    assert s['sources']==[] and data['candidates'][0]['selected_for_zip'] is False
    video.write_bytes(b'tamper')
    with pytest.raises(SourceReceiptWaiting):h._deferred_download_records(s)


@pytest.mark.parametrize('kind',['collect_sources','refresh_sources'])
def test_model_capacity_wait_after_root_creation_preserves_safe_retry(tmp_path,monkeypatch,kind):
    from hotpost.model_service import ModelServiceUnavailable
    h,s,j,m,p=setup(tmp_path);j['kind']=kind
    d=json.loads(m.read_text());d.update(audit_checkpoint='preparation',execution_audit_available=True)
    m.write_text(json.dumps(d),'utf-8')
    before=copy.deepcopy(h.store.state)
    def capacity(*a):raise ModelServiceUnavailable('model capacity wait')
    monkeypatch.setattr(h,'_collect_source_attempt' if kind=='collect_sources' else '_refresh_source_attempt',capacity)
    with pytest.raises(ModelServiceUnavailable):
        (h._collect_sources if kind=='collect_sources' else h._refresh_sources)(s,j)
    restored=h._restore_source_attempt_history(s,j)
    assert fresh_queries(['apple'],'youtube',restored['source_acquisition']['queries'])==['apple']
    assert not restored['source_acquisition'].get('receipt_wait')
    assert restored['source_acquisition']['round']==before['source_acquisition']['round']
    assert restored['sources']==[]


def test_missing_execution_audit_without_registered_request_trace_is_unknown_hold(tmp_path):
    h,s,j,m,p=setup(tmp_path)
    d=json.loads(m.read_text());d.update(audit_checkpoint='planned',execution_audit_available=False)
    m.write_text(json.dumps(d),'utf-8')
    with pytest.raises(SourceReceiptWaiting):h._preserve_source_attempt_history(s,j)
    assert h.store.state['source_acquisition']['receipt_wait']['status']=='receipt_wait'


def test_early_pause_before_child_first_checkpoint_preserves_empty_known_receipt(tmp_path):
    h,s,j,m,p=setup(tmp_path)
    cp=m.parent/'browser_debug'/('search-checkpoint-'+'e'*32+'.json');cp.parent.mkdir()
    p.check_cancel=lambda:(_ for _ in ()).throw(StudioPaused('early stop'))
    with pytest.raises(StudioPaused),pause_scope(p):
        run_bounded([sys.executable,'-c','import sys,time;sys.stdin.read();time.sleep(30)'],{},cp,5)
    assert cp.is_file() and json.loads(cp.read_text())['searches']==[]
    h._preserve_source_attempt_history(s,j);s=h._restore_source_attempt_history(s,j)
    assert s['source_acquisition']['queries']==[]
    assert fresh_queries(['apple'],'youtube',s['source_acquisition']['queries'])==['apple']


def test_real_finder_wrapper_registers_root_before_request_and_pause_exposes_owned_child(tmp_path,monkeypatch):
    import hotpost.source_finder as finder
    h,s,j,m,p=setup(tmp_path)
    def actual_child(settings,shortcode,progress,**kwargs):
        root=kwargs['root'];manifest=root/'manifest.json'
        assert j['checkpoint']['source_attempts'][-1]['manifest_path']==str(manifest.resolve())
        data=json.loads(manifest.read_text());data['audit_checkpoint']='planned'
        manifest.write_text(json.dumps(data),'utf-8')
        progress('search started',32)
        w=root/'browser_debug'/('search-checkpoint-'+'f'*32+'.json');w.parent.mkdir()
        nested=bind_progress(lambda *a:None,progress)
        nested.source_worker_checkpoint(w)
        w.write_text(json.dumps({'searches':[result()],'candidates':[]}),'utf-8')
        nested.source_worker_settled(w)
        raise StudioPaused('pause after actual request')
    monkeypatch.setattr(finder,'_find_sources',actual_child)
    monkeypatch.setattr(h,'_collect_source_attempt',lambda state,job:finder.find_sources(h.settings,'apple',p))
    with pytest.raises(StudioPaused):h._collect_sources(s,j)
    owned=j['checkpoint']['source_attempts'][-1]
    current=json.loads(Path(owned['manifest_path']).read_text())
    assert current['status']=='paused' and current['execution_audit_available'] is False
    assert Path(owned['receipt_path']).is_file()
    assert fresh_queries(['apple'],'youtube',h.store.state['source_acquisition']['queries'])==[]
