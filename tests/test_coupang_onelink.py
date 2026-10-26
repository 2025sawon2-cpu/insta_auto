import json
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost.coupang_onelink import (parse_storefront, normalize_one_link, link_identity,
                                     storefront_url, choose_item, verify_landing, find_one_link)
from hotpost.post_preparation import PostPreparation, DraftConflict
from hotpost.post_coupang_link import start, status

STORE = 'https://influencers.coupang.com/s/ourstore'
PRODUCT = 'https://www.coupang.com/vp/products/123?itemId=456&vendorItemId=789'
LINK = 'https://link.coupang.com/re/AFFSDP?lptag=AFTEST&pageKey=123&itemId=456&vendorItemId=789&portal=CREATOR'
ITEM = dict(product_id='123', item_id='456', vendor_item_id='789', title='브랜드 침대 난방텐트', one_link=LINK)


def source(item=ITEM):
    return json.dumps(dict(productId=int(item['product_id']), itemId=int(item['item_id']),
        vendorItemId=int(item['vendor_item_id']), landingUrl=item['one_link'], title=item['title']),
        ensure_ascii=False, separators=(',', ':')).replace('&', r'\u0026')


def test_storefront_extracts_normal_and_nextjs_escaped_source_and_preserves_options():
    for raw in (source(), source().replace('"', r'\"'), json.dumps(source(), ensure_ascii=False)):
        assert parse_storefront(raw) == [ITEM]
    assert normalize_one_link(LINK.replace('&', r'\u0026') + '\\') == LINK
    assert choose_item([ITEM], '난방텐트', PRODUCT) == ITEM
    assert choose_item([ITEM], '난방텐트', PRODUCT.replace('456', '999')) is None
    assert choose_item([ITEM], '다른 제품') is None
    with pytest.raises(ValueError, match='여러 상품'):
        choose_item([ITEM, dict(ITEM, item_id='457')], '난방텐트')


def test_corrupt_or_foreign_affiliate_records_cannot_be_used():
    assert parse_storefront(source(dict(ITEM, item_id='999', one_link=LINK))) == []
    for link in [LINK.replace('link.coupang.com', 'evil.example'), LINK.replace('portal=CREATOR', 'portal=OTHER'),
                 LINK + '&itemId=999', 'https://link.coupang.com/a/short', LINK.replace('itemId=456', 'itemId='),
                 LINK.replace('https://', 'http://')]:
        with pytest.raises(ValueError):
            link_identity(link)


@pytest.mark.parametrize('url', ['http://influencers.coupang.com/s/ourstore', 'https://127.0.0.1/s/a',
    'https://influencers.coupang.com.evil.example/s/a', 'https://user@influencers.coupang.com/s/a',
    'https://influencers.coupang.com:443/s/a', 'https://influencers.coupang.com/s/a?url=http://127.0.0.1',
    'https://influencers.coupang.com/storefront'])
def test_store_fetch_is_limited_to_public_store_paths(url):
    with pytest.raises(ValueError):
        storefront_url(url)


class Title:
    first = property(lambda self: self)
    def count(self): return 0
    def wait_for(self, **kwargs): pass
    def inner_text(self): return ITEM['title']


class Page:
    def __init__(self, landing): self.landing = landing; self.url = STORE
    def goto(self, url, **kwargs): self.url = self.landing
    def locator(self, selector): return Title()
    def title(self): return ITEM['title']
    def wait_for_url(self, *args, **kwargs): pass


def test_landing_checks_actual_product_and_both_options():
    assert verify_landing(Page(PRODUCT), ITEM)['landing_verified'] is True
    for url in [PRODUCT.replace('/123', '/124'), PRODUCT.replace('456', '457'), PRODUCT.replace('789', '790'),
                'https://www.coupang.com/vp/products/123', STORE]:
        with pytest.raises(ValueError):
            verify_landing(Page(url), ITEM)


def test_lookup_only_does_not_launch_or_register_on_missing_item(tmp_path, monkeypatch):
    monkeypatch.setattr('hotpost.coupang_onelink.fetch_storefront', lambda _: [])
    monkeypatch.setattr('hotpost.coupang_onelink.register_product', lambda *_: pytest.fail('registration'))
    with pytest.raises(ValueError, match='찾지 못했습니다'):
        find_one_link(Settings(data_dir=tmp_path), dict(product_name='난방텐트', storefront_url=STORE, register=False))


@pytest.mark.parametrize('register', [False, True])
def test_complete_finder_attaches_only_and_registration_requires_explicit_option(tmp_path, monkeypatch, register):
    page = Page(PRODUCT)
    reads, mutations, attached = [], [], []
    def fetch(url):
        reads.append(url)
        if register and len(reads) == 1:
            return [dict(ITEM, item_id='999', title='다른 상품')]
        return [ITEM]
    @contextmanager
    def playwright():
        yield SimpleNamespace()
    @contextmanager
    def lease(settings):
        yield
    def attach(pw, settings):
        attached.append(settings.source_browser_existing_window_only)
        return SimpleNamespace()
    monkeypatch.setattr('hotpost.coupang_onelink.fetch_storefront', fetch)
    monkeypatch.setattr('hotpost.coupang_onelink.register_product', lambda *args: mutations.append(args))
    monkeypatch.setattr('playwright.sync_api.sync_playwright', playwright)
    monkeypatch.setattr('hotpost.source_browser_runtime.attach_browser', attach)
    monkeypatch.setattr('hotpost.source_browser_runtime.browser_lease', lease)
    monkeypatch.setattr('hotpost.source_browser_runtime._bound_inventory',
                        lambda *_: ({'window_id': 1}, [{'page': page, 'window_id': 1}]))
    result = find_one_link(Settings(data_dir=tmp_path), dict(product_name='난방텐트', storefront_url=STORE,
                                                            product_url=PRODUCT, register=register))
    assert result['landing_verified'] and result['one_link'] == LINK
    assert attached == [True]
    assert len(mutations) == int(register)
    assert reads == [STORE] * (2 if register else 1)


@pytest.fixture
def service(tmp_path, monkeypatch):
    service = PostPreparation(Settings(data_dir=tmp_path))
    monkeypatch.setattr(service, 'source', lambda _: {'media': {'final': tmp_path / 'final.mp4'}})
    return service


def request():
    return dict(revision=0, product_name='난방텐트', storefront_url=STORE, product_url=PRODUCT, register=False)


def wait_job(service, code):
    limit = time.monotonic() + 3
    while time.monotonic() < limit:
        value = status(service, code)
        if value['status'] != 'running': return value
        time.sleep(.01)
    pytest.fail('worker did not return')


def test_attempt_is_durable_prevents_parallel_registration_and_never_changes_draft(service):
    gate, entered = threading.Event(), threading.Event()
    def finder(settings, payload):
        entered.set(); gate.wait(2)
        return dict(ITEM, landing_verified=True, status='one_link_ready', final_url=PRODUCT)
    first = start(service, 'post', request(), finder=finder)
    try:
        assert entered.wait(1)
        assert status(service, 'post')['id'] == first['id']
        with pytest.raises(DraftConflict): start(service, 'another', request(), finder=finder)
    finally:
        gate.set()
    assert wait_job(service, 'post')['status'] == 'completed'
    with service.connect() as db:
        assert db.execute('SELECT count(*) FROM drafts').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM coupang_link_jobs').fetchone()[0] == 1
    reopened = PostPreparation(service.settings)
    assert status(reopened, 'post')['result']['one_link'] == LINK


@pytest.mark.parametrize('result', [dict(ITEM, status='short_url_fallback', landing_verified=True),
    dict(ITEM, status='one_link_ready', landing_verified=False),
    dict(ITEM, status='one_link_ready', landing_verified=True, one_link='https://link.coupang.com/a/short')])
def test_upstream_fallback_and_metadata_only_success_are_rejected(service, result):
    start(service, 'post', request(), finder=lambda *_: result)
    assert wait_job(service, 'post')['status'] == 'failed'
    assert status(service, 'post')['result'] == {}


def test_stale_draft_and_unfinished_video_do_not_submit(service, monkeypatch):
    with service.connect() as db:
        db.execute('INSERT INTO drafts VALUES (?,?,?,?)', ('post', 2, '{}', 1))
    with pytest.raises(DraftConflict): start(service, 'post', request())
    monkeypatch.setattr(service, 'source', lambda _: {'media': {'final': None}})
    with pytest.raises(ValueError, match='완성 영상'): start(service, 'another', request())
    assert status(service, 'post')['status'] == 'idle'


def test_crashed_attempt_is_reported_without_reexecution_or_draft_write(service, monkeypatch):
    with service.connect() as db:
        db.execute('INSERT INTO coupang_link_jobs VALUES (?,?,?,?,?,?,?,?,?)',
                   ('old', 'post', 'running', json.dumps(request()), '{}', 'pending', 1, 99999999, 0))
    monkeypatch.setattr('hotpost.post_coupang_link.find_one_link', lambda *_: pytest.fail('automatic restart'))
    assert status(service, 'post')['status'] == 'interrupted'
    assert status(PostPreparation(service.settings), 'post')['status'] == 'interrupted'
    with service.connect() as db:
        assert db.execute('SELECT status FROM coupang_link_jobs').fetchone()[0] == 'running'
