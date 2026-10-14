"""Versioned cart action replacement from a fully received browser source."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from PIL import Image, ImageDraw
from hotpost.config import load_settings
from hotpost.source_quality import sha256_file
from hotpost.source_finder import probe_video
from hotpost.source_presentation import POLICY, review_scope
from hotpost.studio import Studio
from hotpost.studio_workflow import init_run, snapshot
from tools import build_tiktok_rework as build
from tools.rework_tiktok_batch import save

CODE = 'DeTJ6HbKCdF'
ROOT = Path('data/daily-cart-youtube-20261011-v5')
OLD = Path('data/daily-cart-actions-20261011')
RAWROOT = Path('data/daily-rework-20261011') / CODE / 'youtube-observed-0PRF6gRJkbA'
EDIT = 'daily-cart-youtube-actions-20261011-v5'
PREVIOUS_EDIT = 'daily-cart-actions-20261011-v4'
SHARE_PORT = 8806
SHARE_RECEIPT = 'daily-cart-youtube-20261011-v5-three-share.json'


def configure():
    build.root = lambda code: (ROOT / code / 'final').resolve()
    original = build.boundary
    build.boundary = lambda c, action, **kw:original(c, action, quality_revision=EDIT, **kw)
    bins = next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']


def motion():
    receipt = json.loads((RAWROOT/'source-reception.json').read_text('utf-8'))
    assert receipt['browser_reception']['decoded_video_duration'] >= 33
    raw = Path(receipt['path'])
    for name, start, step in [('leg-fold', 21.0, .2), ('loaded-pull', 25.1, .1)]:
        folder = RAWROOT / ('dense-' + name); folder.mkdir(exist_ok=True)
        sheet = Image.new('RGB', (960, 1808), '#222'); draw=ImageDraw.Draw(sheet)
        frames=[]
        for i in range(16):
            timestamp=start+i*step; frame=folder/f'{timestamp:.2f}.jpg'
            subprocess.run(['ffmpeg','-v','error','-y','-ss',str(timestamp),'-i',str(raw),
                '-frames:v','1','-vf','scale=240:426',str(frame)],check=True,capture_output=True)
            with Image.open(frame) as im:sheet.paste(im,(i%4*240,i//4*452))
            draw.text((i%4*240+3,i//4*452+429),f'{timestamp:.2f}s',fill='white')
            frames.append({'path':str(frame.resolve()),'timestamp':timestamp,'sha256':sha256_file(frame)})
        sheet.save(folder/'contact.jpg',quality=94)
        save(folder/'sampling.json',{'source_sha256':receipt['sha256'],'frames':frames,'actual_review_pending':True})


def clips():
    receipt=json.loads((RAWROOT/'source-reception.json').read_text('utf-8'))
    raw=Path(receipt['path']); final=build.root(CODE); final.mkdir(parents=True,exist_ok=True)
    definitions=[('leg-fold',21.35,23.80),('loaded-pull',25.70,26.51)]
    observations={'leg-fold':'뒤집어 놓은 테이블의 양쪽 다리를 안쪽으로 접어 수납하는 동작',
                  'loaded-pull':'접힌 테이블 카트 위에 상자를 싣고 손잡이로 앞으로 끌어 이동하는 동작'}
    sources=[]; sheet=Image.new('RGB',(960,904),'#222');draw=ImageDraw.Draw(sheet)
    for j,(name,start,end) in enumerate(definitions):
        target=final/'clips'/(name+'-v3.mp4');target.parent.mkdir(exist_ok=True)
        if target.exists():raise RuntimeError('Existing clip version must be preserved')
        vf='scale=720:1280,setsar=1,fps=30,split[base][txt];[txt]crop=660:86:30:366,boxblur=12:2[blur];[base][blur]overlay=30:366'
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(start),'-t',str(end-start),'-i',str(raw),
            '-an','-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','18',str(target)],check=True)
        meta=probe_video(target);frames=[]
        for k,ratio in enumerate((.03,.35,.65,.97)):
            timestamp=(meta['duration']-.02)*ratio;frame=target.with_name(name+f'-{k}.jpg')
            subprocess.run(['ffmpeg','-v','error','-y','-ss',str(timestamp),'-i',str(target),'-frames:v','1',str(frame)],check=True,capture_output=True)
            frames.append({'path':str(frame.resolve()),'timestamp':timestamp,'sha256':sha256_file(frame)})
            with Image.open(frame) as im:
                im.thumbnail((240,426));sheet.paste(im,(k*240,j*452+24))
            draw.text((k*240+3,j*452+3),f'{name} {timestamp:.2f}s',fill='white')
        sources.append({'id':'cart-youtube-v5-'+name,'name':name,'path':str(target.resolve()),'sha256':sha256_file(target),
            'video_meta':meta,'original_path':str(raw.resolve()),'original_sha256':receipt['sha256'],
            'original_interval':{'start':start,'end':end},'url':receipt['url'],'provider':'youtube',
            'rights':receipt['rights'],'source_role':'core','evidence_frames':frames,
            'proposed_observation':observations[name],'pending_visual_review':True,
            'caption_softening_band':[30/720,366/1280,660/720,86/1280], 'watermark_masks':[],
            'same_filming_origin_possible':True})
    save(final/'proposed-sources.json',sources);sheet.save(final/'clip-review.jpg',quality=94)


def prepare():
    final=build.root(CODE)
    review=json.loads((final/'clips-reviewed.json').read_text('utf-8'))
    assert review['leg_folding_witnessed'] and review['loaded_pulling_witnessed']
    sources=json.loads((final/'proposed-sources.json').read_text('utf-8'))
    limits=['같은 기능의 테이블 카트 시연. 정확한 SKU·목적지가 차인지·별도 촬영자인지는 미확인.']
    for s in sources:
        s.update(pending_visual_review=False,editing_eligible=True,blur_required=False,
            source_quality='reviewed-portrait-action',presentation_review_required=False,relevance_review_required=False)
        s['functional_review']={'reviewed':True,'source_sha256':s['sha256'],'same_core_function':True,
            'context_usable':True,'observed_actions':[s['proposed_observation']], 'context_usage_limits':limits,
            'evidence_frames':[f['path'] for f in s['evidence_frames']],'reviewer':'codex_session_visual_review'}
        s['visual_review']={'reviewer':'codex_session_visual_review','reviewed_at':time.time(),
            'scope':'dense decoded original plus four derivative frames','observation':s['proposed_observation'],
            'evidence_frames':s['evidence_frames']}
        s['presentation_review']={'policy':POLICY,'reviewed':True,'source_sha256':s['sha256'],
            'scope':review_scope(s),'usable':True,'quality_usable':True,'action_preserved':True,
            'observations':[s['proposed_observation']],'evidence_frames':s['evidence_frames'],'reviewer':'codex_session_visual_review'}
    save(final/'approved-sources.json',sources)
    p=json.loads((OLD/CODE/'final/timeline.json').read_text('utf-8'))
    for s in sources:
        p['sources'].append(s)
        p['shots'].append({'id':'shot-youtube-v5-'+s['name'],'source_id':s['id'],'path':s['path'],'sha256':s['sha256'],
            'start':0,'end':s['video_meta']['duration'],'frames':[f['path'] for f in s['evidence_frames']],
            'observation':s['proposed_observation'],'source_role':'core','context_usage_limits':limits,
            'evidence_status':'dense-decoded-frame-action-review'})
    for first,last,name,offset in [(4,5,'leg-fold',0),(7,7,'loaded-pull',0)]:
        shot=next(s for s in p['shots'] if s['id']=='shot-youtube-v5-'+name)
        cursor=offset
        for beat in p['beats'][first-1:last]:
            length=beat['end']-beat['start']
            beat.update(options=[{'shot_id':shot['id'],'relation':'direct','reason':shot['observation'],'reviewed':True}],
                selected_shot_id=shot['id'],source_start=cursor,source_end=cursor+length,
                relation='direct',reason=shot['observation'],needs_review=False)
            cursor+=length
        assert cursor <= shot['end']+.01
    p['visual_claims'].update(leg_folding_moment_witnessed=True,loaded_pulling_witnessed=True,
        walking_to_car_witnessed=False,new_raw_downloads=1,independent_filming_origin_unverified=True)
    for key in ('rendered_clips','cover_path','sfx_path','output_dir'):p.pop(key,None)
    save(final/'prepared-plan.json',p)
    for name in ('script.json','voice.json'):shutil.copy2(OLD/CODE/'final'/name,final/name)
    studio=Studio(load_settings(),workers=False)
    save(final/'baseline-state.json',studio.store.get('work-385b11cdea3040cb'))
    save(final/'revision-origin.json',{'previous_video':str((OLD/CODE/'final/preview.mp4').resolve()),
        'changed_beats':[4,5,7],'tts_regenerated':False,'cover_preserved':True,
        'new_received_file':str((RAWROOT/'source-reception.json').resolve()),'filming_diversity_not_claimed':True})


def attach():
    final=build.root(CODE);qa=json.loads((final/'verification.json').read_text('utf-8'))
    assert not qa['visual_review_pending']
    result=json.loads((final/'render-result.json').read_text('utf-8'));plan=json.loads((final/'timeline.json').read_text('utf-8'))
    studio=Studio(load_settings(),workers=False);current=studio.store.get('work-385b11cdea3040cb')
    if any(e['id']==EDIT for e in current['edits']):return
    old=next(e for e in current['edits'] if e['id']==current['edit_id'])
    assert old['id']==PREVIOUS_EDIT
    save(final/'state-before-attachment.json',current)
    edit={k:v for k,v in result.items() if k!='status'}
    edit.update(id=EDIT,script_id=old['script_id'],voice_id=old['voice_id'],status='completed',created=time.time(),
        export_path=result['preview_path'],export_verified=True,exported_at=time.time(),export_kind='web_render',
        registration_deferred=True,source_diversity=qa['metrics'],previous_edit_id=old['id'],
        revision_scope='actual leg folding and loaded pulling, decoded-complete browser source')
    def change(state,db):
        assert state['edit_id']==old['id']
        state['edits'].append(edit)
        state['sources'].extend(copy.deepcopy(s) for s in plan['sources'] if not any(x['id']==s['id'] for x in state['sources']))
        state.update(edit_id=EDIT,status='completed',progress=100,message='실제 다리 접기와 적재 후 끌기 장면으로 보완',error='')
        state.setdefault('automation',{}).update(active=False,stage='completed')
        state.pop('run_id',None);run=init_run(state)
        used={b['selected_shot_id'] for b in plan['beats']};ids={s['source_id'] for s in plan['shots'] if s['id'] in used}
        sources=[copy.deepcopy(s) for s in plan['sources'] if s['id'] in ids]
        run['inputs']['source_ids']=[s['id'] for s in sources];snapshot(state);run['artifacts']['sources']=sources
        run.update(status='completed',completed=time.time(),revision_origin=EDIT)
        state['latest_completed_run_id']=run['id']
        studio.store.event(db,state['id'],'cart_youtube_actions_revised',{'edit_id':EDIT,'previous_edit_id':old['id']})
    saved=studio.store.change(current['id'],change)
    assert all(next(x for x in saved['runs'] if x['id']==old_run['id'])==old_run for old_run in current['runs'])
    print('New version attached, every prior run preserved:',saved['run_id'],flush=True)


def share():
    from tools import share_daily_rework as public
    codes=('DeTaESASnr_',CODE,'DeSvpmAsWgZ')
    for code in codes:
        origin=OLD if code==CODE else Path('data/daily-rework-20261011')
        rev='quality-v4.json' if code=='DeSvpmAsWgZ' else 'quality-v3.json'
        target=ROOT/code/'writing';target.mkdir(parents=True,exist_ok=True)
        # Cart writing lived in the daily root; prior share copied it too.
        shutil.copy2(origin/code/'writing'/rev,target/rev)
        if code!=CODE:
            final=ROOT/code/'final';final.mkdir(exist_ok=True)
            for name in ('cover.png','verification.json','timeline.json'):shutil.copy2(origin/code/'final'/name,final/name)
    public.ROOT=ROOT
    public.main(codes=codes,port=SHARE_PORT,receipt_name=SHARE_RECEIPT,
        writing_revisions={'DeSvpmAsWgZ':'quality-v4.json'})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['motion','clips','prepare','render','attach','share'])
    args=parser.parse_args();configure()
    if args.phase=='render':build.render(CODE)
    else:globals()[args.phase]()
