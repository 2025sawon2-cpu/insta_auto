import copy

from hotpost.source_queries import grounded_tiktok_noun_phrase
from hotpost.studio_sources import SourceAcquisitionMixin


def test_known_current_product_heads_are_grounded_without_action_or_invented_features():
    cleaner='옷에 튄 기름 얼룩, 세제까지 다 써봐도 얼룩이 남아서 얼룩 제거제를 뿌렸어요.'
    knit='버건디 줄무늬에 베이지 카라가 달린 아디다스 폴로니트'
    assert grounded_tiktok_noun_phrase('얼룩 제거제',cleaner)=='얼룩 제거제'
    assert grounded_tiktok_noun_phrase('stain remover',cleaner)=='stain remover'
    assert grounded_tiktok_noun_phrase('去渍剂',cleaner)=='去渍剂'
    assert grounded_tiktok_noun_phrase('아디다스 폴로 니트',knit)=='아디다스 폴로 니트'
    assert grounded_tiktok_noun_phrase('adidas polo sweater',knit)=='adidas polo sweater'
    assert grounded_tiktok_noun_phrase('阿迪达斯Polo针织衫',knit)=='阿迪达斯Polo针织衫'
    for phrase,quote in [('wool sweater',knit),('니트 코디 원본 영상 자막 없는',knit),
                         ('얼룩 제거제 뿌리고 5초 후 털어내기',cleaner),('portable stain remover',cleaner)]:
        assert not grounded_tiktok_noun_phrase(phrase,quote)


def test_manual_resume_preserves_completed_no_progress_history_and_repair_caps():
    hold={'reason':'strategy_exhausted','no_progress_rounds':2}
    state={'daily_quality':{'repair_round':3,'max_repairs':3},'source_acquisition':{
        'hold':hold,'round':2,'bounded_rounds':2,'no_progress_rounds':2,'queries':['old query'],
        'rounds':[{'job_id':'old','improved':False}],'started_at':1,'execution_seconds':123}}
    before=copy.deepcopy(state)
    SourceAcquisitionMixin().release_source_hold(state)
    record=state['source_acquisition']
    assert record['hold_history']==[hold] and not record.get('hold')
    for field in ('round','bounded_rounds','no_progress_rounds','queries','rounds','started_at','execution_seconds'):
        assert record[field]==before['source_acquisition'][field]
    assert state['daily_quality']==before['daily_quality']
