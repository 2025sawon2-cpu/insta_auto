"""An additional editorial pass using the authorized official writing bridge."""
import json
from hotpost.writing import codex_writer
from hotpost.writing.contract import snapshot,receipt
from hotpost.writing.variants import SCHEMA,validate_triplet
from hotpost.writing.checks import review
from hotpost.editing_adapter import _atomic_json
from tools.recover_daily_materials import ROOT

CODES=('DeTaESASnr_','DeTJ6HbKCdF','DeSoiZvyyqj')
NOTES={
 'DeTaESASnr_':'1안의 실제 외출 준비 공감은 좋아요. 두 줄 썸네일은 지금보다 짧고 강하게 제품이 궁금하도록 보완해요. 2안은 관심 효과를 결과로 설명하지 않습니다.',
 'DeTJ6HbKCdF':'2안의 철수→다음 식사 순서와 짧은 동작의 심적 시뮬레이션은 좋아요. 썸네일은 두 번의 사용을 모두 설명하기보다 철수할 때 식탁을 끌고 가는 구체적인 동작의 궁금증을 만드세요. 1안의 고립 효과는 원작의 기대 위반에 이름만 바꾼 듯해요. 실제로 이질적인 요소를 구별되게 하거나, 원작이 쓰지 않은 다른 관심·기억 효과로 재설계하세요.',
 'DeSoiZvyyqj':'1안의 지난 사진/새 촬영 공간이라는 두 심적 계정은 좋지만 나눠보세요라는 강의와 셈이에요라는 설명 반복을 빼고 자연스러운 생활 이야기로 다듬으세요. 썸네일은 짧고 지난 사진을 옮기는 물건 자체가 궁금하도록 해요. 전체 폰 호환/SSD 동봉/자동 공간 확보를 단정하지 않고 SSD를 넣어 쓰는 케이스임을 구별합니다.'}

def main():
 for code in CODES:
  folder=ROOT/code/'writing';out=folder/'quality-v3.json'
  if out.exists():continue
  payload=json.loads((folder/'input.json').read_text('utf-8'))
  previous=json.loads((folder/'quality-v2.json').read_text('utf-8'))
  target=folder/'quality-v3';target.mkdir(exist_ok=True);state={'directory':target,'calls':[]};contract=snapshot()
  instruction=('제품별 1·2·3안 모두를 함께 제안하세요. 추가 편집 검토 의견을 반영해 간결한 약20~30초 원고와 '
   '짧은 두 줄 썸네일을 보완합니다. 원작 대사·문장·특징적인 설명 묶음은 복사하지 않고 1·2안은 서로 다르며 '
   '원작에 없는 같은 카테고리 효과로 갈등·정보 순서·끝맺음을 바꿉니다. 3안만 원작의 전개를 유지하면서 '
   '표면 요소2~3개를 의미 있게 바꿉니다. 제품이 궁금한 댓글만 유도해요. 이론을 말로 설명하거나 제품 장점 요약을 '
   '반복하지 않습니다. 원작의 일반 기능은 직접 말하되 새로운 수치·판매조건·효능 보장은 추가하지 않아요. '
   '촬영 자료 수는 집필에 영향을 주지 않습니다. 원작이쓴 효과 이름에 긴 설명을 붙여 새 효과처럼 속이지 말고 '
   '원작 분석과 실제 문구 작동이 맞아야 합니다. 현재/당시/미확인 같은 자료 한계는 낭독·썸네일에 넣지 말고 '
   'changes에 기록합니다.\n\n'+contract['prompt'])
  value=codex_writer.chat(instruction,json.dumps({'reference':payload['reference_script'],'caption':payload['reference_caption'],
    'previous':previous['scripts'],'analysis':previous['benchmark'],'findings':NOTES[code],
    'keyword':previous['comment_keyword'],'limits':payload['notes']},ensure_ascii=False),SCHEMA,lambda:None,state)
  validate_triplet(value)
  scripts=[]
  for v in value['variants']:
   checked=review(v['text'],payload['reference_script'],keyword=previous['comment_keyword'],contract=contract)
   checked.update(**{k:x for k,x in v.items() if k!='text'},variant_number=v['number'],
     psychological_category=v['category'],human_review_pending=True)
   scripts.append(checked)
  _atomic_json(out,{'scripts':scripts,'analysis':{k:v for k,v in value.items() if k!='variants'},
    'writing_contract':receipt(contract),'generation_model':'codex-cli','calls':state['calls'],
    'human_findings':NOTES[code],'human_review_pending':True})
  print(code+' quality-v3 three proposals saved',flush=True)

if __name__=='__main__':main()
