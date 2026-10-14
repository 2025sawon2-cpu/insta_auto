"""Today's jacket revision reuses existing reviewed files, never new downloads."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from hotpost.config import load_settings
from hotpost.source_quality import sha256_file
from hotpost.studio import Studio
from hotpost.voicebench_adapter import VoiceBenchAdapter
from tools.recover_daily_materials import ROOT
from tools.rework_tiktok_batch import save
from tools import build_tiktok_rework as build
from tools import build_tiktok_quality as version

CODE='DeSvpmAsWgZ'
OLD=ROOT.parent/'tiktok-quality-20261011-v2/DeJ7hD6zsnR/final'


def configure():
    build.ROOT=ROOT
    original=build.boundary
    build.boundary=lambda c,action,**kw:original(c,action,quality_revision='daily-jacket-spoken-v4-caption-v3',**kw)
    version.ROOT=ROOT
    os.environ['PATH']=str(next(Path(os.environ['LOCALAPPDATA']).glob(
        'Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin')))+os.pathsep+os.environ['PATH']


def prepare():
    folder=ROOT/CODE
    quality=json.loads((folder/'writing/quality-v4.json').read_text('utf-8'))
    assert not quality['human_review_pending']
    item=next(s for s in quality['scripts'] if s['number']==1)
    digest=hashlib.sha256(item['text'].encode()).hexdigest()
    r=build.root(CODE);r.mkdir(parents=True,exist_ok=True)
    script={**item,'id':'daily-jacket-script-'+digest[:12],'sha256':digest,'status':'completed',
            'created':time.time(),'writing_contract':quality['writing_contract']}
    save(r/'script.json',script);(r/'words.txt').write_text(script['text'],'utf-8')
    sources=json.loads((OLD/'approved-sources.json').read_text('utf-8'))
    sources=[s for s in sources if s['name']!='store-white']
    extra=ROOT.parent/'tiktok-rework-20261011/DeJ7hD6zsnR/final/approved-sources.json'
    front=next(s for s in json.loads(extra.read_text('utf-8')) if s['name']=='kid-front')
    front['reused_from']=str(extra)
    sources.append(front)
    for s in sources:
        assert sha256_file(Path(s['path']))==s['sha256']
        for f in s['evidence_frames']:assert sha256_file(Path(f['path']))==f['sha256']
        s['id']='daily-jacket-'+s['name']
        s.setdefault('reused_from',str(OLD/'approved-sources.json'))
    save(r/'proposed-sources.json',sources)
    save(r/'clips-reviewed.json',{'scope':'same decoded four-frame reviewed clips; hashes unchanged',
        'previous_review':str(OLD/'clips-reviewed.json'),'source_ids':[s['id'] for s in sources],
        'updated_at':time.time(),'reused_existing_downloads':True})
    recovery=json.loads((folder/'transcript-recovery.json').read_text('utf-8'))
    transcript=json.loads((Path(recovery['directory'])/'transcript.json').read_text('utf-8'))
    Studio(load_settings(),workers=False).store.create(CODE,CODE,initial={
        'original_text':' '.join(x['text'] for x in transcript['speech']),
        'reference_kind':'speech','reference_video':str(Path(recovery['directory'])/'reference.mp4'),
        'status':'preparing','message':'새 3안 중 선택한 대본으로 패딩 검토본 제작'},prepare=False)
    vf=r/'voice.json'
    if vf.exists():
        assert json.loads(vf.read_text('utf-8'))['script_sha256']==digest
        return
    submission=r/'voice-submission.json'
    request=json.loads(submission.read_text('utf-8')).get('request_id') if submission.exists() else None
    result=VoiceBenchAdapter(load_settings()).synthesize(item['text'],r/'narration.wav',
        progress=lambda m,n:print(CODE,m,n,flush=True),request_id=request,
        on_submitted=lambda i:save(submission,{'request_id':i,'script_sha256':digest}),
        generation_key='daily-jacket-'+CODE+'-'+digest,require_personal_clone=True)
    save(vf,{**result,'id':'daily-jacket-voice-'+digest[:12],'path':str(r/'narration.wav'),
        'sha256':sha256_file(r/'narration.wav'),'duration':result['audio']['duration'],
        'script_id':script['id'],'script_sha256':digest,'created':time.time(),'status':'completed'})
    print(CODE,'personal voice saved',result['audio']['duration'],flush=True)


def attach():
    # The attachment helper appends distinct scripts/voices/edits and a new run.
    # Give it the actual writing revision, preserving the previous v3 proposal.
    quality=json.loads((ROOT/CODE/'writing/quality-v4.json').read_text('utf-8'))
    target=ROOT/CODE/'writing/quality-final.json'
    if target.exists():assert json.loads(target.read_text('utf-8'))==quality
    else:save(target,quality)
    from tools.build_selected_three import state
    if state(CODE).get('edit_id')=='tiktok-quality-20261011-v2-'+CODE:
        print(CODE,'verified version already attached; no duplicate run',flush=True)
        return
    version.attach(CODE)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=['prepare','analyze','select','render','attach'])
    args=parser.parse_args();configure()
    if args.phase=='prepare':prepare()
    elif args.phase=='attach':attach()
    else:getattr(build,args.phase)(CODE)


if __name__=='__main__':main()
