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


@pytest.mark.parametrize('body,status',[('verify you are human','captcha'),('log in to search','login_required'),('', 'not_attempted')])
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
