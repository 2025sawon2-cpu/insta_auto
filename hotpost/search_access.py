"""Persist access failures and recheck saved CAPTCHA against the existing page."""
import json
import time
from pathlib import Path

MANUAL_REASONS={'captcha','login_required'}
PROVIDERS={'google':'google-lens','tiktok':'tiktok','douyin':'douyin','xiaohongshu':'xiaohongshu'}


def access_record(data_dir,provider):
    try:
        value=json.loads((Path(data_dir)/'search_cooldowns'/f'{provider}.json').read_text(encoding='utf-8'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}


def manual_required(record):
    # Also honor older CAPTCHA receipts whose fixed timer already expired.
    return record.get('reason') in MANUAL_REASONS and record.get('requires_verification',True)


def observe_saved_captcha(settings, provider, page):
    """Read the current tab only; no navigation, challenge solving or timer release."""
    from urllib.parse import urlparse
    from .editing_adapter import _atomic_json
    record = access_record(settings.data_dir, provider)
    if record.get('reason') != 'captcha' or not manual_required(record):
        return {'status':'not_needed'}
    domains = {'google-lens':('google.com',), 'yandex-images':('yandex.com','yandex.ru'),
               'tikvideo':('tikvideo.app',)}.get(provider, (provider+'.com',))
    try:
        host = urlparse(page.url).hostname or ''
        if not any(host == domain or host.endswith('.'+domain) for domain in domains):
            raise ValueError('Current page is not the recorded platform')
        body = page.locator('body').inner_text()
        if not body.strip():
            raise ValueError('Current page has no observable body')
        captcha = challenge_on_page(page)
        login = login_wall_on_page(page, provider)
    except Exception as exc:
        return {'status':'unavailable','error_type':type(exc).__name__}
    status = 'captcha' if captcha else 'login_required' if login else 'clear'
    observation = {'at':time.time(),'status':status,'page':page.url,
                   'navigation_performed':False,'challenge_solved_by_agent':False}
    record['captcha_observations'] = [*record.get('captcha_observations',[]), observation][-20:]
    record['last_captcha_check'] = observation
    if status == 'clear':
        record.update(requires_verification=False, until=0, captcha_cleared_by_current_page_at=observation['at'])
    elif status == 'login_required':
        record.update(reason='login_required', requires_verification=True)
    else:
        record['requires_verification'] = True
    _atomic_json(settings.data_dir/'search_cooldowns'/f'{provider}.json', record)
    return observation


def indexed_gate(provider, response=None, settings=None):
    """Stop indexed searches on a real challenge, retaining no response body."""
    if settings is None:
        from .config import load_settings
        settings = load_settings()
    record = access_record(settings.data_dir, provider)
    if response is None:
        if manual_required(record):
            return {'status':'verification_required', 'reason':record['reason']}
        if record.get('until', 0) > time.time():
            return {'status':'cooldown', 'reason':record.get('reason', '')}
        return {}
    import re
    raw = response.text.lower()
    visible = re.sub(r'<(?:script|style)\b[^>]*>.*?</(?:script|style)>', '', raw, flags=re.S)
    visible = re.sub(r'<[^>]+>', ' ', visible)
    challenge = ('/captcha' in response.url.lower() or '/sorry/' in response.url.lower()
                 or bool(re.search(r'<form\b[^>]*\bid=[\"\']challenge-form[\"\']', raw))
                 or any(token in visible for token in
                        ('bots use duckduckgo', 'verify you are human', 'confirm you are not a robot',
                         'unusual traffic', '로봇이 아닙니다', '비정상적인 트래픽')))
    reason = 'captcha' if challenge else 'rate_limited' if response.status_code == 429 else ''
    if not reason:
        return {}
    from .editing_adapter import _atomic_json
    _atomic_json(settings.data_dir/'search_cooldowns'/f'{provider}.json',
                 {'provider':provider, 'reason':reason, 'at':time.time(),
                  'requires_verification':challenge, 'http_status':response.status_code,
                  'until':0 if challenge else time.time()+300})
    return {'status':reason, 'reason':reason, 'http_status':response.status_code}


def request_manual_recheck(data_dir,provider):
    """Only the explicit session-save action can authorize one new search check.

    This records a user-requested recheck, not a claim that CAPTCHA is solved.
    Any challenge on that next check closes the gate again.
    """
    from .editing_adapter import _atomic_json
    from .source_search.readiness import request_readiness_recheck
    readiness_recheck = request_readiness_recheck(data_dir,provider)
    record=access_record(data_dir,provider)
    if not manual_required(record):return readiness_recheck
    record.update(requires_verification=False,until=0,manual_recheck_at=time.time())
    _atomic_json(Path(data_dir)/'search_cooldowns'/f'{provider}.json',record)
    return True


def challenge_in_text(text):
    """Recognize a captured visible body, never unexecuted HTML/script text."""
    body=str(text).lower()
    return any(token in body for token in ('unusual traffic','verify you are human','confirm you are not a robot',
        '로봇이 아닙니다','비정상적인 트래픽','drag the slider','fit the puzzle','slide to verify',
        '拖动滑块','拖動滑塊','滑动验证','滑動驗證','请完成下方验证','请完成安全验证',
        '슬라이더를 끌어','슬라이더를 드래그','퍼즐을 맞춰','퍼즐을 맞추'))


def challenge_on_page(page):
    from urllib.parse import urlparse
    if any(token in urlparse(page.url).path.lower() for token in ('/sorry/','/showcaptcha','/captcha')):return True
    return challenge_in_text(page.locator('body').inner_text())


def login_wall_on_page(page,provider):
    body=page.locator('body').inner_text().lower()
    patterns={'douyin':('登录后即可搜索','登录后查看搜索结果','请登录后搜索'),
              'xiaohongshu':('登录后查看搜索结果','登录后探索更多','登录后搜索'),
              'tiktok':('log in to search','log in to see search results','로그인하여 검색')}
    # A normal header's login button, or the name of an SMS login method,
    # does not by itself indicate either a challenge or a search access wall.
    if any(token in body for token in patterns.get(provider,())):
        return True
    # Douyin can open this modal over its unchanged home page when Enter is
    # pressed in search. It contains no "log in to search" text, so treating
    # the unchanged URL as a loading timeout caused a redundant retry.
    # Require the actual modal heading AND both visible login fields; a normal
    # header login button or hidden login template is not an access wall.
    if provider == 'douyin' and '登录后免费畅享高清视频' in body:
        return all(page.locator(selector).count() > 0 for selector in (
            'input[placeholder="请输入手机号"]:visible',
            'input[placeholder="请输入验证码"]:visible'))
    return False


def empty_results_on_page(page):
    body=page.locator('body').inner_text().lower()
    return any(token in body for token in ('no results found','no search results','couldn’t find results',
        "couldn't find results",'결과를 찾을 수 없음','검색 결과가 없습니다',
        '검색 결과 없음','暂无搜索结果','没有找到相关','未找到相关','暂无相关结果'))


def search_restriction_on_page(page):
    """A query safety notice is not a CAPTCHA or platform-wide access block."""
    body = page.locator('body').inner_text().lower()
    headings = ('결과를 찾을 수 없음', 'couldn’t find results', "couldn't find results", 'no results found')
    notices = ('이 문구는 증오 행동과 관련', 'this phrase may be associated with',
               'this search may be associated with', '검색어가 커뮤니티 가이드라인')
    return any(h in body for h in headings) and any(n in body for n in notices)
