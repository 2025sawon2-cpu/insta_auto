"""A new three-script version for the mini holder; do not replace old edits."""
import argparse
import json
from pathlib import Path
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.editing_adapter import _atomic_json as save
from hotpost.writing import codex_writer
from hotpost.writing.contract import snapshot, receipt
from hotpost.writing.checks import review
from hotpost.writing.variants import SCHEMA, validate_triplet

ROOT = Path('data/file-functional-quality-20261011-v3/DeRFXHpEwck').resolve()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--revision', choices=['v3', 'v4', 'v5', 'v6', 'v7'], default='v3')
    args = parser.parse_args()
    folder = ROOT / 'writing'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f'quality-{args.revision}.json'
    if target.exists():
        print('Existing official three-script version retained.', flush=True)
        return
    previous_path = Path('data/tiktok-quality-20261011-v2/DeRFXHpEwck/writing/quality.json')
    if args.revision in ('v4', 'v5', 'v6', 'v7'):
        previous_path = folder / f'quality-v{int(args.revision[1:])-1}.json'
    previous = json.loads(previous_path.read_text('utf-8'))
    state = next(s for s in Studio(load_settings(), workers=False).store.list()
                 if s['shortcode'] == 'DeRFXHpEwck')
    contract = snapshot()
    work = folder / ('generation' if args.revision == 'v3' else 'generation-' + args.revision)
    work.mkdir(exist_ok=True)
    calls = {'directory': work, 'calls': []}
    payload = {'reference_screen_text': state['original_text'],
               'previous_analysis': previous['analysis'], 'previous_scripts': previous['scripts'],
               'product_facts': ['작은 봉투형 파일 홀더', '벨크로 여닫음',
                                 '자잘한 종이·소품 보관', '휴대 편의'],
               'editorial_findings': ['아, 탐나요, 손이 가겠어요 같은 감탄만으로 시작하지 않는다.',
                 '댓글 요청을 빼도 작은 홀더를 찾아보고 싶은 구체적인 생활 갈등과 해결이 남아야 한다.',
                 '원작은 품절·우연한 매장 발견→가격/구성→작지만 수납→닫힘→휴대 흐름이다.',
                 '판매 조건·재고·인기·정량 용량·AS를 현재 사실로 발명하지 않는다.'],
               'comment_keyword': '나도'}
    if args.revision in ('v4', 'v5', 'v6', 'v7'):
        payload['known_product_identity'] = {
            'reference': {'sku': '1064379', 'name': 'A7 파스텔 파일 홀더 6개입',
                          'evidence': 'data/daily-rework-20261011/DeRFXHpEwck/official-product-1064379/visible-metadata.json'},
            'functional_example': {'sku': '1064371', 'name': '포토카드 미니 파일 홀더',
                                   'exact_reference_sku': False}}
        payload['editorial_findings'] += [
            '직전 A의 끝은 나중에 하겠다던 정리를 끝낸다는 추상적 교훈으로 끝나 제품을 찾을 이유가 약하다.',
            '직전 B의 남겨둔 조각의 자리가 생긴다는 끝도 설명만 남아 제품 호기심이 약하다.',
            '댓글 CTA를 추가하는 것만으로 해결하지 말고, 본문 자체에 작은 제품의 여닫음·휴대·수납 매력이 구체적으로 남아야 한다.',
            '영수증 또 미뤄는 어색하다. 사람은 영수증 자체가 아닌 정리를 미룬다. 썸네일은 미니 홀더에 담아 같은 평범한 지시문에서 벗어나 생활 갈등과 제품에 대한 정보 공백을 만든다.',
            '기능을 숨긴 낚시나 과장 대신 실제 작은 홀더에서 보이는 매력으로 클릭할 질문을 남긴다.',
            '참고 제품 SKU1064379는 확인됐다. SKU 미확인이라는 분석은 정정한다. 소스 예시1064371은 다른 제품이므로 가격·구성·수치 근거로 쓰지 않는다.',
            'C의 찾던 제품이라는 말만으로 원작 희소성 메커니즘을 설명했다고 간주하지 않는다. 확인되지 않은 현 재고·품절을 사실로 쓰지 않으며 연출 설정과 판매 사실을 구분한다.']
    if args.revision in ('v5', 'v6', 'v7'):
        payload['editorial_findings'] += [
            '직전 v4도 눈길이 가요/담을 수 있다니 같은 메타 감탄으로 시작한다. 시청자는 누구의 어떤 행동이 의외인지 즉시 알아야 한다.',
            '첫 문장에 모든 해결책을 설명한 뒤 평범한 제품 소개만 이어져 정보 공백이 약하다. 생활에서 자꾸 벌어지는 불편 또는 모순을 짧게 제시하고 작은 홀더의 실제 사용 동작으로 해소한다.',
            '썸네일 2줄을 썸네일과 영상내용을 함께 보는 관점에서 검토한다. 제품명+수납지시/정리는나중에처럼 내용 설명만 늘어놓지 않고 제품 장면과 문구 사이에 구체적인 질문이 남도록 한다.',
            '억지 반문이나 자극어, 새 특수기능, 잃어버릴 걱정없음 같은 보장은 금지. 촬영 상황과 사람이 하는 선택으로 흥미를 만든다.',
            '본문은 170~190자 정도로 간결하게. 현재편향은 지금 정리수고를 피하려는 선택, 매몰비용은 미래쓸모가 불확실한데 이미쓴 시간 때문에 보관하는 선택을 분명히 구별한다.',
            '각 안의 끝은 교훈이나 제품평가 감탄이 아니라 남은 제품매력을 한 동작으로 마무리하고 짧은 제품 댓글 CTA를 붙인다.']
    if args.revision in ('v6', 'v7'):
        payload['editorial_findings'] += [
            '실제 v5 문장: 영수증 담을 작은 홀더는 챙겨도, 정리는 자꾸 내일로 미뤄요. 이 시작은 홀더를 이미 챙겼다고 먼저 밝히며 갈등의 의외성이 약하다. 반복되는 생활 행동의 모순부터 짧게 시작하고 제품의 역할을 자연스럽게 발견하게 한다.',
            '실제 v5 끝: 종이 한 장을 손에서 내려놓는 동작으로 끝나요. 이 문장은 홀더의 매력이 아니라 무의미한 동작 요약이다. 삭제하고 작은 봉투의 여밈·휴대가 생활에서 왜 유용한지 구체적으로 마무리한다. 정리 성공·습관 교정·완벽한 보호는 보장하지 않는다.',
            '실제 v5 썸네일: 정리는 미뤄도 / 영수증은 이 안에? 첫줄은 선언, 둘째줄은 수납 답을 그대로 묻는다. 제품 장면과 문구를 합쳤을 때 어떤 뜻밖의 선택·차이가 궁금한지 설명하고 두줄을 새로 작성한다. 제품명 숨기기와 물음표 붙이기만으로 후킹 개선이라 하지 않는다.',
            'B의 썸네일 이 작은 홀더까지? 는 문장 뜻이 모호하다. 어떤 조각을 왜 못 버리는지와 제품이 만나는 정보 공백을 쉽게 읽히게 만든다.',
            '세 안 전체를 다시 출력하되 원문 구문, 원작의 잡동사니 나열 묶음, 특징적인 정보 순서를 A/B에 재활용하지 않는다. 앞선 문장이 더 나으면 보존할 수 있지만 무엇이 나아졌는지 분석에 구체적으로 남긴다.']
    if args.revision == 'v7':
        payload['editorial_findings'] += [
            'v6는 개선 확인 실패. 영수증은 챙겨야겠고, 이 작은 홀더 앞에서도 정리는 귀찮아요 는 누가 왜 홀더 앞에 있는지 부자연스럽고 솔루션을 먼저 펼쳐놓은 설명문이다. 앞에서도/조각 담는 작은 홀더 처럼 제품명으로 억지 시작하지 않는다. 제품 단어를 첫 문장에 넣는 것은 필수가 아니다. 시청자가 겪을 만한 짧은 선택이나 모순을 먼저 말해도 된다.',
            '한 문장을 읽고 바로 무슨 상황인지 그려져야 한다. 특히 A는 손에 받은 종이를 지금 분류하기 싫어서 가방에 섞는 선택과 분류 없이 담아 닫는 봉투의 쓰임을 대비한다. 제품의 휴대 기능으로 끝내고 같은 홀더에 또 넣어요처럼 이미말한 수납을 재설명하지 않는다.',
            '썸네일 제품장면과 문구를 함께 봤을 때 작은 봉투를 왜 챙기고 싶은지 질문이 남아야 한다. 홀더는왜꺼내, 조각도홀더로 같은 무엇인가왜라는 일반 질문이나 제품명+용도 목록에 그치지 않는다. 생활갈등/짧은 반전과 눈에 보이는 제품을 연결한다.',
            'A/B 심리 기제를 행동으로 자연스럽게 남기면서 어느 사람이나 이해할 구어체로 압축한다. 정리 강의, 심리학 강의, 제품 소개 제목을 첫 문장처럼 읽는 표현은 피한다.']
    save(work / 'input.json', payload)
    print('Official Codex writer: new A/B/C mini-holder proposals.', flush=True)
    result = codex_writer.chat(
        '다음 원본은 음성 전사가 아닌 화면 문구입니다. 일반적인 참고대본3안 규칙으로 새 원고3개를 함께 작성합니다. '
        'A는 현재편향, B는 매몰비용 효과를 유지하되 비용·기회·시간 카테고리의 서로 다른 갈등으로 전개합니다. '
        'A는 지금 정리를 미루는 행동과 영수증을 바로 담는 작은 홀더, B는 스티커에 이미 들인 시간 때문에 '
        '남은 조각을 챙기는 행동과 작은 홀더를 연결합니다. 편향 이름을 말하는 강의가 아니라 실제 선택·행동으로 드러냅니다. '
        'C만 원작의 획득기회와 작지만 담기는 기대반전 흐름을 유지하고 인물·장소·계기 중2~3곳을 의미있게 바꿉니다. '
        'A/B에는 품절→우연한 매장발견이라는 원작 갈등을 재사용하지 않습니다. '
        '1인칭 생활상황 연출은 가능하되 확인된 구매·사용 경험으로 기록하지 않습니다. '
        '본문20~25초를 목표로 군더더기 감탄을 빼고 첫 문장에 제품의 구체적 매력과 갈등이 만나게 합니다. '
        '가격·6장구성·품절·인기·정량 수납 보장을 임의 추가하지 않습니다. 정확한SKU와 일반 기능을 구별합니다. '
        '본문을 확보 소스의 개수·품질·적합성에 맞추는 조건은 없습니다. '
        '원문 문장/특징적 설명묶음 복사금지, 각 안의 편향·변경점 표기, 썸네일2줄은 굵은 도현으로 읽기좋을 짧은 제품후킹 문구입니다. '
        '썸네일의 심리후킹은 각각의 새 갈등에서 나오게 하고 댓글은 제품 자체에 연결합니다. '
        '각 적용은 제작가설이며 심리효과나 댓글률의 실증으로 쓰지 않습니다.\n\n'+contract['prompt'],
        json.dumps(payload, ensure_ascii=False), SCHEMA, lambda: None, calls)
    validate_triplet(result)
    scripts = []
    for variant in result['variants']:
        checked = review(variant['text'], state['original_text'], keyword='나도', contract=contract)
        checked.update(**{k: v for k, v in variant.items() if k != 'text'}, human_review_pending=True)
        scripts.append(checked)
    save(target, {'scripts': scripts, 'analysis': {k:v for k,v in result.items() if k!='variants'},
                 'writing_contract': receipt(contract), 'calls': calls['calls'],
                 'generation_model':'codex-cli','reference_kind':'screen_text',
                 'previous':str(previous_path.resolve()),'human_review_pending':True})
    print('New official three-script version saved for editorial review.', flush=True)


if __name__ == '__main__':
    main()
