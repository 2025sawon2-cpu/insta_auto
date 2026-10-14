import pytest
from hotpost.writing.reference_evidence import choose_keyword, comment_keyword


@pytest.mark.parametrize('text',['아무 댓글이나 남겨주세요','댓글이나 남겨주세요',
                                '댓글에 남겨주세요','댓글로 남겨주세요'])
def test_general_comment_request_is_not_a_product_keyword(text):
    assert comment_keyword(text)==''
    assert choose_keyword('',text)==('나도', 'user_fixed')


def test_generic_request_does_not_hide_a_later_specific_keyword():
    assert comment_keyword('아무 댓글이나 남겨주세요. 댓글에 ‘폴더’ 남겨주세요')=='폴더'
    assert choose_keyword('노페 남겨주세요',"댓글에 ’노페‘ 남겨주세요")==('나도','user_fixed')
