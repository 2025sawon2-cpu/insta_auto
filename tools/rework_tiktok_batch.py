"""Bounded current-session TikTok research, without restarting global workers."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from hotpost.config import load_settings
from hotpost.browser_search import BrowserSearcher
from hotpost.source_browser_runtime import attach_browser, browser_lease, endpoint
from hotpost.source_search.tiktok_results import search_response_candidates
from hotpost.tikvideo_download import with_fallback as download
from hotpost.source_finder import probe_video

ROOT = Path(__file__).resolve().parents[1] / 'data/tiktok-rework-20261011'
QUERIES = {
    'DeRIBMYzn0x': ['암막 수면 텐트', 'bed tent setup blackout', '遮光 床帐 蚊帐'],
    'DeRFXHpEwck': ['다이소 미니 파일홀더', 'mini file holder velcro', '다이소 A7 파일 홀더', '미니 포켓 파일 영수증', '다이소 미니 파일 6개', '다이소 미니 파일 찍찍이', '다이소 미니파일홀더', 'ダイソー ミニ ファイル マジックテープ', '미니파일', 'mini envelope velcro stationery', '다이소 미니 파일 홀더 6매', '迷你 魔术贴 文件袋', 'A7 velcro envelope', '다이소 파일홀더 6매입'],
    'DeJ7hD6zsnR': ['노스페이스 패딩 키즈', 'north face puffer jacket kids'],
}

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['search','download'])
    parser.add_argument('--code', choices=list(QUERIES))
    args = parser.parse_args()
    settings = replace(load_settings(), source_browser_captcha_wait=0)
    if not endpoint(settings):
        raise RuntimeError('기존 수집용 Chrome 연결이 필요합니다. 새 브라우저는 실행하지 않습니다.')
    for code in ([args.code] if args.code else QUERIES):
        ledger = ROOT/code/'discovery.json'
        data = json.loads(ledger.read_text('utf-8')) if ledger.exists() else {'code':code,'queries':[],'candidates':[]}
        if args.phase == 'search':
            with browser_lease(settings), sync_playwright() as pw:
                context = attach_browser(pw, settings)
                pages = [p for p in context.pages if urlparse(p.url).hostname in ('www.tiktok.com','tiktok.com')]
                if len(pages) != 1: raise RuntimeError('기존 TikTok 탭 하나만 사용합니다.')
                page = pages[0]
                searcher = BrowserSearcher(settings, ROOT/code)
                searcher.progress = lambda message: print(message, flush=True)
                for query in QUERIES[code]:
                    if any(q['query']==query for q in data['queries']): continue
                    if searcher._cooling_down('tiktok'): raise RuntimeError('TikTok 접근 중지 또는 휴식 상태입니다.')
                    hits = []
                    def observe(response):
                        if '/api/search/' in response.url:
                            if response.status == 429:
                                searcher._block('tiktok', {}, 'rate_limited', response)
                            try: hits.extend(search_response_candidates(response.url, response.json(), query))
                            except Exception: pass
                    page.on('response', observe)
                    audit = {'provider':'tiktok','query':query}
                    searcher.deadline = time.monotonic()+100
                    try:
                        submitted = searcher._submit_search(page,'tiktok',query,audit)
                        if not submitted: raise RuntimeError('인증 확인 필요; 추가 검색 중지')
                        searcher._wait_platform_results(page,'tiktok',query,audit,hits)
                        seen = {c['url'] for c in data['candidates']}
                        for hit in hits:
                            if hit['url'] not in seen:
                                hit.update(selected=False,rights='unknown-check-before-reuse')
                                data['candidates'].append(hit);seen.add(hit['url'])
                        data['queries'].append({'query':query,'results':len(hits),'audit':audit,'time':time.time()})
                        save(ledger,data)
                        print(json.dumps({'code':code,'query':query,'candidates':len(data['candidates'])},ensure_ascii=False),flush=True)
                        if searcher._cooling_down('tiktok'): raise RuntimeError('TikTok 접근 중지 또는 휴식 상태입니다.')
                    finally: page.remove_listener('response',observe)
        else:
            for row in data['candidates']:
                if not row.get('selected') or row.get('path') or row.get('download_attempted'): continue
                diagnostics = {}
                row.update(download_attempted=True,attempted_at=time.time())
                save(ledger,data)
                target = ROOT/code/'videos'/(row['url'].rsplit('/',1)[-1]+'.mp4')
                try:
                    path = download(settings,row['url'],target,80*1024*1024,
                        deadline=time.monotonic()+330,diagnostics=diagnostics)
                    row.update(path=str(path),video_meta=probe_video(path),acquisition=diagnostics.get('method','existing_browser_playback'))
                except Exception as exc:
                    row['download_error']=str(exc)[:500]
                row['download_diagnostics']=diagnostics
                save(ledger,data)
                print(json.dumps({'code':code,'url':row['url'],'path':row.get('path'),'error':row.get('download_error'),'meta':row.get('video_meta')},ensure_ascii=False),flush=True)
                if BrowserSearcher(settings,ROOT/code)._cooling_down('tiktok'):
                    raise RuntimeError('TikTok 접근 중지 또는 휴식 상태입니다. 추가 다운로드를 하지 않습니다.')

if __name__ == '__main__': main()
