"""Use the real daily reviewer on new feedback renders in an isolated store."""
import argparse,copy,json
from dataclasses import replace
from pathlib import Path
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.daily_quality import POLICY
from hotpost.editing_adapter import _atomic_json

ROOT=Path('data/user-feedback-revisions-20261011').resolve()

def main():
    p=argparse.ArgumentParser();p.add_argument('code');p.add_argument('--version',default='final');args=p.parse_args();code=args.code
    baseline=json.loads(Path('data/user-feedback-20261011-v1',code+'-baseline.json').read_text('utf-8'))
    settings=load_settings();original=Studio(settings,workers=False).store.get(baseline['task_id'])
    final=ROOT/code/args.version;result=json.loads((final/'render-result.json').read_text('utf-8'))
    plan=json.loads((final/'timeline.json').read_text('utf-8'))
    studio=Studio(replace(settings,data_dir=ROOT/'review-store',studio_auto_top_enabled=False),workers=False)
    task,_=studio.store.create(code,'피드백 실제 완성본 검토',prepare=False)
    edit={**result,'id':'feedback-20261011-'+code+'-'+args.version,'portable_draft_path':result['portable_draft_path'],
        'export_path':result['preview_path'],'script_id':plan['voice']['script_id'],
        'voice_id':plan['voice']['id'],'status':'completed'}
    def setup(s,db):
        s.update(reference_video=original['reference_video'],original_text=original['original_text'],
            reviewed_original_text=original.get('reviewed_original_text',original['original_text']),
            benchmark_analysis=original.get('benchmark_analysis',{}),edits=[edit],edit_id=edit['id'],
            daily_quality={'policy':POLICY,'status':'pending','max_repairs':3,'repair_round':0,'reviews':[]},
            automation={'active':False,'protocol':2})
    state=studio.store.change(task['id'],setup)
    job={'id':'actual-review-'+code+'-'+args.version,'kind':'quality_review','payload':{'edit_id':edit['id']}}
    report=studio._quality_review(state,job)
    _atomic_json(final/'daily-review.json',report)
    if report['passed']:
        from hotpost.studio_workflow import snapshot
        def ready(s,db):
            script={'id':plan['voice']['script_id'],'text':plan['script_text'],
                'sha256':plan['voice']['script_sha256'],'status':'completed'}
            voice=copy.deepcopy(plan['voice'])
            s.update(scripts=[script],script_id=script['id'],approved_script_id=script['id'],
                voices=[voice],voice_id=voice['id'],approved_voice_id=voice['id'],
                script_candidates=[{'text':script['text'],'thumbnail_lines':plan['cover_spec']['lines']}],
                sources=copy.deepcopy(plan['sources']),automation={'active':True,'protocol':2,
                    'selection_mode':'manual','finish_selected_batch':True,'stage':'quality_review'})
            snapshot(s)
            studio.store.enqueue(db,s['id'],'quality_review',{'edit_id':edit['id']},
                key='feedback-verified-'+code+'-'+args.version)
        studio.store.change(task['id'],ready)
        queued=studio.store.claim(task_id=task['id'])
        assert queued['kind']=='quality_review'
        studio.store.finish(queued,report,lambda s,db,r:studio._accept(s,queued,r,db))
        completed=studio.store.get(task['id'])
        assert completed['status']=='completed',completed['status']
        _atomic_json(final/'real-workflow-completion.json',{'status':completed['status'],
            'job_kind':queued['kind'],'task_id':task['id'],'quality_verified':completed['edits'][0]['quality_verified']})
    print(json.dumps({'code':code,'passed':report['passed'],'issues':report['issues'],'metrics':report['metrics'],
        'audio':report['audio_timing_audit']['passed']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
