"""A new physical window cannot inherit same-byte prep approval or replay failures."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from hotpost import source_overlay_review as overlay
from hotpost.source_mask_review import GEOMETRY, explicit_review_scope
from hotpost.source_quality import sha256_file, editing_ready
from hotpost.source_functional import needs_function_review
from hotpost.source_presentation import needs_presentation_review


@pytest.fixture
def scoped(tmp_path,monkeypatch):
    path=tmp_path/'video.mp4';path.write_bytes(b'unchanged-source')
    digest=sha256_file(path)
    source={'id':'stable','path':str(path),'sha256':digest,'source_quality':'unknown',
            'blur_required':True,'reviewed_intervals':[{'source_start':0.,'source_end':2.}],
            'functional_review':{'reviewed':True,'source_sha256':digest,'same_core_function':False,
                'context_usable':True},'presentation_review':{'reviewed':True,'source_sha256':digest},
            'source_role':'context_only','editing_eligible':True}
    samples=[]
    def sample(path,sha,output,intervals,**kwargs):
        samples.append(copy.deepcopy(intervals));output=Path(output);output.mkdir(parents=True,exist_ok=True)
        windows=[];frames=[]
        for i,(start,end) in enumerate(intervals):
            windows.append({'index':i,'source_start':start,'source_end':end})
            for n in range(5):
                stamp=start+(end-start-.05)*n/4;frame=output/f'{i}-{n}.png'
                Image.new('RGB',(1080,1920),(n*40,i*40,128)).save(frame)
                frames.append({'frame_id':f'{i}-{n}','path':str(frame),'sha256':sha256_file(frame),
                               'source_timestamp':stamp,'requested_timestamp':stamp,'interval_index':i})
        return {'version':1,'source_path':str(path),'source_sha256':sha,'source_duration':10.,
                'geometry':dict(GEOMETRY),'intervals':windows,'frames':frames}
    monkeypatch.setattr(overlay,'sample_source_frames',sample)
    monkeypatch.setattr(overlay,'_duration',lambda *args:10.)
    return source,tmp_path/'output',samples


def visual(*,accepted=True,first_only=False):
    calls=[]
    def generate(settings,instruction,data,*,media):
        calls.append(data['purpose'])
        if data['purpose']=='overlay_region_proposal':
            return {'frames':[{'frame_id':f['frame_id'],'boxes':[]}for f in data['frames']]}
        p=data['proposal'];ev=p['evidence'];windows=ev['intervals'][:1]if first_only else ev['intervals']
        return {'reviewer':'independent test','proposal_sha256':p['proposal_sha256'],
                'source_sha256':ev['source_sha256'],'geometry':dict(GEOMETRY),
                'intervals':[{'source_start':w['source_start'],'source_end':w['source_end'],
                    'mask_indices':[],'frame_ids':[f['frame_id']for f in ev['frames']if f['interval_index']==w['index']],
                    'coverage_confirmed':accepted,'subject_visible':True,'no_overlays_confirmed':True}for w in windows]}
    return generate,calls


def test_explicit_new_window_requires_fresh_function_and_portrait_without_promoting(scoped):
    source,output,samples=scoped;before=copy.deepcopy(source);gen,calls=visual()
    result=overlay.review_source_overlays(None,source,output,intervals=[[2,6]],generate=gen)
    assert samples==[[[2.,6.]]] and len(calls)==2
    assert result['reviewed_intervals']==[{'source_start':2.,'source_end':6.}]
    assert needs_function_review(result) and needs_presentation_review(result)
    assert not result['editing_eligible'] and not editing_ready(result)
    assert 'functional_review'not in result and 'presentation_review'not in result and 'source_role'not in result
    assert result['interval_review_history'][0]['prior_reviews']['functional_review']==source['functional_review']
    assert result['interval_review_history'][0]['prior_reviews']['presentation_review']==source['presentation_review']
    assert source==before
    reused=overlay.review_source_overlays(None,source,output,intervals=[[2.,6.]],
        generate=lambda *a,**k:pytest.fail('same physical scope must reuse'))
    assert len(samples)==1 and len(reused['interval_review_history'])==1
    assert not reused['editing_eligible']


def test_different_current_scope_cannot_overwrite_old_prep(scoped):
    source,output,samples=scoped;gen,_=visual()
    overlay.review_source_overlays(None,source,output,intervals=[[0,2]],generate=gen)
    hashes={p.name:sha256_file(p)for p in output.glob('*.json')}
    with pytest.raises(ValueError,match='different scope'):
        overlay.review_source_overlays(None,source,output,intervals=[[2,6]],
            generate=lambda *a,**k:pytest.fail('old prep must be preserved'))
    assert hashes=={p.name:sha256_file(p)for p in output.glob('*.json')} and len(samples)==1


def test_different_peer_window_misses_but_exact_scoped_peer_reuses(scoped):
    source,output,samples=scoped;settings=SimpleNamespace(data_dir=output.parent.parent/'peer-scope')
    base=settings.data_dir/'studio'/'previous'/'source-mask-checks'/source['sha256'][:20]
    gen,_=visual();overlay.review_source_overlays(settings,source,base,intervals=[[0,2]],generate=gen)
    old_hash=sha256_file(base/'overlay-receipt.json')
    scope=explicit_review_scope(source['sha256'],[[2,6]],10,samples_per_interval=5,policy=overlay.POLICY)
    bounded=base/('bounded-'+scope['fingerprint'][:20]);gen,calls=visual()
    overlay.review_source_overlays(settings,source,bounded,intervals=[[2,6]],generate=gen)
    assert len(calls)==2 and len(samples)==2 and sha256_file(base/'overlay-receipt.json')==old_hash
    incoming={**copy.deepcopy(source),'id':'another','rights':'preserve'}
    reused=overlay.review_source_overlays(settings,incoming,output,intervals=[[2,6]],
        generate=lambda *a,**k:pytest.fail('exact peer scope must reuse'))
    assert len(samples)==2 and reused['id']=='another' and reused['rights']=='preserve'
    assert reused['reviewed_intervals']==[{'source_start':2.,'source_end':6.}] and not reused['editing_eligible']


def test_forged_matching_scope_marker_cannot_bind_wrong_proposal(scoped):
    source,output,samples=scoped;gen,_=visual()
    overlay.review_source_overlays(None,source,output,intervals=[[0,2]],generate=gen)
    saved=output/'overlay-reviewed.json';data=json.loads(saved.read_text('utf-8'))
    data['overlay_review_scope']=explicit_review_scope(source['sha256'],[[2,6]],10,samples_per_interval=5,policy=overlay.POLICY)
    saved.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError,match='different scope'):
        overlay.review_source_overlays(None,source,output,intervals=[[2,6]],
            generate=lambda *a,**k:pytest.fail('mislabeled old proposal must not be used'))
    assert len(samples)==1


def test_partial_service_wait_keeps_exact_evidence_and_completed_proposal(scoped):
    source,output,samples=scoped;gen,calls=visual();inputs=[]
    def wait(settings,instruction,data,*,media):
        if data['purpose']=='independent_overlay_review':
            inputs.append(copy.deepcopy(data));raise RuntimeError('capacity wait')
        return gen(settings,instruction,data,media=media)
    with pytest.raises(RuntimeError,match='capacity wait'):
        overlay.review_source_overlays(None,source,output,intervals=[[2,6]],generate=wait)
    hashes={p.name:sha256_file(p)for p in (output/'frames').glob('*.png')}
    def resume(settings,instruction,data,*,media):
        assert data['purpose']=='independent_overlay_review' and data==inputs[0]
        return gen(settings,instruction,data,media=media)
    overlay.review_source_overlays(None,source,output,intervals=[[2,6]],generate=resume)
    assert samples==[[[2.,6.]]] and calls==['overlay_region_proposal','independent_overlay_review']
    assert hashes=={p.name:sha256_file(p)for p in (output/'frames').glob('*.png')}


def test_rejected_same_scope_receipt_is_not_an_automatic_second_visual_attempt(scoped):
    source,output,samples=scoped;gen,calls=visual(accepted=False)
    with pytest.raises(ValueError):overlay.review_source_overlays(None,source,output,intervals=[[2,6]],generate=gen)
    receipt_hash=sha256_file(output/'overlay-receipt.json')
    with pytest.raises(ValueError):overlay.review_source_overlays(None,source,output,intervals=[[2,6]],
        generate=lambda *a,**k:pytest.fail('same failed visual receipt cannot replay'))
    assert len(samples)==1 and len(calls)==2 and receipt_hash==sha256_file(output/'overlay-receipt.json')
    assert not(output/'overlay-reviewed.json').exists()


def test_partial_changed_png_is_hold_without_resampling(scoped):
    source,output,samples=scoped;gen,_=visual()
    def wait(settings,instruction,data,*,media):
        if data['purpose']=='independent_overlay_review':raise RuntimeError('wait')
        return gen(settings,instruction,data,media=media)
    with pytest.raises(RuntimeError):overlay.review_source_overlays(None,source,output,intervals=[[2,6]],generate=wait)
    frame=next((output/'frames').glob('*.png'));Image.new('RGB',(1080,1920),'red').save(frame)
    with pytest.raises(ValueError,match='changed'):
        overlay.review_source_overlays(None,source,output,intervals=[[2,6]],generate=gen)
    assert len(samples)==1


def test_default_call_cannot_overwrite_pending_explicit_scope(scoped):
    source,output,samples=scoped;gen,_=visual()
    def wait(settings,instruction,data,*,media):
        if data['purpose']=='independent_overlay_review':raise RuntimeError('wait')
        return gen(settings,instruction,data,media=media)
    with pytest.raises(RuntimeError):overlay.review_source_overlays(None,source,output,intervals=[[2,6]],generate=wait)
    with pytest.raises(ValueError,match='exact interval request'):
        overlay.review_source_overlays(None,source,output,generate=gen)
    assert len(samples)==1


def test_only_accepted_subset_is_editable_and_old_reviews_do_not_leak(scoped):
    source,output,samples=scoped;gen,_=visual(first_only=True)
    result=overlay.review_source_overlays(None,source,output,intervals=[[2,4],[6,8]],generate=gen)
    assert result['reviewed_intervals']==[{'source_start':2.,'source_end':4.}]
    assert 'functional_review'not in result and 'presentation_review'not in result
    assert not editing_ready(result)
    assert sum(x['source_end']-x['source_start']for x in result['reviewed_intervals'])==2
    frames=overlay.accepted_interval_frames(result)
    assert len(frames)==5 and all(2<=f['source_timestamp']<4 for f in frames)
    bad=copy.deepcopy(result);bad['reviewed_intervals']=[{'source_start':0.,'source_end':10.}]
    with pytest.raises(ValueError,match='not bound'):overlay.accepted_interval_frames(bad)
    duplicate=copy.deepcopy(result)
    duplicate['mask_review']['evidence_frames'].append(copy.deepcopy(duplicate['mask_review']['evidence_frames'][0]))
    with pytest.raises(ValueError,match='repeated'):overlay.accepted_interval_frames(duplicate)


def test_real_explicit_window_keeps_native_pts_and_fresh_approval_gates(tmp_path,monkeypatch):
    import shutil,subprocess
    ffmpeg,ffprobe=shutil.which('ffmpeg'),shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:pytest.skip('ffmpeg/ffprobe required for native evidence')
    path=tmp_path/'real.mp4'
    subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=c=blue:s=1080x1920:r=30:d=4',
                    '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',str(path)],
                   check=True,capture_output=True,timeout=30)
    source={'id':'real','path':str(path),'sha256':sha256_file(path),'source_quality':'unknown'}
    from hotpost import source_finder
    monkeypatch.setattr(source_finder,'_executable',lambda name:ffmpeg if name=='ffmpeg'else ffprobe)
    gen,_=visual()
    result=overlay.review_source_overlays(None,source,tmp_path/'proof',intervals=[[1,3]],generate=gen)
    evidence=json.loads((tmp_path/'proof'/'overlay-evidence.json').read_text('utf-8'))
    assert evidence['intervals']==[{'index':0,'source_start':1.,'source_end':3.}]
    assert len(evidence['frames'])==5
    assert all(1<=f['source_timestamp']<3 and f['native_frame_exposure']['source_sha256']==source['sha256']
               and f['native_frame_exposure']['end']<=3 for f in evidence['frames'])
    assert len(overlay.accepted_interval_frames(result))==5 and not editing_ready(result)


@pytest.mark.parametrize('intervals',[[],[[True,4]],[[2,float('nan')]],[[2,11]],[[4,2]],[[2,4],[2,4]]])
def test_invalid_explicit_scope_cannot_call_models_or_sample(scoped,intervals):
    source,output,samples=scoped
    with pytest.raises(ValueError):overlay.review_source_overlays(None,source,output,intervals=intervals,
        generate=lambda *a,**k:pytest.fail('invalid physical scope'))
    assert not samples


def test_scope_order_and_numeric_spelling_do_not_create_a_new_method():
    digest='a'*64
    a=explicit_review_scope(digest,[[2,4],[6,8]],10,samples_per_interval=5,policy=overlay.POLICY)
    b=explicit_review_scope(digest,[[6.,8.],[2.,4.]],10.,samples_per_interval=5,policy=overlay.POLICY)
    assert a==b
    assert a!=explicit_review_scope(digest,[[2,4]],10,samples_per_interval=5,policy=overlay.POLICY)
    assert a!=explicit_review_scope(digest,[[2,4],[6,8]],10,samples_per_interval=3,policy=overlay.POLICY)
    assert a!=explicit_review_scope(digest,[[2,4],[6,8]],10,samples_per_interval=5,policy='different')
