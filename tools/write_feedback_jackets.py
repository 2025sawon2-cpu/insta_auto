"""Official contract-bound three proposals for the two jacket feedback cases."""
import argparse,json
from pathlib import Path
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.editing_adapter import _atomic_json
from hotpost.writing.contract import snapshot
from hotpost.writing.pipeline import generate

ROOT=Path('data/user-feedback-revisions-20261011').resolve()
WORKS={'DeJ7hD6zsnR':'work-7de866f1dc7d4e71','DeSvpmAsWgZ':'work-ea4d11c896714ac1'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--code',choices=list(WORKS));args=parser.parse_args()
    studio=Studio(load_settings(),workers=False)
    for code in ([args.code] if args.code else WORKS):
        folder=ROOT/code/'writing';folder.mkdir(parents=True,exist_ok=True)
        out=folder/'quality.json'
        if out.exists():print('Preserved '+code,flush=True);continue
        state=studio.store.get(WORKS[code])
        previous=next(s['text'] for s in state['scripts'] if s['id']==state['script_id'])
        notes=('사용자의 완성 영상 피드백을 반영한 재설계. 각 안은 공백 정리 후 230자 이내로 '
            '자연스럽게 짧게 써서 목소리 전체가 한 번에 합성되도록 한다. 문장을 잘라 생략하거나 '
            '글자 수를 맞추려고 의미를 모호하게 하지 않는다. 원작의 노스페이스 패딩, '
            '가격 부담 대비 관심이 달라지는 매력, 성인/키즈 탐색은 유지한다. 현재 가격 판매를 '
            '입증하지 않았으므로 10만원대는 사용하려면 한 번의 명확한 조건으로만 표현한다. '
            '키즈도 같은 배색/같은 가격이라고 발명하지 않는다. 원문의 택/AS/키즈사이즈 '
            '특징적 묶음을 복사하지 않는다. 흰 몸판과 검은 어깨는 기존 검토된 외형. '
            '이전 대본은 지시어가 모호하고 가정/애착/가족 탐색을 억지로 붙여 무슨 말인지 '
            '이해하기 어렵다. 주제 하나, 구체적 갈등 하나, 제품의 매력과 결과가 즉시 이해되도록 '
            '새로 쓴다. 마음을 접었다 풀었다/후보를 내준다/제 건 이걸 놓고 같은 추상적 말은 '
            '설명하지 말고 명확한 행동으로 바꾼다. 편향 이름은 분석에만 쓰고 소비자 말로 낭독한다. '
            'A/B는 원작이 쓰지 않은 서로 다른 편향으로 전개를 새로 설계. C만 흐름을 유지하고 '
            '표면2~3개를 의미 있게 치환. 댓글 요청을 빼도 특정 패딩을 궁금해할 이유가 남는다. '
            '대본 3안 및 각각 두 줄 후킹 문구를 함께 제공하며 소스 수·편집 길이는 입력 제약이 아니다. '
            '기존 원고: '+previous)
        payload={'reference_script':state.get('reviewed_original_text',state['original_text']),
                 'reference_kind':state.get('reference_kind','speech'),'reference_caption':state['title'],
                 'comment_keyword':'나도' if code=='DeJ7hD6zsnR' else '노페',
                 'notes':notes,'writing_contract':snapshot()}
        _atomic_json(folder/'input.json',payload)
        result=generate(payload,folder,lambda:None,
            lambda pct,message:print(code,round(pct*100),message,flush=True))
        _atomic_json(out,result)
        print(code,json.dumps([s['text'] for s in result['scripts']],ensure_ascii=False),flush=True)

if __name__=='__main__':main()
