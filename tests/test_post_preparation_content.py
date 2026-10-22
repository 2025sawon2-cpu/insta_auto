import json
import re

from hotpost.post_preparation_content import CONTENT, CTA, build_copy


def test_existing_post_copy_is_detailed_with_five_final_hashtags_and_two_line_comment():
    entries = json.loads(CONTENT.read_text('utf8'))
    for code, entry in entries.items():
        result = build_copy(code, '기존에 확인한 제품 대본입니다.')
        caption = result['caption']
        assert 400 <= len(caption) <= 2200, code
        tag_line = caption.splitlines()[-1]
        assert tag_line == ' '.join('#'+tag for tag in entry['hashtags'])
        tags = re.findall(r'#\w+', caption)
        assert len(tags) == len(set(tags)) == 5, code
        assert caption.endswith(tag_line)
        lines = result['pinned_comment'].splitlines()
        assert lines == ['✨ '+entry['benefit'], CTA], code
        assert '\n' not in entry['benefit']


def test_missing_script_does_not_get_an_unverified_caption_or_comment():
    assert build_copy('DesTrP8SwOa', '') == {'caption': '', 'pinned_comment': ''}


def test_fallback_keeps_known_facts_and_topic_tags_without_inventing_product_claims():
    result = build_copy('new-post', '이 욕실 선반은 변기 뒤에 끼워요. 댓글에 ‘정보’ 남겨주세요.', '빈 공간을 수납으로 활용해요.')
    assert '변기 뒤에 끼워요.' in result['caption']
    assert result['caption'].count('댓글에') == 1
    assert '#욕실수납' in result['caption'].splitlines()[-1]
    assert len(result['caption'].splitlines()[-1].split()) == 5
    assert result['pinned_comment'].splitlines() == ['✨ 빈 공간을 수납으로 활용해요.', CTA]


def test_long_copy_preserves_hashtags_and_comment_invitation_at_the_end():
    result = build_copy('new-post', '생활 속에서 사용하는 물건이에요. ' * 200)
    assert len(result['caption']) <= 2200
    assert len(result['caption'].splitlines()[-1].split()) == 5
    assert CTA in result['caption']
