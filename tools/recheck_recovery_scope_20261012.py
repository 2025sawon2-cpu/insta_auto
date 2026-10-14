"""Confirm cross-group findings with existing actual render evidence, read-only."""
import argparse,base64,json,time
from pathlib import Path
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.daily_quality import REVIEW_INSTRUCTION,validate_report
from hotpost.daily_quality_scope import resolve_visual_scope
from hotpost.script_rewriter import _generate
from hotpost.source_quality import sha256_file
from hotpost.editing_adapter import _atomic_json

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--code',required=True);a=p.parse_args()
    studio=Studio(load_settings(),workers=False);state=next(t for t in studio.store.list() if t['shortcode']==a.code)
    record=next(r for r in reversed(state['daily_quality']['reviews']) if r.get('review_path'))
    report_path=Path(record['review_path']);report=json.loads(report_path.read_text('utf-8'))
    edit=next(e for e in state['edits'] if e['id']==report['edit_id']);plan=json.loads(Path(edit['plan_path']).read_text('utf-8'))
    assert sha256_file(Path(edit['preview_path']))==report['render_sha256']
    assert sha256_file(Path(edit['plan_path']))==report['plan_sha256']
    for group in report['groups']:
        for frame in group['frames']:assert sha256_file(Path(frame['path']))==frame['sha256']
    root=report_path.parent;media=[]
    for label,file in [('BODY overview, not the cover','whole-video-overview.jpg'),
        ('Original reference overview','reference-overview.jpg'),('Actual first-frame cover, not body evidence','actual-first-frame.jpg')]:
        media.extend([{'text':label},{'inlineData':{'mimeType':'image/jpeg','data':base64.b64encode((root/file).read_bytes()).decode()}}])
    details=[{**{k:b[k] for k in ('id','text','start','end')},'relation':b.get('relation'),
        'usage_limits':next((s.get('context_usage_limits',[]) for s in plan['shots'] if s['id']==b['selected_shot_id']),[])} for b in plan['beats']]
    evidence={'script':plan['script_text'],'original_text':state.get('reviewed_original_text') or state['original_text'],
        'all_beats':details,'all_beat_details':details,'cover_lines':plan['cover_spec']['lines']}
    issues,audits=resolve_visual_scope(studio.settings,REVIEW_INSTRUCTION,evidence,report['groups'],media,_generate,validate_report)
    target=Path('data/source-recovery-20261012-v1')/a.code/('scope-recheck-'+edit['id']+'.json')
    _atomic_json(target,{'at':time.time(),'edit_id':edit['id'],'render_sha256':report['render_sha256'],
        'original_report_sha256':sha256_file(report_path),'remaining_issues':issues,'confirmations':audits,
        'original_report_unchanged':True,'production_approval_granted':False})
    print(json.dumps({'scope_recheck':str(target),'remaining_issues':issues,'confirmations':[(r['issue']['beat_id'],r['status']) for r in audits]},ensure_ascii=False),flush=True)
