import json
import mimetypes
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest

from hotpost.config import Settings
from hotpost.criteria import defaults
from hotpost.display_settings import DEFAULTS
from hotpost.models import Post, Profile
from hotpost.report import build_report
from hotpost.storage import Storage

WEB=Path(__file__).resolve().parents[1]/'web'


@pytest.fixture
def dashboard(tmp_path):
    pw=pytest.importorskip('playwright.sync_api')
    settings=Settings(data_dir=tmp_path,web_dir=tmp_path,download_thumbs=False)
    store=Storage(settings.db_path);now=int(time.time())
    store.upsert_profile(Profile('creator',followers=1000))
    posts=[Post(f'old{i}','creator',now-(i+2)*86400,'reel',100,10,1000,caption='주방 요리') for i in range(12)]
    posts += [Post('camp','creator',now-3600,'reel',2000,100,30000,caption='캠핑 여행 수납 가방'),
              Post('clean','creator',now-7200,'reel',1000,100,20000,caption='청소 세탁 곰팡이')]
    store.upsert_posts(posts,collected_at=now)
    report=build_report(settings,store,'test',[],['creator']);store.close()
    report['acquisition_candidates']=[dict(shortcode='camp',username='creator',views_per_follower=30,views=30000)]
    state={'display':dict(DEFAULTS),'report':report,'tasks':[],
           'health':{'collection':{'state':'success','newest_post_update':now},'schedule':{},'hot_tracking':{}},
           'notifications':[dict(id=1,message='새로운 게시물이 있습니다',created_at=now,seen_at=None),
                            dict(id=2,message='이전에 읽은 알림',created_at=now,seen_at=now)]}
    with pw.sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        def route(route):
            request=route.request;path=urlparse(request.url).path
            result={}
            if path=='/api/display-settings':
                if request.method=='PUT':state['display']=request.post_data_json['values']
                result={'values':state['display'],'defaults':DEFAULTS}
            elif path=='/api/criteria':
                if request.method=='PUT':
                    report['criteria']['values']=request.post_data_json['values'];report['criteria']['version']+=1
                    result={'criteria':report['criteria'],'report':report}
                else:result={**report['criteria'],'defaults':defaults(settings)}
            elif path=='/api/accounts':
                result={'accounts':[dict(username='creator',followers=1000,posts_count=14)],'count':1}
            elif path=='/api/notifications':
                result={'notifications':state['notifications'],'unseen':sum(n['seen_at'] is None for n in state['notifications'])}
            elif path=='/api/notifications/seen':
                before=len(state['notifications']);state['notifications']=[n for n in state['notifications'] if n['seen_at'] is None]
                result={'deleted':before-len(state['notifications'])}
            elif path.startswith('/api/notifications/'):
                for n in state['notifications']:
                    if n['id']==int(path.split('/')[3]):n['seen_at']=now
                result={'seen':True}
            elif path=='/api/collection-status':result=state['health']
            elif path=='/api/report':result=state['report']
            elif path=='/api/studio':result={'tasks':state['tasks']}
            elif path=='/api/jobs':result={'jobs':[]}
            elif path.startswith('/api/'):
                result={}
            elif path=='/data.js':
                route.fulfill(content_type='application/javascript',body='window.HOTPOST_REPORT='+json.dumps(report)+';');return
            else:
                file=WEB/('index.html' if path=='/' else path.lstrip('/'))
                if file.is_file():route.fulfill(content_type=mimetypes.guess_type(str(file))[0] or 'text/plain',body=file.read_bytes())
                else:route.fulfill(status=404)
                return
            route.fulfill(content_type='application/json',body=json.dumps(result))
        page.route('**/*',lambda r:route(r) if r.request.url.startswith('http://dashboard.test') else r.abort())
        yield page,state
        browser.close()
        assert not errors,errors


def test_main_is_compact_and_search_and_category_filters_work(dashboard):
    page,state=dashboard
    page.goto('http://dashboard.test/')
    page.wait_for_selector('.card')
    assert page.locator('#criteria,#period,#presets,#accounts,#method,#acquisition-candidates').count()==0
    assert not page.locator('#q').is_visible()
    assert '오늘' in page.locator('#current-settings').text_content()
    assert '발견 시각' in page.locator('#current-settings').text_content()
    assert page.locator('#result-count').inner_text()=='2'
    assert page.locator('.listing-heading #current-settings,.listing-heading #result-count').count()==0
    topic_box=page.locator('.topic-panel').bounding_box()
    summary_box=page.locator('#current-settings').bounding_box()
    assert summary_box['x']>topic_box['x'] and summary_box['y']==topic_box['y']
    assert not page.locator('.threshold-scale').is_visible()
    page.locator('.discovery-conditions summary').click()
    assert page.locator('.threshold-scale li').count()==3
    assert page.locator('.threshold-scale').is_visible()
    page.locator('.discovery-conditions summary').click()
    labels=page.locator('#topics').inner_text()
    assert '캠핑·여행' in labels and '청소·세탁' in labels and '#' not in labels
    page.locator('#topics button').filter(has_text='캠핑·여행').click()
    assert page.locator('.card').count()==1
    assert page.locator('#result-count').inner_text()=='1'
    assert page.locator('#result-context').inner_text()=='캠핑·여행'
    page.locator('#topics button').filter(has_text='캠핑·여행').click()
    page.locator('#search-toggle').click();page.locator('#q').fill('곰팡이')
    page.wait_for_function("document.querySelectorAll('.card').length===1")
    page.locator('#q').press('Escape')
    assert not page.locator('#q').is_visible() and page.locator('.card').count()==2
    assert page.locator('#result-count').inner_text()=='2'
    page.locator('.card').first.click();assert page.locator('#modal').is_visible()


def test_new_collection_refreshes_open_dashboard_without_replacing_modal_media(dashboard):
    page,state=dashboard
    page.goto('http://dashboard.test/')
    page.wait_for_selector('.card')
    assert page.locator('#result-count').inner_text()=='2'
    page.locator('.card').first.click()
    page.evaluate("""() => {
        const player=document.createElement('video');player.id='refresh-player';
        const input=document.createElement('textarea');input.id='refresh-draft';input.value='보존할 입력';
        document.querySelector('.video-info-body').append(player,input);
        window.refreshPlayer=player;
    }""")
    report=state['report']
    newest=dict(next(p for p in report['posts'] if p['shortcode']=='camp'))
    newest['shortcode']='new-after-collection'
    report['posts'].append(newest)
    report['generated_at']+=1
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    page.wait_for_function("document.querySelector('#result-count').textContent==='3'")
    assert page.locator('#modal').is_visible()
    assert page.evaluate("window.refreshPlayer===document.querySelector('#refresh-player')")
    assert page.locator('#refresh-draft').input_value()=='보존할 입력'


def test_settings_save_survives_navigation_and_reload(dashboard):
    page,state=dashboard
    page.goto('http://dashboard.test/settings.html')
    page.wait_for_function("!document.querySelector('#settings-save').disabled")
    page.locator('#detection [data-v="all"]').click()
    page.locator('#period [data-v="72"]').click()
    page.locator('#kind [data-v="video"]').click()
    page.locator('#sort').select_option('views')
    page.locator('#presets [data-preset="views"]').click()
    page.locator('#settings-save').click()
    page.wait_for_function("document.querySelector('#settings-status').textContent.startsWith('저장했습니다')")
    assert page.locator('#settings-toast').inner_text()=='설정을 저장했습니다'
    assert page.url=='http://dashboard.test/settings.html'
    assert page.locator('#settings-save').inner_text()=='설정 저장'
    assert state['display']['period']==72 and state['display']['sort']=='views'
    assert state['report']['criteria']['values']['wvViews']==70
    page.locator('.settings-back').click();page.wait_for_selector('.card')
    assert '3일' in page.locator('#current-settings').text_content() and '조회수순' in page.locator('#current-settings').text_content()
    page.goto('http://dashboard.test/settings.html');page.wait_for_function("!document.querySelector('#settings-save').disabled")
    assert page.locator('#period [data-v="72"]').get_attribute('aria-pressed')=='true'
    page.locator('#detection [data-v="today"]').click()
    assert page.locator('#period [data-v="72"]').is_disabled()
    page.locator('#display-reset').click()
    assert page.locator('#period [data-v="72"]').is_disabled()
    assert page.locator('#detection [data-v="today"]').get_attribute('aria-pressed')=='true'


@pytest.mark.parametrize('endpoint',['criteria','display-settings'])
def test_settings_failed_save_does_not_show_success_toast(dashboard,endpoint):
    page,state=dashboard
    page.goto('http://dashboard.test/settings.html')
    page.wait_for_function("!document.querySelector('#settings-save').disabled")
    page.locator('#settings-save').click()
    page.wait_for_selector('#settings-toast:not([hidden])')
    def fail_save(route):
        if route.request.method=='PUT':
            route.fulfill(status=500,content_type='application/json',body=json.dumps({'error':'저장 실패'}))
        else:route.fallback()
    page.route('**/api/'+endpoint,fail_save)
    page.locator('#settings-save').click()
    page.wait_for_function("document.querySelector('#settings-status').textContent==='저장 실패'")
    assert not page.locator('#settings-toast').is_visible()
    assert page.locator('#settings-save').is_enabled()
    assert page.url=='http://dashboard.test/settings.html'


def test_removed_account_warning_is_hidden_but_current_failures_remain(dashboard):
    page,state=dashboard
    state['report']['notes']=['@retired_account: 이전 수집 실패']
    page.goto('http://dashboard.test/');page.wait_for_selector('.card')
    assert not page.locator('#banner').is_visible()
    state['report']['notes'].append('@creator: 현재 목록 계정의 수집 실패')
    page.reload();page.wait_for_selector('.card')
    assert not page.locator('#collection-health').is_visible()
    page.locator('#collection-notification-toggle').click()
    assert '@creator' in page.locator('#collection-health').inner_text()
    assert '@retired_account' not in page.locator('#collection-health').inner_text()
    assert '수집 기록' in page.locator('#collection-health').inner_text()
    assert len(state['report']['notes'])==2  # No historical report data is erased.


def test_collection_bell_read_state_persists_and_new_issue_reappears(dashboard):
    page,state=dashboard
    state['health']['collection'].update(state='blocked',last_run=dict(id=98,stop_reason='login_required',notes='세션 만료'))
    page.goto('http://dashboard.test/');page.wait_for_selector('#collection-notification-count:not([hidden])')
    assert not page.locator('#collection-health').is_visible()
    page.locator('#collection-notification-toggle').click()
    assert page.locator('#collection-health').is_visible()
    assert not page.locator('#collection-notification-count').is_visible()
    page.keyboard.press('Escape')
    page.reload();page.wait_for_selector('.card')
    page.wait_for_function("document.querySelector('#collection-notification-loading').hidden")
    assert not page.locator('#collection-health').is_visible()
    assert not page.locator('#collection-notification-count').is_visible()
    state['health']['collection'].update(state='blocked',last_run=dict(id=99,started_at=10,finished_at=20,stop_reason='login_required',notes='세션 만료'))
    page.reload();page.wait_for_selector('#collection-notification-count:not([hidden])')
    page.locator('#collection-notification-toggle').click()
    assert '해결 방법:' in page.locator('#collection-health').inner_text()
    assert '로그인 복구 방법' in page.locator('#collection-health').inner_text()
    page.locator('#collection-health a').first.click()
    page.wait_for_url('**/accounts.html#help-login')
    page.wait_for_function("document.querySelector('#collection-help').open")
    assert page.locator('#help-login').is_visible()


def test_report_warning_can_be_closed_without_hiding_other_notices(dashboard):
    page,state=dashboard
    state['report']['is_sample']=True
    page.goto('http://dashboard.test/');page.wait_for_selector('#banner .notice-close')
    page.locator('#banner .notice-close').click()
    assert not page.locator('#banner').is_visible()
    page.locator('#collection-notification-toggle').click()
    assert page.locator('#collection-health').is_visible()
    page.reload();page.wait_for_selector('.card')
    assert not page.locator('#banner').is_visible()


def test_account_summary_candidates_and_notification_actions(dashboard):
    page,state=dashboard
    page.goto('http://dashboard.test/accounts.html');page.wait_for_selector('.account-row')
    assert page.locator('.account-row').count()==1
    assert '평소 조회수' in page.locator('.account-row').inner_text()
    assert page.locator('.account-candidates').count()==1
    assert not page.locator('#notification-panel').is_visible()
    assert page.locator('#notification-count').inner_text()=='1'
    page.locator('#notification-toggle').click()
    assert page.locator('#notification-panel').is_visible()
    page.locator('#notification-clear').click()
    page.wait_for_function("document.querySelectorAll('.notification-item').length===1")
    assert state['notifications'][0]['seen_at'] is None
    page.locator('[data-seen="1"]').click()
    page.wait_for_function("document.querySelector('#notification-count').hidden")
    page.locator('#notification-clear').click()
    page.wait_for_selector('.notification-empty')
    page.keyboard.press('Escape');assert not page.locator('#notification-panel').is_visible()


@pytest.mark.parametrize('path',['/','/settings.html','/accounts.html'])
def test_mobile_layout_fits_viewport(dashboard,path):
    page,state=dashboard
    page.set_viewport_size({'width':390,'height':844})
    page.goto('http://dashboard.test'+path)
    ready='#cards .card' if path=='/' else '#crit-summary' if 'settings' in path else '.account-row'
    page.wait_for_selector(ready)
    if 'accounts' in path:page.locator('#notification-toggle').click()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')

@pytest.mark.parametrize('width',[1440,390])
def test_detail_shows_video_information_without_an_extra_click(dashboard,width):
    page,state=dashboard
    page.set_viewport_size({'width':width,'height':1000})
    original=json.dumps(state['report'],sort_keys=True)
    page.goto('http://dashboard.test/');page.wait_for_selector('.card')
    card=page.locator('.card').first
    for label in ['핫 최초 감지일','신뢰도','잠정 후보','비교 게시물']:
        assert label not in card.inner_text()
    assert '조회수' in card.inner_text()
    card.locator('.thumb').click()
    page.wait_for_selector('#begin-auto')
    assert page.locator('.benchmark-performance').is_visible()
    assert page.locator('#production-flow').is_visible()
    info=page.locator('.video-info')
    assert info.locator('summary').count()==0
    assert info.locator('.video-info-title').inner_text()=='영상 정보'
    assert info.locator('.fullcap').is_visible()
    assert info.locator('.cmp').is_visible()
    assert '추가 확인 사항' not in page.locator('#modal-body').inner_text()
    assert info.locator('.kv').is_visible()
    for label in ['처음 발견한 시각','팔로워','비교 게시물']:
        assert label in info.inner_text()
    for label in ['반응 성숙도','신뢰도','보정 전 배수','시스템 판정 참고','최근 조회 상태','최근 조회 속도','가속도','조회 성공 관측','성장 비교','판정 상태','14일 추적']:
        assert label not in info.inner_text()
    assert info.locator('.kv>div').count()==3
    metrics=info.locator('.detail-metric')
    assert metrics.count()==3
    boxes=[metrics.nth(i).bounding_box() for i in range(3)]
    assert len({box['y'] for box in boxes})==1
    assert boxes[0]['x']<boxes[1]['x']<boxes[2]['x']
    assert page.locator('.pr-stage').count()==4
    assert page.locator('.pr-stage:disabled').count()==4
    assert page.get_by_role('button',name='완성 영상 보기',exact=True).is_disabled()
    assert page.get_by_role('button',name='↓ 영상 다운로드',exact=True).is_disabled()
    assert page.locator('#source-download,#transcript-extract,#source-status,#transcript-status').count()==0
    assert '개별 소스·대본 도구' not in info.inner_text()
    assert page.locator('#production-flow').is_visible()
    assert page.locator('.modal-card').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
    page.keyboard.press('Escape')
    assert not page.locator('#modal').is_visible()
    card.locator('.card-open-production').click()
    assert info.locator('.fullcap').is_visible()
    assert info.locator('.kv').is_visible()
    page.keyboard.press('Escape')
    assert json.dumps(state['report'],sort_keys=True)==original


def snapshot(page,name):
    directory=os.environ.get('HOTPOST_UI_SNAPSHOT_DIR')
    if directory:
        target=Path(directory);target.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(target/(name+'.png')),full_page=False)


def production_task(code):
    return {'id':'work-'+code,'shortcode':code,'status':'rewriting',
            'automation':{'protocol':2,'active':True},'run_id':'current',
            'source_goal':{'count':0,'target':10,'platforms':{},'ready':False},
            'scripts':[],'voices':[],'sources':[],
            'jobs':[{'kind':'rewrite','status':'running'}],
            'pipeline':[{'id':'current','status':'running','created':int(time.time()),'steps':[]}]}


@pytest.mark.parametrize('width',[1440,390])
def test_dashboard_states_and_perimeter_animation_follow_current_production(dashboard,width):
    page,state=dashboard
    page.set_viewport_size({'width':width,'height':1000})
    task=production_task('camp');state['tasks']=[task]
    page.clock.install()
    page.goto('http://dashboard.test/');page.wait_for_selector('.card[data-production-state="working"]')
    card=page.locator('.card[data-code="camp"]')
    assert card.locator('.production-badge').inner_text()=='제작중'
    assert card.locator('.cap,.production-link').count()==0
    assert '캠핑 여행 수납 가방' not in card.inner_text()
    assert card.locator('.card-open-production').inner_text()=='제작 보기 →'
    assert card.locator('.production-status a').count()==0
    assert card.evaluate("el=>getComputedStyle(el,'::after').animationName")=='production-border'
    start=card.evaluate("el=>getComputedStyle(el,'::after').getPropertyValue('--production-angle')")
    page.wait_for_timeout(150)
    assert card.evaluate("el=>getComputedStyle(el,'::after').getPropertyValue('--production-angle')")!=start
    page.emulate_media(reduced_motion='reduce')
    assert card.evaluate("el=>getComputedStyle(el,'::after').animationName")=='none'
    page.emulate_media(reduced_motion='no-preference')
    snapshot(page,f'cards-working-{width}')
    task.update(status='completed',jobs=[])
    task['pipeline'][0].update(status='completed',video_url='/complete.mp4')
    page.clock.fast_forward(4100)
    page.wait_for_function("document.querySelector('[data-code=camp]').dataset.productionState==='completed'")
    assert card.locator('.production-badge').inner_text()=='완성'
    assert card.locator('.card-open-production').inner_text()=='완성 영상 보기 →'
    assert card.evaluate("el=>getComputedStyle(el,'::after').animationName")=='none'
    task.update(status='attention',error='음성 설정을 확인해 주세요.')
    task['pipeline'].append({'id':'revision','status':'failed','steps':[]})
    task['run_id']='revision'
    page.clock.fast_forward(4100)
    page.wait_for_function("document.querySelector('[data-code=camp]').dataset.productionState==='attention'")
    assert card.locator('.production-badge').inner_text()=='확인필요'
    assert card.evaluate("el=>getComputedStyle(el,'::after').animationName")=='none'
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')


@pytest.mark.parametrize('width',[1440,390])
def test_result_buttons_enable_when_assets_arrive_and_preserve_playback(dashboard,width):
    page,state=dashboard
    page.set_viewport_size({'width':width,'height':1000})
    task=production_task('camp');state['tasks']=[task]
    page.clock.install()
    page.goto('http://dashboard.test/');page.wait_for_selector('.card')
    page.locator('.card[data-code="camp"] .thumb').click()
    page.wait_for_selector('.pr-stage.is-running')
    assert page.locator('.pr-stage').count()==4
    assert page.locator('.pr-stage:disabled').count()==4
    assert '작업 중' in page.locator('[data-stage="script"]').inner_text()
    assert page.get_by_role('button',name='완성 영상 보기',exact=True).is_disabled()
    assert page.get_by_role('button',name='↓ 영상 다운로드',exact=True).is_disabled()
    assert page.get_by_role('link',name='제작실에서 수정',exact=True).is_visible()
    snapshot(page,f'detail-pending-{width}')
    task.update(status='completed',jobs=[],script_id='s1',voice_id='v1')
    task['scripts']=[{'id':'s1','text':'완성된 제작 대본'}]
    task['voices']=[{'id':'v1','script_id':'s1','path_url':'/voice.wav'}]
    task['source_goal'].update(count=2,ready=True)
    task['pipeline'][0].update(status='completed',video_url='/complete.mp4',
        steps=[{'key':'export','status':'completed','download_url':'/download.mp4'}])
    page.clock.fast_forward(3100)
    page.wait_for_selector('.pr-video video[src="/complete.mp4"]')
    assert page.locator('.pr-stage:disabled').count()==0
    assert page.get_by_role('button',name='완성 영상 보기',exact=True).is_enabled()
    assert page.get_by_role('link',name='↓ 영상 다운로드',exact=True).get_attribute('href')=='/download.mp4'
    page.evaluate("window.resultPlayer=document.querySelector('video[src=\"/complete.mp4\"]')")
    page.locator('[data-stage="script"]').click()
    assert page.locator('.pr-script').inner_text()=='완성된 제작 대본'
    page.clock.fast_forward(3100)
    assert page.evaluate("window.resultPlayer===document.querySelector('video[src=\"/complete.mp4\"]')")
    assert page.locator('[data-stage="script"]').get_attribute('aria-expanded')=='true'
    assert page.locator('.modal-card').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
    snapshot(page,f'detail-completed-{width}')
    page.locator('.video-info').scroll_into_view_if_needed()
    snapshot(page,f'detail-information-{width}')
    task.update(status='rewriting',run_id='remake',script_id=None,voice_id=None,
                jobs=[{'kind':'rewrite','status':'running'}])
    task['source_goal'].update(count=0,ready=False)
    task['pipeline'].append({'id':'remake','status':'running','steps':[]})
    page.clock.fast_forward(3100)
    page.wait_for_selector('.pr-waiting-wrap')
    assert page.evaluate("window.resultPlayer===document.querySelector('video[src=\"/complete.mp4\"]')")
    assert page.locator('[data-stage="final"]').is_enabled()
    assert page.locator('[data-stage="script"]').is_disabled()
    assert page.locator('.pr-waiting-wrap [data-view-result]').is_disabled()
    assert page.locator('.pr-result-card [data-view-result]').is_enabled()
    assert page.get_by_role('link',name='↓ 영상 다운로드',exact=True).get_attribute('href')=='/download.mp4'
