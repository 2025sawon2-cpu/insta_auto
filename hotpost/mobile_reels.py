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

from .mobile_device import MobileError, atomic_json, phone_lock, device_name
from .post_media_rules import DISCLOSURE_VERSION, require_content_opening
from .post_preparation import ACCOUNTS
from .post_thumbnail import encode_delivery

INSTAGRAM = 'com.instagram.android'
EDITS = 'com.instagram.basel'
FINAL_LABELS = {'공유','공유하기','게시','게시하기','Share','Publish','Post','Share reel'}
NAV_LABELS = {'다음','Next','릴스','릴','Reel','Reels','동영상','Video','확인','OK','완료','Done',
              '프로필','Profile','표지 편집','커버 수정','Edit cover','새 프로젝트','New project','추가','Add','계속','Continue',
              '카메라 롤에서 추가','Add from camera roll','표지','Cover','갤러리','Gallery','최근','Recents'}
EDITS_HANDOFF = {'Instagram에 공유','인스타그램에 공유','Share to Instagram','내보내기','Export'}
PROFILE_TITLES = ('action_bar_title','profile_header_username','row_profile_header_username')
CAPTION_IDS = ('caption','creation_text','write_a_caption')
CAPTION_CLASSES = ('android.widget.EditText', 'android.widget.AutoCompleteTextView')
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


def check_upstream_hold(state):
    hold = state.get('upstream_hold')
    if hold:
        raise MobileError(hold.get('reason') or '리틀리 선행 작업을 완료한 뒤 기존 모바일 작업을 이어가세요.')


def approval_digest(state, screen_sha):
    if state.get('via') != 'edits':
        if not state.get('upstream_binding'):
            return state['package_sha256']
        return package_digest({'input_package':state['package_sha256'],
                               'upstream_binding':state['upstream_binding'], 'screen':screen_sha})
    return package_digest({'input_package': state['package_sha256'],
        'media_selection': state.get('edits_media_selection'), 'audio': state.get('edits_audio_selection'),
        'music_volume_percent': state.get('edits_audio_volume_percent'),
        'handoff_at': state.get('edits_handoff_at'), 'ready_screen_sha256': screen_sha,
        'native_draft': state.get('native_draft_resume'),
        'upstream_binding': state.get('upstream_binding'),
        'cover': state['package']['media']['cover']['sha256']})


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
            db.execute('CREATE TABLE IF NOT EXISTS device_owner(device TEXT PRIMARY KEY, job TEXT NOT NULL)')

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

    def prepare(self, preparations, code, account, converter=phone_video, *, device_id='primary'):
        device_id = device_name(device_id)
        account = account.removeprefix('@')
        available = preparations.accounts() if hasattr(preparations,'accounts') else ACCOUNTS
        if account not in available:
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
        if device_id != 'primary':
            payload['device_id'] = device_id
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
            value = {'package':payload,'package_sha256':package_digest(payload),'created':time.time(),
                     'requested_music_volume_percent':70}
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
        binding = state.get('upstream_binding')
        if binding:
            path = Path(binding['path'])
            if path.parent.resolve()!=folder.resolve() or digest(path)!=binding['sha256']:
                raise MobileError('리틀리 선행 검증 결속이 변경됐습니다.')
            companion = json.loads(path.read_text('utf8'))
            if companion['input_package_sha256']!=state['package_sha256']:
                raise MobileError('리틀리와 모바일 패키지가 다릅니다.')
            for proof in [companion['receipt'], *companion['evidence'].values()]:
                if digest(proof['path'])!=proof['sha256']:
                    raise MobileError('리틀리 저장 근거가 변경됐습니다.')
        return payload

    def bind_littly(self, job, preparations, receipt_path):
        """Freeze verified upstream evidence without replacing an existing native draft."""
        state = self.get(job)
        if state['phase'] in UNSAFE_PHASES or state['phase']=='cancelled':
            raise MobileError('공유 시도 뒤 선행 설정을 교체할 수 없습니다.')
        payload = self.validate(state)
        path = Path(receipt_path).resolve()
        receipt = json.loads(path.read_text('utf8'))
        current = preparations.get(payload['shortcode'])
        draft = current['draft']
        source = preparations.source(payload['shortcode'])
        expected = {'account':payload['account'], 'shortcode':payload['shortcode'], 'job':job,
                    'input_package_sha256':state['package_sha256'], 'draft_revision':current['revision'],
                    'affiliate_url':draft['product_link'], 'post_mode':'next_post',
                    'comment_condition':'all', 'saved_verified':True, 'one_link_format_verified':True,
                    'dm_message':draft['dm_message'], 'button_text':draft['dm_button_text']}
        if any(receipt.get(k)!=v for k,v in expected.items()) or not draft['product_link']:
            raise MobileError('현재 초안과 리틀리 저장 결과가 다릅니다.')
        if (any(draft[k]!=payload[k] for k in ('caption','pinned_comment')) or
                digest(source['media']['final'])!=payload['source_video_sha256'] or
                digest(source['media']['cover'])!=payload['source_cover_sha256']):
            raise MobileError('기존 모바일 초안의 영상·본문·표지가 달라졌습니다.')
        evidence = receipt.get('evidence') or {}
        required = ('system-verified.json','littly-after-update.json')
        if any(k not in evidence for k in required):
            raise MobileError('원링크와 리틀리 실제 저장 근거가 필요합니다.')
        for proof in evidence.values():
            if digest(proof['path'])!=proof['sha256']:
                raise MobileError('리틀리 저장 근거가 변경됐습니다.')
        system = json.loads(Path(evidence['system-verified.json']['path']).read_text('utf8'))
        if system.get('one_link')!=draft['product_link'] or system.get('landing_verified') is not True:
            raise MobileError('검증한 원링크와 저장 링크가 다릅니다.')
        companion = {**expected, 'receipt':{'path':str(path),'sha256':digest(path)},
                     'evidence':evidence, 'draft':draft, 'verified_at':time.time()}
        target = self.folder(job)/('upstream-'+package_digest(companion)+'.json')
        atomic_json(target,companion)
        return self.update(job,'composer',upstream_binding={'path':str(target),'sha256':digest(target)},
                           upstream_hold=None, approval_sha256=None, cover_review=None)

    def claim_submit(self, job, expected_sha):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
            if not row or row['phase']!='ready':
                raise MobileError('게시 직전 검토된 작업만 한 번 공유할 수 있습니다.')
            value = json.loads(row['value'])
            check_upstream_hold(value)
            if expected_sha!=value.get('approval_sha256',value['package_sha256']):
                raise MobileError('승인한 게시 패키지가 다릅니다.')
            for prior in db.execute("SELECT value FROM jobs WHERE id<>? AND phase IN ('submitting','unknown','submitted')", (job,)):
                previous = json.loads(prior[0])['package']
                if (previous['account'],previous['shortcode']) == (value['package']['account'],value['package']['shortcode']):
                    raise MobileError('이 계정과 영상은 다른 폰에서도 이미 공유를 시도했습니다. 결과만 확인하세요.')
            value['share_attempted_at'] = time.time()
            db.execute('UPDATE jobs SET phase=?,value=? WHERE id=?',('submitting',json.dumps(value,ensure_ascii=False),job))

    def own_phone(self, job):
        device_id = self.get(job)['package'].get('device_id','primary')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            owner = (db.execute('SELECT job FROM phone_owner WHERE slot=1').fetchone() if device_id=='primary'
                     else db.execute('SELECT job FROM device_owner WHERE device=?',(device_id,)).fetchone())
            if owner and owner[0]!=job:
                raise MobileError('다른 영상의 폰 작업이 아직 끝나지 않았습니다. 기존 작업을 완료/게시 전 취소한 뒤 진행하세요.')
            if device_id=='primary':
                db.execute('INSERT OR IGNORE INTO phone_owner VALUES (1,?)',(job,))
            else:
                db.execute('INSERT OR IGNORE INTO device_owner VALUES (?,?)',(device_id,job))

    def release_phone(self, job):
        with self.connect() as db:
            db.execute('DELETE FROM phone_owner WHERE slot=1 AND job=?',(job,))
            db.execute('DELETE FROM device_owner WHERE job=?',(job,))

    def cancel(self, job):
        state = self.get(job)
        if state['phase'] in UNSAFE_PHASES:
            raise MobileError('공유 이후 작업은 취소로 재게시 잠금을 해제할 수 없습니다. 결과를 확인하세요.')
        result = self.update(job,'cancelled')
        self.release_phone(job)
        return result


def node_label(node):
    return node.get('text') or node.get('description') or ''


def edits_audio_catalog_sha(screen):
    """Bind music choice to the visible catalog, excluding the playing timeline behind it."""
    rows = [{'id': n['resource_id'], 'description': n['description'], 'bounds': n['bounds']}
            for n in screen['nodes'] if n['resource_id'].startswith('audio_browser_preview_track_')]
    search = [n['text'] for n in screen['nodes']
              if n['resource_id'] == EDITS + ':id/row_search_edit_text']
    if screen['package'] != EDITS or not rows or len(search) != 1:
        raise MobileError('Edits의 음악 검색 목록을 확인하지 못했습니다.')
    return package_digest({'package': EDITS, 'tracks': rows, 'search': search})


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
    def __init__(self, jobs, adb, ui, *, device_id='primary'):
        self.jobs,self.adb,self.ui = jobs,adb,ui
        self.device_id = device_name(device_id)

    def state(self, job):
        state = self.jobs.get(job)
        self.jobs.validate(state)
        self.check_device(state)
        if state['phase'] in UNSAFE_PHASES or state['phase']=='cancelled':
            raise MobileError('이미 공유를 시도한 작업입니다. 재게시하지 말고 결과를 확인하세요.')
        check_upstream_hold(state)
        self.jobs.own_phone(job)
        return state

    def check_device(self, state):
        if state['package'].get('device_id','primary') != self.device_id:
            raise MobileError('이 작업에 지정된 휴대폰과 선택한 기기가 다릅니다.')
        if state.get('device_serial') and state['device_serial']!=self.adb.config.android_serial:
            raise MobileError('작업을 시작했던 휴대폰과 현재 연결이 다릅니다.')

    def inspect(self, job):
        self.check_device(self.jobs.get(job))
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

    def open(self, job, via='edits'):
        state = self.state(job)
        if state['phase']!='transferred':
            raise MobileError('전송된 작업만 작성 화면을 새로 열 수 있습니다.')
        account = self.verify_profile(state['package']['account'])
        # Persist before intent dispatch; a crash cannot silently open another composer.
        self.jobs.update(job,'composer_opening',profile_check=account,via=via)
        if via == 'edits':
            self.ui.open_app(EDITS)
        else:
            self.adb.open_video(state['video_uri'], INSTAGRAM)
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
        account_names = set(ACCOUNTS) | {self.jobs.get(job)['package']['account']}
        profile_switch = node['resource_id'].rsplit('/',1)[-1] in PROFILE_TITLES
        profile_create = (node['resource_id'].rsplit('/',1)[-1] == 'profile_header_create_button'
                          and label in ('새로 만들기', 'Create'))
        if profile_create:
            self.verify_profile(self.jobs.get(job)['package']['account'])
        handoff = (screen['package']==EDITS and (label in EDITS_HANDOFF or
                   (label=='Instagram' and any(n['text']=='공유 위치 선택' for n in screen['nodes']))))
        if screen['package']==EDITS and (handoff or label in ('다음','Next')) and self.jobs.get(job).get('requested_music_volume_percent') is not None:
            music_state = self.jobs.get(job)
            if (not music_state.get('edits_audio_volume_verified') or
                    music_state.get('edits_audio_volume_percent') != music_state['requested_music_volume_percent']):
                raise MobileError('요청한 음악 볼륨을 확인한 뒤 내보내세요.')
        job_album = screen['package'] in (EDITS, INSTAGRAM) and label == job
        edits_audio = screen['package']==EDITS and label in ('오디오 추가', 'Add audio')
        edits_return = (screen['package']==EDITS and label == '취소'
                        and any(n['text']=='공유 위치 선택' for n in screen['nodes']))
        audio_title = re.search(r'님의 (.+) 트랙 선택',
                                (self.jobs.get(job).get('edits_audio_selection') or {}).get('description',''))
        edits_audio_apply = (screen['package']==EDITS and node['resource_id']=='audio_bar_select_tap_target'
                             and audio_title and audio_title[1] in label)
        edits_music_control = (screen['package']==EDITS and audio_title
                               and node['resource_id']==EDITS+':id/clips_action_bar_volume_controls_button'
                               and label in ('볼륨','Volume')
                               and any(audio_title[1] in n['description'] and n['description'].startswith('오디오 트랙')
                                       for n in screen['nodes']))
        if label in FINAL_LABELS or (label not in NAV_LABELS and label.lstrip('@') not in account_names and not profile_switch and not profile_create and not handoff and not job_album and not edits_audio and not edits_return and not edits_audio_apply and not edits_music_control):
            raise MobileError('일반 탐색은 다음/릴스/표지/프로필 등 작성 동작만 허용합니다. 최종 공유는 publish를 사용하세요.')
        self.ui.tap(node)
        self.jobs.update(job,self.jobs.get(job)['phase'],cover_review=None)
        if edits_audio_apply:
            self.jobs.update(job, 'composer', edits_audio_applied=True)
        if edits_music_control:
            self.jobs.update(job, 'composer', edits_audio_volume_verified=False)
        if handoff:
            self.jobs.update(job, 'composer', edits_handoff_at=time.time())
        if profile_switch or label.lstrip('@') in account_names:
            self.jobs.update(job, self.jobs.get(job)['phase'], composer_account_proof=None)
        return self.inspect(job)

    def fill_caption(self, job):
        state = self.state(job)
        if state['phase'] not in ('composer','ready'):
            raise MobileError('작성 화면에서만 본문을 입력합니다.')
        screen = self.ui.screen();check_screen(screen)
        node = unique(screen['nodes'],lambda n:n['class'] in CAPTION_CLASSES and
                      any(s in n['resource_id'].lower() for s in CAPTION_IDS),
                      '현재 앱 버전의 본문 입력칸을 확인해야 합니다. inspect 화면을 확인하세요.')
        self.ui.set_text(node,state['package']['caption'])
        return self.inspect(job)

    def select_edits_video(self, job, screen_sha):
        state = self.state(job)
        if state['phase'] != 'composer' or state.get('via') != 'edits':
            raise MobileError('Edits 작성 단계에서만 전송 영상을 선택합니다.')
        screen = self.ui.screen(); check_screen(screen, edits=True)
        if screen['package'] != EDITS or screen['sha256'] != screen_sha:
            raise MobileError('Edits 갤러리의 현재 화면을 다시 확인하세요.')
        unique(screen['nodes'], lambda n: n['text'] == job, '현재 작업의 전용 사진첩을 선택하세요.')
        node = unique(screen['nodes'], lambda n:
                      n['resource_id'] == EDITS + ':id/gallery_picker_grid_item_container'
                      and n['description'].startswith(('동영상 썸네일', 'Video thumbnail')),
                      '전용 사진첩의 영상 하나를 확인하지 못했습니다.')
        if self.adb.video_uri(state['remote']['video']) != state['video_uri']:
            raise MobileError('전송 영상의 갤러리 식별자가 바뀌었습니다.')
        self.ui.tap(node)
        self.jobs.update(job, 'composer', edits_media_selection={
            'album': job, 'video_uri': state['video_uri'], 'screen_sha256': screen_sha,
            'video_sha256': state['package']['media']['video']['sha256']})
        return self.inspect(job)

    def select_cover(self, job, screen_sha):
        state = self.state(job)
        if state['phase'] not in ('composer','ready'):
            raise MobileError('작성 화면에서 표지를 선택하세요.')
        screen = self.ui.screen(); check_screen(screen)
        if screen['sha256'] != screen_sha:
            raise MobileError('현재 표지 사진첩을 다시 확인하세요.')
        unique(screen['nodes'], lambda n: n['text']==job, '현재 작업의 전용 사진첩을 선택하세요.')
        node = unique(screen['nodes'], lambda n: n['resource_id']==INSTAGRAM+':id/gallery_image'
                      and n['description'].startswith(('사진 썸네일','Photo thumbnail')),
                      '전용 사진첩의 표지 한 장을 확인하지 못했습니다.')
        actual = self.adb.command('shell','toybox','sha256sum',state['remote']['cover']).decode().split()[0]
        if actual != state['package']['media']['cover']['sha256']:
            raise MobileError('폰의 표지 파일이 준비한 파일과 다릅니다.')
        self.ui.tap(node)
        self.jobs.update(job,'composer',selected_cover_sha256=actual,cover_review=None)
        return self.inspect(job)

    def select_edits_audio(self, job, track_id, catalog_sha):
        state = self.state(job)
        screen = self.ui.screen(); check_screen(screen, edits=True)
        if state.get('via') != 'edits' or edits_audio_catalog_sha(screen) != catalog_sha:
            raise MobileError('Edits의 현재 오디오 선택 화면을 다시 확인하세요.')
        node = unique(screen['nodes'], lambda n: n['resource_id'] == track_id
                      and re.fullmatch(r'audio_browser_preview_track_\d+_\d+_TRACK_\d+', n['resource_id']),
                      '관찰된 Edits 음악 항목 하나를 선택하세요.')
        self.ui.tap(node)
        self.jobs.update(job, 'composer', edits_audio_selection={
            'resource_id': node['resource_id'], 'description': node['description'],
            'screen_sha256': screen['sha256'], 'catalog_sha256': catalog_sha},
            edits_audio_volume_verified=False, cover_review=None)
        return self.inspect(job)

    def record_edits_volume(self, job, percent, screen_sha):
        state = self.state(job)
        screen = self.ui.screen(); check_screen(screen, edits=True)
        title = re.search(r'님의 (.+) 트랙 선택', (state.get('edits_audio_selection') or {}).get('description',''))
        if (state.get('via') != 'edits' or screen['package'] != EDITS or screen['sha256'] != screen_sha
                or not state.get('edits_audio_applied') or not title
                or percent != state.get('requested_music_volume_percent')):
            raise MobileError('현재 음악과 요청한 볼륨을 확인하세요.')
        unique(screen['nodes'], lambda n: n['description'].startswith('오디오 트랙') and title[1] in n['description'],
               '선택된 음악 트랙을 확인하지 못했습니다.')
        unique(screen['nodes'], lambda n: n['resource_id']=='volume_slider' and n['text']==f'{percent:.1f}',
               '현재 음악 볼륨이 요청한 값과 다릅니다.')
        proof = self.ui.capture(self.jobs.folder(job), 'edits-music-volume-verified')
        if proof['sha256'] != screen_sha:
            raise MobileError('볼륨 확인 중 화면이 바뀌었습니다.')
        return self.jobs.update(job, 'composer', edits_audio_volume_verified=True,
                                edits_audio_volume_percent=percent, edits_volume_screen_sha256=screen_sha)

    def ready_screen(self, state):
        screen = self.ui.screen();check_screen(screen)
        nodes = screen['nodes'];payload = state['package']
        caption = unique(nodes,lambda n:n['class'] in CAPTION_CLASSES and
                         any(s in n['resource_id'].lower() for s in CAPTION_IDS),
                         '본문 입력칸 하나를 확인하지 못했습니다.')
        if self.ui.get_text(caption) != payload['caption']:
            raise MobileError('게시 본문이 준비한 내용과 다릅니다.')
        # Composer identity must be an account header, never a mention inside the caption.
        headers = [n for n in nodes if n['class'] not in CAPTION_CLASSES and
                   any(s in n['resource_id'].lower() for s in ('username','account','profile_name'))]
        if headers:
            unique(headers,lambda n:node_label(n).lstrip('@')==payload['account'],
                   '게시 화면의 업로드 계정을 확인하지 못했습니다.')
        else:
            self.validate_handoff_account(state)
        unique(nodes,lambda n:node_label(n) in ('새 릴스','새로운 릴스','New reel','릴스 공유','Share reel'),
               '릴스 게시 화면인지 확인하지 못했습니다. 스토리/피드는 게시하지 않습니다.')
        buttons = [n for n in nodes if n['resource_id']==INSTAGRAM+':id/share_button']
        share = unique(buttons or nodes,lambda n:node_label(n) in FINAL_LABELS,'공유 버튼 하나를 확인하지 못했습니다.')
        return screen,share

    def record_handoff_account(self, job, label):
        state = self.state(job)
        if not re.fullmatch(r'[a-z0-9-]+', label):
            raise MobileError('작업 폴더의 화면 기록 이름을 확인하세요.')
        path = self.jobs.folder(job)/(label+'.json')
        image = path.with_suffix('.png')
        proof = json.loads(path.read_text('utf8'))
        expected = state['package']['account']
        if (state.get('via') != 'edits' or not state.get('edits_handoff_at')
                or path.stat().st_mtime < state['edits_handoff_at']
                or (state.get('profile_check') or {}).get('account') != expected
                or proof.get('package') != INSTAGRAM
                or not any(n['resource_id']==INSTAGRAM+':id/snackbar_message'
                           and n['text']==expected+'님으로 로그인함' for n in proof['nodes'])
                or not any(n['resource_id']==INSTAGRAM+':id/action_bar_title'
                           and n['text']=='새로운 릴스' for n in proof['nodes'])):
            raise MobileError('같은 Edits 전달에서 앱이 표시한 로그인 계정 근거가 필요합니다.')
        return self.jobs.update(job, state['phase'], composer_account_proof={
            'account': expected, 'path': str(path), 'sha256': digest(path),
            'image_path': str(image), 'image_sha256': digest(image),
            'handoff_at': state['edits_handoff_at'], 'method': 'app_signin_notice_same_handoff'})

    def validate_handoff_account(self, state):
        proof = state.get('composer_account_proof') or {}
        if (proof.get('account') != state['package']['account'] or state.get('via')!='edits'
                or proof.get('handoff_at') != state.get('edits_handoff_at')
                or not proof.get('path') or not proof.get('image_path')
                or Path(proof['path']).resolve().parent != self.jobs.folder(state['id']).resolve()
                or Path(proof['image_path']).resolve().parent != self.jobs.folder(state['id']).resolve()
                or digest(proof['path']) != proof.get('sha256')
                or digest(proof['image_path']) != proof.get('image_sha256')):
            raise MobileError('게시 화면의 업로드 계정을 확인하지 못했습니다.')

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
        approval = approval_digest(state,captured['sha256'])
        if state.get('via') == 'edits':
            if not state.get('edits_handoff_at') or not state.get('edits_media_selection'):
                raise MobileError('현재 Edits 영상의 선택·전달 기록을 확인하세요.')
            if state.get('requested_music_volume_percent') is not None and (
                    not state.get('edits_audio_applied') or not state.get('edits_audio_volume_verified') or
                    state.get('edits_audio_volume_percent') != state['requested_music_volume_percent']):
                raise MobileError('요청한 Edits 음악 볼륨을 확인하세요.')
            approval = approval_digest(state,captured['sha256'])
        return self.jobs.update(job,'ready',ready_screen_sha256=captured['sha256'],
                                reviewed_package_sha256=state['package_sha256'], approval_sha256=approval)

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
        caption = [n for n in screen['nodes'] if n['class'] in CAPTION_CLASSES and
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
        if state['phase']!='ready' or approved_sha!=state.get('approval_sha256',state['package_sha256']):
            raise MobileError('현재 게시 패키지를 검토한 뒤 그 SHA로 publish를 명시 실행하세요.')
        screen,share = self.ready_screen(state)
        if approval_digest(state,screen['sha256']) != approved_sha:
            raise MobileError('승인 뒤 Edits 음악·볼륨·전달 정보 또는 화면이 바뀌었습니다.')
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
        self.check_device(state)
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
        self.check_device(state)
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
