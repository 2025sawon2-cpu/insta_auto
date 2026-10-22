import pytest
from hotpost.thumbnail_copy import review_copy


@pytest.mark.parametrize('lines', [
    ['운동복 위에 걸쳤는데', '차려입은 느낌 나요'],
    ['공연 줄에선 손난로', '입장 전엔 조명 거울'],
    ['정리함인 줄 알았죠?', '펼치면 캠핑 테이블'],
])
def test_specific_benefit_or_question_is_not_generic_filler(lines):
    assert review_copy(lines)['issues'] == []


def test_generic_interest_advice_does_not_become_a_content_approval_gate():
    review = review_copy(['경량 패딩', '왜 눈길이 갈까요?'])
    assert review['issues'] and review['advisory_only'] is True
