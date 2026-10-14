"""Confirm a visual finding against its actual detailed frames before repair."""
from __future__ import annotations
import base64,copy
from pathlib import Path

VISUAL_KINDS={'scene_gap','repetition','watermark','caption_sync'}
SCOPE_INSTRUCTION=(
    'A previous group reported a possible issue outside its detailed frame scope. '
    'Check it again using the actual rendered start/middle/end frames supplied for the targeted beat. '
    'Do not assume the previous finding is correct or incorrect. A coarse overview cannot prove an action is absent. '
    'Retain a concrete visible problem; dismiss an absence claim when the actual beat frames clearly show the action. '
    'Report beat-specific issues only for the targeted detailed_beat_ids. Global cover or script concerns remain allowed. '
    'Use the whole sentence and the same original-product/capability rules. Return the same JSON schema.'
)

def resolve_visual_scope(settings,instruction,evidence,groups,shared_media,generate,validate):
    local=[];pending={};audits=[];frames={}
    details={b['id']:b for b in evidence.get('all_beat_details',evidence['all_beats'])}
    for index,group in enumerate(groups):
        ids={f['beat_id'] for f in group['frames']}
        for frame in group['frames']:frames.setdefault(frame['beat_id'],[]).append(frame)
        for issue in group['review']['issues']:
            bid=issue.get('beat_id')
            if issue['kind'] not in VISUAL_KINDS or not bid or bid in ids:
                local.append(issue)
            else:
                pending.setdefault((issue['kind'],bid),{'issue':issue,'reported_by_group':index})
    confirmed_keys={(i['kind'],i.get('beat_id')) for i in local}
    for key,request in pending.items():
        if key in confirmed_keys:
            audits.append({**request,'status':'also_reported_with_actual_detailed_frames'})
            continue
        bid=key[1];actual=frames.get(bid)
        if not actual or bid not in details:
            raise ValueError('다른 구간에서 보고한 지적의 실제 대사 프레임이 없습니다.')
        focused=copy.deepcopy(evidence)
        focused.update(purpose='confirm_cross_group_visual_finding',beats=[details[bid]],
            detailed_beat_ids=[bid],candidate_finding=request['issue'])
        focused.pop('previous_findings',None)
        media=list(shared_media)+[{'text':'TARGETED ACTUAL RENDERED BEAT '+bid+': '+details[bid]['text']}]
        for frame in sorted(actual,key=lambda f:f['timestamp']):
            media.append({'text':f"Actual video time {frame['timestamp']:.3f}s"})
            media.append({'inlineData':{'mimeType':'image/jpeg','data':base64.b64encode(Path(frame['path']).read_bytes()).decode()}})
        value=validate(generate(settings,instruction+' '+SCOPE_INSTRUCTION,focused,media=media),{bid})
        local.extend(value['issues'])
        audits.append({**request,'status':'confirmed' if value['issues'] else 'not_supported_by_actual_detailed_frames',
            'confirmation':value,'actual_frames':actual})
    return local,audits
