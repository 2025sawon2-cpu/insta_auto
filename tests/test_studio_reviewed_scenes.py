import pytest
import copy
import json
import hashlib
from hotpost.studio_reviewed_scenes import apply_reviewed_scenes


@pytest.mark.parametrize('change',['voice','script','inventory','phrases','unreviewed','source_tamper','context','long_phrase'])
def test_voice_only_reuses_approved_used_windows_and_keeps_new_audio_clock(tmp_path,change):
    from hotpost.studio_reviewed_scenes import approved_voice_scenes
    from hotpost.daily_quality import POLICY
    source=tmp_path/'source.mp4';source.write_bytes(b'source')
    digest=hashlib.sha256(b'source').hexdigest()
    old={'script_text':'같은 대본','sources':[{'id':'s','path':str(source),'sha256':digest}],
         'shots':[{'id':'chosen','source_id':'s','path':str(source),'sha256':digest,'start':0,'end':20,
                   'context_usage_limits':['소재 성분 확정 불가']}],
         'beats':[{'id':'beat-1','text':'제품을 보세요','selected_shot_id':'chosen','source_start':8,'source_end':10,'relation':'context'}]}
    path=tmp_path/'old-plan.json';path.write_text(json.dumps(old),'utf8')
    video=tmp_path/'old.mp4';video.write_bytes(b'approved video')
    edit={'id':'old','voice_id':'old-voice','quality_verified':True,'plan_path':str(path),'export_path':str(video)}
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    state={'run_id':'new','voice_id':'new-voice','edits':[edit],
        'runs':[{'id':'parent','artifacts':{'edit_id':'old'}},{'id':'new','parent_id':'parent','inputs':{}}],
        'daily_quality':{'policy':POLICY,'reviews':[{'edit_id':'old','passed':True,'render_sha256':sha(video),'plan_sha256':sha(path)}]}}
    new=copy.deepcopy(old);new['voice']={'sha256':'new-audio'};new['beats'][0].update(start=0,end=1.8)
    new['shots'][0]['start']=30
    if change=='script':new['script_text']='바뀐 대본'
    if change=='inventory':new['sources'][0]['sha256']='another-source'
    if change=='phrases':new['beats'][0]['text']='다른 문장'
    if change=='unreviewed':edit['quality_verified']=False
    if change=='context':new['sources'][0]['usage_limits']=['새로운 사용 제한']
    if change=='long_phrase':new['beats'][0]['end']=2.3
    if change=='source_tamper':
        source.write_bytes(b'changed')
        with pytest.raises(ValueError,match='원본이 변경'):approved_voice_scenes(state,new)
        return
    result=approved_voice_scenes(state,new)
    if change!='voice':assert result is None;return
    assert result['voice']=={'sha256':'new-audio'} and result['beats'][0]['end']==1.8
    assert result['shots'][0]['start']==8 and result['shots'][0]['end']==10
    assert result['shots'][0]['context_usage_limits']==old['shots'][0]['context_usage_limits']
    assert result['approved_voice_scene_binding']['edit_id']=='old'
    assert new['shots'][0]['start']==30


def fixture():
    plan={'sources':[{'id':'s1','sha256':'hash','path':'source.mp4'}],
          'shots':[{'id':'old','sha256':'hash','start':0,'end':20}],
          'beats':[{'id':'beat-1','text':'내용을 적어요'},{'id':'beat-2','text':'댓글 남겨주세요'}]}
    rules=[{'reviewed':True,'source_sha256':'hash','pattern':'적어요','start':15,'end':17,
            'relation':'direct','reason':'펜으로 목록 칸에 쓰는 실제 장면','evidence_frames':['review.jpg']},
           {'reviewed':True,'source_sha256':'hash','pattern':'.','start':5,'end':9,
            'relation':'context','reason':'같은 제품의 전체 모습','evidence_frames':['review.jpg']}]
    return plan,rules


def test_reviewed_rules_match_actions_without_mutating_previous_plan():
    plan,rules=fixture();new=apply_reviewed_scenes(plan,rules)
    assert len(plan['shots'])==1 and len(new['shots'])==3
    assert new['shots'][-2]['start']==15
    assert new['beats'][0]['options'][0]['relation']=='direct'
    assert new['beats'][1]['options'][0]['relation']=='context'
    assert new['beats'][1]['options'][0]['reviewed'] is True


@pytest.mark.parametrize('change',[{'source_sha256':'other'},{'reviewed':False},{'end':21},
    {'start':float('nan')},{'evidence_frames':[]},{'relation':'invented'}])
def test_changed_or_unreviewed_sources_fail_before_render(change):
    plan,rules=fixture();rules[0].update(change)
    with pytest.raises(ValueError):apply_reviewed_scenes(plan,rules)


def test_missing_clause_mapping_is_not_replaced_with_default_cycle():
    plan,rules=fixture()
    with pytest.raises(ValueError):apply_reviewed_scenes(plan,rules[:1])


def test_unreviewed_gap_between_approved_windows_is_not_a_valid_rule():
    plan,rules=fixture()
    plan['shots']=[{'id':'a','sha256':'hash','start':0,'end':4},
                   {'id':'b','sha256':'hash','start':18,'end':20}]
    with pytest.raises(ValueError,match='승인 구간'):
        apply_reviewed_scenes(plan,rules)


def test_bounded_manual_shot_preserves_parent_and_function_limits():
    plan,rules=fixture()
    plan['shots'][0].update(parent_original_sha256='parent',creator_overlay_present=True,
        context_usage_limits=['State is visible; the opening action is not demonstrated.'])
    result=apply_reviewed_scenes(plan,rules)
    assert result['shots'][-1]['parent_original_sha256']=='parent'
    assert result['shots'][-1]['creator_overlay_present'] is True
    assert result['shots'][-1]['context_usage_limits']==plan['shots'][0]['context_usage_limits']
