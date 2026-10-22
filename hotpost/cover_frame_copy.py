"""Replace one presented frame while verifying every body frame and audio packet."""
import json
import shutil
import subprocess
from pathlib import Path

from .thumbnail_mp4 import present_cover, video_timing


def replace_frame(source, cover, target, timeout=120, *, validation_base=None):
    source, cover, target = map(Path,(source,cover,target))
    if source.resolve()==target.resolve():raise ValueError('기존 영상은 덮어쓸 수 없습니다.')
    from .source_quality import sha256_file
    from .editing_adapter import _atomic_json
    validation_base=Path(validation_base) if validation_base else source
    inputs={str(p.resolve()):sha256_file(p) for p in (source,cover,validation_base)}
    receipt=target.with_suffix('.cover-copy.json')
    if target.exists():
        saved=json.loads(receipt.read_text('utf-8')) if receipt.is_file() else {}
        if saved.get('inputs')!=inputs or saved.get('sha256')!=sha256_file(target):
            raise ValueError('기존 표지 수정 결과의 입력·출력 결속이 다릅니다. 파일을 보존합니다.')
        return saved['proof']
    ffmpeg,probe=shutil.which('ffmpeg'),shutil.which('ffprobe')
    if not ffmpeg or not probe:raise RuntimeError('첫 프레임 교체에는 FFmpeg가 필요합니다.')
    def run(args):
        return subprocess.check_output(args,stderr=subprocess.PIPE,timeout=timeout)
    def metadata(path):
        return json.loads(run([probe,'-v','error','-count_frames','-show_streams','-show_format','-of','json',str(path)]))
    before=metadata(validation_base);video=next(s for s in before['streams'] if s['codec_type']=='video')
    if tuple(video.get(k) for k in ('width','height','r_frame_rate','codec_name','pix_fmt'))!=(1080,1920,'30/1','h264','yuv420p'):
        raise ValueError('첫 프레임 교체의 영상 규격이 다릅니다.')
    scale,deltas,_,_=video_timing(source)
    if len(deltas)!=int(video['nb_read_frames']):raise ValueError('원본 프레임 시각을 확인할 수 없습니다.')
    target.parent.mkdir(parents=True,exist_ok=True)
    prefix=target.with_name(target.stem+'-prefix.mp4');joined=target.with_name(target.stem+'-joined.mp4')
    listing=target.with_suffix('.concat.txt')
    color=[]
    for key,option in [('color_range','-color_range'),('color_space','-colorspace'),('color_transfer','-color_trc'),('color_primaries','-color_primaries')]:
        if video.get(key) not in (None,'unknown','unspecified'):color += [option,video[key]]
    def encode(args):run([ffmpeg,'-y','-v','error',*map(str,args)])
    encode(['-i',cover,'-frames:v','1','-r','30','-c:v','libx264','-crf','18','-preset','medium',
            '-profile:v','high','-pix_fmt','yuv420p','-bf','0',*color,'-video_track_timescale',scale,prefix])
    def quote(path):return "file '"+path.resolve().as_posix().replace("'","'\\''")+"'\n"
    listing.write_text(quote(prefix)+'duration 0.03333333333333333\n'+quote(source),'utf-8')
    has_audio=any(s['codec_type']=='audio' for s in before['streams'])
    encode(['-f','concat','-safe','0','-i',listing,'-i',source,'-map','0:v:0',
            *(['-map','1:a:0'] if has_audio else []),'-c','copy',*color,
            '-video_track_timescale',scale,'-movie_timescale',scale,joined])
    present_cover(joined,source,target)
    if target.stat().st_size>source.stat().st_size+max(512*1024,source.stat().st_size//10):
        raise ValueError('표지 교체 파일 크기가 예상 범위를 벗어났습니다.')
    after=metadata(target);new=next(s for s in after['streams'] if s['codec_type']=='video')
    if any(new.get(k)!=video.get(k) for k in ('width','height','r_frame_rate','nb_read_frames')):
        raise ValueError('첫 프레임 교체 후 프레임 수·규격이 달라졌습니다.')
    if abs(float(after['format']['duration'])-float(before['format']['duration']))>.04:
        raise ValueError('첫 프레임 교체 후 길이가 달라졌습니다.')
    def frames(path):
        rows=run([ffmpeg,'-v','error','-i',str(path),'-map','0:v:0','-pix_fmt','yuv420p','-f','framemd5','-']).decode().splitlines()
        return [r for r in rows if r and not r.startswith('#')]
    old_rows,new_rows=frames(validation_base),frames(target)
    if len(old_rows)!=len(new_rows) or old_rows[1:]!=new_rows[1:]:
        raise ValueError('표지 교체로 본문 픽셀·시간축이 변경되었습니다.')
    if has_audio:
        def audio(path):return run([ffmpeg,'-v','error','-i',str(path),'-map','0:a:0','-c','copy','-f','hash','-'])
        if audio(validation_base)!=audio(target):raise ValueError('표지 교체로 음성이 변경되었습니다.')
    prefix.unlink();joined.unlink()
    proof={'duration':float(after['format']['duration']),'frames':len(new_rows),
           'body_frames_identical':True,'audio_identical':True}
    if any(sha256_file(Path(p))!=sha for p,sha in inputs.items()):
        raise ValueError('표지 교체 중 입력이 변경되었습니다.')
    _atomic_json(receipt,{'inputs':inputs,'sha256':sha256_file(target),'proof':proof})
    return proof


BODY_FIELDS=('beats','shots','sources','voice','voice_source','script_text','cues','caption_style',
             'sound_effects','sound_effect_policy','audio_mix','narration_policy','pause_processing',
             'fps','width','height','duration','footage_selection_policy')


def compatible_pair(base, body, timeout):
    probe=shutil.which('ffprobe')
    if not probe:return False
    try:
        counts=[]
        for path in (base,body):
            data=json.loads(subprocess.check_output([probe,'-v','error','-select_streams','v:0',
                '-show_streams','-of','json',str(path)],stderr=subprocess.PIPE,timeout=timeout))
            stream=data['streams'][0]
            if tuple(stream.get(k) for k in ('width','height','r_frame_rate','codec_name','pix_fmt'))!=(1080,1920,'30/1','h264','yuv420p'):
                return False
            scale,deltas,_,_=video_timing(path)
            counts.append((len(deltas),sum(deltas)/scale))
        return counts[0]==counts[1]
    except (ValueError,OSError,KeyError,IndexError,subprocess.SubprocessError):
        return False


def render_if_cover_only(studio,state,job,plan):
    from .source_quality import sha256_file
    from .editing_adapter import _atomic_json
    feedback=state.get('daily_quality',{}).get('feedback',[])
    if not feedback or any(i.get('kind')!='cover' for i in feedback):return None
    parent=next((e for e in state['edits'] if e['id']==job['payload'].get('edit_id')),None)
    if not parent:return None
    old=json.loads(Path(parent['plan_path']).read_text('utf-8'))
    if any(plan.get(k)!=old.get(k) for k in BODY_FIELDS):return None
    body=Path(old.get('output_dir',''))/'body.mp4'
    if not body.is_file():return None
    base=Path(parent.get('export_path') or parent['preview_path'])
    old_sha=sha256_file(base);old_plan_sha=sha256_file(Path(parent['plan_path']))
    if not any(r.get('edit_id')==parent['id'] and r.get('render_sha256')==old_sha
               and r.get('plan_sha256')==old_plan_sha
               and (r.get('passed') or (r.get('issues') and all(i.get('kind')=='cover' for i in r['issues'])))
               for r in state['daily_quality'].get('reviews',[])):
        return None
    if not compatible_pair(base,body,studio.settings.auto_capcut_timeout):
        return None
    result=studio._process(state,job,'cover-preview',{'plan':plan})
    selected=json.loads(json.dumps(plan));selected['cover_spec']=result['cover_spec']
    selected['cover_path']=result['cover_path'];selected['cover_text']='\n'.join(selected['cover_spec']['lines'])
    folder=studio.folder(state['id'])/job['id']
    preview=folder/'preview.mp4'
    proof=replace_frame(base,Path(result['cover_path']),preview,studio.settings.auto_capcut_timeout)
    replace_frame(body,Path(result['cover_path']),folder/'body.mp4',studio.settings.auto_capcut_timeout)
    if sha256_file(base)!=old_sha or sha256_file(Path(parent['plan_path']))!=old_plan_sha:
        raise ValueError('표지 교체 중 기존 본문·계획 파일이 변경되었습니다.')
    studio.store.assert_owned(job)
    selected['output_dir']=str(folder)
    selected['cover_revision']={**proof,'policy':'copy-first-frame-v1','parent_render_sha256':old_sha,
                                'parent_plan_sha256':old_plan_sha}
    if selected.get('mask_application_clock'):
        selected['mask_application_clock']['final_render_sha256']=sha256_file(preview)
    path=folder/'timeline.json';_atomic_json(path,selected)
    draft=studio._process(state,job,'portable-draft',{'plan':selected})
    clean=studio._process(state,job,'caption-preview',{'plan':selected})
    return {'plan_path':str(path),'preview_path':str(preview),'cover_path':result['cover_path'],
            'portable_draft_path':draft['portable_draft_path'],'duration':proof['duration'],
            'review_count':len(selected['beats']),**{k:clean[k] for k in ('clean_preview_path',) if k in clean},
            'cover_revision':selected['cover_revision']}
