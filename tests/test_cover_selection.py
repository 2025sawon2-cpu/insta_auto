import copy
import pytest
from hotpost.cover_selection import eligible_frames, select_cover
from hotpost.daily_quality import QualitySceneGap

def review(**changes):
    return dict(id='0',eligible=True,faces_present=False,face_blur_used=False,
                hook_unresolved=True,overlays_acceptable=True,mask_coverage_valid=True,product_view_preserved=True,
                reason='닫힌 제품으로 숨은 사용 방법은 아직 드러나지 않음',**changes)

@pytest.mark.parametrize('field,value', [('faces_present',True),('faces_present',None),
    ('face_blur_used',True),('hook_unresolved',False),('eligible','true'),('reason','')])
def test_ambiguous_faces_blurred_faces_and_answered_hooks_cannot_qualify(field,value):
    row=review();row[field]=value
    assert eligible_frames([{'score':100}], [row])==[]

def test_unknown_ids_and_duplicate_conflicting_rows_do_not_override_rejection():
    first=review();first['faces_present']=True
    assert eligible_frames([{'score':100}], [first,review(),dict(review(),id='invented')])==[]

def fixture(tmp_path):
    frame=tmp_path/'actual.jpg';frame.write_bytes(b'actual frame')
    return {'script_text':'제품의 숨은 기능을 보여요.', 'cover_spec':{'lines':['이 물건','무슨 용도일까?']}},[
        {'score':1,'source_id':'actual','timestamp':1,'frame_path':str(frame)}]

def test_actual_frame_hash_and_copy_change_invalidate_cached_review(tmp_path):
    plan,candidates=fixture(tmp_path);calls=[]
    def generate(*args,**kwargs):calls.append(args[2]);return {'frames':[review()]}
    selected=select_cover(None,plan,candidates,tmp_path,generate)
    assert selected['cover_spec']['source']['reviewed'] and plan.get('cover_review_policy') is None
    select_cover(None,plan,candidates,tmp_path,generate);assert len(calls)==2
    plan['cover_spec']['lines'][0]='다른 질문'
    select_cover(None,plan,candidates,tmp_path,generate)
    (tmp_path/'actual.jpg').write_bytes(b'changed actual frame')
    select_cover(None,plan,candidates,tmp_path,generate);assert len(calls)==6

def test_no_eligible_frame_raises_scene_gap_without_sharpness_fallback(tmp_path):
    plan,candidates=fixture(tmp_path)
    with pytest.raises(QualitySceneGap):
        select_cover(None,plan,candidates,tmp_path,lambda *a,**k:{'frames':[dict(review(),faces_present=True)]})

def test_answered_copy_repairs_the_hook_without_recollecting_or_approving_frames(tmp_path):
    plan,candidates=fixture(tmp_path)
    def generate(settings,instruction,evidence,*,media):
        if evidence['purpose']=='cover_hook_repair':return {'thumbnail_lines':['제품의 다른 궁금증','새 질문을 남겨요']}
        return {'frames':[dict(review(),hook_unresolved=False)]}
    with pytest.raises(QualitySceneGap) as caught:select_cover(None,plan,candidates,tmp_path,generate)
    assert caught.value.issues[0]['kind']=='cover' and not caught.value.issues[0]['search_query']
    assert caught.value.thumbnail_lines==['제품의 다른 궁금증','새 질문을 남겨요']
    assert plan['cover_spec']['lines']==['이 물건','무슨 용도일까?']

def test_individual_review_can_reject_a_side_face_missed_in_batch(tmp_path):
    plan,candidates=fixture(tmp_path)
    second=tmp_path/'face-free.jpg';second.write_bytes(b'different actual frame')
    candidates[0]['score']=100
    candidates.append({**candidates[0],'score':1,'frame_path':str(second),'timestamp':2})
    calls=[]
    def generate(settings,instruction,evidence,*,media):
        calls.append(evidence)
        if evidence['purpose']=='cover_selection':return {'frames':[review(),dict(review(),id='1')]}
        return {'frames':[dict(review(),faces_present=evidence['candidate_id']=='0')]}
    result=select_cover(None,plan,candidates,tmp_path,generate)
    assert result['cover_spec']['source']['frame_path']==str(second)
    assert len(calls)==3
    select_cover(None,plan,candidates,tmp_path,generate)
    assert len(calls)==3  # Both rejection and confirmation survive a retry.

def test_workflow_selects_used_ranges_then_reviews_then_renders(tmp_path,monkeypatch):
    from hotpost.studio_workflow import WorkflowMixin
    from hotpost import cover_selection
    plan,candidates=fixture(tmp_path);calls=[]
    class Editor(WorkflowMixin):
        settings=None
        def folder(self,*a):return tmp_path
        def _process(self,state,job,action,payload):
            calls.append(action)
            if action=='select-shots':return {'plan':payload['plan']}
            if action=='cover-candidates':return {'candidates':candidates}
            assert payload['plan']['cover_spec']['source']['reviewed']
            return {'preview_path':'actual.mp4'}
    monkeypatch.setattr('hotpost.script_rewriter._generate',lambda *a,**k:{'frames':[review()]})
    assert Editor()._render_reviewed_cover({'id':'work'},{'id':'edit'},copy.deepcopy(plan))['preview_path']=='actual.mp4'
    assert calls==['select-shots','cover-candidates','render']
