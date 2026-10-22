"""Share only the requested perfume reference and its playback page."""
import hashlib,json,os,shutil,sqlite3,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from hotpost.comparison_share import server_for
OUT=ROOT/'data/perfume-reference-review-20261020';OUT.mkdir(exist_ok=True)
with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
    state=json.loads(db.execute('select state from tasks where id=?',('work-56d49cbfc5a64c1c',)).fetchone()[0])
source=Path(state['reference_video']);digest=hashlib.sha256(source.read_bytes()).hexdigest()
assert state['shortcode']=='DenReaeTiaA'
assert digest=='81328adfe1f89beb29b1b44ea6850a8f81517336021a2dcef319dd34539bc68d'
public=OUT/'public';public.mkdir(exist_ok=True);target=public/'reference.mp4'
if not target.exists():shutil.copyfile(source,target)
assert hashlib.sha256(target.read_bytes()).hexdigest()==digest
page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>향수 · 레퍼런스 원본 검토</title><style>
*{box-sizing:border-box}body{margin:0;background:#111827;color:#f9fafb;font:16px system-ui,sans-serif}
main{max-width:780px;margin:auto;padding:24px}h1{font-size:24px}p{color:#cbd5e1;line-height:1.6}
video{display:block;width:100%;height:min(72vh,720px);background:#000;border-radius:12px;object-fit:contain}
a{display:inline-block;margin:16px 12px 0 0;color:#bfdbfe}small{display:block;margin-top:24px;color:#94a3b8}
</style><main><h1>향수 · 레퍼런스 원본</h1><p>검색어 선정의 기준이 된 원본 영상입니다. 소리와 화면을 함께 확인해 주세요.</p>
<video controls playsinline preload="metadata" src="/reference.mp4"></video>
<a href="/reference.mp4?download=1" download="perfume-reference.mp4">원본 영상 다운로드</a>
<a href="https://www.instagram.com/reel/DenReaeTiaA/" target="_blank" rel="noopener noreferrer">Instagram 원문</a>
<small>검토 순서: 향수 → 불꽃 → 텐트<br>임시 링크는 작업 PC와 공유 서버·터널이 실행 중일 때 이용할 수 있습니다.</small>
</main></html>'''
(public/'index.html').write_text(page,'utf8')
server=server_for({'/':public/'index.html','/reference.mp4':target},port=0)
base='http://127.0.0.1:'+str(server.server_address[1])
with (OUT/'cloudflared.log').open('a',encoding='utf8') as log:
    tunnel=subprocess.Popen([str(ROOT/'data/tools/cloudflared.exe'),'tunnel','--url',base,'--no-autoupdate'],
        stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
(OUT/'server.json').write_text(json.dumps({'server_pid':os.getpid(),'tunnel_pid':tunnel.pid,
    'local_url':base,'source':str(source),'sha256':digest,'public_files':['index.html','reference.mp4']},indent=2),'utf8')
print(json.dumps({'local_url':base,'reference_sha256':digest}),flush=True)
server.serve_forever()
