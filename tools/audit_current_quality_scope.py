"""Current-state inventory and exact file checks for all seven selected outputs."""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json as save
from hotpost.source_quality import sha256_file
from hotpost.source_coverage import coverage_goal
from hotpost.source_policy import current_policy
from hotpost.studio import Studio
from tools.build_source_rework import metrics

OUT=Path('data/quality-scope-audit-20261011-v1').resolve()
PRIOR=Path('data/source-quality-progress-20261011-folder-phone-v8.json')
def read(p):return json.loads(Path(p).read_text('utf-8'))

def inventory():
    OUT.mkdir(exist_ok=True)
    if (OUT/'inventory.json').exists():raise RuntimeError('Prior audit preserved; use a new audit version.')
    studio=Studio(load_settings(),workers=False);rows=[]
    font=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf',15)
    sheet=Image.new('RGB',(864,3*422),'#171b27');draw=ImageDraw.Draw(sheet)
    for i,row in enumerate(read(PRIOR)['scope_current_state_audit']):
        state=studio.store.get(row['task_id']);edit=next(e for e in state['edits'] if e['id']==state['edit_id'])
        final=Path(edit['plan_path']).parent;plan=read(edit['plan_path'])
        quality=Path(state['quality_revision_path']) if state.get('quality_revision_path') else final.parent/'writing/quality-v3.json'
        writing=read(quality)
        script=next(s for s in state['scripts'] if s['id']==state['script_id'])
        assert plan['script_text']==script['text']
        assert len(writing['scripts'])==3
        assert any(s['text']==script['text'] for s in writing['scripts'])
        used={b['selected_shot_id'] for b in plan['beats']};source_ids={s['source_id'] for s in plan['shots'] if s['id'] in used}
        sources=[s for s in plan['sources'] if s['id'] in source_ids]
        source_files=[]
        for s in sources:
            assert sha256_file(Path(s['path']))==s['sha256']
            original=Path(s.get('original_path') or s['path'])
            digest=s.get('original_sha256') or s['sha256']
            assert sha256_file(original)==digest
            assert s.get('editing_eligible') and (s.get('functional_review') or {}).get('reviewed')
            source_files.append({'id':s['id'],'path':s['path'],'sha256':s['sha256'],
                'original_path':str(original),'original_sha256':digest,'url':s.get('url'),
                'functional_review':s['functional_review'],'presentation_review':s.get('presentation_review')})
        audit=metrics(plan);assert abs(audit['replayed_seconds'])<.08
        voice=plan['voice'];assert sha256_file(Path(voice['path']))==voice['sha256']
        assert hashlib.sha256(script['text'].encode()).hexdigest()==voice['script_sha256']
        qa=read(final/'verification.json')
        public_path=final/'public-file-verification.json'
        if not public_path.exists():public_path=final/'public-verification.json'
        public=read(public_path);browser=read(final/'browser-verification.json')
        digest=sha256_file(final/'preview.mp4')
        assert (public.get('public_sha256') or public.get('full_public_sha256') or public.get('public_full_sha256') or public.get('sha256'))==digest, (row['code'],public)
        cover=Image.open(final/'cover.png').convert('RGB');cover.thumbnail((216,384))
        x=(i%4)*216;y=(i//4)*422;sheet.paste(cover,(x,y+34));draw.text((x+4,y+3),row['code'],font=font,fill='white')
        data={'code':row['code'],'task_id':state['id'],'edit_id':edit['id'],'status':state['status'],
            'plan_path':edit['plan_path'],'render_path':str(final/'preview.mp4'),'render_sha256':digest,
            'writing_path':str(quality),'writing_sha256':sha256_file(quality),'selected_number':next(s['number'] for s in writing['scripts'] if s['text']==script['text']),
            'script_sha256':hashlib.sha256(script['text'].encode()).hexdigest(),
            'cover_lines':plan['cover_spec']['lines'],'cover_path':str(final/'cover.png'),'qa':qa,
            'public':public,'browser':browser,'source_files':source_files,'metrics':audit,
            'coverage_policy':coverage_goal(plan['sources'],{'voices':[voice],'voice_id':voice['id'],'script_id':voice['script_id']},current_policy(load_settings())),
            'declared_coverage':edit.get('source_coverage_complete')}
        save(OUT/(row['code']+'-inventory.json'),data);rows.append(data)
        print(row['code'],state['edit_id'],'writing',quality,flush=True)
    sheet.crop((0,0,864,2*422)).save(OUT/'all-seven-covers.jpg',quality=95)
    save(OUT/'inventory.json',{'full_scope':read(PRIOR)['full_scope'],'rows':rows,'manual_editorial_review_pending':True})

def decode():
    bins=next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    ffmpeg=bins/'ffmpeg.exe';rows=read(OUT/'inventory.json')['rows'];seen=set();results=[]
    for row in rows:
        paths=[(row['render_path'],row['render_sha256'],'render')]
        paths += [(s['original_path'],s['original_sha256'],'received_original') for s in row['source_files']]
        for path,digest,kind in paths:
            if digest in seen:continue
            seen.add(digest)
            assert sha256_file(Path(path))==digest
            result=subprocess.run([str(ffmpeg),'-v','error','-xerror','-i',path,'-f','null','-'],capture_output=True,timeout=240)
            results.append({'path':path,'sha256':digest,'kind':kind,'exit_code':result.returncode,
                'decode_passed':result.returncode==0,'stderr':result.stderr.decode('utf-8','replace')[-400:]})
            save(OUT/'whole-decode.json',results)
            if result.returncode:raise RuntimeError('Whole-file decode failed; inspect recorded result.')
        print(row['code'],'current render and all used parent files decoded',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['inventory','decode']);args=p.parse_args();globals()[args.phase]()
