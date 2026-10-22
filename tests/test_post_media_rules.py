import pytest
from hotpost.post_media_rules import without_opening_interjection, require_content_opening


@pytest.mark.parametrize('text', ['아, 청소용품 하나', '아! 청소용품 하나', '아 청소용품 하나',
                                  '아" 청소용품 하나', '어머! 와, 청소용품 하나'])
def test_standalone_opening_filler_is_removed_and_rejected_for_narration(text):
    assert without_opening_interjection(text)=='청소용품 하나'
    with pytest.raises(ValueError):
        require_content_opening(text)
    require_content_opening(without_opening_interjection(text))


@pytest.mark.parametrize('text',['아침 청소가 편해요','아이 물건을 정리해요','와이드 선반이에요','오늘은 수납해요'])
def test_words_that_begin_like_interjections_are_preserved(text):
    assert without_opening_interjection(text)==text
    require_content_opening(text)
