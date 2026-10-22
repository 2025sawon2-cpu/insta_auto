"""Exercise the observed reel dialog and input against an intercepted local page."""
import pytest

from test_instagram_publish import local_composer
from hotpost.monetization_browser import own_comment_ids, comment_input


@pytest.mark.parametrize('post_button',[False,True])
def test_current_reel_opens_only_onscreen_comments_and_submits_once(tmp_path,local_composer,post_button):
    adapter,page=local_composer
    html='''<aside><a href="/ggul_dol2/">프로필</a></aside>
    <a href="/source/reels/">source</a>
    <div role="button" onclick="document.querySelector('[role=dialog]').hidden=false"><svg role="img" aria-label="댓글"></svg></div>
    <div role="button" style="position:absolute;top:5000px" onclick="window.wrongClip=true"><svg role="img" aria-label="댓글"></svg></div>
    <div role="dialog" hidden><input placeholder="댓글 달기..."><div id="comments"></div></div><div role="grid"></div>
    <script>function submitComment(){window.postCount=(window.postCount||0)+1;const row=document.createElement('div');
    row.innerHTML='<a href="/ggul_dol2/">ggul_dol2</a><span>나도</span><a href="/p/Reference/c/123/">방금</a>';
    document.querySelector('#comments').append(row);const box=document.querySelector('[role=dialog] input,[role=dialog] [role=textbox]');
    if(box.tagName==='INPUT')box.value='';else box.textContent='';}
    document.querySelector('input').addEventListener('keydown',e=>{if(e.key==='Enter')submitComment()});</script>'''
    if post_button:
        html += '<script>document.querySelector("[role=dialog]").insertAdjacentHTML("beforeend",\'<button onclick="submitComment()">게시</button>\')</script>'
        html += '''<script>document.querySelector('input').addEventListener('input',e=>{
        const div=document.createElement('div');div.setAttribute('role','textbox');div.setAttribute('aria-label','댓글 달기...');
        div.contentEditable='true';div.textContent=e.target.value;e.target.replaceWith(div);});</script>'''
    page.route('https://www.instagram.com/**',lambda route:route.fulfill(body=html,content_type='text/html; charset=utf-8'))
    adapter._author=lambda *_:('source','확인할 상품')
    thread_calls=[]
    def thread(*args,**kwargs):
        thread_calls.append(True)
        return None if len(thread_calls)==1 else page.get_by_role('grid')
    adapter._thread=thread
    adapter._message_links=lambda *_:[{'stable_id':'new','digest':'new','message_id':'dm',
        'date':'2099-01-01T00:00:00Z','links':['https://www.coupang.com/vp/products/1']}]
    adapter._read_product=lambda *_:{'product_name':'상품','product_verified':True}
    result=adapter.discover_product({'shortcode':'Reference','account':'ggul_dol2'},'원작키워드',tmp_path/'ui')
    assert page.evaluate('window.postCount')==1
    assert page.evaluate('window.wrongClip') is None
    assert result['comment_id']=='/p/Reference/c/123/'
    assert comment_input(page.get_by_role('dialog')).evaluate('n=>n.value ?? n.textContent')==''


def test_permalink_ack_cannot_mix_another_users_comment_with_our_profile(local_composer):
    _,page=local_composer
    page.set_content('''<div id="root"><div><a href="/ggul_dol2/">나</a><span>예전 댓글</span><a href="/p/Reference/c/1/">이전</a></div>
    <div><a href="/other/">다른 계정</a><span>나도</span><a href="/p/Reference/c/2/">새 댓글</a></div>
    <div><a href="/ggul_dol2/">나</a><span>나도</span><a href="/p/Other/c/3/">다른 게시물</a></div></div>''')
    assert own_comment_ids(page.locator('#root'),'ggul_dol2','Reference','나도')==set()


def test_wrong_reference_url_never_opens_comment_panel(tmp_path,local_composer):
    adapter,page=local_composer
    with pytest.raises(ValueError,match='주소가 작업과 다릅니다'):
        adapter.reference_comment_surface(page,'source','Reference',tmp_path/'ui')
