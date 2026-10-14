"""Portrait windows for the newly reviewed white/black jacket footage."""
import json
from tools import build_daily_rework as daily
from tools.build_tiktok_quality import ROOT,OLD,configure
from tools.rework_tiktok_batch import save

CODE='DeJ7hD6zsnR'


def main():
    configure();daily.ROOT=ROOT
    # Reuse a clearly identified kids example; do not fetch it again.
    ledger=ROOT/CODE/'discovery.json';rows=json.loads(ledger.read_text('utf-8'))
    old=json.loads((OLD/CODE/'discovery.json').read_text('utf-8'))
    kid=next(r for r in old['candidates'] if r['url'].endswith('/7450841635404975393'))
    matching=next((r for r in rows['candidates'] if r['url']==kid['url']),None)
    if matching is None:
        rows['candidates'].append({**kid,'reused_existing_download':True})
    elif not matching.get('path'):
        matching.update(path=kid['path'],video_meta=kid['video_meta'],reused_existing_download=True,
                        reuse_source_ledger=str(OLD/CODE/'discovery.json'))
    save(ledger,rows)
    daily.CLIPS[CODE]=[
        ('white-front','7552470327490514183',0.1,3.0,None,None,'흰 몸판·검은 어깨 배색 패딩을 입은 정면과 상체'),
        ('white-fit','7552470327490514183',4.0,7.2,None,None,'같은 흰/검정 배색 패딩의 전체 착용 핏'),
        ('white-detail','7552470327490514183',8.0,10.9,None,None,'손으로 흰 몸판과 소매를 보여주는 착용 모습'),
        ('outside-front','7497793685048872235',1.0,4.5,None,None,'야외에서 흰 몸판·검은 어깨 배색 패딩을 입은 앞모습'),
        ('outside-back','7497793685048872235',5.0,7.0,None,None,'같은 야외 착용자의 옆면과 뒷면'),
        ('outside-walk','7497793685048872235',8.1,10.8,None,None,'다른 각도에서 같은 배색 패딩을 입고 걷는 모습'),
        ('store-white','7173259157208911106',5.5,7.0,None,[.02,.02,.30,.05],'매장 안에서 흰 몸판·검은 어깨 배색 패딩 착용과 뒷모습. 정확한 SKU·진위는 미확인.'),
        ('kids-fit','7450841635404975393',12.0,16.0,None,None,'검은 키즈 패딩의 착용 예시. 성인용 흰/검정 배색과 같은 모델은 아님.'),
    ]
    daily.clips(CODE)


if __name__=='__main__':main()
