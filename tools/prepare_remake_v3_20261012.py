"""Preserve prior renders and inspect the final corrections before production."""
import argparse, copy, json, subprocess
from pathlib import Path
from hotpost.editing_adapter import _atomic_json
from hotpost.source_quality import sha256_file
from hotpost.source_finder import probe_video
from hotpost.source_presentation import POLICY, review_scope
ROOT=Path('data/feedback-remake-20261012-v1').resolve()

def read(path): return json.loads(path.read_text('utf-8'))

def stage(code):
    folder=ROOT/code/'final-v3';folder.mkdir(exist_ok=True)
    p=read(ROOT/code/'final-v2/timeline.json')
    shots={s['id']:s for s in p['shots']}
    ids={'DeTaESASnr_':['shot-6-1','shot-14-1','extra-panels'],
         'DeTJ6HbKCdF':['shot-8-1','shot-10-1'],
         'DeSvpmAsWgZ':['shot-6-1']}[code]
    for sid in ids:
        s=shots[sid]
        stamps=[1.36] if code=='DeSvpmAsWgZ' else [.05,.4,.8]
        for n,t in enumerate(stamps):
            subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',s['path'],'-frames:v','1',str(folder/f'{sid}-{n}.jpg')],check=True,capture_output=True)
    if code=='DeTaESASnr_':
        changed=[]
        for s in p['sources']:
            name=s['name']
            if name not in ('cta-open','closed-board','closed-gallery','panels'):continue
            original=copy.deepcopy(s);target=folder/f'{name}-final-clean.mp4'
            rect=[270,940,220,90] if name=='panels' else [0,915,210,105]
            x,y,w,h=rect
            graph=f'[0:v]split[b][m];[m]crop={w}:{h}:{x}:{y},boxblur=28:4:14:4[c];[b][c]overlay={x}:{y}[v]'
            if not target.exists():
                subprocess.run(['ffmpeg','-v','error','-i',s['path'],'-filter_complex',graph,'-map','[v]','-an','-c:v','libx264','-crf','18','-preset','veryfast',str(target)],check=True,capture_output=True)
            s.update(path=str(target),sha256=sha256_file(target),video_meta=probe_video(target),watermark_masks=[],blur_required=False)
            s['additional_creator_cleanup']={'pixels':rect,'baked_in':True,'parent_path':original['path'],'parent_sha256':original['sha256']}
            frames=[]
            for n,f in enumerate((.02,.3,.65,.97)):
                t=(s['video_meta']['duration']-.04)*f;frame=folder/f'{name}-clean-{n}.jpg'
                subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(target),'-frames:v','1',str(frame)],check=True,capture_output=True)
                frames.append({'path':str(frame),'timestamp':t,'sha256':sha256_file(frame)})
            s['cleanup_frames']=frames;changed.append(s)
        _atomic_json(folder/'cleanup-pending.json',changed)

def finish(code):
    folder=ROOT/code/'final-v3';p=read(ROOT/code/'final-v2/timeline.json')
    for key in ('rendered_clips','cover_path','sfx_path','output_dir'):p.pop(key,None)
    if code=='DeTaESASnr_':
        changed=read(folder/'cleanup-pending.json');by={s['id']:s for s in changed}
        for s in changed:
            assert sha256_file(Path(s['path']))==s['sha256']
            s['functional_review'].update(source_sha256=s['sha256'],evidence_frames=[f['path'] for f in s['cleanup_frames']])
            s['presentation_review'].update(policy=POLICY,reviewed=True,source_sha256=s['sha256'],scope=review_scope(s),usable=True,quality_usable=True,action_preserved=True,evidence_frames=s['cleanup_frames'],observations=['원래 사용 동작을 보존하고 작은 제작자 표시에 추가 블러 적용. 실제 4프레임 확인.'])
        p['sources']=[by.get(s['id'],s) for s in p['sources']]
        for shot in p['shots']:
            if shot['source_id'] in by:
                s=by[shot['source_id']];shot.update(path=s['path'],sha256=s['sha256'],frames=[f['path'] for f in s['cleanup_frames']])
        p['beats'][14]['options']=[{'shot_id':'shot-6-1','relation':'context','reason':'같은 제품의 다른 설치 구도. 은색 보드의 생활 활용 맥락이며 닫는 동작을 주장하지 않음.','reviewed':True}]
        _atomic_json(folder/'cleanup-approved.json',changed)
    elif code=='DeTJ6HbKCdF':
        p['cover_spec']['lines']=['짐 옮기던 물건이','도착하니 식사 자리가?']
        for n,sid in ((14,'shot-8-1'),(15,'shot-10-1'),(16,'shot-10-1')):
            p['beats'][n]['options']=[{'shot_id':sid,'relation':'context','reason':'직접 확인한 카트의 적재·상판 구성으로 마무리. 이미 본 바퀴·다리 하부를 다시 제시하지 않음.','reviewed':True}]
    else:p['cover_spec']['lines']=['비싸서 넘겼던 노스페이스','왜 다시 입어봤을까?']
    for b in p['beats']:b.pop('selected_shot_id',None)
    p['session_options_ready']=True
    _atomic_json(folder/'selection-input.json',p)
    _atomic_json(folder/'cover-copy-revision.json',{'lines':p['cover_spec']['lines'],'basis':'실제 이미지가 대본의 핵심 질문에 대한 답을 미리 보여주지 않는지 함께 평가. 가격·할인 조건을 새로 주장하지 않음.'})

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['stage','finish']);parser.add_argument('code');a=parser.parse_args();globals()[a.action](a.code)
