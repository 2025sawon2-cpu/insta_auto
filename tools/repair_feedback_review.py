"""Keep failed review renders; prepare a second revision from observed findings."""
import copy,json,subprocess
from pathlib import Path
from hotpost.editing_adapter import _atomic_json
from hotpost.source_quality import sha256_file
from hotpost.source_presentation import review_scope
from hotpost.config import load_settings
from hotpost.studio_ai import describe_shots,restrict_context_shots

ROOT=Path('data/user-feedback-revisions-20261011').resolve()

def main():
    code='DeJ7hD6zsnR';out=ROOT/code/'final-v2';out.mkdir(exist_ok=True)
    plan=json.loads((ROOT/code/'final/prepared-plan.json').read_text('utf-8'))
    excluded={'source-clip-11df0da898bcc582','source-clip-3d2f362dc1fcbf1a'}
    bad={s['id'] for s in plan['shots'] if s['source_id'] in excluded}
    for b in plan['beats']:
        b['options']=[o for o in b['options'] if o['shot_id'] not in bad]
        b.pop('selected_shot_id',None);b.pop('source_start',None);b.pop('source_end',None)
    plan['sources']=[s for s in plan['sources'] if s['id'] not in excluded]
    plan['shots']=[s for s in plan['shots'] if s['id'] not in bad]
    observations,choices=describe_shots(load_settings(),plan['shots'],plan['beats'],review_feedback=[
        {'kind':'watermark','reason':'Excluded actual source logos and repeated red/green two-jacket display. Select only the remaining actual observed scenes.'}])
    for s in plan['shots']:s.update(observations.get(s['id'],{}))
    for b in plan['beats']:
        choice=choices[b['id']]
        assert choice.get('options') and choice.get('analysis_status')!='opposite_only',b['id']
        b['options']=choice['options']
    restrict_context_shots(plan,plan['sources'])
    plan['cover_spec'].pop('source',None)
    for s in plan['sources']:s.setdefault('url',s.get('origin_url',''))
    _atomic_json(out/'prepared-plan.json',plan)
    code='DeTJ6HbKCdF';out=ROOT/code/'final-v2';out.mkdir(exist_ok=True)
    plan=json.loads((ROOT/code/'final/timeline.json').read_text('utf-8'))
    source=next(s for s in plan['sources'] if s['id']=='cart-youtube-v5-leg-fold')
    original_path=source['path'];clip=out/'leg-fold-creator-blurred.mp4'
    if not clip.exists():
        subprocess.run(['ffmpeg','-v','error','-y','-i',original_path,'-an','-vf',
            'split[base][region];[region]crop=288:180:284:488,boxblur=18:3[blur];[base][blur]overlay=284:488',
            '-c:v','libx264','-preset','veryfast','-crf','18',str(clip)],check=True,capture_output=True)
    evidence=[]
    for n,ratio in enumerate((.06,.5,.94)):
        t=(source['video_meta']['duration']-.04)*ratio;frame=out/f'active-pick-after-{n}.jpg'
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(clip),'-frames:v','1','-vf','scale=540:960',str(frame)],check=True,capture_output=True)
        evidence.append({'path':str(frame),'sha256':sha256_file(frame),'source_timestamp':t})
    source.update(path=str(clip),sha256=sha256_file(clip),creator_watermarks_preprocessed=True,
        creator_blur_original_path=original_path,creator_blur_regions_px=[[284,488,288,180]],
        pending_visual_review=True,editing_eligible=False)
    for key in ('functional_review','presentation_review'):
        source['previous_'+key]=copy.deepcopy(source.get(key))
        if source.get(key):source[key].update(source_sha256=source['sha256'],evidence_frames=evidence)
    if source.get('presentation_review'):source['presentation_review']['scope']=review_scope(source)
    for shot in plan['shots']:
        if shot['source_id']==source['id']:shot.update(path=str(clip),sha256=source['sha256'])
    selected=plan['cover_spec'].get('source')
    if selected and selected['source_id']==source['id']:selected['source_sha256']=source['sha256']
    _atomic_json(out/'proposed-plan.json',plan)

if __name__=='__main__':main()
