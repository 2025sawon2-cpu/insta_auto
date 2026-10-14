import json
from hotpost.writing import codex_writer
from hotpost.writing.contract import snapshot
from tools.generate_tiktok_rework_variants import item
from tools.rework_tiktok_batch import ROOT,save
folder=ROOT/'writing'; previous=json.loads((folder/'variants.json').read_text('utf-8'))
ref=next(x for x in json.loads((folder/'inputs.json').read_text('utf-8')) if x['code']=='DeJ7hD6zsnR')
old=next(x for x in previous['items'] if x['code']==ref['code'])
state={'directory':folder/'jacket-repair','calls':[]};state['directory'].mkdir(exist_ok=True)
instruction=('패딩 3안만 다시 작성하세요. 이전 A는 추상적 예산 강의로 제품이 궁금하지 않아 실패입니다. '
 'B도 소유효과를 제품에 구체적으로 연결하세요. A/B는 원작이 쓰지 않은 서로 다른 가치판단 카테고리 편향으로 전체 전개 재설계. '
 '원본 핵심 매력은 브랜드 패딩을 합리적 가격으로 가족용까지 찾아볼 수 있다는 점입니다. 가격을 지워 매력을 없애지 마세요. '
 '원본의 40만원·10만원대 정보는 비교의 출발점으로 사용할 수 있으나 현재 모든 제품의 고정 가격·최저가·지금 대란·AS·재고 보장으로 단정하지 않습니다. '
 '조건부 구체적 쇼핑 상황으로 충분히 자연스럽게 표현할 수 있습니다. 가격확인 안내·주의사항·기준 설명을 낭독하지 마세요. '
 '댓글을 빼도 이 제품과 어디서 찾아볼 수 있는지 궁금해야 합니다. 내레이션 약20~25초, 짧은 2줄 후킹 썸네일. '
 '1인칭 장면은 연출로 changes에 기록해도 됩니다. C는 원작 흐름/심리를 유지하되 최소2~3요소 변경, 특징적 택/AS/키즈 나열 복사 금지.\n'+snapshot()['prompt'])
result=codex_writer.chat(instruction,json.dumps({'reference':ref,'previous':old},ensure_ascii=False),item,lambda:None,state)
previous['items']=[result if x['code']==result['code'] else x for x in previous['items']]
previous['calls']+=state['calls'];save(folder/'variants.json',previous);print(json.dumps(result,ensure_ascii=False),flush=True)
