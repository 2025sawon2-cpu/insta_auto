"""Interval evidence: a file-level core label never proves every shot."""
import hashlib
import math
from pathlib import Path

POLICY = 'shot-presentation-v1'
ROLES = {'promoted_product','related_product','comparison','general_context','preparation'}


def interval_receipt(shot, value):
    """Require explicit observations and bind them to these actual frame bytes."""
    if (not isinstance(value.get('product_role'),str) or value.get('product_role') not in ROLES or type(value.get('product_visible')) is not bool
            or not value.get('visual_cluster') or not value.get('uncertainty')
            or not isinstance(value.get('visible_information'),list)):
        return None
    ratings={k:value.get(k) for k in ('composition','clarity','product_coverage','mask_product_overlap')}
    if any(type(v) not in (float,int) or not math.isfinite(v) or not 0<=v<=1 for v in ratings.values()):
        return None
    frames=[dict(path=str(p),sha256=hashlib.sha256(Path(p).read_bytes()).hexdigest())
            for p in shot.get('frames',[])]
    if not frames:return None
    visibility=value.get('frame_product_visibility')
    if (not isinstance(visibility,list) or len(visibility)!=len(frames)
            or any(type(v) is not bool for v in visibility)):
        return None
    return dict(policy=POLICY,source_sha256=shot.get('sha256'),
                source_window=[shot['start'],shot['end']],evidence_frames=frames,
                product_visible=value['product_visible'] and all(visibility),
                frame_product_visibility=visibility,
                **{k:value[k] for k in ('product_role','visible_information',
                                       'visual_cluster','uncertainty')},**ratings)


def supports_product(receipt):
    return bool(receipt and receipt.get('policy')==POLICY and receipt.get('product_visible') is True
                and receipt.get('product_role') in {'promoted_product','related_product'})


def prefer_clear_options(options, observations, catalog):
    """Break equal relation ties with current visible quality; retain every option."""
    shots={s['id']:s for s in catalog}
    ranked=list(options)
    for relation in ('direct','context','illustration'):
        positions=[];candidates=[]
        for index,option in enumerate(options):
            if option['relation']!=relation:continue
            shot=shots.get(option['shot_id'],{})
            receipt=observations.get(option['shot_id'],{}).get('shot_presentation') or {}
            if (receipt.get('policy')!=POLICY or receipt.get('source_sha256')!=shot.get('sha256')
                    or receipt.get('source_window')!=[shot.get('start'),shot.get('end')]):continue
            actual=[{'path':str(p),'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest()}
                    for p in shot.get('frames',[])]
            if not actual or receipt.get('evidence_frames')!=actual:continue
            keys=('composition','clarity','product_coverage','mask_product_overlap')
            if any(type(receipt.get(k)) not in (int,float) or not math.isfinite(receipt[k])
                    or not 0<=receipt[k]<=1 for k in keys):continue
            score=(receipt['composition']+receipt['clarity']+receipt['product_coverage']
                   -receipt['mask_product_overlap'])
            positions.append(index)
            candidates.append({**option,'presentation_preference':{
                'score':round(score,6),'reason':'같은 관련성에서 선명도·제품 노출·가림 면적 우선'}})
        candidates.sort(key=lambda o:-o['presentation_preference']['score'])
        for position,option in zip(positions,candidates):ranked[position]=option
    return ranked
