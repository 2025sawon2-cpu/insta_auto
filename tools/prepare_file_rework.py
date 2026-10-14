"""Explicitly distinguish alternate mini pockets from velcro detail examples."""
from pathlib import Path
from tools.rework_tiktok_batch import ROOT,save
from tools.build_selected_three import read,root as old_root
c='DeRFXHpEwck';d=read(ROOT/c/'discovery.json');old=read(old_root(c)/'prepared-plan.json')['sources'][1]
from hotpost.source_finder import probe_video
save(ROOT/c/'supplemental-sources.json',[{'url':'local-reviewed-source/old-velcro-detail','original_url':old['origin_url'],'provider':'youtube','title':'기존 검토 소스의 벨크로 구조 설명 구간','path':old['original_path'],'video_meta':probe_video(Path(old['original_path'])),'selected':False,'rights':old.get('rights','unknown-check-before-reuse'),'context_only':True,'outside_tiktok_discovery':True}])
defs=[
 ['pink-open','7626973899581885714',3,7,None,'작은 분홍 포켓을 손으로 펼침. 다른 미니 홀더의 활용 예시'],
 ['paper-in','7626973899581885714',7,9.7,None,'작은 카드형 종이를 분홍 포켓 안에 넣는 동작. 활용 예시'],
 ['mini-pouch','7626973899581885714',32,35,None,'작은 분홍 포켓을 손에 들고 보여줌. 활용 예시'],
 ['card-in','7626973899581885714',36,39.5,None,'작은 카드형 포장을 미니 홀더에 넣는 동작. 활용 예시'],
 ['bag-search','7644330163580177684',2.9,4,[0,.30,1,1],'가방 안의 작은 물건을 찾는 생활 상황'],
 ['bag-next','7644330163580177684',4,6.2,[0,.30,1,1],'가방 옆의 작은 쿠폰과 소품을 챙기는 생활 상황'],
 ['bag-carry','7644330163580177684',23,24.5,[0,.30,1,1],'다른 수납 포켓을 가방 안에 넣는 활용 예시'],
 ['velcro','old-velcro-detail',14.6,15.8,[.47,0,.98,1],'다른 봉투형 파일의 벨크로 구조 설명용 확대 장면'],
 ['velcro-close','old-velcro-detail',15.8,17.5,[.47,0,.98,1],'다른 봉투형 파일의 벨크로를 손으로 잡는 구조 설명용 확대 장면'],
 ['capacity','7686286964064079124',7,10.5,[0,.12,1,.75],'다른 미니 수납 포켓의 여러 칸을 펼쳐 보여주는 활용 예시'],
 ['pocket-end','7686286964064079124',18,21.5,[0,.12,1,.75],'다른 미니 수납 포켓을 닫는 활용 예시'],
]
save(ROOT/c/'clip-definitions.json',defs)
