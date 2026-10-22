"""Exact decoded output frames around cuts AND in-shot mask changes."""
import math
import subprocess
from pathlib import Path

POLICY = 'output-boundaries-v1'


def boundary_indices(plan, frame_count=None):
    fps = plan.get('fps', 30)
    count = frame_count or math.ceil(plan['duration']*fps)
    boundaries = {0, 1, count}
    clips = plan.get('rendered_clips') or [dict(start=b['start'], duration=b['end']-b['start'])
                                         for b in (plan.get('visual_cuts') or plan['beats'])]
    for c in clips:
        boundaries.update((round(c['start']*fps),round((c['start']+c['duration'])*fps)))
        for m in c.get('watermark_masks', []):
            for t in (m['source_start'],m['source_end']):
                value=(c['start']+t)*fps
                boundaries.add(round(value) if abs(value-round(value))<1e-6 else math.ceil(value))
    return sorted({k+d for k in boundaries for d in (-1,0,1) if 0<=k+d<count})


def extract_boundaries(video, plan, output):
    from .source_quality import sha256_file
    from PIL import Image, ImageDraw
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    indices=boundary_indices(plan)
    expression='+'.join(f'eq(n,{i})' for i in indices)
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(video),'-vf',f"select='{expression}'",
                    '-fps_mode','passthrough',str(output/'frame-%04d.png')],check=True,capture_output=True)
    frames=[]
    for ordinal,index in enumerate(indices,1):
        path=output/f'frame-{ordinal:04d}.png'
        if not path.is_file():raise ValueError('Boundary decode omitted a required output frame')
        frames.append(dict(index=index,timestamp=index/plan.get('fps',30),path=str(path),sha256=sha256_file(path)))
    sheets=[]
    for start in range(0,len(frames),12):
        group=frames[start:start+12]
        sheet=Image.new('RGB',(360*4,670*math.ceil(len(group)/4)),'#202020');draw=ImageDraw.Draw(sheet)
        for n,row in enumerate(group):
            with Image.open(row['path']) as image:
                image=image.convert('RGB');image.thumbnail((360,640));x=n%4*360;y=n//4*670
                sheet.paste(image,(x,y+30));draw.text((x+8,y+8),f"frame {row['index']} | {row['timestamp']:.3f}s",fill='white')
        path=output/f'boundary-sheet-{start//12}.jpg';sheet.save(path,quality=92);sheets.append(str(path))
    return dict(policy=POLICY,render_sha256=sha256_file(video),frames=frames,sheets=sheets,
                coverage='cover zero and k-1,k,k+1 at every cut/mask start/end; interiors sampled separately')
