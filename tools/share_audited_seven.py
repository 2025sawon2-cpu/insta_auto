"""Publish only the seven selected, inspected outputs and current three proposals."""
import argparse,json,shutil
from pathlib import Path
from PIL import Image
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.editing_adapter import _atomic_json as save
from hotpost.source_quality import sha256_file
from tools import share_daily_rework as public

OUT=Path('data/quality-scope-audit-20261011-v1').resolve()
TITLES={'DeRIBMYzn0x':'침대 암막 텐트','DeRFXHpEwck':'미니 파일 홀더 · 봉투 수납 장면 수정',
    'DeJ7hD6zsnR':'노스페이스 패딩 · 선택과 소유효과','DeSoiZvyyqj':'실물 폴더 저장 케이스 · USB 사용',
    'DeTaESASnr_':'슬라이딩 자석 보드 전신거울','DeTJ6HbKCdF':'테이블 카트',
    'DeSvpmAsWgZ':'노스페이스 패딩 · 가격 조건과 가족 탐색'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--version',choices=['v1','v2'],default='v1');args=parser.parse_args()
    studio=Studio(load_settings(),workers=False)
    rows=json.loads((OUT/'inventory.json').read_text('utf-8'))['rows'];inputs=OUT/'share-input'
    selection_path=OUT/('shared-current-selection.json' if args.version=='v1' else 'shared-current-selection-v2.json')
    if selection_path.exists():raise RuntimeError('This selection already has a share; preserve it.')
    current=[]
    for row in rows:
        state=studio.store.get(row['task_id']);edit=next(e for e in state['edits'] if e['id']==state['edit_id'])
        expected='a7-envelope-alignment-20261011-v7' if row['code']=='DeRFXHpEwck' else row['edit_id']
        assert state['edit_id']==expected
        final=Path(edit['plan_path']).parent;qa=json.loads((final/'verification.json').read_text('utf-8'))
        assert qa['actual_visual_review'] and not qa['visual_review_pending']
        poster=final/'comparison-poster.jpg'
        if not poster.exists():Image.open(final/'cover.png').convert('RGB').save(poster,quality=95)
        target=inputs/row['code'];(target/'final').mkdir(parents=True,exist_ok=True);(target/'writing').mkdir(exist_ok=True)
        for name in ['cover.png','verification.json','timeline.json']:shutil.copy2(final/name,target/'final'/name)
        writing=Path(state['quality_revision_path']) if state.get('quality_revision_path') else final.parent/'writing/quality-v3.json'
        shutil.copy2(writing,target/'writing/quality.json')
        current.append({'code':row['code'],'task_id':state['id'],'edit_id':state['edit_id'],
            'plan_path':str(final/'timeline.json'),'render_path':edit['export_path'],
            'render_sha256':sha256_file(Path(edit['export_path'])),'writing_path':str(writing),
            'writing_sha256':sha256_file(writing)})
    save(selection_path,current)
    public.ROOT=inputs;public.TITLES.update(TITLES)
    public.main(codes=tuple(TITLES),port=8817 if args.version=='v1' else 8818,
        receipt_name='quality-audited-seven-20261011-share.json' if args.version=='v1' else 'quality-audited-seven-20261011-v2-share.json',
        writing_revisions={code:'quality.json' for code in TITLES},review_codes=tuple(TITLES),lazy_media=True,
        snapshot_suffix='' if args.version=='v1' else 'gallery-v2')

if __name__=='__main__':main()
