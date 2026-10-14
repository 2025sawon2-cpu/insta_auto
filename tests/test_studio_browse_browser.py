"""Collection date browsing and separate intervention screen."""
import copy
import json
from datetime import datetime, timedelta, timezone

from test_studio_board_browser import studio_page


def test_two_lanes_attention_date_range_and_return_preserve_state(studio_page):
    from playwright.sync_api import expect
    page, tasks = studio_page
    page.locator('[data-list-view=board]').click()
    today = datetime.now(timezone(timedelta(hours=9)))
    yesterday = today - timedelta(days=1)
    old = copy.deepcopy(tasks[0])
    old.update(id='yesterday', title='어제 수집한 영상', collected_at=int(yesterday.timestamp()))
    tasks.append(old)
    for i in range(8):
        done = copy.deepcopy(tasks[5]);done.update(id=f'finished-{i}',created=i+2)
        tasks.append(done)
    page.evaluate('refreshStudio()')
    expect(page.locator('#filters')).to_have_count(0)
    expect(page.locator('.kanban-column:visible')).to_have_count(2)
    expect(page.locator('#date-range-label')).to_contain_text('오늘')
    expect(page.locator('#attention-count')).to_have_text('2')
    expect(page.locator('#outside-dates')).to_contain_text('제작 중 1개')
    expect(page.locator('[data-work-card=yesterday]')).to_have_count(0)
    page.locator('[data-stage=finished] [data-lane-page="2"]').click()
    before = page.locator('[data-stage=finished] [data-work-card]').first.get_attribute('data-work-card')
    page.locator('#search').fill('')
    page.locator('#attention-open').click()
    expect(page.locator('#attention-back')).to_be_visible()
    expect(page.locator('[data-stage=attention]')).to_be_visible()
    expect(page.locator('.kanban-column:visible')).to_have_count(1)
    expect(page.locator('[data-work-card=script]')).to_be_visible()
    page.evaluate('refreshStudio()')
    expect(page.locator('#browse-title')).to_have_text('확인 필요한 영상')
    page.locator('#attention-back').click()
    expect(page.locator('[data-stage=finished] [data-work-card]').first).to_have_attribute('data-work-card', before)
    page.locator('#date-open').click()
    page.locator('#date-start').fill(yesterday.strftime('%Y-%m-%d'))
    page.locator('#date-end').fill(today.strftime('%Y-%m-%d'))
    page.get_by_role('button',name='선택한 기간 보기').click()
    expect(page.locator('[data-work-card=yesterday]')).to_be_visible()
    page.locator('#search').fill('어제 수집')
    expect(page.locator('#work-list [data-work-card]')).to_have_count(1)
    page.locator('#attention-open').click()
    expect(page.locator('#board-empty')).to_be_visible()
    page.locator('#attention-back').click()
    expect(page.locator('#search')).to_have_value('어제 수집')
    page.locator('#date-today').click()
    expect(page.locator('[data-work-card=yesterday]')).to_have_count(0)
    page.locator('#show-outside').click()
    expect(page.locator('#date-range-label')).to_have_text('전체 기간')
    expect(page.locator('[data-work-card=yesterday]')).to_be_visible()
    page.set_viewport_size(dict(width=390,height=844))
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), page.evaluate('''()=>[...document.querySelectorAll('main *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,8).map(e=>[e.className,e.getBoundingClientRect().width,e.getBoundingClientRect().right])''')


def test_range_validation_reduced_motion_and_draft_does_not_change_completion(studio_page):
    from playwright.sync_api import expect
    page, _ = studio_page
    page.locator('[data-list-view=board]').click()
    page.emulate_media(reduced_motion='reduce')
    page.locator('#date-open').click()
    page.locator('#date-start').fill('2026-10-10')
    page.locator('#date-end').fill('2026-10-09')
    page.get_by_role('button',name='선택한 기간 보기').click()
    expect(page.locator('#date-error')).to_contain_text('올바른 순서')
    page.keyboard.press('Escape')
    page.locator('#attention-open').click()
    expect(page.locator('#attention-back')).to_be_visible()
    page.locator('#attention-back').click()
    page.locator('[data-work=done]').click()
    page.locator('#detail-tabs [data-detail-tab=script]').click()
    page.locator('[data-field=script]').fill('변경했지만 아직 제작하지 않은 대본')
    expect(page.locator('#drawer-status')).to_have_text('완성')


def test_unknown_collection_date_remains_accessible_and_summary_survives_screen_change(studio_page):
    from playwright.sync_api import expect
    page, tasks = studio_page
    tasks[5].pop('collected_at')
    page.evaluate('refreshStudio()')
    expect(page.locator('#outside-dates')).to_contain_text('수집 날짜를 확인할 수 없는 영상 1개')
    expect(page.locator('[data-work-card=done]')).to_have_count(0)
    page.locator('#date-open').click()
    page.locator('#date-all').click()
    expect(page.locator('[data-work-card=done]')).to_be_visible()
    expect(page.locator('#date-range-label')).to_have_text('전체 기간')
    page.locator('#attention-open').click()
    expect(page.locator('[data-work-card=script]')).to_be_visible()
    expect(page.locator('[data-metric=finished] strong')).to_have_text('1편')
    expect(page.locator('[data-metric=working] strong')).to_have_text('3편')


def test_today_uses_discovery_date_and_cards_do_not_show_creation_date(studio_page):
    from playwright.sync_api import expect
    page,tasks=studio_page
    now=datetime.now(timezone(timedelta(hours=9)))
    earlier=now-timedelta(days=2)
    tasks[0].update(collected_at=int(earlier.timestamp()),hot_detected_at=int(now.timestamp()),
                    collection_date_at=int(now.timestamp()),created=int(earlier.timestamp()))
    page.locator('[data-list-view=grid]').click()
    page.evaluate('refreshStudio()')
    expect(page.locator('[data-work-card=source]')).to_be_visible()
    expect(page.locator('[data-work-card=source] time')).to_contain_text(f'{now.month}. {now.day}.')
    expect(page.locator('#date-today')).to_have_attribute('aria-pressed','true')


def test_latest_collection_is_explicit_and_today_stays_today(studio_page):
    from playwright.sync_api import expect
    page,tasks=studio_page
    now=datetime.now(timezone(timedelta(hours=9)))
    yesterday=now-timedelta(days=1)
    for task in tasks:task['collected_at']=int((now-timedelta(days=2)).timestamp())
    tasks[0]['collected_at']=int(yesterday.timestamp())
    receipt=dict(available=True,ready=True,selection_ready=False,enabled=False,
                 started_at=int(yesterday.timestamp()),finished_at=int(yesterday.timestamp()),
                 updated_at=int(yesterday.timestamp()),new_posts=3,new_hot_videos=1,
                 created=0,existing=1,blocked=0,rows=[],candidates=[])
    page.route('**/api/studio/intake',lambda route:route.fulfill(content_type='application/json',body=json.dumps(receipt)))
    page.reload()
    expect(page.locator('#board-empty')).to_contain_text('아직 수집 결과가 없습니다')
    expect(page.locator('#collection-date-note')).to_contain_text(yesterday.strftime('%Y-%m-%d'))
    page.locator('#date-latest').click()
    expect(page.locator('[data-work-card=source]')).to_be_visible()
    expect(page.locator('#date-range-label')).to_have_text(yesterday.strftime('%Y-%m-%d'))
    expect(page.locator('#date-today')).to_have_attribute('aria-pressed','false')
    page.locator('#date-today').click()
    expect(page.locator('[data-work-card=source]')).to_have_count(0)
    expect(page.locator('#date-range-label')).to_contain_text(now.strftime('%Y-%m-%d'))
    page.set_viewport_size(dict(width=390,height=844))
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')


def test_main_empty_state_points_to_attention_videos_for_the_selected_day(studio_page):
    from playwright.sync_api import expect
    page,tasks=studio_page
    now=datetime.now(timezone(timedelta(hours=9)))
    for task in tasks:
        if task['id'] not in ['script','edit']:task['collected_at']=int((now-timedelta(days=1)).timestamp())
    page.evaluate('refreshStudio()')
    expect(page.locator('#attention-count')).to_have_text('2')
    expect(page.locator('#board-empty')).to_contain_text('영상 2개는 ‘확인 필요한 영상’')
    page.locator('#attention-open').click()
    expect(page.locator('[data-work-card=script]')).to_be_visible()
    expect(page.locator('[data-work-card=edit]')).to_be_visible()


def test_today_follows_korean_midnight_but_explicit_range_remains_fixed(studio_page):
    from playwright.sync_api import expect
    page,tasks=studio_page
    # The browser stays open across Korean midnight (15:00 UTC).
    before=datetime(2026,10,11,14,59,55,tzinfo=timezone.utc)
    after=before+timedelta(seconds=10)
    page.clock.install(time=before)
    tasks[0]['collected_at']=int(before.timestamp())
    for task in tasks[1:]:task['collected_at']=int(after.timestamp())
    page.evaluate('refreshStudio()')
    expect(page.locator('#date-range-label')).to_contain_text('2026-10-11')
    expect(page.locator('[data-work-card=source]')).to_be_visible()
    page.clock.fast_forward(10000)
    page.evaluate('refreshStudio()')
    expect(page.locator('#date-range-label')).to_contain_text('2026-10-12')
    expect(page.locator('[data-work-card=source]')).to_have_count(0)
    page.locator('#date-open').click()
    page.locator('#date-start').fill('2026-10-11');page.locator('#date-end').fill('2026-10-11')
    page.get_by_role('button',name='선택한 기간 보기').click()
    page.clock.fast_forward(86400000)
    page.evaluate('refreshStudio()')
    expect(page.locator('#date-range-label')).to_have_text('2026-10-11')
    expect(page.locator('[data-work-card=source]')).to_be_visible()
