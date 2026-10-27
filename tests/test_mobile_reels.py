from types import SimpleNamespace
from pathlib import Path
import shutil

import pytest

from hotpost.mobile_device import DeviceConfig, MobileError, focused_package, parse_screen
from hotpost.mobile_reels import ReelJobs, ReelsController, INSTAGRAM, digest


class Preparation:
    def __init__(self, root):
        self.video=root/'old-video.mp4';self.video.write_bytes(b'verified final')
        self.cover=root/'old-cover.png';self.cover.write_bytes(b'selected cover')
        self.caption='청소용품 하나 늘어날 때마다 🧴\n#욕실 #수납 #선반 #살림 #정리'

    def get(self, code):
        return {'revision':7,'draft':{'caption':self.caption,'pinned_comment':'댓글에 나도 💬','product_link':''}}

    def source(self, code):
        return {'media':{'final':self.video,'cover':self.cover},'media_version':'current',
                'cover_text':'사용자가 선택한 문구','spoken_text':'청소용품 하나 늘어날 때마다 자리까지 필요해요.',
                'publication_rules':{'advertising_disclosure':'upper-right-gray-v1','content_opening':'no-interjection-v1'}}


def converter(source, target):
    shutil.copyfile(source,target)
    return {'fixture':True}


def test_screen_fingerprint_ignores_system_renumbering_but_keeps_app_and_overlays():
    from hotpost.mobile_device import screen_fingerprint, stable_screen_nodes
    app={'index':1,'package':INSTAGRAM,'text':'새로운 릴스','bounds':[0,0,100,100]}
    edge={'index':2,'package':'com.sec.android.app.launcher','text':'Edge 패널','bounds':[99,1,100,20]}
    clock={'index':0,'package':'com.android.systemui','text':'12:51','bounds':[0,0,10,10]}
    first=screen_fingerprint(INSTAGRAM,[clock,app,edge])
    assert first==screen_fingerprint(INSTAGRAM,[{**edge,'index':0},{**app,'index':20},{**clock,'text':'12:52'}])
    assert stable_screen_nodes([clock,app,edge])==stable_screen_nodes([edge,app,clock])
    assert stable_screen_nodes([clock,app,edge])[0]['text']=='새로운 릴스'
    assert first!=screen_fingerprint(INSTAGRAM,[{**app,'text':'다른 계정'},edge])
    assert first!=screen_fingerprint(INSTAGRAM,[app,{**edge,'bounds':[1,1,90,90]}])
    assert first!=screen_fingerprint(INSTAGRAM,[app,edge,{'index':3,'package':'permission.dialog','text':'허용'}])


@pytest.fixture
def prepared(tmp_path):
    service=Preparation(tmp_path);jobs=ReelJobs(tmp_path/'jobs')
    job=jobs.prepare(service,'test-post','mr.salrim',converter=converter)
    return service,jobs,job


def test_freezes_current_media_and_caption_and_deduplicates(prepared):
    prep,jobs,job=prepared
    assert jobs.prepare(prep,'test-post','mr.salrim',converter=converter)['id']==job['id']
    prep.video.write_bytes(b'later thumbnail edit')
    prep.caption='later user edit'
    assert jobs.validate(jobs.get(job['id']))['caption']!=prep.caption
    assert (jobs.folder(job['id'])/'final.mp4').read_bytes()==b'verified final'
    assert job['package']['pinned_comment']=='댓글에 나도 💬'


def test_modified_package_media_and_unregistered_account_are_rejected(prepared):
    prep,jobs,job=prepared
    with pytest.raises(MobileError):jobs.prepare(prep,'test-post','another',converter=converter)
    (jobs.folder(job['id'])/'cover.png').write_bytes(b'wrong cover')
    with pytest.raises(MobileError):jobs.validate(jobs.get(job['id']))


def test_littly_rebind_preserves_native_draft_and_rejects_changed_evidence(prepared):
    import json
    from hotpost.mobile_device import atomic_json
    from hotpost.mobile_reels import approval_digest
    prep,jobs,job=prepared
    original=prep.get('test-post')
    original['draft'].update(product_link='https://link.coupang.com/re/AFFSDP?fixture=1',
                             dm_message='fixed DM',dm_button_text='button')
    prep.get=lambda code:original
    folder=jobs.folder(job['id'])
    evidence={}
    for name,value in [('system-verified.json',{'one_link':original['draft']['product_link'],'landing_verified':True}),
                       ('littly-after-update.json',{'saved':True})]:
        path=folder/name;atomic_json(path,value)
        evidence[name]={'path':str(path),'sha256':digest(path)}
    receipt={'account':'mr.salrim','shortcode':'test-post','job':job['id'],
             'input_package_sha256':job['package_sha256'],'draft_revision':7,
             'affiliate_url':original['draft']['product_link'],'post_mode':'next_post',
             'comment_condition':'all','saved_verified':True,'one_link_format_verified':True,
             'dm_message':'fixed DM','button_text':'button','evidence':evidence}
    path=folder/'receipt.json';atomic_json(path,receipt)
    jobs.update(job['id'],'ready',upstream_hold={'reason':'Littly first'},approval_sha256='old',
                native_draft_resume={'id':'1027'},edits_audio_volume_percent=70)
    original['draft']['caption']='changed'
    with pytest.raises(MobileError):jobs.bind_littly(job['id'],prep,path)
    assert jobs.get(job['id'])['upstream_hold']
    original['draft']['caption']=job['package']['caption']
    state=jobs.bind_littly(job['id'],prep,path)
    assert state['package']==job['package'] and state['package_sha256']==job['package_sha256']
    assert state['native_draft_resume']=={'id':'1027'} and state['edits_audio_volume_percent']==70
    assert state['upstream_hold'] is None and state['approval_sha256'] is None
    assert approval_digest(state,'screen')!=job['package_sha256']
    jobs.validate(ReelJobs(jobs.root).get(job['id']))
    path.write_text(json.dumps({**receipt,'affiliate_url':'changed'}),'utf8')
    with pytest.raises(MobileError):jobs.validate(jobs.get(job['id']))


def test_installation_publication_account_is_accepted_without_personal_defaults(tmp_path):
    prep=Preparation(tmp_path)
    prep.accounts=lambda:['my.brand']
    jobs=ReelJobs(tmp_path/'jobs')
    assert jobs.prepare(prep,'test-post','my.brand',converter=converter)['package']['account']=='my.brand'
    with pytest.raises(MobileError):
        jobs.prepare(prep,'test-post','mr.salrim',converter=converter)


@pytest.mark.parametrize('account,message', [('my.brand','현재 완성 영상과 표지'),
                                            ('unregistered','등록된 업로드 계정')])
def test_cli_uses_registered_accounts_instead_of_fixed_personal_choices(tmp_path,monkeypatch,account,message):
    import sys
    from hotpost import mobile_reels_cli as cli
    from hotpost.installation_settings import save
    save(tmp_path,{'revision':0,'values':{'publication_accounts':['my.brand'],'discovery_account':'reader',
         'storefront_url':'https://influencers.coupang.com/s/test','collection':'Test'}})
    DeviceConfig('10.9.0.2',40001,android_serial='fixture').save(tmp_path/'.mobile-device.json')
    monkeypatch.setattr(cli,'load_settings',lambda:SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(sys,'argv',['mobile_reels_cli','prepare','video','--account',account])
    # A registered account reaches the next real prerequisite; an unregistered one stops at identity validation.
    with pytest.raises(MobileError,match=message):cli.main()


@pytest.mark.parametrize('ip,port,network', [('8.8.8.8',5555,'0.0.0.0/0'),('127.0.0.1',5555,'127.0.0.0/8'),
    ('10.8.0.2',5555,'10.9.0.0/24'),('10.9.0.2',0,'10.9.0.0/24'),('10.9.0.2;bad',5555,'10.9.0.0/24')])
def test_only_explicit_private_vpn_endpoint_is_accepted(ip,port,network):
    with pytest.raises(MobileError):DeviceConfig(ip,port,network).validate()


def test_profile_screen_and_unicode_input_and_exact_share_are_checked(prepared):
    prep,jobs,job=prepared
    ui=FakeUI(job['package']['caption'])
    adb=FakeAdb()
    c=ReelsController(jobs,adb,ui)
    c.transfer(job['id'])
    assert adb.pushed==['final.mp4','cover.png']
    ui.profile()
    c.open(job['id'],via='instagram')
    assert adb.opened[0][1]==INSTAGRAM
    ui.composer('')
    c.fill_caption(job['id'])
    assert ui.text==prep.caption
    with pytest.raises(MobileError):c.ready(job['id'])
    c.review_cover(job['id'],ui.screen()['sha256'],job['package']['media']['cover']['sha256'])
    ready=c.ready(job['id']);assert ready['phase']=='ready'
    with pytest.raises(MobileError):c.publish(job['id'],'wrong-sha')
    ui.failure=True
    with pytest.raises(ConnectionError):c.publish(job['id'],job['package_sha256'])
    assert jobs.get(job['id'])['phase']=='unknown'
    with pytest.raises(MobileError):c.publish(job['id'],job['package_sha256'])
    assert ui.shares==1
    # Persisted across a new process/service instance, not merely an in-memory flag.
    after=ReelJobs(jobs.root)
    assert after.get(job['id'])['phase']=='unknown'
    with pytest.raises(MobileError):after.cancel(job['id'])
    ui.ack=True
    assert c.reconcile(job['id'])['phase']=='submitted'
    assert c.reconcile(job['id'])['media_verified'] is False


def test_wrong_account_story_duplicate_share_and_stale_screen_stop(prepared):
    _,jobs,job=prepared;c=ReelsController(jobs,FakeAdb(),FakeUI(job['package']['caption']))
    c.transfer(job['id']);c.ui.profile('someone_else')
    with pytest.raises(MobileError):c.open(job['id'])
    c.ui.composer(job['package']['caption'],title='New story')
    jobs.update(job['id'],'composer')
    with pytest.raises(MobileError):c.ready(job['id'])
    c.ui.composer(job['package']['caption'])
    c.ui.nodes.append(node('Share','share2',index=4))
    with pytest.raises(MobileError):c.ready(job['id'])
    with pytest.raises(MobileError):c.navigate(job['id'],1,'stale-sha')
    c.ui.composer(job['package']['caption'])
    with pytest.raises(MobileError):c.navigate(job['id'],3,c.ui.screen()['sha256'])
    assert c.ui.shares==0


def test_another_phone_or_another_job_cannot_replace_the_active_composer(prepared):
    prep,jobs,first=prepared;c=ReelsController(jobs,FakeAdb(),FakeUI(''))
    c.transfer(first['id'])
    second=jobs.prepare(prep,'another-post','__ariddaum__',converter=converter)
    with pytest.raises(MobileError):c.transfer(second['id'])
    jobs.cancel(first['id']);c.transfer(second['id'])
    c.adb.config.android_serial='different-phone'
    with pytest.raises(MobileError):c.state(second['id'])


def test_submit_claim_is_committed_before_click_and_cannot_be_repeated(prepared):
    _,jobs,job=prepared
    jobs.update(job['id'],'ready')
    jobs.claim_submit(job['id'],job['package_sha256'])
    assert ReelJobs(jobs.root).get(job['id'])['phase']=='submitting'
    with pytest.raises(MobileError):jobs.claim_submit(job['id'],job['package_sha256'])


def test_upstream_littly_hold_survives_restart_and_preserves_existing_draft(prepared):
    _,jobs,job=prepared
    ui=FakeUI(job['package']['caption']);ui.composer(ui.text)
    hold={'stage':'littly','reason':'리틀리 저장 확인 전 모바일 진행 보류'}
    jobs.update(job['id'],'ready',upstream_hold=hold,native_draft_resume={'title':'1027'},
                edits_audio_volume_percent=70,approval_sha256=None)
    reopened=ReelJobs(jobs.root);c=ReelsController(reopened,FakeAdb(),ui)
    with pytest.raises(MobileError,match='리틀리'):c.fill_caption(job['id'])
    with pytest.raises(MobileError,match='리틀리'):c.publish(job['id'],job['package_sha256'])
    # The final transaction also blocks callers bypassing controller navigation.
    with pytest.raises(MobileError,match='리틀리'):reopened.claim_submit(job['id'],job['package_sha256'])
    saved=reopened.get(job['id'])
    assert saved['package']==job['package'] and saved['native_draft_resume']=={'title':'1027'}
    assert saved['edits_audio_volume_percent']==70 and 'share_attempted_at' not in saved
    assert c.inspect(job['id'])['sha256']=='screen-hash' and ui.shares==0


def test_xml_nodes_are_observed_not_guessed():
    xml='<hierarchy><node text="다음" bounds="[0,0][100,40]" resource-id="next"/>'\
        '<node text="invisible" bounds="[0,0][0,0]"/></hierarchy>'
    assert parse_screen(xml)[0]['text']=='다음'
    assert len(parse_screen(xml))==1


def test_focused_package_uses_system_focus_not_a_background_app():
    # Samsung Android 17: a background YouTube window is listed first, Instagram has focus.
    dumpsys=('  Window #25 Window{28001ff u0 com.google.android.youtube/com.google.android.youtube.app.honeycomb.Shell$HomeActivity}:\n'
             '  mCurrentFocus=Window{4086bcb u0 com.instagram.android/com.instagram.mainactivity.InstagramMainActivity}\n'
             '  mFocusedApp=ActivityRecord{179838198 u0 com.instagram.android/com.instagram.mainactivity.InstagramMainActivity t13682}\n')
    assert focused_package(dumpsys)==INSTAGRAM
    popup=('  mCurrentFocus=Window{9a1 u0 PopupWindow:e5f1e2}\n'
           '  mFocusedApp=ActivityRecord{77 u0 com.instagram.basel/.MainActivity t9}\n')
    assert focused_package(popup)=='com.instagram.basel'
    with pytest.raises(MobileError):focused_package('  mCurrentFocus=null\n  mFocusedApp=null\n')


def test_reconnect_keeps_registered_phone_and_new_ip_finds_wireguard_network():
    from hotpost.mobile_reels_cli import reconfigure
    saved=DeviceConfig('10.9.0.50',41387,'10.9.0.0/24','R5KL3039BZY')
    moved=reconfigure(saved,None,40001,None,[])
    assert (moved.phone_ip,moved.adb_port,moved.android_serial)==('10.9.0.50',40001,'R5KL3039BZY')
    adapters=[{'InterfaceAlias':'wg','IPAddress':'10.7.0.24','PrefixLength':24}]
    fresh=reconfigure(saved,'10.7.0.31',38000,None,adapters)
    assert (fresh.vpn_network,fresh.android_serial)==('10.7.0.0/24','')
    with pytest.raises(MobileError):reconfigure(saved,'192.168.0.9',38000,None,adapters)
    with pytest.raises(MobileError):reconfigure(DeviceConfig(),None,38000,None,[])


def test_adb_targets_only_the_configured_phone_and_pair_code_is_stdin(monkeypatch):
    from hotpost import mobile_device as mobile
    config=DeviceConfig('10.9.0.7',39211,android_serial='phone-one')
    adb=mobile.AdbDevice(config,executable='adb-fixture')
    calls=[]
    def execute(args,**kwargs):
        calls.append((args,kwargs))
        if 'pair' in args:return b'Successfully paired'
        if 'connect' in args:return b'connected to 10.9.0.7:39211'
        if 'get-state' in args:return b'device\n'
        if 'ro.serialno' in args:return b'phone-one\n'
        if 'ro.build.version.release' in args:return b'15\n'
        if 'sha256sum' in args:return b'abc  final.mp4\n'
        return b''
    monkeypatch.setattr(mobile,'run',execute)
    monkeypatch.setattr(adb,'preflight',lambda:{'InterfaceDescription':'WireGuard Tunnel'})
    monkeypatch.setattr(adb,'preflight_pair',lambda port:None)
    assert adb.connect()['android_serial']=='phone-one'
    assert adb.pair(12345,'654321')['paired']
    assert all('654321' not in str(args) for args,_ in calls)
    assert calls[-1][1]['input']==b'654321\n'
    assert all(args[1:3]==['-s',config.endpoint] for args,_ in calls if 'shell' in args or 'get-state' in args)
    with pytest.raises(MobileError):adb.push(Path('video.mp4'),'/sdcard/Movies/not-our-folder.mp4','abc')


def test_media_uri_uses_canonical_path_and_rejects_another_location(monkeypatch):
    from hotpost.mobile_device import AdbDevice
    adb = AdbDevice(DeviceConfig('10.9.0.7',39211), executable='fixture')
    remote = '/sdcard/Movies/Hotpost/' + 'a'*32 + '/final.mp4'
    canonical = remote.replace('/sdcard', '/storage/emulated/0', 1)
    calls = []
    def command(*args):
        calls.append(args)
        return canonical.encode() if 'readlink' in args else b'Row: 0 _id=50523\n'
    monkeypatch.setattr(adb, 'command', command)
    assert adb.video_uri(remote) == 'content://media/external/video/media/50523'
    assert canonical in calls[-1][-1]
    monkeypatch.setattr(adb, 'command', lambda *args: b'/storage/emulated/0/Movies/other.mp4')
    with pytest.raises(MobileError, match='실제 저장 경로'):
        adb.video_uri(remote)


def test_manual_unknown_result_never_reclicks_share_or_accepts_the_reference_url(prepared):
    _,jobs,job=prepared
    jobs.update(job['id'],'unknown')
    c=ReelsController(jobs,FakeAdb(),FakeUI(''))
    with pytest.raises(MobileError):c.confirm_result(job['id'],'https://www.instagram.com/reel/test-post/','screen-hash')
    result=c.confirm_result(job['id'],'https://www.instagram.com/reel/OurUploadedReel/','screen-hash')
    assert result['operator_confirmed'] and not result['media_verified']
    assert c.ui.shares==0


def test_three_phone_configs_preserve_primary_and_reject_aliases(tmp_path):
    from hotpost.mobile_device import DeviceRegistry, phone_lock
    registry=DeviceRegistry(tmp_path)
    for i,name in enumerate(('primary','phone2','phone3'),1):
        registry.save(name,DeviceConfig(f'10.9.0.{50+i}',41000+i,android_serial=f'phone-{i}'))
    before=registry.path('primary').read_bytes()
    registry.save('phone2',DeviceConfig('10.9.0.52',42002,android_serial='phone-2'))
    assert registry.path('primary').read_bytes()==before
    assert [d['device_id'] for d in registry.devices()]==['phone2','phone3','primary']
    with pytest.raises(MobileError):registry.save('duplicate',DeviceConfig('10.9.0.52',43000))
    with pytest.raises(MobileError):registry.save('duplicate',DeviceConfig('10.9.0.60',43000,android_serial='phone-3'))
    for unsafe in ('../escape','CON','phone/2',''):
        with pytest.raises(MobileError):registry.path(unsafe)
    with phone_lock(registry.lock_folder('phone2')):
        with phone_lock(registry.lock_folder('phone3')):
            with pytest.raises(MobileError):
                with phone_lock(registry.lock_folder('phone2')):pass


def test_three_jobs_are_phone_bound_and_share_claims_are_global(prepared):
    prep,jobs,primary=prepared
    second=jobs.prepare(prep,'test-post','mr.salrim',converter=converter,device_id='phone2')
    third=jobs.prepare(prep,'test-post','__ariddaum__',converter=converter,device_id='phone3')
    for name,job in (('primary',primary),('phone2',second),('phone3',third)):
        adb=FakeAdb();adb.config.android_serial=name
        c=ReelsController(jobs,adb,FakeUI(''),device_id=name)
        c.transfer(job['id'])
        assert jobs.get(job['id'])['device_serial']==name
        if name!='primary':
            with pytest.raises(MobileError):c.state(primary['id'])
        jobs.update(job['id'],'ready')
    another=jobs.prepare(prep,'another-video','mr.salrim',converter=converter,device_id='phone2')
    with pytest.raises(MobileError):jobs.own_phone(another['id'])
    jobs.claim_submit(primary['id'],primary['package_sha256'])
    # Another phone, same account+video: no second attempt even after reopening the DB.
    with pytest.raises(MobileError,match='다른 폰'):
        ReelJobs(jobs.root).claim_submit(second['id'],second['package_sha256'])
    jobs.claim_submit(third['id'],third['package_sha256'])
    wrong=ReelsController(jobs,FakeAdb(),FakeUI(''),device_id='phone2')
    with pytest.raises(MobileError):wrong.reconcile(primary['id'])


def test_caption_raw_unicode_check_does_not_trust_sanitized_xml(prepared):
    prep,jobs,job=prepared
    ui=FakeUI(job['package']['caption']);ui.composer(ui.text)
    ui.nodes[2]['class']='android.widget.AutoCompleteTextView'
    ui.nodes[2]['text']=ui.text.replace('🧴','..')
    c=ReelsController(jobs,FakeAdb(),ui)
    c.ready_screen(job)
    ui.text='different live text'
    with pytest.raises(MobileError,match='본문'):c.ready_screen(job)


def test_default_open_starts_edits_after_verifying_instagram_account(prepared):
    from hotpost.mobile_reels import EDITS
    _,jobs,job=prepared;ui=FakeUI('');adb=FakeAdb();c=ReelsController(jobs,adb,ui)
    c.transfer(job['id']);ui.profile()
    ui.open_app=lambda package:setattr(ui,'package',package)
    c.open(job['id'])
    assert ui.package==EDITS and not adb.opened
    assert jobs.get(job['id'])['via']=='edits'


def test_edits_album_music_volume_and_recipe_are_bound(prepared):
    from hotpost.mobile_reels import EDITS, edits_audio_catalog_sha
    _,jobs,job=prepared;ui=FakeUI('');c=ReelsController(jobs,FakeAdb(),ui)
    c.transfer(job['id']);jobs.update(job['id'],'composer',via='edits',requested_music_volume_percent=70)
    ui.package=EDITS
    album=node(job['id'],'album')
    video=node('','',1);video.update(resource_id=EDITS+':id/gallery_picker_grid_item_container',description='동영상 썸네일')
    ui.nodes=[album,video]
    c.select_edits_video(job['id'],'screen-hash')
    album['text']='another album'
    with pytest.raises(MobileError):c.select_edits_video(job['id'],'screen-hash')
    track=node('','',2);track.update(resource_id='audio_browser_preview_track_0_123_TRACK_123',description='Artist님의 Soft Bounce 트랙 선택')
    search=node('검색...','row_search_edit_text',3);search['resource_id']=EDITS+':id/row_search_edit_text'
    ui.nodes=[track,search];catalog=edits_audio_catalog_sha(ui.screen())
    # A background playback clock/index change cannot change the selected track identity.
    ui.nodes.append(node('00:02','play_time_stamp',4));track['index']=8
    c.select_edits_audio(job['id'],track['resource_id'],catalog)
    track['description']='a different track'
    with pytest.raises(MobileError):c.select_edits_audio(job['id'],track['resource_id'],catalog)
    jobs.update(job['id'],'composer',edits_audio_applied=True)
    music=node('Soft Bounce','music');music['description']='오디오 트랙 \n Soft Bounce'
    slider=node('73.0','slider',1);slider['resource_id']='volume_slider'
    ui.nodes=[music,slider]
    with pytest.raises(MobileError):c.record_edits_volume(job['id'],70,'screen-hash')
    slider['text']='70.0';c.record_edits_volume(job['id'],70,'screen-hash')
    ui.package=INSTAGRAM;ui.composer(job['package']['caption'])
    jobs.update(job['id'],'composer',edits_handoff_at=1)
    c.review_cover(job['id'],'screen-hash',job['package']['media']['cover']['sha256'])
    ready=c.ready(job['id'])
    assert ready['approval_sha256']!=job['package_sha256']
    jobs.update(job['id'],'ready',edits_audio_volume_percent=30)
    with pytest.raises(MobileError):c.publish(job['id'],ready['approval_sha256'])
    assert ui.shares==0


def test_handoff_account_proof_is_not_a_caption_mention_or_an_old_session(prepared):
    import json
    _,jobs,job=prepared;ui=FakeUI('');c=ReelsController(jobs,FakeAdb(),ui)
    jobs.update(job['id'],'composer',via='edits',edits_handoff_at=1,profile_check={'account':'mr.salrim'})
    folder=jobs.folder(job['id']);path=folder/'handoff.json';path.with_suffix('.png').write_bytes(b'captured screen')
    notice=node('mr.salrim님으로 로그인함','snackbar_message')
    title=node('새로운 릴스','action_bar_title',1)
    path.write_text(json.dumps({'package':INSTAGRAM,'nodes':[notice,title]}),encoding='utf8')
    recorded=c.record_handoff_account(job['id'],'handoff');c.validate_handoff_account(recorded)
    jobs.update(job['id'],'composer',edits_handoff_at=2)
    with pytest.raises(MobileError):c.validate_handoff_account(jobs.get(job['id']))
    notice['resource_id']=INSTAGRAM+':id/caption_input_text_view'
    path.write_text(json.dumps({'package':INSTAGRAM,'nodes':[notice,title]}),encoding='utf8')
    with pytest.raises(MobileError):c.record_handoff_account(job['id'],'handoff')


def node(text, rid, index=0, cls='android.widget.TextView'):
    return dict(index=index,text=text,description='',resource_id=INSTAGRAM+':id/'+rid,
                bounds=[0,index*50,100,(index+1)*50],package=INSTAGRAM,**{'class':cls})


class FakeUI:
    def __init__(self,text):
        self.nodes=[];self.text=text;self.shares=0;self.failure=False;self.ack=False;self.package=INSTAGRAM
    def profile(self,account='mr.salrim'):
        self.nodes=[node(account,'action_bar_title'),node('Edit profile','edit_profile',1)]
    def composer(self,text,title='New reel'):
        self.text=text
        self.nodes=[node(title,'title',0),node('mr.salrim','account_username',1),
                    node(text,'caption_text_view',2,'android.widget.EditText'),node('Share','share',3)]
    def screen(self):
        nodes=[node('Your reel has been shared','ack')] if self.ack else self.nodes
        return {'package':self.package,'sha256':'screen-hash','nodes':nodes,'xml':'<hierarchy/>'}
    def capture(self,*args):return self.screen()
    def tap(self,n):
        if n['text']=='Share':
            self.shares+=1
            if self.failure:raise ConnectionError('after share')
    def set_text(self,n,text):
        self.composer(text)
    def get_text(self,n):
        return self.text


class FakeAdb:
    def __init__(self):
        self.config=SimpleNamespace(android_serial='phone-one')
        self.pushed=[];self.opened=[]
    def push(self,local,remote,sha):
        assert digest(local)==sha
        self.pushed.append(Path(local).name)
    def video_uri(self,remote):return 'content://media/external/video/media/123'
    def open_video(self,uri,package):self.opened.append((uri,package))
