import copy
import hashlib
import json
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.daily_quality import QualitySceneGap
from hotpost.model_service import ModelServiceUnavailable
from hotpost.scene_narration_prepare import NarrationContextHold, prepare_narration_context
from hotpost.scene_requirement_context import build_scene_requirement_context
from hotpost.scene_requirements import required_scenes
from test_scene_requirement_intervals import approved


def mixed(tmp_path):
    state = approved(tmp_path)
    state.update(id='work', voice_id='voice-B')
    state['scripts'].append({'id':'script-A', 'text':state['scripts'][0]['text']})
    state['edits'][0]['script_id'] = 'script-A'
    state['scripts'][0]['text'] = '이 매트는 끝을 틈새에 끼워요.'
    voice = tmp_path/'voice-B.wav';voice.write_bytes(b'actual B voice')
    state['voices'] = [{'id':'voice-B','script_id':'script','path':str(voice),
        'sha256':hashlib.sha256(voice.read_bytes()).hexdigest(),
        'script_sha256':hashlib.sha256(state['scripts'][0]['text'].encode()).hexdigest(),
        'spoken_text':state['scripts'][0]['text']}]
    state['daily_quality'].update(repair_round=2,max_repairs=3)
    state['automation'] = {'active':True}
    plan = {'script_text':state['scripts'][0]['text'], 'beats':[
        {'id':'new-owner','text':'이 매트는','start':0,'end':1},
        {'id':'new-action','text':'끝을 틈새에 끼워요.','start':1,'end':2}], 'shots':[]}
    return state, plan


def mapping():
    return {'mappings':[{'index':0,'beat_ids':['new-action'],
        'narration_quote':'끝을 틈새에 끼워요.','reason':'Same mat end insertion action explicitly remains in new approved narration'}]}


class Studio:
    def __init__(self,tmp_path,state,plan):
        self.root=tmp_path;self.state=state;self.plan=plan;self.calls=[]
        self.settings=Settings(data_dir=tmp_path)
        self.store=self
    def folder(self,identity):return self.root
    def change(self,identity,callback):callback(self.state,None)
    def _source_records(self,paths,manifest,records):return copy.deepcopy(records)
    def _process(self,state,job,action,payload):
        self.calls.append(action)
        assert action=='analyze', 'Fresh context must never invoke render'
        assert payload['script']['id']=='script' and payload['voice']['id']=='voice-B'
        return {'plan':copy.deepcopy(self.plan)}


def job(identity='prepare-1'):
    return {'id':identity,'payload':{'daily_quality_repair':True,'voice_id':'voice-B','script_id':'script'},'checkpoint':{}}


def test_fresh_local_analysis_remaps_new_actual_beats_preserving_original_artifacts_and_cap(tmp_path):
    state,plan=mixed(tmp_path);studio=Studio(tmp_path,state,plan)
    old=copy.deepcopy(state['edits']);old_bytes=Path(old[0]['plan_path']).read_bytes();calls=[]
    def generate(*args,**kwargs):calls.append(args[2]);return mapping()
    assert not build_scene_requirement_context(state,required_scenes(state))['verified']
    assert prepare_narration_context(studio,state,job(),generate=generate)
    assert studio.calls==['analyze'] and len(calls)==1
    assert calls[0]['old_requirements'][0]['old_beat']['text']=='Observed action.'
    assert required_scenes(state)[0]['beat_id']=='new-action'
    assert required_scenes(state)[0]['narration_remap']['from_beat_id']=='b1'
    assert build_scene_requirement_context(state,required_scenes(state))['verified']
    assert state['edit_id']=='edit' and state['edits']==old and Path(old[0]['plan_path']).read_bytes()==old_bytes
    assert (state['daily_quality']['repair_round'],state['daily_quality']['max_repairs'])==(2,3)
    assert not prepare_narration_context(studio,state,job('new-job'),generate=lambda *a:pytest.fail('Already verified context'))
    assert studio.calls==['analyze']


def test_ambiguous_remap_is_durable_hold_without_repeating_analysis_or_model(tmp_path):
    state,plan=mixed(tmp_path);studio=Studio(tmp_path,state,plan);before=copy.deepcopy(state['daily_quality']['feedback'])
    with pytest.raises(NarrationContextHold):prepare_narration_context(studio,state,job(),generate=lambda *a:{'mappings':[]})
    with pytest.raises(NarrationContextHold):prepare_narration_context(studio,state,job('restart'),generate=lambda *a:pytest.fail('Same confirmed failure'))
    assert studio.calls==['analyze'] and state['daily_quality']['feedback']==before
    assert state['daily_quality']['repair_round']==2 and not state.get('scene_narration_plan')
    assert next(iter(state['daily_quality']['narration_preparations'].values()))['status']=='held'


def test_capacity_wait_resumes_saved_analysis_in_new_job_without_false_failure(tmp_path):
    state,plan=mixed(tmp_path);studio=Studio(tmp_path,state,plan)
    def busy(*args):raise ModelServiceUnavailable('capacity',attempted=True)
    with pytest.raises(ModelServiceUnavailable):prepare_narration_context(studio,state,job(),generate=busy)
    assert not state['daily_quality'].get('narration_preparations')
    assert studio.calls==['analyze'] and state['daily_quality']['repair_round']==2
    assert prepare_narration_context(studio,state,job('restart'),generate=lambda *args:mapping())
    assert studio.calls==['analyze']


@pytest.mark.parametrize('invalid',['old-id','quote','duplicate','garbage'])
def test_remap_requires_explicit_actual_new_beat_ids_exact_narration_and_unique_response(tmp_path,invalid):
    state,plan=mixed(tmp_path);studio=Studio(tmp_path,state,plan);value=mapping()
    if invalid=='old-id':value['mappings'][0]['beat_ids']=['b1']
    if invalid=='quote':value['mappings'][0]['narration_quote']='Other part'
    if invalid=='duplicate':value['mappings'].append(copy.deepcopy(value['mappings'][0]))
    if invalid=='garbage':value={'mappings':[{'index':0,'beat_ids':[{}]}]}
    with pytest.raises(NarrationContextHold):prepare_narration_context(studio,state,job(),generate=lambda *args:value)
    assert not state.get('scene_narration_plan')


def test_user_feedback_changed_during_model_review_is_not_overwritten(tmp_path):
    worker,plan=mixed(tmp_path);persisted=copy.deepcopy(worker);studio=Studio(tmp_path,persisted,plan)
    def generate(*args):
        persisted['daily_quality']['feedback']=[{'kind':'scene_gap','beat_id':'b1','reason':'new user finding'}]
        persisted['daily_quality']['repair_round']=3
        return mapping()
    with pytest.raises(NarrationContextHold):prepare_narration_context(studio,worker,job(),generate=generate)
    assert persisted['daily_quality']['feedback'][0]['reason']=='new user finding'
    assert persisted['daily_quality']['repair_round']==3 and not persisted.get('scene_narration_plan')


def test_current_fixed_script_needs_no_fresh_analysis(tmp_path):
    state=approved(tmp_path);studio=Studio(tmp_path,state,{})
    assert not prepare_narration_context(studio,state,job(),generate=lambda *a:pytest.fail('No remap for unchanged script'))
    assert studio.calls==[]


def test_wrong_spoken_voice_or_wrong_parent_edit_cannot_approve_prepared_context(tmp_path):
    state,plan=mixed(tmp_path);studio=Studio(tmp_path,state,plan)
    state['voices'][0]['spoken_text']='old A voice text'
    with pytest.raises(NarrationContextHold):prepare_narration_context(studio,state,job(),generate=lambda *a:pytest.fail('Wrong voice'))
    state['voices'][0]['spoken_text']=state['scripts'][0]['text']
    prepare_narration_context(studio,state,job(),generate=lambda *a:mapping())
    state['scene_narration_plan']['old_edit_id']='different-A'
    assert not build_scene_requirement_context(state,required_scenes(state))['verified']


def test_refresh_does_not_search_when_remap_is_unresolved(tmp_path,monkeypatch):
    from hotpost.studio_runtime.generation import GenerationMixin
    from hotpost import script_rewriter,source_finder
    state,plan=mixed(tmp_path)
    class RefreshStudio(GenerationMixin,Studio):pass
    studio=RefreshStudio(tmp_path,state,plan)
    monkeypatch.setattr(script_rewriter,'_generate',lambda *a,**k:{'mappings':[]})
    monkeypatch.setattr(source_finder,'find_sources',lambda *a,**k:pytest.fail('No search to solve unclear narration remap'))
    with pytest.raises(NarrationContextHold):studio._refresh_sources(state,job())
    assert studio.calls==['analyze'] and state['daily_quality']['repair_round']==2


def test_edit_prepares_current_narration_but_still_refuses_render_without_actual_scene_coverage(tmp_path,monkeypatch):
    from hotpost.studio_runtime.editing import EditingMixin
    from hotpost import script_rewriter
    state,plan=mixed(tmp_path)
    class Editor(Studio,EditingMixin):pass
    studio=Editor(tmp_path,state,plan);calls=[]
    def generate(settings,instruction,evidence,**kwargs):
        calls.append(evidence)
        return mapping() if 'old_requirements' in evidence else {'requirements':[{'index':0,'covered':False,'reason':'Missing actual matching footage'}]}
    monkeypatch.setattr(script_rewriter,'_generate',generate)
    with pytest.raises(QualitySceneGap):studio._edit(state,job())
    assert studio.calls==['analyze'] and len(calls)==2
    assert calls[-1]['narration_context']['verified']
    assert calls[-1]['narration_context']['requirement_contexts'][0]['narration']=='끝을 틈새에 끼워요.'
    assert state['daily_quality']['repair_round']==2


def test_refresh_fresh_context_reuses_existing_approved_scene_without_external_search(tmp_path,monkeypatch):
    from hotpost.studio_runtime.generation import GenerationMixin
    from hotpost import script_rewriter,source_finder
    state,plan=mixed(tmp_path)
    class RefreshStudio(GenerationMixin,Studio):pass
    studio=RefreshStudio(tmp_path,state,plan)
    def generate(settings,instruction,evidence,**kwargs):
        if 'old_requirements' in evidence:return mapping()
        from test_scene_requirement_intervals import coverage
        return coverage(state['sources'][0])
    monkeypatch.setattr(script_rewriter,'_generate',generate)
    monkeypatch.setattr(source_finder,'find_sources',lambda *a,**k:pytest.fail('Existing reviewed scene is sufficient'))
    result=studio._refresh_sources(state,job())
    assert result['scene_requirements']['ready'] and result['local_narration_preparation']
    assert result['sources']==result['searches']==result['attempted_urls']==[]
    assert studio.calls==['analyze'] and state['daily_quality']['repair_round']==2


def test_edit_resumes_capacity_during_source_preflight_without_repeating_local_analysis(tmp_path,monkeypatch):
    from hotpost.studio_runtime.editing import EditingMixin
    from hotpost import script_rewriter
    state,plan=mixed(tmp_path)
    class Editor(Studio,EditingMixin):pass
    studio=Editor(tmp_path,state,plan);calls=[]
    def busy(settings,instruction,evidence,**kwargs):
        if 'old_requirements' in evidence:return mapping()
        raise ModelServiceUnavailable('source preflight capacity')
    monkeypatch.setattr(script_rewriter,'_generate',busy)
    with pytest.raises(ModelServiceUnavailable):studio._edit(state,job())
    def missing(settings,instruction,evidence,**kwargs):
        assert 'old_requirements' not in evidence
        calls.append(evidence);return {'requirements':[{'index':0,'covered':False,'reason':'Actual footage missing'}]}
    monkeypatch.setattr(script_rewriter,'_generate',missing)
    with pytest.raises(QualitySceneGap):studio._edit(state,job('restart'))
    assert studio.calls==['analyze'] and len(calls)==1 and state['daily_quality']['repair_round']==2


def test_explicit_current_run_pronunciation_correction_preserves_approved_script_binding(tmp_path):
    state,plan=mixed(tmp_path);studio=Studio(tmp_path,state,plan)
    state['run_id']='run'
    state['runs']=[{'id':'run','inputs':{'pronunciations':[{'from':'매트','to':'메트'}]}}]
    state['voices'][0]['spoken_text']=state['scripts'][0]['text'].replace('매트','메트')
    assert prepare_narration_context(studio,state,job(),generate=lambda *a:mapping())
    assert build_scene_requirement_context(state,required_scenes(state))['verified']


def test_user_stop_or_cap_change_during_source_preflight_cannot_commit_stale_coverage(tmp_path,monkeypatch):
    from hotpost.studio_runtime.editing import EditingMixin
    from hotpost import script_rewriter
    from test_scene_requirement_intervals import coverage
    worker,plan=mixed(tmp_path);persisted=copy.deepcopy(worker)
    class Editor(Studio,EditingMixin):pass
    studio=Editor(tmp_path,persisted,plan)
    def generate(settings,instruction,evidence,**kwargs):
        if 'old_requirements' in evidence:return mapping()
        persisted['automation']['active']=False
        persisted['daily_quality']['repair_round']=3
        return coverage(worker['sources'][0])
    monkeypatch.setattr(script_rewriter,'_generate',generate)
    with pytest.raises(NarrationContextHold):studio._edit(worker,job())
    assert studio.calls==['analyze']
    assert persisted['daily_quality']['repair_round']==3 and not persisted['automation']['active']
    assert not persisted['daily_quality'].get('scene_requirements',{}).get('ready')


def test_actual_worker_lane_holds_ambiguous_remap_without_new_qa_or_collection_loop(tmp_path,monkeypatch):
    from hotpost.studio import Studio as RealStudio
    from hotpost import script_rewriter
    initial,plan=mixed(tmp_path);seen=[]
    class Worker(RealStudio):
        def _source_records(self,paths,manifest,records):return copy.deepcopy(records)
        def _process(self,state,job,action,payload):
            seen.append(action);assert action=='analyze'
            return {'plan':copy.deepcopy(plan)}
        def _refresh_sources(self,state,job):
            try:return super()._refresh_sources(state,job)
            finally:self.stop.set()
    studio=Worker(Settings(data_dir=tmp_path/'isolated-worker'),workers=False)
    created,_=studio.store.create('mixed-hold-worker','Mixed rewrite hold',prepare=False)
    initial['id']=created['id']
    before=copy.deepcopy(initial['daily_quality']['feedback'])
    def setup(state,db):
        state.update(copy.deepcopy(initial))
        studio.store.enqueue(db,state['id'],'refresh_sources',{'daily_quality_repair':True},'typed-remap-hold')
    studio.store.change(created['id'],setup)
    monkeypatch.setattr(script_rewriter,'_generate',lambda *a,**k:{'mappings':[]})
    studio._worker('sources')
    saved=studio.store.get(created['id']);jobs=studio.store.jobs(created['id'])
    assert seen==['analyze'] and len(jobs)==1 and jobs[0]['status']=='failed'
    assert saved['daily_quality'].get('pending')=='scene_wait', jobs
    assert saved['daily_quality']['feedback']==before and saved['edit_id']=='edit'
    assert (saved['daily_quality']['repair_round'],saved['daily_quality']['max_repairs'])==(2,3)
    assert not saved['automation']['active'] and saved['status']=='attention'
    assert not saved['daily_quality'].get('reviews')
    assert not saved.get('source_acquisition',{}).get('rounds')


def test_local_preparation_acceptance_preserves_external_rounds_and_render_counter(tmp_path,monkeypatch):
    from hotpost.studio_runtime.generation import GenerationMixin
    from hotpost.studio_runtime.lifecycle import LifecycleMixin
    from hotpost import script_rewriter
    from test_scene_requirement_intervals import coverage
    state,plan=mixed(tmp_path);state['source_acquisition']={'rounds':[{'job_id':'old-external'}], 'bounded_rounds':2}
    state['daily_quality']['collection_attempt']=4
    advanced=[]
    class LocalStudio(GenerationMixin,LifecycleMixin,Studio):
        def advance_workflow(self,state,db):advanced.append('advance')
    studio=LocalStudio(tmp_path,state,plan)
    def generate(settings,instruction,evidence,**kwargs):
        return mapping() if 'old_requirements' in evidence else coverage(state['sources'][0])
    monkeypatch.setattr(script_rewriter,'_generate',generate)
    task=job();task['kind']='refresh_sources'
    result=studio._refresh_sources(state,task)
    studio._accept(state,task,result)
    assert state['source_acquisition']['rounds']==[{'job_id':'old-external'}]
    assert state['source_acquisition']['bounded_rounds']==2
    assert state['source_acquisition']['local_narration_preparations'][0]['external_search_attempted'] is False
    assert state['daily_quality']['collection_attempt']==4 and state['daily_quality']['local_context_attempt']==1
    assert state['daily_quality']['repair_round']==2 and advanced==['advance']


def test_parent_plan_file_changed_during_remap_is_held_using_pre_call_identity(tmp_path):
    state,plan=mixed(tmp_path);studio=Studio(tmp_path,state,plan)
    before=copy.deepcopy(state['daily_quality']['feedback'])
    def generate(*args):
        path=Path(state['edits'][0]['plan_path'])
        original=json.loads(path.read_text('utf-8'));original['cover_text']='changed during review'
        path.write_text(json.dumps(original),encoding='utf-8')
        return mapping()
    with pytest.raises(NarrationContextHold):prepare_narration_context(studio,state,job(),generate=generate)
    assert state['daily_quality']['feedback']==before and not state.get('scene_narration_plan')
