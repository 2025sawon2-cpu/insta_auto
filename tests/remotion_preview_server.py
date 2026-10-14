"""Manual browser/MP4 QA using an isolated database and synthetic media on localhost:8792."""
import hashlib
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.studio_http import StudioHTTP
from hotpost.studio_workflow import snapshot

ROOT = Path(__file__).resolve().parents[1]
studio = Studio(Settings(data_dir=ROOT/'data/remotion-qa', source_min_usable=1), workers=False)
state, _ = studio.store.create('remotion-qa-'+str(int(time.time())), '편집 기능 검증 · 가상 테스트 영상',
                               {'protocol': 2, 'active': False, 'stage': 'completed'})
folder = studio.folder(state['id'])
video, voice = folder/'qa-clean.mp4', folder/'qa-voice.wav'
ffmpeg = shutil.which('ffmpeg')
if not ffmpeg:raise RuntimeError('FFmpeg must be on PATH for synthetic-media QA')
subprocess.run([ffmpeg,'-y','-v','error','-f','lavfi','-i','color=c=0x294c5a:s=1080x1920:r=30:d=3',
    '-f','lavfi','-i','sine=frequency=440:duration=3','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',
    '-c:a','aac','-shortest',str(video)],check=True)
subprocess.run([ffmpeg,'-y','-v','error','-i',str(video),'-vn',str(voice)],check=True)
poster = folder/'qa-poster.png'
subprocess.run([ffmpeg,'-y','-v','error','-i',str(video),'-frames:v','1',str(poster)],check=True)
plan = {'duration':3,'sources':[],'shots':[],
        'beats':[{'id':'b1','cue_id':'c1','text':'테스트 자막','start':0,'end':3,'emphasis':0}],
        'cues':[{'id':'c1','text':'테스트 자막','start':0,'end':3}],
        'voice':{'duration':3},'warnings':[], 'output_dir':str(folder)}
plan['cover_spec']={'lines':['첫 프레임만 바꾸세요','영상은 그대로'], 'background_path':str(poster)}
path=folder/'timeline.json';path.write_text(json.dumps(plan,ensure_ascii=False),encoding='utf-8')
def prepare(s,db):
    s.update(status='completed',original_text='가상 테스트 영상',
        sources=[{'id':'qa-source','path':str(video),'sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'rights':'user_supplied','source_quality':'clean-source'}],
        scripts=[{'id':'qa-script','text':'테스트 자막','created':time.time()}],script_id='qa-script',approved_script_id='qa-script',
        voices=[{'id':'qa-voice','script_id':'qa-script','path':str(voice),'duration':3,'sha256':hashlib.sha256(voice.read_bytes()).hexdigest()}],voice_id='qa-voice',approved_voice_id='qa-voice',
        edits=[{'id':'qa-edit','script_id':'qa-script','voice_id':'qa-voice','plan_path':str(path),'duration':3,'created':time.time(),
            'preview_path':str(video),'clean_preview_path':str(video),'export_path':str(video),'cover_path':str(poster),'export_verified':True}],edit_id='qa-edit')
    db.execute("UPDATE jobs SET status='done'")
    run=snapshot(s);run['status']='completed';s['latest_completed_run_id']=run['id']
studio.store.change(state['id'],prepare)
def render_queued():
    job=studio.store.claim('media')
    if not job:return
    try:
        state=studio.store.get(job['task_id']);result=studio._revision(state,job)
        studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
    except Exception as exc:
        print('QA render error:',repr(exc),flush=True)
        studio.store.fail(job,exc)
class Handler(StudioHTTP,SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT/'web'),**kwargs)
    def _json(self,value,status=200):
        body=json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
        self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.path.startswith('/api/studio/intake'):return self._json({'available':False})
        if self.path.startswith('/api/studio/voices'):return self._json({'voices':[]})
        if self.path.startswith('/api/display-settings'):return self._json({})
        if self.studio_get(studio):return
        super().do_GET()
    def do_POST(self):
        if self.studio_post(studio):
            if self.path.endswith(('/export-overlays','/export-thumbnail')):threading.Thread(target=render_queued,daemon=True).start()
            return
        self._json({'error':'QA endpoint only'},404)
    def log_message(self,*args):pass
print('Remotion QA: http://localhost:8792/studio.html?work='+state['id']+'&tab=edit',flush=True)
ThreadingHTTPServer(('127.0.0.1',8792),Handler).serve_forever()
