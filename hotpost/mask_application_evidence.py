"""Pixel evidence for applying existing approved masks, not widening them."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

POLICY = 'mask-application-pixels-v2'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def input_binding_sha256(receipt):
    return digest({k:v for k,v in receipt.items() if k not in {'official_review','input_binding_sha256'}})


def frozen_selection(plan):
    shots={s['id']:s for s in plan.get('shots',[])}
    selected=[]
    for b in plan.get('beats',[]):
        shot=shots.get(b.get('selected_shot_id'),{})
        selected.append({'beat':{k:b.get(k) for k in ('id','text','start','end','selected_shot_id','source_start','source_end','emphasis')},
                         'shot':{k:shot.get(k) for k in ('id','source_id','sha256','start','end','path')}})
    return {'script_text':plan.get('script_text'),'voice':plan.get('voice'),
            'selected':selected,'cues':plan.get('cues'),'cover_spec':plan.get('cover_spec'),
            'sources':[{k:s.get(k) for k in ('id','path','sha256','watermark_masks','portrait_geometry','mask_review','reviewed_intervals')}
                       for s in plan.get('sources',[])],
            'duration':plan.get('duration'),'sound_effects':plan.get('sound_effects'),
            'caption_style':plan.get('caption_style')}


def preserves_render_inputs(candidate, original):
    # The application receipt is the only new render input. In particular,
    # native anchors, approved coverage, fonts, cues and audio stay untouched.
    value=copy.deepcopy(candidate)
    value.pop('quality_mask_application',None)
    return value==original


def _pixels(record, roi):
    from PIL import Image
    if file_sha(record['path'])!=record['file_sha256']:raise ValueError('Mask evidence file changed')
    with Image.open(record['path']) as image:
        rgb=image.convert('RGB')
        if rgb.size!=(1080,1920):raise ValueError('Mask evidence canvas changed')
        x,y,w,h=roi
        actual=hashlib.sha256(rgb.tobytes()).hexdigest()
        cropped=hashlib.sha256(rgb.crop((x,y,x+w,y+h)).tobytes()).hexdigest()
    if actual!=record['rgb_sha256'] or cropped!=record['roi_rgb_sha256']:
        raise ValueError('Mask evidence decoded pixels changed')
    return cropped


def pixel_rectangle(rect):
    w=max(2,round(rect['width']*1080));h=max(2,round(rect['height']*1920))
    x=max(0,round((rect['centerX']+1)*540-w/2));y=max(0,round((1-rect['centerY'])*960-h/2))
    return [x,y,min(w,1080-x),min(h,1920-y)]


def approved_material(state, receipt=None):
    """Return only native-bound, officially confirmed decoded ROI changes."""
    receipt=receipt or state.get('daily_quality',{}).get('mask_application_repair_evidence') or {}
    try:
        if receipt.get('policy')!=POLICY or receipt.get('edit_id')!=state.get('edit_id'):return []
        binding=input_binding_sha256(receipt)
        if receipt.get('input_binding_sha256')!=binding:return []
        edit=next(e for e in state['edits'] if e['id']==receipt['edit_id'])
        if file_sha(edit['plan_path'])!=receipt['parent_plan_sha256'] or file_sha(edit['preview_path'])!=receipt['parent_preview_sha256']:return []
        plan=json.loads(Path(edit['plan_path']).read_text('utf-8'))
        if frozen_selection(plan)!=receipt['selection_binding']:return []
        concat=Path(receipt['concat_path'])
        if file_sha(concat)!=receipt['concat_sha256']:return []
        paths=[str(Path(line[6:-1]).resolve()) for line in concat.read_text('utf-8').splitlines() if line.startswith("file '")]
        if not paths or paths!=[str(Path(row['path']).resolve()) for row in receipt['concat_inputs']]:return []
        metadata=receipt['concat_metadata']
        if file_sha(metadata['path'])!=metadata['sha256']:return []
        concat_frames=json.loads(Path(metadata['path']).read_text('utf-8'))['frames']
        clock=receipt['frame_clock']
        if file_sha(clock['path'])!=clock['file_sha256']:return []
        actual_pts=[float(f['pts_time']) for f in json.loads(Path(clock['path']).read_text('utf-8'))['frames']]
        if hashlib.sha256(json.dumps(actual_pts,sort_keys=True).encode()).hexdigest()!=receipt['frame_clock_sha256']:return []
        if actual_pts!=[float(f['pts_time']) for f in concat_frames]:return []
        for name in ('before','after'):
            capture=receipt['captures'][name]
            if file_sha(capture['log_path'])!=capture['log_sha256']:return []
            if file_sha(capture['graph_path'])!=capture['graph_file_sha256']:return []
            graph=json.loads(Path(capture['graph_path']).read_text('utf-8'))['graph']
            if hashlib.sha256(graph.encode()).hexdigest()!=capture['graph_sha256']:return []
            if name=='after' and capture['graph_sha256']!=receipt['graph_sha256']:return []
        official=receipt['official_review']
        if file_sha(official['path'])!=official['sha256']:return []
        review=json.loads(Path(official['path']).read_text('utf-8'))
        if review.get('passed') is not True or review.get('input_binding_sha256')!=binding:return []
        if type(review.get('actual_calls')) is not int or review['actual_calls']!=1:return []
        typed=Path(official['typed_receipt_path'])
        if file_sha(typed)!=review.get('typed_receipt_sha256'):return []
        typed_payload=json.loads(typed.read_text('utf-8'))
        if typed_payload!={k:v for k,v in receipt.items() if k!='official_review'}:return []
        cases=receipt['cases']
        if not cases or len({c['beat_id'] for c in cases})!=len(cases):return []
        approvals=review.get('cases',[])
        if len(approvals)!=len(cases):return []
        displays=review.get('display_projections') or []
        if len(displays)!=len(cases)*2:return []
        expected={(c['beat_id'],role):c[role]['file_sha256'] for c in cases for role in ('before','after')}
        if len({(d.get('beat_id'),d.get('role')) for d in displays})!=len(displays):return []
        if any(expected.get((d.get('beat_id'),d.get('role')))!=d.get('original_png_sha256') or
               d.get('canvas')!=[1080,1920] or not d.get('display_jpeg_sha256') for d in displays):return []
        from .quality_progress import unresolved,text
        defects=unresolved(state)
        if not defects or any(d['kind']!='watermark' for d in defects):return []
        beats={b['id']:b for b in plan['beats']};shots={s['id']:s for s in plan['shots']}
        sources={s['id']:s for s in plan['sources']};current={s['id']:s for s in state['sources']}
        expected_targets={d['target'] for d in defects}
        if expected_targets!={text(beats[c['beat_id']]['text']) for c in cases}:return []
        for row in receipt['concat_inputs']:
            if file_sha(row['path'])!=row['sha256']:return []
        from .source_frame_timing import probe_native_timing
        result=[]
        for case in cases:
            approval=next(a for a in approvals if a['beat_id']==case['beat_id'])
            if any(approval.get(k) is not True for k in ('before_text_readable','after_text_unreadable','subject_visible')):return []
            beat=beats[case['beat_id']];shot=shots[beat['selected_shot_id']]
            source=sources[shot['source_id']];now=current[source['id']]
            if case['source_id']!=source['id'] or case['source_sha256']!=source['sha256'] or file_sha(now['path'])!=source['sha256']:return []
            for field in ('watermark_masks','portrait_geometry','mask_review','reviewed_intervals'):
                if now.get(field)!=source.get(field):return []
            lo=beat.get('source_start',shot['start']);hi=beat.get('source_end',shot['end'])
            if case['source_window']!=[lo,hi] or case['mask_geometry_sha256']!=digest({k:source.get(k) for k in ('watermark_masks','portrait_geometry','mask_review','reviewed_intervals')}):return []
            if case['roi'] not in [pixel_rectangle(m['rectangle']) for m in source['watermark_masks']]:return []
            before,after=case['before'],case['after']
            if before['pts']!=after['pts'] or before['time_base']!=after['time_base']:return []
            for name,record in (('before',before),('after',after)):
                log=Path(receipt['captures'][name]['log_path']).read_text('utf-8')
                clock=re.search(r'Parsed_showinfo_'+str(case['capture_filter_index'])+r'.*?config in time_base:\s*(\d+/\d+)',log)
                if not clock or clock[1]!=record['time_base']:return []
                match=re.search(r'Parsed_showinfo_'+str(case['capture_filter_index'])+r'.*?n:\s*0 pts:\s*(\d+) pts_time:([\d.]+)',log)
                if not match or int(match[1])!=record['pts']:return []
            decoded=next(f for f in concat_frames if f['pts']==before['pts'])
            numerator,denominator=map(int,before['time_base'].split('/'))
            seconds=before['pts']*numerator/denominator
            if abs(float(decoded['pts_time'])-seconds)>1e-6:return []
            segment=[f for f in concat_frames if f['tags']['lavf.concatdec.start_time']==decoded['tags']['lavf.concatdec.start_time']]
            ordinal=segment.index(decoded)
            if ordinal!=case['concat_frame_ordinal']:return []
            clip=next(c for c in plan['rendered_clips'] if c['beat_id']==case['beat_id'])
            # The concat starts with one cover frame and first-body; subsequent
            # segments map one-to-one to the frozen render-cache clips.
            starts=list(dict.fromkeys(f['tags']['lavf.concatdec.start_time'] for f in concat_frames))
            segment_index=starts.index(decoded['tags']['lavf.concatdec.start_time'])
            if segment_index<2 or str(Path(clip['path']).resolve())!=paths[segment_index]:return []
            if _pixels(before,case['roi'])==_pixels(after,case['roi']):return []
            native=case['source_native_frame']
            timing=probe_native_timing(now['path'],source['sha256'])
            if native.get('source_sha256')!=source['sha256']:return []
            if native.get('metadata_sha256')!=timing['metadata_sha256']:return []
            if not any(f['start']==native['start'] and f['end']==native['end'] for f in timing['frames']):return []
            trace=case['native_selection_trace']
            if file_sha(trace['log_path'])!=trace['log_sha256'] or file_sha(trace['argv_path'])!=trace['argv_sha256']:return []
            argv=json.loads(Path(trace['argv_path']).read_text('utf-8'))
            if ('-copyts' not in argv or argv[argv.index('-ss')+1]!=str(lo) or
                    argv[argv.index('-i')+1]!=source['path'] or
                    argv[argv.index('-vf')+1]!='showinfo,fps=30,showinfo'):return []
            log=Path(trace['log_path']).read_text('utf-8')
            fps_match=re.search(r'Parsed_showinfo_2.*?n:\s*'+str(ordinal)+r'\s+pts:\s*(\d+) pts_time:([\d.]+).*?checksum:([0-9A-F]+)',log)
            if not fps_match:return []
            inputs=[float(m[1]) for m in re.finditer(r'Parsed_showinfo_0.*?n:\s*\d+ pts:\s*\d+ pts_time:([\d.]+).*?checksum:'+fps_match[3]+r'\b',log)]
            if inputs!=[native['start']]:return []
            if not lo<=native['start']<native['end']<=hi:return []
            result.append({'beat_id':case['beat_id'],'target':text(beat['text']),
                'source_sha256':source['sha256'],'source_window':case['source_window'],
                'source_native_frame':{k:native[k] for k in ('start','end','source_sha256')},
                'mask_geometry_sha256':digest({'masks':[{k:m.get(k) for k in ('source_start','source_end','rectangle','strength','expected_scale')}
                    for m in source['watermark_masks']],'geometry':source.get('portrait_geometry')}),
                'pts':before['pts'],'time_base':before['time_base'],'roi':case['roi'],
                'before_roi_rgb_sha256':before['roi_rgb_sha256'],'after_roi_rgb_sha256':after['roi_rgb_sha256']})
        return result
    except (OSError,ValueError,KeyError,TypeError,StopIteration,RuntimeError):
        return []


def render_evidence(state):
    receipt=state.get('daily_quality',{}).get('mask_application_repair_evidence') or {}
    material=approved_material(state,receipt)
    if not material:return None
    edit=next(e for e in state['edits'] if e['id']==receipt['edit_id'])
    return {'receipt':copy.deepcopy(receipt),'material':material,'parent_plan_path':edit['plan_path']}
