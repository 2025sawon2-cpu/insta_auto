"""Fresh whole-script voice and semantic edit from an expanded reviewed pool."""
import argparse,copy,hashlib,json,subprocess,time
from pathlib import Path
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json
from hotpost.voicebench_adapter import VoiceBenchAdapter
from hotpost.source_quality import sha256_file,editing_ready
from hotpost.studio import Studio
from hotpost.studio_ai import describe_shots,restrict_context_shots
from hotpost.local_compute import release_idle_voice

ROOT=Path('data/user-feedback-revisions-20261011').resolve()
CODES=('DeJ7hD6zsnR','DeSvpmAsWgZ')

def boundary(code,action,**payload):
    out=ROOT/code/'final';out.mkdir(parents=True,exist_ok=True)
    req=out/(action+'-request.json');res=out/(action+'-result.json')
    _atomic_json(req,{'action':action,'output_dir':str(out),**payload})
    settings=load_settings()
    with (out/(action+'.log')).open('a',encoding='utf-8') as log:
        subprocess.run([str(settings.auto_capcut_python),'-X','utf8','-m','auto_capcut.studio_runner',
            '--request',str(req),'--result',str(res)],cwd=settings.auto_capcut_root,stdout=log,stderr=log,check=True)
    value=json.loads(res.read_text('utf-8'));assert value['status']=='completed';return value

def prepare(code):
    settings=load_settings();final=ROOT/code/'final';final.mkdir(parents=True,exist_ok=True)
    quality=json.loads((ROOT/code/'writing/quality.json').read_text('utf-8'))
    # A ownership for video 3; B opportunity-cost for video 7: concrete conflict.
    selected=quality['scripts'][0 if code==CODES[0] else 1]
    text=selected['text'];digest=hashlib.sha256(text.encode()).hexdigest()
    script={**selected,'id':'feedback-script-'+digest[:12],'sha256':digest,
        'writing_contract':quality['writing_contract'],'status':'completed','created':time.time()}
    _atomic_json(final/'script.json',script)
    vf=final/'voice.json'
    if not vf.exists():
        submit=final/'voice-submission.json'
        request=json.loads(submit.read_text('utf-8'))['request_id'] if submit.exists() else None
        result=VoiceBenchAdapter(settings).synthesize(text,final/'narration.wav',
            request_id=request,on_submitted=lambda i:_atomic_json(submit,{'request_id':i}),
            generation_key='feedback-20261011-'+code+'-'+digest,require_personal_clone=True,
            progress=lambda m,n:print(code,m,n,flush=True))
        assert result['speech_plan']['segment_count']==1,'Whole-script generation required'
        _atomic_json(vf,{**result,'id':'feedback-voice-'+digest[:12],'path':str(final/'narration.wav'),
            'sha256':sha256_file(final/'narration.wav'),'duration':result['audio']['duration'],
            'script_id':script['id'],'script_sha256':digest,'created':time.time(),'status':'completed'})
    release_idle_voice(settings,best_effort=True)
    pool=[]
    for other in CODES:
        baseline=json.loads(Path('data/user-feedback-20261011-v1',other+'-baseline.json').read_text('utf-8'))
        pool.extend(copy.deepcopy(baseline['plan']['sources']))
        state=Studio(settings,workers=False).store.get(baseline['task_id'])
        pool.extend(copy.deepcopy(s) for s in state['sources'] if editing_ready(s))
    unique={}
    for s in pool:
        if s['sha256'] not in unique:unique[s['sha256']]=s
    sources=list(unique.values());_atomic_json(final/'source-pool.json',sources)
    if (final/'prepared-plan.json').exists():return
    voice=json.loads(vf.read_text('utf-8'))
    plan=boundary(code,'analyze',sources=sources,script=script,voice=voice)['plan']
    plan['cover_spec'].update(lines=script['thumbnail_lines'],copy_origin='new_contract_bound_feedback_variant')
    plan['footage_selection_policy']='diverse-sequential-v1';restrict_context_shots(plan,sources)
    by_id={s['id']:s for s in sources}
    for shot in plan['shots']:
        s=by_id[shot['source_id']];shot['parent_original_sha256']=s.get('original_sha256') or s['sha256']
    feedback=[{'kind':'repetition','reason':'Previous video used only 3 parent originals and concentrated on white front/detail. Use distinct observed views from this expanded pool. White/black-specific narration needs matching footage only on that beat; ordinary brand/family context permits reviewed other jackets.'}]
    observations,choices=describe_shots(settings,plan['shots'],plan['beats'],review_feedback=feedback)
    for shot in plan['shots']:shot.update(observations.get(shot['id'],{}))
    for beat in plan['beats']:
        choice=choices.get(beat['id'],{})
        if choice.get('analysis_status')=='opposite_only':raise ValueError('Opposite-only scene')
        if choice.get('options'):beat['options']=choice['options'];beat.pop('selected_shot_id',None)
    restrict_context_shots(plan,sources);_atomic_json(final/'prepared-plan.json',plan)
    _atomic_json(final/'source-selection-evidence.json',{'observations':observations,'choices':choices,
        'source_pool_count':len(sources),'parent_count':len({s.get('original_sha256') or s['sha256'] for s in sources})})
    print(code,'expanded semantic plan ready',len(sources),flush=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--code',choices=CODES);args=parser.parse_args()
    for c in ([args.code] if args.code else CODES):prepare(c)

if __name__=='__main__':main()
