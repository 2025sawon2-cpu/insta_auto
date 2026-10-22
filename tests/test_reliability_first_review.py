"""Counterexamples found by the first independent reliability review."""
import copy
import hashlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost.daily_quality import POLICY
from hotpost.source_queries import tiktok_noun_phrase, tiktok_product_queries, grounded_tiktok_noun_phrase
from hotpost.studio import Studio
from hotpost.studio_runtime.lifecycle import LifecycleMixin
from hotpost.studio_sources import SourceAcquisitionMixin
from hotpost.studio_workflow import snapshot
from hotpost.studio_store import StudioStore


class SingleWorkerStore(StudioStore):
    """A real transactional outbox whose empty queue ends the isolated worker."""
    def __init__(self,root,worker):
        self.worker=worker;self.results=[];self.checkpoints=[]
        super().__init__(root)
    def claim(self,lane=None,**options):
        job=super().claim(lane,**options)
        if job is None:self.worker.stop.set()
        return job
    def finish(self,job,result,accept):
        self.results.append(copy.deepcopy(result))
        return super().finish(job,result,accept)
    def checkpoint(self,identity,value):
        self.checkpoints.append(copy.deepcopy(value))
        return super().checkpoint(identity,value)


def test_source_completion_preserves_latest_user_denial_receipt(monkeypatch):
    current={'editing_eligible':False,'reason':'excluded during review','reviewer':'user','at':42}
    state={'id':'task','product':'검토 대상 제품','sources':[{'id':'stable','sha256':'sha',
        'manual_usage_review':copy.deepcopy(current),'editing_eligible':False}],
        'source_acquisition':{},'status':'completed'}
    mixin=SourceAcquisitionMixin()
    mixin.settings=SimpleNamespace(source_min_usable=1,source_browser_search_interval=30,source_no_progress_rounds=3)
    mixin.ensure_source_collection=lambda *args,**kwargs:None
    goal={'ready':True,'count':1,'target':1,'core_ready':True,'policy_version':'test','platform_targets':{}}
    monkeypatch.setattr('hotpost.studio_sources.source_goal',lambda *a,**k:goal)
    result={'sources':[{'id':'incoming','sha256':'sha','editing_eligible':True,
        'manual_usage_review':{'editing_eligible':True}}], 'round':0,
        'source_search_manifest_path':'manifest','searches':[]}
    mixin.accept_source_round(state,{'id':'job','payload':{}},result,None)
    saved=state['sources'][0]
    assert saved['id']=='stable'
    assert saved['manual_usage_review']==current and saved['editing_eligible'] is False


def test_rewrite_repair_render_counts_once_and_retains_parent():
    mixin=LifecycleMixin()
    state={'edits':[{'id':'old','preview_path':'durable-previous-render.mp4'}],'daily_quality':{'repair_round':2,
        'repair_context':{'parent_edit_id':'old','reason':'quality_feedback_rewrite'}},
        'approved_voice_id':'voice','automation':{'active':False},'runs':[]}
    job={'id':'render','kind':'edit','payload':{'voice_id':'voice','quality_repair':True,
        'repair_input_signature':'actual-input','parent_edit_id':'old'}}
    result={'id':'new','voice_id':'voice','script_id':'newscript'}
    mixin._accept(state,job,result,None)
    assert state['daily_quality']['repair_round']==3
    assert state['daily_quality']['rendered_input_signatures']==['actual-input']
    assert state['edits'][-1]['parent_id']=='old'
    assert 'repair_context' not in state['daily_quality']
    mixin._accept(state,job,result,None)
    assert state['daily_quality']['repair_round']==3 and len(state['edits'])==2


def test_rewrite_repair_no_render_does_not_consume_context_or_count():
    mixin=LifecycleMixin()
    context={'reason':'quality_feedback_rewrite','parent_edit_id':'old'}
    state={'edits':[],'daily_quality':{'repair_round':0,'repair_context':context},
        'approved_voice_id':'voice','automation':{'active':False},'runs':[]}
    mixin._accept(state,{'kind':'edit','payload':{'voice_id':'voice','quality_repair':True}},
                  {'no_render':True},None)
    assert state['daily_quality']['repair_round']==0
    assert state['daily_quality']['repair_context']==context and not state['edits']


@pytest.mark.parametrize('kind,payload',[('quality_reedit',{}),('edit',{'quality_repair':True})])
def test_recovered_queued_repair_preserves_legacy_stop_without_new_actual_evidence(tmp_path,kind,payload):
    mixin=LifecycleMixin()
    initial={'script_id':'script','daily_quality':{'repair_round':3,'max_repairs':3,'pending':'exhausted'},
        'automation':{'active':False},'edits':[]}
    mixin.stop=threading.Event();mixin.store=SingleWorkerStore(tmp_path/'legacy-worker',mixin)
    state,_=mixin.store.create('legacy-stop','제품',prepare=False,initial=initial)
    task=state['id']
    mixin.store.change(task,lambda s,db:mixin.store.enqueue(db,task,kind,payload,'recovered-old-job'))
    mixin.settings=SimpleNamespace(studio_daily_quality_max_repairs=3)
    mixin._edit=lambda *_:pytest.fail('An exhausted repair must not render')
    mixin._quality_reedit=lambda *_:pytest.fail('An exhausted repair must not render')
    mixin._worker()
    state=mixin.store.get(task)
    assert mixin.store.results==[{'no_render':True,'quality_method_held':True}]
    assert state['daily_quality']['pending']=='exhausted' and not state['automation']['active']
    assert state['daily_quality']['repair_round']==3 and state['edits']==[]
    assert mixin.store.jobs(task)[0]['status']=='done'


@pytest.mark.parametrize('already_rendered',[False,True])
def test_queued_repair_freezes_actual_current_input_and_holds_replay(tmp_path,already_rendered):
    from hotpost.scene_requirements import repair_render_signature
    mixin=LifecycleMixin()
    initial={'script_id':'script','daily_quality':{'repair_round':1,'max_repairs':3,
        'feedback':[{'kind':'cover','reason':'제품 질문을 표지에서 공개함'}],
        'thumbnail_lines':['제품의 숨은 장점','어떤 촉감일까요?']},
        'automation':{'active':False},'sources':[],'edits':[],'voice_id':'voice','approved_voice_id':'voice'}
    mixin.stop=threading.Event();mixin.store=SingleWorkerStore(tmp_path/'signature-worker',mixin)
    state,_=mixin.store.create('signature-freeze','제품',prepare=False,initial=initial)
    task=state['id'];actual=repair_render_signature(state)
    if already_rendered:
        def previous_failed_method(s,db):
            from hotpost.quality_progress import permit,finish_attempt
            s['daily_quality']['rendered_input_signatures']=[actual]
            permit(s,'reedit',reserve=True,job_id='previous-committed-render')
            finish_attempt(s,{'id':'previous-committed-render'},failed=True)
        mixin.store.change(task,previous_failed_method)
    mixin.store.change(task,lambda s,db:mixin.store.enqueue(db,task,'quality_reedit',{
        'script_id':'script','voice_id':'voice','repair_input_signature':'queued-older-constraints'},'freeze-input'))
    executed=[]
    mixin.settings=SimpleNamespace(studio_daily_quality_max_repairs=3)
    def edit(s,j):
        executed.append(copy.deepcopy(j['payload']))
        assert j['payload']['repair_input_signature']==actual
        # Completion must retain the execution snapshot even if review state
        # changes before its result is committed.
        s['daily_quality']['thumbnail_lines']=['new','metadata']
        return {'id':'new-render','voice_id':'voice','script_id':'script',
                'repair_input_signature':'incorrect-late-signature'}
    mixin._quality_reedit=edit
    mixin._worker()
    state=mixin.store.get(task);results=mixin.store.results;checkpoints=mixin.store.checkpoints
    if already_rendered:
        assert not executed and not checkpoints
        assert results[0]['no_render'] and results[0]['quality_method_held']
        assert state['daily_quality']['pending']=='scene_wait'
        assert state['daily_quality']['rendered_input_signatures']==[actual]
        assert state['daily_quality']['progress_policy']['attempts'][0]['status']=='failed'
    else:
        assert executed[0]['previous_repair_input_signature']=='queued-older-constraints'
        assert checkpoints[-1]['repair_input_signature']==actual
        assert results[0]['repair_input_signature']==actual
        assert results[0]['previous_repair_input_signature']=='queued-older-constraints'


@pytest.fixture
def rewritten_ready(tmp_path,monkeypatch):
    studio=Studio(Settings(data_dir=tmp_path,source_min_usable=1),workers=False)
    state,_=studio.store.create('rewrite-repair','제품',prepare=False,
        automation={'active':True,'protocol':2,'stage':'edit'},
        initial={'daily_quality':{'policy':POLICY,'max_repairs':3,'repair_round':0,'status':'pending'}})
    root=studio.folder(state['id']);voice=root/'voice.wav';voice.write_bytes(b'voice')
    preview=root/'old-preview.mp4';preview.write_bytes(b'actual old mocked render')
    monkeypatch.setattr(studio,'ensure_source_collection',lambda *a,**k:None)
    monkeypatch.setattr('hotpost.studio_sources.source_goal',lambda *a,**k:{'ready':True,'source_ids':['source']})
    def initialize(s,db):
        s['original_text']='제품 원본 설명'
        studio._script(s,'선정 대본','automatic_codex')
        plan=root/'old-plan.json'
        plan.write_text(json.dumps({'script_text':'선정 대본','voice':{'sha256':hashlib.sha256(b'voice').hexdigest()},
            'beats':[{'id':'b','text':'선정 대본'}]}),encoding='utf-8')
        s.update(sources=[{'id':'source'}],voices=[{'id':'voice','script_id':s['script_id'],
            'path':str(voice),'sha256':hashlib.sha256(b'voice').hexdigest()}],voice_id='voice',
            approved_voice_id='voice',edits=[{'id':'old','voice_id':'voice','script_id':s['script_id'],
            'plan_path':str(plan),'preview_path':str(preview)}],edit_id='old')
        snapshot(s)
        studio.advance_workflow(s,db)
    studio.store.change(state['id'],initialize)
    return studio,state['id'],voice


def complete(studio,task,result):
    job=studio.store.claim(task_id=task)
    assert job
    if job['kind']=='quality_review':
        state=studio.store.get(task)
        edit=next(e for e in state['edits'] if e['id']==result['edit_id'])
        result.setdefault('render_sha256',hashlib.sha256(Path(edit.get('export_path') or edit['preview_path']).read_bytes()).hexdigest())
        result.setdefault('plan_sha256',hashlib.sha256(Path(edit['plan_path']).read_bytes()).hexdigest())
    studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
    return job


def queue_rewrite_repair(studio,task,voice):
    job=complete(studio,task,{'edit_id':'old','passed':False,
        'issues':[{'kind':'script_clarity','beat_id':'b','reason':'unclear words'}]})
    assert job['kind']=='quality_review'
    assert studio.store.get(task)['daily_quality']['repair_context']['parent_edit_id']=='old'
    job=complete(studio,task,{'text':'새로 고친 선정 대본'})
    assert job['kind']=='rewrite'
    job=studio.store.claim(task_id=task)
    assert job['kind']=='voice'
    result={'id':job['payload']['voice_id'],'script_id':job['payload']['script_id'],
            'path':str(voice),'sha256':hashlib.sha256(b'voice').hexdigest()}
    studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))


def test_feedback_rewrite_marks_ordinary_edit_as_durable_repair(rewritten_ready):
    studio,task,voice=rewritten_ready
    queue_rewrite_repair(studio,task,voice)
    studio=Studio(studio.settings,workers=False)
    job=studio.store.claim(task_id=task)
    assert job['kind']=='edit' and job['payload']['quality_repair'] is True
    assert job['payload']['parent_edit_id']=='old' and job['payload']['repair_input_signature']
    result={'id':'new-render','script_id':job['payload']['script_id'],'voice_id':job['payload']['voice_id']}
    studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
    assert studio.store.get(task)['daily_quality']['repair_round']==1


def test_feedback_rewrite_new_actual_script_and_voice_can_queue_fourth_repair(rewritten_ready):
    studio,task,voice=rewritten_ready
    queue_rewrite_repair(studio,task,voice)
    job=studio.store.claim(task_id=task)
    assert job['kind']=='edit'
    # Cumulative usage is audit data. A grounded rewrite remains a valid method.
    def usage(s,db):
        db.execute("UPDATE jobs SET status='queued' WHERE id=?",(job['id'],))
        s['daily_quality']['repair_round']=3
        studio.advance_workflow(s,db)
    state=studio.store.change(task,usage)
    assert state['daily_quality']['repair_round']==3
    assert state['automation']['active'] is True
    assert state['daily_quality'].get('pending')!='exhausted'
    assert len([j for j in studio.store.jobs(task) if j['kind']=='edit' and j['status']=='queued'])==1


@pytest.mark.parametrize('query',[
    'ladle stirring soup','show ladle stirring soup','pot rubbing bottom',
    '국자로 냄비 바닥을 문지르다','국자로 국물을 젓기','汤勺搅拌汤',
    'made up noun guaranteed by model',
])
def test_tiktok_final_boundary_rejects_non_noun_or_unreviewed_vocabulary(query):
    assert tiktok_noun_phrase(query)==''
    # A model's product/subject label and a quote do not grant permission.
    assert tiktok_product_queries({'query_details':[{'query':query,'intent':'product',
        'sources':['caption'],'evidence_quote':query}]})==[]


@pytest.mark.parametrize('query',['실리콘 국자','빨간 패딩','은색 거울','silver mirror',
    'red puffer jacket','silicone ladle','硅胶汤勺','DAISO SKU 1064379','electric heater'])
def test_tiktok_known_product_nouns_and_modifiers_remain_usable(query):
    assert tiktok_noun_phrase(query)==query


@pytest.mark.parametrize('query,quote,accepted',[
    ('silver mirror','은색 거울',True), ('silicone ladle','실리콘 국자',True),
    ('ladle','국자',True), ('red puffer jacket','빨간 패딩',True),
    ('silver mirror','국자',False), ('metal ladle','국자',False),
    ('red ladle','실리콘 국자',False), ('DAISO SKU 1064379','품번 1064379',False),
    ('honey garlic soy chicken','마늘간장 치킨',False),
    ('honey garlic soy chicken','꿀 마늘간장 치킨',True),
])
def test_tiktok_translations_require_matching_object_and_each_modifier(query,quote,accepted):
    assert bool(grounded_tiktok_noun_phrase(query,quote)) is accepted


def test_query_planning_propagates_shared_model_wait(tmp_path):
    from hotpost.source_planning import enrich_plan
    from hotpost.model_service import ModelServiceUnavailable
    def capacity(*args,**kwargs):raise ModelServiceUnavailable(retry_at=123,attempted=False)
    with pytest.raises(ModelServiceUnavailable) as error:
        enrich_plan(Settings(data_dir=tmp_path),{'query_details':[]},'국자',{},capacity)
    assert error.value.retry_at==123 and error.value.attempted is False


def test_external_tiktok_index_operators_preserve_only_prevalidated_noun_queries(tmp_path):
    from hotpost.source_search.discovery import discover
    from hotpost.source_finder import Candidate
    calls=[]
    def indexed(provider):
        def search(queries,*args):calls.append((provider,queries));return []
        return search
    services=SimpleNamespace(search_local_cache=lambda *a:[],search_local_hints=lambda *a:[],
        search_web=indexed('duckduckgo'),search_bing=indexed('bing'),
        search_pexels=lambda *a:[],Candidate=Candidate)
    plan={'search_strategy':{'routes':['duckduckgo','bing','tiktok'],'skipped_routes':{},'vendor_search':False},
          'tiktok_query_details':[{'query':'silicone ladle','evidence_quote':'실리콘 국자'}]}
    discover(Settings(data_dir=tmp_path,source_browser_search=False), 'post',[],
        ['ladle stirring soup'],plan,[],tmp_path,[],[],lambda *a:None,services)
    scoped=[(provider,q) for provider,queries in calls for q in queries if 'site:tiktok.com/@' in q]
    assert scoped==[('duckduckgo','silicone ladle site:tiktok.com/@ inurl:video'),
                    ('bing','silicone ladle site:tiktok.com/@ inurl:video')]


@pytest.mark.parametrize('caption,prohibited',[
    ('냉장고 자석',('DIY','사진','photo')), ('바지걸이',('다단','multi layer')),
])
def test_catalog_product_names_cannot_add_unobserved_tiktok_modifiers(caption,prohibited):
    from hotpost.source_queries import product_query_plan
    plan=product_query_plan(caption,[],[],{},[])
    queries=tiktok_product_queries(plan)
    assert queries, 'The grounded simpler product noun should remain searchable'
    assert all(not any(term.casefold() in q.casefold() for term in prohibited) for q in queries)


@pytest.mark.parametrize('stage',['directory','request.txt','schema.json','receipt.json'])
def test_model_probe_preparation_io_failure_releases_only_its_lease(tmp_path,monkeypatch,stage):
    import sys
    from pathlib import Path
    from hotpost import model_service as service
    from hotpost.writing import codex_writer as writer
    root=tmp_path/'writing';now=[100]
    monkeypatch.setattr(service.time,'time',lambda:now[0])
    monkeypatch.setattr(service.random,'uniform',lambda *a:1)
    retry=service.capacity_failure(root/'previous')
    now[0]=retry+1
    monkeypatch.setattr(writer,'executable',lambda:sys.executable)
    mkdir=Path.mkdir;write=Path.write_text
    def directory(path,*args,**kwargs):
        if stage=='directory' and path.name.startswith('codex-'):raise OSError('request storage failed')
        return mkdir(path,*args,**kwargs)
    def text(path,*args,**kwargs):
        if path.name==stage and path.parent.name.startswith('codex-'):raise OSError('request storage failed')
        return write(path,*args,**kwargs)
    monkeypatch.setattr(Path,'mkdir',directory);monkeypatch.setattr(Path,'write_text',text)
    state={'directory':root/'probe','calls':[]}
    with pytest.raises(OSError,match='request storage failed'):
        writer.chat('rules','data',None,lambda:None,state)
    with service.database(root) as db:
        failures,retry_at,lease,owner=db.execute('SELECT failures,retry_at,probe_until,probe_owner FROM capacity').fetchone()
    assert failures==1 and retry_at==retry and lease==0 and owner==''
    # Another recovery request can start immediately; the original capacity
    # failure remains recorded instead of being reset as a false success.
    assert service.before_call(root/'next',ticket=True)['probe'] is True


def test_probe_request_io_failure_remains_a_durable_failed_writing_job(tmp_path,monkeypatch):
    import sys
    from pathlib import Path
    from hotpost import model_service as service
    from hotpost.writing import codex_writer as writer
    from hotpost.writing.jobs import Jobs
    jobs=Jobs(tmp_path/'writing');now=[100]
    monkeypatch.setattr(service.time,'time',lambda:now[0])
    monkeypatch.setattr(service.random,'uniform',lambda *a:1)
    retry=service.capacity_failure(jobs.root/'previous');now[0]=retry+1
    monkeypatch.setattr(writer,'executable',lambda:sys.executable)
    original=Path.write_text
    def fail_request(path,*args,**kwargs):
        if path.name=='request.txt' and path.parent.name.startswith('codex-'):
            raise OSError('cannot save model request')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'write_text',fail_request)
    job=jobs.create('editorial',{'instruction':'rules','evidence':{},'media':[]})
    jobs.execute(job)
    saved=Jobs(jobs.root).get(job['id'])
    assert saved['state']=='failed' and saved['result']['error_reason']=='OSError'
    assert 'cannot save model request' in saved['error']
    assert service.before_call(jobs.root/'next',ticket=True)['probe'] is True


@pytest.mark.parametrize('query',[
    'L자 주방매트','L자주방매트','엘자 주방 매트','L형 주방 매트','L字형 주방 매트',
    'L-shaped kitchen mat','L shaped kitchen mat','L型厨房地垫','L字型 キッチンマット',
])
def test_observed_l_shape_is_a_grounded_product_modifier(query):
    assert grounded_tiktok_noun_phrase(query,'주방 매트 끝부분이 엘자로 꺾여서')==query
    assert grounded_tiktok_noun_phrase(query,'주방 매트')==''


def test_japanese_kitchen_mat_keeps_noun_but_requires_shape_evidence():
    assert grounded_tiktok_noun_phrase('キッチンマット','キッチンマット')=='キッチンマット'
    assert grounded_tiktok_noun_phrase('L字型 キッチンマット','キッチンマット')==''
    assert grounded_tiktok_noun_phrase('L字型 キッチンマット','L字型のキッチンマット')=='L字型 キッチンマット'


@pytest.mark.parametrize('caption,search_request,expected',[
    ('주방 매트 끝부분이 엘자로 꺾여서','L자 주방매트',['L자 주방매트']),
    ('주방 매트','L자 주방매트',[]),
    ('주방 매트 끝부분이 엘자로 꺾여서','주방 매트로 바닥 긁기 원본 영상 자막 없는',[]),
])
def test_operator_request_reaches_actual_tiktok_provider_pool_with_existing_model_queries(
        tmp_path,monkeypatch,caption,search_request,expected):
    from PIL import Image
    from hotpost import source_finder as sf, text_overlay
    from hotpost.models import Post
    settings=Settings(data_dir=tmp_path,source_browser_search=True,source_query_model_enabled=False,
        source_transcribe_reference=False,source_refine_max_candidates=0)
    monkeypatch.setattr(sf,'_post',lambda *_:Post('ref','user',1,'reel',caption=caption))
    monkeypatch.setattr(sf,'_download_reference',lambda *a:(a[-1].write_bytes(b'reference'),a[-1])[1])
    def frames(video,folder,*a,**k):
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/'candidate_001.jpg';Image.new('RGB',(20,30),'white').save(path);return [path]
    monkeypatch.setattr(sf,'extract_frames',frames)
    monkeypatch.setattr(sf,'_transcript_evidence',lambda *a:{})
    monkeypatch.setattr(sf,'OpenClipVerifier',lambda *a:SimpleNamespace(error='',product_evidence=[],
        last_embedding=None,subject_reference_indices=[],focus_subject=lambda _:None,
        discover_product_queries=lambda:[],score=lambda _:.7))
    monkeypatch.setattr(text_overlay,'TextOverlayDetector',lambda *a:SimpleNamespace(note='',
        reference_text=lambda _: '',analyze=lambda _:{'source_quality':'clean-source'}))
    monkeypatch.setattr(sf,'search_google_vision',lambda *a:([],[]))
    monkeypatch.setattr(sf,'search_local_cache',lambda *a:[])
    monkeypatch.setattr(sf,'search_local_hints',lambda *a:[])
    base={'products':[],'query_evidence':{'caption':caption},
        'query_details':[{'query':'kitchen mat','language':'en','intent':'product'}],
        'tiktok_query_details':[{'query':'kitchen mat','language':'en','evidence_quote':'주방 매트'}]}
    monkeypatch.setattr(sf,'product_query_plan',lambda *a:copy.deepcopy(base))
    captured=[]
    def browser(settings,frames,queries,limit,root,**options):
        captured.append(options['provider_queries']['tiktok'])
        return {'candidates':[],'searches':[],'notes':[],'terms':[]}
    monkeypatch.setattr('hotpost.browser_search.browser_search',browser)
    result=sf.find_sources(settings,'ref',search_request=search_request)
    assert captured==[expected]
    assert result['product_evidence']['tiktok_query_details']==base['tiktok_query_details']
    assert any(q['query']=='kitchen mat' for q in result['query_details'])
    assert result['product_evidence']['tiktok_operator_request'] is True
