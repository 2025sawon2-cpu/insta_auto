"""Recover imported work titles from the source caption, preserving user titles."""
import re


def missing_title(title, shortcode, task_id=None):
    return str(title or '').strip() in {'', shortcode, task_id, '새 쇼츠 제작', '새쇼츠제작'}


def caption_title(caption):
    text = re.sub(r'https?://\S+|#\S+', '', str(caption or '')).strip()
    return ' '.join(text.splitlines()[0].split())[:70] if text else ''
