"""Exclude a late unrelated picnic cut, preserving every prior render/run."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
from PIL import Image, ImageDraw
from hotpost.config import load_settings
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file
from hotpost.source_presentation import review_scope
from hotpost.studio import Studio
from tools import revise_cart_youtube_actions as revision
from tools.rework_tiktok_batch import save

CODE=revision.CODE
OLD=Path('data/daily-cart-youtube-20261011-v5')
ROOT=Path('data/daily-cart-youtube-20261011-v6')


def configure():
    revision.ROOT=ROOT;revision.OLD=OLD
    revision.EDIT='daily-cart-youtube-actions-20261011-v6'
    revision.PREVIOUS_EDIT='daily-cart-youtube-actions-20261011-v5'
    revision.SHARE_PORT=8807
    revision.SHARE_RECEIPT='daily-cart-youtube-20261011-v6-three-share.json'
    revision.configure()


def clips():
    final=revision.build.root(CODE);final.mkdir(parents=True,exist_ok=True)
    p=json.loads((OLD/CODE/'final/timeline.json').read_text('utf-8'))
    base=next(s for s in p['sources'] if s['id']=='cart-action-v4-outdoor-use')
    raw=Path(base['original_path']);target=final/'clips/outdoor-cta-v6.mp4';target.parent.mkdir(exist_ok=True)
    if target.exists():raise RuntimeError('Existing source version must be preserved')
    vf='scale=720:1280,setsar=1,fps=30,split[base][txt];[txt]crop=690:140:14:946,boxblur=12:2[blur];[base][blur]overlay=14:946'
    subprocess.run(['ffmpeg','-v','error','-y','-ss','12.3','-t','2.84','-i',str(raw),'-an',
        '-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','18',str(target)],check=True)
    frames=[];sheet=Image.new('RGB',(960,452),'#222');draw=ImageDraw.Draw(sheet)
    for i,timestamp in enumerate((.03,1,2,2.8)):
        frame=final/'clips'/f'outdoor-cta-{i}.jpg'
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(timestamp),'-i',str(target),'-frames:v','1',str(frame)],check=True,capture_output=True)
        frames.append({'path':str(frame.resolve()),'timestamp':timestamp,'sha256':sha256_file(frame)})
        with Image.open(frame) as im:
            im.thumbnail((240,426));sheet.paste(im,(i*240,24))
        draw.text((i*240+3,3),f'{timestamp:.2f}s',fill='white')
    source=copy.deepcopy(base)
    source.update(id='cart-action-v6-outdoor-cta',name='outdoor-cta-v6',path=str(target.resolve()),
        sha256=sha256_file(target),video_meta=probe_video(target),original_interval={'start':12.3,'end':15.14},
        evidence_frames=frames,pending_visual_review=True,editing_eligible=False,
        proposed_observation='테이블 위에서 컵과 음식을 놓고 과일을 손질하는 장면. 마지막까지 같은 테이블 사용 상황이 이어짐.')
    save(final/'proposed-source.json',source);sheet.save(final/'clip-review.jpg',quality=94)


def prepare():
    final=revision.build.root(CODE)
    review=json.loads((final/'clip-reviewed.json').read_text('utf-8'));assert review['reviewed']
    s=json.loads((final/'proposed-source.json').read_text('utf-8'))
    s.update(pending_visual_review=False,editing_eligible=True)
    s['functional_review'].update(source_sha256=s['sha256'],observed_actions=[s['proposed_observation']],
        evidence_frames=[f['path'] for f in s['evidence_frames']])
    s['visual_review'].update(observation=s['proposed_observation'],evidence_frames=s['evidence_frames'])
    s['presentation_review'].update(source_sha256=s['sha256'],scope=review_scope(s),
        observations=[s['proposed_observation']],evidence_frames=s['evidence_frames'])
    p=json.loads((OLD/CODE/'final/timeline.json').read_text('utf-8'))
    p['sources'].append(s)
    shot={'id':'shot-v6-outdoor-cta','source_id':s['id'],'path':s['path'],'sha256':s['sha256'],
        'start':0,'end':s['video_meta']['duration'],'frames':[f['path'] for f in s['evidence_frames']],
        'observation':s['proposed_observation'],'source_role':'core',
        'context_usage_limits':s['functional_review']['context_usage_limits'],'evidence_status':'dense-decoded-frame-action-review'}
    p['shots'].append(shot);cursor=0
    for beat in p['beats'][16:19]:
        length=beat['end']-beat['start']
        beat.update(options=[{'shot_id':shot['id'],'relation':'context','reason':shot['observation'],'reviewed':True}],
            selected_shot_id=shot['id'],source_start=cursor,source_end=cursor+length,
            relation='context',reason=shot['observation'],needs_review=False)
        cursor+=length
    assert cursor<=shot['end']+.001
    for key in ('rendered_clips','cover_path','sfx_path','output_dir'):p.pop(key,None)
    p['visual_claims']['unrelated_last_scene_removed']=True
    save(final/'prepared-plan.json',p)
    for name in ('script.json','voice.json'):shutil.copy2(OLD/CODE/'final'/name,final/name)
    save(final/'baseline-state.json',Studio(load_settings(),workers=False).store.get('work-385b11cdea3040cb'))
    save(final/'revision-origin.json',{'previous_video':str((OLD/CODE/'final/preview.mp4').resolve()),
        'changed_beats':[17,18,19],'tts_regenerated':False,'cover_preserved':True,
        'reason':'Actual browser playback exposed unrelated last picnic scene missed by uniform sampling',
        'source_raw_interval':[12.3,15.14],'new_downloads':0})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['clips','prepare','render','attach','share'])
    args=parser.parse_args();configure()
    if args.phase=='render':revision.build.render(CODE)
    elif args.phase in ('attach','share'):getattr(revision,args.phase)()
    else:globals()[args.phase]()
