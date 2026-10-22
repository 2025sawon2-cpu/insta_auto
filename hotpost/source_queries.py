"""근거가 있는 제품·브랜드·특징을 언어와 검색 의도별로 확장한다.

브랜드/품번은 관측된 텍스트에서만 추출한다. 사전에 없는 제품의 번역을 만들어내지 않는다.
"""
from __future__ import annotations

import re
from itertools import zip_longest

PRODUCTS = [
    ('밥도그', 'rice hot dog', '米饭热狗', ('밥도그', '밥 핫도그', 'rice hot dog', 'rice dog', '米饭热狗')),
    ('스팀 청소기', 'steam cleaner', '蒸汽清洁机', ('스팀청소기', '스팀 청소기', 'steam cleaner', '蒸汽清洁机', '蒸汽清洁器', '蒸汽清洗机')),
    ('사과', 'apple', '苹果', ('사과', 'apple', '苹果')),
    ('얼룩 제거제', 'stain remover', '去渍剂', ('얼룩제거제','얼룩 제거제','기름얼룩','기름 얼룩','stain remover','去渍剂')),
    ('폴로 니트', 'polo sweater', 'Polo针织衫', ('폴로니트','폴로 니트','polo sweater','polo knit','Polo针织衫')),
    ('니트', 'sweater', '针织衫', ('니트','sweater','针织衫')),
    ('사진 냉장고 자석', 'DIY photo fridge magnets', '照片冰箱贴制作', ('사진 자석', '냉장고 자석', 'photo fridge magnet', 'photo magnet', '照片冰箱贴')),
    ('스카치 매직테이프 디스펜서', 'Scotch Magic Tape dispenser', 'Scotch 隐形胶带 胶台', ('스카치 매직', '마카롱 디스펜서', 'macaron dispenser', 'Scotch Magic Tape', '马卡龙胶台', '馬卡龍膠台')),
    ('차량 후면 텐트', 'car rear tent', '车尾帐篷', ('차 뒤에 달고', 'car rear tent', 'hitch tent', '车尾帐篷')),
    ('자동 감김 빨랫줄', 'retractable clothesline', '伸缩晾衣绳', ('자동 감김 빨랫줄', '줄이 상자 안으로', 'retractable clothesline', '伸缩晾衣绳')),
    ('다진 마늘 준비', 'minced garlic preparation', '蒜末准备', ('다진마늘', '다진 마늘', '마늘보관', '마늘 보관', 'minced garlic', 'garlic storage', '蒜末')),
    ('발 전용 핫팩', 'foot warmer wrap', '暖脚贴', ('발바닥 핫팩', '발 전용 핫팩', '전용 핫팩', 'foot warmer', '暖脚贴')),
    ('투두 리스트', 'DIY checklist board', '自制待办清单板', ('투두', '투두리스트', 'to do list', 'checklist board', '待办清单')),
    ('분사형 유리 청소기', '3 in 1 spray squeegee', '三合一喷水玻璃刮', ('분사부터 문지르기', '3in1', 'spray squeegee', '喷水玻璃刮')),
    ('신발장', 'shoe cabinet demonstration', '鞋柜演示', ('신발장', 'shoe cabinet', '鞋柜')),
    ('무타공 전동 블라인드', 'no drill motorized cellular blinds', '免打孔电动蜂巢帘', ('무타공 자동블라인드', '무타공블라인드', '무타공 전동', 'no drill motorized', '免打孔电动')),
    ('쌀가루 요리', 'rice flour recipe', '米粉食谱', ('쌀가루', 'rice flour', '米粉食谱')),
    ('문틀 운동 기구', 'door frame pull up gym', '门框单杠', ('푸시업부터 풀업', '문틀 운동', 'door frame gym', '门框单杠')),
    ('래글런 롱슬리브', 'raglan long sleeve outfit', '插肩长袖穿搭', ('나그랑', '래글런', 'raglan', '插肩')),
    ('다단 바지걸이', 'multi layer pants hanger', '多层裤架', ('바지가 층층이', '바지걸이', 'pants hanger', '裤架')),
    ('코바늘 뜨개', 'crochet tutorial', '钩针教程', ('코바늘', 'crochet', '钩针')),
    ('온 러닝 운동화', 'On running shoes outfit', 'On跑鞋穿搭', ('온러닝', '온 러닝', 'on running', 'On跑鞋')),
    ('휴대용 얼룩 제거기', 'portable stain remover demonstration', '便携去渍笔演示', ('얼룩제거', '얼룩 제거', '리무버', 'stain remover', '去渍笔')),
    ('진열장', 'display cabinet', '展示柜', ('진열장', '장식장', 'display cabinet', '展示柜', '陈列柜')),
    ('캠핑 주방세트', 'camping kitchen set', '露营厨具套装', ('캠핑 주방세트', '캠핑 주방 세트', 'camping kitchen set', '露营厨具')),
    ('생선구이', 'pan fried fish cooking', '煎鱼技巧', ('생선구이', '생선 구이', '생선 굽', '생선을 구', '생선 부서', 'pan fried fish', 'frying fish', '煎鱼')),
    ('타일 보수', 'tile repair', '瓷砖修补', ('타일 보수', '타일보수', 'tile repair', '瓷砖修补')),
    ('여권 복대', 'hidden passport money belt', '隐形护照腰包', ('여권지갑', '여권 지갑', '여권 복대', '여행 복대', 'money belt', 'passport pouch', '护照腰包')),
    ('뮬 운동화', 'backless mule sneakers', '半拖运动鞋', ('뮬', 'mule sneakers', 'backless sneakers', '半拖运动鞋')),
    ('마늘간장 치킨', 'honey garlic soy chicken', '蜂蜜蒜香酱油鸡', ('마늘간장', '마늘 간장', 'honey garlic chicken', '蒜香鸡')),
    ('백팩', 'backpack', '双肩包', ('백팩', '배낭', 'backpack', 'rucksack', '双肩包', '背包')),
    ('숄더백', 'shoulder bag', '单肩包', ('숄더백', 'shoulder bag', '单肩包')),
    ('여행 정리 가방', 'travel organizer bag', '旅行收纳袋', ('여행 정리', 'travel organizer', '旅行收纳袋')),
    ('컵홀더', 'cup holder', '杯架', ('컵홀더', '컵 홀더', 'cup holder', '杯架')),
    ('차량 수납함', 'car seat gap organizer', '汽车座椅缝隙收纳盒', ('차량 수납', 'seat gap organizer', '缝隙收纳')),
    ('쓰레기통', 'trash bin', '垃圾桶', ('쓰레기통', 'trash bin', '垃圾桶')),
    ('주방 수납함', 'kitchen storage organizer', '厨房收纳盒', ('주방 수납', 'kitchen storage', '厨房收纳')),
    ('청소 브러시', 'cleaning brush', '清洁刷', ('청소솔', '청소 브러시', 'cleaning brush', '清洁刷')),
    ('채칼', 'vegetable slicer', '切菜器', ('채칼', 'vegetable slicer', '切菜器')),
    ('보관 용기', 'food storage container', '食品保鲜盒', ('밀폐용기', '보관 용기', 'food storage', '保鲜盒')),
    ('휴대용 선풍기', 'portable fan', '便携风扇', ('휴대용 선풍기', 'portable fan', '便携风扇')),
    ('휴대폰 거치대', 'phone holder stand', '手机支架', ('폰 거치대', '휴대폰 거치대', 'phone holder', '手机支架')),
    ('신발 세척 도구', 'shoe cleaning tool', '鞋子清洁工具', ('신발 세척', 'shoe cleaning', '鞋子清洁')),
    ('반려동물 털 제거기', 'pet hair remover', '宠物除毛器', ('털 제거', 'pet hair remover', '除毛器')),
    ('손난로', 'hand warmer', '暖手宝', ('손난로', '키티 손난로', '헬로키티 손난로', 'hand warmer', '暖手宝', '暖手寶')),
    ('보조배터리', 'power bank', '充电宝', ('보조배터리', '보조 배터리', 'power bank', '充电宝')),
    ('패딩', 'puffer jacket', '羽绒服', ('패딩', '몽벨 패딩', 'puffer jacket', 'down jacket', '羽绒服', '棉服')),
]
BRANDS = [('DAISO', 'DAISO', ('daiso', '다이소', '大创', 'ダイソー')),
          ('adidas', '阿迪达斯', ('adidas', '아디다스', '阿迪达斯')),
          ('UGG', 'UGG', ('ugg', '어그')),
          ('nike', '耐克', ('nike', '나이키', '耐克')),
          ('dyson', '戴森', ('dyson', '다이슨', '戴森')),
          ('xiaomi', '小米', ('xiaomi', '샤오미', '小米')),
          ('Hello Kitty', 'Hello Kitty', ('hello kitty', 'hellokitty', '헬로키티', '키티', '凯蒂猫')),
          ('Sanrio', '三丽鸥', ('sanrio', '산리오', '三丽鸥')),
          ('Montbell', 'Montbell', ('montbell', '몽벨', 'モンベル'))]
FEATURES = [('nylon', '尼龙', ('나일론', 'nylon', '尼龙')),
            ('suede', '绒面革', ('스웨이드', 'suede', '绒面革')),
            ('flap', '翻盖', ('플랩', 'flap', '翻盖')),
            ('drawstring', '抽绳', ('조임끈', 'drawstring', '抽绳')),
            ('front zip pocket', '前拉链口袋', ('앞 지퍼', 'front zip', '前拉链')),
            ('foldable', '可折叠', ('접이식', 'foldable', '可折叠')),
            ('car door hanging', '车门挂式', ('차문', 'car door', '车门'))]
NOISE = {'recognize text', 'text in image', 'similar images', 'image appears to contain',
         'person', 'people', 'human', 'video', 'image', 'photo', 'search'}

# Reviewed lexical noun heads, independent of model-supplied intent labels.
# Unknown subjects stay out of TikTok until the dictionary has a reviewed noun
# translation; other providers can still use the grounded scene/action pool.
TIKTOK_NOUN_HEADS = {
    'en': ('photo fridge magnets','photo fridge magnet','fridge magnets','fridge magnet',
        'tape dispenser','dispenser','rear tent','hitch tent','tent','clothesline',
        'garlic','checklist board','squeegee','shoe cabinet','cabinet','cellular blinds','blinds',
        'rice flour','pull up gym','door frame gym','raglan long sleeve','long sleeve','foot warmer wrap',
        'foot warmer','pants hanger','hanger','crochet hook','running shoes','shoes','stain remover',
        'display cabinet','kitchen set','fish','tile','passport money belt','money belt','passport pouch',
        'mule sneakers','sneakers','chicken','backpack','rucksack','shoulder bag','travel organizer bag',
        'cup holder','car seat gap organizer','storage organizer','trash bin','cleaning brush',
        'vegetable slicer','food storage container','storage container','portable fan','fan',
        'phone holder stand','phone holder','shoe cleaning tool','pet hair remover','ladle',
        'mirror','puffer jacket','padding','hoodie','jacket','coat','sweatshirt','heater','vest','polo sweater','sweater',
        'ice cream scoop','pot scraper','frying pan','pan','spoon','bowl','shelf','rack','cart','mat'),
    'ko': ('사진 냉장고 자석','냉장고 자석','사진 자석','테이프 디스펜서','디스펜서',
        '차량 후면 텐트','텐트','빨랫줄','마늘','투두 리스트','투두리스트','체크리스트',
        '유리 청소기','스퀴지','신발장','블라인드','쌀가루','문틀 운동 기구','운동 기구',
        '래글런 롱슬리브','롱슬리브','핫팩','바지걸이','코바늘','러닝 운동화','운동화','신발',
        '얼룩 제거제','얼룩제거제','얼룩 제거기','폴로 니트','폴로니트','니트','진열장','장식장','주방세트','주방 세트','생선','타일','여권 복대','복대',
        '뮬 운동화','치킨','백팩','배낭','숄더백','여행 정리 가방','가방','컵홀더','컵 홀더',
        '차량 수납함','수납함','쓰레기통','청소 브러시','청소솔','채칼','보관 용기','밀폐용기',
        '선풍기','휴대폰 거치대','폰 거치대','거치대','신발 세척 도구','털 제거기','국자','거울',
        '패딩','후드티','후드 티','후드','재킷','자켓','코트','맨투맨','조끼','온열기','냄비','숟가락',
        '팬','프라이팬','카트','매트','선반','행거'),
    'zh': ('照片冰箱贴','冰箱贴','胶台','车尾帐篷','帐篷','晾衣绳','蒜末','蒜蓉','大蒜',
        '待办清单板','玻璃刮','鞋柜','蜂巢帘','米粉','单杠','长袖','暖脚贴','裤架','钩针',
        '跑鞋','运动鞋','去渍笔','去渍剂','polo针织衫','针织衫','展示柜','厨具套装','鱼','瓷砖','护照腰包','双肩包','背包',
        '单肩包','收纳袋','杯架','收纳盒','垃圾桶','清洁刷','切菜器','保鲜盒','风扇','手机支架',
        '鞋子清洁工具','除毛器','汤勺','勺子','镜子','羽绒服','连帽衫','卫衣','外套','锅','地垫','背心','鸡'),
    'ja': ('おたま','鏡','ダウンジャケット','パーカー','鍋','収納ケース','扇風機','靴','バッグ','ベスト',
           'マット','キッチンマット'),
}

# Reviewed object heads and translations. Ingredient/object names alone do not
# identify a promoted product; central-subject selection is a separate step.
REVIEWED_OBJECT_GROUPS = (
    ('밥도그', '밥 핫도그', 'rice hot dog', 'rice dog', '米饭热狗'),
    ('소시지', 'sausage', '香肠'), ('사과', 'apple', '苹果'),
    ('바나나', 'banana', '香蕉'),
    ('스팀 청소기', '스팀청소기', 'steam cleaner', '蒸汽清洁机', '蒸汽清洁器', '蒸汽清洗机'),
    ('계량스푼', '계량 스푼', 'measuring spoon', '量勺', '计量勺'),
    ('로봇청소기', '로봇 청소기', 'robot cleaner', '清洁机器人'),
    ('손난로', 'hand warmer', '暖手宝', '暖手寶'),
    ('보조배터리', '보조 배터리', 'power bank', '充电宝'),
    ('물감', '스틱 물감', 'paint stick', '固体水彩'),
    ('암막 텐트', '난방 텐트', 'blackout tent', '遮光帐篷'),
    ('오트밀빵', '오트밀 빵', 'oatmeal bread', '燕麦面包'),
    ('세정시트', '청소 시트', 'cleaning sheet', '清洁片'),
    ('화장품 브러시', '메이크업 브러시', '브러시', 'makeup brush', '化妆刷'),
    ('차량용 타프', '차박 그늘막', '그늘막', 'car awning', '车边帐'),
    ('독서대', '책 거치대', 'book stand', 'reading stand', '阅读架', '看书架'),
    ('가습기', '미니 가습기', 'humidifier', 'mini humidifier', '加湿器'),
    ('마사지기', '안마기', 'massager', '按摩器', '按摩仪'),
    ('캠핑 랜턴', '랜턴', 'camping lantern', 'lantern', '露营灯'),
    ('거품기', '우유 거품기', 'milk frother', 'frother', '奶泡机', '打蛋器'),
    ('밀봉기', '미니 밀봉기', 'bag sealer', 'heat sealer', '封口机'),
    ('보풀 제거기', '보풀제거기', 'lint remover', 'fabric shaver', '毛球修剪器'),
    ('주방 저울', '전자저울', 'kitchen scale', 'digital scale', '厨房秤', '电子秤'),
    ('에어프라이어', 'air fryer', '空气炸锅'),
    ('계란찜기', '에그보일러', 'egg steamer', 'egg cooker', '煮蛋器'),
    ('무드등', '수면등', 'night light', 'ambient light', '小夜灯', '氛围灯'),
    ('충전기', '무선 충전기', 'charger', 'wireless charger', '充电器', '无线充电器'),
    ('파우치', '화장품 파우치', 'pouch', 'makeup pouch', '收纳包', '化妆包'),
    ('텀블러', '보온병', 'tumbler', 'thermos', '保温杯', '随行杯'),
)
for _group in REVIEWED_OBJECT_GROUPS:
    for _term in _group:
        _lang = 'ko' if re.search('[가-힣]', _term) else 'zh' if re.search('[\u3400-\u9fff]', _term) else 'en'
        TIKTOK_NOUN_HEADS[_lang] = (*TIKTOK_NOUN_HEADS[_lang], _term)
TIKTOK_MODIFIERS = {
    'en': ('red','silver','black','white','blue','green','gray','grey','pink','yellow','brown','beige',
        'silicone','metal','stainless steel','wooden','plastic','nylon','suede','foldable','portable',
        'retractable','electric','motorized','no drill','hidden','backless','multi layer','minced',
        'camping','kitchen','car','3 in 1','diy','scotch magic','scotch','honey','garlic soy',
        'front zip pocket','drawstring','flap','on','waterproof','danton','lightweight','inner down','down','photo',
        'l-shaped','l shaped','handheld'),
    'ko': ('빨간','빨강','은색','검정','검은','흰색','하얀','파란','파랑','녹색','초록','회색',
        '분홍','핑크','노란','노랑','갈색','베이지','실리콘','금속','스테인리스','나무','플라스틱',
        '나일론','스웨이드','접이식','휴대용','전기','전동','무타공','자동 감김','발 전용',
        '다진','다단','캠핑','주방','차량','래글런','나그랑','온 러닝','온러닝','스카치 매직',
        '마늘간장','마늘 간장','분사형','정리','방수','단톤','경량','이너 다운','사진',
        'l자','엘자','l형','l자형','l字형','핸디형','핸디'),
    'zh': ('红色','银色','黑色','白色','蓝色','绿色','灰色','粉色','黄色','棕色','硅胶','金属',
        '不锈钢','木制','塑料','尼龙','绒面革','可折叠','便携','伸缩','电动','免打孔','隐形',
        '多层','自制','插肩','半拖','汽车座椅缝隙','厨房','露营','三合一喷水','照片','食品',
        '阿迪达斯','耐克','前拉链口袋','抽绳','翻盖','轻量','羽绒','蜂蜜','蒜香酱油','l型','l字型','手持'),
    'ja': ('赤い','銀色','黒い','白い','シリコン','折りたたみ','携帯','電動','ダントン','danton','軽量','インナーダウン',
           'キッチン','l字型','l型'),
}


def _approved_tiktok_noun(query):
    lang=language(query)
    value=query.casefold()
    brands={name.casefold() for en,zh,aliases in BRANDS for name in (en,zh,*aliases)}
    model=r'(?:sku|품번|货号)\s+[a-z0-9-]{4,18}'
    if re.fullmatch(model,value):return True
    for head in sorted(TIKTOK_NOUN_HEADS.get(lang,()),key=len,reverse=True):
        if value==head:return True
        if not value.endswith(head):continue
        prefix=value[:-len(head)]
        if lang=='en' and not prefix.endswith(' '):continue
        prefix=prefix.strip()
        tokens=sorted({*TIKTOK_MODIFIERS.get(lang,()),*brands},key=len,reverse=True)
        while prefix:
            token=next((t for t in tokens if prefix==t or prefix.startswith(t+' ')
                or lang in {'ko','zh','ja'} and prefix.startswith(t)),None)
            if token is None:
                match=re.match(r'(?:sku|품번|货号)\s+[a-z0-9-]{4,18}(?:\s|$)',prefix)
                if match:prefix=prefix[match.end():].strip();continue
                break
            prefix=prefix[len(token):].strip()
        if not prefix:return True
    # Explicit observed model identifiers may be searched without a catalog noun.
    return any(value.startswith(b+' ') and re.fullmatch(model,value[len(b)+1:]) for b in brands)


def within_query_word_limit(query):
    """Current dispatch ceiling: ten whitespace-separated words in every language."""
    return isinstance(query,str) and 1<=len(query.split())<=10


def _clean_tiktok_syntax(query: str, *, max_words=6, max_characters=80) -> str:
    query = ' '.join(str(query).split())
    suffix = (r'\s+(?:raw footage no captions|close up footage|원본 영상 자막 없는|클로즈업 영상|'
              r'实拍\s*无字幕|特写视频|detail review|demonstration|unboxing|실물 리뷰|사용 영상|'
              r'언박싱|细节展示|使用演示|开箱\s*实拍)$')
    while re.search(suffix, query, re.I):
        query = re.sub(suffix, '', query, flags=re.I).strip()
    prohibited = (r'https?://|site:|inurl:|[!?。\n\r]|'
                  r'원본|자막|영상|클로즈업|장면|찾아|검색해|긁기|긁는|긁어|떠서|사용하기|'
                  r'(?:^|\s)(?:여닫기|열기|닫기|접기|펼치기)(?:\s|$)|방법|과정|후기|사용법|'
                  r'\b(?:scraping|scrape|scrapes|scooping|fry|frying(?!\s+pan\b)|how to|footage|captions?|tutorial|'
                  r'review|unboxing|demonstration|step by step)\b|无字幕|無字幕|视频|視頻|教程|演示|刮锅|刮鍋')
    if not query or (max_characters is not None and len(query)>max_characters) or len(query.split()) > max_words or re.search(prohibited, query, re.I):
        return ''
    return query


def register_tiktok_noun_head(phrase: str) -> str:
    clean = _clean_tiktok_syntax(phrase,max_words=10,max_characters=None)
    if not clean or re.search(r'(?:으로|로)\s+\S+|(?:하기|하는|만들기|만드는)$', clean):
        return ''
    lang = language(clean)
    if lang in TIKTOK_NOUN_HEADS:
        low = clean.casefold()
        if low not in TIKTOK_NOUN_HEADS[lang]:
            TIKTOK_NOUN_HEADS[lang] = (*TIKTOK_NOUN_HEADS[lang], low)
        return clean
    return ''


def tiktok_noun_phrase(query: str) -> str:
    """Remove collection suffixes; reject action/instruction queries, never guess an object."""
    query = _clean_tiktok_syntax(query,max_words=10,max_characters=None)
    return query if query and _approved_tiktok_noun(query) else ''


TIKTOK_EQUIVALENTS = (
    *REVIEWED_OBJECT_GROUPS,
    ('handheld', '핸디형', '핸디', '手持'),
    ('stain remover','얼룩 제거제','얼룩제거제','去渍剂'),
    ('polo sweater','polo knit','폴로 니트','폴로니트','polo针织衫'),
    ('sweater','니트','针织衫'),
    ('ladle','국자','汤勺','おたま'), ('mirror','거울','镜子','鏡'),
    ('puffer jacket','padding','패딩','羽绒服','ダウンジャケット'),
    ('hoodie','후드','후드티','후드 티','连帽衫','パーカー'),
    ('sweatshirt','맨투맨','卫衣'), ('jacket','재킷','자켓','外套'),
    ('heater','온열기'), ('fan','선풍기','风扇','扇風機'),
    ('mat','매트','地垫','マット'), ('kitchen mat','주방 매트','주방매트','厨房地垫','キッチンマット'),
    ('l-shaped','l shaped','l자','엘자','l형','l자형','l字형','l型','l字型'),
    ('pan','frying pan','프라이팬','팬','锅'), ('pot','냄비','鍋'),
    ('red','빨간','빨강','红色','赤い'), ('silver','은색','银色','銀色'),
    ('black','검정','검은','黑色','黒い'), ('white','흰색','하얀','白色','白い'),
    ('blue','파란','파랑','蓝色'), ('green','녹색','초록','绿色'),
    ('gray','grey','회색','灰色'), ('pink','분홍','핑크','粉色'), ('yellow','노란','노랑','黄色'),
    ('brown','갈색','棕色'), ('beige','베이지'),
    ('silicone','실리콘','硅胶','シリコン'), ('metal','금속','金属'),
    ('stainless steel','스테인리스','不锈钢'), ('wooden','나무','木制'),
    ('plastic','플라스틱','塑料'), ('nylon','나일론','尼龙'), ('suede','스웨이드','绒面革'),
    ('foldable','접이식','可折叠','折りたたみ'), ('portable','휴대용','便携','携帯'),
    ('electric','전기','电动','電動'), ('motorized','전동','电动','電動'),
    ('retractable','자동 감김','伸缩'), ('no drill','무타공','免打孔'),
    ('hidden','숨겨진','隐形'), ('backless','뮬','半拖'), ('multi layer','다단','多层'),
    ('minced','다진','蒜末','蒜蓉'), ('camping','캠핑','露营'), ('kitchen','주방','厨房','キッチン'),
    ('car','차량','汽车'), ('waterproof','방수','防水'), ('diy','자작','自制'),
    ('vest','조끼','ベスト','背心'), ('danton','단톤','ダントン'), ('lightweight','경량','軽量','轻量'),
    ('down','다운','羽绒'),
    ('photo','사진','照片'),
    ('inner down','이너 다운','インナーダウン'),
    ('front zip pocket','앞 지퍼','前拉链口袋'), ('drawstring','조임끈','抽绳'),
    ('flap','플랩','翻盖'), ('garlic soy','마늘간장','마늘 간장','蒜香酱油'),
    ('honey','꿀','蜂蜜'),
)


def _literal_term(term,text):
    if re.fullmatch(r'[a-z0-9 -]+',term):
        return bool(re.search(r'(?<![a-z0-9])'+re.escape(term)+r'(?![a-z0-9])',text))
    return term in text


def grounded_tiktok_noun_phrase(query,quote):
    """Approve translations by reviewed lexical equivalence, never a model label."""
    query=tiktok_noun_phrase(query)
    if not query:return ''
    q=query.casefold();evidence=str(quote).casefold()
    if _literal_term(q,evidence):return query
    groups=[tuple(x.casefold() for x in group) for group in TIKTOK_EQUIVALENTS]
    groups.extend(tuple(x.casefold() for x in (ko,en,zh,*aliases)) for ko,en,zh,aliases in PRODUCTS)
    groups.extend(tuple(x.casefold() for x in (en,zh,*aliases)) for en,zh,aliases in BRANDS)
    heads=[h for h in TIKTOK_NOUN_HEADS.get(language(query),()) if q==h or q.endswith(' '+h)
           or language(query) in {'ko','zh','ja'} and q.endswith(h)]
    if not heads:
        # A model/SKU is an identifier: its exact code must occur in the quote.
        codes=re.findall(r'(?:sku|품번|货号)\s+([a-z0-9-]{4,18})',q)
        if not codes or any(not _literal_term(c,evidence) for c in codes):return ''
    elif not any(_literal_term(head,evidence) or any(
            _literal_term(head,item) and any(_literal_term(alias,evidence) for alias in group)
            for group in groups for item in group) for head in heads):
        return ''
    # Every known modifier/brand anywhere in the phrase also needs direct or
    # reviewed translated evidence, including modifiers inside catalog heads.
    terms={*TIKTOK_MODIFIERS.get(language(query),()),
           *(x.casefold() for en,zh,aliases in BRANDS for x in (en,zh,*aliases))}
    for term in terms:
        if _literal_term(term,q) and not (_literal_term(term,evidence) or any(
                term in group and any(_literal_term(alias,evidence) for alias in group) for group in groups)):
            return ''
    return query


def prioritize_tiktok_requests(plan,requested):
    """Use explicit noun requests only after checking the actual reference evidence."""
    result={**plan,'tiktok_operator_request':True,'tiktok_operator_query_details':[],
            'tiktok_operator_query_rejections':[]}
    evidence=plan.get('query_evidence') or {}
    quote=' '.join(str(v) for v in evidence.values())
    for raw in requested:
        query=grounded_tiktok_noun_phrase(raw,quote)
        if query:
            if not any(r['query'].casefold()==query.casefold() for r in result['tiktok_operator_query_details']):
                result['tiktok_operator_query_details'].append({'query':query,'language':language(query),
                    'origin':'user_feedback','intent':'product','sources':[k for k,v in evidence.items() if v],
                    'evidence_quote':quote})
        else:
            result['tiktok_operator_query_rejections'].append({'query':raw,'reason':'not_grounded_noun_phrase'})
    return result


def tiktok_product_queries(plan: dict, fallback: list[str] | None = None) -> list[str]:
    """Prefer separately grounded product phrases over scene/quality instructions."""
    if plan.get('search_purpose')=='support':
        from .source_query_identity import checked_identity
        identity=checked_identity(plan.get('core_search_identity'))
        approved={word for words in identity['product_terms'].values() for word in words[:3]}
        result=[]
        for row in plan.get('query_details',[]):
            word=row.get('query')
            if word in approved:
                register_tiktok_noun_head(word)
                if query:=tiktok_noun_phrase(word):result.append(query)
        return list(dict.fromkeys(result))
    if plan.get('text_query_evidence') and not plan.get('tiktok_operator_request'):
        from .source_text_query_receipts import plan_text_queries
        rows = plan_text_queries(plan)
        accepted = []
        for row in rows:
            if register_tiktok_noun_head(row['query']):
                accepted.append(row['query'])
        return list(dict.fromkeys(accepted))
    visual_rows = []
    if plan.get('visual_query_evidence') and not plan.get('tiktok_operator_request'):
        from .source_visual_queries import plan_queries
        # Recheck this plan's actual pixels/receipts at dispatch; a registered
        # noun from another task is never sufficient evidence for this one.
        visual_rows = plan_queries(plan)
        from .reference_scene_roles import diverse_query_order
        visual_rows = diverse_query_order(visual_rows)
        # Keep the product identity during refinement as well as first search.
        # A broad caption head must not turn replacement parts into clothing.
        for row in visual_rows:
            register_tiktok_noun_head(row['query'])
        return list(dict.fromkeys(row['query'] for row in visual_rows))
    operator=plan.get('tiktok_operator_request',False)
    ps = plan.get('primary_subject')
    dynamic_primary = ''
    if isinstance(ps, dict):
        from .source_planning import primary_subject, grounded_named_terms
        ev = dict(plan.get('query_evidence') or {})
        if not ev and ps.get('source') and ps.get('quote'):
            ev = {str(ps['source']): str(ps['quote'])}
        validated = primary_subject(ps, ev)
        if validated and grounded_named_terms(validated['name'], ev):
            ev_text = ' '.join(str(v) for v in ev.values()).casefold()
            if _literal_term(validated['name'].casefold(), ev_text):
                dynamic_primary = register_tiktok_noun_head(validated['name'])
    details=plan.get('tiktok_operator_query_details',[]) if operator else plan.get('tiktok_query_details', [])
    rows = [q for r in details if (q :=
        grounded_tiktok_noun_phrase(r['query'],r['evidence_quote']) if r.get('evidence_quote')
        else tiktok_noun_phrase(r['query']))]
    if operator and not rows:return []
    rows += [q for r in ([] if operator else plan.get('query_details', []))
             if r.get('intent') in {'product', 'unbranded', 'appearance', 'model', 'subject'}
             and (q := grounded_tiktok_noun_phrase(r['query'],r['evidence_quote'])
                  if r.get('evidence_quote') else tiktok_noun_phrase(r['query']))]
    rows += [p[lang] for p in ([] if operator else plan.get('products', []))
             for lang in ('en', 'ko', 'zh', 'ja') if p.get(lang)]
    if dynamic_primary and not operator and dynamic_primary not in rows:
        rows.append(dynamic_primary)
    if not rows:
        rows = list(fallback or [])
    if 'query_evidence' in plan:
        evidence=' '.join(str(v) for v in plan['query_evidence'].values())
        approved=[]
        for raw in rows:
            query=grounded_tiktok_noun_phrase(raw,evidence)
            if query:
                approved.append(query);continue
            # Catalog names may contain features absent from this reference.
            # Retain only an independently grounded noun head, never the extra
            # catalog modifiers (DIY/photo/multi-layer etc.).
            clean=tiktok_noun_phrase(raw)
            if not clean:continue
            for head in sorted(TIKTOK_NOUN_HEADS.get(language(clean),()),key=len,reverse=True):
                if clean.casefold().endswith(head) and grounded_tiktok_noun_phrase(head,evidence):
                    approved.append(head);break
        rows=approved
    for r in visual_rows:
        register_tiktok_noun_head(r['query'])
    return list(dict.fromkeys([*[r['query'] for r in visual_rows],
        *[q for row in rows if (q := tiktok_noun_phrase(row))]]))


def language(text: str) -> str:
    if re.search(r'[가-힣]', text):
        return 'ko'
    if re.search(r'[\u3040-\u30ff]', text):
        return 'ja'
    if re.search(r'[\u3400-\u9fff]', text):
        return 'zh'
    if re.search(r'[A-Za-z]', text) and not re.search(r'[\u0400-\u04ff]', text):
        return 'en'
    return 'other'


def clean_terms(terms: list[str]) -> list[str]:
    return list(dict.fromkeys(t.strip() for t in terms if t.strip().lower() not in NOISE
                             and len(t.strip()) >= 3))


def _hits(aliases: tuple, sources: dict[str, str]) -> list[str]:
    def present(alias, body):
        if re.fullmatch(r'[a-z ]+', alias):
            return bool(re.search(r'(?<![a-z])' + re.escape(alias) + r'(?![a-z])', body.lower()))
        return alias.lower() in body.lower()
    return [name for name, body in sources.items() if any(present(a, body) for a in aliases)]


def product_query_plan(caption: str, visual_queries: list[str], vision_terms: list[str],
                       transcript: dict[str, str], fallback: list[str], candidate_titles: list[str] | None = None) -> dict:
    sources = {'caption': caption, 'screen_text': transcript.get('screen_text', ''),
               'speech': transcript.get('speech', ''), 'vision': ' '.join(clean_terms(vision_terms))}
    if candidate_titles:
        sources['verified_candidate_title'] = ' '.join(candidate_titles)[:3000]
    # Caption and speech identify the subject more reliably than search-engine
    # guesses. Keep vision evidence, but never let a matched background object
    # occupy the two subject slots ahead of an explicitly named subject.
    direct_sources = {k: v for k, v in sources.items() if k != 'vision'}
    products = []
    for ko, en, zh, aliases in PRODUCTS:
        evidence = _hits(aliases, sources)
        if evidence:
            products.append({'ko': ko, 'en': en, 'zh': zh, 'sources': evidence,
                             'confidence': 'high' if len(evidence) >= 2 else 'medium'})
    direct_products = [p for p in products if any(s in {'caption','speech','screen_text'} for s in p['sources'])]
    hypotheses = [p for p in products if p not in direct_products]
    products = direct_products
    # 직접 식별한 제품이 있으면 넓은 CLIP 카탈로그가 그것을 덮어쓰지 않는다.
    for en, zh in zip(visual_queries[::2], visual_queries[1::2]):
        if language(en) == 'en' and language(zh) == 'zh':
            hypotheses.append({'ko': '', 'en': en, 'zh': zh, 'sources': ['openclip'], 'confidence': 'hypothesis'})
    products = products[:2]
    brands = [{'en': en, 'zh': zh, 'sources': evidence, 'confidence': 'high' if len(evidence) >= 2 else 'medium'}
              for en, zh, aliases in BRANDS if (evidence := _hits(aliases, direct_sources if direct_products else sources))]
    features = [{'en': en, 'zh': zh, 'sources': evidence}
                for en, zh, aliases in FEATURES if (evidence := _hits(aliases, sources))][:3]
    models = []
    for name, body in sources.items():
        for match in re.finditer(r'(?:품번|모델명|型号|货号|\bmodel\b|\bsku\b)\s*[:：#]?\s*([A-Za-z0-9-]{4,18})(?![A-Za-z0-9-])', body, re.I):
            value = match[1]
            # Explicit numeric SKUs are identifiers too. Unlabelled prices,
            # years, phone numbers and model guesses from vision are not.
            valid = (bool(re.search('[A-Za-z]', value)) and bool(re.search('[0-9]', value))) or (
                value.isdigit() and name != 'vision')
            if valid:
                old = next((m for m in models if m['value'].casefold() == value.casefold()), None)
                if old:
                    if name not in old['sources']:
                        old['sources'].append(name)
                else:
                    models.append({'value': value, 'sources': [name], 'confidence': 'medium',
                                   'evidence_quote': match[0]})
    pools = {'en': [], 'zh': [], 'ko': [], 'ja': []}
    def add(query, lang, intent, evidence, confidence='medium'):
        query = ' '.join(query.split())[:180]
        if query:
            pools[lang].append({'query': query, 'language': lang, 'intent': intent, 'role': 'product',
                                'sources': list(dict.fromkeys(evidence)), 'confidence': confidence})
    # An exact identifier must survive even for a product outside the static
    # catalog, and retain a language marker for provider query selection.
    for model in models[:3]:
        for lang, label in (('en', 'SKU'), ('zh', '货号'), ('ko', '품번')):
            brand = brands[0].get(lang, brands[0]['en']) if brands else ''
            add(f"{brand} {label} {model['value']}", lang, 'model',
                model['sources'] + (brands[0]['sources'] if brands else []))
            pools[lang][-1]['evidence_quote'] = model['evidence_quote']
    for product in products:
        for lang in ('en', 'zh', 'ko'):
            base = product[lang]
            if not base:
                continue
            brand = brands[0].get(lang, brands[0]['en']) if brands else ''
            evidence = product['sources'] + (brands[0]['sources'] if brand else [])
            confidence = 'high' if product['confidence'] == 'high' and (not brand or brands[0]['confidence'] == 'high') else 'medium'
            add(f'{brand} {base}', lang, 'product', evidence, confidence)
            add(base, lang, 'unbranded', product['sources'], product['confidence'])
            if models:
                add(f"{brand} {models[0]['value']} {base}", lang, 'model', evidence + models[0]['sources'])
            attrs = ' '.join(f[lang] for f in features if lang in f)
            if attrs:
                add(f'{brand} {attrs} {base}', lang, 'appearance', evidence + [s for f in features for s in f['sources']])
            intents = {'en': ('detail review', 'demonstration', 'unboxing'),
                       'zh': ('细节展示', '使用演示', '开箱 实拍'), 'ko': ('실물 리뷰', '사용 영상', '언박싱')}
            if product['en'] in {'honey garlic soy chicken', 'pan fried fish cooking', 'minced garlic preparation',
                                 'rice hot dog', 'apple'}:
                intents = {'en': ('recipe', 'cooking tutorial', 'close up cooking'),
                           'zh': ('做法', '制作教程', '烹饪 特写'), 'ko': ('레시피', '요리 과정', '만들기')}
            elif product['en'] == 'tile repair':
                intents = {'en': ('crack repair tutorial', 'repair process', 'before after repair'),
                           'zh': ('裂缝修复教程', '修补过程', '修复前后'), 'ko': ('균열 보수 방법', '보수 과정', '보수 전후')}
            for intent in intents[lang]:
                add(f'{brand} {base} {intent}', lang, intent, evidence)
    if not products:
        for query in clean_terms(fallback + vision_terms):
            lang = language(query)
            if lang in pools:
                add(query, lang, 'fallback', ['caption' if query in fallback else 'vision'], 'low')
    details = []
    seen = set()
    for batch in zip_longest(*pools.values()):
        for item in batch:
            if item and item['query'].casefold() not in seen:
                details.append(item); seen.add(item['query'].casefold())
    return {'products': products, 'inferred_products':hypotheses, 'brands': brands, 'features': features, 'models': models,
            'query_evidence':{k:v for k,v in sources.items() if k in {'caption','speech','screen_text'}},
            'query_details': details[:30]}


def feedback_queries(request: str) -> list[str]:
    """Accept concise explicit keywords, never a truncated instruction paragraph."""
    result = []
    for line in request.splitlines():
        line = re.sub(r'^(?:검색어|keywords?|queries)\s*[:：]\s*', '', line.strip(), flags=re.I)
        if len(line) > 180 or re.search(r'찾으세요|찾아주세요|제외하세요|허용하지|확정하지|레퍼런스|장면만|등의.*검색', line):
            continue
        for query in re.split(r'[,;；]', line):
            query = ' '.join(query.strip(' \"\'').split())
            if 2 <= len(query) <= 80 and not re.search(r'https?://|[.!?。!?]', query):
                result.append(query)
    return list(dict.fromkeys(result))[:8]


def next_round_queries(plan, round_number, history):
    """Change grounded search intents; never recycle an instruction paragraph."""
    # A query tried on YouTube is still new on TikTok. Provider-specific
    # exhaustion belongs to discovery, never to this shared grounded pool.
    from .source_search.strategy import normalize_query
    used = {normalize_query(r.get('query', '')) for r in history if not r.get('provider')
            and r.get('status') in {'results', 'no_results'}}
    details = [dict(q) for q in plan['query_details'] if q['query'].casefold() not in used]
    intents = {
        'en': [('close up demonstration','how to use'),('step by step tutorial','hands on review'),('preparation process','storage tips'),('product demonstration video','daily use'),('long review','detailed tutorial')],
        'ko': [('사용 장면 클로즈업','사용 방법'),('단계별 사용법','실사용 후기'),('준비 과정','보관 방법'),('제품 시연 영상','일상 활용'),('상세 리뷰','자세한 사용법')],
        'zh': [('使用 特写','使用方法'),('步骤 教程','实际体验'),('准备过程','保存方法'),('产品演示 视频','日常使用'),('详细评测','完整教程')],
    }
    offset = (round_number-1)%5
    products = list(plan.get('products', []))
    # Subjects identified by the model also need future search intents. Without
    # a catalog match, exhausting their first queries used to leave an empty
    # plan and only unrelated image-search labels in subsequent rounds.
    if not products:
        for lang in ('en', 'ko', 'zh'):
            bases = [q for q in plan['query_details'] if q.get('language') == lang
                     and q.get('role') == 'subject_action' and q.get('evidence_quote')]
            for base in sorted(bases, key=lambda q: len(q['query']))[:2]:
                products.append({lang:base['query'], 'sources':base.get('sources', [])})
    for product in products:
        for lang in ('en','ko','zh'):
            base = product.get(lang)
            if not base: continue
            groups = intents[lang]
            if plan.get('subject_kind') == 'recipe' or product.get('en') in {
                    'minced garlic preparation', 'honey garlic soy chicken', 'pan fried fish cooking', 'rice flour recipe'}:
                groups = {
                    'en': [('close up preparation', 'step by step cooking'), ('preparation process', 'portioning'),
                           ('storage preparation', 'spooning demonstration'), ('cooking technique', 'hands on preparation'),
                           ('detailed cooking tutorial', 'ingredient preparation')],
                    'ko': [('준비 장면 클로즈업', '단계별 조리 과정'), ('준비 과정', '소분 장면'),
                           ('보관 준비', '숟가락으로 뜨는 장면'), ('조리 방법', '직접 준비하는 장면'),
                           ('자세한 조리 과정', '재료 준비')],
                    'zh': [('准备 特写', '分步烹饪'), ('准备过程', '分装'), ('保存准备', '舀取演示'),
                           ('烹饪方法', '实际准备'), ('详细制作教程', '食材准备')],
                }[lang]
            # Visit every remaining intent, starting at a different group. A
            # modulo-selected exhausted group must not erase the whole pool.
            for suffix in [s for group in groups[offset:] + groups[:offset] for s in group]:
                query = f'{base} {suffix}'
                if query.casefold() not in used:
                    details.insert(0, {'query':query,'language':lang,'role':'product','intent':suffix,'sources':product.get('sources',[]),'origin':'automatic_expansion'})
    return list({normalize_query(d['query']): d for d in details}.values())


def platform_queries(queries: list[str], provider: str, limit: int, *, search_minimums=None) -> list[str]:
    """지원 언어별 풀에서 고른다. 앞쪽 네 검색어에서 잘라 중국어를 버리지 않는다."""
    queries=[q for q in queries if within_query_word_limit(q)]
    if provider == 'tiktok':
        queries = list(dict.fromkeys(q for raw in queries if (q := tiktok_noun_phrase(raw))))
    languages = ('zh', 'en', 'ko') if provider in {'douyin', 'xiaohongshu', 'bilibili'} else ('en', 'ko', 'zh', 'ja')
    pools = {lang: [q for q in dict.fromkeys(queries) if language(q) == lang] for lang in languages}
    if provider in {'douyin', 'xiaohongshu', 'bilibili'}:
        return pools['zh'][:max(0, limit)]
    if search_minimums:
        # English and Chinese minima precede supplementary languages; retain
        # literal phrases and let actual execution evidence satisfy the quota.
        priority=[q for batch in zip_longest(pools.get('en',[]),pools.get('zh',[])) for q in batch if q]
        rest=[q for lang in languages if lang not in {'en','zh'} for q in pools[lang]]
        return [*priority,*rest][:max(0,limit)]
    if provider == 'tiktok':
        # One query in each language before spending a second slot on any language.
        return [q for batch in zip_longest(*(pools[l] for l in languages))
                for q in batch if q][:max(0, limit)]
    out = []
    # 영어 우선 두 개마다 한국어 등 보조 언어 하나를 배분한다.
    preferred = pools[languages[0]]
    secondary = [q for batch in zip_longest(*(pools[l] for l in languages[1:])) for q in batch if q]
    while preferred or secondary:
        out.extend(preferred[:2]); del preferred[:2]
        if secondary:
            out.append(secondary.pop(0))
    return out[:max(0, limit)]
