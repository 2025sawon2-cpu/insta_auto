"""Apply specific observed alternate views to the remaining video-3 findings."""
import json
from pathlib import Path
from hotpost.editing_adapter import _atomic_json

ROOT=Path('data/user-feedback-revisions-20261011/DeJ7hD6zsnR').resolve()

def main():
    plan=json.loads((ROOT/'final-v2/timeline.json').read_text('utf-8'))
    alternatives={'beat-11':('shot-11-1','직접 검토한 남색 패딩의 뒷면 착장. 개인 사이즈 탐색 상황의 다른 후보 예시이며 흰 배색 동일 SKU의 증거가 아님.'),
        'beat-14':('shot-18-1','직접 검토한 어린이의 보라색 노스페이스 패딩 착용. 별도 키즈 라인 예시이며 같은 흰 배색 판매를 주장하지 않음.'),
        'beat-18':('shot-5-1','직접 검토한 야외 흰 몸판·검은 어깨 패딩의 뒷면. 거울 셀카 반복 대신 다른 각도를 사용.')}
    for b in plan['beats']:
        if b['id'] in alternatives:
            shot,reason=alternatives[b['id']]
            b['options']=[{'shot_id':shot,'relation':'context','reason':reason,'reviewed':True}]
            b['selected_shot_id']=shot
        b.pop('source_start',None);b.pop('source_end',None)
    plan['cover_spec'].pop('source',None)
    out=ROOT/'final-v3';out.mkdir(exist_ok=True)
    _atomic_json(out/'prepared-plan.json',plan)

if __name__=='__main__':main()
