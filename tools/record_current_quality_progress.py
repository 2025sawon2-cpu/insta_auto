"""Persist actual editorial and download evidence; never promote it to final render."""
import json
import time
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json
from hotpost.source_browser_runtime import attach_browser, browser_lease
from hotpost.source_queries import product_query_plan
from hotpost.source_search.planner import round_queries
from hotpost.storage import Storage


def main():
    root = Path('data/daily-rework-20261011')
    settings = load_settings()
    folder = root / 'DeSoiZvyyqj'
    ledger = folder / 'discovery.json'
    data = json.loads(ledger.read_text('utf-8'))
    row = next(r for r in data['candidates'] if r['url'].endswith('/7597253661135244565'))
    evidence = json.loads((folder / 'review/7597253661135244565/decode-sampling.json').read_text('utf-8'))
    review = {
        'url': row['url'], 'file_sha256': evidence['sha256'], 'full_decode': evidence['full_decode'],
        'actual_frames_viewed': 16, 'status': 'context_only_not_core', 'core_approved': False,
        'editing_eligible': False, 'rights': row['rights'],
        'reason': '제품 소개 정지 이미지 위주의 MP4. 폰 뒤 부착/사진 전송 핵심 동작으로 채택하지 않음. 사진 영상을 새로 제작하지 않음.',
        'checked_at': time.time()}
    review['observations'] = [
        '첫 화면은 Folder Style SSD Enclosure 정지 상품 이미지, 이후 손에 든 노란 폴더와 노트북 연결 사진 위주.',
        '실제로 본 균등16프레임에서 스마트폰 부착·파일 전송 동작은 미확인.',
        '끝부분에 큰 폴더와 작은 폴더가 함께 보임. 두 모델 기능을 합치는 근거가 아님.']
    row.update(visual_review_pending=False, usage_review=review)
    _atomic_json(ledger, data)
    _atomic_json(folder / 'review/7597253661135244565/usage-review.json', review)
    writing = folder / 'writing/quality-v5.json'
    value = json.loads(writing.read_text('utf-8'))
    findings = {
        'status': 'editorially_reviewed', 'selected_number': 2, 'render_ready': False,
        'selected_reason': 'B는 비슷한 풍경이라도 내 기록이면 따로 보관하려는 가치 차이로 전송 제품의 필요를 연결. 삭제 손실 중심 원작과 갈등 및 순서가 다름.',
        'variant_reviews': [
            {'number': 1, 'content_status': 'usable_alternate', 'mechanism': '심적 회계의 보관 역할 응용',
             'limitation': '지난 기록/새 촬영 역할 설명이 두 번 나와 B보다 압축 여지가 있음. 효과 입증을 주장하지 않음.'},
            {'number': 2, 'content_status': 'selected', 'mechanism': '소유효과를 응용한 가치 차이',
             'limitation': '촬영 주체·개인 기억도 영향을 주는 연출이며 소유효과의 실험적 입증은 아님.'},
            {'number': 3, 'content_status': 'surface_variant_only', 'mechanism': '손실회피+정보 격차 유지',
             'limitation': '원작 흐름은 사용자 3안 규칙에 따라 유지. 실제 문장 그대로 복사한 것은 없으나 독립적인 전체 전개로 평가하지 않음.'}],
        'thumbnail_selected': value['scripts'][1]['thumbnail_lines'],
        'thumbnail_review': '폰 뒤 실물 폴더/내 사진도 담는다고?는 제품 형태와 기능의 연결을 구체적으로 드러냄. 실제 썸네일 렌더·관객 후킹 성과는 아직 미검증.',
        'identity_review': '세 안 모두 SSD/SD/내부 부품·자동 정리·가격·현재 재고·전체 호환 보장을 추가하지 않음.',
        'source_dependency': '폰 부착과 사진 이동을 같은 제품으로 시연하는 실제 핵심 영상은 아직 필요.',
        'legal_clearance': False, 'audio_listened': False, 'checked_at': time.time()}
    for script in value['scripts']:
        script['human_review_pending'] = False
    value.update(human_review_pending=False, editorial_review=findings)
    _atomic_json(writing, value)
    _atomic_json(folder / 'writing/quality-v5-editorial-review.json', findings)
    store = Storage(settings.db_path)
    try:
        caption = store.conn.execute('SELECT caption FROM posts WHERE shortcode=?', ('DeRFXHpEwck',)).fetchone()['caption']
    finally:
        store.close()
    plan = product_query_plan(caption, [], [], {}, [])
    _atomic_json(root / 'DeRFXHpEwck/numeric-sku-plan.json', {
        'original_caption_already_had_sku': True, 'official_page_confirmed': True,
        'old_failure': '모델에 영문과 숫자를 모두 요구했고 action 경로가 model intent를 제거함.',
        'plan': plan, 'actual_round_plan': round_queries(plan, {'phase': 'clean_action'}),
        'live_search_pending': 'SKU 검색 제출 전 Yandex CAPTCHA 발생. 새 SKU 검색 성공으로 기록하지 않음.',
        'time': time.time()})
    # Read-only capture of the currently blocked Yandex tab; no navigation/retry.
    with browser_lease(settings), sync_playwright() as pw:
        context = attach_browser(pw, settings)
        pages = [p for p in context.pages if 'yandex' in (urlparse(p.url).hostname or '')]
        for page in pages:
            receipt = {'url': page.url, 'body': page.locator('body').inner_text()[:6000],
                       'sku_search_submitted': False, 'navigation_after_detection': 0, 'time': time.time()}
            target = root / 'DeRFXHpEwck/yandex-sku'
            _atomic_json(target / 'verification-stop.json', receipt)
            page.screenshot(path=str(target / 'verification-stop.png'), full_page=False)
    print('Actual source/editorial/SKU evidence saved; final render remains incomplete.', flush=True)


if __name__ == '__main__':
    main()
