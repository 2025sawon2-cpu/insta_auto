"""Attach only actual reviewed feedback revisions; keep every earlier run."""
import argparse,copy,json,time
from pathlib import Path
from PIL import Image
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.studio_workflow import init_run,snapshot
from hotpost.editing_adapter import _atomic_json
from hotpost.source_quality import sha256_file
from hotpost.source_finder import probe_video
from tools.report_seven_revision_changes import summary

ROOT=Path('data/user-feedback-revisions-20261011').resolve()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('code');parser.add_argument('--version',default='final');args=parser.parse_args()
    code=args.code;out=ROOT/code/args.version
    baseline=json.loads(Path('data/user-feedback-20261011-v1',code+'-baseline.json').read_text('utf-8'))
    report=json.loads((out/'daily-review.json').read_text('utf-8'))
    result=json.loads((out/'render-result.json').read_text('utf-8'));plan=json.loads((out/'timeline.json').read_text('utf-8'))
    assert report['passed'] and report['audio_timing_audit']['passed']
    assert sha256_file(Path(result['preview_path']))==report['render_sha256']
    metrics=summary(out/'timeline.json');_atomic_json(out/'verification.json',{
        'actual_visual_review':True,'visual_review_pending':False,'metadata':probe_video(Path(result['preview_path'])),
        'metrics':{'independent_original_videos':metrics['parent_files'],'action_clips':metrics['action_clips'],
            'replayed_seconds':metrics['repeated_source_seconds'],'largest_source_share':metrics['largest_source_share']},
        'audio_timing_audit':report['audio_timing_audit'],'auditory_naturalness_reviewed':False,
        'render_sha256':report['render_sha256'],'quality_review_path':report['review_path']})
    Image.open(out/'cover.png').convert('RGB').save(out/'comparison-poster.jpg',quality=95)
    studio=Studio(load_settings(),workers=False);current=studio.store.get(baseline['task_id'])
    editid='feedback-20261011-'+code+'-'+args.version
    if any(e['id']==editid for e in current['edits']):return
    assert current['edit_id']==baseline['edit']['id']
    edit={**result,'id':editid,'status':'completed','created':time.time(),
        'script_id':plan['voice']['script_id'],'voice_id':plan['voice']['id'],
        'export_path':result['preview_path'],'export_verified':True,'export_kind':'web_render',
        'review_draft':True,'registration_deferred':True,'quality_verified':True,
        'quality_review_path':report['review_path'],'previous_edit_id':current['edit_id']}
    def update(s,db):
        if code in {'DeJ7hD6zsnR','DeSvpmAsWgZ'}:
            script=json.loads((ROOT/code/'final/script.json').read_text('utf-8'))
            s['scripts'].append(script);s['voices'].append(copy.deepcopy(plan['voice']))
            s.update(script_id=script['id'],approved_script_id=script['id'],voice_id=plan['voice']['id'],
                approved_voice_id=plan['voice']['id'],quality_revision_path=str(ROOT/code/'writing/quality.json'))
            q=json.loads((ROOT/code/'writing/quality.json').read_text('utf-8'));s['script_candidates']=copy.deepcopy(q['scripts'])
        merged={v['id']:v for v in s['sources']};merged.update({v['id']:copy.deepcopy(v) for v in plan['sources']})
        s['sources']=list(merged.values());s['edits'].append(edit)
        s.update(edit_id=editid,status='draft_review',progress=100,error='',message='피드백 수정본 · 실제 장면 및 출력 음성 시간 검토 통과')
        s.setdefault('automation',{}).update(active=False)
        parent=s.pop('run_id',None);run=init_run(s)
        if parent:run['parent_id']=parent
        snapshot(s);used={b['selected_shot_id'] for b in plan['beats']}
        ids={h['source_id'] for h in plan['shots'] if h['id'] in used}
        run['inputs']['source_ids']=list(ids);run['artifacts']['sources']=[copy.deepcopy(v) for v in plan['sources'] if v['id'] in ids]
        run.update(status='review',quality_draft=True)
        studio.store.event(db,s['id'],'user_feedback_revision',{'edit_id':editid,'previous_edit_id':current['edit_id']})
    saved=studio.store.change(current['id'],update)
    assert all(next(r for r in saved['runs'] if r['id']==old['id'])==old for old in current['runs'])
    _atomic_json(out/'attachment.json',{'task_id':current['id'],'edit_id':editid,'run_id':saved['run_id'],
        'prior_runs_unchanged':True,'summary':metrics})
    print(code,'attached',json.dumps({k:metrics[k] for k in ['parent_files','tiktok_used_files','largest_source_share','repeated_source_seconds']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
