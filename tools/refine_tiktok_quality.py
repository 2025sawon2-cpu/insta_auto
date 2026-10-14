"""Preserve prior three renders while drafting a separately versioned repair."""
import json
from pathlib import Path

from hotpost.editing_adapter import _atomic_json
from hotpost.writing import codex_writer
from hotpost.writing.checks import review
from hotpost.writing.contract import snapshot, receipt
from hotpost.writing.variants import SCHEMA, validate_triplet

OLD = Path(__file__).resolve().parents[1] / 'data/tiktok-rework-20261011'
ROOT = OLD.parent / 'tiktok-quality-20261011-v2'
FINDINGS = {
    'DeRIBMYzn0x': '기존 1안의 자기참조 갈등은 유지할 만하지만 썸네일이 기능 설명으로 끝납니다. 불을 끄는 선택 없이 침대만 가린다는 구체적인 역설을 짧은 2줄로 궁금하게 만드세요. 2안 고립 효과는 원작의 의외성과 실제 작동이 겹치므로 다른 관심·기억 메커니즘을 적용하세요. 두 안의 생활 상황과 정보 공개 순서를 구별하고 빛 차단을 반복 설명하지 않습니다. 수면 개선과 난방비 절감 보장은 금지합니다.',
    'DeRFXHpEwck': '기존 1안은 지금 정리하기 편리하다는 편의만 있어서 현재 편향의 즉시 보상과 미래 비용 사이 갈등이 없습니다. 현재 편향을 제대로 설계하거나 원작이 쓰지 않은 다른 비용·기회·시간 메커니즘을 선택하세요. 2안 매몰비용은 이미 들인 수집 노력을 유지 동기로 쓰되 단순 아까움인 손실회피로 이름만 바꾸지 않습니다. 작은 포켓·벨크로 구조와 손에 든 조각을 챙기는 구체성이 제품 궁금증을 만들어야 하며 단순 정리 교훈으로 끝내지 않습니다. 미래 재고·품절·현재 가격은 추가하지 않습니다.',
    'DeJ7hD6zsnR': '기존 썸네일 십만 원대도?는 현재 구매 가능한 가격처럼 보입니다. 가격·가치 판단이라는 중심 매력은 유지하면서 판매 사실과 개인 예산/가정은 구별하세요. 숫자를 과거 회상으로 돌려 놓는 것으로 해결하지 않습니다. 1안 심적 회계는 용도 배정이 실제 지출 의향을 바꾸게 하고, 2안은 원작의 앵커링·손실회피·희소성과 다른 메커니즘이 실제 갈등을 이끌게 합니다. 입어본 옷을 좋아한다고 소유효과가 입증된 것은 아닙니다. 가정/연출은 changes에 남기며 실제 구매·현재 할인을 주장하지 않습니다. 상품을 찾고 싶게 하는 패딩의 구체적인 관심을 남기고 기준·예산 강의로 끝내지 않습니다. 택→AS→키즈 묶음은 재사용하지 않습니다.',
}


def main():
    inputs = json.loads((OLD/'writing/inputs.json').read_text('utf-8'))
    previous = json.loads((OLD/'writing/variants.json').read_text('utf-8'))
    contract = snapshot()
    for payload in inputs:
        code = payload['code']; folder = ROOT/code/'writing'; folder.mkdir(parents=True, exist_ok=True)
        out = folder/'quality.json'
        if out.exists():
            continue
        state = {'directory': folder, 'calls': []}
        old = next(x for x in previous['items'] if x['code'] == code)
        instruction = ('원본을 다시 분석하고 개선한 1·2·3안 전체를 함께 작성하세요. '
            '1·2안은 서로 다르며 원작이 쓰지 않은 같은 주된 카테고리의 메커니즘으로 전개와 갈등을 재설계합니다. '
            '메커니즘 이름을 붙이는 데 그치지 말고 작동 문구·판단 변화를 mechanism_application에 설명하세요. '
            '3안만 원작 흐름을 유지하며 의미 있는 표면 요소 2~3개를 바꾸고 문장과 특징적인 설명 묶음을 복사하지 않습니다. '
            '짧고 강한 두 줄 썸네일은 제품의 구체적인 차이/갈등을 보여주고 핵심 정보에 호기심을 남깁니다. '
            '약 20~25초의 자연스러운 구어체로 한 갈등을 진행하고 기능 요약 반복·이론 해설은 빼세요. '
            '댓글 요청 없이도 제품을 찾아보고 싶어야 합니다. 내용 평가를 중간 승인 조건으로 삼지 않습니다. '
            '판매 가격·재고·AS·보장 효능은 만들지 않고 현재 구매 가능한 사실로 쓰지 않습니다. '
            '대본은 확보된 영상 소스 수/적합성과 독립적으로 작성합니다. 새 연출과 자료 한계는 changes에 기록하고 '
            '낭독/썸네일에 참고 당시·미확인 같은 자료 해설을 넣지 않습니다.\n\n'+contract['prompt'])
        cached = sorted(folder.glob('codex-*/result.json'), key=lambda p:p.stat().st_mtime)
        if cached:
            value = codex_writer.decode(cached[-1].read_text('utf-8'),SCHEMA)
            state['calls'] = [json.loads(p.read_text('utf-8')) for p in folder.glob('codex-*/receipt.json')]
        else:
            value = codex_writer.chat(instruction, json.dumps({'reference': payload, 'previous': old,
                'editorial_findings': FINDINGS[code]}, ensure_ascii=False), SCHEMA, lambda: None, state,
                images=[OLD/'writing'/(code+'-reference-first.jpg')])
        for repair in range(2):
            try:
                validate_triplet(value)
                break
            except ValueError as exc:
                _atomic_json(folder/('validation-before-repair-'+str(repair)+'.json'),{'value':value,'error':str(exc)})
                value = codex_writer.chat(instruction+'\n구조 검사를 통과하도록 해당 오류만 보완하세요. '
                    'original_category에는 주된 카테고리 이름 하나만 쓰고 1·2안 category에도 정확히 같은 이름을 씁니다. '
                    '보조 카테고리는 hook_analysis에 설명합니다. 실제 메커니즘의 카테고리가 다르면 이름만 바꾸지 말고 '
                    '맞는 메커니즘과 해당 전개를 새로 설계합니다. 원문은 세 안 모두 함께 반환합니다.',
                    json.dumps({'reference':payload,'draft':value,'validation_error':str(exc)},ensure_ascii=False),
                    SCHEMA,lambda:None,state)
        validate_triplet(value)
        scripts = []
        for variant in value['variants']:
            checked = review(variant['text'], payload['reference'], keyword=payload['comment_keyword'], contract=contract)
            checked.update(**{k:v for k,v in variant.items() if k != 'text'}, human_review_pending=True)
            scripts.append(checked)
        _atomic_json(out, {'scripts': scripts, 'analysis': {k:v for k,v in value.items() if k != 'variants'},
            'reference': payload, 'writing_contract': receipt(contract), 'calls': state['calls'],
            'generation_model': 'codex-cli', 'human_findings': FINDINGS[code], 'human_review_pending': True})
        print(code+' separately versioned three proposals saved', flush=True)


if __name__ == '__main__':
    main()
