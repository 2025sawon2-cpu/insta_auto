"""Immutable inputs for a single, explicitly requested Instagram publication."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .production import file_digest
from .coupang_partners import product_identity


def package_digest(package):
    value = {key: value for key, value in package.items() if key != 'package_sha256'}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def bind_package(package, state, video):
    edit = next(row for row in video['edits'] if row['id'] == state['binding']['edit_id'])
    media = {}
    for kind, field in (('video', 'export_path'), ('plan', 'plan_path'), ('cover', 'cover_path')):
        path = edit.get(field)
        if path:
            path = Path(path).resolve(strict=True)
            media[kind] = {'path': str(path), 'sha256': file_digest(path)}
    result = {**package, 'publication_contract': 'instagram-publication-v1',
              'task_id': state['task_id'], 'account': state['account'],
              'reference_shortcode': state['shortcode'], 'binding': state['binding'],
              'product_identity': product_identity(state['product']['product_url']),
              'media': media}
    result['package_sha256'] = package_digest(result)
    return result


def validate_package(state, *, require_cover=False):
    package = state.get('package') or {}
    if (package.get('publication_contract') != 'instagram-publication-v1'
            or package.get('package_sha256') != package_digest(package)
            or package.get('account') != state['account']
            or package.get('task_id') != state['task_id']
            or package.get('reference_shortcode') != state['shortcode']
            or package.get('binding') != state['binding']
            or package.get('affiliate_url') != state['affiliate']['affiliate_url']
            or package.get('product_identity') != product_identity(state['product']['product_url'])):
        raise ValueError('게시 패키지의 계정·상품·본문 연결이 바뀌었거나 패키지 검증이 필요합니다.')
    media = package.get('media') or {}
    for kind in ('video', 'plan', 'cover'):
        row = media.get(kind)
        if not row:
            if kind != 'cover' or require_cover:
                raise ValueError('검수된 영상·계획·표지 파일을 갖춘 게시 패키지가 필요합니다.')
            continue
        path = Path(row['path'])
        if not path.is_file() or not path.stat().st_size or file_digest(path) != row['sha256']:
            raise ValueError('게시 준비 이후 영상·표지·계획 파일이 바뀌었습니다.')
    if (media['video']['sha256'] != state['binding']['video_sha256']
            or media['plan']['sha256'] != state['binding']['plan_sha256']):
        raise ValueError('게시 파일과 최종 검수 결과가 다릅니다.')
    return package
