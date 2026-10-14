"""Scoped three-variant writing through the existing official Codex CLI bridge."""
import json
from pathlib import Path
import subprocess
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.writing import codex_writer
from hotpost.writing.contract import snapshot, receipt
from tools.rework_tiktok_batch import ROOT, QUERIES, save


def obj(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
string = {'type':'string'}
variant = obj({'number':{'type':'integer','enum':[1,2,3]},'type':string,'bias':string,'category':string,
    'changes':string,'text':string,'thumbnail_lines':{'type':'array','items':string,'minItems':2,'maxItems':2},
    'thumbnail_mechanism':string})
item = obj({'code':string,'original_mechanisms':{'type':'array','items':string},'original_hook_analysis':string,
    'variants':{'type':'array','items':variant,'minItems':3,'maxItems':3},
    'recommended_variant':{'type':'integer','enum':[1,2]},'selection_reason':string})
schema = obj({'items':{'type':'array','items':item,'minItems':3,'maxItems':3}})


def main():
    settings=load_settings(); studio=Studio(settings,workers=False)
    contract=snapshot(); folder=ROOT/'writing';folder.mkdir(parents=True,exist_ok=True)
    inputs=[];images=[]
    for code in QUERIES:
        st=next(st for st in studio.store.list() if st['shortcode']==code)
        reference=(st.get('reference_text_evidence') or {}).get('text') or st.get('original_text','')
        inputs.append({'code':code,'title':st['title'],'reference':reference,
            'reference_kind':st.get('reference_kind'),'comment_keyword':(st.get('benchmark_analysis') or {}).get('comment_keyword','나도')})
        image=folder/(code+'-reference-first.jpg')
        subprocess.run(['ffmpeg','-v','error','-y','-i',st['reference_video'],'-frames:v','1',str(image)],capture_output=True,check=True)
        images.append(image)
    save(folder/'inputs.json',inputs)
    state={'directory':folder,'calls':[]}
    instruction=('첨부 이미지는 입력 순서대로 각 원본의 첫 프레임입니다. 세 제품 각각 1,2,3안 모두를 한 번에 작성하세요. '
        '1안 유형전환 A, 2안 유형전환 B, 3안 표면치환형입니다. 1·2안은 원작이 사용하지 않은 서로 다른 같은 카테고리의 심리효과를 '
        '사용하며 소재·제품 매력만 유지하고 도입·갈등·정보 공개 순서·마무리를 재설계하세요. 3안만 메커니즘·전개를 유지하되 '
        '인물·장소·계기 중 적용 가능한 요소 2~3개를 의미 있게 바꿉니다. 원문 문장과 특징적인 설명 묶음을 복사하지 마세요. '
        '첫 프레임의 후킹을 심리적으로 분석하고, 새 썸네일 두 줄은 제품 정보를 왜곡하지 않고 다른 적용으로 호기심을 만들어야 합니다. '
        '댓글은 제품이 궁금해서 달도록 하고 기준·방법을 알려주는 대본으로 끝내지 마세요. 각 안은 자연스럽게 약 20~30초 분량으로 '
        '간결하게 쓰되 길이 맞추려고 반복하지 마세요. 할인·품절·현재가격·환불·매장택·AS·인기 등을 묶어 원작 순서대로 복사하지 '
        '마세요. 2026-10-11 현재 판매 조건을 확인한 것이 아니므로 현재 최저가·시즌·재고·AS 보장으로 단정하지 않습니다. '
        '수면·난방비 절약 효과는 보장하지 말고 빛·찬바람 차단이라는 실제 기능을 중심으로 씁니다. '
        '화면에 브랜드를 보여도 댓글로 제품 자체를 찾고 싶은 이유를 남기세요. recommended_variant는 1 또는 2 중 좋은 안을 선택합니다. '
        '각 제품 3개 안의 의미 차이가 있는지와 CTA를 빼도 제품 호기심이 남는지 스스로 검사한 최종안을 반환하세요.\n\n'+contract['prompt'])
    result=codex_writer.chat(instruction,json.dumps(inputs,ensure_ascii=False),schema,lambda:None,state,images=images)
    result['writing_contract']=receipt(contract)
    result['calls']=state['calls']
    save(folder/'variants.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
