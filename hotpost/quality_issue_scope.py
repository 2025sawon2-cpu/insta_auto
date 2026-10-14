"""Keep the face-free cover contract separate from body footage requirements."""
import hashlib
import json
from pathlib import Path

COVER_SCENE_REASON = '실제 사용 구간에서 얼굴 없이 제품 호기심을 남기는 썸네일을 확보하지 못함'


def is_cover_scene_gap(issue):
    if issue.get('kind') != 'scene_gap' or issue.get('beat_id'):
        return False
    if issue.get('scope') is not None:
        return issue['scope'] == 'cover'
    # Only the exact former server-produced issue is migrated. A body issue
    # mentioning a face or thumbnail remains a body requirement.
    return issue.get('reason') == COVER_SCENE_REASON


def approved_footage_signature(sources):
    """Actual usable files/ranges/crops, excluding labels and review timestamps."""
    from .source_quality import editing_ready, sha256_file
    rows = []
    for source in sources:
        path = Path(source.get('path') or '__missing__')
        if (not editing_ready(source) or not path.is_file()
                or sha256_file(path) != source.get('sha256')):
            continue
        row={k: source.get(k) for k in ('sha256','original_sha256')}
        row['retiming']={k:(source.get('retiming') or {}).get(k) for k in
            ('playback_rate','method','source_sha256','original_sha256','full_decode_passed')}
        for name in ('source_interval','original_interval'):
            row[name]={k:(source.get(name) or {}).get(k) for k in ('start','end')}
        row['reviewed_intervals']=[{k:w.get(k) for k in ('source_start','source_end')}
            for w in source.get('reviewed_intervals') or []]
        row['portrait_geometry']={k:(source.get('portrait_geometry') or {}).get(k) for k in
            ('canvas_width','canvas_height','fit','expected_scale','rotation','flip','coordinates')}
        row['watermark_masks']=[{k:m.get(k) for k in
            ('source_start','source_end','expected_scale','strength','rectangle')}
            for m in source.get('watermark_masks') or []]
        rows.append(row)
    serialized = sorted({json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows})
    return hashlib.sha256(json.dumps(serialized).encode()).hexdigest()


def coverage_evidence_signature(receipt):
    """Established file/range mappings, excluding prose and generated review IDs."""
    rows=[]
    for requirement in receipt.get('requirements',[]):
        if requirement.get('covered') is not True:
            continue
        matches=[{k:m.get(k) for k in ('source_sha256','source_start','source_end')}
                 for m in requirement.get('matches',[])]
        rows.append({'kind':requirement.get('kind'),'beat_id':requirement.get('beat_id'),
            'matches':sorted({json.dumps(m,sort_keys=True) for m in matches})})
    return hashlib.sha256(json.dumps(sorted({json.dumps(r,sort_keys=True) for r in rows})).encode()).hexdigest()
