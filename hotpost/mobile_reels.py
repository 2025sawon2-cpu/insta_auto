"""Durable, explicit mobile reel jobs; no Studio runner or background publisher."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import time
import uuid

from .mobile_device import MobileError, atomic_json, phone_lock
from .post_media_rules import DISCLOSURE_VERSION, require_content_opening
from .post_preparation import ACCOUNTS
from .post_thumbnail import encode_delivery

INSTAGRAM = 'com.instagram.android'
EDITS = 'com.instagram.basel'
FINAL_LABELS = {'공유','공유하기','게시','게시하기','Share','Publish','Post','Share reel'}
NAV_LABELS = {'다음','Next','릴스','릴','Reel','Reels','동영상','Video','확인','OK','완료','Done',
              '프로필','Profile','표지 편집','Edit cover','새 프로젝트','New project','추가','Add','계속','Continue',
              '카메라 롤에서 추가','Add from camera roll','표지','Cover'}
EDITS_HANDOFF = {'Instagram에 공유','인스타그램에 공유','Share to Instagram','내보내기','Export'}
PROFILE_TITLES = ('action_bar_title','profile_header_username','row_profile_header_username')
CAPTION_IDS = ('caption','creation_text','write_a_caption')
ACKNOWLEDGEMENTS = ('릴스가 공유되었습니다','게시물이 공유되었습니다','Your reel has been shared',
                    'Your post has been shared','Reel shared')
UNSAFE_PHASES = ('submitting','unknown','submitted')


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            result.update(chunk)
    return result.hexdigest()


def package_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':')).encode()).hexdigest()


def phone_video(source, output):
    """Use the same verified Main/4.0 delivery contract as publication downloads."""
    checks = encode_delivery(source, output)
    return {'video_codec':checks['codec'],'profile':checks['profile'],'pix_fmt':checks['pix_fmt'],
            'duration':checks['duration'],'source_sha256':digest(source),'sha256':digest(output),
            'delivery':checks}


class ReelJobs:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root/'jobs.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE, phase TEXT, value TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS phone_owner(slot INTEGER PRIMARY KEY, job TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        with sqlite3.connect(self.path, timeout=10) as db:
            db.row_factory = sqlite3.Row
            yield db

    def folder(self, job):
        if not re.fullmatch('[a-f0-9]{32}', job):
            raise MobileError('올바른 모바일 작업 ID가 필요합니다.')
        return self.root/job

    def get(self, job):
        self.folder(job)
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
        if not row:
            raise MobileError('모바일 게시 작업을 찾을 수 없습니다.')
        return {'id':row['id'],'phase':row['phase'],**json.loads(row['value'])}

    def update(self, job, phase, **changes):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT value FROM jobs WHERE id=?',(job,)).fetchone()
            if not row:
                raise MobileError('모바일 작업이 없습니다.')
            value = {**json.loads(row[0]),**changes,'updated':time.time()}
            db.execute('UPDATE jobs SET phase=?,value=? WHERE id=?',(phase,json.dumps(value,ensure_ascii=False),job))
        return self.get(job)

    def prepare(self, preparations, code, account, converter=phone_video):
        account = account.removeprefix('@')
        if account not in ACCOUNTS:
            raise MobileError('등록된 업로드 계정을 선택하세요.')
        state = preparations.get(code)
        source = preparations.source(code)
        if not source['media'].get('final') or not source['media'].get('cover'):
            raise MobileError('현재 완성 영상과 표지가 필요합니다.')
        rules = source.get('publication_rules',{})
        if rules.get('advertising_disclosure')!=DISCLOSURE_VERSION:
            raise MobileError('현재 영상에 우상단 [광고]를 먼저 적용하세요.')
        require_content_opening(source.get('spoken_text',''))
        if not state['draft']['caption'].strip():
            raise MobileError('게시물 본문을 먼저 작성하세요.')
        payload = {'contract':'mobile-reels-v1','shortcode':code,'account':account,'draft_revision':state['revision'],
                   'source_version':source.get('media_version'),'source_video_sha256':digest(source['media']['final']),
                   'source_cover_sha256':digest(source['media']['cover']), 'rules':rules,
                   'caption':state['draft']['caption'],'pinned_comment':state['draft']['pinned_comment'],
                   'product_link':state['draft']['product_link'],
                   'thumbnail_text':source['cover_text']}
        fingerprint = package_digest(payload)
        with phone_lock(self.root):
            with self.connect() as db:
                prior = db.execute('SELECT id FROM jobs WHERE fingerprint=?',(fingerprint,)).fetchone()
            if prior:
                return self.get(prior[0])
            job = uuid.uuid4().hex
            folder = self.folder(job)
            folder.mkdir()
            # Freeze source bytes before encoding; later thumbnail changes cannot replace them.
            source_copy = folder/'source.mp4'
            shutil.copyfile(source['media']['final'], source_copy)
            shutil.copyfile(source['media']['cover'], folder/'cover.png')
            if digest(source_copy)!=payload['source_video_sha256'] or digest(folder/'cover.png')!=payload['source_cover_sha256']:
                raise MobileError('게시 준비 중 원본 영상이나 표지가 바뀌었습니다.')
            conversion = converter(source_copy, folder/'final.mp4')
            payload['media'] = {'video':{'name':'final.mp4','sha256':digest(folder/'final.mp4')},
                                'cover':{'name':'cover.png','sha256':digest(folder/'cover.png')}}
            payload['conversion'] = conversion
            value = {'package':payload,'package_sha256':package_digest(payload),'created':time.time()}
            atomic_json(folder/'package.json',value)
            (folder/'caption.txt').write_text(payload['caption'],'utf8')
            (folder/'pinned-comment.txt').write_text(payload['pinned_comment'],'utf8')
            with self.connect() as db:
                db.execute('INSERT INTO jobs VALUES (?,?,?,?)',(job,fingerprint,'prepared',json.dumps(value,ensure_ascii=False)))
            return self.get(job)

    def validate(self, state):
        payload = state['package']
        if package_digest(payload)!=state['package_sha256']:
            raise MobileError('게시 패키지가 변경됐습니다.')
        folder = self.folder(state['id'])
        for key, name in (('video','final.mp4'),('cover','cover.png')):
            row = payload['media'][key]
            if row['name']!=name or not (folder/name).is_file() or digest(folder/name)!=row['sha256']:
                raise MobileError('준비된 영상·표지가 변경됐습니다.')
        return payload

    def claim_submit(self, job, expected_sha):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
            if not row or row['phase']!='ready':
                raise MobileError('게시 직전 검토된 작업만 한 번 공유할 수 있습니다.')
            value = json.loads(row['value'])
            if expected_sha!=value['package_sha256']:
                raise MobileError('승인한 게시 패키지가 다릅니다.')
            value['share_attempted_at'] = time.time()
            db.execute('UPDATE jobs SET phase=?,value=? WHERE id=?',('submitting',json.dumps(value,ensure_ascii=False),job))

    def own_phone(self, job):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            owner = db.execute('SELECT job FROM phone_owner WHERE slot=1').fetchone()
            if owner and owner[0]!=job:
                raise MobileError('다른 영상의 폰 작업이 아직 끝나지 않았습니다. 기존 작업을 완료/게시 전 취소한 뒤 진행하세요.')
            db.execute('INSERT OR IGNORE INTO phone_owner VALUES (1,?)',(job,))

    def release_phone(self, job):
        with self.connect() as db:
            db.execute('DELETE FROM phone_owner WHERE slot=1 AND job=?',(job,))

    def cancel(self, job):
        state = self.get(job)
        if state['phase'] in UNSAFE_PHASES:
            raise MobileError('공유 이후 작업은 취소로 재게시 잠금을 해제할 수 없습니다. 결과를 확인하세요.')
        result = self.update(job,'cancelled')
        self.release_phone(job)
        return result


def node_label(node):
    return node.get('text') or node.get('description') or ''


def unique(nodes, predicate, reason):
    matches = [n for n in nodes if predicate(n)]
    if len(matches)!=1:
        raise MobileError(reason)
    return matches[0]


def check_screen(screen, *, edits=False):
    if screen['package'] not in ((INSTAGRAM,EDITS) if edits else (INSTAGRAM,)):
        raise MobileError('휴대폰에서 Instagram/Edits 화면을 먼저 확인하세요. 잠금·권한·로그인은 직접 확인이 필요합니다.')
    labels = '\n'.join(node_label(n) for n in screen['nodes'])
    if any(text in labels for text in ('비밀번호','인증 코드','보안 코드','사람인지','CAPTCHA','Enter security code','Password')):
        raise MobileError('로그인 또는 인증 화면입니다. 자동 진행하지 않습니다.')


class ReelsController:
    def __init__(self, jobs, adb, ui):
        self.jobs,self.adb,self.ui = jobs,adb,ui

    def state(self, job):
        state = self.jobs.get(job)
        self.jobs.validate(state)
        if state['phase'] in UNSAFE_PHASES or state['phase']=='cancelled':
            raise MobileError('이미 공유를 시도한 작업입니다. 재게시하지 말고 결과를 확인하세요.')
        if state.get('device_serial') and state['device_serial']!=self.adb.config.android_serial:
            raise MobileError('작업을 시작했던 휴대폰과 현재 연결이 다릅니다.')
        self.jobs.own_phone(job)
        return state

    def inspect(self, job):
        return self.ui.capture(self.jobs.folder(job), 'screen-'+str(time.time_ns()))

    def transfer(self, job):
        state = self.state(job)
        serial = self.adb.config.android_serial
        if not serial:
            raise MobileError('connect로 실제 휴대폰 식별자를 먼저 저장하세요.')
        if state['phase'] not in ('prepared','transferred'):
            raise MobileError('작성 화면을 연 작업은 다시 전송하지 않고 현재 화면에서 이어가세요.')
        files = {}
        for kind, row in state['package']['media'].items():
            remote = f'/sdcard/Movies/Hotpost/{job}/{row["name"]}'
            self.adb.push(self.jobs.folder(job)/row['name'],remote,row['sha256'])
            files[kind] = remote
        uri = self.adb.video_uri(files['video'])
        return self.jobs.update(job,'transferred',remote=files,video_uri=uri,device_serial=serial)

    def verify_profile(self, account):
        screen = self.ui.screen()
        check_screen(screen)
        if not any(node_label(n) in ('프로필 편집','프로필편집','Edit profile') for n in screen['nodes']):
            raise MobileError('로그인한 본인의 프로필 화면인지 확인하지 못했습니다. 프로필 탭을 여세요.')
        node = unique(screen['nodes'],lambda n:n['resource_id'].rsplit('/',1)[-1] in PROFILE_TITLES
                      and node_label(n).lstrip('@')==account,
                      '프로필 화면의 현재 계정 이름을 확인하지 못했습니다. 프로필/계정을 선택한 뒤 다시 실행하세요.')
        return {'account':account,'screen_sha256':screen['sha256'],'resource_id':node['resource_id']}

    def open(self, job, via='instagram'):
        state = self.state(job)
        if state['phase']!='transferred':
            raise MobileError('전송된 작업만 작성 화면을 새로 열 수 있습니다.')
        account = self.verify_profile(state['package']['account'])
        # Persist before intent dispatch; a crash cannot silently open another composer.
        self.jobs.update(job,'composer_opening',profile_check=account,via=via)
        self.adb.open_video(state['video_uri'], EDITS if via=='edits' else INSTAGRAM)
        self.jobs.update(job,'composer',opened_at=time.time())
        return self.inspect(job)

    def navigate(self, job, index, screen_sha):
        self.state(job)
        screen = self.ui.screen()
        check_screen(screen,edits=True)
        if screen['sha256']!=screen_sha:
            raise MobileError('화면이 바뀌었습니다. inspect로 현재 화면을 다시 읽으세요.')
        node = unique(screen['nodes'],lambda n:n['index']==index,'현재 화면 요소가 없습니다.')
        label = node_label(node)
        account_names = set(ACCOUNTS)
        profile_switch = node['resource_id'].rsplit('/',1)[-1] in PROFILE_TITLES
        handoff = screen['package']==EDITS and label in EDITS_HANDOFF
        if label in FINAL_LABELS or (label not in NAV_LABELS and label.lstrip('@') not in account_names and not profile_switch and not handoff):
            raise MobileError('일반 탐색은 다음/릴스/표지/프로필 등 작성 동작만 허용합니다. 최종 공유는 publish를 사용하세요.')
        self.ui.tap(node)
        self.jobs.update(job,self.jobs.get(job)['phase'],cover_review=None)
        return self.inspect(job)

    def fill_caption(self, job):
        state = self.state(job)
        if state['phase'] not in ('composer','ready'):
            raise MobileError('작성 화면에서만 본문을 입력합니다.')
        screen = self.ui.screen();check_screen(screen)
        node = unique(screen['nodes'],lambda n:n['class']=='android.widget.EditText' and
                      any(s in n['resource_id'].lower() for s in CAPTION_IDS),
                      '현재 앱 버전의 본문 입력칸을 확인해야 합니다. inspect 화면을 확인하세요.')
        self.ui.set_text(node,state['package']['caption'])
        return self.inspect(job)

    def ready_screen(self, state):
        screen = self.ui.screen();check_screen(screen)
        nodes = screen['nodes'];payload = state['package']
        unique(nodes,lambda n:n['class']=='android.widget.EditText' and n['text']==payload['caption'],
               '게시 본문이 준비한 내용과 다릅니다.')
        # Composer identity must be an account header, never a mention inside the caption.
        unique(nodes,lambda n:n['class']!='android.widget.EditText' and
               any(s in n['resource_id'].lower() for s in ('username','account','profile_name')) and
               node_label(n).lstrip('@')==payload['account'],'게시 화면의 업로드 계정을 확인하지 못했습니다.')
        unique(nodes,lambda n:node_label(n) in ('새 릴스','New reel','릴스 공유','Share reel'),
               '릴스 게시 화면인지 확인하지 못했습니다. 스토리/피드는 게시하지 않습니다.')
        share = unique(nodes,lambda n:node_label(n) in FINAL_LABELS,'공유 버튼 하나를 확인하지 못했습니다.')
        return screen,share

    def ready(self, job):
        state = self.state(job)
        if state['phase'] not in ('composer','ready'):
            raise MobileError('현재 작성 화면이 준비되지 않았습니다.')
        screen,_ = self.ready_screen(state)
        review = state.get('cover_review') or {}
        if (review.get('screen_sha256')!=screen['sha256'] or
                review.get('cover_sha256')!=state['package']['media']['cover']['sha256']):
            raise MobileError('현재 작성 화면의 표지를 준비한 cover.png와 시각 비교한 뒤 review-cover로 기록하세요.')
        captured = self.ui.capture(self.jobs.folder(job),'ready-to-share')
        return self.jobs.update(job,'ready',ready_screen_sha256=captured['sha256'],
                                reviewed_package_sha256=state['package_sha256'])

    def review_cover(self, job, screen_sha, cover_sha):
        """Record an operator's visual review, not automatic cover-image recognition."""
        state = self.state(job)
        if state['phase'] not in ('composer','ready'):
            raise MobileError('작성 화면에서 표지를 확인하세요.')
        screen,_ = self.ready_screen(state)
        if screen['sha256']!=screen_sha or cover_sha!=state['package']['media']['cover']['sha256']:
            raise MobileError('현재 화면과 검토한 표지가 다릅니다.')
        self.ui.capture(self.jobs.folder(job),'cover-operator-reviewed')
        return self.jobs.update(job,'composer',cover_review={'screen_sha256':screen_sha,'cover_sha256':cover_sha,
                                                          'method':'operator_visual_review'})

    def advance(self, job):
        """One observed navigation step; repeat explicitly, never blind coordinate macros."""
        state = self.state(job)
        if state['phase']!='composer':
            raise MobileError('open으로 작성 화면을 먼저 여세요.')
        screen = self.ui.screen();check_screen(screen,edits=True)
        caption = [n for n in screen['nodes'] if n['class']=='android.widget.EditText' and
                   any(s in n['resource_id'].lower() for s in CAPTION_IDS)]
        if len(caption)==1:
            return self.fill_caption(job)
        choices = [n for n in screen['nodes'] if node_label(n) in ('릴스','Reel','Reels','다음','Next') or
                   (screen['package']==EDITS and node_label(n) in EDITS_HANDOFF)]
        if len(choices)!=1:
            return {'needs_screen_review':True,**self.inspect(job)}
        return self.navigate(job,choices[0]['index'],screen['sha256'])

    def publish(self, job, approved_sha):
        state = self.state(job)
        if state['phase']!='ready' or approved_sha!=state['package_sha256']:
            raise MobileError('현재 게시 패키지를 검토한 뒤 그 SHA로 publish를 명시 실행하세요.')
        screen,share = self.ready_screen(state)
        if (state.get('cover_review') or {}).get('screen_sha256')!=screen['sha256']:
            raise MobileError('표지 검토 기록이 없습니다.')
        proof = self.ui.capture(self.jobs.folder(job),'before-share')
        if proof['sha256']!=screen['sha256']:
            raise MobileError('공유 직전 화면이 바뀌었습니다. 현재 작성 화면을 다시 확인하세요.')
        self.jobs.claim_submit(job,approved_sha)
        try:
            self.ui.tap(share)
        except Exception:
            self.jobs.update(job,'unknown',message='공유 요청 이후 연결 상태 불명. 다시 누르지 않고 결과 확인이 필요합니다.')
            raise
        # A lack of acknowledgement is ambiguous, never a reason to tap again.
        return self.reconcile(job)

    def reconcile(self, job):
        state = self.jobs.get(job);self.jobs.validate(state)
        if state['phase'] not in ('submitting','unknown','submitted'):
            raise MobileError('공유를 시도한 작업만 결과를 확인합니다.')
        try:
            screen = self.ui.capture(self.jobs.folder(job),'share-result-'+str(time.time_ns()))
            check_screen(screen)
            found = any(any(ack in node_label(n) for ack in ACKNOWLEDGEMENTS) for n in screen['nodes'])
            if found:
                result = self.jobs.update(job,'submitted',platform_acknowledged=True,media_verified=False,
                                          message='앱의 공유 완료 안내 확인. 공개 릴스의 계정/영상 확인은 별도입니다.')
                self.jobs.release_phone(job)
                return result
        except Exception:
            pass
        if state['phase']=='submitted':
            return state
        return self.jobs.update(job,'unknown',message='공유 완료 안내를 확인하지 못했습니다. 재게시 없이 현재 앱/프로필에서 확인하세요.')

    def confirm_result(self, job, post_url, screen_sha):
        """Explicit operator result confirmation after an ambiguous share; never re-submit."""
        state = self.jobs.get(job);self.jobs.validate(state)
        if state['phase'] not in ('unknown','submitting'):
            raise MobileError('결과가 불명확한 공유 시도만 수동 결과 확인으로 마무리합니다.')
        match = re.fullmatch(r'https://(?:www\.)?instagram\.com/reel/([A-Za-z0-9_-]+)/?',post_url)
        if not match or match[1]==state['package']['shortcode']:
            raise MobileError('원본 레퍼런스가 아닌 실제 우리 릴스 URL이 필요합니다.')
        screen = self.ui.capture(self.jobs.folder(job),'operator-confirmed-result');check_screen(screen)
        if screen['sha256']!=screen_sha:
            raise MobileError('게시 결과를 확인한 화면이 바뀌었습니다.')
        result = self.jobs.update(job,'submitted',operator_confirmed=True,platform_acknowledged=False,
                                  post_url=post_url,media_verified=False,
                                  message='운영자가 현재 앱 화면과 릴스 URL로 결과 확인. 자동 재게시하지 않습니다.')
        self.jobs.release_phone(job)
        return result
