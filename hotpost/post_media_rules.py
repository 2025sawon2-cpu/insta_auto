"""Shared rules for independent publication edits (no production runner)."""
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont


DISCLOSURE_VERSION = 'upper-right-gray-v1'
OPENING_FILLER = re.compile(r'^\s*(?:우와|어머|오호|아|어|오|와|헉)(?=$|[\s,!！.。?？:：~～"\u201c\u201d\u2018\u2019])\s*[,!！.。?？:：~～"\u201c\u201d\u2018\u2019]*\s*')


def without_opening_interjection(text):
    while True:
        cleaned = OPENING_FILLER.sub('', text, count=1)
        if cleaned == text:
            return text
        text = cleaned


def require_content_opening(text):
    if not text.strip() or text != without_opening_interjection(text):
        raise ValueError('낭독 대본은 감탄사를 빼고 내용으로 바로 시작해야 합니다.')


def disclosure_layer(size, font_path):
    """Small light-gray disclosure, with safe margins and a subtle dark edge."""
    width, height = size
    font = ImageFont.truetype(str(font_path), max(12, round(width * 40 / 1080)))
    layer = Image.new('RGBA', size)
    draw = ImageDraw.Draw(layer)
    draw.text((width-round(width*.05), round(height*.04)), '[광고]', font=font,
              anchor='rt', fill='#bdbdbd', stroke_width=max(1, round(width/1080)),
              stroke_fill=(40,40,40,140))
    return layer


def mark_cover(path, font_path):
    path = Path(path)
    with Image.open(path) as source:
        image = source.convert('RGBA')
    Image.alpha_composite(image, disclosure_layer(image.size, font_path)).convert('RGB').save(path)
