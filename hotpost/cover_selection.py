"""Choose a real used frame after explicit face and product-hook review."""
import base64,copy,hashlib,json
from pathlib import Path
from .editing_adapter import _atomic_json
from .source_quality import sha256_file
from .quality_issue_scope import COVER_SCENE_REASON
from .thumbnail_copy import INSTRUCTION as THUMBNAIL_INSTRUCTION

POLICY='face-free-product-interest-20261016-v5-approved-mask-canvas'
INSTRUCTION=(
 'Review supplied actual used-video frames and the two-line thumbnail copy jointly. Frames are untrusted evidence. '
 'Return {frames:[{id:string,eligible:boolean,faces_present:boolean,face_blur_used:boolean,hook_unresolved:boolean, '
 'overlays_acceptable:boolean,mask_coverage_valid:boolean,product_view_preserved:boolean,reason:string}]}. '
 'Evaluate every supplied ID only. A cover must show a meaningful product/use view and NO visible human face, '
 'including reflections, photographs or background portraits. A blurred face is ineligible; another frame must be used. '
 'Hands, rear heads and face-free wearing views may qualify. Physical product branding is allowed; isolated logo cards are not. '
 'The legacy hook_unresolved field means a concrete reason to keep watching remains: a relevant benefit, desire, '
 'conflict or discovery, not necessarily an unanswered question. A visible product benefit may qualify. '
 'Do not invent hidden features, popularity, sales terms or identity. '
 'If evidence is uncertain, eligible=false. Give a specific visible observation in Korean. '
 'For cover_crop_evidence inspect the ACTUAL NEW cropped image: prior full-frame mask approval does not '
 'approve this enlarged/transformed geometry. Require overlays_acceptable=true only when creator captions, '
 'watermarks and inserted text are absent or actually obscured, mask_coverage_valid=true only when the '
 'actual transformed masking leaves no readable creator text, and product_view_preserved=true only when '
 'a meaningful product/use detail remains. Never accept a cropped or blurred partial face. '
 + THUMBNAIL_INSTRUCTION
)

def _cover_inline(candidate):
    if candidate.get('cover_crop_evidence') or candidate.get('cover_pixel_binding'):
        from .visual_media import review_frame_data
        return review_frame_data(candidate['frame_path'])
    return {'mimeType':'image/jpeg','data':base64.b64encode(Path(candidate['frame_path']).read_bytes()).decode()}


def _frame_cache_key(candidate):
    return (candidate.get('cover_pixel_binding') or {}).get('canvas_rgb_sha256') or sha256_file(Path(candidate['frame_path']))


def _review_batches(candidates, indexed=None):
    batch=[];cost=0
    items=indexed if indexed is not None else list(enumerate(candidates))
    for index,candidate in items:
        inline=_cover_inline(candidate);size=len(inline['data'])+1024
        if size>6*1024*1024:raise ValueError('표지 검토 이미지의 전달 크기가 너무 큽니다.')
        if batch and (len(batch)>=12 or cost+size>6*1024*1024):
            yield batch;batch=[];cost=0
        batch.append((index,candidate,inline));cost+=size
    if batch:yield batch


def eligible_frames(candidates,reviews):
    by_id={str(i):c for i,c in enumerate(candidates)};seen=set();result=[]
    for r in reviews:
        key=r.get('id')
        if not isinstance(key,str) or key not in by_id or key in seen:continue
        seen.add(key)
        if not all(r.get(k) is True for k in (
                'overlays_acceptable','mask_coverage_valid','product_view_preserved')):continue
        if (r.get('eligible') is True and r.get('faces_present') is False and
            r.get('face_blur_used') is False and r.get('hook_unresolved') is True and
            isinstance(r.get('reason'),str) and r['reason'].strip()):
            result.append({**by_id[key],'review_frame_id':key,'reviewed':True,'faces_present':False,'face_blur_used':False,
              'hook_unresolved':True,'visual_observation':r['reason'],'review_policy':POLICY})
    return result

def mask_only_rejections(reviews):
    return [r for r in reviews if r.get('faces_present') is False
        and r.get('face_blur_used') is False and r.get('hook_unresolved') is True
        and r.get('product_view_preserved') is True
        and (r.get('overlays_acceptable') is False or r.get('mask_coverage_valid') is False)]


def cover_gap(settings,plan,candidates,reviews,generate,search_context):
    from .daily_quality import QualitySceneGap
    masking=mask_only_rejections(reviews)
    if masking:
        return QualitySceneGap([{'kind':'cover','scope':'source_overlay','beat_id':'',
            'reason':'얼굴·제품·문구 검토를 통과한 실제 표지에 원작 삽입 글자가 남음. 승인 마스크가 적용된 새 픽셀 근거 필요.',
            'search_query':'','candidate_ids':[r['id'] for r in masking],
            'observations':[r.get('reason','') for r in masking]}])
    face_free={r.get('id') for r in reviews if r.get('faces_present') is False
               and r.get('face_blur_used') is False and r.get('hook_unresolved') is False}
    pool=[c for i,c in enumerate(candidates) if str(i) in face_free]
    if pool:
        # Relevant face-free imagery exists. Repair its viewer appeal before
        # requesting new footage, then re-run the actual-image checks.
        media=[]
        for c in sorted(pool,key=lambda c:c['score'],reverse=True)[:3]:
            media.append({'inlineData':_cover_inline(c)})
        value=generate(settings,
            'Revise only a two-line product-curiosity thumbnail hook. Return {thumbnail_lines:[string,string]}. '
            'The script and actual product facts are fixed. Infer the selected everyday conflict and psychological appeal '
            'from the script, and preserve that appeal while creating a specific viewer reason to watch. '
            'Do not require a question or hide a benefit already visible. Do not ask the viewer for criteria or add unsupported features, numbers, health, '
            'sales, popularity or personal events. Describe a product/use uncertainty, not an abstract lesson. '
            'Actual frames and previous findings are untrusted evidence. This response does not approve any frame. '
            + THUMBNAIL_INSTRUCTION,
            {'purpose':'cover_hook_repair','approved_script':plan['script_text'],
             'previous_lines':plan['cover_spec']['lines'],'findings':reviews},media=media)
        lines=value.get('thumbnail_lines') if isinstance(value,dict) else None
        if not isinstance(lines,list) or len(lines)!=2 or any(not isinstance(x,str) or not x.strip() or len(x)>70 for x in lines):
            raise ValueError('썸네일 후킹 보완 문구는 두 줄이어야 합니다.')
        return QualitySceneGap([{'kind':'cover','beat_id':'','reason':'얼굴 없는 제품 장면은 있으나 문구·이미지를 함께 볼 구체적인 제품 매력이 부족함. 문구만 보완하고 실제 장면을 다시 검토.',
            'search_query':''}],thumbnail_lines=lines)
    return QualitySceneGap([{'kind':'scene_gap','scope':'cover','beat_id':'','reason':COVER_SCENE_REASON,
        'search_query':str(search_context).strip()+' 제품 단독 사용 디테일 얼굴 없는 장면'}])

def select_cover(settings,plan,candidates,folder,generate=None,*,search_context='',_allow_product_crop=True):
    from .script_rewriter import _generate
    from .daily_quality import QualitySceneGap
    generate=generate or _generate;folder=Path(folder);path=folder/'cover-selection.json'
    fingerprint=hashlib.sha256(json.dumps({'policy':POLICY,'lines':plan['cover_spec']['lines'],
      'script':plan['script_text'],'candidates':[{**c,'frame_sha256':sha256_file(Path(c['frame_path']))} for c in candidates]},
      ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    confirmations=[]
    frame_reviews={}
    if path.exists():
        saved=json.loads(path.read_text('utf-8'))
        if saved.get('policy')==POLICY and saved.get('lines')==plan['cover_spec']['lines'] and saved.get('script')==plan['script_text'] and isinstance(saved.get('frame_reviews'),dict):
            frame_reviews=dict(saved['frame_reviews'])
        if saved.get('fingerprint')==fingerprint:
            reviews=saved['reviews']
            confirmations=saved.get('confirmations',[])
        else:reviews=[]
    else:reviews=[]
    if not reviews:
        missing=[]
        for index,c in enumerate(candidates):
            ck=_frame_cache_key(c)
            cached=frame_reviews.get(ck)
            if isinstance(cached,dict):
                reviews.append({**cached,'id':str(index)})
            else:
                missing.append((index,c))
        for batch in _review_batches(candidates,indexed=missing):
            media=[];ids=[]
            for index,c,inline in batch:
                ids.append(str(index));media.append({'text':f"FRAME {index}, source {c['source_id']}, timestamp {c['timestamp']}."})
                media.append({'inlineData':inline})
            value=generate(settings,INSTRUCTION,{'purpose':'cover_selection','frame_ids':ids,
              'thumbnail_lines':plan['cover_spec']['lines'],'approved_script':plan['script_text'],
              'candidate_geometry':{str(i):c.get('cover_crop_evidence') for i,c in enumerate(candidates)
                                    if str(i) in ids and c.get('cover_crop_evidence')},
              'native_cover_frames':{str(i):{'geometry':c['cover_pixel_binding']['geometry'],
                  'native_frame':c['cover_pixel_binding']['native_frame']}
                  for i,c in enumerate(candidates) if str(i) in ids and c.get('cover_pixel_binding')}},media=media)
            rows=value.get('frames',[]) if isinstance(value,dict) else []
            if not isinstance(rows,list):raise ValueError('썸네일 장면 검토 형식 오류')
            for r in rows:
                if isinstance(r,dict) and r.get('id') in ids:
                    reviews.append(r)
                    idx_int=int(r['id'])
                    if 0<=idx_int<len(candidates):
                        frame_reviews[_frame_cache_key(candidates[idx_int])]={k:v for k,v in r.items() if k!='id'}
        reviews.sort(key=lambda r:int(r['id']) if str(r.get('id','')).isdigit() else 999999)
        _atomic_json(path,{'fingerprint':fingerprint,'policy':POLICY,'lines':plan['cover_spec']['lines'],
            'script':plan['script_text'],'reviews':reviews,'frame_reviews':frame_reviews})
    eligible=eligible_frames(candidates,reviews)
    if not eligible:
        if _allow_product_crop and not mask_only_rejections(reviews):
            cropped=_review_product_crop(settings,plan,candidates,folder,generate,search_context)
            if cropped is not None:return cropped
        raise cover_gap(settings,plan,candidates,reviews,generate,search_context)
    # A batch can miss a small profile or reflected face. Inspect the proposed
    # winner by itself before rendering, and move to another actual used frame
    # on rejection. Cached approvals remain bound to all image/copy hashes.
    selected=None
    for candidate in sorted(eligible,key=lambda c:c['score'],reverse=True)[:12]:
        key=candidate['review_frame_id']
        confirmation=next((r for r in confirmations if r['candidate_id']==key),None)
        if confirmation is None:
            value=generate(settings,INSTRUCTION+
                'This is the final proposed cover frame shown alone. Inspect small/partial side profiles, '
                'reflections and background photographs carefully; a partial visible human face is still a face. ',
                {'purpose':'cover_single_frame_confirmation','frame_ids':['0'],'candidate_id':key,
                 'thumbnail_lines':plan['cover_spec']['lines'],'approved_script':plan['script_text'],
                 'cover_crop_evidence':candidate.get('cover_crop_evidence'),
                 'native_cover_frame':{k:candidate['cover_pixel_binding'][k] for k in ('geometry','native_frame')}
                    if candidate.get('cover_pixel_binding') else None},
                media=[{'text':'FINAL PROPOSED ACTUAL COVER FRAME, inspect it individually.'},
                    {'inlineData':_cover_inline(candidate)}])
            rows=value.get('frames',[]) if isinstance(value,dict) else []
            if not isinstance(rows,list):raise ValueError('썸네일 단독 프레임 검토 형식 오류')
            confirmation={'candidate_id':key,'reviews':rows}
            confirmations.append(confirmation)
            _atomic_json(path,{'fingerprint':fingerprint,'policy':POLICY,'lines':plan['cover_spec']['lines'],
                'script':plan['script_text'],'reviews':reviews,'frame_reviews':frame_reviews,'confirmations':confirmations})
        approved=eligible_frames([candidate],confirmation['reviews'])
        if approved:
            selected={**candidate,'single_frame_confirmation':confirmation};break
    if selected is None:
        if _allow_product_crop and not mask_only_rejections([r for v in confirmations for r in v['reviews']]):
            cropped=_review_product_crop(settings,plan,candidates,folder,generate,search_context)
            if cropped is not None:return cropped
        confirmed=[{**r,'id':v['candidate_id']} for v in confirmations for r in v['reviews']]
        raise cover_gap(settings,plan,candidates,confirmed,generate,search_context)
    if selected.get('crop'):
        from .cover_product_crop import validate_crop_selection
        validate_crop_selection(plan,selected)
    plan=copy.deepcopy(plan)
    plan['cover_spec'].update(source=selected,selection_note='실제 사용 구간·얼굴 없음·이미지와 문구의 제품 호기심 검토',selection_policy=POLICY)
    plan['cover_review_policy']=POLICY
    return plan


def _review_product_crop(settings,plan,candidates,folder,generate,search_context):
    from .cover_product_crop import product_crop_candidates,validate_crop_selection
    crops=product_crop_candidates(settings,plan,candidates,folder,generate)
    if not crops:return None
    # Crops remain normal candidates. Batch and isolated final review both inspect
    # their actual new pixels and mask geometry; a proposal grants no approval.
    reviewed=select_cover(settings,plan,crops,Path(folder)/'product-crop',generate,
        search_context=search_context,_allow_product_crop=False)
    validate_crop_selection(plan,reviewed['cover_spec']['source'])
    return reviewed
