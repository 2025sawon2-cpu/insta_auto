"""Restore price/family attraction in all three older jacket proposals via Codex."""
import argparse
import json
from pathlib import Path
from hotpost.editing_adapter import _atomic_json
from hotpost.writing import codex_writer
from hotpost.writing.checks import review
from hotpost.writing.contract import snapshot, receipt
from hotpost.writing.variants import SCHEMA, validate_triplet

CODE = 'DeJ7hD6zsnR'
PREVIOUS = Path('data/tiktok-quality-20261011-v2') / CODE / 'writing/quality-final.json'
ROOT = Path('data/old-jacket-value-20261011-v3') / CODE / 'writing'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--revision', type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    out = ROOT / f'quality-v{args.revision}.json'
    if out.exists():
        print('Existing three proposals retained; no new writer call.', flush=True)
        return
    previous_path = PREVIOUS if args.revision == 1 else ROOT / 'quality-v1.json'
    previous = json.loads(previous_path.read_text('utf-8'))
    contract = snapshot()
    target = ROOT / f'writer-v{args.revision}'
    target.mkdir(parents=True, exist_ok=True)
    state = {'directory': target, 'calls': []}
    instruction = (
        '구 패딩 DeJ7hD6zsnR의 실제 재작업 품질 보완입니다. 원본 자료와 이전 세 안을 직접 읽고 '
        '항상 A/B/C 세 안을 함께 생성하세요. 이전 A는 아이 겨울옷 예산 이야기만 남아 원작의 핵심인 '
        '합리적인 가격으로 노스페이스를 찾고 가족 겨울옷도 함께 탐색하는 매력이 약해졌습니다. '
        '핵심 제품 외형은 흰 몸판/검은 어깨 배색입니다. 이 외형과 가격 부담이 낮아지면 재탐색한다는 '
        '매력을 구체적인 제품 갈등에 연결하세요. 현재 할인 판매를 입증하지 않았으므로 10만 원대는 '
        '명확한 조건문으로만 사용합니다. 현재 십만원대 판매 중, 현재 대란 시즌, 정품 인증, AS, '
        '매장 택, 재고/사이즈, 같은 키즈 배색 판매를 단정하지 마세요. 가족은 성인/키즈 라인에서 '
        '각각 고르고 싶은 생활 설정이며 같은 제품/배색 보장을 뜻하지 않습니다. '
        '원작 가격 앵커링/손실회피와 다른 A 심적 회계, B 소유효과를 실제 전개에 작동시키세요. '
        'A는 같은 돈을 일반 여윳돈과 가족 겨울옷 몫으로 볼 때 달라지는 제품 탐색/지출 판단을 '
        '한 번만 보여주세요. B는 대체 후보도 괜찮던 선택 전과 내 것으로 정한 뒤 교환이 아까워지는 '
        '소유 전후 판단 차이를 보여주며, 그저 예쁘고 마음에 든다는 호감으로 대체하지 않습니다. '
        'A/B의 갈등과 공개 순서는 서로 다르게 쓰세요. C만 원작의 심리 메커니즘·전개 흐름을 '
        '유지하고 인물·장소·계기·행동을 최소 2~3군데 의미 있게 바꾸세요. 원문 문장과 대사, '
        '매장 택→AS→키즈 같은 특징적인 설명 묶음은 재사용하지 않습니다. '
        '1인칭 생활 연출은 가능하지만 실제 구매/가격 검증으로 기록하지 않습니다. 각 changes에 '
        '연출과 현재 가격 미확인을 짧게 기록하고, 낭독에는 검증 해설을 넣지 않습니다. '
        '썸네일 두 줄은 이 특정 제품의 매력과 갈등을 짧고 자연스럽게 드러내세요. '
        '가격을 넣으면 조건이 현재 판매 주장으로 읽히지 않아야 합니다. 댓글 요청을 빼도 '
        '이 배색 패딩을 찾아보고 싶은 이유가 남게 쓰세요. 선택 기준·구매 방법·교훈 강의는 '
        '제거하고 가격/가족/애착을 문장마다 반복하지 않습니다. 댓글 키워드는 나도, 요청은 한 번. '
        '이전 렌더/대본/음성은 보존하며 확보 소스 수나 영상 길이로 원고를 제한하지 않습니다.\n\n'
        + contract['prompt'])
    if args.revision == 2:
        instruction += (
            '\n실제 v1 전체 검토 후 한 번 보완: A는 흰 몸판/검은 어깨를 도입과 중간에 반복하고 '
            '가족 예산과 각자 라인 탐색도 반복돼요. 같은 돈의 용도에 따른 갈등을 생활 설정 안에서 '
            '한 번만 보여주고, 십만 원대라면이라는 조건을 제품 재탐색과 짧게 연결하세요. '
            'B의 두 벌은 그대로인데 제 대답만 달라지는 거예요는 심리 효과 해설이라 제거하세요. '
            '소유 전후 교환 아쉬움은 하나의 생활 갈등으로만 보이고 가격 조건/가족 매력은 짧게 '
            '연결하세요. C의 결제했다고 해볼게요와 그럴 것 같아요 반복은 가정 강의처럼 들립니다. '
            '고가 기준/낮은 조건 가격/차액 아쉬움/재탐색/가족 흐름과 3군데 의미 있는 표면 변경은 '
            '유지하면서 문장을 연결해 압축하세요. 현재 판매가·확인된 실제 결제인 듯한 주장은 '
            '금지하며 조건을 한 번 명확하게 표현합니다. 원작의 짧은 추천 영상처럼 말하세요. '
            '썸네일 A의 겨울옷 몫이면 다시 볼까는 예산 강의라 제품 호기심이 약합니다. '
            '이 특정 패딩과 소비자 갈등을 연결한 두 줄로 개선하세요. 도현의 중간점(·)과 이모지는 '
            '지원되지 않아 쓰지 말고 기본 한글·숫자·일반 문장부호로만 씁니다. '
            '소스 확보 수/장면 문제는 대본 입력이나 제약에 넣지 않습니다.')
    payload = {'reference': previous['reference'], 'previous_scripts': previous['scripts'],
               'previous_analysis': previous['analysis'], 'material_kind': 'screen_text'}
    _atomic_json(target / 'input.json', payload)
    print('Older jacket A/B/C value repair started through official Codex CLI.', flush=True)
    value = codex_writer.chat(instruction, json.dumps(payload, ensure_ascii=False), SCHEMA, lambda: None, state)
    validate_triplet(value)
    scripts = []
    for variant in value['variants']:
        checked = review(variant['text'], previous['reference']['reference'],
                         keyword=previous['reference']['comment_keyword'], contract=contract)
        checked.update(**{k:v for k,v in variant.items() if k != 'text'}, human_review_pending=True)
        scripts.append(checked)
    _atomic_json(out, {**previous, 'scripts': scripts,
        'analysis': {k:v for k,v in value.items() if k != 'variants'},
        'writing_contract': receipt(contract), 'calls': state['calls'], 'human_review_pending': True,
        'revision': f'old-jacket-value-v{args.revision}', 'previous': str(previous_path.resolve()),
        'current_sale_price_verified': False, 'reference_kind': 'screen_text'})
    print('Older jacket A/B/C saved as a separate version.', flush=True)


if __name__ == '__main__':
    main()
