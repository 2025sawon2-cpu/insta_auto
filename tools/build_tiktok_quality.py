"""New script/voice/render versions; reuse hash-bound reviewed source clips."""
import argparse,copy,hashlib,json,os,time
from pathlib import Path

from hotpost.config import load_settings
from hotpost.source_quality import sha256_file
from hotpost.voicebench_adapter import VoiceBenchAdapter
from hotpost.studio import Studio
from tools.refine_tiktok_quality import OLD,ROOT,FINDINGS
from tools.rework_tiktok_batch import save
from tools import build_tiktok_rework as build

CODES=tuple(FINDINGS)
CHOICE={CODES[0]:1,CODES[1]:1,CODES[2]:1}


def configure():
    build.ROOT=ROOT;build.CODES=CODES
    original=build.boundary
    build.boundary=lambda c,action,**kw:original(c,action,quality_revision='psychology-cover-20261011-v2'+('-caption-v3' if c=='DeJ7hD6zsnR' else ''),**kw)
    bins=next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH']=str(bins)+os.pathsep+os.environ['PATH']


def prepare(code):
    folder=ROOT/code/'writing';quality=json.loads((folder/('quality-final.json' if (folder/'quality-final.json').exists() else 'quality.json')).read_text('utf-8'))
    assert not quality['human_review_pending'],'Editorial comparison must be recorded before rendering.'
    selected=next(s for s in quality['scripts'] if s['number']==CHOICE[code]);r=build.root(code);r.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(selected['text'].encode()).hexdigest()
    script={**selected,'id':'tiktok-quality-script-'+code+'-'+digest[:12],'sha256':digest,'status':'completed',
            'created':time.time(),'writing_contract':quality['writing_contract']}
    save(r/'script.json',script);(r/'words.txt').write_text(script['text'],'utf-8')
    sources=json.loads((OLD/code/'final/approved-sources.json').read_text('utf-8'))
    for s in sources:
        assert sha256_file(Path(s['path']))==s['sha256']
        for f in s['evidence_frames']:assert sha256_file(Path(f['path']))==f['sha256']
    save(r/'proposed-sources.json',sources)
    save(r/'clips-reviewed.json',{'scope':'reuse unchanged actual visually reviewed portrait clips with matching hashes',
        'previous_review':str(OLD/code/'final/clips-reviewed.json'),'source_ids':[s['id'] for s in sources],
        'updated_at':time.time(),'original_coverage_complete':code!=build.EXAMPLE_CODE})
    voice_file=r/'voice.json'
    if voice_file.exists():
        assert json.loads(voice_file.read_text('utf-8'))['script_sha256']==digest
        return
    submission=r/'voice-submission.json';request=json.loads(submission.read_text('utf-8')).get('request_id') if submission.exists() else None
    result=VoiceBenchAdapter(load_settings()).synthesize(script['text'],r/'narration.wav',
        progress=lambda m,n:print(code,m,n,flush=True),request_id=request,
        on_submitted=lambda i:save(submission,{'request_id':i,'script_sha256':digest}),
        generation_key='tiktok-quality-'+code+'-'+digest,require_personal_clone=True)
    save(voice_file,{**result,'id':'tiktok-quality-voice-'+code+'-'+digest[:12],'path':str(r/'narration.wav'),
        'sha256':sha256_file(r/'narration.wav'),'duration':result['audio']['duration'],'script_id':script['id'],
        'script_sha256':digest,'created':time.time(),'status':'completed'})
    print(code,'new personal voice saved',result['audio']['duration'],flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','analyze','select','render','attach']);p.add_argument('--code',choices=CODES)
    args=p.parse_args();configure()
    for code in ([args.code] if args.code else CODES):
        (globals()[args.phase] if args.phase in ('prepare','attach') else getattr(build,args.phase))(code)


def attach(code):
    r=build.root(code);v=json.loads((r/'verification.json').read_text('utf-8'));assert not v['visual_review_pending']
    result=json.loads((r/'render-result.json').read_text('utf-8'));script=json.loads((r/'script.json').read_text('utf-8'))
    voice=json.loads((r/'voice.json').read_text('utf-8'));plan=json.loads(Path(result['plan_path']).read_text('utf-8'))
    assert sha256_file(Path(result['preview_path']))==sha256_file(r/'preview.mp4')
    state=json.loads((r/'baseline-state.json').read_text('utf-8'));studio=Studio(load_settings(),workers=False)
    edit={k:x for k,x in result.items() if k!='status'}
    edit.update(id='tiktok-quality-20261011-v2-'+code,script_id=script['id'],voice_id=voice['id'],created=time.time(),
        status='completed',export_path=result['preview_path'],export_verified=True,export_kind='web_render',
        registration_deferred=True,source_diversity=v['metrics'],quality_revision='psychology-cover-v2')
    def change(task,db):
        previous=task.get('edit_id')
        for key,obj in [('scripts',script),('voices',voice),('edits',edit)]:
            if not any(x['id']==obj['id'] for x in task[key]):task[key].append(obj)
        task['sources'].extend(x for x in plan['sources'] if not any(y['id']==x['id'] for y in task['sources']))
        task.update(script_id=script['id'],voice_id=voice['id'],edit_id=edit['id'],status='completed',error='',progress=100,
            message='대본·썸네일·장면 구성을 보완한 새 검토본 생성')
        task.setdefault('automation',{}).update(active=False,stage='completed')
        quality_file=ROOT/code/'writing/quality-final.json'
        if not quality_file.exists():quality_file=ROOT/code/'writing/quality.json'
        task['quality_revision_path']=str(quality_file)
        from hotpost.studio_workflow import init_run,snapshot
        parent_run=task.pop('run_id',None)
        run=init_run(task)
        if parent_run:run['parent_id']=parent_run
        run['inputs']['source_ids']=[s['id'] for s in plan['sources']]
        snapshot(task)
        run['artifacts']['sources']=copy.deepcopy(plan['sources'])
        run.update(status='completed',completed=time.time())
        task['latest_completed_run_id']=run['id']
        studio.store.event(db,task['id'],'quality_rework_version_added',{'edit_id':edit['id'],'preserved_edit_id':previous})
    studio.store.change(state['id'],change);print(code,'new version attached; prior edits preserved',flush=True)


if __name__=='__main__':main()
