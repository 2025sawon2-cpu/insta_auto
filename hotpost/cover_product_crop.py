"""Propose and rasterize cover-only crops of actual used source timestamps."""
import base64
import copy
import hashlib
import json
import math
import shutil
import io
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from .editing_adapter import _atomic_json
from .operation_progress import run_progress_command
from .source_quality import sha256_file
from .thumbnail_copy import INSTRUCTION as THUMBNAIL_INSTRUCTION

POLICY='actual-used-product-cover-crop-v2-viewer-interest'
PROPOSAL_INSTRUCTION=(
    'Propose product-only crops of supplied actual USED video frames after full-frame cover rejection. '
    'Return {crops:[{frame_id:string,crop:[left,top,right,bottom],reason:string}]}. '
    'Coordinates are normalized 0..1 in the shown vertical image. Propose at most six crops, at most one '
    'per frame, only where an actually visible meaningful garment/product/use detail remains. Exclude '
    'ALL human faces including partial profiles, reflections and photographs. Hands and face-free wearing '
    'details may remain. Do not use face blur, invent pixels/features, or propose an empty/background/logo '
    'crop. Preserve a concrete viewer benefit, desire or discovery with the supplied two-line copy; changing framing cannot '
    'prove unseen features. A proposal is not approval: the actual cropped image will be independently '
    'reviewed for product meaning, faces, hook, and transformed text/mask geometry. '+THUMBNAIL_INSTRUCTION
)


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def valid_crop(crop):
    return (isinstance(crop,list) and len(crop)==4
        and all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1 for v in crop)
        and crop[0]<crop[2] and crop[1]<crop[3]
        and round(crop[2]*1080)>round(crop[0]*1080)
        and round(crop[3]*1920)>round(crop[1]*1920))


def _bound_source(plan,candidate):
    shot=next((s for s in plan.get('shots',[]) if s.get('id')==candidate.get('shot_id')),None)
    source=next((s for s in plan.get('sources',[]) if s.get('id')==candidate.get('source_id')),None)
    timestamp=candidate.get('timestamp')
    if not shot or not source or type(timestamp) not in (int,float) or not math.isfinite(timestamp):return None
    expected=candidate.get('source_sha256')
    if (shot.get('source_id')!=source.get('id') or not isinstance(expected,str) or len(expected)!=64
            or source.get('sha256')!=expected or shot.get('sha256')!=expected):return None
    path=Path(shot.get('path',''))
    if not path.is_file() or path.resolve()!=Path(source.get('path','')).resolve() or sha256_file(path)!=expected:return None
    if not any(b.get('selected_shot_id')==shot['id'] and type(b.get('source_start')) in (int,float)
               and type(b.get('source_end')) in (int,float)
               and b['source_start']<=timestamp<b['source_end'] for b in plan.get('beats',[])):return None
    if source.get('blur_required') and not source.get('watermark_masks'):return None
    return source


def _capture_source_frame(source,timestamp,path):
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:raise RuntimeError('실제 표지 크롭 프레임 추출에 ffmpeg가 필요합니다.')
    result=run_progress_command([ffmpeg,'-hide_banner','-loglevel','info','-nostdin','-n',
        '-ss',str(timestamp),'-i',source['path'],'-frames:v','1','-progress','pipe:1',str(path)],
        progress_dir=path.parent)
    if result.returncode or not path.is_file():raise RuntimeError('실제 표지 크롭 프레임 추출 실패')


def crop_image(native_image,source,timestamp,crop,*,masked_canvas=False):
    """Match the existing engine: center fill, canvas masks, then explicit crop."""
    if not valid_crop(crop):raise ValueError('제품 표지 크롭 범위가 잘못되었습니다.')
    image=ImageOps.fit(native_image.convert('RGB'),(1080,1920),Image.Resampling.LANCZOS)
    for mask in ([] if masked_canvas else source.get('watermark_masks') or []):
        if mask.get('reviewed') is not True:raise ValueError('검토되지 않은 표지 텍스트 마스크')
        start,end=mask.get('source_start'),mask.get('source_end')
        if not all(type(v) in (int,float) and math.isfinite(v) for v in (start,end)) or not 0<=start<end:
            raise ValueError('표지 마스크 시간 범위 오류')
        if not start<=timestamp<end:continue
        rect=mask.get('rectangle') or {}
        if not all(type(rect.get(k)) in (int,float) and math.isfinite(rect[k])
                   for k in ('width','height','centerX','centerY')):
            raise ValueError('표지 마스크 좌표 오류')
        if not (.001<=rect['width']<=1 and .001<=rect['height']<=1
                and -1<=rect['centerX']<=1 and -1<=rect['centerY']<=1):
            raise ValueError('표지 마스크 좌표 범위 오류')
        width=max(2,round(rect['width']*1080));height=max(2,round(rect['height']*1920))
        x=max(0,round((rect['centerX']+1)*540-width/2))
        y=max(0,round((1-rect['centerY'])*960-height/2))
        width=min(width,1080-x);height=min(height,1920-y)
        if width<2 or height<2:raise ValueError('표지 마스크가 화면 밖에 있습니다.')
        box=(x,y,x+width,y+height)
        image.paste(image.crop(box).filter(ImageFilter.GaussianBlur(30)),box)
    box=tuple(round(v*(1080 if i%2==0 else 1920)) for i,v in enumerate(crop))
    return ImageOps.fit(image.crop(box),(1080,1920),Image.Resampling.LANCZOS)


def product_crop_candidates(settings,plan,candidates,folder,generate):
    folder=Path(folder)/'product-crop';folder.mkdir(parents=True,exist_ok=True)
    usable=[]
    for index,candidate in enumerate(candidates):
        source=_bound_source(plan,candidate)
        path=Path(candidate.get('frame_path',''))
        if source and path.is_file():
            with Image.open(path) as image:
                if abs(image.width/image.height-9/16)>.001:continue
            usable.append((index,candidate,source,sha256_file(path)))
    usable=sorted(usable,key=lambda r:r[1].get('score',0),reverse=True)[:12]
    if not usable:return []
    for _,candidate,_,_ in usable:
        if candidate.get('cover_pixel_binding'):
            from .initial_prepared_render import checked_cover
            checked_cover(plan,candidate,require_approval=False,require_mask_change=False)
    evidence={'purpose':'cover_product_crop_proposal','policy':POLICY,
        'approved_script':plan['script_text'],'thumbnail_lines':plan['cover_spec']['lines'],
        'frames':[{'id':str(i),'source_sha256':c['source_sha256'],'timestamp':c['timestamp'],
                  'frame_sha256':sha,'canvas':list(Image.open(c['frame_path']).size),'watermark_masks':s.get('watermark_masks',[])}
                  for i,c,s,sha in usable]}
    fingerprint=_hash(evidence);receipt_path=folder/'proposals.json'
    saved=json.loads(receipt_path.read_text('utf-8')) if receipt_path.is_file() else {}
    if saved.get('fingerprint')==fingerprint:rows=saved.get('crops',[])
    else:
        media=[]
        for index,candidate,_,_ in usable:
            from .visual_media import review_frame_data
            media.extend([{'text':'ACTUAL USED FRAME '+str(index)},
                {'inlineData':review_frame_data(candidate['frame_path']) if candidate.get('cover_pixel_binding') else
                    {'mimeType':'image/jpeg','data':base64.b64encode(Path(candidate['frame_path']).read_bytes()).decode()}}])
        value=generate(settings,PROPOSAL_INSTRUCTION,evidence,media=media)
        rows=value.get('crops',[]) if isinstance(value,dict) else []
        if not isinstance(rows,list):raise ValueError('제품 표지 크롭 제안 형식 오류')
        _atomic_json(receipt_path,{'fingerprint':fingerprint,'policy':POLICY,'crops':rows})
    available={str(i):(candidate,source,sha) for i,candidate,source,sha in usable}
    proposed=[];seen=set()
    for row in rows:
        if not isinstance(row,dict):continue
        key=row.get('frame_id');crop=row.get('crop');reason=row.get('reason')
        if (not isinstance(key,str) or key not in available or key in seen or not valid_crop(crop)
                or not isinstance(reason,str) or not reason.strip()):continue
        candidate,source,sha=available[key]
        binding={'policy':POLICY,'original_frame_sha256':sha,'original_frame_path':candidate['frame_path'],
            'source_sha256':candidate['source_sha256'],'timestamp':candidate['timestamp'],
            'crop':crop,'canvas':[1080,1920],'fit':'native-center-fill-masks-then-crop-center-fill',
            'watermark_masks':copy.deepcopy(source.get('watermark_masks',[]))}
        bounded=bool(candidate.get('cover_pixel_binding'))
        if bounded:
            binding.update(fit='approved-native-masked-canvas-then-crop-center-fill',
                cover_canvas_binding_sha256=candidate['cover_pixel_binding']['binding_sha256'])
        token=_hash(binding);native=folder/(token+'-native.png');target=folder/(token+'-crop.png')
        native_receipt=folder/(token+'-native.json')
        if _bound_source(plan,candidate) is None:raise ValueError('표지 크롭의 실제 소스가 변경되었습니다.')
        if native.is_file():
            saved_native=json.loads(native_receipt.read_text('utf-8')) if native_receipt.is_file() else {}
            if saved_native.get('binding')!=token or saved_native.get('sha256')!=sha256_file(native):
                raise ValueError('표지 크롭 원본 프레임 캐시의 실제 해시 결속이 불명확합니다.')
        else:
            if bounded:shutil.copyfile(candidate['frame_path'],native)
            else:_capture_source_frame(source,candidate['timestamp'],native)
            _atomic_json(native_receipt,{'binding':token,'sha256':sha256_file(native)})
        image=crop_image(Image.open(native),source,candidate['timestamp'],crop,masked_canvas=bounded)
        image.save(target)
        if _bound_source(plan,candidate) is None:raise ValueError('표지 크롭 추출 중 소스가 변경되었습니다.')
        binding.update(binding_sha256=token,native_frame_path=str(native),
            native_frame_sha256=sha256_file(native),image_sha256=sha256_file(target),
            geometry_requires_independent_review=True)
        proposed.append({**copy.deepcopy(candidate),'crop':crop,'frame_path':str(target),
            'frame_sha256':binding['image_sha256'],'cover_crop_evidence':binding,'crop_proposal_reason':reason})
        seen.add(key)
        if len(proposed)>=6:break
    _atomic_json(folder/'candidates.json',{'fingerprint':fingerprint,'candidates':proposed})
    return proposed


def validate_crop_selection(plan,selected):
    evidence=selected.get('cover_crop_evidence') or {}
    original={**selected,'frame_path':evidence.get('original_frame_path')}
    if (_bound_source(plan,original) is None or evidence.get('policy')!=POLICY
            or evidence.get('timestamp')!=selected.get('timestamp')
            or evidence.get('source_sha256')!=selected.get('source_sha256')
            or selected.get('crop')!=evidence.get('crop')
            or sha256_file(Path(evidence['original_frame_path']))!=evidence.get('original_frame_sha256')
            or sha256_file(Path(selected['frame_path']))!=evidence.get('image_sha256')):
        raise ValueError('검토한 제품 표지 크롭의 실제 이미지·소스 결속이 변경되었습니다.')
    source=_bound_source(plan,original)
    if evidence.get('watermark_masks')!=(source.get('watermark_masks') or []):
        raise ValueError('제품 표지 크롭 검토 후 마스크가 변경되었습니다.')
    binding={k:evidence.get(k) for k in ('policy','original_frame_sha256','original_frame_path',
        'source_sha256','timestamp','crop','canvas','fit','watermark_masks')}
    bounded=bool(selected.get('cover_pixel_binding'))
    if bounded:
        from .initial_prepared_render import checked_cover
        original.pop('crop',None)
        checked_cover(plan,original,require_approval=False,require_mask_change=False)
        binding['cover_canvas_binding_sha256']=evidence.get('cover_canvas_binding_sha256')
        if binding['cover_canvas_binding_sha256']!=selected['cover_pixel_binding']['binding_sha256']:
            raise ValueError('제품 크롭의 승인 마스크 캔버스 결속이 다릅니다.')
    token=_hash(binding)
    native=Path(evidence.get('native_frame_path',''))
    receipt_path=native.with_name(token+'-native.json')
    saved=json.loads(receipt_path.read_text('utf-8')) if receipt_path.is_file() else {}
    if (token!=evidence.get('binding_sha256') or not native.is_file()
            or native.name!=token+'-native.png' or saved.get('binding')!=token
            or saved.get('sha256')!=evidence.get('native_frame_sha256')
            or sha256_file(native)!=evidence.get('native_frame_sha256')):
        raise ValueError('제품 표지 크롭의 실제 프레임·기하 결속이 변경되었습니다.')
    image=crop_image(Image.open(native),source,selected['timestamp'],selected['crop'],masked_canvas=bounded)
    encoded=io.BytesIO();image.save(encoded,format='PNG')
    if hashlib.sha256(encoded.getvalue()).hexdigest()!=evidence.get('image_sha256'):
        raise ValueError('제품 표지 크롭 이미지가 검토한 실제 프레임·기하와 다릅니다.')
