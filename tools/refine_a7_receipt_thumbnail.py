"""Revise all three thumbnail hooks through the official writer; retain bodies."""
import json
from pathlib import Path
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.editing_adapter import _atomic_json as save
from hotpost.writing import codex_writer
from hotpost.writing.contract import snapshot, receipt
from hotpost.writing.checks import review
from hotpost.writing.variants import SCHEMA, validate_triplet

ROOT = Path('data/a7-receipt-review-20261011-v6/DeRFXHpEwck').resolve()
PREVIOUS = Path('data/file-functional-quality-20261011-v3/DeRFXHpEwck/writing/quality-v7.json')


def main():
    target = ROOT / 'writing/quality-v8.json'
    if target.exists():
        print('Existing writer output preserved.', flush=True)
        return
    previous = json.loads(PREVIOUS.read_text('utf-8'))
    original = next(s for s in Studio(load_settings(), workers=False).store.list()
                    if s['shortcode'] == 'DeRFXHpEwck')['original_text']
    contract = snapshot()
    folder = ROOT / 'writing/generation-v8'
    folder.mkdir(parents=True, exist_ok=True)
    calls = {'directory': folder, 'calls': []}
    instruction = (
        '미니 봉투형 파일홀더의 썸네일 품질 개선입니다. 세 안 모두 함께 출력하세요. '
        '각 본문 text와 편향, 전개, changes, surface_changes는 한 글자도 바꾸지 않습니다. '
        '두 줄 thumbnail_lines와 thumbnail_mechanism만 새로 작성합니다. '
        'A의 정리는 내일/이 봉투는 지금은 어느 제품에도 붙일 수 있고 영수증이 보이지 않으면 '
        '제품의 쓰임이 모호합니다. 정리를 미루는 사람이 영수증을 작은 봉투에는 바로 챙기는 '
        '행동 차이와 제품의 작은 크기·휴대를 짧고 구체적으로 연결하세요. '
        'B는 고르느라 들인 시간이 아까워 스티커 조각까지 챙기는 매몰비용 선택과 작은 홀더를 '
        '연결합니다. 버려야 할 쓰레기를 반드시 모으라는 교훈으로 만들지 않습니다. '
        'C는 못 찾던 제품을 우연히 만나고 예상보다 담기는 기대 위반을 살리면서 '
        '원작의 문장이나 특징적인 나열을 복사하지 않습니다. '
        '썸네일만 봐도 어느 생활 장면인지 알 수 있고 이 제품을 찾아보고 싶은 질문이 남아야 합니다. '
        '방법·기준·일기·명령문만으로 끝내거나 굳이 물음표를 붙이지 않습니다. '
        '새 기능·판매 조건·품절·가격·정량 용량·잃어버리지 않는다는 보장 금지. '
        '도현에 읽기 좋은 짧은 기본 한글 두 줄, 중간점·이모지 제외. '
        '효과나 댓글률 검증이라고 주장하지 말고 제작 가설로만 설명합니다. '
        '확보 소스 수나 길이는 집필 제약에 넣지 않습니다.\n\n' + contract['prompt'])
    payload = {'reference_screen_text': original, 'previous_analysis': previous['analysis'],
               'previous_scripts': previous['scripts'], 'comment_keyword': '나도'}
    save(folder / 'input.json', payload)
    print('Official writer: all three thumbnail hooks, bodies retained.', flush=True)
    result = codex_writer.chat(instruction, json.dumps(payload, ensure_ascii=False),
                              SCHEMA, lambda: None, calls)
    validate_triplet(result)
    scripts = []
    for variant in result['variants']:
        old = next(s for s in previous['scripts'] if s['number'] == variant['number'])
        assert variant['text'] == old['text']
        # Only the requested thumbnail fields replace the original record.
        checked = review(old['text'], original, keyword='나도', contract=contract)
        checked.update({k:v for k,v in old.items() if k != 'text'})
        checked.update(thumbnail_lines=variant['thumbnail_lines'],
                       thumbnail_mechanism=variant['thumbnail_mechanism'],
                       human_review_pending=True)
        scripts.append(checked)
    save(target, {**previous, 'scripts': scripts, 'writing_contract': receipt(contract),
                  'calls': calls['calls'], 'previous': str(PREVIOUS.resolve()),
                  'generation_model': 'codex-cli', 'body_preserved': True,
                  'human_review_pending': True})
    print('Three revised thumbnails saved.', flush=True)


if __name__ == '__main__':
    main()
