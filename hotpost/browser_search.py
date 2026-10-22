"""Playwright 기반 무료 역이미지/플랫폼 검색 공급자.

현재 연결된 수집용 Chrome을 사용하며 CAPTCHA, 로그인, DOM 변경은 우회하지 않는다.
공급자 하나가 실패해도 다른 검색은 계속 수행하고 진단 스크린샷을 남긴다.
"""
from __future__ import annotations

import re
import time
import html
import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from .config import Settings
from .request_pacing import request_pause
from .browser_profile import BROWSER_LOCK, export_cookies, save_platform_cookies
from .search_access import access_record, manual_required, challenge_on_page, challenge_in_text, login_wall_on_page, empty_results_on_page, search_restriction_on_page
from .source_urls import video_url
from .source_queries import platform_queries, clean_terms, language
from .source_browser_runtime import attach_browser, browser_lease, existing_page, pace

VIDEO_HOSTS = ("tiktok.com", "douyin.com", "xiaohongshu.com", "youtube.com", "youtu.be", "bilibili.com",
               "vimeo.com", "lazada.", "manuals.plus", "made-in-china.com")
SKIP_HOSTS = ("google.com", "gstatic.com", "googleusercontent.com", "yandex.com", "yandex.ru", "yandex.net")
from .source_search.strategy import fresh_queries, fresh_frames, image_sha256, image_signature, minimum_search_queries
from .source_search.readiness import readiness_blocked, record_unresolved, parser_revision
BROWSER_COOLDOWNS: dict[str, float] = {}


class SearchBudgetReached(Exception):
    pass


def _is_candidate(url: str) -> bool:
    return video_url(url)


def _unwrap(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.endswith("google.com") and parsed.path == "/url":
        return unquote(parse_qs(parsed.query).get("q", parse_qs(parsed.query).get("url", [url]))[0])
    return url


def _anchors(page, provider: str, query: str, match_kind: str) -> list[dict]:
    out = []
    try:
        # 동적 검색 페이지의 수천 개 노드를 Python에서 하나씩 조회하면 분 단위로 멈출 수 있다.
        # Bilibili's footer has an unrelated BV video before result hydration.
        # It must not count as a result or end the bounded result wait early.
        selector = ('.bili-video-card a[href], .video-item a[href]'
                    if 'bilibili' in provider and match_kind == 'platform-search' else 'a[href]')
        anchors = page.locator(selector).evaluate_all(
            """els => els.slice(0, 1500).map(a => ({href: a.href,
              text: a.innerText || a.getAttribute('aria-label') || '',
              title: a.getAttribute('title') || a.querySelector('[title]')?.getAttribute('title') || '',
              card_title: a.closest('.bili-video-card,.video-item')?.querySelector('.bili-video-card__info--tit')?.textContent || '',
              card_visible: !!a.closest('.bili-video-card,.video-item')?.getClientRects().length,
              duration: a.closest('.bili-video-card,.video-item')?.querySelector('.bili-video-card__stats__duration,.duration')?.textContent || ''}))"""
        )
    except Exception:  # noqa: BLE001
        return out
    for anchor in anchors:
        try:
            scoped_bilibili = 'bilibili' in provider and match_kind == 'platform-search'
            if scoped_bilibili and anchor.get('card_visible') is False:
                continue
            url = _unwrap(urljoin(page.url, anchor.get("href") or ""))
            if not _is_candidate(url):
                continue
            title = str((anchor.get('card_title') if scoped_bilibili else '')
                        or anchor.get("title") or anchor.get("text") or "").strip()
            item = {"url": url, "provider": provider, "title": re.sub(r"\s+", " ", title)[:240],
                    "query": query, "match_kind": match_kind}
            if 'bilibili' in urlparse(url).netloc:
                stamp = re.search(r'(?<!\d)(\d{1,2}:\d{2}(?::\d{2})?)(?!\d)',
                                  str(anchor.get('duration') or anchor.get('text') or ''))
                if stamp:
                    parts = [int(p) for p in stamp[1].split(':')]
                    if all(p < 60 for p in parts[1:]):
                        seconds = sum(p*60**i for i,p in enumerate(reversed(parts)))
                        item['discovery_meta'] = {'duration':seconds, 'duration_source':'search_card'}
                # Bilibili links the thumbnail (view counts) before the title.
                # Merge both so deduplication does not throw away the real title
                # or duration, which avoids downloading known overlong clips.
                from .source_urls import canonical_video_key
                old = next((v for v in out if canonical_video_key(v['url']) == canonical_video_key(url)), None)
                if old is not None:
                    if re.fullmatch(r'[\d\s.:万亿]*', old['title']) and item['title']:
                        old['title'] = item['title']
                    if item.get('discovery_meta'):
                        old.setdefault('discovery_meta', {}).update(item['discovery_meta'])
                    continue
            out.append(item)
        except Exception:  # noqa: BLE001 - 개별 동적 DOM 노드는 건너뛴다.
            continue
    return out


def _html_candidates(raw: str, provider: str, query: str) -> list[dict]:
    """서버 HTML·hydration 데이터에서 SPA 영상 ID와 상세 URL을 복구한다."""
    body = html.unescape(raw).replace("\\u002F", "/").replace("\\/", "/")
    urls = []
    if provider == "tiktok":
        urls += re.findall(r'https?://(?:www\.)?tiktok\.com/@[^"\'<>\s]+/video/\d+', body)
    elif provider == "douyin":
        urls += [f"https://www.douyin.com/video/{video_id}" for video_id in
                 re.findall(r'(?:aweme_id["\']?\s*[:=]\s*["\']|/video/)(\d{10,})', body)]
    elif provider == "xiaohongshu":
        note_ids = re.findall(r'(?:/explore/|noteId["\']?\s*[:=]\s*["\'])([0-9a-f]{24})', body, re.I)
        urls += [f"https://www.xiaohongshu.com/explore/{note_id}" for note_id in note_ids]
    elif provider == "bilibili":
        urls += [f"https://www.bilibili.com/video/{video_id}" for video_id in
                 re.findall(r'/video/(BV[0-9A-Za-z]+)', body)]
    return [{"url": url, "provider": f"playwright-{provider}", "title": "", "query": query,
             "match_kind": "platform-search"} for url in dict.fromkeys(urls) if _is_candidate(url)]


def _embedded_candidates(page, provider: str, query: str) -> list[dict]:
    """SPA가 링크를 anchor로 만들지 않아도 hydration 데이터의 영상 ID를 복구한다."""
    if provider == 'bilibili':
        # Whole-page HTML includes navigation/footer BV IDs unrelated to this
        # query. The hydrated visible search cards already provide exact links.
        return []
    try:
        return _html_candidates(page.content(), provider, query)
    except Exception:  # noqa: BLE001
        return []


def _sample_frames(frames: list[Path], count: int) -> list[Path]:
    if count <= 1:
        return frames[len(frames) // 2:len(frames) // 2 + 1]
    if len(frames) <= count:
        return frames
    indexes = {round(i * (len(frames) - 1) / (count - 1)) for i in range(count)}
    return [frames[i] for i in sorted(indexes)]


class BrowserSearcher:
    def __init__(self, settings: Settings, debug_dir: Path):
        self.settings = settings
        self.debug_dir = debug_dir
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        self.candidates: list[dict] = []
        self.visual_candidates: list[dict] = []
        self.terms: list[str] = []
        self.notes: list[str] = []
        self.searches: list[dict] = []
        self.previous_searches: list[dict] = []
        self.routes = None
        self.progress = lambda _message: None
        self.deadline = None

    def _pace(self, provider, reserve=20):
        try:
            pace(self.settings, provider, self.progress,
                 on_wait=lambda until: setattr(self, 'waiting_until', until))
        except TimeoutError as exc:
            raise SearchBudgetReached(str(exc)) from exc

    def _page(self, context, provider):
        return existing_page(context, self.settings, provider)

    def _retry_pause(self, provider):
        self.progress(f'{provider} · 일시적 로딩 실패 · 20초 후 1회 재시도')
        time.sleep(20)

    def _audit_request(self, audit, operation):
        from .source_browser_runtime import operation_interval
        audit.setdefault('requests', []).append({'operation': operation, 'at': time.time(),
            'minimum_interval_seconds': operation_interval(self.settings, audit.get('provider'))})
        # Flush before navigation/upload: a worker termination must not turn a
        # real request into an unattempted "started" row on the next round.
        self.progress(f"{audit.get('provider')} · 요청 기록: {operation}")

    def _cooldown_path(self, provider):
        return self.settings.data_dir / 'search_cooldowns' / f'{provider}.json'

    def _recheck_saved_captcha(self, provider, context=None, page=None):
        from .search_access import observe_saved_captcha
        try:
            if page is not None:
                return observe_saved_captcha(self.settings,provider,page)
            if context is not None:
                return observe_saved_captcha(self.settings,provider,self._page(context,provider))
            if not (self.settings.source_browser_profile_dir/'hotpost-live-session-v1').exists():
                return {'status':'unavailable','error_type':'ExistingLiveSessionMissing'}
            from playwright.sync_api import sync_playwright
            with browser_lease(self.settings), sync_playwright() as pw:
                context = attach_browser(pw,self.settings)
                return observe_saved_captcha(self.settings,provider,self._page(context,provider))
        except Exception as exc:
            return {'status':'unavailable','error_type':type(exc).__name__}

    def _cooling_down(self, provider, *, context=None, page=None):
        from .source_collection_access import disabled_platforms
        disabled = disabled_platforms(self.settings)
        if provider in disabled:
            self.searches.append({'provider':provider, 'query':'', 'language':'',
                                  'status':'platform_disabled', 'candidates':0,
                                  'reason':disabled[provider]})
            self.progress(f'{provider} · 사용자 설정으로 수집 제외')
            return True
        record=access_record(self.settings.data_dir,provider)
        captcha_check = None
        if record.get('reason') in {'captcha','captcha_review_pending'} and manual_required(record):
            captcha_check=self._recheck_saved_captcha(provider,context,page)
            if captcha_check['status']=='unavailable':
                self.searches.append({'provider':provider,'query':'','language':'','status':'not_attempted',
                    'candidates':0,'reason':'captcha_recheck_unavailable','captcha_check':captcha_check})
                self.progress(f'{provider} · 현재 수집용 화면을 확인할 수 없어 요청 보류')
                return True
            record=access_record(self.settings.data_dir,provider)
            if captcha_check['status']=='clear':
                BROWSER_COOLDOWNS.pop(provider,None)
                self.notes.append(f'{provider} · 현재 기존 탭에 CAPTCHA 없음 확인 · 과거 차단 기록 해제')
        if readiness_blocked(self.settings.data_dir,provider):
            self.searches.append({'provider':provider,'query':'','language':'','status':'readiness_blocked',
                                  'parser_revision':parser_revision(provider),'candidates':0})
            self.notes.append(f'{provider} · 검색 화면 판독 실패 · 판독기 수정 또는 명시적 세션 재확인 전 재접근 중지')
            self.progress(f'{provider} · 검색 화면 판독 실패로 경로 중지')
            return True
        if manual_required(record):
            reason=('captcha_review_pending' if record.get('reason')=='captcha_review_pending' else
                    'login_required' if record.get('reason')=='login_required' else 'verification_required')
            self.searches.append({'provider':provider,'query':'','language':'','status':reason,'candidates':0,
                                  **({'captcha_check':captcha_check} if captcha_check else {})})
            self.notes.append(f'{provider} · '+('CAPTCHA 의심 화면 캡처·재검토 대기 · 미확정' if reason=='captcha_review_pending' else
                '스크린샷 재검토로 CAPTCHA 확인 · 해당 플랫폼 요청 중지' if captcha_check else '로그인 확인 필요'))
            self.progress(f'{provider} · 인증 확인 필요 · 다른 검색으로 진행')
            return True
        until = BROWSER_COOLDOWNS.get(provider, 0)
        try:
            target = self._cooldown_path(provider)
            saved = json.loads(target.read_text())
            # Apply the ten-minute ceiling to old persisted exponential pauses too.
            blocked_at = float(saved.get('blocked_at', target.stat().st_mtime))
            until = float(saved['until']) if saved.get('server_retry_after') else min(float(saved['until']), blocked_at + 600)
            BROWSER_COOLDOWNS[provider] = until
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if until <= time.time():
            return False
        self.notes.append(f'{provider} 인증/요청 제한 후 휴식 중 · 검색 건너뜀')
        self.searches.append({'provider': provider, 'query': '', 'language': '',
                              'status': 'cooldown', 'candidates': 0})
        self.progress(f'{provider} · 인증/요청 제한으로 이번 검색 건너뜀')
        return True

    def _block(self, provider, audit, reason, response=None):
        from .editing_adapter import _atomic_json
        if reason=='captcha':
            from .captcha_review import saved_review
            verified=saved_review(audit.get('captcha_review') or {})
            if not verified or verified.get('status')!='captcha':reason='captcha_review_pending'
        target = self._cooldown_path(provider)
        previous = {}
        try:
            previous = json.loads(target.read_text())
        except (OSError, ValueError):
            pass
        now = time.time()
        strikes = (max(1, int(previous.get('strikes', 1))) + 1
                   if previous and now - float(previous.get('blocked_at', previous.get('until', 0))) < 86400 else 1)
        seconds = min(600, max(60, self.settings.source_browser_block_cooldown))
        server_retry_after = False
        if response is not None and reason == 'rate_limited':
            from email.utils import parsedate_to_datetime
            value = getattr(response, 'headers', {}).get('retry-after', '')
            try:
                seconds = max(0, float(value))
                server_retry_after = True
            except ValueError:
                try:
                    seconds = max(0, parsedate_to_datetime(value).timestamp() - now)
                    server_retry_after = True
                except (TypeError, ValueError, OverflowError):
                    pass
        until = now + seconds
        BROWSER_COOLDOWNS[provider] = until
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(target, {'until': until, 'reason': reason, 'blocked_at': now, 'strikes': strikes,
                             'server_retry_after': server_retry_after,
                             'requires_verification':reason in {'captcha','captcha_review_pending','login_required'},
                             **({'captcha_review':audit['captcha_review']} if audit.get('captcha_review') else {})})
        audit['status'] = reason
        self.notes.append(f'{provider} {reason} · '+('CAPTCHA 의심 화면 재검토 대기 · 미확정' if reason=='captcha_review_pending' else
            '사용자 인증 확인 전 재검색 중지' if reason in {'captcha','login_required'} else f'{seconds}초 동안 재검색 중지'))
        self.progress(f'{provider} · 인증/요청 제한으로 검색 중지 · 다른 검색으로 진행')

    @staticmethod
    def _captcha(page):
        return challenge_on_page(page)

    def _check_block(self, page, provider, audit, response=None):
        if response is not None and response.status == 429:
            self._block(provider, audit, 'rate_limited', response)
            return True
        if not self._captcha(page):
            if login_wall_on_page(page,provider):
                self._block(provider,audit,'login_required')
                return True
            return False
        from .captcha_review import review_page
        review=review_page(self.settings,provider,page,query=audit.get('query',''))
        audit['captcha_review']=review
        if review['status']=='clear':
            if login_wall_on_page(page,provider):
                self._block(provider,audit,'login_required')
                return True
            return False
        if review['status']!='captcha':
            self._block(provider,audit,'captcha_review_pending')
            self.progress(f'{provider} · CAPTCHA 의심 화면 캡처/재검토 대기 · 확정 차단으로 세지 않음')
            return True
        audit['challenge_detected_at'] = time.time()
        audit['challenge_page'] = page.url.split('?',1)[0]
        if provider == 'tiktok':
            self._block(provider, audit, 'captcha')
            return True
        audit['challenge_wait_setting_seconds'] = self.settings.source_browser_captcha_wait
        self.progress(f'{provider} · CAPTCHA 인증 대기 · 열린 Chrome에서 직접 확인해 주세요')
        if not self.settings.source_browser_headless:
            deadline = time.monotonic() + self.settings.source_browser_captcha_wait
            while time.monotonic() < deadline:
                page.wait_for_timeout(1000)
                if not self._captcha(page):
                    if login_wall_on_page(page,provider):
                        self._block(provider,audit,'login_required')
                        return True
                    return False
        # The page may have changed while waiting. Recheck the actual captured
        # screen instead of retaining the initial positive image as current proof.
        review=review_page(self.settings,provider,page,query=audit.get('query',''))
        audit['captcha_review']=review
        if review['status']=='clear':return False
        if review['status']!='captcha':
            self._block(provider,audit,'captcha_review_pending')
            return True
        audit['challenge_still_present'] = True
        self._block(provider, audit, 'captcha')
        return True

    def run(self, frames: list[Path], queries: list[str], limit: int) -> dict:
        if not self.settings.source_browser_search or limit <= 0:
            return {"candidates": [], "terms": [], "notes": []}
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"candidates": [], "terms": [], "notes": ["Playwright가 설치되지 않아 브라우저 검색을 건너뜀"]}
        selected = frames
        with BROWSER_LOCK, browser_lease(self.settings), sync_playwright() as pw:
            try:
                context = attach_browser(pw, self.settings)
            except Exception as exc:  # noqa: BLE001
                return {"candidates": [], "terms": [], "notes": [f"Chrome 연결 실패: {exc}"],
                        "searches": [{'provider': 'browser-worker', 'status': 'connection_failed', 'candidates': 0}]}
            context.set_default_timeout(15000)
            try:
                routes = self.routes if self.routes is not None else ['youtube','tiktok','douyin','xiaohongshu','bilibili','google-lens','yandex-images']
                for provider in routes:
                    if getattr(self,'search_only',False):
                        from .source_search.strategy import search_quota_needed
                        if not search_quota_needed([*self.previous_searches,*self.searches],getattr(self,'search_minimums',{}),search_identity=getattr(self,'search_identity',None)):break
                        if provider in {'google-lens','yandex-images'}:continue
                    self.visual_candidates.extend(self.candidates)
                    self.candidates = []
                    try:
                        self._run_route(context, provider, selected, queries, limit)
                    except LookupError as exc:
                        self.searches.append({'provider':provider, 'query':'', 'status':'not_attempted',
                                              'candidates':0, 'reason':str(exc)})
                        self.notes.append(f'{provider} · 기존 탭을 특정할 수 없어 건너뜀 · 새 탭을 만들지 않음')
                # 역이미지 근거를 보존한다. 최종 플랫폼 분배는 source_finder에서 수행한다.
                seen = set()
                combined = []
                for item in [*self.visual_candidates, *self.candidates]:
                    normalized = item["url"].rstrip("/")
                    if normalized and normalized not in seen:
                        seen.add(normalized); combined.append(item)
                self.candidates = combined
            except SearchBudgetReached:
                self.notes.append('이번 브라우저 검색 예산 완료 · 세션과 중간 결과를 정상 저장')
                self.searches.append({'provider':'browser-worker','query':'','language':'','status':'budget_exhausted','candidates':0})
            finally:
                self.progress('브라우저 검색 중간 결과 저장')
                try:
                    cookies = context.cookies()
                    export_cookies(cookies, self.settings.source_browser_cookie_file)
                    for platform in ('google','tiktok', 'douyin', 'xiaohongshu', 'youtube'):
                        save_platform_cookies(cookies, self.settings.data_dir, platform)
                except Exception as exc:  # noqa: BLE001
                    self.notes.append(f"브라우저 쿠키 저장 실패: {type(exc).__name__}")
                self.progress('검색 완료 · 수집용 Chrome과 검색 화면을 유지합니다')
        # A cooperative budget stop can occur between visual and text searches.
        # Keep both groups, just as the incremental checkpoint does.
        combined={item['url'].rstrip('/'):item for item in [*self.visual_candidates,*self.candidates]}
        self.candidates=list(combined.values())
        return {"candidates": self.candidates, "terms": clean_terms(self.terms)[:20], "notes": self.notes,
                "searches": self.searches}

    def _run_route(self, context, provider, selected, queries, limit):
        provider_pool = getattr(self, 'provider_queries', {})
        if provider == 'tiktok' and 'tiktok' in provider_pool:
            from .source_queries import register_tiktok_noun_head
            for raw in provider_pool.get('tiktok') or []:
                register_tiktok_noun_head(raw)
        queries = provider_pool.get(provider, queries)
        if provider == 'google-lens' and selected:
            self._google(context, selected, limit)
        elif provider == 'yandex-images' and selected:
            self._yandex(context, selected, limit)
        elif provider in {'tiktok','douyin','xiaohongshu','bilibili'}:
            self._platforms(context, queries, limit, providers={provider})
        elif provider == 'youtube':
            self._youtube(context, queries, limit)
        elif provider not in {'google-lens', 'yandex-images'}:
            self.searches.append({'provider':provider, 'query':'', 'status':'not_attempted',
                                  'candidates':0, 'reason':'existing_browser_search_not_implemented'})
            self.notes.append(f'{provider} · 기존 브라우저 검색 연결 미구현 · 별도 HTTP 검색으로 대체하지 않음')

    def _google(self, context, frames: list[Path], limit: int) -> None:
        if self._cooling_down('google-lens',context=context):
            return
        frames = self._fresh_images(frames, 'google-lens')
        if not frames:
            return
        page = self._page(context, 'google-lens')
        try:
            for i, frame in enumerate(frames, 1):
                self._pace('Google Lens',reserve=100)
                self.progress(f'Google Lens · 장면 {i}/{len(frames)} 이미지 검색')
                audit = {'provider': 'google-lens', 'query': frame.name, 'language': 'image', 'image_sha256': image_sha256(frame), 'image_signature':image_signature(frame), 'status': 'started', 'candidates': 0}
                self.searches.append(audit)
                self._audit_request(audit, 'image_search_page')
                response = page.goto("https://www.google.com/imghp?hl=en", wait_until="domcontentloaded", timeout=60000)
                if self._check_block(page, 'google-lens', audit, response):
                    break
                request_pause()
                page.get_by_role("button", name="Search by image").click()
                upload = page.locator("input[type=file]")
                upload.wait_for(state="attached")
                self._pace('google-lens')
                self._audit_request(audit, 'image_upload')
                upload.set_input_files(str(frame))
                page.wait_for_timeout(3500)
                if self._check_block(page, 'google-lens', audit):
                    break
                found = _anchors(page, "google-lens", frame.name, "visual-match")
                self.candidates.extend(found)
                audit.update(status='results' if found else 'no_results', candidates=len(found))
                if len(self.candidates) >= limit:
                    break
                page.wait_for_timeout(1200)
        except SearchBudgetReached:
            raise
        except Exception as exc:  # noqa: BLE001
            if frames: audit.update(status='error', error=type(exc).__name__)
            self.notes.append(f"Google Lens 실패: {type(exc).__name__}: {str(exc)[:180]}")
            try: page.screenshot(path=str(self.debug_dir / "google_error.png"), full_page=True)
            except Exception: pass  # noqa: E701
        finally:
            pass  # Keep results/challenge visible for the user.

    def _yandex(self, context, frames: list[Path], limit: int) -> None:
        if self._cooling_down('yandex-images',context=context):
            return
        frames = self._fresh_images(frames, 'yandex-images')
        if not frames:
            return
        page = self._page(context, 'yandex-images')
        try:
            for frame in frames:
                self._pace('Yandex',reserve=70)
                self.progress(f'Yandex · {frame.name} 이미지 검색')
                audit = {'provider': 'yandex-images', 'query': frame.name, 'language': 'image', 'image_sha256': image_sha256(frame), 'image_signature':image_signature(frame), 'status': 'started', 'candidates': 0}
                self.searches.append(audit)
                self._audit_request(audit, 'image_search_page')
                response = page.goto("https://yandex.com/images/", wait_until="domcontentloaded", timeout=60000)
                if self._check_block(page, 'yandex-images', audit, response):
                    break
                self._pace('yandex-images',reserve=85)
                self._audit_request(audit, 'image_upload')
                page.locator("input[type=file]").set_input_files(str(frame))
                page.wait_for_timeout(2500)
                if self._check_block(page, 'yandex-images', audit):
                    break
                page.wait_for_url("**/images/search**", timeout=60000)
                page.wait_for_timeout(2500)
                body = page.locator("body").inner_text()
                self._yandex_terms(body)
                found = _anchors(page, "yandex-images", frame.name, "visual-match")
                self.candidates.extend(found)
                audit.update(status='results' if found else 'no_results', candidates=len(found))
                if len(self.candidates) >= limit:
                    break
                page.wait_for_timeout(1000)
        except SearchBudgetReached:
            raise
        except Exception as exc:  # noqa: BLE001
            if frames: audit.update(status='error', error=type(exc).__name__)
            self.notes.append(f"Yandex Images 실패: {type(exc).__name__}: {str(exc)[:180]}")
            try: page.screenshot(path=str(self.debug_dir / "yandex_error.png"), full_page=True)
            except Exception: pass  # noqa: E701
        finally:
            pass  # Keep results/challenge visible for the user.

    def _fresh_images(self, frames, provider):
        fresh = fresh_frames(frames, provider, [*self.previous_searches, *self.searches])
        if not fresh:
            self.searches.append({'provider':provider, 'query':'', 'language':'image',
                                  'status':'image_exhausted', 'candidates':0})
        return _sample_frames(fresh, max(1, self.settings.source_browser_frames))

    def _yandex_terms(self, body: str) -> None:
        lines = [x.strip() for x in body.splitlines() if x.strip()]
        try:
            start = lines.index("Image appears to contain") + 1
        except ValueError:
            return
        for line in lines[start:start + 6]:
            if line in {"Similar images", "Sites", "Search"}:
                break
            if 2 <= len(line) <= 100:
                self.terms.append(line)

    def _submit_search(self, page, provider, query, audit):
        """Use the site's visible search box; never silently replace it with a URL."""
        execution = audit.setdefault('execution', {'query_submitted':False, 'query_url_matched':False})
        from .source_queries import within_query_word_limit
        if not within_query_word_limit(query):
            audit.update(status='query_rejected',stage='query_validation',reason='query_word_limit_exceeded')
            return False
        homes = {'tiktok': 'https://www.tiktok.com/', 'douyin': 'https://www.douyin.com/',
                 'xiaohongshu': 'https://www.xiaohongshu.com/explore',
                 'bilibili': 'https://search.bilibili.com/'}
        parsed_url = urlparse(page.url)
        host = parsed_url.hostname or ''
        # Both the homepage and watch-page headers open a native results tab.
        # Waiting for their original URL falsely reports an unresolved result.
        # Reuse this tab's search home and its visible box instead.
        bili_header = provider == 'bilibili' and host == 'www.bilibili.com' and not (parsed_url.path or '').startswith('/search')
        if bili_header and self._check_block(page, provider, audit):
            return False
        if bili_header or not (host == provider + '.com' or host.endswith('.' + provider + '.com')):
            self._pace(provider, reserve=45)
            self._audit_request(audit, 'search_home')
            response = page.goto(homes[provider], wait_until='domcontentloaded',
                                 timeout=self.settings.source_browser_navigation_timeout * 1000)
            if self._check_block(page, provider, audit, response):
                return False
        if self._check_block(page, provider, audit):
            return False
        selectors = {
            'tiktok': 'input[data-e2e="search-user-input"], input[name="q"], input[placeholder*="Search"], input[placeholder*="검색"]',
            'douyin': 'input[data-e2e="searchbar-input"], input[placeholder*="搜索"]',
            'xiaohongshu': 'input#search-input, input[placeholder*="搜索"]',
            'bilibili': 'input.search-input, input.nav-search-input, input[placeholder*="搜索"]',
        }
        fields = page.locator(', '.join(s.strip() + ':visible' for s in selectors[provider].split(',')))
        field = fields.first
        audit['stage'] = 'locate_search_input'
        if provider == 'tiktok' and not field.is_visible():
            # TikTok's desktop sidebar collapses the search input until its
            # visible Search control is clicked. Waiting for the hidden input
            # alone times out even in an authenticated session.
            control = page.get_by_text(re.compile(r'^(Search|검색|搜索)$')).filter(visible=True)
            count = control.count()
            if count == 0:
                previous_query = parse_qs(urlparse(page.url).query).get('q', [''])[0]
                if previous_query:
                    # The sidebar button shows the last query on results pages.
                    control = page.get_by_text(previous_query, exact=True).filter(visible=True)
                    count = control.count()
            if count != 1:
                # TikTok can retain an older sidebar label after SPA navigation.
                # Identify the visible search-icon control instead of guessing
                # its stale text or issuing a second navigation.
                control = page.locator('.TUXButton-content:has([class*="DivSearchIconContainer"]):visible')
                count = control.count()
            audit['visible_search_controls'] = count
            if count == 1:
                audit['stage'] = 'open_search_panel'
                control.click(timeout=self.settings.source_browser_navigation_timeout * 1000)
                if self._check_block(page, provider, audit):
                    return False
                audit['stage'] = 'locate_search_input'
            else:
                audit.update(status='page_unresolved',stage='search_control_ambiguous',
                             reason='no_unique_visible_search_control')
                record_unresolved(self.settings.data_dir,provider,query)
                self.progress(f'{provider} · 검색 버튼을 하나로 확인하지 못함 · 입력 전 판독 대기')
                return False
        field.wait_for(state='visible', timeout=self.settings.source_browser_navigation_timeout * 1000)
        audit['visible_search_inputs'] = fields.count()
        if audit['visible_search_inputs'] != 1:
            audit.update(status='page_unresolved',stage='search_input_ambiguous',reason='no_unique_visible_search_input')
            record_unresolved(self.settings.data_dir,provider,query)
            self.progress(f'{provider} · 검색 입력란을 하나로 확인하지 못함 · 제출 중지')
            return False
        # Filling can trigger suggestions, so pace before touching the input.
        from .source_input_observation import InputObservation
        observation=InputObservation(field,query,audit) if provider=='tiktok' else None
        try:
            if observation:observation.capture('before_pacing')
            self._pace(provider, reserve=self.settings.source_browser_result_timeout + 5)
            self._audit_request(audit, 'search_input')
            self.progress(f'{provider} · 검색창 입력: {query}')
            audit['stage'] = 'submit_search'
            if observation:observation.capture('after_pacing')
            if provider in ('tiktok', 'bilibili'):
                # Controlled inputs can restore or concatenate the previous query
                # after fill(). Both behaviours were observed in the live collector.
                # Real key events replace it and update the site's input state.
                if provider == 'bilibili' and hasattr(field, 'fill'):
                    field.fill('')
                field.press('ControlOrMeta+A')
                if observation:observation.capture('after_select_all')
                field.press_sequentially(query, delay=90)
                if observation:observation.capture('after_typing')
                page.wait_for_timeout(750)
                if observation:observation.capture('after_settle')
            else:
                field.fill(query)
        finally:
            if observation:observation.close()
        actual_value = field.input_value()
        execution['input_value'] = actual_value
        if ' '.join(actual_value.split()) != query:
            audit.update(status='page_unresolved',stage='search_input_mismatch',reason='planned_query_differs_from_input')
            record_unresolved(self.settings.data_dir,provider,query)
            self.progress(f'{provider} · 계획 검색어와 실제 입력값 불일치 · 제출 중지')
            return False
        execution['submit_intent'] = True
        field.press('Enter')
        execution['query_submitted'] = True
        execution['submitted_at'] = time.time()
        self.progress(f'{provider} · 검색 제출 확인: {query}')
        def matching_url(url):
            parsed = urlparse(str(url))
            host = parsed.hostname or ''
            if not (host == provider+'.com' or host.endswith('.'+provider+'.com')):
                return False
            if provider == 'douyin':
                return unquote(parsed.path).rstrip('/') == '/search/' + query
            paths = {'tiktok':{'/search','/search/video'},
                     'xiaohongshu':{'/search_result'},'bilibili':{'/all','/search'}}
            if parsed.path.rstrip('/') not in paths[provider]:
                return False
            key = 'q' if provider == 'tiktok' else 'keyword'
            return parse_qs(parsed.query).get(key, [''])[0] == query
        page.wait_for_url(matching_url, wait_until='domcontentloaded',
                          timeout=self.settings.source_browser_navigation_timeout * 1000)
        execution.update(query_url_matched=True,result_url=page.url)
        audit['stage'] = 'search_results'
        return True

    def _youtube(self, context, queries: list[str], limit: int) -> None:
        from .youtube_search import search_existing_youtube
        search_existing_youtube(self, context, queries, limit)

    def _platforms(self, context, queries: list[str], limit: int, providers=None) -> None:
        for provider in ('tiktok', 'douyin', 'xiaohongshu', 'bilibili'):
            if providers is not None and provider not in providers:
                continue
            if self._cooling_down(provider,context=context):
                continue
            query_limit = max(3, self.settings.source_queries_per_platform) if provider == 'tiktok' else self.settings.source_queries_per_platform
            minimums=getattr(self,'search_minimums',{}) or {}
            if minimums:query_limit=max(query_limit,sum(minimums.values()))
            available = platform_queries(queries, provider, len(queries),search_minimums=minimums)
            search_only=getattr(self,'search_only',False)
            selected = minimum_search_queries(available,provider,[*self.previous_searches,*self.searches],minimums,query_limit,search_only=search_only,search_identity=getattr(self,'search_identity',None))
            if not selected:
                self.searches.append({'provider':provider, 'query':'', 'language':'',
                                      'status':'query_exhausted' if available else 'no_supported_queries', 'candidates':0})
                self.notes.append(f'{provider} · 지원 언어의 미사용 검색어가 없어 검색 건너뜀')
                continue
            planned_languages = {language(q) for q in selected}
            if provider == 'tiktok':
                missing = {'en','ko','zh'} - {language(q) for q in queries}
                if missing:
                    self.notes.append('TikTok 검색어 누락 언어: ' + ', '.join(sorted(missing)))
            per_provider_limit = min(limit, max(1, self.settings.source_candidates_per_platform,
                self.settings.source_tiktok_min_usable * 3 if provider == 'tiktok' else 0))
            # The necessary search response is the access check. An extra raw
            # HTTP request to /login did not execute site JavaScript and could
            # itself cause a new challenge; cookie presence is not auth proof.
            auth = 'unverified'
            page = self._page(context, provider)
            provider_urls: set[str] = set()
            response_candidates = []
            current_query = ['']
            limited_response = [None]
            self._rate_response = limited_response
            def observe_status(response):
                host = urlparse(response.url).hostname or ''
                if response.status == 429 and (host == provider + '.com' or host.endswith('.' + provider + '.com')):
                    limited_response[0] = response
            if hasattr(page, 'on'):
                page.on('response', observe_status)
            if provider == 'tiktok' and hasattr(page, 'on'):
                from .source_search.tiktok_results import search_response_candidates
                def receive_search(response):
                    parsed = urlparse(response.url)
                    if parsed.path not in ('/api/search/item/full/', '/api/search/general/full/'):
                        return
                    try:
                        response_candidates.extend(search_response_candidates(
                            response.url, response.json(), current_query[0]))
                    except Exception:
                        pass
                page.on('response', receive_search)
            try:
                per_query_limit = max(2, (per_provider_limit + len(selected) - 1) // max(1, len(selected)))
                searched_languages = set()
                for query in selected:
                    if search_only:
                        from .source_search.strategy import search_quota_needed
                        if not search_quota_needed([*self.previous_searches,*self.searches],minimums,query,search_identity=getattr(self,'search_identity',None)):continue
                    current_query[0] = query
                    response_candidates.clear()
                    limited_response[0] = None
                    searched_languages.add(language(query))
                    self.progress(f'{provider} · {language(query)} · {query}')
                    audit = {'provider': provider, 'query': query, 'language': language(query),
                             'parser_revision':parser_revision(provider),
                             'auth': auth, 'status': 'started', 'candidates': 0}
                    if getattr(self,'search_identity',None) is not None:
                        audit['search_identity']=self.search_identity
                    self.searches.append(audit)
                    loaded = False
                    for attempt in range(2):
                        try:
                            if not self._submit_search(page, provider, query, audit):
                                break
                            loaded = True
                            break
                        except SearchBudgetReached:
                            raise
                        except Exception as exc:  # SPA 로딩 지연은 1회 재시도한다.
                            if page.is_closed() or not page.context.browser.is_connected():
                                audit.update(status='connection_lost', error=type(exc).__name__)
                                self.progress(f'{provider} · Chrome 연결 끊김 · 완료 결과 보존')
                                return
                            if limited_response[0] is not None:
                                self._block(provider, audit, 'rate_limited', limited_response[0])
                                break
                            if self._check_block(page, provider, audit):
                                break
                            audit.update(status='error', error=type(exc).__name__, error_detail=str(exc)[:1200])
                            self.notes.append(f"{provider} 페이지 로딩 지연: {type(exc).__name__}")
                            if audit.get('execution',{}).get('submit_intent'):
                                audit.update(status='page_unresolved',reason='submitted_query_response_unconfirmed')
                                record_unresolved(self.settings.data_dir,provider,query)
                                self.progress(f'{provider} · 제출 후 응답 판독 대기 · 같은 검색 재전송 보류')
                                break
                            if audit.get('stage') in {'locate_search_input','open_search_panel','search_control_ambiguous','search_input_ambiguous','submit_search'}:
                                audit.update(status='page_unresolved',reason='search_input_unavailable_before_submit')
                                record_unresolved(self.settings.data_dir,provider,query)
                                self.progress(f'{provider} · 검색 입력 전 판독 대기 · 같은 화면 재시도 보류')
                                break
                            if attempt == 0:
                                self._retry_pause(provider)
                    if BROWSER_COOLDOWNS.get(provider, 0) > time.time():
                        break
                    if not loaded:
                        break  # Stop after the bounded retry; never scrape stale results.
                    if (audit.get('http_status') or 200) >= 400:
                        audit['status'] = 'http_error'
                        continue
                    page.wait_for_timeout(2000)
                    if limited_response[0] is not None:
                        self._block(provider, audit, 'rate_limited', limited_response[0])
                        break
                    if self._check_block(page, provider, audit):
                        break
                    page.mouse.wheel(0, 900)
                    page.wait_for_timeout(1000)
                    # The slider challenge may appear after the SPA hydrates
                    # or scrolls, after the initial block check has passed.
                    if self._check_block(page, provider, audit):
                        break
                    found = self._wait_platform_results(page, provider, query, audit, response_candidates)
                    if found == [] and audit.get('status') != 'query_restricted' and not empty_results_on_page(page) and attempt == 0:
                        if challenge_in_text(page.locator('body').inner_text()) and self._check_block(page,provider,audit):
                            break
                        self._retry_pause(provider)
                        response_candidates.clear()
                        if not self._submit_search(page, provider, query, audit):
                            break
                        found = self._wait_platform_results(page, provider, query, audit, response_candidates)
                    if limited_response[0] is not None:
                        self._block(provider, audit, 'rate_limited', limited_response[0])
                        break
                    if found is None:
                        break
                    added = 0
                    for item in found:
                        if item["url"] not in provider_urls and len(provider_urls) < per_provider_limit and added < per_query_limit:
                            provider_urls.add(item["url"])
                            self.candidates.append(item)
                            added += 1
                    audit.update(status='query_restricted' if audit.get('status') == 'query_restricted' else
                                 'results' if found else ('no_results' if empty_results_on_page(page) else 'page_unresolved'),
                                 candidates=added)
                    if not found:
                        # HTTP 200 alone cannot distinguish empty results from
                        # a login/error/unfinished SPA. Keep visible evidence
                        # for diagnosis without copying scripts or cookie data.
                        try:
                            audit['page_url'] = page.url.split('?', 1)[0]
                            audit['page_excerpt'] = ' '.join(page.locator('body').inner_text().split())[:800]
                        except Exception:
                            pass
                        # A challenge can hydrate after the last polling check.
                        # Classify the actual captured body, rather than saving
                        # this known authentication wall as a parser failure.
                        if challenge_in_text(audit.get('page_excerpt', '')) and self._check_block(page,provider,audit):
                            break
                    if audit['status']=='page_unresolved':
                        record_unresolved(self.settings.data_dir,provider,query)
                        self.notes.append(f'{provider} · 검색 화면에서 결과·인증·빈 결과를 확인할 수 없어 이번 공급자 검색 종료')
                        self.progress(f'{provider} · 검색 화면 판독 실패 기록 · 이후 검색어를 바꿔도 자동 재접근 중지')
                        break
                    self.progress(f'{provider} · {language(query)} · {query} → 후보 {added}개')
                    from .source_coverage import actual_search_coverage
                    quota=actual_search_coverage([*self.previous_searches,*self.searches],minimums,getattr(self,'search_identity',None))
                    minima_met=all(row['ready'] for row in quota.values())
                    if search_only and minima_met:break
                    if len(provider_urls) >= per_provider_limit and searched_languages >= planned_languages and minima_met:
                        break
            except SearchBudgetReached:
                raise
            except Exception as exc:  # noqa: BLE001
                if 'audit' in locals() and audit.get('provider') == provider and audit['status'] == 'started':
                    disconnected = page.is_closed() or not page.context.browser.is_connected()
                    audit.update(status='connection_lost' if disconnected else 'error', error=type(exc).__name__)
                self.notes.append(f"{provider} 검색 실패: {type(exc).__name__}: {str(exc)[:140]}")
            finally:
                if hasattr(page, 'remove_listener'):
                    page.remove_listener('response', observe_status)
                if provider == 'tiktok' and hasattr(page, 'remove_listener'):
                    page.remove_listener('response', receive_search)

    def _wait_platform_results(self, page, provider, query, audit, response_candidates):
        """Bound hydration wait without another navigation or ignoring an auth wall."""
        started = time.monotonic()
        result_timeout = max(1, self.settings.source_browser_result_timeout)
        for attempt in range(result_timeout + 1):
            rate_response = getattr(self, '_rate_response', [None])[0]
            if rate_response is not None:
                self._block(provider, audit, 'rate_limited', rate_response)
                return None
            if self._check_block(page, provider, audit):
                return None
            if provider == 'tiktok' and search_restriction_on_page(page):
                audit.update(status='query_restricted', result_method='visible_search_restriction',
                             result_wait_seconds=round(time.monotonic() - started, 2))
                return []
            if provider == 'tiktok':
                # Activity notifications also contain /video/ links. Never use
                # the whole document or hydration payload as TikTok search hits.
                found = list(response_candidates)
            else:
                found = [*_anchors(page, f'playwright-{provider}', query, 'platform-search'),
                         *_embedded_candidates(page, provider, query)]
            if found or empty_results_on_page(page):
                if self._check_block(page, provider, audit):
                    return None
                audit['result_wait_seconds'] = round(time.monotonic() - started, 2)
                audit['result_method'] = ('search_response' if provider == 'tiktok' else
                                          'search_card_links' if provider == 'bilibili' else 'page_links')
                return found
            if time.monotonic() - started >= result_timeout or attempt == result_timeout:
                break
            page.wait_for_timeout(1000)
        audit['result_wait_seconds'] = round(time.monotonic() - started, 2)
        if self._check_block(page, provider, audit):
            return None
        return []


def browser_search(settings: Settings, frames: list[Path], queries: list[str], limit: int, debug_dir: Path,
                   previous_searches: list[dict] | None = None, progress=None, routes=None, provider_queries=None,
                   search_minimums=None,search_only=False,search_identity=None) -> dict:
    if not settings.source_browser_search or limit <= 0:
        return {'candidates': [], 'terms': [], 'notes': [], 'searches': []}
    from .source_browser_worker import isolated_search
    with BROWSER_LOCK:
        return isolated_search(settings, frames, queries, limit, debug_dir, previous_searches, progress,
                               routes=routes, provider_queries=provider_queries,search_minimums=search_minimums,search_only=search_only,search_identity=search_identity)
