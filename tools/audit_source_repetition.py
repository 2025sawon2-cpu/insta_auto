"""Read-only source funnel/timeline audit and evenly timed reference contact sheets."""
import collections
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/source-quality-rework-20261010'


def union_seconds(spans):
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return sum(end-start for start, end in merged)


def sheet(video, output, count=20):
    from hotpost.source_finder import probe_video
    duration = probe_video(video)['duration']
    folder = output.parent / output.stem
    folder.mkdir(exist_ok=True)
    canvas = Image.new('RGB', (5*192, ((count+4)//5)*370), '#202020')
    draw = ImageDraw.Draw(canvas)
    timestamps = []
    for index in range(count):
        timestamp = (index+.5)*duration/count
        frame = folder / f'{index:02d}-{timestamp:.3f}.jpg'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',str(timestamp),
                        '-i',str(video),'-frames:v','1','-vf','scale=180:320:force_original_aspect_ratio=decrease',
                        str(frame)],check=True,capture_output=True)
        with Image.open(frame) as image:
            x,y = (index%5)*192, (index//5)*370
            canvas.paste(image,(x+(192-image.width)//2,y+22))
            draw.text((x+8,y+4),f'{index+1:02d} | {timestamp:.2f}s',fill='white')
        timestamps.append({'index':index+1,'timestamp':timestamp,'path':str(frame)})
    canvas.save(output)
    return timestamps


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if not shutil.which('ffmpeg'):
        bins=list(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
        if bins:os.environ['PATH']=str(bins[0])+os.pathsep+os.environ['PATH']
    with urllib.request.urlopen('http://127.0.0.1:8775/api/studio') as response:
        tasks=json.load(response)['tasks']
    summaries=[]
    for task in tasks:
        code=task['shortcode'];folder=OUT/code;folder.mkdir(exist_ok=True)
        (folder/'baseline-state.json').write_text(json.dumps(task,ensure_ascii=False,indent=2),'utf-8')
        plan=json.loads(Path(task['edits'][-1]['plan_path']).read_text('utf-8'))
        shots={s['id']:s for s in plan['shots']};uses=collections.defaultdict(list);screen=collections.Counter()
        for beat in plan['beats']:
            shot=shots[beat['selected_shot_id']];key=shot['sha256']
            uses[key].append((beat['source_start'],beat['source_end']))
            screen[key]+=beat['end']-beat['start']
        used_seconds=sum(screen.values());unique_seconds=sum(union_seconds(rows) for rows in uses.values())
        manifests=[]
        for path in (ROOT/'data/source_jobs').glob(code+'-*/manifest.json'):
            manifest=json.loads(path.read_text('utf-8'));manifests.append(manifest)
        candidates=[c for m in manifests for c in m.get('candidates',[])]
        searches=[q for m in manifests for q in m.get('search_audit',[])]
        reasons=collections.Counter(reason for c in candidates for reason in c.get('rejection_reasons',[]))
        review_rows=[]
        for source in task['sources']:
            function=source.get('functional_review') or {};portrait=source.get('presentation_review') or {}
            review_rows.append({'id':source['id'],'path':source['path'],'origin_url':source.get('origin_url'),
                'eligible':source.get('editing_eligible',False),'role':source.get('source_role'),
                'core':function.get('same_core_function'),'context':function.get('context_usable'),
                'reason':function.get('reason'),'portrait_reason':portrait.get('reason'),
                'overlay_error':source.get('overlay_review_error'),'portrait_error':source.get('presentation_review_error'),
                'reviewed_intervals':source.get('reviewed_intervals'),
                'unreviewed':source.get('relevance_review_required',False)})
        summary={'shortcode':code,'task_id':task['id'],'candidates':len(candidates),
            'download_attempts':sum(bool(c.get('download_attempted')) for c in candidates),
            'downloaded':sum(bool(c.get('downloaded_file')) for c in candidates),
            'task_sources':len(task['sources']),'eligible':sum(bool(s.get('editing_eligible')) for s in task['sources']),
            'actually_used_files':len(uses),'timeline_seconds':round(used_seconds,3),
            'unique_source_seconds':round(unique_seconds,3),'replayed_seconds':round(used_seconds-unique_seconds,3),
            'largest_source_share':round(max(screen.values())/used_seconds,3),
            'rejection_reasons':dict(reasons),'search_states':dict(collections.Counter((q.get('provider','')+' / '+q.get('status','')) for q in searches)),
            'source_reviews':review_rows,'searches':searches,'candidates_detail':candidates,
            'reference_samples':sheet(Path(task['reference_video']),folder/'reference-20.jpg'),
            'final_samples':sheet(Path(task['edits'][-1].get('export_path') or task['edits'][-1]['preview_path']),folder/'baseline-final-20.jpg')}
        (folder/'baseline-audit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),'utf-8')
        summaries.append({k:v for k,v in summary.items() if k not in ('source_reviews','searches','candidates_detail','reference_samples','final_samples')})
    (OUT/'baseline-summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(summaries,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
