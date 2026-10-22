"""Render new title previews through the separate renderer; preserve tasks."""
import copy
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    folder=ROOT/'data/feedback-title-voice-20261016'
    proposals=json.loads((folder/'thumbnail-proposals.json').read_text('utf-8'))['result']['products']
    renderer=ROOT.parent/'auto_capcut'
    records=[]
    with closing(sqlite3.connect((ROOT/'data/studio/studio.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)) as db:
        for proposal in proposals:
            code=proposal['shortcode']
            state=json.loads(db.execute("SELECT state FROM tasks WHERE json_extract(state,'$.shortcode')=?",(code,)).fetchone()[0])
            edit=next(e for e in state['edits'] if e['id']==state['edit_id'])
            path=Path(edit['plan_path'])
            if code=='Dec8wlLhu9N':
                path=ROOT/'data/padding-quality-implementation-20261015/verified-export/timeline.json'
            plan=copy.deepcopy(json.loads(path.read_text('utf-8')))
            old=plan['cover_spec']['lines']
            selected=proposal['options'][proposal['selected_index']]
            plan['cover_spec']['lines']=selected['lines']
            plan['cover_spec'].pop('copy_review',None)
            target=folder/code
            target.mkdir(exist_ok=True)
            request=target/'cover-request.json';result=target/'cover-result.json'
            if not request.exists():
                request.write_text(json.dumps({'action':'cover-preview','plan':plan,'output_dir':str(target)},ensure_ascii=False),'utf-8')
            subprocess.run([str(renderer/'.venv/Scripts/python.exe'),'-X','utf8','-m','auto_capcut.studio_runner',
                '--request',str(request),'--result',str(result)],cwd=renderer,check=True)
            receipt=json.loads(result.read_text('utf-8'))
            assert receipt['status']=='completed',receipt
            records.append({'shortcode':code,'before_lines':old,'after_lines':selected['lines'],
                'cover_path':receipt['cover_path'],'source_plan':str(path),'task_changed':False})
    (folder/'rendered-covers.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(records,ensure_ascii=False))


if __name__=='__main__':main()
