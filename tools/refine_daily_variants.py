"""Additional user-requested quality pass; keep the first drafts and all receipts."""
import json
from hotpost.editing_adapter import _atomic_json
from hotpost.writing import codex_writer
from hotpost.writing.contract import snapshot,receipt
from hotpost.writing.checks import review
from hotpost.writing.reference_evidence import choose_keyword
from hotpost.writing.variants import SCHEMA,validate_triplet
from tools.recover_daily_materials import ROOT,CODES

FINDINGS={
 'DeTaESASnr_':'1안에서 공간 통합 이득이 도입·중간·결말에 반복돼요. 한 번만 말하고 외출 직전의 구체적인 공감을 살리세요. 2안의 썸네일은 설명문이라 호기심이 약해요. 댓글이나는 키워드가 아니라 조사이므로 기본 나도를 씁니다.',
 'DeSvpmAsWgZ':'세 안 모두 참고 당시·현재 검증 등의 해설과 원작의 정품/AS/사이즈 묶음이 남아 품질이 낮아요. 판매조건 안내는 낭독에서 빼고 제품 호기심과 새 갈등을 살리세요. 2안은 평가 기준 강의라면 실패입니다. 가격을 써야 한다면 10만 원대에 볼 수 있다면 같은 가정만 쓰고 현재 가격인 듯한 썸네일은 금지해요.',
 'DeTJ6HbKCdF':'식사와 철수의 전환은 좋은데 마지막에 같은 운반 기능을 다시 평가하는 해설이 반복돼요. 이미 보인 이득은 반복하지 마세요. 3초라는 홍보 숫자를 굳이 강제하지 말고 다리를 접어 카트로 변하는 기능을 중심에 둡니다.',
 'DeSoiZvyyqj':'1안은 과거 사진과 오늘 쓸 공간을 나누는 심적 회계가 선명해요. 2안의 장식인 줄 알았는데 실용적이었다는 정체 반전은 앵커링을 실제로 작동시켰다는 근거가 약해요. 가격/용량 숫자를 발명하지 말고 같은 카테고리의 평가 가능성 등 적합한 다른 효과로 전개를 새로 만드세요. 특정 폰 호환·SSD 동봉은 단정하지 않아요.',
 'DeSngDcTAUJ':'2안은 효과의 결과인 기억을 직접 설명하고 음식/재료 대비도 억지예요. 시청자의 음식 경험이나 제품에 관한 짧은 갈등에서 효과가 자연스럽게 작동해야 합니다. 재료명은 확인 안 됐으므로 특정하지 않고 비린내 완벽 차단·절대 효과는 쓰지 않아요. 두 줄 썸네일은 지금보다 짧게 읽혀야 해요.'}


def main():
 for code in CODES:
  folder=ROOT/code/'writing';destination=folder/'quality-v2.json'
  if destination.exists():continue
  original=json.loads((folder/'variants.json').read_text('utf-8'))
  payload=json.loads((folder/'input.json').read_text('utf-8'))
  keyword=choose_keyword(payload['reference_script'],payload['reference_caption'])[0] or '나도'
  target=folder/'quality-v2';target.mkdir(exist_ok=True);state={'directory':target,'calls':[]};contract=snapshot()
  instruction=('사용자가 실제 결과물의 지속 개선을 요청한 추가 품질 보완입니다. 원본과 1차 세 안, 구체적인 검토 의견을 읽고 '
    '제품마다 항상 1·2·3안을 함께 보완하세요. 원문 문장·대사·특징적인 설명 묶음은 복사하지 않습니다. '
    '실제 20~30초 쇼츠처럼 간결하게 한 갈등을 전개하고 같은 기능·이득을 다른 말로 반복하지 않습니다. '
    '1·2안은 같은 심리 카테고리에서 원작이 쓰지 않은 서로 다른 효과가 실제 문구와 정보 순서에 작동해야 해요. '
    '3안만 원작 메커니즘·흐름을 유지하고 표면 요소 2~3개를 의미 있게 바꿉니다. '
    '효과 이름은 홍보 설명이 아니라 실제 작동을 설명하는 정확한 심리 메커니즘으로 쓰세요. '
    'original_mechanisms에는 이름만 쓰고 근거 설명은 original_hook_analysis에 따로 씁니다. '
    '낭독과 썸네일에는 당시/참고/소개됐어요/현재 미확인 같은 자료 해설을 넣지 않아요. '
    '불확실한 조건은 삭제하거나 가정으로만 말하고 한계는 changes에 적으세요. '
    '원작의 일반 기능은 직접 쓰고 일반 기능까지 전언으로 돌리지 않습니다. '
    '썸네일은 반드시 두 줄이며 길게 설명하지 않고, 원작의 심리 후킹을 다른 적용으로 바꾸어 제품 자체가 궁금하게 해요. '
    '새 생활 상황·1인칭 연출은 changes에 기록하고 낭독에 설정 설명을 붙이지 마세요. '
    '자료보다 제품을 말하며, 댓글 요청을 빼도 제품을 찾아보고 싶은 이유가 남아야 합니다. '\
    '\n\n'+contract['prompt'])
  data={'reference':payload['reference_script'],'caption':payload['reference_caption'],'comment_keyword':keyword,
        'previous':original['scripts'],'original_analysis':original['benchmark'],
        'human_findings':FINDINGS[code],'reference_limits':payload['notes']}
  _atomic_json(target/'input.json',data);print(code+' quality revision started',flush=True)
  try:
   value=codex_writer.chat(instruction,json.dumps(data,ensure_ascii=False),SCHEMA,lambda:None,state)
   validate_triplet(value)
   candidates=[]
   for v in value['variants']:
    c=review(v['text'],payload['reference_script'],keyword=keyword,contract=contract)
    c.update(**{k:x for k,x in v.items() if k!='text'},variant_number=v['number'],
        psychological_category=v['category'],human_review_pending=True)
    candidates.append(c)
   result={'type':'scripts','scripts':candidates,'benchmark':{'analysis':{k:v for k,v in value.items() if k!='variants'}},
       'writing_contract':receipt(contract),'generation_model':'codex-cli','calls':state['calls'],
       'human_findings':FINDINGS[code],'comment_keyword':keyword,'human_review_pending':True}
   _atomic_json(destination,result);print(code+' revised three variants saved',flush=True)
  except Exception as exc:
   _atomic_json(target/'failure.json',{'error':str(exc)});print(code+' quality revision error '+str(exc),flush=True)

if __name__=='__main__':main()
