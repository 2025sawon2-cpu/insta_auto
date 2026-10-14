"""Acquire an explicitly identified public vendor clip and run normal reviews."""
import argparse
import hashlib
import json
import os
import subprocess
import shutil
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.request_pacing import request_pause
from hotpost.source_finder import probe_video, extract_frames, download_candidate, Candidate
from hotpost.source_quality import sha256_file
from hotpost.studio_sources import source_goal, unique_sources
from hotpost.text_overlay import TextOverlayDetector


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--task',required=True)
    parser.add_argument('--origin',required=True)
    parser.add_argument('--media',required=True)
    parser.add_argument('--start',type=float)
    parser.add_argument('--duration',type=float)
    parser.add_argument('--replace-origin',action='store_true',help='Replace an unused pre-edit record after reviewing a more specific interval')
    args=parser.parse_args()
    if urlsplit(args.media).scheme!='https': raise ValueError('HTTPS media required')
    root=Path('data/selected-four-research')/('clip-'+hashlib.sha256(args.media.encode()).hexdigest()[:12])
    root.mkdir(parents=True,exist_ok=True)
    raw=root/('download.gif' if '.gif' in urlsplit(args.media).path else 'download.mp4')
    settings=load_settings()
    ffmpeg=list(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    if ffmpeg:os.environ['PATH']=str(ffmpeg[0])+os.pathsep+os.environ['PATH']
    if not raw.is_file():
        host=urlsplit(args.media).hostname
        if host in {'www.youtube.com','youtube.com','youtu.be','www.lazada.com.ph','www.lazada.com.my'}:
            videos=root/'videos';videos.mkdir(exist_ok=True)
            candidate=Candidate(args.media,'vendor' if 'lazada' in host else 'youtube',original_url=args.origin)
            downloaded=download_candidate(candidate,videos,1,settings.source_max_file_mb,
                cookie_file=settings.source_browser_cookie_file,js_runtime=settings.source_ytdlp_js_runtime)
            if not downloaded:raise RuntimeError(candidate.error)
            shutil.copy2(downloaded,raw)
    if not raw.is_file():
        request_pause()
        with requests.get(args.media,timeout=45,stream=True) as response:
            response.raise_for_status()
            size=0
            with raw.open('wb') as file:
                for chunk in response.iter_content(256*1024):
                    size+=len(chunk)
                    if size>100*1024*1024: raise ValueError('Source exceeds size limit')
                    file.write(chunk)
    path=raw
    if raw.suffix=='.gif':
        path=root/'converted.mp4'
        if not path.is_file():
            subprocess.run(['ffmpeg','-y','-i',str(raw),'-vf','scale=trunc(iw/2)*2:trunc(ih/2)*2',
                '-pix_fmt','yuv420p','-movflags','+faststart',str(path)],check=True,capture_output=True,timeout=120)
    original_meta=probe_video(path)
    interval=None
    if args.start is not None:
        if args.start<0 or not args.duration or args.duration<4 or args.start+args.duration>(original_meta.get('duration') or 0):
            raise ValueError('Invalid source interval')
        clipped=root/f'interval-{args.start:g}-{args.duration:g}.mp4'
        subprocess.run(['ffmpeg','-y','-ss',str(args.start),'-i',str(path),'-t',str(args.duration),
            '-c:v','libx264','-pix_fmt','yuv420p','-an','-movflags','+faststart',str(clipped)],
            check=True,capture_output=True,timeout=120)
        interval={'source_start':args.start,'source_end':args.start+args.duration,
            'original_path':str(path.resolve()),'original_sha256':sha256_file(path),'original_meta':original_meta}
        path=clipped
    studio=Studio(settings,workers=False)
    meta=probe_video(path)
    print('Downloaded',meta,flush=True)
    if not 4<=(meta.get('duration') or 0)<=180:raise ValueError('Source duration is outside normal usable range')
    frames=extract_frames(path,root/'frames',max_frames=6)
    overlay=TextOverlayDetector(settings).analyze(frames)
    source={'id':'source-'+sha256_file(path)[:16],'path':str(path.resolve()),'sha256':sha256_file(path),
        'origin_url':args.origin,'media_origin_url':args.media,'rights':'unknown-check-before-reuse',
        'video_meta':meta,'source_quality':overlay['source_quality'],'relevance_review_required':True,
        'editing_eligible':False,'presentation_review_required':True,'acquisition':'public_vendor_supplement',
        'raw_path':str(raw.resolve()),'overlay_detection':overlay}
    if interval:source['source_interval']=interval
    manifest=root/'manifest.json'
    manifest.write_text(json.dumps({'caption':args.origin,'candidates':[{
        **source,'file_sha256':source['sha256'],'downloaded_file':path.name,'original_url':args.origin,
        'url':args.media,'selected_for_zip':True}]},ensure_ascii=False,indent=2),'utf-8')
    source['manifest_path']=str(manifest.resolve())
    state=studio.store.get(args.task)
    def progress(message,pct):print(message,pct,flush=True)
    reviewed,_=studio._review_source_records(state,{'id':'vendor-'+source['sha256'][:12],'kind':'refresh_sources'},[source],progress)
    def accept(state,db):
        if args.replace_origin:
            if state['edits'] or not reviewed[0].get('editing_eligible'):
                raise ValueError('Replacement requires an eligible review and no existing edits')
            state['sources']=[s for s in state['sources'] if s.get('origin_url')!=args.origin]
        state['sources']=unique_sources([*state['sources'],*reviewed])
        studio.store.event(db,state['id'],'supplemental_source_reviewed',{
            'origin_url':args.origin,'sha256':source['sha256'],'eligible':reviewed[0].get('editing_eligible')})
        studio.advance_workflow(state,db)
    result=studio.store.change(args.task,accept)
    print('Task coverage',json.dumps(source_goal(result),ensure_ascii=False),flush=True)
    (root/'reviewed.json').write_text(json.dumps(reviewed,ensure_ascii=False,indent=2),'utf-8')


if __name__=='__main__':main()
