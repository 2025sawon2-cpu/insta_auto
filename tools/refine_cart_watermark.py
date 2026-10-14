"""Follow the observed moving handle with a small blur instead of a large band."""
import json,subprocess
from pathlib import Path
from PIL import Image
from hotpost.editing_adapter import _atomic_json
from hotpost.source_quality import sha256_file
ROOT=Path('data/user-feedback-revisions-20261011/DeTJ6HbKCdF/final-v2').resolve()

def main():
    plan=json.loads((ROOT/'proposed-plan.json').read_text('utf-8'))
    source=next(s for s in plan['sources'] if s['id']=='cart-youtube-v5-leg-fold')
    target=ROOT/'leg-fold-creator-tracked-blur.mp4'
    x='402-45*t';y='610-46*t'
    subprocess.run(['ffmpeg','-v','error','-y','-i',source['creator_blur_original_path'],'-an','-vf',
        f"split[base][region];[region]crop=w=190:h=54:x='{x}':y='{y}',boxblur=8:3[blur];[base][blur]overlay=x='{x}':y='{y}'",
        '-c:v','libx264','-preset','veryfast','-crf','18',str(target)],check=True,capture_output=True)
    source.update(path=str(target),sha256=sha256_file(target),creator_blur_regions_px=[],
        creator_blur_motion={'x':x,'y':y,'width':190,'height':54})
    frames=[];canvas=Image.new('RGB',(1080,600))
    for n in range(9):
        t=(source['video_meta']['duration']-.04)*(n+.5)/9;frame=ROOT/f'tracked-after-{n}.jpg'
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(target),'-frames:v','1',str(frame)],check=True,capture_output=True)
        frames.append({'path':str(frame),'sha256':sha256_file(frame),'source_timestamp':t})
        region=Image.open(frame).crop((200,470,650,700)).resize((360,200))
        canvas.paste(region,(n%3*360,n//3*200))
    canvas.save(ROOT/'tracked-creator-review.jpg',quality=95)
    for key in ('functional_review','presentation_review'):
        source[key].update(source_sha256=source['sha256'],evidence_frames=frames)
    for s in plan['shots']:
        if s['source_id']==source['id']:s.update(path=str(target),sha256=source['sha256'])
    _atomic_json(ROOT/'proposed-plan.json',plan)

if __name__=='__main__':main()
