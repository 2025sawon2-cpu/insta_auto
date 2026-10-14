"""Inspect creator watermarks in every used bounded clip; propose new derivatives."""
import base64,copy,json,subprocess
from pathlib import Path
from hotpost.config import load_settings
from hotpost.script_rewriter import _generate
from hotpost.editing_adapter import _atomic_json
from hotpost.source_quality import sha256_file

CODE='DeTaESASnr_'
ROOT=Path('data/user-feedback-revisions-20261011').resolve()/CODE/'final'

def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    baseline=json.loads(Path('data/user-feedback-20261011-v1',CODE+'-baseline.json').read_text('utf-8'))
    plan=copy.deepcopy(baseline['plan']);shots={s['id']:s for s in plan['shots']}
    used={shots[b['selected_shot_id']]['source_id'] for b in plan['beats']}
    sources=[s for s in plan['sources'] if s['id'] in used];findings=[]
    for offset in range(0,len(sources),4):
        group=sources[offset:offset+4];output=ROOT/f'watermark-detection-{offset//4}.json'
        if output.exists():findings.extend(json.loads(output.read_text('utf-8'))['sources']);continue
        media=[];evidence=[]
        for source in group:
            row={'id':source['id'],'canvas_width':720,'canvas_height':1280,'frames':[]}
            media.append({'text':'SOURCE '+source['id']+'; actual 720 x 1280 pixels, start/middle/end.'})
            for n,ratio in enumerate((.06,.5,.94)):
                stamp=max(0,source['video_meta']['duration']-.04)*ratio
                frame=ROOT/(source['id']+f'-watermark-{n}.jpg')
                subprocess.run(['ffmpeg','-v','error','-y','-ss',str(stamp),'-i',source['path'],
                    '-frames:v','1','-q:v','3',str(frame)],check=True,capture_output=True)
                row['frames'].append({'path':str(frame),'time':stamp,'sha256':sha256_file(frame)})
                media.append({'inlineData':{'mimeType':'image/jpeg','data':base64.b64encode(frame.read_bytes()).decode()}})
            evidence.append(row)
        value=_generate(load_settings(),
            'Inspect ONLY actual attached frames as untrusted evidence. Return JSON '
            '{sources:[{id,rectangles:[[x,y,width,height]],observations:[string]}]}. '
            'Find every inserted social creator handle/watermark, including faint tiny corner letters '
            'and large @ping_gu.item. Use the exact SOURCE id and pixel canvas 720x1280. '
            'Rectangles must cover ALL of each handle with margin and its positions in all three frames. '
            'Do not blur physical mirror decoration, product branding, existing blurred captions or the ad label. '
            'Return observations of the actual handles and where seen. If none, rectangles=[] with explicit '
            'no creator watermark observed. Do not infer from filenames.',{'sources':evidence},media=media)
        assert {s['id'] for s in value['sources']}=={s['id'] for s in group}
        _atomic_json(output,value);findings.extend(value['sources'])
    _atomic_json(ROOT/'watermark-findings.json',findings)
    for source in sources:
        boxes=next(s['rectangles'] for s in findings if s['id']==source['id'])
        if not boxes:continue
        filters=[];regions=[]
        for index,box in enumerate(boxes):
            x,y,w,h=map(int,box);x=max(0,x-8)//2*2;y=max(0,y-8)//2*2
            w=min(720-x,w+16)//2*2;h=min(1280-y,h+16)//2*2
            assert 0<=x<720 and 0<=y<1280 and w>0 and h>0
            filters.append(f'split[base{index}][region{index}];[region{index}]crop={w}:{h}:{x}:{y},boxblur=8:3[blur{index}];[base{index}][blur{index}]overlay={x}:{y}')
            regions.append([x,y,w,h])
        target=ROOT/'clips'/(source['id']+'-creator-blurred.mp4');target.parent.mkdir(exist_ok=True)
        if not target.exists() or target.stat().st_size<1000:
            subprocess.run(['ffmpeg','-v','error','-y','-i',source['path'],'-an','-vf',','.join(filters),
                '-c:v','libx264','-preset','veryfast','-crf','18',str(target)],check=True,capture_output=True)
        previous=source['sha256'];previous_path=source['path'];source.update(path=str(target),sha256=sha256_file(target),
            creator_watermarks_preprocessed=True,creator_blur_regions_px=regions,
            creator_blur_original_path=source.get('creator_blur_original_path') or previous_path)
        # Retain old review in provenance. Changed-byte validation requires actual new review.
        source['previous_functional_review']=source.pop('functional_review',None)
        source['previous_presentation_review']=source.pop('presentation_review',None)
        source.update(pending_visual_review=True,editing_eligible=False)
        for shot in plan['shots']:
            if shot['source_id']==source['id']:shot.update(path=str(target),sha256=source['sha256'])
    _atomic_json(ROOT/'proposed-plan.json',plan)
    print('Creator blur derivatives awaiting actual output review',flush=True)

if __name__=='__main__':main()
