"""Immutable preparation bundles bound to real media and query evidence."""
import copy
import hashlib
import json
from pathlib import Path
from .source_access_preflight import SourceAccessWaiting

PREPARATION_POLICY = 'source-preparation-sha-v1'


class PreparationEvidenceWaiting(SourceAccessWaiting, ValueError):
    """Missing/changed evidence waits without retry or quality failure charging."""


def query_policy():
    from . import source_planning
    return getattr(source_planning, 'QUERY_PLAN_POLICY', 'legacy-query-plan')


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def evidence_key(caption, transcript):
    value={'caption':caption, **{k:transcript.get(k,'') for k in ('speech','screen_text','reference_kind')}}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def payload_key(value):
    body={k:v for k,v in value.items() if k!='payload_sha256'}
    return hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def bundle_paths(settings,shortcode,caption,transcript):
    # Compact filenames keep atomic-write temporary paths within Windows limits.
    key=evidence_key(caption,transcript)[:24]
    stamp=hashlib.sha256(query_policy().encode()).hexdigest()[:8]
    directory=Path(settings.data_dir)/'source-preparations'/shortcode
    return directory/(key+'.json'),directory/(key+'-'+stamp+'.json')


def verify_acceptance(value,path,context=None,expected_reference=None):
    if expected_reference and digest(value['reference']) != expected_reference:
        raise PreparationEvidenceWaiting('저장된 준비 원본이 현재 작업의 기준 영상과 다릅니다.')
    for row in (context or {}).get('rounds',[]):
        manifest=Path(row.get('manifest_path') or '__missing__')
        if manifest.is_file():
            try:receipt=json.loads(manifest.read_text('utf-8'))
            except (ValueError,OSError) as exc:
                raise PreparationEvidenceWaiting('작업 수용 소스 영수증을 확인할 수 없습니다.') from exc
            if receipt.get('preparation_bundle_path')==str(Path(path).resolve()) and receipt.get('preparation_bundle_sha256') != digest(path):
                raise PreparationEvidenceWaiting('작업 수용 영수증의 소스 준비 SHA가 변경되었습니다.')


def save_bundle(path, caption, raw_transcript, reference, frames, sheet, **data):
    from .editing_adapter import _atomic_json
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    files=[reference,*frames,sheet]
    bundle={'policy':PREPARATION_POLICY,'query_policy':query_policy(),
            'evidence_key':evidence_key(caption,raw_transcript),
            'reference':str(Path(reference).resolve()), 'frames':[str(Path(f).resolve()) for f in frames],
            'sheet':str(Path(sheet).resolve()),
            'files':[{'path':str(Path(f).resolve()),'sha256':digest(f)} for f in files], **copy.deepcopy(data)}
    bundle['payload_sha256']=payload_key(bundle)
    _atomic_json(Path(path),bundle)
    return bundle


def load_bundle(path, caption, transcript):
    path=Path(path)
    try:
        value=json.loads(path.read_text('utf-8'))
    except (ValueError,OSError) as exc:
        raise PreparationEvidenceWaiting('저장된 소스 준비 영수증을 읽을 수 없습니다.') from exc
    if (not isinstance(value,dict) or not isinstance(value.get('frames'),list)
            or not isinstance(value.get('files'),list) or not value.get('reference') or not value.get('sheet')
            or any(not isinstance(row,dict) or not row.get('path') or not row.get('sha256') for row in value['files'])):
        raise PreparationEvidenceWaiting('저장된 소스 준비 영수증의 구조가 잘못되었습니다.')
    if value.get('payload_sha256') != payload_key(value):
        raise PreparationEvidenceWaiting('저장된 소스 준비 계획·전사 내용의 결속 SHA가 변경되었습니다.')
    if value.get('policy') != PREPARATION_POLICY or value.get('evidence_key') != evidence_key(caption,transcript):
        raise PreparationEvidenceWaiting('저장된 소스 준비 원문 근거가 변경되었습니다. 자동 재추출하지 않습니다.')
    required=[value['reference'],*value['frames'],value['sheet']]
    receipts={r['path']:r['sha256'] for r in value.get('files',[])}
    try:
        invalid=not value['frames'] or any(str(Path(p).resolve()) not in receipts or not Path(p).is_file()
            or digest(p)!=receipts[str(Path(p).resolve())] for p in required)
    except (OSError,TypeError,ValueError) as exc:
        raise PreparationEvidenceWaiting('저장된 소스 준비 영상·프레임을 확인할 수 없습니다.') from exc
    if invalid:
        raise PreparationEvidenceWaiting('저장된 소스 준비 영상·프레임 SHA가 변경되거나 소실되었습니다.')
    return value


def prior_bundle(settings, shortcode, caption, transcript, context=None):
    """Find bound preparation first; adopt legacy media with explicitly current hashes.

    Adoption does not claim historical integrity and never accepts a legacy plan
    as the current query policy. Original receipts remain unchanged.
    """
    base,current=bundle_paths(settings,shortcode,caption,transcript)
    expected_reference=(context or {}).get('expected_reference_sha256')
    older=sorted(base.parent.glob(base.stem+'-*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    for path in dict.fromkeys([current,base,*older,base.with_suffix('.media.json')]):
        if path.is_file():
            value=load_bundle(path,caption,transcript)
            verify_acceptance(value,path,context,expected_reference)
            return value,path
    paths=[r.get('manifest_path') for r in (context or {}).get('rounds',[]) if r.get('manifest_path')]
    for raw in reversed(paths):
        manifest=Path(raw)
        if not manifest.is_file():continue
        saved=json.loads(manifest.read_text('utf-8'))
        if saved.get('shortcode') != shortcode or saved.get('caption') != caption:continue
        reference=manifest.parent/'reference.mp4';sheet=manifest.parent/'reference_contact_sheet.jpg'
        frames=[manifest.parent/f for f in saved.get('reference_frames',[])]
        if not frames or not all(p.is_file() for p in [reference,sheet,*frames]):
            raise PreparationEvidenceWaiting('이전 소스 준비 자료가 소실되었습니다. 자동 재추출하지 않습니다.')
        if expected_reference and digest(reference)!=expected_reference:
            raise PreparationEvidenceWaiting('이전 소스 준비 원본이 현재 작업의 기준 영상 SHA와 다릅니다.')
        data={k:saved.get(k,[]) for k in ('visual_product_queries','google_vision_terms','openclip_product_evidence','subject_reference_indices')}
        data.update(transcript=copy.deepcopy(transcript),query_plan={**saved.get('product_evidence',{}),
            'query_details':saved.get('query_details',[])},legacy_adoption=True,
            integrity_basis='current_files_captured_not_retroactive',origin_manifest=str(manifest.resolve()))
        value=save_bundle(base,caption,transcript,reference,frames,sheet,**data)
        value['query_policy']='legacy-adopted-plan'
        value['payload_sha256']=payload_key(value)
        from .editing_adapter import _atomic_json
        _atomic_json(base,value)
        return value,base
    return None,current


def preflight_preparation(settings, state, job=None):
    """Read a current bundle for scope checks without adopting/writing legacy media."""
    from .source_finder import _post, _transcript_evidence
    post=_post(settings,state['shortcode']);transcript=_transcript_evidence(settings,state['shortcode'])
    base,current=bundle_paths(settings,state['shortcode'],post.caption,transcript)
    rounds=[*state.get('source_acquisition',{}).get('rounds',[]),
            *(job or {}).get('checkpoint',{}).get('refresh_wait_history',[])]
    if state.get('source_search_manifest_path'):
        rounds.append({'manifest_path':state['source_search_manifest_path']})
    context={'rounds':rounds}
    authoritative=state.get('reference_video')
    if authoritative and not Path(authoritative).is_file():
        raise PreparationEvidenceWaiting('현재 작업 기준 영상이 소실되었습니다.')
    expected=digest(authoritative) if authoritative else None
    older=sorted(base.parent.glob(base.stem+'-*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    for path in dict.fromkeys([current,base,*older,base.with_suffix('.media.json')]):
        if path.is_file():
            value=load_bundle(path,post.caption,transcript)
            verify_acceptance(value,path,context,expected)
            return (value.get('query_plan') if value.get('query_policy')==query_policy() else None,
                    [Path(f) for f in value['frames']])
    # Legacy media can be checked before access, without writing an adoption receipt.
    for row in reversed(rounds):
        manifest=Path(row.get('manifest_path') or '__missing__')
        if not manifest.is_file():continue
        saved=json.loads(manifest.read_text('utf-8'))
        if saved.get('shortcode')!=state['shortcode'] or saved.get('caption')!=post.caption:continue
        reference=manifest.parent/'reference.mp4';sheet=manifest.parent/'reference_contact_sheet.jpg'
        frames=[manifest.parent/f for f in saved.get('reference_frames',[])]
        if not frames or not all(p.is_file() for p in [reference,sheet,*frames]):
            raise PreparationEvidenceWaiting('이전 소스 준비 자료가 소실되었습니다. 자동 재추출하지 않습니다.')
        if expected and digest(reference)!=expected:
            raise PreparationEvidenceWaiting('이전 소스 준비 원본이 현재 작업의 기준 영상 SHA와 다릅니다.')
        return None,frames
    return None,[]
