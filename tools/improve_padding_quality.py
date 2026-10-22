"""Isolated, resumable Montbell experiment. Never mutate the studio task or old runs."""
import argparse
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'data/padding-quality-implementation-20261015'
OLD=ROOT/'data/studio/work-d82634dd9a064151/job-93795039313a43ff'
RENDERER=ROOT.parent/'auto_capcut'


def read(path):return json.loads(Path(path).read_text('utf-8'))
def save(path,data):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def process(action,plan,name,**extra):
    folder=OUT/name;folder.mkdir(parents=True,exist_ok=True)
    request=dict(action=action,plan=plan,output_dir=str(folder),**extra)
    save(folder/'request.json',request)
    with (folder/'process.log').open('w',encoding='utf-8') as log:
        subprocess.run([str(RENDERER/'.venv/Scripts/python.exe'),'-X','utf8','-m','auto_capcut.studio_runner',
                        '--request',str(folder/'request.json'),'--result',str(folder/'result.json')],
                       cwd=RENDERER,stdout=log,stderr=log,check=True)
    return read(folder/'result.json')


def review_sources():
    from hotpost.config import load_settings
    from hotpost.source_overlay_review import review_source_overlays
    settings=load_settings()
    state=read(OUT/'original-state.json')
    requests={'4391':[[46.2,46.45],[46.45,48.8],[48.8,50.2]],
              '42ac':[[1.6,3.4],[4.4,7.5],[51.8,54.0],[55.8,58.0]]}
    for tail,intervals in requests.items():
        source=next(s for s in state['sources'] if s['id'].endswith(tail))
        print('Review exact intervals',tail,intervals,flush=True)
        reviewed=review_source_overlays(settings,source,OUT/'source-reviews'/tail,intervals=intervals)
        save(OUT/'source-reviews'/f'{tail}.json',reviewed)
        print('Accepted',tail,reviewed['reviewed_intervals'],flush=True)


def build_plan():
    from hotpost.shot_presentation import interval_receipt
    from hotpost.scene_analysis import _observe
    from hotpost.script_rewriter import _generate
    from hotpost.config import load_settings
    old=read(OLD/'timeline.json');state=read(OUT/'original-state.json')
    sources={s['id'][-4:]:copy.deepcopy(s) for s in state['sources']}
    for tail in ('4391','42ac'):sources[tail]=read(OUT/'source-reviews'/f'{tail}.json')
    # Different product information within the same original is kept distinct;
    # identical uploads may share a visual cluster. No file-count target.
    windows=[('compare','4df4',7.566667,9.0),('hanger','4391',46.2,47.3),
             ('purple-front','42ac',1.6,3.4),('green-front','44cc',1.5,3.3),
             ('quilting','42ac',51.8,54.0),('store-fit','4391',47.4,50.2),
             ('green-side','44cc',3.6,5.3),('zip-front','42ac',55.8,58.0),
             ('purple-finish','42ac',4.4,7.5)]
    shots=[]
    for sid,tail,a,b in windows:
        src=sources[tail];folder=OUT/'shot-evidence'/sid;folder.mkdir(parents=True,exist_ok=True)
        frames=[]
        # Boundaries + scene-change samples; source reviews retain full-sized
        # native-PTS evidence as well. The timeline observes only THIS window.
        for n,t in enumerate([a+.035,(a+b)/2,b-.04]):
            path=folder/f'{n}.jpg'
            if not path.exists():
                subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',src['path'],
                    '-frames:v','1','-vf','scale=540:960:force_original_aspect_ratio=increase,crop=540:960',str(path)],
                    check=True,capture_output=True)
            frames.append(str(path))
        shots.append(dict(id=sid,source_id=src['id'],path=src['path'],sha256=src['sha256'],
            start=a,end=b,frames=frames,source_role='context_only' if sid=='compare' else 'core',
            context_usage_limits=['Different thick coat for opening comparison only'] if sid=='compare' else [],
            parent_original_sha256=src.get('original_sha256') or src['sha256']))
    observed=OUT/'interval-observations.json'
    if observed.exists():observations=read(observed)
    else:
        observations=_observe(load_settings(),shots,_generate);save(observed,observations)
    for shot in shots:
        row=observations[shot['id']]
        if row.get('evidence_status')!='observed' or not row.get('shot_presentation'):
            raise ValueError('Interval presentation not explicitly reviewed: '+shot['id'])
        shot.update(row)
        if shot['id']!='compare':
            from hotpost.shot_presentation import supports_product
            if not supports_product(shot['shot_presentation']):
                raise ValueError('Interval is not reviewed product footage: '+shot['id'])
    groups=[(0,40,['compare']), (40,70,['hanger']), (70,118,['purple-front','green-front','store-fit']),
            (118,166,['green-front','purple-front','store-fit']), (166,232,['quilting','zip-front']),
            (232,298,['store-fit','purple-front']), (298,343,['green-side','purple-front']),
            (343,405,['zip-front','quilting']), (405,495,['purple-finish'])]
    plan=copy.deepcopy(old)
    for key in ('rendered_clips','mask_application_clock','selection_frozen','semantic_cache','footage_diversity',
                'output_dir','cover_path','sfx_path','audio_mix'):plan.pop(key,None)
    plan['caption_emphasis']={b['cue_id']:b['emphasis'] for b in old['beats']}
    plan['shots']=shots;plan['sources']=[sources[k] for k in ('4df4','4391','42ac','44cc')]
    plan['footage_selection_policy']='product-story-global-v3';plan['beats']=[]
    for i,(a,b,ids) in enumerate(groups):
        # Preserve final speech, cue wording, cue timestamps and total duration.
        cues=[c for c in plan['cues'] if c['start']<b/30 and c['end']>a/30]
        end=old['duration'] if b==495 else b/30
        plan['beats'].append(dict(id=f'scene-{i+1}',start=a/30,end=end,
            text=' '.join(c['text'] for c in cues),cue_id=cues[0]['id'],cue_ids=[c['id'] for c in cues],
            emphasis=0,promoted_subject_reference=i>0,
            options=[dict(shot_id=s,relation='context',action_match='not_established',reviewed=True,
                          reason='Reviewed interval: '+observations[s]['observation']) for s in ids]))
    save(OUT/'candidate-plan.json',plan)
    result=process('select-shots',plan,'selection')
    save(OUT/'selected-plan.json',result['plan'])
    print('Selected',[(b['id'],b['selected_shot_id'],b['source_start'],b['source_end']) for b in result['plan']['beats']],flush=True)


def cover_candidate():
    plan=read(OUT/'selected-plan.json')
    src=next(s for s in plan['sources'] if s['id'].endswith('4391'))
    candidate=dict(shot_id='hanger',source_id=src['id'],source_sha256=src['sha256'],
                   timestamp=46.31,timeline_time=40/30+.11,core_scene=True)
    result=process('cover-candidates',plan,'cover-review',candidates=[candidate])
    print(result['candidates'][0]['frame_path'],flush=True)


def finish_plan():
    from hotpost.cover_selection import select_cover
    from hotpost.config import load_settings
    plan=read(OUT/'selected-plan.json')
    replacement=read(OUT/'green-reframed-shots.json')
    observations=read(OUT/'green-reframed-observations.json')
    for shot in replacement:
        shot.update(observations[shot['id']])
        old=next(s for s in plan['shots'] if s['id']==shot['id']);old.clear();old.update(shot)
    source=read(OUT/'source-reviews/green-reframed.json')
    plan['sources']=[s for s in plan['sources'] if not s['id'].endswith('44cc')]+[source]
    plan.pop('selection_frozen',None)
    # Reopen previous automatic choices; actual editorial candidate constraints
    # remain in options. Neither a user lock nor a required evidence frame is removed.
    for beat in plan['beats']:
        for k in ('selected_shot_id','source_start','source_end'):beat.pop(k,None)
    plan=process('select-shots',plan,'selection-reframed')['plan']
    candidates=read(OUT/'cover-review/result.json')['candidates']
    plan=select_cover(load_settings(),plan,candidates,OUT/'cover-approval')
    plan['source_frame_trace']=True
    save(OUT/'final-plan.json',plan)
    print('Final plan and exact cover approved',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['review-sources','build-plan','cover-candidate','finish-plan','render'])
    phase=parser.parse_args().phase
    if phase=='review-sources':review_sources()
    elif phase=='build-plan':build_plan()
    elif phase=='cover-candidate':cover_candidate()
    elif phase=='finish-plan':finish_plan()
    elif phase=='render':print(process('render',read(OUT/'final-plan.json'),'improved-video'),flush=True)
