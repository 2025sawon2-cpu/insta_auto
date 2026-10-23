from types import SimpleNamespace
from pathlib import Path
import shutil

import pytest

from hotpost.mobile_device import DeviceConfig, MobileError, parse_screen
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
    c.open(job['id'])
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


def test_xml_nodes_are_observed_not_guessed():
    xml='<hierarchy><node text="다음" bounds="[0,0][100,40]" resource-id="next"/>'\
        '<node text="invisible" bounds="[0,0][0,0]"/></hierarchy>'
    assert parse_screen(xml)[0]['text']=='다음'
    assert len(parse_screen(xml))==1


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


def test_manual_unknown_result_never_reclicks_share_or_accepts_the_reference_url(prepared):
    _,jobs,job=prepared
    jobs.update(job['id'],'unknown')
    c=ReelsController(jobs,FakeAdb(),FakeUI(''))
    with pytest.raises(MobileError):c.confirm_result(job['id'],'https://www.instagram.com/reel/test-post/','screen-hash')
    result=c.confirm_result(job['id'],'https://www.instagram.com/reel/OurUploadedReel/','screen-hash')
    assert result['operator_confirmed'] and not result['media_verified']
    assert c.ui.shares==0


def node(text, rid, index=0, cls='android.widget.TextView'):
    return dict(index=index,text=text,description='',resource_id=INSTAGRAM+':id/'+rid,
                bounds=[0,index*50,100,(index+1)*50],package=INSTAGRAM,**{'class':cls})


class FakeUI:
    def __init__(self,text):
        self.nodes=[];self.text=text;self.shares=0;self.failure=False;self.ack=False
    def profile(self,account='mr.salrim'):
        self.nodes=[node(account,'action_bar_title'),node('Edit profile','edit_profile',1)]
    def composer(self,text,title='New reel'):
        self.text=text
        self.nodes=[node(title,'title',0),node('mr.salrim','account_username',1),
                    node(text,'caption_text_view',2,'android.widget.EditText'),node('Share','share',3)]
    def screen(self):
        nodes=[node('Your reel has been shared','ack')] if self.ack else self.nodes
        return {'package':INSTAGRAM,'sha256':'screen-hash','nodes':nodes,'xml':'<hierarchy/>'}
    def capture(self,*args):return self.screen()
    def tap(self,n):
        if n['text']=='Share':
            self.shares+=1
            if self.failure:raise ConnectionError('after share')
    def set_text(self,n,text):
        self.composer(text)


class FakeAdb:
    def __init__(self):
        self.config=SimpleNamespace(android_serial='phone-one')
        self.pushed=[];self.opened=[]
    def push(self,local,remote,sha):
        assert digest(local)==sha
        self.pushed.append(Path(local).name)
    def video_uri(self,remote):return 'content://media/external/video/media/123'
    def open_video(self,uri,package):self.opened.append((uri,package))
