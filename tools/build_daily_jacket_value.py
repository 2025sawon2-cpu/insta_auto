"""New approved value-oriented script/voice/render, preserving all prior versions."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
import math
from functools import lru_cache

from hotpost.config import load_settings
from hotpost.source_quality import sha256_file
from hotpost.studio import Studio
from hotpost.voicebench_adapter import VoiceBenchAdapter
from tools import build_tiktok_rework as build
from tools import revise_cart_youtube_actions as environment
from tools import revise_jacket_cover_glyph as cover_version
from tools.rework_tiktok_batch import save

CODE = 'DeSvpmAsWgZ'
ROOT = Path('data/daily-jacket-value-20261011-v6')
OLD = Path('data/daily-rework-20261011')
EDIT = 'daily-jacket-value-20261011-v6'


def configure():
    environment.ROOT=ROOT;environment.EDIT=EDIT;environment.configure()


def prepare():
    quality=json.loads((OLD/CODE/'writing/quality-v6.json').read_text('utf-8'))
    assert not quality['human_review_pending']
    selected=next(s for s in quality['scripts'] if s['number']==1)
    digest=hashlib.sha256(selected['text'].encode()).hexdigest()
    final=build.root(CODE);final.mkdir(parents=True,exist_ok=True)
    script={**selected,'id':'daily-jacket-value-script-'+digest[:12], 'sha256':digest,
        'status':'completed','created':time.time(),'writing_contract':quality['writing_contract']}
    if (final/'script.json').exists():
        assert json.loads((final/'script.json').read_text('utf-8'))['sha256']==digest
    else:
        save(final/'script.json',script)
        (final/'words.txt').write_text(script['text'],'utf-8')
    sources=json.loads((OLD/CODE/'final/approved-sources.json').read_text('utf-8'))
    for source in sources:
        assert sha256_file(Path(source['path']))==source['sha256']
        for frame in source['evidence_frames']:
            assert sha256_file(Path(frame['path']))==frame['sha256']
    save(final/'proposed-sources.json',sources)
    save(final/'clips-reviewed.json',{'previous_review':str(OLD/CODE/'final/clips-reviewed.json'),
        'scope':'Reuse byte-identical bounded reviewed portrait clips; new timeline review required',
        'source_ids':[s['id'] for s in sources]})
    if not (final/'baseline-state.json').exists():
        save(final/'baseline-state.json',Studio(load_settings(),workers=False).store.get(cover_version.WORK))
    voice_file=final/'voice.json'
    if voice_file.exists():
        assert json.loads(voice_file.read_text('utf-8'))['script_sha256']==digest
        return
    submission=final/'voice-submission.json'
    request=json.loads(submission.read_text('utf-8')).get('request_id') if submission.exists() else None
    result=VoiceBenchAdapter(load_settings()).synthesize(script['text'],final/'narration.wav',
        progress=lambda m,n:print(CODE,m,n,flush=True),request_id=request,
        on_submitted=lambda i:save(submission,{'request_id':i,'script_sha256':digest}),
        generation_key='daily-jacket-value-'+CODE+'-'+digest,require_personal_clone=True)
    save(voice_file,{**result,'id':'daily-jacket-value-voice-'+digest[:12],
        'path':str(final/'narration.wav'),'sha256':sha256_file(final/'narration.wav'),
        'duration':result['audio']['duration'],'script_id':script['id'],'script_sha256':digest,
        'created':time.time(),'status':'completed'})
    print('New personal voice saved',result['audio']['duration'],flush=True)


def select():
    """Fit whole cues into reviewed clips; price/story images remain context."""
    final=build.root(CODE)
    plan=json.loads((final/'prepared-plan.json').read_text('utf-8'))
    beats=plan['beats'];shots={s['id']:s for s in plan['shots']}
    assert len(beats)==21 and '키즈라인' in beats[16]['text']
    adults=['white-front','white-fit','white-detail','outside-front','outside-back','outside-walk']
    capacity=[math.floor(shots['shot-'+n]['end']*1000) for n in adults]
    lengths=[math.ceil((b['end']-b['start'])*1000-1e-6) for b in beats]
    assignment={}
    for i in (3,4,5):assignment[i]='white-detail';capacity[2]-=lengths[i]
    for i in (18,19,20):assignment[i]='white-front';capacity[0]-=lengths[i]
    for i in (16,17):assignment[i]='kid-front'
    assert sum(lengths[i] for i in (16,17))<=shots['shot-kid-front']['end']*1000
    pending=sorted((i for i in range(len(beats)) if i not in assignment),key=lambda i:-lengths[i])
    preferred=['outside-front','white-fit','outside-walk','outside-back','white-detail','white-front']
    @lru_cache(None)
    def fit(position,remaining):
        if position==len(pending):return ()
        i=pending[position];length=lengths[i]
        for name in preferred:
            k=adults.index(name)
            if remaining[k]<length:continue
            rest=list(remaining);rest[k]-=length
            solution=fit(position+1,tuple(rest))
            if solution is not None:return ((i,name),)+solution
        return None
    solution=fit(0,tuple(capacity))
    if solution is None:raise ValueError('Current reviewed source ranges cannot fit all whole cues without repetition')
    assignment.update(dict(solution))
    for i,beat in enumerate(beats):
        shot=shots['shot-'+assignment[i]]
        relation='direct' if i in (3,4,5) else 'context'
        reason=shot['observation']+' · 가격·개인 선택·가족 상황은 대본의 조건/연출이며 영상이 판매 조건이나 실제 경험을 입증하지 않음.'
        beat.update(selected_shot_id=shot['id'],options=[{'shot_id':shot['id'],'relation':relation,
            'reason':reason,'reviewed':True}],emphasis=0,needs_review=False)
    plan['footage_selection_policy']='diverse-sequential-v1'
    prior=json.loads((OLD/CODE/'final/timeline.json').read_text('utf-8'))
    # Same actually reviewed white-front highlight, now used in the adult CTA.
    plan['cover_spec']['source']=prior['cover_spec']['source']
    plan['cover_spec']['copy_review']={'reviewer':'codex_session_editorial_review',
        'source_review':'Previously inspected real white-body/black-shoulder frame; reused unchanged bounded source',
        'hook_review':'Product ownership and conditional price curiosity, not current sale verification'}
    save(final/'prepared-plan.json',plan)
    result=build.boundary(CODE,'cover-candidates',plan=plan)
    save(final/'selection-description.json',{'assignment':[(i+1,assignment[i]) for i in range(21)],
        'all_price_story_images_context':True,'no_source_quantity_in_writing':True,
        'cover_candidate_receipt':str(final/'cover-candidates-result.json')})
    print('Whole cues assigned within reviewed ranges, adult CTA and explicit conditional-price context',flush=True)


def attach():
    final=build.root(CODE);qa=json.loads((final/'verification.json').read_text('utf-8'))
    assert not qa['visual_review_pending']
    result=json.loads((final/'render-result.json').read_text('utf-8'))
    script=json.loads((final/'script.json').read_text('utf-8'))
    voice=json.loads((final/'voice.json').read_text('utf-8'))
    studio=Studio(load_settings(),workers=False)
    current=studio.store.get(cover_version.WORK)
    if any(e['id']==EDIT for e in current['edits']):
        print('Existing version retained; no duplicate run',flush=True);return
    baseline=json.loads((final/'baseline-state.json').read_text('utf-8'))
    assert current['edit_id']==baseline['edit_id']
    previous=current['edit_id']
    edit={k:v for k,v in result.items() if k!='status'}
    edit.update(id=EDIT,script_id=script['id'],voice_id=voice['id'],created=time.time(),status='completed',
        export_path=result['preview_path'],export_verified=True,export_kind='web_render',
        registration_deferred=True,source_diversity=qa['metrics'],previous_edit_id=previous,
        revision_scope='product value and family appeal restored, three variants retained')
    plan=json.loads(Path(result['plan_path']).read_text('utf-8'))
    def change(state,db):
        assert state['edit_id']==previous
        for name,item in [('scripts',script),('voices',voice),('edits',edit)]:
            if not any(x['id']==item['id'] for x in state[name]):state[name].append(item)
        state.update(script_id=script['id'],voice_id=voice['id'],edit_id=EDIT,status='completed',
            error='',progress=100,message='가격 조건·가족 제품 매력을 복원한 새 대본 보완본')
        state.setdefault('automation',{}).update(active=False,stage='completed')
        from hotpost.studio_workflow import init_run,snapshot
        import copy
        parent=state.pop('run_id',None);run=init_run(state)
        if parent:run['parent_id']=parent
        used={b['selected_shot_id'] for b in plan['beats']}
        ids={s['source_id'] for s in plan['shots'] if s['id'] in used}
        used_sources=[copy.deepcopy(s) for s in plan['sources'] if s['id'] in ids]
        run['inputs']['source_ids']=[s['id'] for s in used_sources]
        snapshot(state);run['artifacts']['sources']=used_sources
        run.update(status='completed',completed=time.time(),revision_origin=EDIT)
        state['latest_completed_run_id']=run['id']
        state['quality_revision_path']=str((OLD/CODE/'writing/quality-v6.json').resolve())
        studio.store.event(db,state['id'],'jacket_value_revision_added',{'edit_id':EDIT,'previous_edit_id':previous})
    saved=studio.store.change(current['id'],change)
    assert all(next(r for r in saved['runs'] if r['id']==prior['id'])==prior for prior in current['runs'])
    save(final/'attachment-verification.json',{'edit_id':EDIT,'run_id':saved['run_id'],'prior_runs_unchanged':True,
        'old_scripts_retained':all(x in saved['scripts'] for x in current['scripts']),
        'old_voices_retained':all(x in saved['voices'] for x in current['voices'])})
    print('New value version attached, all previous runs retained',saved['run_id'],flush=True)


def share():
    from tools import share_daily_rework as public
    codes=('DeTaESASnr_','DeTJ6HbKCdF',CODE)
    for code in codes:
        origin=Path('data/daily-cart-youtube-20261011-v6') if code=='DeTJ6HbKCdF' else OLD
        revision='quality-v6.json' if code==CODE else 'quality-v3.json'
        writing=ROOT/code/'writing';writing.mkdir(parents=True,exist_ok=True)
        shutil.copy2(origin/code/'writing'/revision,writing/revision)
        if code!=CODE:
            final=ROOT/code/'final';final.mkdir(exist_ok=True)
            for name in ('cover.png','verification.json','timeline.json'):
                shutil.copy2(origin/code/'final'/name,final/name)
    public.ROOT=ROOT;public.TITLES[CODE]='노스페이스 패딩 · 가격·가족 매력 보완'
    public.main(codes=codes,port=8809,receipt_name='daily-jacket-value-20261011-v6-three-share.json',
        writing_revisions={CODE:'quality-v6.json'})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['prepare','analyze','select','render','attach','share'])
    args=parser.parse_args();configure()
    if args.phase in ('analyze','render'):getattr(build,args.phase)(CODE)
    else:globals()[args.phase]()
