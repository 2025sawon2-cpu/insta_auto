"""Preserve current dirty code and local production before interval improvements."""
import hashlib,json,sqlite3,subprocess,zipfile
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'data/interval-improvement-20261017'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
OUT.mkdir(parents=True,exist_ok=True)
assert not (OUT/'baseline.json').exists()
with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
    rows=db.execute('SELECT id,state FROM tasks').fetchall()
    with sqlite3.connect(OUT/'studio-before.sqlite3') as backup:db.backup(backup)
tasks={key:hashlib.sha256(raw.encode()).hexdigest() for key,raw in rows}
finals={str(path):sha(path) for path in (ROOT/'data/studio').glob('**/*.mp4')}
source_files={}
for key,raw in rows:
    state=json.loads(raw)
    for item in [*state.get('sources',[]),{'path':state.get('reference_video')}]:
        path=Path(item.get('path') or '__missing__')
        if path.is_file():source_files[str(path)]=sha(path)
with zipfile.ZipFile(OUT/'source-before.zip','w',zipfile.ZIP_DEFLATED) as z:
    for repo in [ROOT,ROOT.parent/'auto_capcut',ROOT.parent/'VoiceBench']:
        for directory in ['hotpost','auto_capcut','voicebench','tests','tools','web']:
            folder=repo/directory
            for path in folder.rglob('*') if folder.is_dir() else []:
                if path.is_file() and path.suffix in {'.py','.js','.cjs','.html','.md'} and '__pycache__' not in path.parts:
                    z.write(path,repo.name+'/'+str(path.relative_to(repo)).replace('\\','/'))
        for name,args in [('status',['status','--short']),('diff',['diff','--binary'])]:
            result=subprocess.run(['git',*args],cwd=repo,capture_output=True,check=True)
            (OUT/(repo.name+'-'+name+'-before.txt')).write_bytes(result.stdout)
value={'at':datetime.now().astimezone().isoformat(),'tasks':tasks,'finals':finals,'sources':source_files,'config':{str(ROOT/'config.json'):sha(ROOT/'config.json')},'preserved_files':{'mp4':len(finals),'source_reference':len(source_files)}}
(OUT/'baseline.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf8')
print(json.dumps({'at':value['at'],'tasks':len(tasks),**value['preserved_files']},ensure_ascii=False))
