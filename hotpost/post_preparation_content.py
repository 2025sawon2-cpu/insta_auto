"""Publication copy is longer than narration; it never changes the spoken script."""
import json
from pathlib import Path
import re

CTA = '💬 댓글에 "나도" 남겨주세요.'
CONTENT = Path(__file__).with_suffix('.json')


def fallback_tags(text):
    groups = (
        (r'텐트|캠핑', ['캠핑용품', '가족캠핑', '캠핑아이디어', '캠핑준비', '캠핑생활']),
        (r'고양이|캣타워', ['고양이용품', '반려묘', '집사생활', '고양이일상', '반려생활']),
        (r'가방|니트|패딩|신발|바지', ['데일리룩', '데일리코디', '외출코디', '패션아이템', '일상코디']),
        (r'요리|미역|사과|도시락|간식', ['집밥', '홈쿡', '요리아이디어', '주방생활', '집밥기록']),
        (r'욕실|변기', ['욕실정리', '욕실수납', '공간활용', '살림꿀팁', '살림아이디어']),
    )
    return next((tags for pattern, tags in groups if re.search(pattern, text)),
                ['살림템', '생활아이템', '살림꿀팁', '살림아이디어', '일상생활'])


def build_copy(code, script, fallback_benefit=''):
    if not script.strip():
        return {'caption': '', 'pinned_comment': ''}
    entries = json.loads(CONTENT.read_text('utf-8'))
    entry = entries.get(code)
    if entry:
        body = '\n\n'.join([
            entry['opening'], entry['context'],
            '이런 점이 좋아요 👇\n' + '\n'.join('✅ ' + point for point in entry['advantages']),
            entry['closing'],
        ])
        tags = entry['hashtags']
        benefit = entry['benefit']
    else:
        text = re.sub(r'댓글에\s*[‘’\'\"]?[^\s‘’\'\"]+[‘’\'\"]?\s*남겨주세요[.!！]?',
                      '댓글에 "나도" 남겨주세요.', script).strip()
        sentences = re.split(r'(?<=[.!?。])\s+', text)
        # Preserve a natural final CTA sentence, including any preceding condition.
        closing = sentences.pop() if sentences and '댓글에' in sentences[-1] else ''
        if closing:
            closing = '💬 ' + closing
        else:
            closing = CTA
        body = '✨ ' + '\n\n'.join(sentences)
        tags = fallback_tags(script)
        benefit = fallback_benefit or next((sentence for sentence in sentences if not sentence.endswith('?')), '')
    tail = '\n\n' + (CTA if entry else closing) + '\n\n' + ' '.join('#' + tag for tag in tags)
    if len(body) + len(tail) > 2200:
        body = body[:2200 - len(tail) - 1].rstrip() + '…'
    benefit = ' '.join(benefit.split()).strip()
    return {'caption': body + tail,
            'pinned_comment': ('✨ ' + benefit + '\n' + CTA) if benefit else ''}
