"""Persist current evidence without declaring the 18-item goal complete."""
import json,time
from pathlib import Path
from collections import Counter
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.source_quality import sha256_file
from hotpost.editing_adapter import _atomic_json
ROOT=Path('data/source-recovery-20261012-v1').resolve()

def main():
    studio=Studio(load_settings(),workers=False)
    tasks=sorted([t for t in studio.store.list() if t.get('automation',{}).get('selection_date_kst')=='2026-10-12'],key=lambda t:t['automation']['rank'])
    assert len(tasks)==18
    raw=[]
    for file in ROOT.glob('*/ledger.json'):
        ledger=json.loads(file.read_text('utf-8'))
        for i,v in enumerate(ledger['candidates']):
            if v.get('full_decode_passed'):raw.append({'code':file.parent.name,'index':i,'sha256':v['sha256'],'url':v['url']})
    table=next(t for t in tasks if t['shortcode']=='DeVUQRZqKRM')
    e=next(e for e in table['edits'] if e['id']==table['edit_id'])
    assert e['id']=='job-c7acab44b8c349bb' and e.get('quality_verified')
    qa=json.loads(Path(e['quality_review_path']).read_text('utf-8'))
    assert qa['passed'] and qa['render_sha256']==sha256_file(Path(e['preview_path']))
    evidence=[Path(e['quality_review_path']).parent/'actual-first-frame.jpg',
        Path(e['quality_review_path']).parent/'whole-video-overview.jpg',
        ROOT/table['shortcode']/'render-job-c7acab44b8c349bb-dense-3-8/contact.jpg']
    _atomic_json(ROOT/table['shortcode']/'manual-render-review.json',{'at':time.time(),'edit_id':e['id'],
        'render_sha256':qa['render_sha256'],'actual_images_viewed':[{'path':str(p),'sha256':sha256_file(p)} for p in evidence],
        'observations':['First-frame thumbnail contains no human face, including the background; the two hook lines remain legible.',
            'Dense final-render frames show the box rolling on wheels while pulled by the handle, removal of stored folded legs, and deployment of legs.',
            'Whole-render overview includes stored-box handling, wheels/handle, underside legs, and outdoor table use from three parent files.'],
        'audio_timing_passed':qa['audio_timing_audit']['passed'],'auditory_naturalness_reviewed':False,
        'metrics':qa['metrics'],'scope':'This item only; remaining 17 are not approved by this record.'})
    causes=json.loads((ROOT/'recovery-cause-audit.json').read_text('utf-8'))
    findings=[
        {'code':'primary_function_only','finding':'A bounded real drying-rack clip was classified as context although this is an explicitly promoted secondary function in the whole reference.',
         'evidence':'DeWFM7RyO0t/feature-recheck-9a81eea1fd560df2.json','fix':'Full-reference overview, original product facts and named matched secondary features; limits retained.'},
        {'code':'sampling_window_missed_action','finding':'Mat raw11 wiping starts about 26.33s and largely falls beyond the old 22.433–26.433 window; raw12 contains clear wiping at 13.33–17s that sparse whole-file sampling did not retain.',
         'evidence':['DeWWWOeDhGk/raw-11-dense-22-30/contact.jpg','DeWWWOeDhGk/raw-12-dense-10-17/contact.jpg'],
         'fix':'Actual wiping trim registered for the ordinary overlay/function/crop reviews; not blanket file approval.'},
        {'code':'semantic_priority_vs_diversity','finding':'Legacy scoring can prefer a new-parent contextual view to an available direct action solely because the direct parent is adjacent. Real mat-plan replay also proves priority alone cannot solve missing/misclassified action samples.',
         'evidence':'semantic-priority-real-plan-audit.json','fix':'Versioned semantic-first selection, preserving legacy version and shortage/replay checks; bounded action review still required.'},
        {'code':'parent_trim_order','finding':'A valid full parent following its focused derivative was removed as a duplicate, discarding distinct reviewed intervals.',
         'fix':'Preserve valid same-parent interval mappings and count unique original parents instead of trims as TikTok originals.'},
        {'code':'cover_body_mask_mismatch','finding':'Body source blur rectangles were reapplied to the thumbnail after new title painting.',
         'fix':'Keep cover source masking before title painting and start body masking after the first frame; actual two-frame regression verified.'},
        {'code':'qa_cross_group_beat_ids','finding':'Reviewer given whole overview reported a real beat outside its detailed subgroup, causing an execution error.',
         'fix':'Provide all known beat IDs while retaining subgroup detail and reject truly nonexistent IDs.'},
    ]
    known={x['code'] for x in causes['causes']}
    causes['causes']=[next((x for x in findings if x['code']==old['code']),old) for old in causes['causes']]
    causes['causes'].extend(x for x in findings if x['code'] not in known)
    causes.update(updated_at=time.time(),status='in_progress; full scope is 18; saved CAPTCHA requires a current existing-page observation, not an assumed human wait')
    _atomic_json(ROOT/'recovery-cause-audit.json',causes)
    rows=[]
    for t in tasks:
        rows.append({'rank':t['automation']['rank'],'code':t['shortcode'],'status':t['status'],
            'completed_render_qa':t['status']=='completed' and t.get('daily_quality',{}).get('status')=='passed',
            'live_jobs':[{k:j[k] for k in ('id','kind','status')} for j in studio.store.jobs(t['id']) if j['status'] in ('running','queued')]})
    from hotpost.search_access import access_record,manual_required
    gate=access_record(studio.settings.data_dir,'tiktok')
    recheck_required=gate.get('reason')=='captcha' and manual_required(gate)
    progress={'updated_at':time.time(),'required_scope':18,'completion':False,'tasks':rows,
        'status_counts':dict(Counter(t['status'] for t in tasks)),'raw_received_and_decoded':len(raw),
        'raw_receipts':raw,'captcha_recheck_required':recheck_required,
        'human_captcha_reply_pending':None if recheck_required else False,
        'latest_saved_captcha_observation':gate.get('last_captcha_check'),
        'approved_items':[r['code'] for r in rows if r['completed_render_qa']]}
    _atomic_json(ROOT/'live-recovery-progress.json',progress)
    print(json.dumps({k:v for k,v in progress.items() if k not in ('tasks','raw_receipts')},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
