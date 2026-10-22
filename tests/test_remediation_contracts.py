import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_visual_query_plan_cannot_append_a_broad_caption_noun(monkeypatch):
    from hotpost import source_visual_queries
    from hotpost.source_queries import tiktok_product_queries
    approved=[{'query':'나사형 교체 지퍼 슬라이더'},{'query':'Screw replacement zipper slider'}]
    monkeypatch.setattr(source_visual_queries,'plan_queries',lambda plan:approved)
    plan={'visual_query_evidence':{'bound':True},'products':[{'ko':'지퍼'}],
          'query_details':[{'intent':'product','query':'지퍼','evidence_quote':'지퍼'}]}
    assert tiktok_product_queries(plan,['지퍼'])==[r['query'] for r in approved]


def test_bad_visual_binding_never_falls_back_to_broad_search(monkeypatch):
    from hotpost import source_visual_queries
    from hotpost.source_queries import tiktok_product_queries
    def reject(plan):raise ValueError('changed actual reference')
    monkeypatch.setattr(source_visual_queries,'plan_queries',reject)
    with pytest.raises(ValueError):tiktok_product_queries({'visual_query_evidence':{'bad':True}},['지퍼'])


@pytest.mark.parametrize('phase',['core_action','clean_action','scene_discovery'])
def test_all_provider_rounds_keep_the_same_verified_product_identity(monkeypatch,phase):
    from hotpost import source_visual_queries
    from hotpost.source_search.planner import round_queries
    approved=[{'query':'나사형 교체 지퍼 슬라이더','language':'ko','intent':'product','origin':'reference_visual'}]
    monkeypatch.setattr(source_visual_queries,'plan_queries',lambda plan:approved)
    plan={'visual_query_evidence':{'bound':True},'query_details':[
        {'query':'지퍼','language':'ko','intent':'product'},
        {'query':'지퍼 고치기','language':'ko','intent':'action','role':'subject_action','evidence_quote':'지퍼 고치기'}]}
    rows=round_queries(plan,{'phase':phase})
    assert len(rows)==1 and rows[0]['query'].startswith(approved[0]['query'])
    assert rows[0]['origin']=='reference_visual'


def test_invalid_visual_identity_also_blocks_non_tiktok_rounds(monkeypatch):
    from hotpost import source_visual_queries
    from hotpost.source_search.planner import round_queries
    def reject(plan):raise ValueError('changed actual reference')
    monkeypatch.setattr(source_visual_queries,'plan_queries',reject)
    with pytest.raises(ValueError):round_queries({'visual_query_evidence':{'bad':True},
        'query_details':[{'query':'지퍼','language':'ko','intent':'product'}]},{'phase':'core_action'})


@pytest.mark.parametrize('browser_mode',[True,False])
def test_verified_product_reaches_actual_provider_dispatch(monkeypatch,tmp_path,browser_mode):
    from hotpost import source_visual_queries,browser_search
    from hotpost.source_search.planner import round_queries
    from hotpost.source_search.discovery import discover
    from hotpost.source_finder import Candidate
    from hotpost.config import Settings
    product='Screw replacement zipper slider'
    rows=[{'query':product,'language':'en','intent':'product','origin':'reference_visual'}]
    monkeypatch.setattr(source_visual_queries,'plan_queries',lambda plan:rows)
    plan={'visual_query_evidence':{'bound':True},'query_details':[
        {'query':'지퍼','language':'ko','intent':'product'}]}
    queries=[r['query'] for r in round_queries(plan,{'phase':'clean_action'})]
    calls=[]
    def external(pool,*args):calls.extend(pool);return []
    def browser(settings,frames,pool,*args,**kwargs):
        calls.extend(pool)
        assert kwargs['provider_queries']['tiktok']==[product]
        return {'candidates':[],'terms':[],'notes':[],'searches':[]}
    monkeypatch.setattr(browser_search,'browser_search',browser)
    services=SimpleNamespace(Candidate=Candidate,search_local_cache=lambda *a:[],search_local_hints=lambda *a:[],
        search_web=external,search_bing=external,search_youtube=external,
        search_pexels=lambda settings,pool,*a:external(pool))
    discover(Settings(data_dir=tmp_path,source_browser_search=browser_mode),'ref',[],queries,plan,[],tmp_path,
             [],[],lambda *a:None,services)
    assert calls and all(q.startswith(product) for q in calls)


def test_transfer_receipt_keeps_both_failure_paths_without_media_secrets(tmp_path):
    from hotpost.source_transfer_trace import attach,event,finish
    from hotpost.source_attempts import transfer_diagnostics
    stats={'attempted':True};path=tmp_path/'transfer.json';attach(stats,path)
    event(stats,'reading_response_body',covered_bytes=100)
    stats['direct_error']='timeout https://cdn.example/video?token=private'
    child={'attempted':False,'_checkpoint':stats['_checkpoint']};stats['fallback']=child
    finish(child,error=RuntimeError('response blocked'))
    finish(stats,error=RuntimeError('fallback unavailable'))
    receipt=json.loads(path.read_text('utf8'))
    assert receipt['failure_stage']=='reading_response_body'
    assert receipt['covered_bytes']==100 and receipt['ended_at']>=receipt['started_at']
    assert receipt['fallback']['attempted'] is False and receipt['fallback']['error_type']=='RuntimeError'
    assert 'private' not in json.dumps(receipt) and '_checkpoint' not in json.dumps(receipt)
    assert receipt==transfer_diagnostics(stats)


def test_copy_correction_has_one_independent_comparison_and_preserves_script():
    from hotpost.thumbnail_copy import resolve_copy
    calls=[];old=['지퍼 하나 때문에','옷 한 벌을 예산에?'];new=['지퍼 하나 고장인데','새 옷부터 사려고요?']
    def ask(instruction,data,schema):
        calls.append(data)
        return {'preferred':1,'natural':True,'grounded':True,'reason':'상황과 질문이 이어짐'}
    result,receipt=resolve_copy(ask,old,'원래 원고','원본',
        {'natural':False,'reason':'의미가 끊김','problem_quote':'옷 한 벌을 예산에?','proposed_lines':new})
    assert result==new and len(calls)==1 and calls[0]['script']=='원래 원고'
    assert receipt['changed'] and receipt['script_sha256']==hashlib.sha256('원래 원고'.encode()).hexdigest()


def test_copy_correction_cannot_add_an_unsupported_benefit():
    from hotpost.thumbnail_copy import resolve_copy
    old=['첫 줄','문장이 끊겨']
    def ask(*_):return {'preferred':1,'natural':True,'grounded':False,'reason':'무료라는 사실 없음'}
    chosen,receipt=resolve_copy(ask,old,'본문','근거',
        {'natural':False,'problem_quote':'문장이 끊겨','proposed_lines':['첫 줄','모두 무료!']})
    assert chosen==old and receipt['changed'] is False


def test_short_noun_headline_does_not_require_a_repair_call():
    from hotpost.thumbnail_copy import resolve_copy
    lines=['버릴 뻔한 옷','문제는 지퍼 하나']
    selected,receipt=resolve_copy(lambda *_:pytest.fail('unnecessary model call'),lines,'원고','원본',
        {'natural':True,'problem_quote':'','proposed_lines':lines})
    assert selected==lines and receipt['status']=='evaluated'


def test_copy_report_must_quote_the_actual_defect():
    from hotpost.thumbnail_copy import resolve_copy
    with pytest.raises(ValueError,match='실제 문구'):
        resolve_copy(None,['문구','원본'],'본문','근거',
            {'natural':False,'problem_quote':'없는 글자','proposed_lines':['변경','제안']})


def test_top_pick_uses_variant_contract_and_actual_reference_frames(tmp_path,monkeypatch):
    from hotpost import studio_top_pick as pick
    reference=tmp_path/'reference.mp4';reference.write_bytes(b'bound reference')
    frame=tmp_path/'frame.jpg';frame.write_bytes(b'actual fixture image')
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    payload={'reference_script':'참고 원문','reference_video_sha256':sha(reference),
        'reference_visual_evidence':{'source_path':str(reference),'source_sha256':sha(reference),
        'frames':[{'frame_id':'1','source_timestamp':1.,'path':str(frame),'sha256':sha(frame)}]}}
    def generate(settings,instruction,evidence,**kw):
        assert 'A replaced hook mechanism must score below 3' not in instruction
        assert 'transformation_a/b' in instruction
        assert evidence['candidates'][0]['variant']['variant_type']=='transformation_a'
        assert evidence['reference_visual']['source_sha256']==sha(reference) and kw['media']
        return {'evaluations':[{'index':0,'eligible':True,'scores':dict(hook=5,grounding=5,narration=5),'reason':'새 장치','issues':[]}]}
    monkeypatch.setattr(pick,'_generate',generate)
    monkeypatch.setattr(pick,'refresh_local_reviews',lambda a,b,c:c)
    state={'id':'bound','original_text':'참고 원문','reference_video':str(reference),'writing_visual_payload':payload}
    selected,result=pick.choose(SimpleNamespace(data_dir=tmp_path),state,[(0,{'text':'다른 도입이에요','variant_type':'transformation_a'})])
    assert selected==0 and result['review_policy']==23
    frame.write_bytes(b'changed')
    from hotpost.writing.reference_evidence import VisualEvidenceIntegrityError
    with pytest.raises(VisualEvidenceIntegrityError):pick.choose(SimpleNamespace(data_dir=tmp_path),state,[(0,{'text':'다른 도입이에요'})])


def test_cover_copy_repair_bypasses_script_audio_and_shot_analysis(tmp_path):
    from hotpost.daily_quality import DailyQualityMixin
    plan={'cover_spec':{'lines':['기존','문구']},'beats':[{'id':'b','source_start':1,'source_end':2}],
          'voice':{'sha256':'voice'},'cues':[{'text':'본문'}]}
    path=tmp_path/'timeline.json';path.write_text(json.dumps(plan),'utf8');before=path.read_bytes()
    state={'script_id':'script','voice_id':'voice','edits':[{'id':'old','plan_path':str(path)}],
           'daily_quality':{'feedback':[{'kind':'cover'}],'thumbnail_lines':['바뀐','표지']}}
    seen=[]
    port=SimpleNamespace(_edit=lambda *a:pytest.fail('body analysis should not run'),
        render_feedback=lambda s,j,p:seen.append(p) or {'plan_path':'new'})
    result=DailyQualityMixin._quality_reedit(port,state,{'id':'repair','payload':{'edit_id':'old'}})
    assert seen[0]['beats']==plan['beats'] and seen[0]['voice']==plan['voice'] and seen[0]['cues']==plan['cues']
    assert seen[0]['cover_spec']['lines']==['바뀐','표지'] and result['parent_id']=='old'
    assert path.read_bytes()==before


def test_cover_copy_optimizer_rejects_any_body_selection_change(tmp_path):
    from hotpost.cover_frame_copy import render_if_cover_only
    path=tmp_path/'timeline.json';old={'beats':[{'source_start':0}], 'cover_spec':{'lines':['a','b']}}
    path.write_text(json.dumps(old),'utf8')
    state={'edits':[{'id':'old','plan_path':str(path)}],'daily_quality':{'feedback':[{'kind':'cover'}]}}
    port=SimpleNamespace(_process=lambda *a:pytest.fail('not a cover-only input'))
    changed={**old,'beats':[{'source_start':1}]}
    assert render_if_cover_only(port,state,{'payload':{'edit_id':'old'}},changed) is None
