"""A bounded spoken-language repair, retaining all three earlier proposals."""
import json
from hotpost.writing import codex_writer
from hotpost.writing.checks import review
from hotpost.writing.variants import SCHEMA,validate_triplet
from hotpost.writing.contract import snapshot,receipt
from hotpost.editing_adapter import _atomic_json
from tools.refine_tiktok_quality import ROOT


def main():
    folder=ROOT/'DeJ7hD6zsnR/writing';out=folder/'quality-final.json'
    if out.exists():return
    previous=json.loads((folder/'quality.json').read_text('utf-8'));contract=snapshot()
    target=folder/'spoken-repair';target.mkdir(exist_ok=True);state={'directory':target,'calls':[]}
    instruction=('세 안을 모두 함께 반환하되 실제 낭독이 자연스러운 제품 추천이 되도록 보완하세요. '
        '1안의 예산을 사십만 원 잡았다고 해볼게요, 2안의 제 옷이면/이미 제 옷이라면 반복은 가정 강의처럼 들립니다. '
        'A의 심적 회계, B의 소유효과, C의 원작 흐름은 유지하되 말투와 전개를 보완합니다. '
        'A는 숫자 가정 없이 여윳돈일 때와 아이 겨울옷 몫일 때의 지출 의향 차이를 자연스러운 생활 이야기로 '
        '제품 자체와 연결하세요. 실제 할인/현재 가격을 만들지 않습니다. B는 그냥 마음에 든다는 호감이 아니라 '
        '고르기 전에는 같은 값의 대체 패딩도 괜찮았으나 내 것으로 고른 뒤 교환을 꺼리는 소유 전후 판단 차이를 '
        '연출 사연으로 보여주세요. 연출 사연을 위해 장바구니·선택·교환 제안·대사를 바꿀 수 있으며 '
        '낭독에 가정이나 연출 해설을 반복할 필요가 없습니다. 실제 구매/재고/할인 검증으로 기록하지 않습니다. '
        '흰 몸판과 검은 어깨의 구체적인 제품 외형은 참고 첫 프레임 근거가 있으므로 유지하되 키즈에 정확히 같은 '
        '디자인이 판매 중이라고 단정하지 않습니다. C의 금액은 실제 판매가가 아니라 가정임이 문장에 드러나게 '
        '유지하며 원문 대사를 재사용하지 않습니다. 썸네일은 두 줄의 짧은 제품 갈등으로 궁금증을 남기고 '
        '가격 조건을 현재 사실처럼 보이게 쓰지 않습니다. 글자 수나 장면 수로 제한하지 말고 간결한 약20초의 '
        '연결된 구어체로 씁니다. 세 안의 동일한 기능 요약 반복, 선택 기준·심리학 강의는 제거하세요.\n\n'+contract['prompt'])
    value=codex_writer.chat(instruction,json.dumps({'reference':previous['reference'],'drafts':previous['scripts'],
        'analysis':previous['analysis']},ensure_ascii=False),SCHEMA,lambda:None,state)
    validate_triplet(value);scripts=[]
    for v in value['variants']:
        checked=review(v['text'],previous['reference']['reference'],keyword=previous['reference']['comment_keyword'],contract=contract)
        checked.update(**{k:x for k,x in v.items() if k!='text'},human_review_pending=True);scripts.append(checked)
    _atomic_json(out,{**previous,'scripts':scripts,'analysis':{k:v for k,v in value.items() if k!='variants'},
        'writing_contract':receipt(contract),'calls':previous['calls']+state['calls'],'human_review_pending':True,
        'revision':'spoken-repair','previous':str(folder/'quality.json')})
    print('Jacket A/B/C spoken repair saved separately',flush=True)


if __name__=='__main__':main()
