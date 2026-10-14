"""Exercise the real three-variant pipeline against today's recovered narration."""
import json
from pathlib import Path

from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json
from hotpost.writing.contract import snapshot
from hotpost.writing.pipeline import generate
from tools.recover_daily_materials import ROOT,CODES


def main():
    settings=load_settings()
    report=json.loads(settings.report_path.read_text('utf-8'))
    posts={p['shortcode']:p for p in report['posts']}
    for code in CODES:
        output=ROOT/code/'writing';output.mkdir(exist_ok=True)
        destination=output/'variants.json'
        if destination.exists():continue
        receipt=json.loads((ROOT/code/'transcript-recovery.json').read_text('utf-8'))
        reference=json.loads((Path(receipt['directory'])/'transcript.json').read_text('utf-8'))
        text=' '.join(r['text'] for r in reference['speech'])
        notes=('실제 전사를 참고하되 인식 오타는 화면과 본문으로만 확인합니다. '
            '원문 문장·특징적인 설명 묶음을 복사하지 않습니다. 썸네일도 2줄의 구체적인 제품 궁금증을 만드세요. '
            '주어진 참고는 현재 가격·재고·AS를 확인한 것이 아닙니다. 최저가·품절·AS를 보장하거나 '
            '실제로 할인 정보 DM을 보내겠다는 약속을 넣지 않습니다. 댓글은 제품 자체에 대한 궁금증으로 연결하세요.')
        if code=='DeSngDcTAUJ':
            notes+=' 원본에서 재료 이름은 확인되지 않았으므로 미림·맛술 등으로 임의 특정하지 않습니다. 비린내 완벽 차단, 100% 수분 차단은 입증된 사실로 쓰지 마세요.'
        if code=='DeSoiZvyyqj':
            notes+=' 폴더 모양 SSD 케이스의 매력과 작은 물건 휴대·사진 보관을 구분하세요. SSD 동봉·용량·모든 폰 호환을 임의로 보장하지 않습니다.'
        payload={'reference_script':text,'reference_kind':'speech','reference_caption':posts[code]['caption'],
                 'notes':notes,'writing_contract':snapshot()}
        _atomic_json(output/'input.json',payload)
        _atomic_json(output/'execution.json',{'status':'running','code':code})
        print(code+' three-variant writing started',flush=True)
        try:
            result=generate(payload,output,lambda:None,lambda pct,msg:print(code+' '+msg,flush=True))
            _atomic_json(destination,result)
            _atomic_json(output/'execution.json',{'status':'done','code':code,'scripts':len(result['scripts'])})
            print(code+' three variants saved',flush=True)
        except Exception as exc:
            _atomic_json(output/'execution.json',{'status':'error','code':code,'error':str(exc)})
            print(code+' writing error: '+str(exc),flush=True)


if __name__=='__main__':main()
