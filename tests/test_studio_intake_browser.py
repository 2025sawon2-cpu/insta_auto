"""Collection receipt pagination against isolated API data."""
import json

from test_studio_board_browser import studio_page


def test_intake_pages_bound_lists_keep_links_and_survive_refresh(studio_page):
    from playwright.sync_api import expect
    page, _ = studio_page
    receipt = dict(available=True, ready=True, selection_ready=True, enabled=True,
                   updated_at=1791300000, new_posts=13, new_hot_videos=13,
                   created=13, existing=0, blocked=6,
                   rows=[dict(rank=i+1, registration='new', state='completed',
                              label='완료', title=f'결과 {i+1}', reason='등록됨',
                              solution='', task_id=f'work-{i+1}') for i in range(13)],
                   candidates=[dict(username='test', title=f'후보 {i+1}',
                                    shortcode=f'code-{i+1}', task_id=f'work-{i+1}')
                               for i in range(13)])
    page.route('**/api/studio/intake', lambda route: route.fulfill(
        content_type='application/json', body=json.dumps(receipt)))
    page.add_init_script("""const nativeInterval=window.setInterval;
        window.setInterval=(fn,ms,...args)=>{
            if(ms===30000){window.refreshIntake=fn;return 1;}
            return nativeInterval(fn,ms,...args);
        };""")
    page.reload()
    page.locator('[data-intake-detail] > summary').click()
    page.locator('[data-intake-problems] > summary').click()
    page.locator('[data-intake-candidates] > summary').click()
    rows = page.get_by_role('navigation', name='자동 선정 결과 페이지')
    candidates = page.get_by_role('navigation', name='직접 고를 핫 영상 페이지')
    expect(page.locator('.intake-results article')).to_have_count(6)
    expect(page.locator('.intake-candidates article')).to_have_count(6)
    expect(rows.get_by_role('button', name='이전')).to_be_disabled()
    for theme in ['light', 'dark']:
        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
        buttons = candidates.locator('button')
        assert buttons.first.bounding_box()['y'] == buttons.last.bounding_box()['y']
        assert buttons.first.bounding_box()['height'] >= 44
        assert buttons.last.evaluate('(e)=>getComputedStyle(e).borderRadius') == '10px'
        assert buttons.last.evaluate('(e)=>getComputedStyle(e).fontFamily===getComputedStyle(e.parentElement).fontFamily')
        assert candidates.evaluate('(e)=>e.scrollWidth<=e.clientWidth')
    rows.get_by_role('button', name='다음').click()
    expect(page.locator('.intake-results h3').first).to_have_text('결과 7')
    expect(page.locator('.intake-results a').first).to_have_attribute('href', 'studio.html?work=work-7')
    expect(candidates).to_contain_text('1 / 3 페이지')
    candidates.get_by_role('button', name='다음').click()
    receipt['updated_at'] += 1
    page.evaluate('refreshIntake()')
    expect(rows).to_contain_text('2 / 3 페이지')
    expect(candidates).to_contain_text('2 / 3 페이지')
    expect(page.locator('[data-intake-problems]')).to_have_attribute('open', '')
    expect(page.locator('[data-intake-candidates]')).to_have_attribute('open', '')
    rows.get_by_role('button', name='다음').click()
    expect(page.locator('.intake-results article')).to_have_count(1)
    expect(rows.get_by_role('button', name='다음')).to_be_disabled()
    receipt['rows'] = receipt['rows'][:7]
    receipt['candidates'] = receipt['candidates'][:2]
    page.evaluate('refreshIntake()')
    expect(rows).to_contain_text('2 / 2 페이지')
    expect(page.locator('.intake-results h3')).to_have_text('결과 7')
    expect(candidates).to_have_count(0)
    expect(page.locator('.intake-candidates article')).to_have_count(2)
    page.set_viewport_size(dict(width=390, height=844))
    assert page.locator('#collection-intake').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
    assert rows.locator('button').first.bounding_box()['y'] == rows.locator('button').last.bounding_box()['y']
