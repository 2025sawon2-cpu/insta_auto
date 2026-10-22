import copy
import hashlib
import json
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.model_service import ModelServiceUnavailable,ModelResponseInvalid
from hotpost.studio_store import Conflict
from hotpost.studio_runtime.editing import EditingMixin


class Editor(EditingMixin):
    def folder(self,task):return self.root
    def _source_records(self,videos,manifest,existing):return copy.deepcopy(existing)
    def _process(self,state,job,action,payload):
        assert action=='analyze'
        source=payload['sources'][0];script=payload['script']
        return {'plan':{'script_text':script['text'],'voice':copy.deepcopy(payload['voice']),
            'sources':copy.deepcopy(payload['sources']),'warnings':[],
            'shots':[{'id':'shot','source_id':source['id'],'path':source['path'],'sha256':source['sha256'],
                'start':0,'end':2,'frames':[str(self.frame)]}],
            'beats':[{'id':'beat','text':script['text'],'start':0,'end':1,'options':[]}],
            'width':1080,'height':1920,'duration':1}}
    def render_feedback(self,state,job,plan):
        self.rendered.append(copy.deepcopy(plan));return {'plan':plan}


def fixture(tmp_path,monkeypatch):
    source=tmp_path/'source.mp4';source.write_bytes(b'actual source identity')
    voice=tmp_path/'voice.wav';voice.write_bytes(b'actual approved voice identity')
    frame=tmp_path/'frame.jpg';frame.write_bytes(b'actual observed frame identity')
    words=tmp_path/'script.txt';words.write_text('This spray removes stains.',encoding='utf-8')
    state={'id':'task','scripts':[{'id':'script','text':words.read_text(encoding='utf-8'),'path':str(words)}],
        'voices':[{'id':'voice','path':str(voice),'sha256':hashlib.sha256(voice.read_bytes()).hexdigest(),
            'script_id':'script','spoken_text':words.read_text(encoding='utf-8')}],
        'approved_script_id':'script','approved_voice_id':'voice','daily_quality':{'repair_round':2,'max_repairs':3},
        'sources':[{'id':'source','path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'source_quality':'clean-source','editing_eligible':True,'source_role':'core',
            'video_meta':{'duration':3,'width':720,'height':1280},
            'functional_review':{'reviewed':True,'same_core_function':True,
                'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'context_usage_limits':[]}}]}
    job={'id':'edit','kind':'edit','payload':{'script_id':'script','voice_id':'voice'},'checkpoint':{}}
    editor=Editor();editor.root=tmp_path;editor.frame=frame;editor.settings=Settings(data_dir=tmp_path);editor.rendered=[]
    calls=[]
    def describe(*args,**kwargs):
        calls.append((copy.deepcopy(args),copy.deepcopy(kwargs)))
        return {'shot':{'observation':'Actual aerosol spray','evidence_status':'observed'}}, {
            'beat':{'analysis_status':'ranked','options':[{'shot_id':'shot','relation':'context','reason':'Observed spray'}],
                'incompatible_subject_shot_ids':[],'promoted_subject_reference':True}}
    monkeypatch.setattr('hotpost.studio_ai.describe_shots',describe)
    return editor,state,job,calls,describe


def cache_path(editor):return editor.root/'edit'/'semantic-plan.json'


def test_interval_policy_switch_is_an_output_not_a_concurrent_input_change(tmp_path,monkeypatch):
    editor,state,job,calls,original_describe=fixture(tmp_path,monkeypatch)
    original_process=editor._process
    def analyze(*args,**kwargs):
        result=original_process(*args,**kwargs)
        result['plan'].update(daily_quality_policy='test',footage_selection_policy='diverse-sequential-v2-semantic-first')
        return result
    def describe(*args,**kwargs):
        observations,choices=original_describe(*args,**kwargs)
        from hotpost.shot_presentation import interval_receipt
        observations['shot']['shot_presentation']=interval_receipt(args[1][0],dict(
            product_visible=True,frame_product_visibility=[True],product_role='promoted_product',
            visible_information=['spray'],visual_cluster='spray-front',composition=.8,clarity=.8,
            product_coverage=.5,mask_product_overlap=0,uncertainty='Provided frame only'))
        return observations,choices
    editor._process=analyze
    monkeypatch.setattr('hotpost.studio_ai.describe_shots',describe)
    first=editor._edit(state,job)['plan']
    assert first['footage_selection_policy']=='product-story-global-v3'
    assert editor._edit(state,job)['plan']==first and len(calls)==1


def test_same_contract_and_actual_inputs_reuse_verified_semantics(tmp_path,monkeypatch):
    editor,state,job,calls,_=fixture(tmp_path,monkeypatch);before=copy.deepcopy(state)
    editor._edit(state,job);first=cache_path(editor).read_bytes()
    result=editor._edit(state,job)
    assert len(calls)==1 and cache_path(editor).read_bytes()==first
    assert result['plan']['semantic_cache']['analysis_complete']
    assert result['plan']['beats'][0]['promoted_subject_reference'] is True
    assert state==before


def test_cover_only_copy_change_survives_semantic_cache_without_reanalyzing_body(tmp_path,monkeypatch):
    editor,state,job,calls,_=fixture(tmp_path,monkeypatch)
    original=editor._process;lines=['Original product','Original question']
    def analyze(*args,**kwargs):
        result=original(*args,**kwargs);result['plan']['cover_spec']={'lines':list(lines)}
        return result
    monkeypatch.setattr(editor,'_process',analyze)
    first=editor._edit(state,job)['plan'];raw=cache_path(editor).read_bytes()
    lines[:]=['Same product','New unanswered question']
    result=editor._edit(state,job)['plan']
    assert result['cover_spec']['lines']==lines and len(calls)==1
    assert result['shots']==first['shots'] and result['beats']==first['beats']
    assert cache_path(editor).read_bytes()==raw # Preserve prior analysis/copy checkpoint.


def test_loaded_contract_signature_and_cache_survive_constant_reference_changes(tmp_path,monkeypatch):
    import gc
    from hotpost import scene_analysis
    from hotpost.studio_runtime.editing import _semantic_binding
    editor,state,job,calls,_=fixture(tmp_path,monkeypatch)
    plan=editor._edit(state,job)['plan'];raw=cache_path(editor).read_bytes()
    def binding():return _semantic_binding(state,state['scripts'][0],state['voices'][0],state['sources'],plan)
    before=binding()
    held=list(scene_analysis.analyze_shots.__code__.co_consts)
    assert held and binding()==before
    editor._edit(state,job)
    del held
    gc.collect()
    assert binding()==before
    editor._edit(state,job)
    assert len(calls)==1 and cache_path(editor).read_bytes()==raw


def test_changed_loaded_nested_code_invalidates_contract_and_preserves_prior_cache(tmp_path,monkeypatch):
    from types import CodeType
    from hotpost import scene_analysis
    editor,state,job,calls,_=fixture(tmp_path,monkeypatch)
    first=editor._edit(state,job)['plan'];raw=cache_path(editor).read_bytes()
    code=scene_analysis.analyze_shots.__code__;constants=list(code.co_consts)
    index=next(i for i,value in enumerate(constants) if isinstance(value,CodeType))
    nested=constants[index]
    constants[index]=nested.replace(co_consts=(*nested.co_consts,'new loaded nested analysis contract'))
    changed=code.replace(co_consts=tuple(constants))
    assert changed.co_code==code.co_code # Only the nested executable contract changed.
    monkeypatch.setattr(scene_analysis.analyze_shots,'__code__',changed)
    result=editor._edit(state,job)['plan']
    assert result['semantic_cache']['contract_sha256']!=first['semantic_cache']['contract_sha256']
    assert len(calls)==2
    assert (cache_path(editor).parent/'semantic-history'/('semantic-plan-'+hashlib.sha256(raw).hexdigest()+'.json')).read_bytes()==raw
    assert state['daily_quality']['repair_round']==2


@pytest.mark.parametrize('marker',[None,'invalid',{'policy':'old-policy'}])
def test_legacy_or_unbound_cache_is_preserved_by_exact_sha_before_normal_analysis(tmp_path,monkeypatch,marker):
    editor,state,job,calls,_=fixture(tmp_path,monkeypatch)
    path=cache_path(editor);path.parent.mkdir()
    old={'script_text':'Old narration','warnings':['Original old record']}
    if marker is not None:old['semantic_cache']=marker
    raw=json.dumps(old).encode();path.write_bytes(raw)
    result=editor._edit(state,job)
    history=path.parent/'semantic-history'/('semantic-plan-'+hashlib.sha256(raw).hexdigest()+'.json')
    assert history.read_bytes()==raw and len(calls)==1
    assert result['plan']['script_text']==state['scripts'][0]['text']


@pytest.mark.parametrize('change',['observe_contract','rank_contract','usage_limits','geometry','frame','source','narration','voice'])
def test_changed_contract_or_actual_input_invalidates_cache_with_history(tmp_path,monkeypatch,change):
    editor,state,job,calls,_=fixture(tmp_path,monkeypatch)
    editor._edit(state,job);old=cache_path(editor).read_bytes()
    from hotpost import scene_analysis
    if change=='observe_contract':monkeypatch.setattr(scene_analysis,'OBSERVE_INSTRUCTION',scene_analysis.OBSERVE_INSTRUCTION+' New actual frame contract.')
    elif change=='rank_contract':monkeypatch.setattr(scene_analysis,'RANK_INSTRUCTION',scene_analysis.RANK_INSTRUCTION+' New incompatible subject propagation.')
    elif change=='usage_limits':state['sources'][0]['functional_review']['context_usage_limits']=['Do not present a contact applicator as this spray']
    elif change=='geometry':state['sources'][0]['portrait_geometry']={'fit':'static-center-fill','expected_scale':1.1}
    elif change=='frame':editor.frame.write_bytes(b'new actual source frame')
    elif change=='source':
        source=state['sources'][0];Path(source['path']).write_bytes(b'new actual source video')
        source['sha256']=hashlib.sha256(Path(source['path']).read_bytes()).hexdigest()
        source['functional_review']['source_sha256']=source['sha256']
    elif change=='narration':
        script=state['scripts'][0];script['text']='This aerosol spray removes stains.'
        Path(script['path']).write_text(script['text'],encoding='utf-8')
    else:
        voice=state['voices'][0];Path(voice['path']).write_bytes(b'new actual approved voice')
        voice['sha256']=hashlib.sha256(Path(voice['path']).read_bytes()).hexdigest()
    result=editor._edit(state,job)
    assert len(calls)==2 and result['plan']['semantic_cache']['analysis_complete']
    assert (cache_path(editor).parent/'semantic-history'/('semantic-plan-'+hashlib.sha256(old).hexdigest()+'.json')).read_bytes()==old
    assert state['daily_quality']['repair_round']==2


@pytest.mark.parametrize('error',[ModelServiceUnavailable,ModelResponseInvalid])
def test_typed_semantic_failure_propagates_without_stamping_fallback_cache(tmp_path,monkeypatch,error):
    editor,state,job,calls,_=fixture(tmp_path,monkeypatch)
    editor._edit(state,job);old=cache_path(editor).read_bytes();render_count=len(editor.rendered)
    from hotpost import scene_analysis
    monkeypatch.setattr(scene_analysis,'RANK_INSTRUCTION',scene_analysis.RANK_INSTRUCTION+' New contract.')
    monkeypatch.setattr('hotpost.studio_ai.describe_shots',lambda *a,**k:(_ for _ in ()).throw(error()))
    with pytest.raises(error):editor._edit(state,job)
    assert cache_path(editor).read_bytes()==old and len(editor.rendered)==render_count
    assert state['daily_quality']['repair_round']==2


def test_tampered_semantic_output_is_not_reused_as_verified_plan(tmp_path,monkeypatch):
    editor,state,job,calls,_=fixture(tmp_path,monkeypatch);editor._edit(state,job)
    path=cache_path(editor);plan=json.loads(path.read_text(encoding='utf-8'));plan['beats'][0]['options']=[]
    path.write_text(json.dumps(plan),encoding='utf-8');raw=path.read_bytes()
    editor._edit(state,job)
    assert len(calls)==2
    assert (path.parent/'semantic-history'/('semantic-plan-'+hashlib.sha256(raw).hexdigest()+'.json')).read_bytes()==raw


def test_failed_or_missing_evidence_cache_cannot_be_reused_as_approval(tmp_path,monkeypatch):
    editor,state,job,calls,describe=fixture(tmp_path,monkeypatch)
    monkeypatch.setattr('hotpost.studio_ai.describe_shots',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('Observation failed')))
    editor._edit(state,job)
    assert not json.loads(cache_path(editor).read_text(encoding='utf-8'))['semantic_cache']['analysis_complete']
    monkeypatch.setattr('hotpost.studio_ai.describe_shots',describe);editor._edit(state,job)
    assert len(calls)==1
    editor.frame.unlink();editor._edit(state,job);editor._edit(state,job)
    assert len(calls)==3 # Unavailable actual frames never authorize cache reuse.


def test_changed_actual_source_or_voice_without_updated_identity_holds_before_render(tmp_path,monkeypatch):
    editor,state,job,calls,_=fixture(tmp_path,monkeypatch);editor._edit(state,job)
    Path(state['sources'][0]['path']).write_bytes(b'changed without approval')
    with pytest.raises(Conflict):editor._edit(state,job)
    assert len(calls)==1 and len(editor.rendered)==1
