"""Today's recovery uses only the already connected collector TikTok tab."""
from tools import rework_tiktok_batch as batch
from tools.recover_daily_materials import ROOT

batch.ROOT = ROOT
batch.QUERIES = {
    'DeTaESASnr_': ['슬라이딩 자석 전신거울', 'magnetic sliding mirror silver board'],
    'DeSvpmAsWgZ': ['노스페이스 패딩 키즈', 'north face puffer jacket kids'],
    'DeTJ6HbKCdF': ['露营桌 推车 四态', 'camping table cart fold legs'],
    'DeSoiZvyyqj': ['folder SSD magnetic phone Hagibis', '폴더 모양 맥세이프 SSD',
                    '하기비스 폴더 SSD 맥세이프', 'HAGIBIS folder SSD phone'],
    'DeSngDcTAUJ': ['생선 굽기 전 바르는 재료', '생선 구이 코팅 재료'],
    'DeRFXHpEwck': ['다이소 미니 파일 벨크로 6매', 'A7 mini envelope hook loop', 'ミニ ファイル ベルクロ ダイソー',
                    'A7 6매입 파일홀더', '다이소 A7 파일홀더 찍찍이'],
}

if __name__ == '__main__':
    batch.main()
