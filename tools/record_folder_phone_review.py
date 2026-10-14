"""Verify the published USB-use revision and retain the whole work scope."""
import json
from datetime import datetime
from pathlib import Path
import requests
from hotpost.editing_adapter import _atomic_json as save
from hotpost.request_pacing import request_pause
from hotpost.source_quality import sha256_file
from hotpost.studio import Studio
from hotpost.config import load_settings

ROOT=Path('data/folder-phone-review-20261011-v8/DeSoiZvyyqj')
FINAL=ROOT/'final'

def read(path):return json.loads(Path(path).read_text('utf-8'))

def public():
    receipt=read('data/folder-phone-quality-20261011-v8-share.json')
    base=receipt['url']
    def req(path,**kw):
        request_pause()
        r=requests.get(base+path,timeout=60,**kw);r.raise_for_status();return r
    page=req('/');scripts=read(ROOT/'writing/quality-v9.json')['scripts']
    page_text=page.content.decode('utf-8').replace('\r\n','\n')
    import html
    assert all(html.escape(s['text']).replace('\r\n','\n') in page_text for s in scripts)
    assert '폰 뒤 부착 설명을 폰과 USB 케이블로 연결하는' in page_text
    media='/DeSoiZvyyqj-final.mp4'
    r=req(media);public_sha=__import__('hashlib').sha256(r.content).hexdigest()
    assert public_sha==sha256_file(FINAL/'preview.mp4')
    ranged=req(media,headers={'Range':'bytes=0-15'})
    assert ranged.status_code==206 and len(ranged.content)==16
    request_pause();head=requests.head(base+media+'?download=1',timeout=30)
    assert head.headers['Content-Disposition'].startswith('attachment;')
    save(FINAL/'public-file-verification.json',{
        'url':base,'verified_at':datetime.now().astimezone().isoformat(),
        'public_sha256':public_sha,'local_sha256':sha256_file(FINAL/'preview.mp4'),
        'full_public_bytes':len(r.content),'range_206':True,'attachment_header':True,
        'all_three_current_scripts_present':True,'read_only_api_checks':receipt['verified']})
    print('Public file equals rendered file; range/download and three revised scripts verified.')

def progress():
    prior=Path('data/source-quality-progress-20261011-a7-receipts-v6.json')
    result=read(prior)
    browser=read(FINAL/'browser-verification.json')
    assert browser['final']['ended'] and browser['final']['error'] is None
    result.update(at=datetime.now().timestamp(),previous_progress_receipt=str(prior),
        this_goal_turn_classification='progress: current TikTok CAPTCHA absent, new fully received portrait source, three USB-use corrected scripts, new personal TTS and actual render/public playback',
        full_goal_complete=False)
    result['folder_phone_v8']={'writing':'data/folder-phone-review-20261011-v8/DeSoiZvyyqj/writing/quality-v9.json',
        'editorial':read(ROOT/'writing/editorial-review-v9.json'),
        'new_source':read(ROOT/'source-reception.json'),
        'clips_review':read(FINAL/'clips-reviewed.json'),
        'render_review':read(FINAL/'verification.json'),
        'coverage':read(FINAL/'source-coverage.json'),
        'attachment':read(FINAL/'attachment.json'),
        'share':read('data/folder-phone-quality-20261011-v8-share.json'),
        'public_file':read(FINAL/'public-file-verification.json'),'browser':browser,
        'public_session_id':40065,'previous_edits_and_shares_preserved':True,
        'new_tts_requests':1,'phone_photo_copy_directly_verified':False,
        'phone_mounting_claim_removed':True,'same_sku_added_as_hard_gate':False}
    studio=Studio(load_settings(),workers=False)
    for row in result['scope_current_state_audit']:
        state=studio.store.get(row['task_id'])
        edit=next(e for e in state['edits'] if e['id']==state['edit_id'])
        row.update(status=state['status'],selected_edit=state['edit_id'],
            export_file_exists=Path(edit['export_path']).exists(),
            review_draft=edit.get('review_draft'),source_coverage_complete=edit.get('source_coverage_complete'))
    result['current_tiktok_live_recheck']='data/tiktok-current-recheck/20261011-195103/state.json'
    result['remaining_full_scope']=[
        'Audit all seven selected outputs and script/source/thumbnail provenance together before marking the full goal complete.',
        'A7 functional evidence should be assessed without making exact SKU a hard gate.',
        'Cart source enlargement and promotional-caption softening remain visual limitations.',
        'Separate fish source coating-material identity remains unresolved; no unsupported identity claim added.',
        'Actual audio listening and audience click-rate testing are limitations, not newly imposed completion gates.']
    save(Path('data/source-quality-progress-20261011-folder-phone-v8.json'),result)
    print('Full seven-output scope retained with current folder source/render/share evidence.')

if __name__=='__main__':
    import sys
    globals()[sys.argv[1]]()
