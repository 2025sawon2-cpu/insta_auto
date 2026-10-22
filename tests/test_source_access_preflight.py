import copy
import json
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost.source_access_preflight import SourceAccessWaiting, check_access, observe_routes, current_routes
from hotpost import source_preparation as preparation


class Page:
    url='https://www.tiktok.com/'
    def __init__(self,body):self.body=body
    def locator(self,selector):return self
    def inner_text(self,**kwargs):return self.body
    def count(self):return 0


@pytest.mark.parametrize('body,status',[('verify you are human','captcha_review_pending'),('log in to search','login_required'),('', 'not_attempted')])
def test_actual_existing_body_controls_readiness(tmp_path,monkeypatch,body,status):
    settings=Settings(data_dir=tmp_path)
    monkeypatch.setattr('hotpost.source_browser_runtime.existing_page',lambda *a:Page(body))
    rows=observe_routes(settings,['tiktok'],context=object())
    assert rows[0]['status']==status and rows[0]['attempted'] is False


def test_restricted_query_is_not_captcha_and_saved_429_survives_clear_page(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path)
    monkeypatch.setattr('hotpost.source_browser_runtime.existing_page',lambda *a:Page('결과를 찾을 수 없음'))
    assert observe_routes(settings,['tiktok'],context=object())[0]['status']=='ready'
    folder=tmp_path/'search_cooldowns';folder.mkdir()
    (folder/'tiktok.json').write_text(json.dumps({'reason':'rate_limited','until':9999,'server_retry_after':True}))
    row=observe_routes(settings,['tiktok'],context=object(),now=9000)[0]
    assert row['status']=='cooldown' and row['retry_at']==9999
    assert json.loads((folder/'tiktok.json').read_text())['until']==9999


def test_saved_login_requires_explicit_recheck_and_exclusion_remains(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path)
    folder=tmp_path/'search_cooldowns';folder.mkdir()
    (folder/'tiktok.json').write_text(json.dumps({'reason':'login_required','requires_verification':True,'until':0}))
    monkeypatch.setattr('hotpost.source_browser_runtime.existing_page',lambda *a:Page('normal logged in page'))
    assert observe_routes(settings,['tiktok'],context=object())[0]['status']=='login_required'
    (tmp_path/'source_collection_policy.json').write_text(json.dumps({'disabled_platforms':{'tiktok':'user pause'}}))
    assert observe_routes(settings,['tiktok'],context=object())[0]['status']=='platform_disabled'


def test_marker_missing_never_attaches_or_restores_cookies(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path)
    monkeypatch.setattr('hotpost.source_browser_runtime.endpoint',lambda *_:'http://127.0.0.1:1234')
    monkeypatch.setattr('hotpost.source_browser_runtime.attach_browser',lambda *a:pytest.fail('migration attach forbidden'))
    assert current_routes(settings,['tiktok'])[0]['status']=='not_attempted'
    assert not settings.source_browser_profile_dir.exists()


def test_all_missing_routes_hold_same_input_without_any_files(tmp_path):
    settings=Settings(data_dir=tmp_path);job={'checkpoint':{}}
    observe=lambda s,ps:[{'provider':p,'status':'not_attempted','reason':'existing_browser_tab_missing'} for p in ps]
    for _ in range(3):
        with pytest.raises(SourceAccessWaiting):check_access(settings,{},job,observe=observe)
    assert job['checkpoint']['source_access_preflight']['ready_routes']==[]
    assert list(tmp_path.iterdir())==[]


def test_one_ready_route_with_unused_scope_can_proceed(tmp_path):
    settings=Settings(data_dir=tmp_path);job={'checkpoint':{}}
    plan={'products':[],'query_details':[{'query':'handheld steam cleaner','language':'en','intent':'subject'}]}
    observe=lambda s,ps:[{'provider':p,'status':'ready' if p=='youtube' else 'login_required'} for p in ps]
    assert check_access(settings,{},job,plan=plan,observe=observe)==['youtube']
    history=[{'provider':'youtube','query':q,'status':'no_results'} for q in
             ['handheld steam cleaner','handheld steam cleaner raw footage no captions','handheld steam cleaner close up footage']]
    with pytest.raises(SourceAccessWaiting):check_access(settings,{},job,plan=plan,history=history,observe=observe)


def test_ready_image_route_cannot_spin_rounds_when_only_text_receipts_are_missing(tmp_path):
    settings=Settings(data_dir=tmp_path);job={'checkpoint':{}}
    frame=tmp_path/'frame.jpg';frame.write_bytes(b'observed frame')
    plan={'query_details':[{'query':'handheld steam cleaner','language':'en'}],
          'search_minimums':{'en':5,'zh':5}}
    observe=lambda *_:[{'provider':'tiktok','status':'captcha'},
        {'provider':'youtube','status':'login_required'}, {'provider':'yandex-images','status':'ready'}]
    for _ in range(3):
        with pytest.raises(SourceAccessWaiting):
            check_access(settings,{},job,plan=plan,frames=[frame],observe=observe,search_only=True)
    cp=job['checkpoint']['source_access_preflight']
    assert cp['ready_routes']==[]
    assert cp['observations'][-1]['reason']=='text_search_receipts_required'
    assert cp['observations'][-1]['access_status']=='ready'
    # Image search remains available when actual additional footage is needed.
    assert check_access(settings,{},job,plan=plan,frames=[frame],observe=observe)==['yandex-images']


@pytest.mark.parametrize('missing',['none','core','diversity','selection','scene','repair','request'])
def test_query_only_eligibility_keeps_real_footage_recovery(missing):
    from hotpost.source_coverage import query_receipts_only
    state={'automation':{'active':True},'source_policy':{'search_minimums':{'en':5,'zh':5}}}
    job={'kind':'collect_sources','payload':{}}
    goal={'core_ready':True,'source_diversity_ready':True}
    if missing=='core':goal['core_ready']=False
    if missing=='diversity':goal['source_diversity_ready']=False
    if missing=='selection':goal['selection_recovery_required']=True
    if missing=='scene':state['daily_quality']={'scene_requirements':{'ready':False}}
    if missing=='repair':job['payload']['daily_quality_repair']=True
    if missing=='request':state['source_search_brief']='different footage'
    assert query_receipts_only(state,job,goal)==(missing=='none')


def test_real_collect_claim_with_five_sources_waits_without_new_round_when_only_image_is_ready(tmp_path,monkeypatch):
    from test_source_diversity_completion_recovery import setup
    studio,tid,folder,edit=setup(tmp_path)
    studio.store.finish(edit,{},lambda *a:None)
    studio.settings.source_browser_search=True
    def missing_queries(s,db):
        s['source_acquisition']['queries']=[]
        studio.ensure_source_collection(s,db)
    studio.store.change(tid,missing_queries)
    job=studio.store.claim('sources',task_id=tid)
    state=studio.store.get(tid);before=copy.deepcopy(state['source_acquisition'])
    plan={'query_details':[{'query':'hand warmer','language':'en'}],
          'search_minimums':{'en':5,'zh':5}}
    frame=folder/'actual-frame.jpg';frame.write_bytes(b'observed image')
    monkeypatch.setattr(preparation,'preflight_preparation',lambda *a:(plan,[frame]))
    monkeypatch.setattr('hotpost.source_access_preflight.current_routes',lambda *_:[
        {'provider':'tiktok','status':'captcha'}, {'provider':'yandex-images','status':'ready'}])
    with pytest.raises(SourceAccessWaiting) as caught:studio._source_access_gate(state,job)
    studio.handle_source_error(job,caught.value)
    assert studio.store.get(tid)['source_acquisition']==before
    with studio.store.connect() as db:
        row=db.execute('select id,status,checkpoint from jobs where id=?',(job['id'],)).fetchone()
        assert row['status']=='queued'
        assert json.loads(row['checkpoint'])['source_access_preflight']['ready_routes']==[]
        assert db.execute("select count(*) from jobs where task_id=? and kind='collect_sources'",(tid,)).fetchone()[0]==1


def test_preflight_wait_preserves_real_claim_rounds_and_accounting(tmp_path,monkeypatch):
    from test_parallel_sources import task
    studio,tid,_=task(tmp_path)
    studio.store.change(tid,lambda s,db:s['source_acquisition'].update(waiting={'searches':[]},
        rounds=[{'manifest_path':'immutable-prior'}],repair_round=7,urls=['inspected']))
    job=studio.store.claim('sources');before=copy.deepcopy(studio.store.get(tid)['source_acquisition'])
    monkeypatch.setattr(preparation,'preflight_preparation',lambda *a:(None,[]))
    monkeypatch.setattr('hotpost.source_access_preflight.current_routes',lambda s,ps:[{'provider':p,'status':'not_attempted'} for p in ps])
    monkeypatch.setattr('hotpost.source_finder.find_sources',lambda *a,**k:pytest.fail('full finder during access wait'))
    with pytest.raises(SourceAccessWaiting) as caught:studio._collect_sources(studio.store.get(tid),job)
    studio.handle_source_error(job,caught.value)
    assert studio.store.get(tid)['source_acquisition']==before
    with studio.store.connect() as db:
        row=db.execute('select id,status,checkpoint from jobs where id=?',(job['id'],)).fetchone()
    assert row['status']=='queued' and row['id']==job['id']
    cp=json.loads(row['checkpoint']);assert 'auto_retries' not in cp and 'service_retries' not in cp
    assert not studio.settings.source_dir.exists()


def bundle(tmp_path,monkeypatch):
    monkeypatch.setattr('hotpost.source_planning.QUERY_PLAN_POLICY','test-current',raising=False)
    reference=tmp_path/'ref.mp4';reference.write_bytes(b'real reference identity')
    frame=tmp_path/'frame.jpg';frame.write_bytes(b'real observed pixels')
    sheet=tmp_path/'sheet.jpg';sheet.write_bytes(b'real observed sheet')
    path=tmp_path/'bundle.json'
    preparation.save_bundle(path,'스팀청소기',{'speech':'제품'},reference,[frame],sheet,
        transcript={'speech':'제품'},query_plan={'query_details':[{'query':'steam cleaner'}]})
    return path,reference,frame


@pytest.mark.parametrize('change',['frame','reference','query_plan','transcript'])
def test_preparation_rejects_changed_media_or_plan_without_rebuilding(tmp_path,monkeypatch,change):
    path,reference,frame=bundle(tmp_path,monkeypatch)
    if change in {'frame','reference'}:(frame if change=='frame' else reference).write_bytes(b'changed')
    else:
        value=json.loads(path.read_text(encoding='utf-8'));value[change]={'invented':'new product'};path.write_text(json.dumps(value),encoding='utf-8')
    with pytest.raises(ValueError):preparation.load_bundle(path,'스팀청소기',{'speech':'제품'})
    assert len(list(tmp_path.iterdir()))==4


def test_policy_upgrade_preserves_media_bundle_and_does_not_inherit_plan(tmp_path,monkeypatch):
    path,reference,frame=bundle(tmp_path,monkeypatch)
    old=path.read_bytes()
    monkeypatch.setattr('hotpost.source_planning.QUERY_PLAN_POLICY','test-new',raising=False)
    value=preparation.load_bundle(path,'스팀청소기',{'speech':'제품'})
    assert value['query_policy']!=preparation.query_policy()
    assert path.read_bytes()==old and preparation.digest(reference)==value['files'][0]['sha256']


@pytest.mark.parametrize('has_current_pool',[True,False])
def test_v5_preflight_prefers_matching_acquisition_pool_and_never_exhausts_legacy_pool(tmp_path,monkeypatch,has_current_pool):
    from hotpost.source_policy import montage_policy
    from hotpost.source_visual_queries import search_contract
    settings=Settings(data_dir=tmp_path)
    reference=tmp_path/'reference.mp4';reference.write_bytes(b'actual reference')
    frame=tmp_path/'frame.jpg';frame.write_bytes(b'actual frame')
    sheet=tmp_path/'sheet.jpg';sheet.write_bytes(b'actual sheet')
    caption='차량 후면 텐트';text={'speech':'차 뒤에서 펼쳐지는 텐트'}
    monkeypatch.setattr('hotpost.source_finder._post',lambda *a:SimpleNamespace(caption=caption))
    monkeypatch.setattr('hotpost.source_finder._transcript_evidence',lambda *a:text)
    _,legacy=preparation.bundle_paths(settings,'tent',caption,text)
    preparation.save_bundle(legacy,caption,text,reference,[frame],sheet,
                            query_plan={'query_details':[{'query':'elevated tent'}]})
    old_bytes=legacy.read_bytes()
    policy=montage_policy(settings)
    state={'shortcode':'tent','product':'텐트','reference_video':str(reference),'source_policy':policy}
    current=preparation.acquisition_bundle_path(settings,'tent',caption,text,policy,'텐트')
    plan={'source_policy':policy,'query_details':[{'query':'rear-mounted folding elevated tent'}],
          'visual_query_evidence':{'evidence':{**search_contract({'en':5,'zh':5}),'subject_hint':'텐트'}}}
    if has_current_pool:
        preparation.save_bundle(current,caption,text,reference,[frame],sheet,query_plan=plan)
    selected,frames=preparation.preflight_preparation(settings,state)
    assert selected==(plan if has_current_pool else None)
    assert frames==[frame]
    assert legacy.read_bytes()==old_bytes
    if not has_current_pool:
        # Unknown new scopes permit preparation, but no auth block is waived.
        observe=lambda *_:[{'provider':'tiktok','status':'ready'}]
        assert check_access(settings,state,{'checkpoint':{}},plan=selected,frames=frames,
            history=[{'provider':'tiktok','query':'elevated tent','status':'no_results'}],observe=observe)==['tiktok']
        with pytest.raises(SourceAccessWaiting):
            check_access(settings,state,{'checkpoint':{}},plan=selected,frames=frames,
                         observe=lambda *_:[{'provider':'tiktok','status':'captcha'}])
