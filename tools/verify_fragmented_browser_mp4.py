"""Real Chrome range reception and full decode, using a local test fixture.

This proves the assembler's browser-response path, not a TikTok CDN outcome.
Only the owned localhost test tab is closed; existing user tabs stay intact.
"""
import hashlib,json,os,re,subprocess,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json
from hotpost.source_browser_runtime import attach_browser,browser_lease
from hotpost.tiktok_download import MediaAssembly,publish_video

ROOT=Path(__file__).resolve().parents[1]/'data/download-range-integration-20261011'


def main():
    ROOT.mkdir(exist_ok=True)
    bins=next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH']=str(bins)+os.pathsep+os.environ['PATH']
    fixture=ROOT/'fixture.mp4'
    if not fixture.exists():
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=360x640:rate=30',
            '-t','8','-c:v','libx264','-preset','veryfast','-crf','15','-pix_fmt','yuv420p','-movflags','+faststart',str(fixture)],check=True)
    body=fixture.read_bytes();requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.path=='/':
                page=b'<video autoplay muted controls playsinline src="/fixture.mp4" style="height:600px"></video>'
                self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(page)));self.end_headers();self.wfile.write(page);return
            if self.path!='/fixture.mp4':self.send_error(404);return
            match=re.fullmatch(r'bytes=(\d+)-(\d*)',self.headers.get('Range',''))
            if not match:self.send_error(416);return
            start=int(match[1]);end=min(start+65535,int(match[2]) if match[2] else len(body)-1,len(body)-1)
            if start>=len(body):self.send_error(416);return
            piece=body[start:end+1];requests.append({'start':start,'end':end,'bytes':len(piece)})
            self.send_response(206);self.send_header('Content-Type','video/mp4');self.send_header('Accept-Ranges','bytes')
            self.send_header('Content-Range',f'bytes {start}-{end}/{len(body)}');self.send_header('Content-Length',str(len(piece)))
            self.send_header('ETag','"local-fixture-one"');self.end_headers();self.wfile.write(piece)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{server.server_port}';assembly=MediaAssembly(20*1024*1024);received=[];errors=[];samples=[]
    try:
        with browser_lease(load_settings()),sync_playwright() as pw:
            context=attach_browser(pw,load_settings());page=context.new_page()
            def receive(request):
                response=request.response()
                if response is None or response.url!=url+'/fixture.mp4':return
                try:
                    payload=response.body();assembly.add(response.status,response.headers,payload)
                    received.append({'status':response.status,'range':response.headers.get('content-range'),'bytes':len(payload),'complete_after_response':assembly.result() is not None})
                except Exception as exc:errors.append(str(exc))
            page.on('requestfinished',receive)
            try:
                page.goto(url,wait_until='domcontentloaded',timeout=15000);deadline=time.monotonic()+45
                while time.monotonic()<deadline and assembly.result() is None and not errors:
                    samples.append(page.locator('video').evaluate('e=>({time:e.currentTime,paused:e.paused,ready:e.readyState,error:e.error?.code??null})'))
                    page.wait_for_timeout(1000)
            finally:page.remove_listener('requestfinished',receive);page.close()
        result=assembly.result()
        audit={'scope':'local real-browser multi-206 integration, not a live TikTok multi-206 success',
            'fixture_bytes':len(body),'requests':requests,'received':received,'errors':errors,'playback_samples':samples,
            'complete':result is not None,'ranges':assembly.ranges,'updated_at':time.time()}
        if result is not None:
            target=ROOT/'assembled.mp4';assert result==body;assert len(received)>1 and all(r['status']==206 for r in received)
            assert any(not r['complete_after_response'] for r in received)
            assert publish_video(result,target,8)
            subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(target),'-f','null','-'],check=True)
            audit.update(full_decode_passed=True,sha256=hashlib.sha256(result).hexdigest(),original_sha256=hashlib.sha256(body).hexdigest())
        _atomic_json(ROOT/'receipt.json',audit)
        print(json.dumps({k:v for k,v in audit.items() if k not in ('requests','received','playback_samples')},ensure_ascii=False),flush=True)
        if errors or result is None:raise RuntimeError('Actual Chrome range reception did not assemble the full fixture; inspect receipt.')
    finally:server.shutdown();server.server_close()


if __name__=='__main__':main()
