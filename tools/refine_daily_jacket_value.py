"""Restore reference product appeal in three official Codex proposals."""
import argparse
import json
from pathlib import Path

from hotpost.editing_adapter import _atomic_json
from hotpost.writing import codex_writer
from hotpost.writing.contract import snapshot, receipt
from hotpost.writing.checks import review
from hotpost.writing.variants import SCHEMA, validate_triplet

ROOT = Path('data/daily-rework-20261011/DeSvpmAsWgZ/writing')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--revision',type=int,choices=(5,6),default=5)
    args=parser.parse_args()
    output = ROOT/f'quality-v{args.revision}.json'
    if output.exists():
        print('Existing revision preserved; inspect before any further revision', flush=True)
        return
    previous_path=ROOT/f'quality-v{args.revision-1}.json'
    previous = json.loads(previous_path.read_text('utf-8'))
    evidence = json.loads((ROOT/'input.json').read_text('utf-8'))
    directory = ROOT/f'quality-v{args.revision}'; directory.mkdir(exist_ok=True)
    state = {'directory': directory, 'calls': []}
    contract = snapshot()
    findings = (
        '현재 선택 A는 배색에 대한 애착만 있고, 원본의 합리적 가격 및 가족 겨울옷까지 찾아보는 매력이 빠져 있습니다. '
        'B의 여행 포기 갈등도 제품보다 여행 선택을 궁금하게 만듭니다. 단순 문장 보정이 아니라 제품 호기심 중심으로 '
        '세 안을 모두 재설계하세요. 원작의 제품 핵심: 노스페이스 패딩, 성인과 키즈라인, 높은 가격 부담과 '
        '10만원대라면 다시 찾아볼 만큼 구매 판단이 달라지는 매력. 흰 몸판과 검은 어깨 배색은 실제 검토한 외형입니다. '
        '가격과 가족 범위를 삭제해 스타일 일반론으로 축소하면 실패입니다. 그러나 지금 10만원대 판매나 '
        '할인/재고/정품/AS를 확인한 것은 아니므로 실제 핫딜을 발견했다거나 구매했다고 상품 사실로 발명하지 마세요. '
        '원본의 40만원 초과/10만원대 수치는 유지하려면 명확한 조건 문장(예: 10만원대라면)으로 쓰고, '
        '전부 가정 설명 강의로 늘어놓지 마세요. 조건부 쇼핑 판단은 자연스러운 소비자 말로 한 번 연결하세요. '
        '가격이 떨어지는데 구매가 더 어렵다는 인과 오류를 만들지 마세요. 키즈에도 정확히 같은 배색이나 '
        '같은 가격이 있다고 쓰지 않습니다. 가격조건/가족제품과 애착 또는 기회비용이 이야기 속에서 연결돼야 합니다. '
        'A는 소유효과, B는 기회비용 현저성을 주된 효과로 유지하되 서로 다른 갈등·정보 순서·결말로 새로 구성하세요. '
        '두 효과는 가격·가치 판단 카테고리이고 원작의 효과들과 다릅니다. 이름만 붙인 호감이나 선택 기준 강의는 안 됩니다. '
        'C만 원작의 심리·전개를 유지하고 인물·장소·계기·행동 중 최소2~3개를 의미 있게 바꾸세요. '
        'AS/택/키즈사이즈의 특징적인 나열과 문장·대사는 가져오지 않습니다. 댓글 요청을 삭제해도 어떤 제품을 '
        '왜 찾아보고 싶은지가 남아야 합니다. 기준/방법/예산상담 댓글이 아니라 이 패딩을 궁금하게 만드세요. '
        '썸네일도 두 줄의 짧은 문구로 가격 조건을 현재 확정 할인처럼 오해하게 하지 않으면서 제품에 관심을 모으세요. '
        '도현에서 깨진 중간점(·)과 이모지는 쓰지 말고 기본 한글·숫자·일반 문장부호를 씁니다. '
        '사연은 사용자 승인된 연출이며 changes에만 기록합니다. 소스 수나 확보 장면은 집필 입력·제약에 넣지 않습니다.')
    if args.revision==6:
        findings += (
            '추가 실제 검토: v5는 핵심 매력을 복원했지만 A의 애착을 세 번 설명하고 가족 탐색도 두 번 반복했습니다. '
            'A의 가격 조건이 뒤늦게 붙은 설명처럼 들립니다. 첫 후킹부터 특정 패딩을 조건부로 다시 보고 싶은 '
            '이유를 짧게 공개하고, 내 것으로 선택하기 전/후의 교환 아쉬움은 하나의 갈등으로만 보입니다. '
            'B도 가족옷을 미룬다는 설명과 아이옷 예산을 남긴다는 설명이 반복돼요. 하나의 포기 대상을 먼저 '
            '드러내고 제품 매력과 가격 조건이 그 갈등을 바꾸게 합니다. 아이 옷을 무조건 함께 살 수 있다고 '
            '금액 효과를 보장하지 마세요. C의 언니/도서관카페/겨울옷목록/온라인보류 변경과 원작 흐름은 유지합니다. '
            '세 안 모두 원작의 27초 내외처럼 간결한 소비자 말로 압축하세요. 고정 글자 수는 강요하지 않지만 '
            '같은 매력을 다른 표현으로 되풀이하지 않습니다. 강의형 40만원이면A/10만원이면B를 안마다 똑같이 '
            '낭독하지 마세요. 10만원대라면 조건은 해당 안에 한 번만 명확히 연결하고 후킹부터 길게 '
            '당시/가정/기준 해설을 하지 않습니다. 1·2안의 썸네일은 원작의 가격경고를 다시 베끼지 않고 '
            '각 새로운 심리 갈등을 담으며, 특정 패딩을 왜 찾아볼지 바로 이해되게 합니다.')
    payload = {'reference':evidence['reference_script'], 'caption':evidence['reference_caption'],
        'previous_scripts':previous['scripts'], 'original_analysis':previous['analysis'],
        'keyword':'노페', 'findings':findings}
    _atomic_json(directory/'input.json', payload)
    print('Official Codex: new jacket product-value A/B/C started',flush=True)
    value = codex_writer.chat(
        '항상 세 안을 함께 제안하고 이전 대본의 핵심 매력 누락을 고칩니다. '+findings+'\n\n'+contract['prompt'],
        json.dumps(payload,ensure_ascii=False),SCHEMA,lambda:None,state)
    _atomic_json(directory/'raw-triplet.json',value)
    validate_triplet(value)
    scripts=[]
    for variant in value['variants']:
        checked=review(variant['text'],evidence['reference_script'],keyword='노페',contract=contract)
        checked.update(**{k:v for k,v in variant.items() if k!='text'},human_review_pending=True)
        scripts.append(checked)
    _atomic_json(output,{'scripts':scripts,'analysis':{k:v for k,v in value.items() if k!='variants'},
        'writing_contract':receipt(contract),'generation_model':'codex-cli','calls':state['calls'],
        'human_findings':findings,'previous':str(previous_path),
        'human_review_pending':True,'comment_keyword':'노페'})
    print(f'New jacket v{args.revision} three scripts saved separately',flush=True)


if __name__=='__main__':main()
