"""Post-video side effects must survive races, interruptions and bad links."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import hmac
import json
from types import SimpleNamespace
import uuid

import pytest

from hotpost.coupang_partners import (authorization, PartnerCredentials, CoupangPartners,
                                     product_identity, verify_product_match)
from hotpost.monetization_store import MonetizationStore, MonetizationConflict, effect_lease
from hotpost.post_publish import publishing_package, DISCLOSURE, CTA


def test_explicit_unstarted_account_correction_preserves_binding_and_audit(tmp_path):
    store = MonetizationStore(tmp_path)
    original = store.prepare('task', 'mr.salrim', 'Reference', {'sha':'actual-video'})
    changed = store.rebind_unstarted_account('task', '@ggul_dol2', expected=original['revision'])
    assert changed['account'] == 'ggul_dol2'
    assert changed['binding'] == original['binding'] and changed['created'] == original['created']
    assert store.effects(original) == [] and store.effects(changed) == []
    assert changed['revision'] == original['revision'] + 1
    with store.connect() as db:
        event = db.execute("SELECT details FROM events WHERE kind='account_rebound'").fetchone()
    assert json.loads(event[0]) == {'previous_account':'mr.salrim','account':'ggul_dol2'}
    with pytest.raises(MonetizationConflict):
        store.rebind_unstarted_account('task', 'third', expected=original['revision'])


@pytest.mark.parametrize('attempted_account', ['mr.salrim', 'ggul_dol2'])
def test_account_correction_cannot_erase_prior_reference_attempt(tmp_path, attempted_account):
    store = MonetizationStore(tmp_path)
    target = store.prepare('task', 'mr.salrim', 'Reference', {})
    attempted = store.prepare('earlier-task', attempted_account, 'Reference', {})
    store.reserve_effect(attempted, 'product_discovery', {'keyword':'나도'})
    with pytest.raises(MonetizationConflict):
        store.rebind_unstarted_account('task', 'ggul_dol2', expected=target['revision'])
    assert store.get('task') == target and len(store.effects(attempted)) == 1


def test_account_correction_cannot_move_reserved_next_post(tmp_path):
    store = MonetizationStore(tmp_path)
    state = store.prepare('task', 'mr.salrim', 'Reference', {})
    store.reserve_next_post(state)
    with pytest.raises(MonetizationConflict):
        store.rebind_unstarted_account('task', 'ggul_dol2', expected=state['revision'])


def test_concurrent_and_new_task_ids_cannot_repeat_same_reference_request(tmp_path):
    store = MonetizationStore(tmp_path)
    a = store.prepare('task-a', 'MyAccount', 'Ref123', {'sha': 'a'})
    b = store.prepare('task-b', ' @myaccount ', 'Ref123', {'sha': 'b'})
    def reserve(state):
        try:
            return store.reserve_effect(state, 'product_discovery', {'keyword': '나도'})
        except MonetizationConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, (a, b)))
    assert sum(value is not None for value in results) == 1
    restarted = MonetizationStore(tmp_path)
    with pytest.raises(MonetizationConflict):
        restarted.reserve_effect(a, 'product_discovery', {})


def test_lease_liveness_and_crash_recovery_never_repost(tmp_path):
    store = MonetizationStore(tmp_path)
    state = store.prepare('task', 'account', 'Reference', {})
    effect = uuid.uuid4().hex
    with effect_lease(tmp_path, effect):
        store.reserve_effect(state, 'product_discovery', {'keyword': '나도'}, effect_id=effect)
        store.change('task', {'effect_id': effect, 'status': 'running'})
        store.recover_abandoned()
        assert store.get('task')['status'] == 'running'
        assert store.effects(state)[0]['status'] == 'dispatching'
    MonetizationStore(tmp_path).recover_abandoned()
    assert store.get('task')['status'] == 'error'
    assert store.effects(state)[0]['status'] == 'unknown'
    assert store.effects(state)[0]['details']['keyword'] == '나도'
    with pytest.raises(MonetizationConflict):
        store.reserve_effect(state, 'product_discovery', {})


def test_only_one_next_post_per_account_even_after_restart(tmp_path):
    store = MonetizationStore(tmp_path)
    a = store.prepare('a', 'Account', 'one', {})
    b = store.prepare('b', '@account', 'two', {})
    store.reserve_next_post(a)
    with pytest.raises(MonetizationConflict):
        MonetizationStore(tmp_path).reserve_next_post(b)
    store.confirm_next_post(a, {'automation_id': 'automation-1'})
    with pytest.raises(ValueError):
        store.associate_post(a, {'verified': True, 'post_id': 'post', 'automation_id': 'wrong'})
    store.associate_post(a, {'verified': True, 'post_id': 'post', 'automation_id': 'automation-1'})
    store.reserve_next_post(b)


@pytest.mark.parametrize('url', [
    'http://www.coupang.com/vp/products/1', 'https://www.coupang.com.evil.org/vp/products/1',
    'https://127.0.0.1/vp/products/1', 'https://user@www.coupang.com/vp/products/1',
    'https://www.coupang.com:443/vp/products/1', 'https://www.coupang.com/vp/products/1?itemId=x'])
def test_product_identity_rejects_wrong_hosts_and_ambiguous_options(url):
    with pytest.raises(ValueError):
        product_identity(url)


def test_landing_verification_does_not_drop_option_ids():
    original = 'https://www.coupang.com/vp/products/123?itemId=456&vendorItemId=789'
    assert verify_product_match(original, original)['vendor_item_id'] == '789'
    for bad in ['https://www.coupang.com/vp/products/123',
                'https://www.coupang.com/vp/products/123?itemId=457&vendorItemId=789']:
        with pytest.raises(ValueError):
            verify_product_match(original, bad)


def test_api_signing_and_key_redaction_and_response_correlation(tmp_path):
    credentials = PartnerCredentials(tmp_path)
    public = credentials.save(dict(access_key='access', secret_key='super-secret',
                                   account_ref='mine', eligible=True))
    assert 'super-secret' not in json.dumps(public)
    assert 'access_key' not in public and 'secret_key' not in public
    moment = datetime(2026, 10, 16, 1, 2, 3, tzinfo=timezone.utc)
    expected = hmac.new(b'super-secret', b'261016T010203ZPOST/path', hashlib.sha256).hexdigest()
    assert authorization('POST', '/path', 'access', 'super-secret', now=moment).endswith(expected)
    url = 'https://www.coupang.com/vp/products/123?itemId=456'
    requests = []
    def transport(request):
        requests.append(request)
        return {'rCode': '0', 'data': [{'originalUrl': url, 'shortenUrl': 'https://link.coupang.com/a/abc123'}]}
    result = CoupangPartners(credentials, transport).issue(url)
    assert result['api_issued'] is True and result['landing_verified'] is False
    assert json.loads(requests[0].data) == {'coupangUrls': [url]}
    bad = lambda _: {'rCode': '0', 'data': [{'originalUrl': url + '9', 'shortenUrl': 'https://link.coupang.com/a/abc123'}]}
    with pytest.raises(ValueError):
        CoupangPartners(credentials, bad).issue(url)


def test_caption_uses_selected_script_and_exact_dm_without_extra_claims():
    script = '작은 손난로 안에 거울이 있어요. ' + CTA
    package = publishing_package(script, '키티 손난로', '거울 달린 손난로', 'https://link.coupang.com/a/abc')
    assert package['caption'] == DISCLOSURE + '\n\n' + script
    assert package['dm_message'] == DISCLOSURE + '\n키티 손난로\n' + '👇' * 8
    assert package['caption'].count(CTA) == 1
    assert package['comment_condition'] == 'all'
    assert package['reply_add_count'] == 2
    with pytest.raises(ValueError):
        publishing_package(script, '키티 손난로', '가' * 19, 'https://link.coupang.com/a/abc')


def followup_fixture(tmp_path, *, fail_dm=False):
    from hotpost.config import Settings
    from hotpost.monetization import Monetization
    import copy
    video = tmp_path / 'video.mp4'; video.write_bytes(b'preserved-video')
    plan = tmp_path / 'plan.json'; plan.write_text('{}', 'utf-8')
    state = dict(id='work-1', status='completed', shortcode='Reference', edit_id='edit', script_id='script',
        edits=[dict(id='edit', export_verified=True, export_path=str(video), plan_path=str(plan), script_id='script')],
        scripts=[dict(id='script', text='거울이 있는 손난로예요. ' + CTA)])
    calls = []
    url = 'https://www.coupang.com/vp/products/123?itemId=456&vendorItemId=789'
    class Browser:
        def preflight(self, account, providers): calls.append(('preflight', tuple(providers)))
        def discover_product(self, current, keyword, folder):
            calls.append(('comment', keyword))
            if fail_dm: raise RuntimeError('댓글 전송 결과 불명확')
            return dict(account=current['account'], shortcode=current['shortcode'], comment_count=1,
                comment_id='ui-receipt:1', message_id='dm-1', product_verified=True, product_name='거울 손난로',
                product_url=url, verified_features=['거울'], evidence_path='fixture-ui.json')
        def verify_link(self, link, folder):
            calls.append(('landing', link['affiliate_url']))
            return dict(url=url, product_verified=True, evidence_path='fixture-landing.json')
        def register_littly(self, current, folder):
            calls.append(('littly', current['package']['affiliate_url']))
            return {**current['package'], 'account': current['account'], 'automation_id': 'automation-1',
                    'saved_verified': True, 'evidence_path': 'fixture-littly.json',
                    'automation_url': 'https://app.litt.ly/automations/automation-1'}
        def inspect_post_connection(self, current, post_url, folder):
            calls.append(('inspect-post', post_url))
            return dict(verified=True, account=current['account'], post_id='OurPost', post_shortcode='OurPost',
                post_url=post_url, automation_id=current['littly']['automation_id'],
                affiliate_url=current['package']['affiliate_url'], evidence_path='fixture-connected.json',
                post_evidence_path='fixture-owned-post.json')
        def inspect_delivery(self, current, folder):
            calls.append(('inspect-delivery', current['post_connection']['post_shortcode']))
            return dict(verified=True, account=current['account'], automation_id=current['littly']['automation_id'],
                post_shortcode=current['post_connection']['post_shortcode'], affiliate_url=current['package']['affiliate_url'],
                message_ids=['delivered-message'], evidence_path='fixture-delivered.json')
    service = Monetization(Settings(data_dir=tmp_path), lambda _: copy.deepcopy(state),
        browser_factory=lambda _: Browser())
    service.credentials.save(dict(access_key='test-key', secret_key='test-secret', account_ref='mine', eligible=True))
    def transport(request):
        calls.append(('api', request.full_url))
        return {'rCode': '0', 'data': [dict(originalUrl=url, shortenUrl='https://link.coupang.com/a/abc')]}
    service.partners = CoupangPartners(service.credentials, transport)
    return service, calls, state, video


def test_orchestrator_completes_order_and_preserves_video_without_live_account_calls(tmp_path):
    service, calls, original, video = followup_fixture(tmp_path)
    before = json.dumps(original, sort_keys=True)
    service.run('work-1', 'OurAccount', '나도')
    service.close()
    result = service.get('work-1')
    assert result['stage'] == 'awaiting_post' and result['status'] == 'ready'
    assert result['delivery_verified'] is False
    assert [kind for kind, _ in calls if kind != 'preflight'] == ['comment', 'api', 'landing', 'littly']
    assert all(effect['status'] == 'completed' for effect in result['effects'])
    assert result['package']['caption'].endswith(CTA)
    assert before == json.dumps(original, sort_keys=True) and video.read_bytes() == b'preserved-video'
    assert 'test-secret' not in json.dumps(result, ensure_ascii=False)
    service.run('work-1', 'OurAccount', '나도')
    service.close()
    assert len([row for row in calls if row[0] == 'comment']) == 1


def test_uncertain_comment_is_error_and_restart_does_not_retry(tmp_path):
    service, calls, _, video = followup_fixture(tmp_path, fail_dm=True)
    service.run('work-1', 'OurAccount', '나도'); service.close()
    assert service.get('work-1')['status'] == 'error'
    assert service.get('work-1')['stage'] == 'product'
    service.run('work-1', 'ouraccount', '나도'); service.close()
    assert len([row for row in calls if row[0] == 'comment']) == 1
    assert not [row for row in calls if row[0] in {'api', 'littly'}]
    assert video.read_bytes() == b'preserved-video'


def test_littly_slot_and_effect_reservation_rollback_together(tmp_path):
    store = MonetizationStore(tmp_path)
    state = store.prepare('task', 'account', 'Reference', {})
    effect = store.reserve_effect(state, 'littly_create', {})
    running = store.get('task')
    with pytest.raises(MonetizationConflict):
        store.reserve_effect(running, 'littly_create', {})
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM next_post_slots').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM effects').fetchone()[0] == 1
    store.resolve_effect('task', effect, 'error', {'reason': 'unknown click'}, {'error': 'unknown click'})
    restarted = MonetizationStore(tmp_path)
    restarted.recover_abandoned()
    assert restarted.get('task')['status'] == 'error'
    assert restarted.effects(state)[0]['status'] == 'error'


def test_littly_atomic_accept_rolls_back_when_slot_owner_is_wrong(tmp_path):
    store = MonetizationStore(tmp_path)
    state = store.prepare('task', 'account', 'Reference', {})
    effect = store.reserve_effect(state, 'littly_create', {})
    with store.connect() as db:
        db.execute('UPDATE next_post_slots SET task_id=?', ('different-task',))
    with pytest.raises(MonetizationConflict):
        store.resolve_effect('task', effect, 'completed', {'automation_id': 'automation'}, {'stage': 'awaiting_post'})
    assert store.get('task')['status'] == 'running'
    assert store.effects(state)[0]['status'] == 'dispatching'


def test_old_dm_relative_time_change_is_not_a_new_follow_instruction():
    from hotpost.monetization_browser import message_signature, new_received_message
    old = dict(stable_id='old-platform-message', digest=message_signature('팔로우 확인\n2분 전', []))
    changed = dict(stable_id='old-platform-message', digest=message_signature('팔로우 확인\n3분 전', []))
    assert old['digest'] == changed['digest']
    assert not new_received_message(changed, [old], 100)
    # Even a remounted element ID cannot make identical old content new.
    changed['stable_id'] = 'remounted-react-element'
    assert not new_received_message(changed, [old], 100)
    assert not new_received_message(dict(stable_id=None, digest='different', date=None), [old], 100)
    assert new_received_message(dict(stable_id=None, digest='new-content', date='2026-10-16T00:00:00Z'), [old], 100)
    assert not new_received_message(dict(stable_id='late-old-id', digest='old-content', date='2020-01-01T00:00:00Z'), [], 1792000000)
    assert not new_received_message(dict(stable_id='unseen-id', digest='unknown-time', date=None), [], 100)


def test_terminal_pre_littly_error_releases_only_workflow_slot(tmp_path):
    store = MonetizationStore(tmp_path)
    state = store.prepare('task', 'account', 'Reference', {})
    effect = store.reserve_effect(state, 'product_discovery', {})
    state = store.resolve_effect('task', effect, 'completed', {}, {'stage': 'affiliate'})
    effect = store.reserve_effect(state, 'affiliate_issue', {})
    store.resolve_effect('task', effect, 'error', {'reason': 'API error'}, {'error': 'API error'})
    assert not store.next_post_busy('account', 'another-task')
    assert len(store.effects(state)) == 2


def test_interrupted_discovery_releases_workflow_without_allowing_same_reference_retry(tmp_path):
    store = MonetizationStore(tmp_path)
    state = store.prepare('task', 'account', 'Reference', {})
    store.reserve_effect(state, 'product_discovery', {})
    store.recover_abandoned()
    assert not store.next_post_busy('account', 'another-task')
    with pytest.raises(MonetizationConflict):
        store.reserve_effect(store.get('task'), 'product_discovery', {})


def test_post_and_delivery_inspection_do_not_send_new_comments_or_dm(tmp_path):
    service, calls, _, _ = followup_fixture(tmp_path)
    service.run('work-1', 'OurAccount', '나도'); service.close()
    assert service.store.next_post_busy('ouraccount', 'another-task')
    service.inspect_post('work-1', 'https://www.instagram.com/reel/OurPost/'); service.close()
    state = service.get('work-1')
    assert state['stage'] == 'awaiting_delivery' and state['delivery_verified'] is False
    assert not service.store.next_post_busy('ouraccount', 'another-task')
    service.inspect_delivery('work-1'); service.close()
    assert service.get('work-1')['stage'] == 'completed'
    assert service.get('work-1')['delivery_verified'] is True
    assert len([row for row in calls if row[0] == 'comment']) == 1
    assert len([row for row in calls if row[0] == 'littly']) == 1


def test_unverified_post_boolean_cannot_release_reserved_next_post(tmp_path):
    service, calls, _, _ = followup_fixture(tmp_path)
    service.run('work-1', 'OurAccount', '나도'); service.close()
    original = service._browser()
    original.inspect_post_connection = lambda *_: {'verified': True}
    service.browser_factory = lambda _: original
    service.inspect_post('work-1', 'https://www.instagram.com/reel/OurPost/'); service.close()
    state = service.get('work-1')
    assert state['stage'] == 'awaiting_post' and state['post_check']['verified'] is False
    assert service.store.next_post_busy('ouraccount', 'another-task')


@pytest.mark.parametrize('url', ['https://instagram.com.evil.com/reel/OurPost/',
    'http://www.instagram.com/reel/OurPost/', 'https://user@www.instagram.com/reel/OurPost/',
    'https://www.instagram.com/direct/inbox/'])
def test_published_post_check_rejects_wrong_destinations(url):
    from hotpost.monetization_browser import instagram_post_identity
    with pytest.raises(ValueError): instagram_post_identity(url)


def test_actual_delivery_status_column_not_success_word_or_zero_count_summary():
    from hotpost.monetization_browser import delivery_succeeded
    assert delivery_succeeded(['게시물', '발송 상태', '메시지'], ['OurPost', '발송 성공', 'product link'])
    assert not delivery_succeeded(['게시물', '상태'], ['OurPost', '발송 성공: 0건 / 발송 실패: 1건'])
    assert not delivery_succeeded(['상태', '메시지'], ['발송 실패', '발송 성공'])
    assert not delivery_succeeded(['상태', '메시지'], ['대기 중', '발송 성공'])
    assert not delivery_succeeded(['메시지'], ['발송 성공'])
    assert not delivery_succeeded(['상태', '상태'], ['발송 성공', '발송 성공'])


def test_observed_product_link_supports_link_page_and_instagram_wrapper_only_https():
    from hotpost.monetization_browser import observed_product_link
    from urllib.parse import quote
    target = 'https://litt.ly/observed-product'
    assert observed_product_link(target) == target
    assert observed_product_link('https://l.instagram.com/?u=' + quote(target, safe='')) == target
    for bad in ['javascript:alert(1)', 'http://www.coupang.com/vp/products/1',
                'http://l.instagram.com/?u=' + quote(target, safe=''),
                'https://127.0.0.1/private', 'https://localhost/admin', 'https://device.local/',
                'https://user:password@www.coupang.com/', 'https://10.0.0.1/',
                'https://www.instagram.com/creator/',
                'https://l.instagram.com/?u=https%3A%2F%2Flocalhost%2F']:
        assert observed_product_link(bad) is None


def test_same_product_link_label_cannot_pick_different_option_by_index():
    from hotpost.monetization_browser import ambiguous_product_candidates
    a = {'text': '키티 손난로', 'url': 'https://www.coupang.com/vp/products/123?itemId=111'}
    b = {'text': '키티 손난로', 'url': 'https://www.coupang.com/vp/products/123?itemId=222'}
    assert ambiguous_product_candidates([a, b])
    assert not ambiguous_product_candidates([a, {**a, 'url': a['url'] + '&tracking=other'}])


@pytest.mark.parametrize('screenshot_fails', [False, True])
def test_failed_browser_session_preserves_original_error_and_only_current_page(tmp_path, monkeypatch, screenshot_fails):
    from contextlib import nullcontext
    from pathlib import Path
    from hotpost.config import Settings
    from hotpost import monetization_browser as ui, source_browser_runtime as runtime
    import playwright.sync_api
    monkeypatch.setattr(playwright.sync_api, 'sync_playwright', lambda: nullcontext(object()))
    monkeypatch.setattr(runtime, 'browser_lease', lambda _: nullcontext())
    monkeypatch.setattr(runtime, 'attach_browser', lambda *_: object())
    monkeypatch.setattr(ui, 'request_pause', lambda: None)
    captures = []
    class Page:
        def __init__(self, url): self.url = url
        def goto(self, url, **_): self.url = url
        def screenshot(self, path, **_):
            captures.append(self.url)
            if screenshot_fails: raise RuntimeError('screenshot unavailable')
            Path(path).write_bytes(b'fixture-png')
    browser = ui.MonetizationBrowser(Settings(data_dir=tmp_path))
    page = Page('https://www.instagram.com/direct/inbox/')
    unrelated = Page('https://unrelated.example/private')
    failure = ValueError('product access denied')
    with pytest.raises(ValueError) as caught:
        with browser.session(tmp_path):
            browser.navigate(page, 'https://www.coupang.com/vp/products/123')
            if not screenshot_fails:
                before_path = browser.capture(page, tmp_path, 'same-step')
            raise failure
    assert caught.value is failure
    receipt_path = Path(failure.monetization_evidence_path)
    receipt = json.loads(receipt_path.read_text('utf-8'))
    assert captures == [page.url] * (1 if screenshot_fails else 2) and unrelated.url not in captures
    assert receipt['url'] == page.url and receipt['error_type'] == 'ValueError'
    assert bool(receipt['screenshot']) is not screenshot_fails
    if screenshot_fails: assert receipt['screenshot_error'] == 'RuntimeError'
    else:
        assert receipt['previous_evidence_path'] == before_path
        before_bytes = Path(before_path).read_bytes()
        with browser.session(tmp_path):
            next_path = browser.capture(page, tmp_path, 'same-step')
        assert before_path != next_path and Path(before_path).read_bytes() == before_bytes
    previous = receipt_path.read_bytes()
    # A session which has not touched any page must not reuse the old page.
    second = ValueError('no page selected')
    with pytest.raises(ValueError):
        with browser.session(tmp_path): raise second
    assert not hasattr(second, 'monetization_evidence_path')
    assert receipt_path.read_bytes() == previous and len(captures) == (1 if screenshot_fails else 3)


def test_effect_error_keeps_attempt_details_and_exact_exception_evidence(tmp_path):
    service, calls, _, _ = followup_fixture(tmp_path)
    state = service.prepare('work-1', 'OurAccount')
    evidence = tmp_path / 'failure.json'
    evidence.write_text('{"step":"error-fixture"}', 'utf-8')
    failure = ValueError('DM wait expired')
    failure.monetization_evidence_path = str(evidence)
    def fail():
        calls.append(('comment', '나도'))
        raise failure
    result = service._execute_effect(state, 'product_discovery', {'keyword': '나도', 'attempt_count': 1}, fail, lambda _: {})
    assert result['error_evidence_path'] == str(evidence)
    effect = result['effects'][0]
    assert effect['details']['error_evidence_path'] == str(evidence)
    assert effect['details']['keyword'] == '나도' and effect['details']['attempt_count'] == 1
    assert service._error_evidence(ValueError('another failure')) == {}
    service.store.recover_abandoned()
    with pytest.raises(MonetizationConflict): service.discover_product('work-1', '나도', background=False)
    assert calls == [('comment', '나도')]
    service.close()


def test_playwright_inspection_timeout_keeps_evidence_and_read_only_retry(tmp_path):
    from playwright.sync_api import TimeoutError as BrowserTimeout
    service, calls, _, _ = followup_fixture(tmp_path)
    service.run('work-1', 'OurAccount', '나도'); service.close()
    browser = service._browser()
    evidence = str(tmp_path / 'current-timeout.json')
    def fail(*_):
        exc = BrowserTimeout('fixture timeout')
        exc.monetization_evidence_path = evidence
        raise exc
    browser.inspect_post_connection = fail
    service.browser_factory = lambda _: browser
    service.inspect_post('work-1', 'https://www.instagram.com/reel/OurPost/'); service.close()
    state = service.get('work-1')
    assert state['status'] == 'ready' and state['stage'] == 'awaiting_post'
    assert state['post_check']['error_evidence_path'] == evidence
    assert state['post_check']['verified'] is False
    assert service.store.next_post_busy('ouraccount', 'another-task')
    # Read-only checks can run again, without creating another automation.
    service.inspect_post('work-1', 'https://www.instagram.com/reel/OurPost/'); service.close()
    assert len([row for row in calls if row[0] == 'littly']) == 1
