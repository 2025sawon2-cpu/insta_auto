"""Retry one observed fish candidate after the old authentication gate was cleared."""
import json
import os
import subprocess
import time
from pathlib import Path
from PIL import Image,ImageDraw
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json as save
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file
from hotpost.tikvideo_download import with_fallback

def main():
    old=Path('data/daily-rework-20261011/DeSngDcTAUJ/discovery.json')
    rows=json.loads(old.read_text('utf-8'))['candidates']
    candidate=next(x for x in rows if x['url'].endswith('/7315732765494791432'))
    proof=Path('data/tiktok-current-recheck/20261011-195103/state.json')
    checked=json.loads(proof.read_text('utf-8'))
    assert not checked['captcha_visible'] and not checked['login_wall_visible']
    root=Path('data/quality-scope-audit-20261011-v1/fish-reception')
    root.mkdir(parents=True,exist_ok=True)
    if (root/'result.json').exists():raise RuntimeError('This explicit retry is already recorded; do not repeat it.')
    result={'url':candidate['url'],'candidate_title':candidate['title'],'original_ledger':str(old),
        'prior_failure':candidate.get('download_error'),'current_gate_recheck':str(proof),
        'retry_reason':'Prior authentication failure retained; live existing-session page now has no gate.',
        'started_at':time.time(),'editing_eligible':False,'rights':candidate.get('rights','unknown-check-before-reuse')}
    diagnostics={}
    try:
        path=with_fallback(load_settings(),candidate['url'],root/'7315732765494791432.mp4',80*1024*1024,
            deadline=time.monotonic()+330,diagnostics=diagnostics)
        result.update(path=str(path.resolve()),sha256=sha256_file(path),metadata=probe_video(path))
        bins=next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
        subprocess.run([str(bins/'ffmpeg.exe'),'-v','error','-xerror','-i',str(path),'-f','null','-'],capture_output=True,check=True,timeout=180)
        result['full_decode_passed']=True
        frames=[];sheet=Image.new('RGB',(800,1512),'#222');draw=ImageDraw.Draw(sheet)
        for i in range(16):
            t=(result['metadata']['duration']-.1)*i/15;frame=root/f'frame-{i:02}.jpg'
            subprocess.run([str(bins/'ffmpeg.exe'),'-v','error','-y','-ss',str(t),'-i',str(path),'-frames:v','1',
                '-vf','scale=200:356:force_original_aspect_ratio=decrease',str(frame)],check=True,capture_output=True)
            im=Image.open(frame);sheet.paste(im,((i%4)*200,(i//4)*378));draw.text(((i%4)*200,(i//4)*378+357),f'{t:.2f}s',fill='white')
            frames.append({'path':str(frame.resolve()),'sha256':sha256_file(frame),'timestamp':t})
        sheet.save(root/'contact.jpg',quality=95)
        result.update(frames=frames,visual_review_pending=True,status='received')
    except Exception as exc:
        result.update(status='failed',error=str(exc)[:900])
    result.update(diagnostics=diagnostics,finished_at=time.time())
    save(root/'result.json',result)
    print(json.dumps({k:result[k] for k in ['status','metadata','error'] if k in result},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
