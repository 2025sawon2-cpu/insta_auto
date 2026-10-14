import copy,json,hashlib
from pathlib import Path
from types import SimpleNamespace
import pytest
from PIL import Image
from hotpost import mask_application_evidence as evidence
from hotpost import quality_progress as progress


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');return str(path)


def seal(receipt,tmp_path,passed=True):
    receipt['input_binding_sha256']=evidence.input_binding_sha256(receipt)
    report=tmp_path/'official.json'
    typed=tmp_path/'typed.json';write(typed,{k:v for k,v in receipt.items() if k!='official_review'})
    write(report,{'passed':passed,'input_binding_sha256':receipt['input_binding_sha256'],'actual_calls':1,'typed_receipt_sha256':evidence.file_sha(typed),
                  'display_projections':[{'beat_id':c['beat_id'],'role':role,'original_png_sha256':c[role]['file_sha256'],'display_jpeg_sha256':'display','canvas':[1080,1920]} for c in receipt['cases'] for role in ('before','after')],
                  'cases':[{'beat_id':c['beat_id'],'before_text_readable':True,'after_text_unreadable':True,'subject_visible':True} for c in receipt['cases']]})
    receipt['official_review']={'path':str(report),'sha256':evidence.file_sha(report),'typed_receipt_path':str(typed)}


@pytest.fixture
def case(tmp_path,monkeypatch):
    source=tmp_path/'source.mp4';source.write_bytes(b'actual-source')
    src={'id':'s','path':str(source),'sha256':evidence.file_sha(source),
         'watermark_masks':[{'source_start':0,'source_end':2,'rectangle':{'width':.1,'height':.1,'centerX':0,'centerY':0},'strength':.8}],
         'mask_review':{'source_sha256':evidence.file_sha(source)},'reviewed_intervals':[{'source_start':0,'source_end':2}]}
    roi=evidence.pixel_rectangle(src['watermark_masks'][0]['rectangle'])
    plan={'script_text':'제품입니다','voice':{'sha256':'voice'},'sources':[src],
          'shots':[{'id':'shot','source_id':'s','path':str(source),'sha256':src['sha256'],'start':0,'end':2}],
          'beats':[{'id':'beat','text':'제품입니다','selected_shot_id':'shot','start':1,'end':3,
                    'required_scene_anchor':{'native_start':1,'native_end':1.033}}],
          'rendered_clips':[{'beat_id':'beat','path':str(source)}], 'cues':[]}
    pp=tmp_path/'plan.json';write(pp,plan);video=tmp_path/'preview.mp4';video.write_bytes(b'old-render')
    state={'edit_id':'old','script_id':'script','voice_id':'voice','sources':[copy.deepcopy(src)],
           'edits':[{'id':'old','plan_path':str(pp),'preview_path':str(video)}],
           'automation':{},'daily_quality':{'feedback':[{'kind':'watermark','beat_id':'beat','reason':'old text'}],
           'progress_policy':{'policy':progress.POLICY,'defects':{},'reviews':[],'attempts':[],'decisions':[],'best':None}}}
    inputs=[]
    for i in range(2):
        p=tmp_path/f'prefix{i}.mp4';p.write_bytes(bytes([i]));inputs.append({'path':str(p),'sha256':evidence.file_sha(p)})
    inputs.append({'path':str(source),'sha256':src['sha256']})
    concat=tmp_path/'concat.txt';concat.write_text('\n'.join("file '"+r['path']+"'" for r in inputs),encoding='utf-8')
    metadata=tmp_path/'frames.json';write(metadata,{'frames':[{'pts':i,'pts_time':str(i),'tags':{'lavf.concatdec.start_time':str(i)}} for i in range(3)]})
    native={'start':0,'end':1,'metadata_sha256':'native','source_sha256':src['sha256']}
    monkeypatch.setattr('hotpost.source_frame_timing.probe_native_timing',lambda *a:{'frames':[{'start':0,'end':1},{'start':1,'end':2}],'metadata_sha256':'native'})
    receipt={'policy':evidence.POLICY,'edit_id':'old','parent_plan_sha256':evidence.file_sha(pp),'parent_preview_sha256':evidence.file_sha(video),
        'selection_binding':evidence.frozen_selection(plan),'graph_sha256':hashlib.sha256(b'new').hexdigest(),
        'concat_path':str(concat),'concat_sha256':evidence.file_sha(concat),'concat_inputs':inputs,
        'concat_metadata':{'path':str(metadata),'sha256':evidence.file_sha(metadata)},'captures':{},'cases':[],
        'frame_clock':{'path':str(metadata),'file_sha256':evidence.file_sha(metadata)},
        'frame_clock_sha256':hashlib.sha256(json.dumps([0.0,1.0,2.0],sort_keys=True).encode()).hexdigest()}
    row={'beat_id':'beat','source_id':'s','source_sha256':src['sha256'],'source_window':[0,2],
         'source_native_frame':native,'concat_frame_ordinal':0,'capture_filter_index':75,'roi':roi,
         'mask_geometry_sha256':evidence.digest({k:src.get(k) for k in ('watermark_masks','portrait_geometry','mask_review','reviewed_intervals')})}
    for key,color,graph in [('before','white','old'),('after','gray','new')]:
        p=tmp_path/(key+'.png');im=Image.new('RGB',(1080,1920),color);im.save(p)
        x,y,w,h=roi;row[key]={'path':str(p),'file_sha256':evidence.file_sha(p),'rgb_sha256':hashlib.sha256(im.tobytes()).hexdigest(),
            'roi_rgb_sha256':hashlib.sha256(im.crop((x,y,x+w,y+h)).tobytes()).hexdigest(),'pts':2,'time_base':'1/1'}
        gp=tmp_path/(key+'graph.json');write(gp,{'graph':graph});lp=tmp_path/(key+'.log');lp.write_text('[Parsed_showinfo_75 @ x] config in time_base: 1/1\n[Parsed_showinfo_75 @ x] n: 0 pts: 2 pts_time:2\n')
        receipt['captures'][key]={'graph_path':str(gp),'graph_file_sha256':evidence.file_sha(gp),'graph_sha256':hashlib.sha256(graph.encode()).hexdigest(),
                               'log_path':str(lp),'log_sha256':evidence.file_sha(lp)}
    native_log=tmp_path/'native.log';native_log.write_text('[Parsed_showinfo_0 @ x] n: 0 pts: 0 pts_time:0 checksum:ABCD\n[Parsed_showinfo_2 @ x] n: 0 pts: 0 pts_time:0 checksum:ABCD\n')
    native_argv=tmp_path/'nativeargv.json';write(native_argv,['ffmpeg','-copyts','-ss','0','-i',str(source),'-vf','showinfo,fps=30,showinfo'])
    row['native_selection_trace']={'log_path':str(native_log),'log_sha256':evidence.file_sha(native_log),'argv_path':str(native_argv),'argv_sha256':evidence.file_sha(native_argv)}
    receipt['cases']=[row];seal(receipt,tmp_path);state['daily_quality']['mask_application_repair_evidence']=receipt
    return state,plan,receipt


def test_decoded_roi_approved_material_permits_new_output_and_blocks_repeat(case):
    state,plan,r=case
    assert evidence.approved_material(state)
    method=progress.permit(state,'reedit',reserve=True,job_id='new')
    assert method and method['facts'][0]['method']=='approved_mask_application_pixels'
    candidate=copy.deepcopy(plan);candidate['quality_mask_application']=evidence.render_evidence(state)
    assert progress.guard_render(state,candidate,'new') is None
    assert progress.guard_render(state,candidate,'again')
    assert progress.permit(state,'reedit',job_id='again') is None


@pytest.mark.parametrize('change',['samepixels','missingapproval','emptyconcat','arbitrarypts','timebase','nativeframe','expandedroi','falseapproval','nativeanchor','sourcechange'])
def test_metadata_or_unbound_pixel_changes_do_not_permit(case,tmp_path,change):
    state,plan,r=case;c=r['cases'][0]
    if change=='samepixels':c['after']=copy.deepcopy(c['before'])
    elif change=='emptyconcat':r['concat_inputs']=[]
    elif change=='arbitrarypts':c['before']['pts']=c['after']['pts']=9
    elif change=='timebase':c['before']['time_base']=c['after']['time_base']='1/2'
    elif change=='nativeframe':c['source_native_frame'].update(start=1,end=2)
    elif change=='expandedroi':c['roi'][2]+=1
    elif change=='sourcechange':Path(state['sources'][0]['path']).write_bytes(b'changed')
    elif change=='nativeanchor':
        candidate=copy.deepcopy(plan);candidate['quality_mask_application']=evidence.render_evidence(state)
        candidate['beats'][0]['required_scene_anchor']['native_end']=1
        assert progress.guard_render(state,candidate,'bad')
        return
    seal(r,tmp_path,passed=change!='falseapproval')
    if change=='missingapproval':r.pop('official_review')
    assert not evidence.approved_material(state)
    assert progress.permit(state,'reedit') is None


def test_mask_evidence_cannot_bypass_other_defect(case):
    state,plan,r=case
    state['daily_quality']['feedback'].append({'kind':'repetition','beat_id':'beat','reason':'repeat'})
    assert not evidence.approved_material(state)


def test_frozen_mask_route_executes_only_render(case,monkeypatch):
    from hotpost.daily_quality import DailyQualityMixin
    state,plan,r=case;state.update(script_id='script',voice_id='voice')
    monkeypatch.setattr('hotpost.daily_quality.change_claimed',lambda store,job,fn:fn(state,None))
    calls=[]
    owner=DailyQualityMixin();owner.store=SimpleNamespace()
    owner._process=lambda s,j,phase,request: calls.append(phase) or {'plan_path':'new'}
    result=owner._quality_reedit(state,{'id':'new','payload':{'mask_application_only':True,'edit_id':'old'}})
    assert calls==['render'] and result['parent_id']=='old'
    assert result['script_id']=='script' and result['voice_id']=='voice'



def test_native_metadata_spelling_cannot_create_another_pixel_method(case,tmp_path):
    state,plan,r=case
    first=evidence.approved_material(state)
    r['cases'][0]['source_native_frame']['review_prose']='new wording'
    seal(r,tmp_path)
    assert evidence.approved_material(state)==first
    r['cases'][0]['source_native_frame']['source_sha256']='other'
    seal(r,tmp_path)
    assert not evidence.approved_material(state)



@pytest.mark.parametrize('field,value',[('actual_calls',0),('display_projections',[]),('typed_receipt_sha256','fake')])
def test_no_actual_call_or_missing_exact_visual_input_is_not_an_approval(case,field,value):
    state,plan,r=case
    path=Path(r['official_review']['path']);review=json.loads(path.read_text(encoding='utf-8'));review[field]=value;write(path,review)
    r['official_review']['sha256']=evidence.file_sha(path)
    assert not evidence.approved_material(state)



@pytest.mark.parametrize('change',['nominal_clock','native_floor','trace_ordinal','source_frame_changed'])
def test_actual_clock_and_native_resample_receipts_are_required(case,tmp_path,change):
    state,plan,r=case;c=r['cases'][0]
    if change=='nominal_clock':r['frame_clock_sha256']='nominal-only'
    elif change=='native_floor':c['source_native_frame'].update(start=1,end=2)
    elif change=='trace_ordinal':c['concat_frame_ordinal']=1
    elif change=='source_frame_changed':
        lp=Path(c['native_selection_trace']['log_path']);lp.write_text(lp.read_text().replace('pts_time:0 checksum:ABCD','pts_time:1 checksum:ABCD'))
        c['native_selection_trace']['log_sha256']=evidence.file_sha(lp)
    seal(r,tmp_path)
    assert not evidence.approved_material(state)
