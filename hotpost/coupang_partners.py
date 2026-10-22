"""Coupang Partners API only. No seller API or web-issuance fallback."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

API_HOST = 'https://api-gateway.coupang.com'
DEEPLINK_PATH = '/v2/providers/affiliate_open_api/apis/openapi/deeplink'


def product_identity(url):
    parsed = urlsplit(url)
    match = re.fullmatch(r'/vp/products/(\d+)/?', parsed.path)
    if parsed.scheme != 'https' or parsed.hostname not in {'www.coupang.com', 'm.coupang.com', 'coupang.com'} or parsed.port or parsed.username or not match:
        raise ValueError('확인된 쿠팡 상품 상세 HTTPS URL이 필요합니다.')
    query = parse_qs(parsed.query)
    identity = {'product_id': match[1]}
    for key, output in [('itemId', 'item_id'), ('vendorItemId', 'vendor_item_id')]:
        if key in query:
            if len(query[key]) != 1 or not query[key][0].isdigit():
                raise ValueError('상품 옵션 식별자가 올바르지 않습니다.')
            identity[output] = query[key][0]
    return identity


def verify_product_match(original, landing):
    expected, actual = product_identity(original), product_identity(landing)
    if any(actual.get(key) != value for key, value in expected.items()):
        raise ValueError('발급 링크의 상품 또는 옵션이 확인한 상품과 다릅니다.')
    return actual


def authorization(method, path, access_key, secret_key, *, now=None, query=''):
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime('%y%m%dT%H%M%SZ')
    message = stamp + method.upper() + path + query
    signature = hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f'CEA algorithm=HmacSHA256, access-key={access_key}, signed-date={stamp}, signature={signature}'


class PartnerCredentials:
    def __init__(self, root: Path):
        self.path = Path(root) / 'credentials.json'

    def read(self):
        if os.environ.get('HOTPOST_COUPANG_ACCESS_KEY') and os.environ.get('HOTPOST_COUPANG_SECRET_KEY'):
            return dict(access_key=os.environ['HOTPOST_COUPANG_ACCESS_KEY'],
                        secret_key=os.environ['HOTPOST_COUPANG_SECRET_KEY'],
                        account_ref=os.environ.get('HOTPOST_COUPANG_ACCOUNT_REF', ''), eligible=True)
        try:
            return json.loads(self.path.read_text('utf-8'))
        except (OSError, ValueError):
            return {}

    def status(self):
        values = self.read()
        return dict(configured=bool(values.get('access_key') and values.get('secret_key')),
                    eligible=values.get('eligible') is True, account_ref=values.get('account_ref', ''),
                    source='environment' if os.environ.get('HOTPOST_COUPANG_ACCESS_KEY') else 'local_file')

    def save(self, values):
        if not values.get('access_key') or not values.get('secret_key') or not values.get('account_ref'):
            raise ValueError('본인 API 계정 참조와 Access/Secret Key를 모두 입력하세요.')
        if values.get('eligible') is not True:
            raise ValueError('본인 계정의 파트너스 API 이용 자격을 확인하세요.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        kept = {key: str(values[key]).strip() for key in ('access_key', 'secret_key', 'account_ref')}
        if any(not value or '\n' in value for value in kept.values()):
            raise ValueError('API 연결 값이 올바르지 않습니다.')
        kept['eligible'] = True
        fd, temp = tempfile.mkstemp(dir=self.path.parent, prefix='.credentials-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(kept, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return self.status()


class CoupangPartners:
    def __init__(self, credentials, transport=None):
        self.credentials = credentials
        self.transport = transport or self._request

    @staticmethod
    def _request(request):
        try:
            from .request_pacing import request_pause
            request_pause()
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read(1_000_000).decode('utf-8'))
        except Exception as exc:
            # Never expose authorization headers, keys or raw remote bodies.
            raise RuntimeError('쿠팡파트너스 API 요청에 실패했습니다. 인증·이용 자격·네트워크를 확인하세요.') from None

    def issue(self, original_url):
        identity = product_identity(original_url)
        values = self.credentials.read()
        if not self.credentials.status()['configured'] or values.get('eligible') is not True or not values.get('account_ref'):
            raise ValueError('쿠팡파트너스 본인 계정의 API 연결이 필요합니다.')
        body = json.dumps({'coupangUrls': [original_url]}, separators=(',', ':')).encode()
        request = Request(API_HOST + DEEPLINK_PATH, data=body, method='POST', headers={
            'Content-Type': 'application/json',
            'Authorization': authorization('POST', DEEPLINK_PATH, values['access_key'], values['secret_key'])})
        response = self.transport(request)
        rows = response.get('data')
        if str(response.get('rCode')) != '0' or not isinstance(rows, list) or len(rows) != 1:
            raise ValueError('쿠팡파트너스 API가 링크 한 개의 발급 성공을 반환하지 않았습니다.')
        row = rows[0]
        short = row.get('shortenUrl') or row.get('shortUrl') or ''
        if not re.fullmatch(r'https://link\.coupang\.com/a/[A-Za-z0-9_-]+/?', short):
            raise ValueError('발급된 쿠팡파트너스 링크 형식이 올바르지 않습니다.')
        # API response correlation is necessary, but is not landing verification.
        if row.get('originalUrl') != original_url:
            raise ValueError('API 발급 결과의 원 상품 URL이 요청과 다릅니다.')
        return dict(original_url=original_url, affiliate_url=short, identity=identity,
                    account_ref=values['account_ref'], api_issued=True, landing_verified=False)
