"""Prepare publishing text from the selected script, never from reference copy."""
from __future__ import annotations
import hashlib
import re

DISCLOSURE = '본 포스팅은 쿠팡파트너스 활동의\n일환으로 제품 구매시 일정액의 수수료를\n지급 받습니다!🩷'
CTA = '댓글에 ‘나도’ 남겨주세요.'
COMMENT_KEYWORD = '나도'


def script_hash(script):
    return hashlib.sha256(script.encode('utf-8')).hexdigest()


def publishing_package(script, product_name, button_text, affiliate_url):
    script = str(script).strip()
    product_name = str(product_name).strip()
    button_text = str(button_text).strip()
    if not script or not product_name or '\n' in product_name or len(product_name) > 120:
        raise ValueError('선택 대본과 확인된 짧은 제품명이 필요합니다.')
    if not button_text or len(button_text) > 18 or '\n' in button_text:
        raise ValueError('버튼 문구는 공백 포함 18자 이내 한 줄이어야 합니다.')
    if not re.fullmatch(r'https://link\.coupang\.com/a/[A-Za-z0-9_-]+/?', affiliate_url):
        raise ValueError('검증된 우리 쿠팡파트너스 단축 링크가 필요합니다.')
    # Preserve every product claim in the approved script, without introducing
    # another generation round, hashtags, prices or unverified benefits.
    body = script
    if not body.endswith(CTA):
        body += '\n\n' + CTA
    caption = DISCLOSURE + '\n\n' + body
    if len(caption) > 2200:
        raise ValueError('인스타 본문 2,200자 제한을 초과했습니다. 선택 대본을 확인하세요.')
    return dict(caption=caption, caption_basis='selected-script-verbatim-v1',
                script_sha256=script_hash(script), product_name=product_name,
                dm_message=DISCLOSURE + '\n' + product_name + '\n' + '👇' * 8,
                button_text=button_text, affiliate_url=affiliate_url,
                post_mode='next_post', comment_condition='all', reply_add_count=2)
