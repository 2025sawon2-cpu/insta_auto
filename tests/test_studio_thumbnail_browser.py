import io
import json
import copy
import shutil
import subprocess
import pytest

from PIL import Image
from test_studio_board_browser import studio_page


def test_thumbnail_draft_tabs_poll_save_and_mobile(studio_page,tmp_path):
    from playwright.sync_api import expect
    page,tasks=studio_page;t=tasks[5]
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:pytest.skip('FFmpeg unavailable for the real preview fixture')
    video=tmp_path/'clean.mp4'
    subprocess.run([ffmpeg,'-y','-v','error','-f','lavfi','-i','color=c=0x294c5a:s=108x192:r=30:d=3',
        '-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True)
    page.route('**/clean.mp4',lambda route:route.fulfill(content_type='video/mp4',body=video.read_bytes()))
    png=io.BytesIO();Image.new('RGB',(108,192),'#294c5a').save(png,format='PNG')
    page.route('**/thumbnail-background.png',lambda route:route.fulfill(content_type='image/png',body=png.getvalue()))
    t.update(remotion_editor_supported=True,thumbnail_editor_supported=True,edit_id='thumbnail-edit')
    t['automation']={'protocol':2,'active':False,'stage':'completed'}
    t['edits']=[dict(id='thumbnail-edit',duration=3,script_id='s1',voice_id=None,export_url='/final.mp4',
        clean_preview_url='/clean.mp4',thumbnail_background_url='/thumbnail-background.png',
        plan={'duration':3,'beats':[],'cues':[], 'cover_spec':{'lines':['첫 번째 문구','두 번째 문구']}})]
    original=copy.deepcopy(t['edits'][0]['plan']);calls=[]
    def save(route):
        body=route.request.post_data_json;calls.append(body)
        t['revision']+=1;t['feedback_revision']+=1
        t['feedback']={'base_edit_id':'thumbnail-edit','thumbnail_document':body['document'],'thumbnail_only':True}
        route.fulfill(content_type='application/json',body=json.dumps(t))
    page.route('**/api/studio/done/save-thumbnail',save)
    page.evaluate("localStorage.setItem('studio-edit-mode-done','thumbnail')")
    page.evaluate('refreshStudio()');page.locator('[data-work=done]').click()
    page.locator('#detail-tabs [data-detail-tab=edit]').click()
    expect(page.get_by_role('heading',name='첫 프레임 썸네일',exact=True)).to_be_visible()
    expect(page.locator('.re-canvas img')).to_have_js_property('naturalWidth',108)
    page.get_by_label('썸네일 문구',exact=True).fill('작은 봉투엔 바로 쏙')
    page.get_by_label('썸네일 글자 크기',exact=True).fill('128')
    assert page.locator('[data-thumbnail-element="cover-line-0"]>div').evaluate('(e)=>e.offsetHeight')<=161
    page.get_by_label('썸네일 문구',exact=True).fill('변경한 썸네일')
    page.get_by_label('썸네일 글자 크기',exact=True).fill('140')
    assert page.locator('[data-thumbnail-element="cover-line-0"]>div').evaluate('(e)=>e.offsetHeight')<=176
    page.evaluate('refreshStudio()')
    expect(page.get_by_label('썸네일 문구',exact=True)).to_have_value('변경한 썸네일')
    page.get_by_role('button',name='영상 꾸미기',exact=True).click()
    page.get_by_role('button',name='썸네일 · 첫 프레임',exact=True).click()
    expect(page.get_by_label('썸네일 문구',exact=True)).to_have_value('변경한 썸네일')
    page.locator('#close-work').click();page.locator('[data-work=done]').click()
    page.locator('#detail-tabs [data-detail-tab=edit]').click()
    expect(page.get_by_label('썸네일 문구',exact=True)).to_have_value('변경한 썸네일')
    page.get_by_role('button',name='썸네일 내용 저장',exact=True).click()
    expect(page.locator('.re-thumbnail .re-feedback')).to_contain_text('썸네일 내용을 저장했습니다')
    assert calls[0]['document']['elements'][0]['text']=='변경한 썸네일'
    assert calls[0]['document']['elements'][0]['size']==140
    assert calls[0]['document']['elements'][0]['end']==1/30
    assert t['edits'][0]['plan']==original
    expect(page.locator('#drawer-status')).to_have_text('완성')
    page.set_viewport_size({'width':390,'height':844})
    assert page.locator('#work-drawer').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
    assert page.locator('.re-thumbnail .re-properties').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
    assert page.get_by_role('button',name='썸네일 내용 저장',exact=True).bounding_box()['height']>=44
    t.pop('thumbnail_editor_supported');t['revision']+=1
    page.evaluate('refreshStudio()')
    expect(page.get_by_role('button',name='썸네일 내용 저장',exact=True)).to_be_disabled()
    expect(page.get_by_text('미리보기와 임시 편집을 사용할 수 있습니다.',exact=False)).to_be_visible()
