"""Visible Instagram composer contract; unsupported screens stop the attempt.

No private endpoints, replacement sessions, or repeated Share clicks are used.
The receipt proves submitted inputs, not the transcoded media on a public post.
"""
from pathlib import Path
import re

from .instagram_publish import validate_package
from .request_pacing import request_pause


class InstagramPublishBrowserMixin:
    def publish_instagram(self, state, folder, progress):
        from .monetization_browser import (one_visible, instagram_post_identity,
                                           selected_setting, logged_in_instagram_profile)
        package = validate_package(state, require_cover=True)
        with self.session(folder) as context:
            # A manual post could have consumed the reservation since creation.
            automation = self._open_saved_automation(context, state)
            if not selected_setting(automation, '다음에 올릴게시물을 자동화할게요'):
                raise ValueError('리틀리의 다음 게시물 예약 모드가 확인되지 않습니다.')
            for anchor in automation.locator('a[href]:visible').all():
                try:
                    instagram_post_identity(anchor.get_attribute('href'))
                except ValueError:
                    continue
                raise ValueError('리틀리 예약이 이미 게시물에 연결됐습니다. 수동 게시 여부를 확인하세요.')
            page = self.page(context, 'instagram')
            self.access(page)
            logged_in_instagram_profile(page, state['account'])
            create = re.compile(r'^(?:새로 만들기|만들기|Create|New post)$', re.I)
            control = one_visible(page.get_by_role('link', name=create).or_(page.get_by_role('button', name=create)))
            request_pause(); control.click()
            # Some supported layouts expose a Post menu before the dialog.
            menu = page.get_by_role('menuitem', name=re.compile(r'^(?:게시물|Post)$', re.I))
            if menu.count() == 1 and menu.is_visible():
                request_pause(); menu.click()
            dialog = one_visible(page.get_by_role('dialog'))
            self.capture(page, folder, 'instagram-composer')
            progress('uploading', {'package_sha256': package['package_sha256']})

            def upload(locator, kind):
                # File inputs can be hidden, but must be unique and explicitly
                # accept the expected media type in this composer.
                if locator.count() != 1:
                    raise ValueError('현재 작성 화면에서 업로드 입력 하나를 확인하지 못했습니다.')
                row = package['media'][kind]
                locator.set_input_files(row['path'])
                if Path(locator.input_value().replace('\\', '/')).name != Path(row['path']).name:
                    raise ValueError('선택된 업로드 파일이 게시 패키지와 다릅니다.')

            upload(dialog.locator('input[type=file][accept*="video"]'), 'video')
            one_visible(dialog.locator('video:visible'))
            self.capture(page, folder, 'instagram-video-selected')

            def next_step(step):
                request_pause()
                one_visible(dialog.get_by_role('button', name=re.compile(r'^(?:다음|Next)$', re.I))).click()
                self.capture(page, folder, step)
                self.access(page)

            next_step('instagram-crop-next')
            cover_button = dialog.get_by_role('button', name=re.compile(
                r'^(?:표지 사진 선택|표지 사진 수정|표지 편집|Select cover photo|Edit cover)$', re.I))
            request_pause(); one_visible(cover_button).click()
            upload(dialog.locator('input[type=file][accept*="image"]:not([accept*="video"])'), 'cover')
            self.capture(page, folder, 'instagram-cover-selected')
            next_step('instagram-edit-next')
            caption = one_visible(dialog.get_by_role('textbox', name=re.compile('문구|캡션|caption', re.I)))
            caption.fill(package['caption'])
            actual = caption.input_value() if caption.evaluate('(e) => e.tagName === "TEXTAREA" || e.tagName === "INPUT"') else caption.inner_text()
            if actual.replace('\r\n', '\n') != package['caption']:
                raise ValueError('인스타 작성 화면의 본문이 게시 패키지와 다릅니다.')
            one_visible(dialog.get_by_text(state['account'], exact=True))
            validate_package(state, require_cover=True)
            self.capture(page, folder, 'instagram-ready-to-share', details={
                'account': state['account'], 'package_sha256': package['package_sha256'],
                'automation_id': state['littly']['automation_id']})
            # Persist before the irreversible click. Any disconnect after this
            # boundary is reconciled through inspection, never another upload.
            progress('submitting')
            request_pause()
            one_visible(dialog.get_by_role('button', name=re.compile(r'^(?:공유|Share)$', re.I))).click()
            progress('platform_processing')
            one_visible(page.get_by_text(re.compile(
                r'게시물이 공유되었습니다|릴스가 공유되었습니다|Your (?:post|reel) has been shared', re.I)))
            evidence = self.capture(page, folder, 'instagram-share-acknowledged')
            urls = set()
            for anchor in dialog.locator('a[href]:visible').all():
                url = anchor.get_attribute('href')
                try:
                    instagram_post_identity(url)
                    urls.add(url)
                except ValueError:
                    pass
            return {'submitted': True, 'account': state['account'],
                    'package_sha256': package['package_sha256'],
                    'automation_id': state['littly']['automation_id'], 'evidence_path': evidence,
                    'post_url': next(iter(urls)) if len(urls) == 1 else '', 'media_verified': False}
