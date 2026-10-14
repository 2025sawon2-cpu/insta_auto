import pytest
from hotpost.writing.reference_evidence import comment_issues

@pytest.mark.parametrize('old_keyword',['나도','거울','테이블'])
def test_fixed_nado_ending_ignores_historical_keyword_metadata(old_keyword):
    assert comment_issues('옆으로 밀면 거울이 나와요. 댓글에 ‘나도’ 남겨주세요.',old_keyword)==[]

@pytest.mark.parametrize('old_keyword',['거울','테이블'])
def test_other_keyword_is_rejected_even_with_matching_historical_metadata(old_keyword):
    assert comment_issues(f'옆으로 밀면 거울이 나와요. 댓글에 ‘{old_keyword}’ 남겨주세요.',old_keyword)

@pytest.mark.parametrize('text',[
    '이 제품이 궁금하면 댓글에 ‘나도’ 남겨주세요.',
    '마지막으로 댓글에 ‘나도’ 남겨주세요.',
    '댓글에 ‘나도’ 남겨주세요. 다음 영상에서 봐요.',
])
def test_end_announcements_conditions_and_extra_tail_are_rejected(text):
    assert comment_issues(text,'나도')
