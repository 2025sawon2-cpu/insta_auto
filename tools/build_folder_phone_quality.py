"""Versioned USB-use correction with separate personal TTS and JSON rendering."""
import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from PIL import Image, ImageDraw
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json as save
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file
from hotpost.source_presentation import POLICY, review_scope
from hotpost.source_policy import current_policy
from hotpost.source_coverage import coverage_goal
from hotpost.studio import Studio
from hotpost.studio_workflow import init_run, snapshot
from hotpost.voicebench_adapter import VoiceBenchAdapter
from tools import build_tiktok_rework as build
from tools import revise_cart_youtube_actions as environment

CODE='DeSoiZvyyqj'
ROOT=Path('data/folder-phone-review-20261011-v8').resolve()
OLD=Path('data/folder-transfer-quality-20261011-v7').resolve()
EDIT='folder-phone-quality-20261011-v8'
PREVIOUS='folder-transfer-quality-20261011-v7'
WORK='work-df891c7f6d48490e'


def read(path):return json.loads(Path(path).read_text('utf-8'))


def configure():
    environment.ROOT,environment.EDIT=ROOT,EDIT;environment.configure()


def clips():
    final=build.root(CODE);final.mkdir(parents=True,exist_ok=True)
    receipt=read(ROOT/CODE/'source-reception.json');raw=Path(receipt['path'])
    assert receipt['browser_reception']['full_decode_passed'] and sha256_file(raw)==receipt['sha256']
    oldraw=Path('data/daily-rework-20261011/DeSoiZvyyqj/videos/7636068417656589600.mp4').resolve()
    oldreview=read(oldraw.parent.parent/'review/7636068417656589600/visual-review.json')
    assert sha256_file(oldraw)==oldreview['source_sha256']
    definitions=[('small-held',raw,receipt['url'],1.8,5.3,'작은 노란 폴더 케이스를 손에 들고 돌려 보여줌',False),
        ('two-folders',raw,receipt['url'],12.65,16.65,'작은 노란 폴더와 큰 파란 폴더의 실물 외형을 함께 보여줌',False),
        ('usb-plug',raw,receipt['url'],6.17,8.07,'폴더 케이스 USB-C 포트에 실제 케이블을 꽂고 연결부를 보여줌',True),
        ('phone-usb',oldraw,'https://www.tiktok.com/@nunoagonia/video/7636068417656589600',8.12,9.98,
         '노란 폴더 케이스와 휴대폰이 USB-C 케이블로 연결된 모습. 폰 뒤 부착이 아님',True)]
    rows=[];sheet=Image.new('RGB',(960,1808),'#222');draw=ImageDraw.Draw(sheet)
    for j,(name,raw,url,start,end,observation,core) in enumerate(definitions):
        target=final/'clips'/(name+'-v1.mp4');target.parent.mkdir(exist_ok=True)
        if target.exists():raise RuntimeError('Existing derivative preserved; use a new revision.')
        vf='scale=720:1280,setsar=1,fps=30';bands=[]
        if name=='phone-usb':
            bands=[[96,838,530,110]]
            vf+=",split[base][txt];[txt]crop=530:110:96:838,boxblur=12:2:6:2[blur];[base][blur]overlay=96:838:enable='lt(t,0.52)+gte(t,0.97)'"
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(start),'-t',str(end-start),'-i',str(raw),
            '-an','-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','18',str(target)],check=True,capture_output=True)
        subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(target),'-f','null','-'],check=True,capture_output=True)
        meta=probe_video(target);frames=[]
        for k,frac in enumerate((.05,.35,.65,.95)):
            t=(meta['duration']-.05)*frac;frame=target.with_name(target.stem+f'-{k}.jpg')
            subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(target),'-frames:v','1',str(frame)],check=True,capture_output=True)
            frames.append({'path':str(frame),'timestamp':t,'sha256':sha256_file(frame)})
            im=Image.open(frame);im.thumbnail((240,426));sheet.paste(im,(k*240,j*452+25));draw.text((k*240,j*452+2),f'{name} {t:.2f}s',fill='white')
        rows.append({'id':EDIT+'-'+name,'name':name,'path':str(target),'sha256':sha256_file(target),'video_meta':meta,
            'original_path':str(raw),'original_sha256':sha256_file(raw),'original_interval':{'start':start,'end':end},
            'url':url,'provider':'tiktok','rights':'unknown-check-before-reuse','source_role':'core' if core else 'context',
            'proposed_observation':observation,'same_core_function_proposed':core,'evidence_frames':frames,
            'preprocessed_blur_regions_px':bands,'pending_visual_review':True,'editing_eligible':False})
    save(final/'proposed-sources.json',rows);sheet.save(final/'clip-review.jpg',quality=95)
    print('Four actual-use derivatives saved for review.',flush=True)


def voice():
    final=build.root(CODE);final.mkdir(parents=True,exist_ok=True)
    quality=read(ROOT/CODE/'writing/quality-v9.json');editorial=read(ROOT/CODE/'writing/editorial-review-v9.json')
    assert editorial['actual_text_review'] and editorial['writing_sha256']==sha256_file(ROOT/CODE/'writing/quality-v9.json')
    selected=next(s for s in quality['scripts'] if s['number']==2);digest=hashlib.sha256(selected['text'].encode()).hexdigest()
    script={**selected,'id':EDIT+'-script-'+digest[:12],'sha256':digest,'status':'completed',
            'created':time.time(),'human_review_pending':False,'writing_contract':quality['writing_contract']}
    if (final/'script.json').exists():assert read(final/'script.json')['sha256']==digest
    else:save(final/'script.json',script)
    if (final/'voice.json').exists():
        assert read(final/'voice.json')['script_sha256']==digest;print('Matching personal voice retained.',flush=True);return
    submission=final/'voice-submission.json';request=read(submission).get('request_id') if submission.exists() else None
    result=VoiceBenchAdapter(load_settings()).synthesize(script['text'],final/'narration.wav',
        require_personal_clone=True,request_id=request,generation_key=EDIT+'-'+digest,
        on_submitted=lambda rid:save(submission,{'request_id':rid,'script_sha256':digest}),
        progress=lambda m,n:print(m,n,flush=True))
    save(final/'voice.json',{**result,'id':EDIT+'-voice-'+digest[:12],'path':str(final/'narration.wav'),
        'sha256':sha256_file(final/'narration.wav'),'script_id':script['id'],'script_sha256':digest,
        'duration':result['audio']['duration'],'status':'completed','created':time.time()})
    print('New personal voice saved',result['audio']['duration'],flush=True)


def prepare():
    final=build.root(CODE)
    if (final/'prepared-plan.json').exists():raise RuntimeError('Existing plan preserved.')
    approval=read(final/'clips-reviewed.json');extra=read(final/'proposed-sources.json')
    assert approval['actual_visual_review'] and approval['source_hashes']=={s['id']:s['sha256'] for s in extra}
    old=read(OLD/CODE/'final/timeline.json');sources=copy.deepcopy(old['sources'])
    for s in sources:
        assert sha256_file(Path(s['path']))==s['sha256']
    for s in extra:
        s['reviewed_intervals']=approval['usable_intervals'][s['id']]
        s['mask_review']={'source_sha256':s['sha256'],'reviewed':True,
            'intervals':[{**span,'coverage_confirmed':True,'subject_visible':True,
                'evidence_frames':[f['path'] for f in s['evidence_frames']]}
                for span in s['reviewed_intervals']],
            'reviewer':'codex_session_actual_visual_review',
            'note':'Actual derivative frames reviewed; existing local caption softening retained.'}
        limits=['관찰한 폴더 외형·USB 연결만 사용. 같은 SKU·기본 자석 부착·용량·속도·자동 백업 보장 없음.',
                '사진·영상 저장 기능은 원작의 일반 기능이며 이 화면만으로 특정 사진 복사를 검증했다고 주장하지 않음.']
        s.update(pending_visual_review=False,editing_eligible=True,source_quality='reviewed-portrait',blur_required=False,
                 watermark_masks=[],presentation_review_required=False,relevance_review_required=False)
        s['functional_review']={'reviewed':True,'source_sha256':s['sha256'],'same_core_function':s['same_core_function_proposed'],
            'context_usable':True,'context_usage_limits':limits,'observed_actions':[s['proposed_observation']],
            'evidence_frames':[f['path'] for f in s['evidence_frames']],'reviewer':'codex_session_actual_visual_review'}
        s['presentation_review']={'policy':POLICY,'reviewed':True,'source_sha256':s['sha256'],'scope':review_scope(s),
            'usable':True,'quality_usable':True,'action_preserved':True,'observations':[s['proposed_observation']],
            'evidence_frames':s['evidence_frames'],'reviewer':'codex_session_actual_visual_review'}
        sources.append(s)
    script,voice=read(final/'script.json'),read(final/'voice.json')
    plan=build.boundary(CODE,'analyze',sources=sources,script=script,voice=voice,thumbnail_lines=script['thumbnail_lines'])['plan']
    plan['shots']=copy.deepcopy(old['shots'])
    for s in extra:
        plan['shots'].append({'id':'shot-new-'+s['name'],'source_id':s['id'],'path':s['path'],'sha256':s['sha256'],
            'start':s['reviewed_intervals'][0]['source_start'],'end':s['reviewed_intervals'][0]['source_end'],'frames':[f['path'] for f in s['evidence_frames']],
            'observation':s['proposed_observation'],'source_role':s['source_role'],
            'context_usage_limits':s['functional_review']['context_usage_limits'],'evidence_status':'actual-portrait-and-action-review'})
    plan['cover_spec']=copy.deepcopy(old['cover_spec']);plan['cover_spec'].pop('layout',None);plan['cover_spec'].pop('background_path',None)
    plan['cover_spec']['lines']=script['thumbnail_lines'];plan['cover_font_style']=copy.deepcopy(old['cover_font_style'])
    plan['quality_draft']=True
    goal=coverage_goal(sources,{'voices':[voice],'voice_id':voice['id'],'script_id':script['id']},current_policy(load_settings()))
    plan['source_coverage_complete']=goal['duration_ready'] and goal['core_ready']
    save(final/'source-coverage.json',{'policy':current_policy(load_settings()),'goal':goal,
        'exact_sku_not_a_hard_gate':True,'phone_photo_copy_not_directly_verified':True,'mounting_claim_removed':True})
    save(final/'prepared-plan.json',plan);save(final/'all-approved-sources.json',sources)
    save(final/'baseline-state.json',Studio(load_settings(),workers=False).store.get(WORK))
    print(json.dumps([(i+1,b['text'],round(b['end']-b['start'],3)) for i,b in enumerate(plan['beats'])],ensure_ascii=False),flush=True)


def select():
    final=build.root(CODE);plan=read(final/'prepared-plan.json');selection=read(final/'selection-input.json')
    assert len(selection)==len(plan['beats']);shots={s['id']:s for s in plan['shots']};used={}
    for i,name in enumerate(selection):
        shot=shots[name];beat=plan['beats'][i];start=used.get(name,shot['start'])
        length=beat['end']-beat['start'];assert start+length<=shot['end']+.001,(i+1,name,length,start,shot['end'])
        beat.update(selected_shot_id=name,source_start=start,relation='direct' if shot['source_role']=='core' else 'context',
            reason=shot['observation'],options=[{'shot_id':name,'relation':'direct' if shot['source_role']=='core' else 'context',
                                               'reason':shot['observation'],'reviewed':True}],needs_review=False)
        used[name]=start+length
    save(final/'prepared-plan.json',plan);print('All cues fitted into reviewed non-repeated intervals.',flush=True)


def attach():
    final=build.root(CODE);qa=read(final/'verification.json');assert qa['actual_visual_review'] and not qa['visual_review_pending']
    studio=Studio(load_settings(),workers=False);current=studio.store.get(WORK)
    if any(e['id']==EDIT for e in current['edits']):return
    assert current['edit_id']==PREVIOUS
    result,plan=read(final/'render-result.json'),read(final/'timeline.json');script,voice=read(final/'script.json'),read(final/'voice.json')
    edit={k:v for k,v in result.items() if k!='status'}
    edit.update(id=EDIT,script_id=script['id'],voice_id=voice['id'],status='completed',created=time.time(),
        export_path=result['preview_path'],export_verified=True,export_kind='web_render',registration_deferred=True,
        source_diversity=qa['metrics'],previous_edit_id=PREVIOUS,review_draft=True,
        source_coverage_complete=plan['source_coverage_complete'])
    def change(state,db):
        assert state['edit_id']==PREVIOUS
        for name,item in [('scripts',script),('voices',voice),('edits',edit)]:
            if not any(x['id']==item['id'] for x in state[name]):state[name].append(item)
        state['sources'].extend(copy.deepcopy(s) for s in plan['sources'] if not any(x['id']==s['id'] for x in state['sources']))
        state.update(script_id=script['id'],voice_id=voice['id'],edit_id=EDIT,status='draft_review',progress=100,error='',
                     message='부착 기능 혼용을 USB 사용으로 정정하고 실제 연결 장면을 보완한 검토본')
        state.setdefault('automation',{}).update(active=False)
        parent=state.pop('run_id',None);run=init_run(state)
        if parent:run['parent_id']=parent
        used={b['selected_shot_id'] for b in plan['beats']};ids={s['source_id'] for s in plan['shots'] if s['id'] in used}
        chosen=[copy.deepcopy(s) for s in plan['sources'] if s['id'] in ids]
        run['inputs']['source_ids']=[s['id'] for s in chosen];snapshot(state);run['artifacts']['sources']=chosen
        run.update(status='review',quality_draft=True,source_coverage_complete=plan['source_coverage_complete'])
        state['quality_revision_path']=str(ROOT/CODE/'writing/quality-v9.json')
        studio.store.event(db,WORK,'folder_usb_product_correction',{'edit_id':EDIT,'previous_edit_id':PREVIOUS})
    saved=studio.store.change(WORK,change)
    assert all(next(r for r in saved['runs'] if r['id']==p['id'])==p for p in current['runs'])
    save(final/'attachment.json',{'task_id':WORK,'edit_id':EDIT,'run_id':saved['run_id'],'all_prior_runs_preserved':True,
        'new_script_id':script['id'],'new_voice_id':voice['id'],'source_coverage_complete':plan['source_coverage_complete']})
    print('Corrected script/new voice/render attached; all earlier runs preserved.',flush=True)


def share():
    from tools import share_daily_rework as public
    public.ROOT=ROOT;public.TITLES[CODE]='실물 폴더 저장 케이스 · USB 사용 설명 정정'
    public.main(codes=(CODE,),port=8816,receipt_name=EDIT+'-share.json',
                writing_revisions={CODE:'quality-v9.json'},review_codes=(CODE,))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['clips','voice','prepare','select','render','attach','share'])
    args=parser.parse_args();configure()
    if args.phase=='render':
        if (build.root(CODE)/'render-result.json').exists():raise RuntimeError('Existing render preserved.')
        build.render(CODE)
    else:globals()[args.phase]()
