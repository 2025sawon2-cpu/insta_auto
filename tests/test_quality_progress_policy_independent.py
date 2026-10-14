"""Independent adversarial checks of defect progress, with isolated actual files."""
import copy
import hashlib
import json
from pathlib import Path
import pytest

from hotpost import quality_progress as qp


def state_fixture(tmp_path):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'independent verified source fixture')
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    plan = {'script_text': '제품 사용. 제품 마무리.', 'voice': {'sha256': 'approved-voice'},
            'sources': [{'id': 'source', 'sha256': sha, 'url': 'https://youtu.be/abcdefghijk'}],
            'shots': [{'id': 'shot', 'source_id': 'source', 'start': 0, 'end': 5}],
            'beats': [{'id': 'use', 'text': '제품 사용.', 'selected_shot_id': 'shot', 'source_start': 0, 'source_end': 2},
                      {'id': 'finish', 'text': '제품 마무리.', 'selected_shot_id': 'shot', 'source_start': 2, 'source_end': 4}],
            'cover_spec': {'lines': ['원래 질문'], 'source': {'source_sha256': sha, 'source_timestamp': 1}}}
    path = tmp_path / 'baseline.json'
    path.write_text(json.dumps(plan), encoding='utf-8')
    issue = {'kind': 'scene_gap', 'beat_id': 'use', 'reason': '다른 도구를 단독 제품 효과로 보여줌'}
    state = {'edit_id': 'baseline', 'edits': [{'id': 'baseline', 'plan_path': str(path)}],
             'sources': [{**plan['sources'][0], 'path': str(source)}],
             'automation': {'active': True},
             'daily_quality': {'repair_round': 4, 'max_repairs': 3, 'feedback': [issue], 'reviews': []}}
    return state, plan


def review(state, plan, tmp_path, identity, issues, *, score=1):
    path = tmp_path / (identity + '.json')
    path.write_text(json.dumps(plan), encoding='utf-8')
    if not any(e['id'] == identity for e in state['edits']):
        state['edits'].append({'id': identity, 'plan_path': str(path)})
    state['edit_id'] = identity
    value = {'edit_id': identity, 'render_sha256': hashlib.sha256(identity.encode()).hexdigest(),
             'plan_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
             'passed': not issues, 'issues': issues, 'score': score}
    result = qp.observe(state, value)
    state['daily_quality']['feedback'] = copy.deepcopy(issues)
    return result, value


def test_same_defect_survives_reason_changes_and_beat_reordering(tmp_path):
    state, plan = state_fixture(tmp_path)
    issue = copy.deepcopy(state['daily_quality']['feedback'][0])
    review(state, plan, tmp_path, 'first', [issue])
    moved = copy.deepcopy(plan)
    moved['beats'].reverse()
    moved['beats'][1]['id'] = 'renumbered-use'
    issue.update(beat_id='renumbered-use', reason='제품에 다른 후처리 도구의 효과를 잘못 연결')
    row, _ = review(state, moved, tmp_path, 'second', [issue], score=99)
    ledger = state['daily_quality']['progress_policy']
    assert len(ledger['defects']) == 1
    assert not row['resolved'] and not row['improved']
    assert ledger['best']['edit_id'] == 'first'


def test_paraphrased_narration_does_not_resolve_unchanged_wrong_product_footage(tmp_path):
    state,plan=state_fixture(tmp_path)
    review(state,plan,tmp_path,'original',state['daily_quality']['feedback'])
    candidate=copy.deepcopy(plan)
    candidate['beats'][0].update(id='new-beat-id',text='제품을 사용하는 모습.')
    candidate['script_text']='제품을 사용하는 모습. 제품 마무리.'
    row,_=review(state,candidate,tmp_path,'paraphrase',[])
    assert row['conflict'] and not row['passed'] and not row['improved']


def test_unrelated_new_source_and_metadata_do_not_ground_a_repair(tmp_path):
    state, plan = state_fixture(tmp_path)
    review(state, plan, tmp_path, 'first', state['daily_quality']['feedback'])
    state['sources'].append({'id': 'unrelated', 'sha256': 'new-file'})
    state['daily_quality']['review_policy'] = 'new-code'
    state['daily_quality']['checked_at'] = 999
    assert qp.permit(state, 'reedit') is None
    candidate = copy.deepcopy(plan)
    candidate['sources'].append({'id': 'unrelated', 'sha256': 'new-file'})
    candidate['beats'][1]['source_start'] = 3  # Only the unaffected finish changes.
    assert qp.guard_render(state, candidate, 'new-job') is not None


def test_valid_cover_change_can_continue_after_four_actual_repairs(tmp_path):
    state, plan = state_fixture(tmp_path)
    state['daily_quality']['feedback'] = [{'kind': 'cover', 'reason': '이미지가 답을 미리 공개함'}]
    state['daily_quality']['thumbnail_lines'] = ['새로운 제품 질문']
    before = copy.deepcopy(state['daily_quality'])
    assert qp.permit(state, 'reedit', reserve=True, job_id='fifth-render')
    assert state['daily_quality']['repair_round'] == before['repair_round'] == 4
    assert state['daily_quality']['max_repairs'] == before['max_repairs'] == 3


def test_one_failed_method_and_a_b_a_cycle_are_blocked_before_render(tmp_path):
    state, _ = state_fixture(tmp_path)
    state['daily_quality']['feedback'] = [{'kind': 'cover', 'reason': '답 공개'}]
    state['daily_quality']['thumbnail_lines'] = ['질문 A']
    method_a = qp.permit(state, 'reedit', reserve=True, job_id='job-a')
    assert method_a
    qp.finish_attempt(state, {'id': 'job-a'}, failed=True)
    assert not qp.permit(state, 'reedit', reserve=True, job_id='job-a-again')
    state['daily_quality']['thumbnail_lines'] = ['질문 B']
    assert qp.permit(state, 'reedit', reserve=True, job_id='job-b')
    qp.finish_attempt(state, {'id': 'job-b'}, failed=True)
    state['daily_quality']['thumbnail_lines'] = ['질문 A']
    assert not qp.permit(state, 'reedit', reserve=True, job_id='new-run-job-a')
    assert state['daily_quality']['repair_round'] == 4


def test_resolution_plus_new_blocking_regression_preserves_best_result(tmp_path):
    state, plan = state_fixture(tmp_path)
    review(state, plan, tmp_path, 'first', state['daily_quality']['feedback'])
    candidate = copy.deepcopy(plan)
    candidate['beats'][0]['source_start'] = 1
    regression = {'kind': 'watermark', 'beat_id': 'finish', 'reason': '읽히는 삽입 문구'}
    row, _ = review(state, candidate, tmp_path, 'candidate', [regression])
    assert row['resolved'] and row['introduced'] and not row['improved']
    assert state['daily_quality']['progress_policy']['best']['edit_id'] == 'first'


def test_higher_score_and_fewer_findings_without_target_change_are_conflict(tmp_path):
    state, plan = state_fixture(tmp_path)
    review(state, plan, tmp_path, 'first', state['daily_quality']['feedback'], score=1)
    candidate = copy.deepcopy(plan)
    candidate['beats'][1]['source_start'] = 3
    row, _ = review(state, candidate, tmp_path, 'higher-score', [], score=100)
    assert row['conflict'] and not row['improved'] and not row['passed']
    assert state['daily_quality']['progress_policy']['best']['edit_id'] == 'first'


def test_an_unresolved_conflict_cannot_pass_by_reviewing_same_output_under_new_id(tmp_path):
    state,plan=state_fixture(tmp_path)
    review(state,plan,tmp_path,'original',state['daily_quality']['feedback'])
    first,_=review(state,plan,tmp_path,'disagreement-one',[])
    assert first['conflict'] and not first['passed']
    again,_=review(state,plan,tmp_path,'disagreement-two',[])
    assert again['conflict'] and not again['passed']
    assert state['daily_quality']['progress_policy']['best']['edit_id']=='original'


def test_duplicate_review_completion_is_idempotent_and_contradiction_is_recheck(tmp_path):
    state, plan = state_fixture(tmp_path)
    _, result = review(state, plan, tmp_path, 'first', state['daily_quality']['feedback'])
    ledger = state['daily_quality']['progress_policy']
    frozen = copy.deepcopy(ledger)
    assert qp.observe(state, {**result, 'checked_at': 999, 'score': 100})['duplicate']
    assert ledger == frozen
    changed = {**result, 'passed': True, 'issues': []}
    assert qp.observe(state, changed)['conflict']
    assert ledger['decision']['action'] == 'recheck'
    assert ledger['best'] == frozen['best'] and len(ledger['reviews']) == 1


def test_noise_after_dense_confirmation_cannot_reopen_same_output_as_new_defect(tmp_path):
    state,plan=state_fixture(tmp_path)
    original_issue=copy.deepcopy(state['daily_quality']['feedback'])
    _,original=review(state,plan,tmp_path,'first',original_issue)
    confirmed={**original,'passed':True,'issues':[], 'evidence_recheck':True,
               'recheck_evidence':{'render_sha256':original['render_sha256'],'frames':['dense-actual-frames']}}
    assert qp.observe(state,confirmed)['passed']
    state['daily_quality']['feedback']=[]
    noise=qp.observe(state,original)
    assert noise.get('conflict') or noise.get('duplicate')
    assert state['daily_quality']['progress_policy']['best']['passed']
    assert all(d['status']=='resolved' for d in state['daily_quality']['progress_policy']['defects'].values())


def test_reencoded_source_same_origin_window_does_not_change_repair(tmp_path):
    state, plan = state_fixture(tmp_path)
    review(state, plan, tmp_path, 'first', state['daily_quality']['feedback'])
    candidate = copy.deepcopy(plan)
    candidate['sources'][0].update(id='new-filename', sha256='new-encoding-sha',
                                 url='https://youtube.com/shorts/abcdefghijk')
    candidate['shots'][0]['source_id'] = 'new-filename'
    assert qp.same_output(qp.projection(candidate),qp.projection(plan))
    assert qp.guard_render(state, candidate, 'attempt-reencoding')


def test_known_parent_sha_derivative_and_raw_url_share_the_same_failed_window(tmp_path):
    state,plan=state_fixture(tmp_path)
    review(state,plan,tmp_path,'first',state['daily_quality']['feedback'])
    candidate=copy.deepcopy(plan)
    source=candidate['sources'][0]
    source.update(sha256='derivative-sha',original_sha256=plan['sources'][0]['sha256'],
                  original_url=source['url'],original_interval={'start':0,'end':4},
                  retiming={'playback_rate':1})
    assert qp.same_output(qp.projection(candidate),qp.projection(plan))
    assert qp.guard_render(state,candidate,'attempt-known-parent')
    row,_=review(state,candidate,tmp_path,'reencoded-verdict',[])
    assert row['conflict'] and not row['improved'] and not row['passed']


def test_explicit_resume_cannot_reopen_failed_method_by_adding_known_source_url(tmp_path):
    from test_scene_requirement_intervals import approved,coverage
    from hotpost.scene_requirements import assess
    from hotpost.config import Settings
    state=approved(tmp_path)
    state['automation']={'active':False}
    state['daily_quality']['scene_requirements']=assess(Settings(data_dir=tmp_path),state,
        generate=lambda *args,**kwargs:coverage(state['sources'][0]))
    assert qp.permit(state,'reedit',reserve=True,job_id='failed-method')
    qp.finish_attempt(state,{'id':'failed-method'},failed=True)
    state['daily_quality']['pending']='exhausted'
    # URL metadata added to exactly the same bound file cannot be new footage.
    state['sources'][0]['original_url']='https://youtu.be/abcdefghijk'
    assert not qp.resume_assessment(state)
    assert state['daily_quality']['pending']=='exhausted'


def test_missing_plan_preserves_existing_best_and_accounting(tmp_path):
    state, plan = state_fixture(tmp_path)
    review(state, plan, tmp_path, 'first', state['daily_quality']['feedback'])
    best = copy.deepcopy(state['daily_quality']['progress_policy']['best'])
    state['edits'].append({'id': 'missing', 'plan_path': str(tmp_path / 'missing.json')})
    row = qp.observe(state, {'edit_id': 'missing', 'passed': True, 'issues': []})
    assert row['missing_evidence'] and not row['passed']
    assert state['daily_quality']['progress_policy']['best'] == best
    assert state['daily_quality']['repair_round'] == 4


def test_legacy_exhausted_and_user_stop_cannot_be_reset_by_policy_migration(tmp_path):
    state, _ = state_fixture(tmp_path)
    state['daily_quality'].update(pending='exhausted', render_accounting=[{'repair_charge': 1}])
    state['automation'].update(active=False, paused_by_user=True)
    state['daily_quality']['feedback'] = [{'kind': 'cover', 'reason': '답 공개'}]
    state['daily_quality']['thumbnail_lines'] = ['다른 질문']
    before = copy.deepcopy(state)
    ledger = qp.ensure(state)
    assert not qp.permit(state, 'reedit')
    assert state['automation'] == before['automation']
    for key in ('pending', 'repair_round', 'max_repairs', 'render_accounting'):
        assert state['daily_quality'][key] == before['daily_quality'][key]
    assert ledger['legacy']['pending'] == 'exhausted'


def test_cover_receipt_strings_without_actual_pixels_are_not_repair_evidence(tmp_path):
    state, _ = state_fixture(tmp_path)
    state['daily_quality']['feedback'] = [{'kind': 'scene_gap', 'beat_id': '', 'scope': 'cover', 'reason': '얼굴 없는 표지 없음'}]
    state['daily_quality']['cover_repair_evidence'] = {'reviewed': True, 'image_sha256': 'made-up',
        'source_sha256': state['sources'][0]['sha256'], 'source_timestamp': 1, 'rectangle': [0, 0, 20, 20]}
    assert qp.permit(state, 'reedit') is None


@pytest.mark.parametrize('problem',['visible-face','invalid-time','changed-mask'])
def test_cover_receipt_must_bind_eligibility_actual_time_and_mask(tmp_path,problem):
    from test_scene_requirement_intervals import approved
    state=approved(tmp_path)
    state['daily_quality']['feedback']=[{'kind':'scene_gap','scope':'cover','beat_id':'','reason':'표지 없음'}]
    state['sources'][0]['video_meta']={'duration':4,'width':720,'height':1280}
    source=state['sources'][0];frame=source['mask_review']['evidence_frames'][0]
    receipt={'reviewed':True,'source_sha256':source['sha256'],'source_timestamp':1,
        'image_path':frame['path'],'image_sha256':frame['sha256'],'watermark_masks':[],
        'selection':{'source_sha256':source['sha256'],'source_id':source['id'],
            'timestamp':1,'frame_path':frame['path'],'frame_sha256':frame['sha256'],
            'single_frame_confirmation':{'eligible':True,'faces_present':False,'face_blur_used':False}}}
    if problem=='visible-face':
        receipt['selection']['single_frame_confirmation'].update(eligible=False,faces_present=True)
    elif problem=='invalid-time':
        receipt.update(source_timestamp=500)
        receipt['selection']['timestamp']=500
    else:
        source['watermark_masks']=[{'rectangle':[0,0,.5,.5],'source_start':0,'source_end':4}]
    state['daily_quality']['cover_repair_evidence']=receipt
    assert qp.permit(state,'reedit') is None
