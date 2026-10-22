"""Collect integer source->fps->concat->final ordinals and immutable QA bindings."""
import collections
import hashlib
import json
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from improve_padding_quality import OUT,OLD,read,save,sha


def probe(path):
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
        '-show_frames','-show_entries','stream=time_base:frame=best_effort_timestamp','-of','json',str(path)],text=True))


def trace(plan):
    shots={s['id']:s for s in plan['shots']};beats={b['id']:b for b in plan['beats']};native={};rows=[]
    for clip in plan['rendered_clips']:
        shot=shots[beats[clip['beat_id']]['selected_shot_id']]
        if shot['path'] not in native:native[shot['path']]=probe(shot['path'])
        catalog=native[shot['path']];base=Fraction(catalog['streams'][0]['time_base'])
        times=[(int(f['best_effort_timestamp'])*base,int(f['best_effort_timestamp'])) for f in catalog['frames']]
        path=Path(clip['source_decode_trace']);log=path.read_text('utf-8')
        configs=re.findall(r'Parsed_showinfo_(\d+).*?config in time_base:\s*(\d+/\d+)',log)
        first,last=configs[0],configs[1]
        def decoded(index):
            return [(int(n),int(pts),checksum) for n,pts,checksum in re.findall(
                r'Parsed_showinfo_'+index+r'[^\n]*?n:\s*(\d+)\s+pts:\s*(-?\d+)[^\n]*?\bchecksum:([0-9A-F]+)',log)]
        inputs=decoded(first[0]);outputs=decoded(last[0]);seek=Fraction(round(clip['source_seek']*1000000),1000000)
        count=round(clip['duration']*30);mapped=[]
        for index,pts,checksum in outputs[:count]:
            candidates=[]
            for n,local,crc in inputs:
                if crc!=checksum:continue
                absolute=local*Fraction(first[1])+seek
                near=min(times,key=lambda t:abs(t[0]-absolute))
                if abs(near[0]-absolute)>Fraction(1,1000000):raise ValueError('Decoded source PTS did not match native catalog')
                candidates.append(dict(ordinal=n,local_pts=local,native_pts=near[1],time_base=str(base)))
            if not candidates:raise ValueError('FPS output has no matching decoded source pixels')
            global_index=round(clip['start']*30)+index
            mapped.append(dict(local_fps_ordinal=index,local_fps_pts=pts,local_fps_time_base=last[1],
                global_ordinal=global_index,concat_pts=plan['mask_application_clock']['pts'][global_index],
                concat_time_base=plan['mask_application_clock']['time_base'],final_output_ordinal=global_index,
                cover_replaces_source_frame=global_index==0,native_candidates=candidates))
        if len(mapped)!=count:raise ValueError('Incomplete actual source->FPS mapping')
        rows.append(dict(beat_id=clip['beat_id'],source_sha256=shot['sha256'],
            log_path=str(path),log_sha256=sha(path),frames=mapped))
    return rows


def stream_hash(path,kind):
    if kind=='video':
        output=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0','-f','framemd5','-'],text=True)
        return [r.split(',')[-1].strip() for r in output.splitlines() if not r.startswith('#')]
    output=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-c','copy','-f','hash','-hash','sha256','-'],text=True)
    return output.strip()


if __name__=='__main__':
    final=OUT/'improved-video';export=OUT/'verified-export';plan=read(final/'timeline.json');old=read(OLD/'timeline.json')
    mapping=trace(plan);save(OUT/'qa/source-output-frame-map.json',mapping)
    current=read(OUT/'qa/production-improved.json');before=read(OUT/'qa/production-old.json')
    assert before['passed'] is False and current['passed'] is True
    assert any('70' in r['reason'] for r in before['issues']) and any('388' in r['reason'] for r in before['issues'])
    assert sha(final/'preview.mp4')==current['render_sha256']==plan['mask_application_clock']['final_render_sha256']
    assert sha(final/'timeline.json')==current['plan_sha256']
    assert old['script_text']==plan['script_text'] and old['voice']==plan['voice'] and old['cues']==plan['cues']
    video_equal=stream_hash(final/'preview.mp4','video')==stream_hash(export/'preview.mp4','video')
    audio_equal=stream_hash(final/'preview.mp4','audio')==stream_hash(export/'preview.mp4','audio')
    assert video_equal and audio_equal
    assert read(export/'timeline.json')['mask_application_clock']['final_render_sha256']==sha(export/'preview.mp4')
    usage=collections.defaultdict(float)
    for b in plan['beats']:
        s=next(s for s in plan['shots'] if s['id']==b['selected_shot_id']);usage[s['source_id']]+=round(b['end']*30)/30-round(b['start']*30)/30
    receipt=dict(technical_passed=True,editorial_review_passed=current['passed'],baseline_new_review_failed=not before['passed'],
        original_render_sha256=sha(OLD/'preview.mp4'),improved_render_sha256=sha(final/'preview.mp4'),
        improved_plan_sha256=sha(final/'timeline.json'),export_sha256=sha(export/'preview.mp4'),
        decoded_export_video_equal=video_equal,encoded_export_audio_equal=audio_equal,
        final_frame_count=len(mapping[0]['frames'])+sum(len(r['frames']) for r in mapping[1:]),
        source_trace_path=str(OUT/'qa/source-output-frame-map.json'),source_trace_sha256=sha(OUT/'qa/source-output-frame-map.json'),
        original_sources_preserved=True,script_voice_cues_preserved=True,usage_seconds=dict(usage),
        native_capcut_ui_export_verified=False,audio_listened=False,
        caveats=['Mask positions are reviewed on samples and output boundaries; not continuous OCR of every frame.',
                 'Native CapCut UI export was not run. Actual portable/web export decoded frames and AAC packets are identical.'])
    save(OUT/'qa/technical-receipt.json',receipt)
    print(json.dumps(receipt,ensure_ascii=False,indent=2),flush=True)
