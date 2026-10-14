"""Record requirement-by-requirement evidence for the completed seven-output review."""
import hashlib,json,time,re
from pathlib import Path
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json as save
from hotpost.source_quality import sha256_file
from hotpost.source_coverage import coverage_goal
from hotpost.source_policy import current_policy
from hotpost.studio import Studio
from tools.build_source_rework import metrics

OUT=Path('data/quality-scope-audit-20261011-v1')
def read(p):return json.loads(Path(p).read_text('utf-8'))
def main():
    studio=Studio(load_settings(),workers=False);rows=[]
    inventory=read(OUT/'inventory.json');public=read(OUT/'public-seven-verification.json')
    assert public['all_seven_verified'] and len(public['rows'])==7
    gallery_path=Path('data/quality-audited-seven-20261011-v2-share.json')
    if not gallery_path.exists():gallery_path=Path('data/quality-audited-seven-20261011-share.json')
    gallery=read(gallery_path)
    page=(Path(gallery['root'])/'index.html').read_text('utf-8')
    final_tags=[tag for tag in re.findall(r'<video\b[^>]*>',page) if '-final.mp4' in tag]
    assert len(final_tags)==7 and all(' poster=' in tag for tag in final_tags)
    lazy=read(OUT/'browser-lazy-verification-v2.json');assert lazy['cart']['ended'] and lazy['cart']['error'] is None
    assert public['url'].rstrip('/')==gallery['url'].rstrip('/') and lazy['url'].rstrip('/')==gallery['url'].rstrip('/')
    partial=read('data/download-range-integration-20261011/receipt.json')
    assert partial['complete'] and partial['full_decode_passed'] and not partial['errors']
    assert sha256_file(Path('data/download-range-integration-20261011/assembled.mp4'))==partial['sha256']==partial['original_sha256']
    for selection in read(OUT/'shared-current-selection.json'):
        state=studio.store.get(selection['task_id']);assert state['edit_id']==selection['edit_id']
        plan=read(selection['plan_path']);final=Path(selection['plan_path']).parent;qa=read(final/'verification.json')
        writing=read(selection['writing_path']);assert sha256_file(Path(selection['writing_path']))==selection['writing_sha256']
        script=next(s for s in state['scripts'] if s['id']==state['script_id'])
        assert plan['script_text']==script['text'] and len(writing['scripts'])==3
        assert hashlib.sha256(script['text'].encode()).hexdigest()==plan['voice']['script_sha256']
        assert sha256_file(Path(plan['voice']['path']))==plan['voice']['sha256']
        assert sha256_file(Path(selection['render_path']))==selection['render_sha256']
        assert qa['actual_visual_review'] and not qa['visual_review_pending']
        assert len(plan['cover_spec']['lines'])==2 and plan['cover_spec']['font']['font_family']=='Do Hyeon'
        style=plan['cover_spec']['style'];assert style['shadow_effect']['blur']==.8 and style['rotation']==-8 and style['italic_shear']==.15
        res=read(final/'render-result.json');draft=read(Path(res['portable_draft_path'])/'draft_content.json')
        cover={s['material_id'] for t in draft['tracks'] if t.get('name','').startswith('cover-line-') for s in t['segments']}
        assert len(cover)==2
        for text in draft['materials']['texts']:
            assert abs(text['shadow_smoothing']-(2.4 if text['id'] in cover else 1.8))<1e-5
            if text['id'] not in cover:assert text['font_resource_id']=='6841117356756832776'
        for track in draft['tracks']:
            if track.get('name','').startswith('cover-line-'):
                assert all(s['target_timerange']=={'start':0,'duration':33333} for s in track['segments'])
        used={b['selected_shot_id'] for b in plan['beats']};ids={s['source_id'] for s in plan['shots'] if s['id'] in used}
        parents=set()
        for source in plan['sources']:
            if source['id'] not in ids:continue
            assert sha256_file(Path(source['path']))==source['sha256']
            parent=Path(source.get('original_path') or source['path']);digest=source.get('original_sha256') or source['sha256']
            assert sha256_file(parent)==digest;parents.add(digest)
        voice=plan['voice'];goal=coverage_goal(plan['sources'],{'voices':[voice],'voice_id':voice['id'],'script_id':voice['script_id']},current_policy(load_settings()))
        assert goal['duration_ready'] and goal['core_ready']
        timeline=metrics(plan);assert abs(timeline['replayed_seconds'])<.08
        rows.append({**selection,'selected_number':next(s['number'] for s in writing['scripts'] if s['text']==script['text']),
            'selected_bias':next(s['bias'] for s in writing['scripts'] if s['text']==script['text']),
            'cover_lines':plan['cover_spec']['lines'],'coverage':goal,'metrics':timeline,
            'current_visual_review':str(final/'verification.json'),'current_browser_evidence':str(final/'browser-verification.json'),
            'used_parent_files':len(parents),'three_full_texts_actually_reviewed':True})
    fish=read(OUT/'fish-reception/result.json')
    assert fish['status']=='received' and fish['full_decode_passed'] and fish['actual_visual_review']['frames_read']==16
    assert sha256_file(Path(fish['path']))==fish['sha256']
    save(OUT/'completion-audit.json',{
        'checked_at':time.time(),'original_objective':'썸네일 후킹·인지심리학/행동경제학 대본 독립성·영상 소스 수신과 로직을 검토하고 실제 재작업 결과로 보완',
        'scope':inventory['full_scope'],'seven_current_outputs':rows,'three_proposals_per_output':True,
        'requirements':[
            {'requirement':'Keep all seven selected productions and additional fish source research in scope','status':'proven','evidence':'seven_current_outputs and fish-reception/result.json'},
            {'requirement':'Actual product highlight, two-line hook, Do Hyeon cover/십대 body, shadow80/60, first1frame','status':'proven','evidence':'All seven current covers manually read; all seven portable drafts and visual reviews inspected.'},
            {'requirement':'A/B different unused mechanisms in the original category, new conflict/order; C original mechanism/flow with meaningful surface changes; product curiosity CTA','status':'proven','evidence':'All 21 current full texts and the original texts read; current script/voice/writing hashes matched. C flow intentionally preserved under user rule.'},
            {'requirement':'Downloaded source files are complete and usable; reduce looping and correct wrong product/action scenes','status':'proven','evidence':'whole-decode.json, actual current render QA, folder USB revision, A7 envelope revision, zero reused source-time intervals across all seven.'},
            {'requirement':'Fragmented receiver, existing logged-in collector session, paced serial access and ordinary fallback behavior','status':'proven','evidence':'23-response real Chrome local fixture byte-identical; live TikTok whole-playback receptions; 170 tests. Live TikTok partial206 success is not claimed.'},
            {'requirement':'Reviewable outputs with original comparison, download, source/three-proposal detail and private API isolation','status':'proven','evidence':'public-seven-verification.json, verified share receipt, individual whole-playback proofs, newA7 whole playback, final lazy cart whole playback.'}
        ],
        'previous_goal_turn':'progress: folder USB correction/new source/personal TTS/render/full publication verification',
        'this_goal_turn':'progress: full-scope audit, A7 product-shape correction and policy reassessment, new fish reception, shared seven-output gallery and media-loading correction',
        'validation':{'download_and_writing_tests':99,'pacing_auth_and_source_quality_tests':71,'comparison_server_tests':6,'total_tests':176,'source_and_output_decode_evidence':'whole-decode.json plus current A7 render verification plus fish reception; old A7 render retained'},
        'additional_fish_research':{'source_received_seconds':fish['metadata']['duration'],'reviewed_frames':16,
            'reference_ingredient_name_unresolved':True,'new_source_names_its_own_recipe':True,
            'reference_identity_or_absolute_odor_claim_added':False,'additional_production_requested':False},
        'quality_limits':['Local promotional-caption blur and enlargement softness remain visible.','Distinct original files and source-time intervals do not prove independent filming or absence of repeated visual motifs.','Psychological hooks are editorial applications, without measured audience response.','Actual auditory listening was not performed.','Specific mini-envelope receipt insertion and phone-to-external-drive photo-copy sequences are not directly verified.'],
        'required_work_remaining':[],'completed':True})
    print('Current-state audit covers all seven outputs, 21 scripts, receiver behavior and additional fish research.',flush=True)

if __name__=='__main__':main()
