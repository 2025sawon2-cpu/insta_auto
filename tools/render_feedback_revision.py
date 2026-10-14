"""Create a new render through the separate editor; no existing result mutation."""
import argparse,json,subprocess
from pathlib import Path
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json

BASE=Path('data/user-feedback-20261011-v1').resolve()
ROOT=Path('data/user-feedback-revisions-20261011').resolve()

def main():
    p=argparse.ArgumentParser();p.add_argument('code');p.add_argument('--version',default='final');args=p.parse_args()
    base=json.loads((BASE/(args.code+'-baseline.json')).read_text('utf-8'))
    output=ROOT/args.code/args.version;output.mkdir(parents=True,exist_ok=True)
    request=output/'render-request.json';result=output/'render-result.json'
    if result.exists():
        prior=json.loads(result.read_text('utf-8'))
        if prior.get('status')!='failed':raise RuntimeError('Keep existing revision; choose a new version')
        import time
        result.rename(output/f'render-failed-{time.time_ns()}.json')
    if args.version!='final' and not (output/'prepared-plan.json').is_file():raise ValueError('New revision requires its own reviewed prepared plan')
    plan=json.loads((output/'prepared-plan.json').read_text('utf-8')) if (output/'prepared-plan.json').exists() else base['plan']
    for key in ('rendered_clips','cover_path','sfx_path','output_dir'):plan.pop(key,None)
    _atomic_json(request,{'action':'render','output_dir':str(output),'plan':plan,
        'quality_revision':'user-feedback-20261011-'+args.code})
    settings=load_settings()
    with (output/'render.log').open('w',encoding='utf-8') as log:
        subprocess.run([str(settings.auto_capcut_python),'-X','utf8','-m','auto_capcut.studio_runner',
            '--request',str(request),'--result',str(result)],cwd=settings.auto_capcut_root,
            stdout=log,stderr=log,check=True)
    value=json.loads(result.read_text('utf-8'));assert value['status']=='completed'
    print(json.dumps(value,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
