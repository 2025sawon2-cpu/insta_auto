"""Explicit publication One-Link lookup, adapted from coupang-onelink-finder.

Source: 2025sawon2-cpu/coupang-onelink-finder @ 5cea0dc1f7811774cb736058b3111c1e717785f4.
Storefront landingUrl extraction and escaped ampersand normalization are reused.
No Chrome launch, login, credential import, short-link fallback or metadata-only
landing verification. Store registration is a separate, explicit option.
"""
from __future__ import annotations

from dataclasses import replace
import html
import json
import re
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .coupang_partners import product_identity, verify_product_match


def normalize_one_link(value):
    value = re.sub(r'\\+u0026', '&', html.unescape(str(value)))
    value = re.sub(r'\\+/', '/', value)
    return re.sub(r'(?:%5C|\\)+$', '', value).strip('\'" ')


def storefront_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.netloc != 'influencers.coupang.com'
            or not re.fullmatch(r'/s/[A-Za-z0-9_-]+/?', parsed.path)
            or parsed.query or parsed.fragment):
        raise ValueError('내 쿠팡 인플루언서 스토어 HTTPS 주소를 입력하세요.')
    return parsed.geturl()


def link_identity(value):
    parsed = urlsplit(normalize_one_link(value))
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (parsed.scheme != 'https' or parsed.netloc != 'link.coupang.com'
            or parsed.path != '/re/AFFSDP' or parsed.fragment
            or any(len(values) != 1 for values in query.values())
            or query.get('portal') != ['CREATOR'] or not query.get('lptag', [''])[0]):
        raise ValueError('쿠팡 인플루언서 원링크 형식이 아닙니다.')
    identity = {}
    for key, target in [('pageKey', 'product_id'), ('itemId', 'item_id'), ('vendorItemId', 'vendor_item_id')]:
        values = query.get(key, [])
        if len(values) != 1 or not re.fullmatch(r'[0-9]+', values[0]):
            raise ValueError('원링크의 상품·옵션 식별자를 확인할 수 없습니다.')
        identity[target] = values[0]
    return identity


def parse_storefront(source):
    """Read product records, including JSON escaped inside Next.js scripts."""
    unescaped = source.replace(r'\"', '"')
    pattern = re.compile(
        r'"productId"\s*:\s*(\d+)\s*,\s*"itemId"\s*:\s*(\d+)\s*,\s*"vendorItemId"\s*:\s*(\d+)'
        r'(?:(?!"productId").)*?"landingUrl"\s*:\s*"([^"\n]+)"\s*,\s*"title"\s*:\s*"((?:\\.|[^"\\])*)"', re.S)
    items = []
    for match in pattern.finditer(unescaped):
        pid, iid, vid, raw, title = match.groups()
        link = normalize_one_link(raw)
        try:
            identity = link_identity(link)
            if identity != dict(product_id=pid, item_id=iid, vendor_item_id=vid):
                continue
            title = json.loads('"' + title + '"')
        except (ValueError, TypeError):
            continue
        row = dict(identity, title=html.unescape(title), one_link=link)
        if row not in items:
            items.append(row)
    return items


def _name(value):
    # Use full normalized names, keeping model/capacity/color distinctions.
    return re.sub(r'[^a-z0-9가-힣]', '', value.casefold())


def choose_item(items, name, original_url=''):
    expected = product_identity(original_url) if original_url else None
    if expected:
        matches = [item for item in items if all(item.get(k) == v for k, v in expected.items())]
    else:
        query = _name(name)
        matches = [item for item in items if query and query in _name(item['title'])]
    if len(matches) > 1:
        raise ValueError('여러 상품·옵션이 일치합니다. itemId와 vendorItemId가 포함된 원 상품 URL을 입력하세요.')
    return matches[0] if matches else None


class _StoreRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Store lookup cannot become an arbitrary server-side URL fetch.
        storefront_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_storefront(url):
    request = Request(storefront_url(url), headers={'User-Agent': 'Mozilla/5.0', 'Cache-Control': 'no-cache'})
    try:
        with build_opener(_StoreRedirect()).open(request, timeout=15) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError('스토어 응답이 너무 큽니다.')
            source = raw.decode('utf8')
    except Exception:
        raise ValueError('스토어를 읽지 못했습니다. 주소·공개 상태·접근 제한을 확인하세요.') from None
    if re.search(r'access denied|captcha|<title>[^<]*(?:로그인|보안 확인)', source, re.I):
        raise ValueError('스토어 접근 확인이 필요합니다. 요청을 중지했습니다.')
    items = parse_storefront(source)
    if not items:
        raise ValueError('스토어의 상품 정보를 확인하지 못했습니다. 빈 스토어로 추정해 자동 등록하지 않습니다.')
    return items


def _access(page):
    parsed = urlsplit(page.url)
    if (parsed.hostname not in {'partners.coupang.com', 'influencers.coupang.com', 'link.coupang.com',
                                'www.coupang.com', 'm.coupang.com', 'coupang.com'}
            or re.search(r'login|captcha|challenge', parsed.path, re.I)
            or page.locator('input[type=password]:visible, iframe[src*="captcha"]:visible').count()
            or re.search(r'access denied|captcha|보안 확인', page.title(), re.I)):
        raise ValueError('기존 Chrome에 로그인·접근 확인이 필요합니다. 자동 재시도하지 않습니다.')


def _navigate(page, url):
    page.goto(url, wait_until='domcontentloaded', timeout=30000)
    _access(page)


def _click(locator):
    if locator.count() != 1 or not locator.is_visible() or not locator.is_enabled():
        raise ValueError('쿠팡 화면이 예상과 다릅니다. 현재 단계에서 중지했습니다.')
    locator.click(timeout=10000)


def register_product(page, name, store, original_url=''):
    """Original steps 1–9, on one existing approved tab; never log in or launch."""
    _navigate(page, 'https://partners.coupang.com/#affiliate/ws/link/0/' + quote(name))
    cards = page.locator('.product-item')
    cards.first.wait_for(state='visible', timeout=15000)
    candidates = []
    for card in cards.all():
        desc = card.locator('.product-description')
        title = desc.get_attribute('title') or desc.inner_text() if desc.count() == 1 else card.inner_text()
        urls = card.locator('a[href]').evaluate_all('(nodes) => nodes.map(n => n.href)')
        if original_url:
            matched = False
            for url in urls:
                try:
                    verify_product_match(original_url, url)
                    matched = True
                except ValueError:
                    pass
        else:
            matched = bool(_name(name) and _name(name) in _name(title))
        if matched:
            candidates.append(card)
    if len(candidates) != 1:
        raise ValueError('파트너스에서 일치 상품 한 개를 확인하지 못했습니다. 제품명·원 상품 URL을 확인하세요.')
    _click(candidates[0].locator('button.btn-generate-link'))
    short = page.get_by_text(re.compile(r'^https://link\.coupang\.com/a/[A-Za-z0-9_-]+/?$'))
    short.first.wait_for(state='visible', timeout=15000)
    values = set(short.all_text_contents())
    if len(values) != 1:
        raise ValueError('발급한 파트너스 링크 한 개를 확인하지 못했습니다.')
    short_url = next(iter(values)).strip()
    _navigate(page, 'https://influencers.coupang.com/storefront')
    # Verify the signed-in store before any collection mutation.
    paths = page.locator('a[href]').evaluate_all('(nodes) => nodes.map(n => n.href)')
    if store.rstrip('/') not in {url.rstrip('/') for url in paths}:
        raise ValueError('로그인한 내 스토어와 입력한 공개 스토어의 일치를 확인하지 못했습니다.')
    collection = page.locator('a[href*="/storefront/collections/"]').first
    collection.wait_for(state='visible', timeout=15000)
    _click(collection)
    _access(page)
    field = page.locator('input[placeholder*="링크로 제품"]:visible, input[placeholder*="링크"]:visible, input[placeholder*="URL"]:visible')
    if field.count() != 1:
        raise ValueError('컬렉션의 상품 링크 입력 한 개를 확인하지 못했습니다.')
    field.fill(short_url)
    _click(page.get_by_role('button', name='저장', exact=True))
    # Wait for the added product to be shown before the final save.
    page.get_by_text(name, exact=False).first.wait_for(state='visible', timeout=15000)
    save = page.get_by_role('button', name=re.compile(r'^(저장|최종저장|완료|저장하기)$'))
    _click(save)
    _access(page)


def verify_landing(page, item):
    _navigate(page, item['one_link'])
    page.wait_for_url(re.compile(r'^https://(?:www\.|m\.)?coupang\.com/vp/products/\d+'), timeout=15000)
    _access(page)
    expected = ('https://www.coupang.com/vp/products/' + item['product_id']
                + '?itemId=' + item['item_id'] + '&vendorItemId=' + item['vendor_item_id'])
    verify_product_match(expected, page.url)
    title = page.locator('h1.prod-buy-header__title:visible, h2.prod-buy-header__title:visible, .prod-buy-header__title:visible, h1:visible').first
    title.wait_for(state='visible', timeout=15000)
    observed = title.inner_text().strip()
    if not observed or not (_name(item['title']) in _name(observed) or _name(observed) in _name(item['title'])):
        raise ValueError('실제 연결 상품명이 스토어 상품명과 다릅니다. 기존 제품 링크를 유지합니다.')
    return dict(item, final_url=page.url, final_product_title=observed, landing_verified=True)


def find_one_link(settings, payload):
    name = payload.get('product_name', '')
    store = payload.get('storefront_url', '')
    original = payload.get('product_url', '')
    register = payload.get('register', False)
    if (not isinstance(name, str) or not name.strip() or len(name) > 300
            or not isinstance(store, str) or not isinstance(original, str) or len(original) > 2048
            or type(register) is not bool):
        raise ValueError('제품명과 스토어·원 상품 URL을 확인하세요.')
    name, store, original = name.strip(), storefront_url(store.strip()), original.strip()
    if original:
        product_identity(original)
    item = choose_item(fetch_storefront(store), name, original)
    if item is None and not register:
        raise ValueError('스토어에서 일치 상품을 찾지 못했습니다. 원 상품 URL을 확인하거나 등록 옵션을 선택하세요.')
    from playwright.sync_api import sync_playwright
    from .source_browser_runtime import attach_browser, browser_lease, _bound_inventory
    attached_settings = replace(settings, source_browser_existing_window_only=True)
    with browser_lease(attached_settings), sync_playwright() as playwright:
        context = attach_browser(playwright, attached_settings)
        binding, rows = _bound_inventory(context, attached_settings)
        pages = [row['page'] for row in rows if row.get('page') is not None
                 and row['window_id'] == binding['window_id']
                 and urlsplit(row['page'].url).hostname in {'partners.coupang.com', 'influencers.coupang.com',
                        'www.coupang.com', 'm.coupang.com', 'coupang.com', 'link.coupang.com'}]
        if len(pages) != 1:
            raise ValueError('기존 승인된 Chrome 창에 쿠팡 탭 하나가 필요합니다. 새 Chrome은 실행하지 않습니다.')
        page = pages[0]
        _access(page)
        if item is None:
            register_product(page, name, store, original)
            item = choose_item(fetch_storefront(store), name, original)
            if item is None:
                raise ValueError('스토어 저장 결과를 확인하지 못했습니다. 자동으로 다시 등록하지 않습니다.')
        return dict(verify_landing(page, item), storefront_url=store, product_name=name,
                    status='one_link_ready')
