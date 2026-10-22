"""A read-only allowlisted comparison server; no Studio API or arbitrary files."""
from __future__ import annotations
import html, json, mimetypes, re, shutil
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, unquote

BATCH_CODES=('DeNgZSYAaQc','DeNb4AsSgGw','DeOZa4ulJ0J','DeOhQMSzm5N')
LABELS={'DeNgZSYAaQc':'아이 그림 커스텀 목걸이', 'DeNb4AsSgGw':'사진 냉장고 자석',
        'DeOZa4ulJ0J':'고윤정 네이비 맨투맨 · 사진 영상', 'DeOhQMSzm5N':'마카롱 매직테이프 라벨링'}


def build_comparison(studio, codes=BATCH_CODES, *, review_codes=(), snapshot_suffix=''):
    if snapshot_suffix and not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,31}',snapshot_suffix):
        raise ValueError('Invalid comparison snapshot suffix.')
    tasks={s['shortcode']:s for s in studio.store.list()}
    selected=[]
    for code in codes:
        state=tasks.get(code,{})
        edit=next((e for e in state.get('edits',[]) if e['id']==state.get('edit_id')), {})
        review = (code in review_codes and state.get('status') == 'draft_review'
                  and edit.get('review_draft') is True)
        if (state.get('status')!='completed' and not review) or not edit.get('export_verified') or not Path(edit.get('export_path') or '__missing__').is_file():
            raise ValueError(f'{code}: 검증된 완성 영상이 아직 없습니다.')
        from .daily_quality import verified_quality_export
        if not review and not verified_quality_export(state, edit):
            raise ValueError(f'{code}: 현재 영상·편집 계획에 결속한 완성본 품질 검수가 없습니다.')
        selected.append((state,edit))
    # Separate immutable export snapshot: never point a public server at data/.
    import hashlib
    from .production import file_digest
    identities = []
    for state, edit in selected:
        originals = state.get('reference_images', []) if state.get('creation_mode') == 'photo_post' else [state['reference_video']]
        identities.append([edit['id'], file_digest(edit['export_path']), [file_digest(p) for p in originals]])
    version=hashlib.sha256(json.dumps(identities,sort_keys=True).encode()).hexdigest()[:12]
    root=studio.settings.data_dir/'public_comparisons'/(version+('-'+snapshot_suffix if snapshot_suffix else ''))
    root.mkdir(parents=True,exist_ok=True)
    assets={};sections=[]
    def copy_asset(src,name):
        src=Path(src)
        if not src.is_file():
            raise ValueError('원본 비교 파일을 확보하지 못했습니다: '+name)
        target=root/name
        if not target.is_file():
            shutil.copy2(src,target)
        if file_digest(src) != file_digest(target):
            raise ValueError('공유 스냅샷 파일이 변경되었습니다: '+name)
        assets['/'+name]=target
        return '/'+name
    for state,edit in selected:
        code=state['shortcode']; title=html.escape(LABELS.get(code,state['title']))
        final=copy_asset(edit['export_path'],code+'-final.mp4')
        poster_path=Path(edit['export_path']).parent/'comparison-poster.jpg'
        poster=''
        if poster_path.is_file():
            poster=' poster="'+copy_asset(poster_path,code+'-poster.jpg')+'"'
        if state.get('creation_mode')=='photo_post':
            images=state.get('reference_images',[])
            if not images:
                raise ValueError(code+': 원본 사진이 없습니다.')
            gallery=[]
            for i,image in enumerate(images):
                uri=copy_asset(image,code+f'-original-{i+1:02}.jpg')
                gallery.append(f'<img src="{uri}" alt="원본 사진 {i+1}" loading="lazy">')
            original='<div class="gallery">'+''.join(gallery)+'</div><p class="note">사진을 좌우로 넘겨 확인하세요.</p>'
        else:
            uri=copy_asset(state['reference_video'],code+'-original.mp4')
            original=f'<video controls playsinline preload="metadata" src="{uri}"></video>'
        used_sources=[];usage_note=''
        plan_path=Path(edit.get('plan_path') or '__missing__')
        if plan_path.is_file():
            plan=json.loads(plan_path.read_text('utf-8'))
            used_shots={b.get('selected_shot_id') for b in (plan.get('visual_cuts') or plan.get('beats',[]))}
            used_ids={s.get('source_id') for s in plan.get('shots',[]) if s.get('id') in used_shots}
            used_sources=[s for s in plan.get('sources',[]) if s.get('id') in used_ids]
            if plan.get('source_diversity_policy'):
                from .source_diversity import body_usage_report
                usage=body_usage_report(plan)
                usage_note=f'<p class="note">본문에 서로 다른 원본 {usage["used_parent_sources"]}개 사용 · 최소 {usage["minimum_parent_sources"]}개 기준</p>'
        credits=sorted({s.get('origin_url','') for s in [*used_sources,*edit.get('photo_assets',[])] if urlsplit(s.get('origin_url','')).scheme in {'http','https'}})
        credit_html=''.join('<li><a target="_blank" rel="noopener noreferrer" href="'+html.escape(u,quote=True)+'">소스 '+str(i+1)+'</a></li>' for i,u in enumerate(credits))
        kind_note=('<p class="note">원본 사진에 화면 이동·확대, 제작 음성과 자막을 넣은 사진 영상입니다.</p>' if edit.get('export_kind')=='photo_story' else '')+usage_note
        sections.append(f'<section><h2>{title}</h2><div class="pair"><article><h3>원본</h3>{original}<a href="https://www.instagram.com/p/{code}/" target="_blank" rel="noopener noreferrer">Instagram 원본 보기</a></article><article><h3>완성본</h3><video controls playsinline preload="metadata" src="{final}"{poster}></video>{kind_note}<a class="download" href="{final}?download=1" download="{code}.mp4">완성 영상 다운로드</a></article></div><details><summary>사용 소스 출처</summary><ul>{credit_html}</ul><p>출처를 보존했습니다. 다운로드 성공만으로 재사용 허가가 확인되는 것은 아닙니다.</p></details></section>')
        if state.get('status') == 'draft_review':
            illustrative = edit.get('source_coverage_complete') is False
            label = '활용 예시본 · 동일 제품 미확보' if illustrative else '재작업 검토본'
            download_label = '예시 영상 다운로드' if illustrative else '검토 영상 다운로드'
            sections[-1] = sections[-1].replace('<h3>완성본</h3>', '<h3>'+label+'</h3>').replace('완성 영상 다운로드', download_label)
    page="""<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>원본 · 완성 영상 비교</title><style>body{margin:0;background:#0d1220;color:#f3f5fa;font:16px system-ui,sans-serif}main{max-width:1000px;margin:auto;padding:24px}h1{font-size:26px}h2{font-size:19px}h3{font-size:16px;color:#a6b6d5}section{background:#171f31;border:1px solid #2b3650;border-radius:16px;padding:18px;margin:24px 0}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}article{min-width:0}video,.gallery{width:100%;height:540px;background:#050810;border-radius:10px}video{object-fit:contain}.gallery{display:flex;overflow:auto;scroll-snap-type:x mandatory}.gallery img{width:100%;height:100%;object-fit:contain;flex:0 0 100%;scroll-snap-align:start}a{color:#b3cdff;display:inline-block;margin-top:12px}.download{padding:10px 14px;background:#2d4d81;border-radius:8px;text-decoration:none}p,details{color:#b6c2d7;font-size:13px}details{margin-top:20px}@media(max-width:600px){main{padding:10px}section{padding:10px}.pair{gap:8px}video,.gallery{height:320px}h1{font-size:21px}.download{padding:8px;font-size:12px}}</style><main><h1>원본 · 완성 영상 비교</h1><p>왼쪽 원본과 오른쪽 완성본을 재생하고 비교할 수 있습니다. 총 """+str(len(selected))+'건</p>'+''.join(sections)+'</main></html>'
    index=root/'index.html';index.write_text(page,'utf-8');assets['/']=index
    (root/'share_manifest.json').write_text(json.dumps({'public_files':[p.name for p in assets.values()],'codes':list(codes)},ensure_ascii=False,indent=2),'utf-8')
    return root,assets


def handler_for(assets, *, allow_scripts=False):
    class ReadOnlyHandler(BaseHTTPRequestHandler):
        def do_GET(self): self.serve_file(False)
        def do_HEAD(self): self.serve_file(True)
        def do_POST(self): self.send_error(405)
        def log_message(self,*args): pass
        def serve_file(self,head):
            parsed=urlsplit(self.path);path=unquote(parsed.path)
            target=assets.get(path)
            if target is None or not target.is_file():
                self.send_error(404);return
            size=target.stat().st_size;start=0;end=size-1;status=200
            value=self.headers.get('Range')
            if value:
                m=re.fullmatch(r'bytes=(\d*)-(\d*)',value)
                if not m or not any(m.groups()):
                    self.range_error(size);return
                left,right=m.groups()
                if left:
                    start=int(left);end=min(int(right),size-1) if right else size-1
                else:
                    length=int(right);start=max(0,size-length)
                    if not length:
                        self.range_error(size);return
                if start>=size or start>end:
                    self.range_error(size);return
                status=206
            self.send_response(status)
            content_type=mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
            if content_type.startswith('text/'):
                content_type += '; charset=utf-8'
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(max(0,end-start+1)))
            self.send_header('Accept-Ranges','bytes')
            self.send_header('X-Content-Type-Options','nosniff')
            policy="default-src 'none'; media-src 'self'; img-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
            if allow_scripts:
                policy += "; script-src 'self'"
            self.send_header('Content-Security-Policy',policy)
            self.send_header('Referrer-Policy','no-referrer')
            if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            if target.suffix=='.mp4' and parse_qs(parsed.query).get('download')==['1']:
                self.send_header('Content-Disposition',f'attachment; filename="{target.name}"')
            self.end_headers()
            if head:return
            with target.open('rb') as file:
                file.seek(start);remaining=end-start+1
                while remaining>0:
                    chunk=file.read(min(256*1024,remaining))
                    if not chunk:break
                    try:self.wfile.write(chunk)
                    except (BrokenPipeError,ConnectionResetError):break
                    remaining-=len(chunk)
        def range_error(self,size):
            self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers()
    return ReadOnlyHandler


def server_for(assets,port=8788, *, allow_scripts=False):
    return ThreadingHTTPServer(('127.0.0.1',port),handler_for(assets,allow_scripts=allow_scripts))
