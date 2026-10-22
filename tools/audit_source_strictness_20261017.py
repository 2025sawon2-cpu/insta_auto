"""Read-only, frozen five-reference audit of current source gates; no production."""
import argparse,copy,hashlib,json,math,os,re,sqlite3,subprocess,sys,time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
FFDIR=Path('C:/Users/s98se/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-9.0.2-full_build/bin')
os.environ['PATH']=str(FFDIR)+os.pathsep+os.environ['PATH']
from hotpost.config import load_settings
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file,editing_ready,relevance_reasons
from hotpost.source_functional import review_function,apply_function_review,REVIEW_POLICY
from hotpost.source_presentation import review_presentation,apply_presentation_review,format_warnings
from hotpost.source_coverage import coverage_goal
from hotpost.source_policy import current_policy
from hotpost.product_appeal_review import PRODUCT_APPEAL_INSTRUCTION
from hotpost.visual_media import review_frame_data
OUT=ROOT/'data/source-strictness-audit-20261017'
CASES=[('DeiBMuLzPxV','스웻팬츠'),('DeiCA-gyWhM','틈새 선반'),('DeiD1rYzW9-','후드 집업'),('Dege8mKBaUR','교체용 지퍼 슬라이더'),('DegiqugP5pn','토트백')]
def save(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),'utf8')
def read(path):return json.loads(Path(path).read_text('utf8'))
def rows():
    with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
        return {key:raw for key,raw in db.execute('SELECT id,state FROM tasks')}
def prepare():
    if (OUT/'selection.json').exists():raise ValueError('Frozen audit selection exists')
    settings=load_settings();raw=rows();states=[json.loads(v) for v in raw.values()]
    OUT.mkdir(parents=True,exist_ok=True)
    save(OUT/'baseline.json',{'at':datetime.now().astimezone().isoformat(),'tasks':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in raw.items()},'modules':{p:sha256_file(ROOT/p) for p in ['hotpost/source_quality.py','hotpost/source_functional.py','hotpost/source_presentation.py','hotpost/source_coverage.py','hotpost/source_policy.py','hotpost/scene_analysis.py','hotpost/shot_presentation.py','hotpost/source_overlay_review.py']}})
    records=[]
    for code,product in CASES:
        state=next(s for s in states if s.get('shortcode')==code);folder=OUT/code;folder.mkdir()
        source=Path(state['reference_video']);digest=sha256_file(source);meta=probe_video(source)
        frames=folder/'frames';frames.mkdir()
        result=subprocess.run([str(FFDIR/'ffmpeg.exe'),'-hide_banner','-v','info','-i',str(source),'-vf',"setpts=PTS-STARTPTS,select='isnan(prev_selected_t)+gte(t-prev_selected_t,0.5)',showinfo,scale=270:480:force_original_aspect_ratio=decrease,pad=270:480:(ow-iw)/2:(oh-ih)/2",'-fps_mode','vfr',str(frames/'%04d.jpg')],capture_output=True,text=True,encoding='utf8',errors='replace',check=True)
        times=[float(t) for t in re.findall(r'\bpts_time:([\d.eE+-]+)',result.stderr)];paths=sorted(frames.glob('*.jpg'))
        assert len(times)==len(paths) and times[0]==0
        samples=[{'path':str(p),'time':t,'sha256':sha256_file(p)} for p,t in zip(paths,times)];sheets=[]
        for offset in range(0,len(samples),12):
            group=samples[offset:offset+12];sheet=Image.new('RGB',(1080,math.ceil(len(group)/4)*506),'#202020');draw=ImageDraw.Draw(sheet)
            for i,row in enumerate(group):
                x=i%4*270;y=i//4*506
                with Image.open(row['path']) as image:sheet.paste(image,(x,y+26))
                draw.text((x+4,y+4),f"{row['time']:.3f}s",fill='white')
            path=folder/f'sequence-{offset//12:02d}.jpg';sheet.save(path,quality=93);sheets.append({'path':str(path),'sha256':sha256_file(path),'start':group[0]['time'],'end':group[-1]['time']})
        # Exactly the four chronological positions used by the current function reviewer.
        sparse=[]
        for i,index in enumerate([round(n*(len(samples)-1)/3) for n in range(4)],1):
            path=folder/f'candidate_{i}.jpg';path.write_bytes(Path(samples[index]['path']).read_bytes());sparse.append(str(path))
        overview=folder/'overview.jpg'
        subprocess.run([str(FFDIR/'ffmpeg.exe'),'-v','error','-i',str(source),'-vf',f"fps={12/meta['duration']},scale=270:480:force_original_aspect_ratio=decrease,pad=270:480:(ow-iw)/2:(oh-ih)/2,tile=4x3",'-frames:v','1',str(overview)],check=True,capture_output=True)
        approved=[];pending=[]
        for item in state.get('sources',[]):
            receipt=item.get('functional_review') or {};presentation=item.get('presentation_review') or {}
            value={'id':item.get('id'),'path':item.get('path'),'sha256':item.get('sha256'),'ready_now':editing_ready(item),'source_role':item.get('source_role'),'function_reviewed':receipt.get('reviewed'),'function_policy':receipt.get('policy'),'same_core_function':receipt.get('same_core_function'),'context_usable':receipt.get('context_usable'),'reason':receipt.get('reason'),'presentation_usable':presentation.get('usable'),'presentation_reason':presentation.get('reason'),'actual_file_matches':bool(item.get('path') and Path(item['path']).is_file() and sha256_file(Path(item['path']))==item.get('sha256')),'state_record':copy.deepcopy(item)}
            (approved if value['ready_now'] else pending).append(value)
        evidence={'code':code,'product':product,'task_id':state['id'],'reference_path':str(source),'reference_sha256':digest,'meta':meta,'format_warnings':format_warnings(meta),'original_text':state.get('reviewed_original_text') or state.get('original_text',''),'sparse_frames':sparse,'samples':samples,'sheets':sheets,'overview_path':str(overview),'overview_sha256':sha256_file(overview),'existing_ready_sources':approved,'existing_not_ready_sources':pending}
        save(folder/'evidence.json',evidence);records.append({'code':code,'product':product,'evidence':str(folder/'evidence.json')})
        print(json.dumps({'prepared':code,'duration':meta['duration'],'frames':len(samples),'ready':len(approved),'not_ready':len(pending)},ensure_ascii=False),flush=True)
    save(OUT/'selection.json',{'at':datetime.now().astimezone().isoformat(),'selection':records,'selection_rule':'Frozen before fresh reviews: today top3 plus preceding bag and zipper; varied appearance, installation and mechanical use; no outcome selection','production_task_mutations':0,'new_acquisition':0})
def run_one(settings,evidence,kind):
    code=evidence['code'];folder=OUT/code;target=folder/f'{kind}.json'
    if target.exists():return
    if (folder/f'{kind}-attempt.json').exists():raise ValueError('Do not repeat failed/in-flight identical review')
    assert sha256_file(Path(evidence['reference_path']))==evidence['reference_sha256']
    save(folder/f'{kind}-attempt.json',{'started':time.time(),'reference_sha256':evidence['reference_sha256']})
    started=time.time()
    try:
        if kind=='function':
            candidate=SimpleNamespace(file_sha256=evidence['reference_sha256'])
            info={'product':evidence['product'],'original_product_text':evidence['original_text'],'overview_path':evidence['overview_path'],'overview_sha256':evidence['overview_sha256'],'reference_sha256':evidence['reference_sha256']}
            value=review_function(settings,candidate,evidence['sparse_frames'],evidence['sparse_frames'],info)
        elif kind=='presentation-native':
            stream=json.loads(subprocess.check_output([str(FFDIR/'ffprobe.exe'),'-v','error','-select_streams','v:0','-show_entries','stream=duration','-of','json',evidence['reference_path']],text=True))['streams'][0]
            video_duration=float(stream['duration'])
            source={'path':evidence['reference_path'],'sha256':evidence['reference_sha256'],'video_meta':evidence['meta'],'source_role':'core','functional_review':read(folder/'function.json')['result'],'reviewed_intervals':[{'source_start':0.,'source_end':video_duration}]}
            value=review_presentation(settings,source,folder/'portrait')
        elif kind=='montage':
            from hotpost.script_rewriter import _generate
            media=[]
            for sheet in evidence['sheets']:
                assert sha256_file(Path(sheet['path']))==sheet['sha256']
                media.extend([{'text':f"ACTUAL ORIGINAL REFERENCE: row-major ordered samples {sheet['start']}..{sheet['end']} seconds; NOT one frame"},{'inlineData':review_frame_data(sheet['path'])}])
            instruction=(PRODUCT_APPEAL_INSTRUCTION+' Audit an ORIGINAL reference independently of prior pass/fail labels. Creator text/watermarks, a face in the source, source voice and comment keyword are separate project-contract adaptations, not intrinsic montage failures. Popularity is not proof of quality. Return JSON {product_appeal_pass:boolean,summary:string,observed_appeal:[string],nonliteral_or_nonproduct_intervals:[{start:number,end:number,shown:string,acceptable_in_context:boolean,reason:string}],true_misleading_defects:[string],mask_adaptation_risks:[string],strictness_guidance:[string]}. Include only actual observed facts and uncertain boundaries as estimates. Do not infer motion between samples, invisible material/performance, or auditory listening. Distinguish a clear product view sufficient as support from a complete mechanical transition offered as proof. Do not impose every frame or every sentence product visibility on the whole montage.')
            value=_generate(settings,instruction,{'purpose':'five_reference_source_gate_audit_independent_montage','product':evidence['product'],'source_sha256':evidence['reference_sha256'],'duration':evidence['meta']['duration'],'reference_text':evidence['original_text'],'sampling':'actual normalized native PTS, one sample per ~0.5sec; sample gaps do not prove continuous motion'},media=media)
        save(target,{'kind':kind,'reference_sha256':evidence['reference_sha256'],'started':started,'finished':time.time(),'result':value,'production_state_changed':False})
        print(json.dumps({'code':code,'kind':kind,'seconds':round(time.time()-started,2),'result':value if kind=='montage' else {k:value.get(k) for k in ('same_core_function','context_usable','usable','reason')}},ensure_ascii=False),flush=True)
    except Exception as exc:
        save(folder/f'{kind}-error.json',{'error':str(exc),'at':time.time()});raise
def review():
    settings=load_settings()
    for row in read(OUT/'selection.json')['selection']:
        evidence=read(row['evidence'])
        for kind in ['function','presentation-native','montage']:run_one(settings,evidence,kind)
def summarize():
    settings=load_settings();policy=current_policy(settings);summary=[]
    for row in read(OUT/'selection.json')['selection']:
        e=read(row['evidence']);folder=OUT/e['code'];function=read(folder/'function.json')['result'];presentation=read(folder/'presentation-native.json')['result'];montage=read(folder/'montage.json')['result']
        # Mask contracts are not forged for original creator text. This counterfactual isolates duration readiness only.
        source={'id':'reference-positive-control','path':e['reference_path'],'sha256':e['reference_sha256'],'video_meta':e['meta'],'source_role':'core','functional_review':function,'reviewed_intervals':[{'source_start':0.,'source_end':e['meta']['duration']}]}
        goal=coverage_goal([source],{'reference_duration':e['meta']['duration']},policy)
        summary.append({'code':e['code'],'product':e['product'],'duration':e['meta']['duration'],'same_core_function':function['same_core_function'],'function_context_usable':function['context_usable'],'portrait_usable':presentation['usable'],'intrinsic_appeal_pass':montage.get('product_appeal_pass'),'duration_control_ignoring_masks':goal,'existing_ready':len(e['existing_ready_sources']),'existing_not_ready':len(e['existing_not_ready_sources']),'existing_core':sum(s['source_role']=='core' for s in e['existing_ready_sources']),'existing_context':sum(s['source_role']=='context_only' for s in e['existing_ready_sources']),'existing_not_ready_reasons':[{'id':s['id'],'reason':s['state_record'].get('overlay_review_error') or s['state_record'].get('mask_review_error') or s['state_record'].get('error') or s['state_record'].get('presentation_review_error'),'function_reviewed':s['function_reviewed']} for s in e['existing_not_ready_sources']]})
    baseline=read(OUT/'baseline.json');current=rows()
    assert {k:hashlib.sha256(v.encode()).hexdigest() for k,v in current.items()}==baseline['tasks']
    assert all(sha256_file(ROOT/p)==digest for p,digest in baseline['modules'].items())
    save(OUT/'summary.json',{'at':datetime.now().astimezone().isoformat(),'references':summary,'current_policy':policy,'task_states_unchanged':len(current),'runtime_source_modules_unchanged':True,'new_source_collection_jobs':0,'note':'Self-reference function is a positive control, not proof arbitrary candidates are valid. Duration-only control does not certify mask eligibility or authorize source reuse.'})
    print(json.dumps(summary,ensure_ascii=False,indent=2))
def overlay_audit():
    from hotpost.source_overlay_review import review_source_overlays
    settings=load_settings()
    for row in read(OUT/'selection.json')['selection']:
        e=read(row['evidence']);folder=OUT/e['code'];target=folder/'overlay-outcome.json'
        if target.exists():continue
        marker=folder/'overlay-attempt.json'
        if marker.exists():raise ValueError('Do not repeat identical overlay attempt')
        save(marker,{'at':time.time(),'source_sha256':e['reference_sha256']});started=time.time()
        source={'id':'audit-only-original','path':e['reference_path'],'sha256':e['reference_sha256'],'video_meta':e['meta'],'source_quality':'unknown','editing_eligible':False}
        try:
            value=review_source_overlays(settings,source,folder/'overlay')
            result={'accepted':True,'reviewed_intervals':value.get('reviewed_intervals'),'mask_count':len(value.get('watermark_masks',[])),'reuse':value.get('overlay_review_reused_from'),'receipt_path':str(folder/'overlay/overlay-reviewed.json')}
        except Exception as exc:
            result={'accepted':False,'error':str(exc),'reviewer_receipt':read(folder/'overlay/overlay-receipt.json') if (folder/'overlay/overlay-receipt.json').exists() else None}
        save(target,{'source_sha256':e['reference_sha256'],'started':started,'finished':time.time(),'result':result,'not_a_production_approval':True})
        print(json.dumps({'code':e['code'],'kind':'overlay','seconds':round(time.time()-started,2),'accepted':result['accepted'],'intervals':result.get('reviewed_intervals'),'error':result.get('error')},ensure_ascii=False),flush=True)
def focused_window():
    from hotpost.source_overlay_review import review_source_overlays
    e=read(OUT/'DeiCA-gyWhM/evidence.json');folder=OUT/'focused-shelf';target=folder/'outcome.json'
    if target.exists():return
    if (folder/'hypothesis.json').exists():raise ValueError('Same focused request already attempted')
    prior=read(OUT/'DeiCA-gyWhM/overlay-outcome.json')
    assert prior['result']['accepted'] and not any(w['source_start']==0 for w in prior['result']['reviewed_intervals'])
    save(folder/'hypothesis.json',{'at':time.time(),'source_sha256':e['reference_sha256'],'parent_rejected_scope':[0,4],'new_scope':[.5,1.3],'reason':'Actual ~0.5 and1.0sec native-PTS samples show shelf top and placement, after the large opening title. Test whether narrower exact evidence/mask geometry preserves useful footage without changing any acceptance rule. A passed 0.8sec window does not prove every rejected window salvageable.','production_registration':False})
    source={'id':'audit-only-original','path':e['reference_path'],'sha256':e['reference_sha256'],'video_meta':e['meta'],'source_quality':'unknown','editing_eligible':False}
    started=time.time()
    try:
        value=review_source_overlays(load_settings(),source,folder/'review',intervals=[[.5,1.3]])
        result={'accepted':True,'reviewed_intervals':value.get('reviewed_intervals'),'mask_count':len(value.get('watermark_masks',[]))}
    except Exception as exc:result={'accepted':False,'error':str(exc)}
    save(target,{'started':started,'finished':time.time(),'result':result,'not_a_production_approval':True});print(json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','review','overlay','focused','summarize']);args=parser.parse_args()
    {'prepare':prepare,'review':review,'overlay':overlay_audit,'focused':focused_window,'summarize':summarize}[args.stage]()
