"""Per-install identity settings. Saving never logs in or starts an automation."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time

from .coupang_onelink import storefront_url
from .monetization_store import MonetizationStore, canonical_account
from .state_lock import file_lock


class SetupConflict(ValueError):
    pass


def configuration(root, name):
    path = Path(root)/'monetization/state.sqlite3'
    if not path.is_file():
        return None
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='configuration'").fetchone():
            return None
        row = db.execute('SELECT value FROM configuration WHERE name=?',(name,)).fetchone()
    return json.loads(row[0]) if row else None


def read(root):
    root = Path(root)
    saved = configuration(root,'installation')
    if saved:
        return {**saved, 'configured': True, 'login_verified': False}
    products = configuration(root,'collection_products') or {}
    automation = configuration(root,'automation') or {}
    account = automation.get('account','')
    publication = [account] if account else []
    draft_path = root/'post-preparation.sqlite3'
    if draft_path.is_file():
        with closing(sqlite3.connect(draft_path.resolve().as_uri()+'?mode=ro',uri=True)) as drafts:
            if drafts.execute("SELECT 1 FROM sqlite_master WHERE name='drafts'").fetchone():
                for row in drafts.execute('SELECT value FROM drafts ORDER BY updated DESC'):
                    publication.extend(json.loads(row[0]).get('selected_accounts',[]))
    # Only historical Studio installations used these fixed publication choices.
    # A configured collector alone is not evidence of a publication identity.
    if (root/'studio/studio.sqlite3').is_file():
        publication = list(dict.fromkeys([*publication,'mr.salrim','__ariddaum__']))
    publication = list(dict.fromkeys(publication))
    values = dict(publication_accounts=publication,
                  discovery_account=products.get('account') or automation.get('discovery_account') or account,
                  storefront_url=products.get('storefront_url',''), collection=products.get('collection',''))
    return dict(revision=0,values=values,configured=bool(publication and values['discovery_account']
                and values['storefront_url'] and values['collection']),login_verified=False,legacy=bool(publication))


def validate(values):
    keys = {'publication_accounts','discovery_account','storefront_url','collection'}
    if not isinstance(values,dict) or not keys <= set(values) or set(values)-keys-{'littly_logins'}:
        raise ValueError('초기 설정 항목을 확인하세요.')
    accounts = values['publication_accounts']
    if not isinstance(accounts,list) or not 1 <= len(accounts) <= 10 or any(not isinstance(a,str) for a in accounts):
        raise ValueError('게시용 인스타 계정을 1개 이상 입력하세요.')
    accounts = list(dict.fromkeys(canonical_account(a) for a in accounts))
    if not all(isinstance(values[k],str) for k in keys-{'publication_accounts'}):
        raise ValueError('계정·스토어·컬렉션은 문자로 입력하세요.')
    collection = values['collection'].strip()
    if not 1 <= len(collection) <= 80 or any(ord(c)<32 for c in collection):
        raise ValueError('상품을 등록할 컬렉션 이름을 입력하세요(80자 이내).')
    result = dict(publication_accounts=accounts,
                discovery_account=canonical_account(values['discovery_account'] or accounts[0]),
                storefront_url=storefront_url(values['storefront_url'].strip()),collection=collection)
    if 'littly_logins' in values:
        routes = values['littly_logins']
        if not isinstance(routes,dict):
            raise ValueError('리틀리 로그인 안내는 게시 계정별로 입력하세요.')
        normalized = {}
        for account, route in routes.items():
            account = canonical_account(account)
            if account not in accounts or account in normalized:
                raise ValueError('리틀리 로그인 안내의 게시 계정을 확인하세요.')
            if not isinstance(route,dict) or set(route) != {'provider','account_hint'}:
                raise ValueError('리틀리에는 로그인 방식과 저장 계정 식별자만 입력하세요.')
            if route['provider'] not in ('','chrome','google','kakao','email'):
                raise ValueError('리틀리 로그인 방식을 확인하세요.')
            hint = route['account_hint']
            if not isinstance(hint,str) or len(hint)>160 or any(ord(c)<32 for c in hint):
                raise ValueError('Chrome 저장 계정 식별자를 한 줄로 입력하세요(160자 이내).')
            normalized[account] = dict(provider=route['provider'],account_hint=hint.strip())
        result['littly_logins'] = normalized
    return result


def littly_login_routes(values):
    """Login hints are instructions for a visible login, never authentication proof."""
    saved = values.get('littly_logins',{})
    return [dict(account=account, provider=saved.get(account,{}).get('provider',''),
                 account_hint=saved.get(account,{}).get('account_hint',''),
                 configured=bool(saved.get(account,{}).get('provider') and
                                 saved.get(account,{}).get('account_hint')),
                 login_verified=False)
            for account in values['publication_accounts']]


def require_littly_login(root, account):
    account = canonical_account(account)
    route = next((r for r in littly_login_routes(read(root)['values']) if r['account']==account),None)
    if not route:
        raise ValueError('등록된 업로드 계정을 선택하세요.')
    if not route['configured']:
        raise ValueError(f'@{account}의 리틀리 로그인 방식과 Chrome 저장 계정 식별자를 설정에서 확인·저장하세요. 비밀번호는 입력하지 마세요.')
    return route


def save(root, payload):
    if (not isinstance(payload,dict) or set(payload) != {'revision','values'}
            or type(payload['revision']) is not int or payload['revision'] < 0):
        raise ValueError('현재 설정 버전과 입력값이 필요합니다.')
    values = validate(payload['values'])
    root = Path(root)
    with file_lock(root/'monetization/product-admission.lock'):
        before = read(root)
        store = MonetizationStore(root/'monetization')
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT value FROM configuration WHERE name='installation'").fetchone()
            current = json.loads(row[0]) if row else before
            if current['revision'] != payload['revision']:
                raise SetupConflict('다른 화면에서 설정이 변경됐어요. 새로고침한 뒤 확인해 주세요.')
            # Older clients omit this optional field. Preserve known routes for
            # retained accounts instead of silently erasing them on their save.
            if 'littly_logins' not in values and 'littly_logins' in current['values']:
                values['littly_logins'] = {account:route for account,route in current['values']['littly_logins'].items()
                                           if account in values['publication_accounts']}
            # Login instructions do not rebind running work. Keep all existing
            # identity-change guards for accounts, collector, store and collection.
            if any(values[key] != current['values'][key] for key in
                   ('publication_accounts','discovery_account','storefront_url','collection')):
                if db.execute("SELECT 1 FROM effects WHERE status IN ('dispatching','unknown') LIMIT 1").fetchone():
                    raise SetupConflict('진행 중이거나 결과 확인이 필요한 작업이 있어요. 현재 계정 연결을 유지해 주세요.')
                queued = db.execute("SELECT 1 FROM sqlite_master WHERE name='collection_product_queue'").fetchone()
                # Additional publication choices do not change pending product work.
                # Keep its collector/store and the automation's primary account bound.
                identity_changed = (any(values[key] != current['values'][key]
                    for key in ('discovery_account', 'storefront_url', 'collection'))
                    or values['publication_accounts'][:1] != current['values']['publication_accounts'][:1])
                if identity_changed and queued and db.execute("SELECT 1 FROM collection_product_queue WHERE json_extract(state,'$.status') IN ('pending','comment_reserved','comment_confirmed','dm_received','product_verified','link_reserved') LIMIT 1").fetchone():
                    raise SetupConflict('상품 확인 대기·실행 기록이 있어요. 현재 연결 정보를 유지해 주세요.')
                draft_path = root/'post-preparation.sqlite3'
                if draft_path.is_file():
                    with closing(sqlite3.connect(draft_path.resolve().as_uri()+'?mode=ro',uri=True)) as drafts:
                        if (drafts.execute("SELECT 1 FROM sqlite_master WHERE name='coupang_link_jobs'").fetchone()
                                and drafts.execute("SELECT 1 FROM coupang_link_jobs WHERE status='running' LIMIT 1").fetchone()):
                            raise SetupConflict('원링크 확인 작업이 진행 중이에요. 완료 뒤 설정을 변경해 주세요.')
                # Switching an installation's owner is not a history migration.
                if (current['values']['storefront_url'] and values['storefront_url'] != current['values']['storefront_url']
                        and db.execute('SELECT 1 FROM effects LIMIT 1').fetchone()):
                    raise SetupConflict('기존 스토어의 작업 이력이 있어요. 다른 사용자에게는 별도 설치·데이터 폴더를 사용해 주세요.')
            result = dict(revision=current['revision']+1,values=values,updated=time.time())
            db.execute("INSERT INTO configuration VALUES('installation',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                       (json.dumps(result,ensure_ascii=False),))
    return {**result,'configured':True,'login_verified':False}
