"""Keep narration, visible text and post captions distinct in writing inputs."""
import hashlib
import re

COMMENT_KEYWORD = '나도'

def comment_keyword(text):
    # Quote/bracket/emoji wrappers are common in typed Instagram captions.
    wrap = r'[^가-힣A-Za-z0-9\n]*'
    keyword = r'([가-힣A-Za-z0-9]{1,20})'
    quote = r'[\'"‘’“”\[\]]'
    leave = r'(?:남(?:겨|기)|쓰(?:면|세|시)|적(?:어|으))'
    patterns = [
        r'댓글\s*(?:에|로)?\s*(?:[한두세네1234]\s*글자)?\s*[（(]\s*' + keyword + r'\s*[)）]\s*' + leave,
        r'댓글(?:에|로)?' + wrap + keyword + wrap + r'\s*(?:이라고|라고)?\s*' + leave,
        quote + keyword + quote + r'\s*(?:이라고|라고)?\s*(?:댓글(?:에|로)?\s*)?' + leave,
        r'(?:정보는|비법은|궁금하시면|궁금하신\s*분은)\s+' + keyword + r'\s*' + leave,
        r'(?:^|\n)' + wrap + keyword + r'\s+' + leave,
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, str(text)):
            if re.fullmatch(r'(?:아무)?댓글(?:에|로|을|이나|하나|한번)?', match.group(1)):
                continue
            if match.group(1) not in {
            '아무거나', '아무', '댓글', '두글자', '세글자', '후기', '의견',
            '감상', '한마디', '자유롭게', '말씀', '질문', '정보',
            '이나', '에', '로', '을', '한번', '아무댓글', '아무댓글이나', '댓글이나',
            }:
                return match.group(1)
    return ''


def context(payload):
    """These are reference claims, not independently verified product facts."""
    return [{
        'id': 'C1', 'kind': 'post_caption', 'title': '원본 게시물 본문',
        'text': payload['reference_caption'], 'independently_verified': False,
        'sha256': hashlib.sha256(payload['reference_caption'].encode()).hexdigest(),
    }] if payload.get('reference_caption', '').strip() else []


def choose_keyword(reference, caption=''):
    # Source keyword extraction stays available for evidence; new narration
    # follows the user's fixed CTA rather than borrowing the reference CTA.
    return COMMENT_KEYWORD, 'user_fixed'


def comment_issues(text, keyword=None):
    """Shared writing/recovery checks; no feature metadata required."""
    keyword=COMMENT_KEYWORD
    issues=[]
    if keyword not in text or not re.search(r'댓글|남겨',text):
        issues.append('주제와 연결되는 댓글 유도가 없습니다.')
    extracted=comment_keyword(text)
    if extracted and extracted!=keyword:
        issues.append('댓글 요청의 키워드가 선택한 키워드와 다릅니다.')
    if len(re.findall(r'댓글(?:에|로)?',text))>1:
        issues.append('댓글 요청이 반복됩니다. 선택한 키워드로 한 번만 요청하세요.')
    if re.search(r'(?:정보|링크|할인|선물).{0,15}(?:보내|드릴|드려)',text):
        issues.append('확인되지 않은 댓글 보상을 약속했습니다.')
    tail=r'댓글에\s*[\'"‘’“”]?'+re.escape(keyword)+r'[\'"‘’“”]?\s*남겨주세요[.!。]?\s*$'
    if not re.search(tail,text):
        issues.append('대본은 “댓글에 ‘나도’ 남겨주세요.” 한 문장으로 바로 끝내세요.')
    if re.search(r'(?:궁금(?:하면|하신\s*분|하시면)|마지막으로|끝으로)[^.!?。\n]{0,60}댓글에',text):
        issues.append('댓글 조건이나 종료 예고를 빼고 본문 뒤에 짧은 댓글 요청만 붙이세요.')
    return issues


def source_record(reference, kind='speech'):
    kinds = {
        'speech': ('reference_narration', '원본 발화'),
        'screen_text': ('reference_screen_text', '원본 화면 글자'),
        'mixed': ('reference_mixed', '원본 발화·화면 글자 대조본'),
        'provided_text': ('reference_text', '저장된 원본 대본 · 출처 구분 미확인'),
    }
    source_kind, title = kinds[kind]
    return {'id': 'R1', 'kind': source_kind, 'title': title, 'text': reference, 'url': ''}
