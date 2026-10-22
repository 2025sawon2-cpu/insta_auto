"""Bound original preparation pixels for isolated incident reproduction."""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
from pathlib import Path

FRAME_BYTES = 1024*1024
TOTAL_FRAME_BYTES = 6*1024*1024
MAX_FRAMES = 24


def preparation_frames(studio,state,*,include_bytes=False,diagnostics=None):
    """No media approval: retain the exact pixels used by scope deduplication."""
    from .video_agent_context import (artifact_paths,job_artifact_paths,
        _preparation_artifact_bindings,preparation_query_diagnostics,semantic_fingerprint)
    from .source_preparation import payload_key
    from .source_search.strategy import image_signature
    diagnostics=preparation_query_diagnostics(studio,state) if diagnostics is None else diagnostics
    if not any(row.get('media_sha_checked') for row in diagnostics):return []
    bindings=_preparation_artifact_bindings(studio,state,artifact_paths(state)|job_artifact_paths(studio,state))
    source_root=Path(studio.settings.source_dir).resolve()
    shortcode=state.get('shortcode','')
    result=[];remaining=TOTAL_FRAME_BYTES;count=0
    for diagnostic in diagnostics[:4]:
        name=diagnostic.get('path')
        if not diagnostic.get('media_sha_checked') or name not in bindings:continue
        group={'bundle_path':name,'bundle_sha256':bindings[name],
            'task_id':state['id'],'run_id':state.get('run_id'),
            'input_fingerprint':semantic_fingerprint(state),'status':'unverified','frames':[]}
        result.append(group)
        try:
            with Path(name).open('rb') as stream:raw=stream.read(4*1024*1024+1)
            if len(raw)>4*1024*1024 or hashlib.sha256(raw).hexdigest()!=bindings[name]:
                raise ValueError('Registered preparation bundle changed')
            bundle=json.loads(raw)
            if bundle.get('payload_sha256')!=payload_key(bundle):raise ValueError('Preparation payload changed')
            frames=bundle.get('frames')
            if not isinstance(frames,list) or not frames or len(frames)>MAX_FRAMES-count:
                raise ValueError('Original frame count exceeds capture budget')
            declared={row['path']:row['sha256'] for row in bundle['files']}
            captured=[]
            for name in frames:
                path=Path(name)
                if not path.is_absolute() or '..' in path.parts:raise ValueError('Unsafe original frame path')
                for parent in (path,*path.parents):
                    if parent==source_root:break
                    if parent.is_symlink() or getattr(parent,'is_junction',lambda:False)():
                        raise ValueError('Linked original frame')
                path=path.resolve()
                if (not path.is_relative_to(source_root) or len(path.relative_to(source_root).parts)<2
                        or not path.relative_to(source_root).parts[0].startswith(shortcode+'-')
                        or path.suffix.lower() not in {'.jpg','.jpeg','.png'}):
                    raise ValueError('Foreign original frame')
                with path.open('rb') as stream:data=stream.read(min(FRAME_BYTES,remaining)+1)
                if len(data)>FRAME_BYTES or len(data)>remaining:raise ValueError('Original frame bytes exceed capture budget')
                remaining-=len(data)
                digest=hashlib.sha256(data).hexdigest()
                if declared.get(str(path))!=digest:raise ValueError('Original frame SHA changed')
                signature=image_signature(io.BytesIO(data))
                if signature is None:raise ValueError('Original frame cannot be decoded')
                item={'path':str(path),'sha256':digest,'bytes':len(data),'image_signature':signature}
                if include_bytes:item['data_base64']=base64.b64encode(data).decode('ascii')
                captured.append(item)
            group.update(status='captured',frames=captured)
            count+=len(captured)
            group['fixture_guidance']=('The host captured these immutable original frame bytes. In isolated tests, '
                'decode preparation_frame_evidence frames data_base64 into temporary files, verify their original '
                'SHA, and consistently rebind copied preparation paths/receipts. Preserve the original pixel '
                'relationship to saved image_signature history; unrelated stand-in images change scope consumption. '
                'These are diagnostic fixture bytes, never search permission or product/quality approval.')
        except (OSError,ValueError,TypeError,KeyError,RuntimeError) as exc:
            group.update(status='unavailable',frames=[],reason=str(exc)[:250])
    return result


def frame_summary(groups):
    result=copy.deepcopy(groups)
    for group in result:
        for frame in group.get('frames',[]):frame.pop('data_base64',None)
    return result
