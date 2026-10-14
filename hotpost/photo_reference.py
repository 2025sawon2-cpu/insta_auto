"""Photo posts are visual/caption evidence, never audio transcripts or footage."""
from __future__ import annotations
import json, shutil, subprocess
from pathlib import Path
from urllib.parse import urlsplit
import requests
from PIL import Image, ImageOps
from .request_pacing import request_pause


def image_groups(value, shortcode):
    if isinstance(value, dict):
        if value.get('code', value.get('shortcode')) == shortcode:
            nodes = value.get('carousel_media') or [value]
            edges = (value.get('edge_sidecar_to_children') or {}).get('edges') or []
            if edges:
                nodes = [edge.get('node', {}) for edge in edges]
            for node in nodes:
                versions = (node.get('image_versions2') or {}).get('candidates') or []
                if versions:
                    yield max(versions, key=lambda v: v.get('width',0)*v.get('height',0)).get('url')
                elif node.get('display_url'):
                    yield node['display_url']
        for child in value.values():
            if isinstance(child, (dict,list)):
                yield from image_groups(child, shortcode)
    elif isinstance(value, list):
        for child in value:
            yield from image_groups(child, shortcode)


def browser_images(settings, shortcode):
    from .instagram_browser import InstagramBrowser
    from playwright.sync_api import Error
    browser = InstagramBrowser(settings)
    found = []
    def receive(response):
        if urlsplit(response.url).hostname not in {'instagram.com','www.instagram.com'}:
            return
        try:
            if response.status == 200 and 'json' in response.headers.get('content-type',''):
                found.extend(image_groups(response.json(), shortcode))
        except (ValueError,Error):
            pass
    try:
        browser.open()
        browser.page.on('response', receive)
        browser.navigate(f'p/{shortcode}/')
        browser.verify_identity()
        for _ in range(10):
            browser.guard()
            for raw in browser.page.locator('script[type="application/json"]').all_text_contents():
                try:
                    found.extend(image_groups(json.loads(raw),shortcode))
                except ValueError:
                    pass
            if found:
                return list(dict.fromkeys(u for u in found if u))
            browser.page.wait_for_timeout(1000)
        raise RuntimeError('해당 사진 게시물의 원본 이미지 정보를 찾지 못했습니다.')
    finally:
        browser.close()


def prepare_reference(settings, code, progress=None):
    from .source_finder import _post, _executable, probe_video
    post = _post(settings,code)
    if post.kind not in {'image','carousel'}:
        raise ValueError('사진 게시물만 사진 레퍼런스로 준비할 수 있습니다.')
    root = settings.transcript_dir / (code+'-photos-v1')
    root.mkdir(parents=True,exist_ok=True)
    receipt = root/'photo_reference.json'
    if receipt.is_file() and (root/'reference.mp4').is_file():
        data=json.loads(receipt.read_text('utf-8'))
        if all(Path(p).is_file() for p in data['reference_images']):
            return data
    progress = progress or (lambda *_:None)
    progress('사진 게시물의 실제 이미지와 캡션을 가져오는 중',10)
    urls=browser_images(settings,code)
    if not urls:
        raise ValueError('원본 사진을 확보하지 못했습니다.')
    originals=[]; frames=[]
    for i,url in enumerate(urls):
        request_pause()
        response=requests.get(url,timeout=45)
        response.raise_for_status()
        if len(response.content)>25*1024*1024:
            raise ValueError('원본 사진이 크기 제한을 초과합니다.')
        original=root/f'original-{i+1:02}.jpg'
        import io
        im=ImageOps.exif_transpose(Image.open(io.BytesIO(response.content))).convert('RGB')
        im.save(original,quality=95); originals.append(str(original))
        canvas=Image.new('RGB',(1080,1920),'#111827')
        fitted=ImageOps.contain(im,(1080,1920))
        canvas.paste(fitted,((1080-fitted.width)//2,(1920-fitted.height)//2))
        frame=root/f'frame-{i+1:02}.jpg';canvas.save(frame,quality=92);frames.append(frame)
    # Analysis-only reference: no invented movement, no audio transcription.
    concat=root/'frames.txt'
    lines=[]
    for frame in frames:
        lines.extend(["file '"+frame.name+"'",'duration 4'])
    lines.append("file '"+frames[-1].name+"'")
    concat.write_text('\n'.join(lines)+'\n','utf-8')
    run=subprocess.run([_executable('ffmpeg') or 'ffmpeg','-y','-f','concat','-safe','0','-i',str(concat),
        '-vf','fps=25','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart','-an',str(root/'reference.mp4')],
        capture_output=True,timeout=180)
    if run.returncode:
        raise RuntimeError('사진 분석용 슬라이드 준비 실패: '+run.stderr.decode('utf-8',errors='replace')[-600:])
    data={'creation_mode':'photo_post','original_text':post.caption,'original_caption':post.caption,
        'reference_kind':'provided_text','reference_speech_text':'','reference_images':originals,
        'reference_video':str(root/'reference.mp4'),'reference_duration':probe_video(root/'reference.mp4')['duration'],
        'transcript_path':str(root/'transcript.json'),'reference_text_evidence':{'kind':'post_caption','source_url':post.url},
        'photo_provenance':{'source_url':post.url,'image_urls':urls,'usage':'analysis_reference_only','rights':'unknown'}}
    (root/'transcript.json').write_text(json.dumps({'shortcode':code,'speech':[],'screen_text':[],
        'provided_text':post.caption,'reference_kind':'provided_text','methods':{'speech':'unavailable','reference':'photo_slideshow'},
        'source_url':post.url},ensure_ascii=False,indent=2),'utf-8')
    receipt.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8')
    return data


class PhotoProductionDisabled(ValueError):
    pass


def assert_creation_enabled(settings,state,kind):
    if (state.get('creation_mode')=='photo_post' and not settings.photo_production_enabled
            and kind in {'prepare','rewrite','voice','edit','revision','edit_request','quality_reedit',
                         'export','collect_sources','refresh_sources'}):
        raise PhotoProductionDisabled('사진·캐러셀 영상 제작 비활성화 · 기존 자료와 품질 이력을 보존하고 제작 실행을 보류합니다.')


def prepare_studio(studio,state,job):
    assert_creation_enabled(studio.settings,state,'prepare')
    from .studio_store import change_claimed
    job={**job,'task_id':state['id']}
    if job.get('claim_token'):
        studio.store.assert_owned(job)
    data=prepare_reference(studio.settings,state['shortcode'],lambda m,p:change_claimed(studio.store,job,lambda s,db:s.update(message=m,progress=p)))
    if job.get('claim_token'):
        studio.store.assert_owned(job)
    manifest=studio.folder(state['id'])/(job['id']+'-reference.json')
    manifest.write_text(json.dumps({'caption':data['original_caption'],'reference_kind':'photo_post',
        'reference_usage':'analysis_only','downloaded':0,'candidates':[]},ensure_ascii=False),'utf-8')
    return {**data,'manifest_path':str(manifest),'sources':state['sources']}
