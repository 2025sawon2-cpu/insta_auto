"""Targeted quality repair of the scoped three-variant draft set."""
import json
from hotpost.writing import codex_writer
from hotpost.writing.contract import snapshot
from tools.generate_tiktok_rework_variants import schema
from tools.rework_tiktok_batch import ROOT,save

folder=ROOT/'writing'
previous=json.loads((folder/'variants.json').read_text('utf-8'))
inputs=json.loads((folder/'inputs.json').read_text('utf-8'))
save(folder/'variants-before-review.json',previous)
state={'directory':folder,'calls':[]}
instruction=('3제품×3안 전체를 같은 출력 형식으로 보완하세요. 메커니즘과 3안 유형 구분을 유지하되 실제 낭독이 제품 추천처럼 들려야 합니다. '
    '패딩 대본의 현재/과거 판매정보 주의 문구, 예전에, 당시, 별도 확인 필요 같은 메타 해설을 낭독문과 썸네일에서 모두 빼세요. '
    '현재 최저가/재고/AS/할인 보장도 금지합니다. 그런 한계는 비교페이지의 출처 설명에 남깁니다. 원본 가격 숫자를 단순히 과거 '
    '회상으로 돌려넣지 말고, 구체적인 어른·키즈 패딩 제품을 보고 싶게 만드는 가족 예산/선택 갈등을 새로 설계하세요. '
    '1·2안은 추상적인 예산 관점 강의, 구매 선택기준 강의, 말하려는 게 뭔지 모를 교훈으로 끝나면 실패입니다. '
    '제작용은 1·2안 중 제품의 눈에 보이는 매력이 분명하고 댓글에 그 제품을 찾을 이유가 강한 것을 선택합니다. '
    '새로 만든 인물·생활 상황은 연출임을 changes에만 적고 낭독에 설정 설명을 넣지 마세요. 확인되지 않은 구매 경험으로 기록하지 않습니다. '
    '텐트는 방 전체 불을 끄지 않고 침대 주변만 가리는 구체적인 편의를 전개해 같은 기능을 반복 설명하지 마세요. '
    '파일 홀더도 파일박스나 대형 서류함과 구별되는 작은 포켓·벨크로·휴대/수납 매력을 앞에 넣으세요. '
    '시청자가 이미 안다는 듯 단정하지 말고 짧고 강렬하게 제품 궁금증을 만드세요. 이전안의 3안 표면치환은 최소2~3의 의미 있는 설정 변화와 '
    '원작의 메커니즘/진행을 유지하되 세부 설명 묶음을 그대로 복사하지 않습니다. 각안 약20~30초, 원작 문장복사 금지. '
    '썸네일 2줄은 짧고 굵게 읽히는 후킹문구로, 원작 심리후킹을 분석한 뒤 다른 적용을 만들고 제품내용을 왜곡하지 마세요.\n\n'+snapshot()['prompt'])
result=codex_writer.chat(instruction,json.dumps({'references':inputs,'previous':previous['items']},ensure_ascii=False),schema,lambda:None,state)
result['writing_contract']=previous['writing_contract']
result['calls']=previous['calls']+state['calls']
save(folder/'variants.json',result)
print(json.dumps(result['items'],ensure_ascii=False),flush=True)
