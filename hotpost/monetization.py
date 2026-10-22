"""Post-video orchestration. Does not resume or mutate the video pipeline."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import threading
import time
import uuid

from .coupang_partners import CoupangPartners, PartnerCredentials, product_identity, verify_product_match
from .monetization_store import (MonetizationStore, MonetizationConflict, NextPostBusy,
                                 ConnectionsNotReady, canonical_account, effect_lease)
from .post_publish import publishing_package, script_hash, COMMENT_KEYWORD
from .production import file_digest
from .instagram_publish import bind_package, validate_package


class Monetization:
    def __init__(self, settings, studio_store, *, browser_factory=None, partners=None, completion_store=None):
        self.settings = settings
        self.studio_store = studio_store
        self.store = MonetizationStore(settings.data_dir / 'monetization')
        self.store.recover_abandoned()
        self.credentials = PartnerCredentials(self.store.root)
        self.partners = partners or CoupangPartners(self.credentials)
        self.browser_factory = browser_factory
        self.lock = threading.Lock()
        self.threads = {}
        self.completion_store = completion_store
        self.stop = threading.Event()
        self.auto_thread = None

    def connections(self):
        from .source_browser_runtime import endpoint
        return dict(coupang=self.credentials.status(),
                    existing_browser_connected=bool(endpoint(self.settings)), automation=self.store.automation(),
                    publication_supported=True,
                    automatic_inputs_supported=True,
                    account_roles_supported=True,
                    comment_keyword=COMMENT_KEYWORD,
                    completion_worker_active=bool(self.auto_thread and self.auto_thread.is_alive()))

    def inputs(self, task_id=''):
        from .monetization_inputs import task_inputs
        return task_inputs(self.settings, self.store, task_id)

    def run_saved(self, task_id):
        account = self.store.automation()['account']
        if not account:
            raise ValueError('우리 인스타 계정을 한 번 저장하세요.')
        return self.run(task_id, account, COMMENT_KEYWORD)

    def discover_product_saved(self, task_id):
        return self.discover_product(task_id, COMMENT_KEYWORD)

    def retry_product_authorized(self, task_id, previous_effect_id, approval_ref, expected_revision):
        """Called only for an explicit new user instruction, never by a worker."""
        with effect_lease(self.store.root,self._task_lease_id(task_id)):
            _,_,binding=self._binding(task_id)
            state=self.store.get(task_id)
            if not state or state['binding']!=binding:
                raise MonetizationConflict('실패 시도 이후 영상·대본 연결이 달라졌습니다.')
            browser=self._browser()
            self._preflight(browser,state.get('discovery_account',state['account']),('instagram','coupang'))
            self._preflight(browser,state['account'],('littly',))
            self.store.authorize_product_retry(task_id,previous_effect_id,approval_ref,expected=expected_revision)
        return self.run_saved(task_id)

    def rebind_account(self, task_id, expected_revision):
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
            raise ValueError('현재 작업 revision이 필요합니다.')
        account = self.store.automation()['account']
        if not account:
            raise ValueError('우리 인스타 계정을 먼저 저장하세요.')
        with effect_lease(self.store.root, self._task_lease_id(task_id)):
            _, _, binding = self._binding(task_id)
            state = self.store.get(task_id)
            if not state or state['binding'] != binding:
                raise MonetizationConflict('현재 영상·대본과 준비된 작업의 연결이 다릅니다.')
            return self.store.rebind_unstarted_account(task_id, account, expected=expected_revision,
                discovery_account=self.store.automation().get('discovery_account', account))

    def continue_unsubmitted_product(self, task_id, effect_id, approval_id, expected_revision):
        """Manual continuation of one approved comment, never a second submit."""
        with effect_lease(self.store.root,self._task_lease_id(task_id)), effect_lease(self.store.root,effect_id):
            _,_,binding=self._binding(task_id)
            state=self.store.get(task_id)
            if not state or state['binding']!=binding:
                raise MonetizationConflict('현재 영상·대본과 승인 시도의 연결이 다릅니다.')
            browser=self._browser()
            actor=state.get('discovery_account',state['account'])
            self._preflight(browser,actor,('instagram','coupang'))
            self._preflight(browser,state['account'],('littly',))
            current=self.store.continue_unsubmitted_product(task_id,effect_id,approval_id,expected=expected_revision)
            try:
                product=browser.discover_product({**current,'account':actor},COMMENT_KEYWORD,self.store.root/task_id)
                if (product.get('account')!=actor or product.get('shortcode')!=state['shortcode']
                        or product.get('comment_count')!=1 or not product.get('comment_id') or not product.get('message_id')
                        or not product.get('product_verified') or not product.get('product_name') or not product.get('evidence_path')):
                    raise ValueError('댓글·DM·상품의 실제 확인 근거가 부족합니다.')
                product_identity(product['product_url'])
                self.store.resolve_effect(task_id,effect_id,'completed',product,{'product':product,'stage':'affiliate','error':'','comment_submit_called':True})
            except BaseException as exc:
                reason=str(exc) if isinstance(exc,(ValueError,RuntimeError)) else type(exc).__name__
                return self.store.resolve_effect(task_id,effect_id,'error',{'reason':reason,**self._error_evidence(exc)},
                                                 {'error':reason,**self._error_evidence(exc)})
        return self.run_saved(task_id)

    def preview(self, task_id):
        """Verify the real completed media and saved mapping without preparing/sending."""
        try:
            video, _, binding = self._binding(task_id)
        except OSError as exc:
            raise ValueError('선택한 완성 영상의 파일을 확인하지 못했습니다.') from exc
        account = self.store.automation()['account']
        state = self.store.get(task_id)
        execution_account = state['account'] if state else account
        discovery_account = self.store.automation().get('discovery_account', account)
        execution_discovery = state.get('discovery_account',state['account']) if state else discovery_account
        matches = bool(account and execution_account == account and discovery_account == execution_discovery)
        reason = ('우리 인스타 계정이 아직 저장되지 않았습니다.' if not account else
                  '이 작업에 연결된 계정과 현재 저장 계정이 다릅니다.' if not matches else '')
        return dict(task_id=task_id, title=video.get('title', video['shortcode']),
                    shortcode=video['shortcode'], video_verified=True, binding=binding,
                    keyword=COMMENT_KEYWORD, comment_mode='fixed', account=account,
                    execution_account=execution_account, account_matches=matches,
                    discovery_account=discovery_account, execution_discovery_account=execution_discovery,
                    verified=matches, reason=reason, external_effects_started=False)

    def start_completion_worker(self):
        if self.completion_store is None or self.auto_thread is not None:
            return
        def watch():
            while not self.stop.is_set():
                try:
                    self.completion_tick()
                except Exception:
                    # Production completion remains durable in the outbox.
                    # Never rerender a video because its follow-up is waiting.
                    pass
                self.stop.wait(5)
        self.auto_thread = threading.Thread(target=watch, name='postproduction-completions', daemon=True)
        self.auto_thread.start()

    def completion_tick(self):
        config = self.store.automation()
        if not config['enabled'] or self.completion_store is None:
            return
        owner = 'c6be6bd6217c45c788f252621dfb6838'
        try:
            with effect_lease(self.store.root, owner):
                rows = self.completion_store.postproduction_pending()
                for row in rows:
                    task_id, edit_id = row['task_id'], row['edit_id']
                    try:
                        video, _, binding = self._binding(task_id)
                        expected = {key: value for key, value in row['binding'].items() if key in binding}
                        if set(expected) != set(binding) or any(value is None or binding[key] != value for key, value in expected.items()):
                            self.completion_store.postproduction_update(task_id, edit_id, 'superseded', '완료 이후 영상·대본이 달라졌습니다.')
                            continue
                        if video.get('automation', {}).get('paused_by_user'):
                            self.completion_store.postproduction_update(task_id, edit_id, 'error', '사용자가 중지한 작업은 자동 재개하지 않습니다.')
                            continue
                        self.prepare(task_id, config['account'])
                        state = self.store.get(task_id)
                        current = self.get(task_id)
                        if current['worker_live']:
                            continue
                        if state['stage'] in {'awaiting_post', 'awaiting_delivery', 'completed'} and state['status'] == 'ready':
                            self.completion_store.postproduction_update(task_id, edit_id, 'done')
                            continue
                        if state['status'] == 'error':
                            self.completion_store.postproduction_update(task_id, edit_id, 'error', state.get('error', '후속 작업 오류'))
                            continue
                        if self.store.next_post_busy(config['account'], task_id):
                            self.completion_store.postproduction_update(task_id, edit_id, 'waiting_slot', '앞선 다음 게시물 자동화의 실제 연결 확인 대기')
                            continue
                        status = self.connections()
                        if not status['coupang']['configured'] or not status['coupang']['eligible'] or not status['existing_browser_connected']:
                            self.completion_store.postproduction_update(task_id, edit_id, 'waiting_connections', '기존 Chrome·본인 쿠팡파트너스 API 연결 대기')
                            continue
                        self.run(task_id, config['account'], COMMENT_KEYWORD)
                        self.completion_store.postproduction_update(task_id, edit_id, 'dispatched')
                    except (MonetizationConflict, ConnectionsNotReady) as exc:
                        self.completion_store.postproduction_update(task_id, edit_id, 'waiting_connections', str(exc))
                    except ValueError as exc:
                        self.completion_store.postproduction_update(task_id, edit_id, 'error', str(exc))
        except MonetizationConflict:
            return  # A verified live consumer owns this completion pass.

    def _binding(self, task_id):
        from .daily_quality import verified_quality_export
        video = self.studio_store(task_id) if callable(self.studio_store) else self.studio_store.get(task_id)
        edit = next((row for row in video.get('edits', []) if row['id'] == video.get('edit_id')), {})
        script = next((row for row in video.get('scripts', []) if row['id'] == video.get('script_id')), {})
        if (video.get('status') != 'completed' or edit.get('export_verified') is not True
                or not verified_quality_export(video, edit) or not script.get('text')):
            raise ValueError('검수·내보내기가 끝난 영상과 선택 대본이 필요합니다.')
        if edit.get('script_id') and edit['script_id'] != script['id']:
            raise ValueError('완성 영상과 현재 선택 대본의 버전이 다릅니다.')
        binding = dict(edit_id=edit['id'], video_sha256=file_digest(edit['export_path']),
                       plan_sha256=file_digest(edit['plan_path']), script_id=script['id'],
                       script_sha256=script_hash(script['text'].strip()))
        return video, script, binding

    def prepare(self, task_id, account):
        video, script, binding = self._binding(task_id)
        state = self.store.prepare(task_id, account, video['shortcode'], binding,
                                  discovery_account=self.store.automation().get('discovery_account',account))
        if state['status'] == 'waiting_connections' and all(e['status'] == 'completed' for e in self.store.effects(state)):
            state = self.store.change(task_id, {'status': 'ready', 'error': ''}, expected=state['revision'])
        if (state['status'] == 'waiting_slot' and not self.store.effects(state)
                and not self.store.next_post_busy(state['account'], task_id)):
            state = self.store.change(task_id, {'status': 'ready', 'error': ''}, expected=state['revision'])
        return state

    def get(self, task_id):
        state = self.store.get(task_id)
        if state:
            if self.completion_store is not None:
                state['automatic_followup'] = self.completion_store.postproduction_status(task_id)
            state['effects'] = self.store.effects(state)
            with self.lock:
                thread = self.threads.get(task_id)
                state['worker_live'] = bool(thread and thread.is_alive())
            if not state['worker_live']:
                try:
                    with effect_lease(self.store.root, self._task_lease_id(task_id)):
                        pass
                except MonetizationConflict:
                    state['worker_live'] = True
            # A receipt marked dispatching is evidence of an uncertain effect,
            # never permission to repost after restart.
            state['external_result_uncertain'] = any(e['status'] in {'dispatching', 'unknown'}
                and not (e['kind'] == 'instagram_publish' and state.get('post_connection', {}).get('verified'))
                for e in state['effects'])
        return state

    @staticmethod
    def _task_lease_id(task_id):
        return hashlib.sha256(('postproduction-task:' + task_id).encode()).hexdigest()[:32]

    def _current(self, task_id, stage):
        state = self.store.get(task_id)
        if not state or state['stage'] != stage or state['status'] != 'ready':
            raise MonetizationConflict('현재 단계에서 실행할 수 없습니다. 중복 실행·실패 재요청은 하지 않습니다.')
        _, _, binding = self._binding(task_id)
        if state['binding'] != binding:
            raise MonetizationConflict('준비 이후 완성 영상 또는 대본이 바뀌었습니다.')
        return state

    def _browser(self):
        if self.browser_factory:
            return self.browser_factory(self.settings)
        from .monetization_browser import MonetizationBrowser
        return MonetizationBrowser(self.settings)

    def _preflight(self, browser, account, providers):
        try:
            browser.preflight(account, providers)
        except (ValueError, RuntimeError) as exc:
            raise ConnectionsNotReady(str(exc)) from None

    def _start(self, task_id, operation):
        def execute():
            try:
                operation()
            except Exception as exc:
                state = self.store.get(task_id)
                # A duplicate request must never rewrite another live owner's
                # running state, but its own ready record must show the error.
                if state and state['status'] == 'ready':
                    reason = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
                    try:
                        status = 'waiting_slot' if isinstance(exc, NextPostBusy) else 'waiting_connections' if isinstance(exc, ConnectionsNotReady) else 'error'
                        self.store.change(task_id, {'status': status,
                                                   'error': reason, **self._error_evidence(exc)}, expected=state['revision'])
                    except MonetizationConflict:
                        pass
        def guarded():
            try:
                with effect_lease(self.store.root, self._task_lease_id(task_id)):
                    execute()
            except MonetizationConflict:
                return  # Another verified live process owns this task.
        with self.lock:
            if self.threads.get(task_id) and self.threads[task_id].is_alive():
                raise MonetizationConflict('이 게시물의 후속 작업이 진행 중입니다.')
            thread = threading.Thread(target=guarded, name='monetization-' + task_id, daemon=True)
            self.threads[task_id] = thread
            thread.start()
        return {'accepted': True, 'task_id': task_id}

    def _execute_effect(self, state, kind, details, operation, accept):
        effect = uuid.uuid4().hex
        with effect_lease(self.store.root, effect):
            self.store.reserve_effect(state, kind, {**details, 'owner_pid': os.getpid()}, effect_id=effect)
            state = self.store.get(state['task_id'])
            if kind=='product_discovery' and state.get('product_retry',{}).get('status')=='consumed':
                details={**details,'attempt_count':state['product_retry']['attempt_count']}
            try:
                result = operation()
                changes = accept(result)
            except BaseException as exc:
                reason = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
                evidence = self._error_evidence(exc)
                outcome = 'unknown' if kind in {'instagram_publish', 'littly_create'} else 'error'
                self.store.resolve_effect(state['task_id'], effect, outcome,
                    {**details, 'reason': reason, 'stage': state['stage'], **evidence},
                    {'error': reason, **evidence})
                return self.get(state['task_id'])
            # Commit accepted state while the lease is held. If this is
            # interrupted, startup records uncertainty and never re-dispatches.
            return self.store.resolve_effect(state['task_id'], effect, 'completed', result, changes)

    @staticmethod
    def _error_evidence(exc):
        # Bound to this exception, never to a stale task-level last-ui pointer.
        path = getattr(exc, 'monetization_evidence_path', None)
        result = {'error_evidence_path': path} if isinstance(path, str) and path else {}
        submitted = getattr(exc,'monetization_comment_submit_called',None)
        if isinstance(submitted,bool): result['comment_submit_called'] = submitted
        return result

    def close(self):
        self.stop.set()
        if self.auto_thread is not None:
            self.auto_thread.join()
        with self.lock:
            threads = list(self.threads.values())
        for thread in threads:
            thread.join()

    def discover_product(self, task_id, keyword, *, background=True):
        state = self._current(task_id, 'product')
        discovery_account = state.get('discovery_account',state['account'])
        keyword = COMMENT_KEYWORD
        browser = self._browser()
        # Session absence does not submit a comment or consume the one attempt.
        self._preflight(browser, discovery_account, ('instagram', 'coupang'))

        def accept(result):
            if (result.get('account') != discovery_account or result.get('shortcode') != state['shortcode']
                    or result.get('comment_count') != 1 or not result.get('comment_id')
                    or not result.get('message_id') or not result.get('product_verified')
                    or not result.get('product_name') or not result.get('evidence_path')):
                raise ValueError('댓글·DM·확인 상품의 실제 근거가 부족합니다.')
            product_identity(result['product_url'])
            return dict(product=result, stage='affiliate', error='',comment_submit_called=True)

        operation = lambda: self._execute_effect(state, 'product_discovery',
            {'keyword': keyword, 'attempt_count': 1},
            lambda: browser.discover_product({**state, 'account':discovery_account}, keyword, self.store.root / task_id), accept)
        return self._start(task_id, operation) if background else operation()

    def issue_link(self, task_id, *, background=True):
        state = self._current(task_id, 'affiliate')
        if not self.credentials.status()['configured']:
            raise ValueError('설정에서 본인 쿠팡파트너스 API를 연결하세요.')
        browser = self._browser()
        self._preflight(browser, state['account'], ('coupang',))

        def operation():
            link = self.partners.issue(state['product']['product_url'])
            # Persist the successfully issued link even if landing observation
            # later fails. Never discard it and repeat Instagram discovery.
            folder = self.store.root / task_id
            folder.mkdir(exist_ok=True)
            (folder / 'issued-link.json').write_text(json.dumps(link, ensure_ascii=False, indent=2), 'utf-8')
            landing = browser.verify_link(link, folder)
            verify_product_match(link['original_url'], landing['url'])
            if landing.get('product_verified') is not True or not landing.get('evidence_path'):
                raise ValueError('발급 링크의 실제 상품 페이지 확인이 필요합니다.')
            return {**link, 'landing': landing, 'landing_verified': True, 'verified_at': time.time()}

        execute = lambda: self._execute_effect(state, 'affiliate_issue', {}, operation,
            lambda result: dict(affiliate=result, stage='caption', error=''))
        return self._start(task_id, execute) if background else execute()

    def prepare_caption(self, task_id, button_text):
        state = self._current(task_id, 'caption')
        _, script, _ = self._binding(task_id)
        link = state['affiliate']
        if link.get('landing_verified') is not True:
            raise ValueError('링크의 상품 연결 검증이 끝나지 않았습니다.')
        package = publishing_package(script['text'], state['product']['product_name'],
                                     button_text, link['affiliate_url'])
        # The button text must be an observed property, not a newly invented
        # efficacy claim. Product discovery records the visible page evidence.
        evidence = ' '.join([state['product']['product_name'], *state['product'].get('verified_features', [])])
        if button_text.strip() not in evidence:
            raise ValueError('버튼 문구는 확인된 제품명 또는 특징에서 선택하세요.')
        video, _, _ = self._binding(task_id)
        package = bind_package(package, state, video)
        return self.store.change(task_id, {'package': package, 'stage': 'littly', 'error': ''}, expected=state['revision'])

    def register_littly(self, task_id, *, background=True):
        state = self._current(task_id, 'littly')
        validate_package(state)
        browser = self._browser()
        self._preflight(browser, state['account'], ('littly',))

        operation = lambda: self._execute_effect(state, 'littly_create',
            {'post_mode': 'next_post'},
            lambda: browser.register_littly(self.store.get(task_id), self.store.root / task_id),
            lambda result: self._accept_littly(state, result))
        return self._start(task_id, operation) if background else operation()

    def _checked_package(self, state, *, require_cover=False):
        _, _, binding = self._binding(state['task_id'])
        current = self.store.get(state['task_id'])
        if binding != state['binding'] or current.get('package') != state.get('package'):
            raise MonetizationConflict('실행 중 영상·선택 대본·게시 패키지가 바뀌었습니다.')
        return validate_package(state, require_cover=require_cover)

    def _accept_littly(self, state, result):
        self._checked_package(state)
        package = state['package']
        checks = {'account': state['account'], 'post_mode': 'next_post', 'comment_condition': 'all',
                  'dm_message': package['dm_message'], 'button_text': package['button_text'],
                  'affiliate_url': package['affiliate_url'], 'reply_add_count': 2}
        if (any(result.get(key) != value for key, value in checks.items()) or not result.get('automation_id')
                or result.get('saved_verified') is not True or not result.get('evidence_path')):
            raise ValueError('리틀리 등록 결과 미확인: 실제 저장된 설정이 요청과 다릅니다.')
        return dict(littly=result, stage='awaiting_post', status='ready', error='', delivery_verified=False)

    def inspect_littly(self, task_id, automation_url):
        state = self.store.get(task_id)
        if (not state or state['stage'] != 'littly' or state['status'] != 'error'
                or not any(e['kind'] == 'littly_create' and e['status'] == 'unknown'
                           and e['id'] == state.get('effect_id') for e in self.store.effects(state))):
            raise MonetizationConflict('등록 결과가 불명확한 기존 리틀리 시도만 조회할 수 있습니다.')
        _, _, binding = self._binding(task_id)
        if state['binding'] != binding:
            raise MonetizationConflict('기존 리틀리 등록 시도와 영상·대본이 다릅니다.')
        validate_package(state)
        browser = self._browser()
        self._preflight(browser, state['account'], ('littly',))
        def inspect():
            try:
                result = browser.inspect_littly_registration(state, automation_url, self.store.root / task_id)
                changes = self._accept_littly(state, result)
                return self.store.resolve_effect(task_id, state['effect_id'], 'completed',
                    {**result, 'reconciled': True, 'original_outcome': 'unknown'}, changes,
                    reconcile=True, expected_revision=state['revision'])
            except Exception as exc:
                reason = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
                return self.store.change(task_id, {'littly_check': {'verified': False, 'reason': reason,
                    'at': time.time(), **self._error_evidence(exc)}}, expected=state['revision'])
        return self._start(task_id, inspect)

    def publish(self, task_id, *, background=True):
        """Explicit publication only; the automatic preparation loop stops first."""
        state = self._current(task_id, 'awaiting_post')
        package = validate_package(state, require_cover=True)
        if state.get('publication') or any(e['kind'] == 'instagram_publish' for e in self.store.effects(state)):
            raise MonetizationConflict('게시를 이미 시도했습니다. 실제 게시물 조회로 결과를 확인하세요.')
        browser = self._browser()
        self._preflight(browser, state['account'], ('instagram', 'littly'))

        def upload():
            effect_id = self.store.get(task_id)['effect_id']
            def progress(phase, details=None):
                self.store.publish_progress(task_id, effect_id, phase, details)
            self._checked_package(state, require_cover=True)
            return browser.publish_instagram(state, self.store.root / task_id, progress)

        def accept(receipt):
            self._checked_package(state, require_cover=True)
            if (receipt.get('submitted') is not True or receipt.get('account') != state['account']
                    or receipt.get('package_sha256') != package['package_sha256']
                    or receipt.get('automation_id') != state['littly']['automation_id']
                    or not receipt.get('evidence_path')):
                raise ValueError('인스타 게시 제출의 패키지·계정·화면 근거가 부족합니다.')
            return dict(publication={**receipt, 'phase': 'awaiting_confirmation',
                                     'updated': time.time(), 'media_verified': False}, error='')

        operation = lambda: self._execute_effect(state, 'instagram_publish',
            {'package_sha256': package['package_sha256'], 'automation_id': state['littly']['automation_id']},
            upload, accept)
        return self._start(task_id, operation) if background else operation()

    def run(self, task_id, account, keyword):
        state = self.prepare(task_id, account)
        if state['stage'] == 'awaiting_post':
            return {'accepted': False, 'task_id': task_id, 'status': 'awaiting_post'}
        if self.store.next_post_busy(state['account'], task_id):
            raise NextPostBusy('이 계정의 앞선 상품·다음 게시물 연결 확인 후 진행합니다.')
        status = self.connections()
        if not status['coupang']['configured'] or not status['coupang']['eligible']:
            raise ValueError('댓글 시도 전에 쿠팡파트너스 API 연결을 완료하세요.')
        browser = self._browser()
        self._preflight(browser, state.get('discovery_account',state['account']), ('instagram', 'coupang'))
        self._preflight(browser, state['account'], ('littly',))

        def advance():
            try:
                while True:
                    state = self.store.get(task_id)
                    if state['status'] != 'ready':
                        return
                    if state['stage'] == 'product':
                        self.discover_product(task_id, keyword, background=False)
                    elif state['stage'] == 'affiliate':
                        self.issue_link(task_id, background=False)
                    elif state['stage'] == 'caption':
                        choices = [state['product']['product_name'], *state['product'].get('verified_features', [])]
                        button = next((text for text in choices if text and len(text) <= 18), '')
                        self.prepare_caption(task_id, button)
                    elif state['stage'] == 'littly':
                        self.register_littly(task_id, background=False)
                    else:
                        return
            except (ValueError, RuntimeError) as exc:
                state = self.store.get(task_id)
                if state and state['status'] == 'ready':
                    status = 'waiting_slot' if isinstance(exc, NextPostBusy) else 'waiting_connections' if isinstance(exc, ConnectionsNotReady) else 'error'
                    self.store.change(task_id, {'status': status,
                                               'error': str(exc)}, expected=state['revision'])
        return self._start(task_id, advance)

    def inspect_post(self, task_id, post_url):
        state = self.store.get(task_id)
        # A lost submission response must still permit observation, never a
        # second upload. Other failed stages keep their original stop rules.
        recovering = (state and state['stage'] == 'awaiting_post' and state['status'] == 'error'
                      and any(e['kind'] == 'instagram_publish' and e['status'] in {'unknown', 'error'}
                              for e in self.store.effects(state)))
        if recovering:
            _, _, binding = self._binding(task_id)
            if state['binding'] != binding:
                raise MonetizationConflict('현재 영상·대본이 게시 시도와 다릅니다.')
            validate_package(state, require_cover=True)
        else:
            state = self._current(task_id, 'awaiting_post')
            if state.get('package', {}).get('publication_contract'):
                validate_package(state)
        from .monetization_browser import instagram_post_identity
        expected_post = instagram_post_identity(post_url)
        reported_url = state.get('publication', {}).get('post_url')
        if reported_url and instagram_post_identity(reported_url) != expected_post:
            raise ValueError('업로드 결과에 표시된 게시물과 확인할 주소가 다릅니다.')
        browser = self._browser()
        self._preflight(browser, state['account'], ('instagram', 'littly'))
        def inspect():
            try:
                receipt = browser.inspect_post_connection(state, post_url, self.store.root / task_id)
                if (receipt.get('verified') is not True or receipt.get('account') != state['account']
                        or receipt.get('post_shortcode') != expected_post or receipt.get('post_id') != expected_post
                        or receipt.get('automation_id') != state['littly']['automation_id']
                        or receipt.get('affiliate_url') != state['package']['affiliate_url']
                        or not receipt.get('evidence_path') or not receipt.get('post_evidence_path')):
                    raise ValueError('실제 게시물·계정·상품 링크의 연결 근거가 부족합니다.')
                return self.store.associate_post(state, receipt)
            except Exception as exc:
                reason = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
                return self.store.change(task_id, {'post_check': {'verified': False, 'reason': reason,
                    'at': time.time(), **self._error_evidence(exc)}}, expected=state['revision'])
        return self._start(task_id, inspect)

    def inspect_delivery(self, task_id):
        state = self._current(task_id, 'awaiting_delivery')
        browser = self._browser()
        self._preflight(browser, state['account'], ('littly',))
        def inspect():
            try:
                receipt = browser.inspect_delivery(state, self.store.root / task_id)
                if (receipt.get('verified') is not True or receipt.get('account') != state['account']
                        or receipt.get('automation_id') != state['littly']['automation_id']
                        or receipt.get('post_shortcode') != state['post_connection']['post_shortcode']
                        or receipt.get('affiliate_url') != state['package']['affiliate_url']
                        or not receipt.get('message_ids') or not receipt.get('evidence_path')):
                    raise ValueError('실제 댓글·DM 전달 성공의 결속된 발송 근거가 부족합니다.')
                return self.store.change(task_id, {'delivery': receipt, 'delivery_verified': True, 'stage': 'completed'}, expected=state['revision'])
            except Exception as exc:
                reason = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
                return self.store.change(task_id, {'delivery_check': {'verified': False, 'reason': reason,
                    'at': time.time(), **self._error_evidence(exc)}}, expected=state['revision'])
        return self._start(task_id, inspect)
