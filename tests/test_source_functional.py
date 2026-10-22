"""Functional evidence spans the clip without inventing scene chronology."""
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost.source_functional import review_function, sample_review_frames


def test_hash_named_mask_frames_keep_actual_decoded_timestamps(tmp_path,monkeypatch):
    from hotpost import source_functional as module
    reference=tmp_path/'reference.jpg';reference.write_bytes(b'reference')
    frames=[]
    for i,t in enumerate([12.0,3.0,8.0]):
        p=tmp_path/f'arbitrary-hash-{i}.png';p.write_bytes(str(t).encode())
        frames.append({'path':str(p),'source_timestamp':t})
    monkeypatch.setattr(module,'frame_inline_data',lambda p:{'mimeType':'image/jpeg','data':base64.b64encode(p.read_bytes()).decode()})
    monkeypatch.setattr('hotpost.visual_media.review_frame_data',module.frame_inline_data)
    seen=[]
    def generate(settings,instruction,data,*,media):
        seen.extend(media)
        return {'same_core_function':True,'context_usable':True,'context_usage_limits':[],
                'observed_actions':['처음 액체를 붓고 뒤에 표면을 닦음'],'differences':[],'reason':'실제 순서 확인'}
    monkeypatch.setattr('hotpost.script_rewriter._generate',generate)
    result=review_function(Settings(),SimpleNamespace(file_sha256='hash'),[reference],frames)
    stamps=[v['text'] for v in seen if 'text' in v and 'decoded source timestamp' in v['text']]
    assert stamps==['CANDIDATE: decoded source timestamp 3.0000s',
                   'CANDIDATE: decoded source timestamp 8.0000s',
                   'CANDIDATE: decoded source timestamp 12.0000s']
    assert result['evidence_frames'][1:]==[frames[i]['path'] for i in [1,2,0]]


def test_old_rejection_rechecked_and_success_clears_stale_ineligibility():
    from hotpost.source_functional import needs_function_review, apply_function_review, REVIEW_POLICY
    source={'sha256':'hash','editing_eligible':False,'functional_review':{
        'reviewed':True,'source_sha256':'hash','same_core_function':False,'context_usable':False}}
    assert needs_function_review(source)
    apply_function_review(source,{'reviewed':True,'source_sha256':'hash',
        'same_core_function':True,'policy':REVIEW_POLICY})
    assert source['editing_eligible'] and source['source_role']=='core'
    assert not needs_function_review(source)
    source['sha256']='changed'
    assert needs_function_review(source)


@pytest.mark.parametrize('core',[True,False])
def test_explicit_source_reanalysis_revisits_old_core_and_context_without_touching_history(core):
    import copy
    from hotpost.source_functional import needs_identity_reanalysis, REVIEW_POLICY
    source={'functional_review':{'reviewed':True,'policy':'visual-product-presentation-v4-full-reference-features',
                                'same_core_function':core,'context_usable':not core}}
    state={'run_id':'new','runs':[{'id':'old','status':'completed','inputs':{'source_ids':['old-source']}},
        {'id':'new','inputs':{'source_selection_mode':'automatic'}}]}
    before=copy.deepcopy(state)
    assert needs_identity_reanalysis(state,source)
    assert state==before
    source['functional_review']['policy']=REVIEW_POLICY
    assert not needs_identity_reanalysis(state,source)
    source['functional_review']['policy']='old'
    state['run_id']='old'
    assert not needs_identity_reanalysis(state,source)
    state['run_id']='new'
    source['manual_usage_review']={'editing_eligible':False}
    assert not needs_identity_reanalysis(state,source)


def test_current_rejection_and_old_acceptance_are_not_repeated():
    from hotpost.source_functional import needs_function_review, REVIEW_POLICY
    for review in ({'same_core_function':False,'context_usable':False,'policy':REVIEW_POLICY},
                   {'same_core_function':True,'reviewer':'manual'}):
        assert not needs_function_review({'sha256':'hash','functional_review':{
            **review,'reviewed':True,'source_sha256':'hash'}})


def test_fourteen_uniform_frames_include_start_middle_and_last():
    frames = [Path(f'candidate_{i:03d}.jpg') for i in range(1, 15)]
    selected, chronological = sample_review_frames(frames)
    assert selected == [frames[0], frames[4], frames[9], frames[13]]
    assert chronological


@pytest.mark.parametrize('ordering', ['interleaved', 'lexicographic'])
def test_mixed_scene_samples_do_not_displace_uniform_endpoints(ordering):
    uniform = [Path(f'frame_{i:03d}.jpg') for i in range(1, 11)]
    scenes = [Path(f'frame_scene_{i:03d}.jpg') for i in range(1, 5)]
    frames = [value for pair in zip(uniform[:4], scenes) for value in pair] + uniform[4:]
    if ordering == 'lexicographic':
        frames = sorted(frames)
    selected, chronological = sample_review_frames(frames)
    assert selected == [uniform[0], uniform[3], uniform[6], uniform[9]]
    assert chronological and all('_scene_' not in path.name for path in selected)


def test_uniform_sequence_is_sorted_numerically():
    frames = [Path('candidate_10.jpg'), Path('candidate_1.jpg'), Path('candidate_2.jpg')]
    assert sample_review_frames(frames) == ([frames[1], frames[2], frames[0]], True)


def test_new_model_review_cannot_undo_explicit_usage_exclusion():
    from hotpost.source_functional import apply_function_review
    source = {'manual_usage_review': {'editing_eligible': False, 'reason': 'Unrelated shoe painting'}}
    apply_function_review(source, {'reviewed': True, 'same_core_function': True})
    assert source['editing_eligible'] is False


@pytest.mark.parametrize('names', [[], ['candidate_001.jpg'],
    ['candidate_001.jpg', 'candidate_scene_001.jpg', 'candidate_010.jpg', 'candidate_scene_002.jpg'],
    ['candidate_scene_001.jpg', 'candidate_scene_002.jpg', 'candidate_scene_003.jpg']])
def test_sparse_or_scene_only_samples_never_claim_chronology(names):
    frames = [Path(name) for name in names]
    selected, chronological = sample_review_frames(frames)
    assert selected == frames and not chronological


def test_review_sends_bounded_endpoint_evidence_and_labels_uncertain_order(tmp_path, monkeypatch):
    from hotpost import script_rewriter
    from hotpost import source_functional
    # This test isolates chronological sampling; actual bounded JPEG transport
    # is covered with real image pixels in test_visual_media.py.
    monkeypatch.setattr(source_functional,'frame_inline_data',lambda path:
        {'mimeType':'image/jpeg','data':base64.b64encode(path.read_bytes()).decode()})
    monkeypatch.setattr('hotpost.visual_media.review_frame_data',source_functional.frame_inline_data)

    def files(names):
        result = []
        for name in names:
            path = tmp_path / name
            path.write_bytes(name.encode())
            result.append(path)
        return result

    reference = files(['frame_001.jpg', 'frame_scene_001.jpg', 'frame_009.jpg'])
    candidate = files([f'candidate_{i:03d}.jpg' for i in range(1, 15)])
    observed = {}

    def generate(settings, instruction, data, *, media):
        observed['media'] = media
        # The model remains free to reject the function; sampling grants no pass.
        return {'same_core_function': False, 'reason': 'Not demonstrated'}

    monkeypatch.setattr(script_rewriter, '_generate', generate)
    result = review_function(Settings(), SimpleNamespace(file_sha256='hash'), reference, candidate)
    labels = [item['text'] for item in observed['media'] if 'text' in item]
    assert 'timestamps/order unknown' in labels[0]
    assert 'chronological order' in labels[1]
    payloads = [base64.b64decode(item['inlineData']['data']).decode()
                for item in observed['media'] if 'inlineData' in item]
    assert payloads == [path.name for path in reference] + [
        'candidate_001.jpg', 'candidate_005.jpg', 'candidate_010.jpg', 'candidate_014.jpg']
    assert result['evidence_frames'][-1] == str(candidate[-1])
    assert len(result['evidence_frames']) == 7
    assert result['same_core_function'] is False and result['source_sha256'] == 'hash'

def test_whole_reference_overview_contains_late_scene_and_tracks_file_identity(tmp_path):
    import shutil,subprocess
    from PIL import Image
    from hotpost.source_functional import reference_review_info
    from hotpost.source_quality import sha256_file
    binary=shutil.which('ffmpeg')
    if not binary:pytest.skip('ffmpeg unavailable')
    video=tmp_path/'reference.mp4'
    def create(color):
        subprocess.run([binary,'-v','error','-y','-f','lavfi','-i',
            f"color=red:size=90x160:rate=10:duration=1.2,drawbox=x=0:y=0:w=iw:h=ih:color={color}:t=fill:enable='gte(t,0.6)'",
            '-an','-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True,capture_output=True)
    create('blue')
    info=reference_review_info({'reference_video':str(video),'original_text':'두 가지 기능을 보여요.'},tmp_path)
    assert info['reference_sha256']==sha256_file(video)
    with Image.open(info['overview_path']) as im:
        first=im.convert('RGB').getpixel((135,240));last=im.convert('RGB').getpixel((1320,1491))
        assert first[0]>first[2]+100 and last[2]>last[0]+100
    old=info['overview_path'];create('green')
    updated=reference_review_info({'reference_video':str(video)},tmp_path)
    assert updated['overview_path']!=old

def test_secondary_feature_review_receives_full_overview_and_reference_information(tmp_path,monkeypatch):
    from PIL import Image
    from hotpost import source_functional,script_rewriter
    overview=tmp_path/'whole.jpg';Image.new('RGB',(1080,1440),'blue').save(overview)
    candidate=tmp_path/'cloth.jpg';Image.new('RGB',(540,960),'green').save(candidate)
    captured={}
    def generate(settings,instruction,data,*,media):
        captured.update(data=data,media=media)
        return {'same_core_function':True,'matched_reference_features':['cloth hanging on convertible frame'],
                'observed_actions':['cloth placed on the exposed frame'],
                'context_usage_limits':['Not proof of drying speed or other modes']}
    monkeypatch.setattr(script_rewriter,'_generate',generate)
    info={'overview_path':str(overview),'original_product_text':'흔들의자, 테이블, 건조대의 세 가지 용도.'}
    result=source_functional.review_function(Settings(),SimpleNamespace(file_sha256='hash'),[],[candidate],info)
    assert 'FULL-VIDEO OVERVIEW' in captured['media'][0]['text']
    assert captured['data']['provided_reference_info']['original_product_text']==info['original_product_text']
    assert result['matched_reference_features']==['cloth hanging on convertible frame']
    assert str(overview) in result['evidence_frames'] and result['context_usage_limits']


def test_reference_scene_samples_survive_without_false_chronology(tmp_path,monkeypatch):
    from PIL import Image
    from hotpost.source_functional import REFERENCE_EVIDENCE_REVISION
    frames=[]
    for name in ['frame_001.jpg','frame_002.jpg','frame_003.jpg','frame_004.jpg','frame_123_scene_001.jpg']:
        p=tmp_path/name;Image.new('RGB',(20,20),'gray').save(p);frames.append(p)
    seen={}
    def generate(settings,instruction,data,*,media):
        seen.update(instruction=instruction,media=media)
        return {'same_core_function':False,'context_usable':False,'observed_actions':['uncertain']}
    monkeypatch.setattr('hotpost.script_rewriter._generate',generate)
    receipt=review_function(Settings(),SimpleNamespace(file_sha256='test'),frames,[frames[0]],
        {'reference_evidence_revision':REFERENCE_EVIDENCE_REVISION})
    assert str(frames[-1]) in receipt['evidence_frames']
    assert any('REFERENCE:' in p.get('text','') and 'order unknown' in p['text'] for p in seen['media'])
    assert 'visible evidence in BOTH videos' in seen['instruction']
    assert receipt['reference_evidence_revision']==REFERENCE_EVIDENCE_REVISION
    assert not receipt['same_core_function']


def test_prior_same_function_identity_rejection_gets_one_richer_reference_review(tmp_path):
    from test_core_product_priority import state,asset
    from hotpost.source_functional import needs_identity_reanalysis,REFERENCE_EVIDENCE_REVISION
    s=state();item=asset(tmp_path,0,s)
    assert not needs_identity_reanalysis(s,item)
    item['functional_review']['featured_product_identity']=False
    assert needs_identity_reanalysis(s,item)
    item['functional_review']['reference_evidence_revision']=REFERENCE_EVIDENCE_REVISION
    assert not needs_identity_reanalysis(s,item)
    item['functional_review'].pop('reference_evidence_revision')
    item['manual_usage_review']={'editing_eligible':False}
    assert not needs_identity_reanalysis(s,item)


@pytest.mark.parametrize('finished',['completed','superseded'])
def test_richer_reference_revision_preserves_finished_runs(tmp_path,finished):
    from test_core_product_priority import state,asset
    from hotpost.source_functional import needs_identity_reanalysis
    s=state();item=asset(tmp_path,0,s)
    item['functional_review']['featured_product_identity']=False
    s.update(status=finished,runs=[{'id':s['run_id'],'status':finished,'source_policy':s['source_policy']}])
    assert not needs_identity_reanalysis(s,item)
    s['runs'][0]['status']='running'
    assert needs_identity_reanalysis(s,item)
