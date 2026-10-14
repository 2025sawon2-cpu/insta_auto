"""Explicit, bounded source research for the two retained references; no queue/automation."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from hotpost.config import load_settings
from hotpost.request_pacing import request_pause, ytdlp_pacing_args
from hotpost.source_finder import Candidate, download_candidate, probe_video, _executable, _yt_runtime_args
from tools.audit_source_repetition import OUT, sheet

QUERIES = {
    'DeNb4AsSgGw': [
        'DIY photo fridge magnets magnetic sheets',
        'self adhesive magnetic sheets photo magnets tutorial',
        '사진 자석 만들기 마그넷 시트',
        '照片冰箱贴制作 软磁',
        '照片冰箱贴 亚克力 自制',
        'turn kids drawings into fridge magnets',
        'DIY shrink plastic magnets kids drawings',
        '사진 냉장고 자석 만들기 다이소 자석',
    ],
    'DeOhQMSzm5N': [
        'Scotch macaron tape dispenser',
        '스카치 마카롱 디스펜서 다이소',
        '3M 馬卡龍 膠台',
        'Scotch magic tape kitchen food labels',
        'label food containers masking tape freezer',
        'write on Scotch magic tape dispenser refill',
        'Scotch เทป มาการอง รีวิว',
        'Scotch magic tape remove label container demonstration',
        'Scotch removable tape peel clean removal demo',
    ],
}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['search','download','sheets'])
    parser.add_argument('--code',choices=list(QUERIES));args=parser.parse_args()
    bins=list(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    if bins:os.environ['PATH']=str(bins[0])+os.pathsep+os.environ['PATH']
    settings=load_settings();runtime='node:'+shutil.which('node') if shutil.which('node') else ''
    for code in ([args.code] if args.code else QUERIES):
        root=OUT/code/'research';root.mkdir(parents=True,exist_ok=True)
        ledger=root/'discovery.json'
        data=json.loads(ledger.read_text('utf-8')) if ledger.is_file() else {'queries':[],'candidates':[]}
        if args.phase=='search':
            tried={r['query'] for r in data['queries']};seen={r['url'] for r in data['candidates']}
            for query in QUERIES[code]:
                if query in tried:continue
                request_pause()
                start=time.monotonic()
                try:
                    result=subprocess.run([_executable('yt-dlp'),*ytdlp_pacing_args(),*_yt_runtime_args(runtime),
                        '--flat-playlist','--dump-single-json','--no-warnings',f'ytsearch6:{query}'],
                        capture_output=True,text=True,encoding='utf-8',timeout=90)
                    entries=json.loads(result.stdout).get('entries') or []
                    for entry in entries:
                        url=entry.get('webpage_url') or entry.get('url')
                        if not url or not url.startswith('http'):url='https://www.youtube.com/watch?v='+entry['id']
                        if url in seen:continue
                        seen.add(url);data['candidates'].append({'url':url,'provider':'youtube','query':query,
                            'title':entry.get('title',''),'duration':entry.get('duration'),'selected':False})
                    row={'query':query,'count':len(entries),'seconds':round(time.monotonic()-start,2),'status':'results' if entries else 'no_results'}
                except Exception as exc:
                    row={'query':query,'count':0,'status':'error','error':str(exc)[:200]}
                data['queries'].append(row)
                ledger.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8')
                print(code,json.dumps(row,ensure_ascii=False),flush=True)
        elif args.phase=='download':
            for index,row in enumerate(data['candidates'],1):
                if not row.get('selected') or row.get('path') or row.get('download_error'):continue
                video_dir=root/'videos';video_dir.mkdir(exist_ok=True)
                candidate=Candidate(row['url'],row['provider'],title=row['title'],query=row['query'])
                path=download_candidate(candidate,video_dir,index,150,js_runtime=runtime,deadline=time.monotonic()+110)
                row.update(download_attempted=True)
                if path:row.update(path=str(path.resolve()),meta=probe_video(path),title=candidate.title)
                else:row['download_error']=candidate.error
                ledger.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8')
                print(code,index,row['title'],'downloaded' if path else row['download_error'][-150:],flush=True)
        else:
            for index,row in enumerate(data['candidates'],1):
                if not row.get('path'):continue
                target=root/f'candidate-{index:02d}.jpg'
                if target.is_file():continue
                row['samples']=sheet(Path(row['path']),target,count=15)
                print(code,index,'sheet',flush=True)


if __name__=='__main__':main()
