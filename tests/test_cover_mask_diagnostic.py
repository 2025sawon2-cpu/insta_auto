import pytest
from hotpost.cover_selection import eligible_frames, cover_gap


def verdict(**changes):
    value={'id':'0','eligible':True,'faces_present':False,'face_blur_used':False,
        'hook_unresolved':True,'overlays_acceptable':True,'mask_coverage_valid':True,
        'product_view_preserved':True,'reason':'제품은 보이지만 완성 모습은 아직 드러나지 않음'}
    value.update(changes)
    return value


@pytest.mark.parametrize('field',['overlays_acceptable','mask_coverage_valid','product_view_preserved'])
@pytest.mark.parametrize('bad',[False,None,'true',1])
def test_uncropped_frame_must_pass_all_actual_pixel_gates(field,bad):
    assert eligible_frames([{'score':100}],[verdict(**{field:bad})])==[]


def test_core_mask_failure_is_not_relabelled_as_context_hook_failure():
    rows=[verdict(eligible=False,mask_coverage_valid=False,overlays_acceptable=False,
        reason='상단 중국어 삽입 글자가 읽힘'),verdict(id='1',eligible=False,hook_unresolved=False)]
    def forbidden(*args,**kwargs):pytest.fail('An actual mask failure must not trigger hook generation')
    gap=cover_gap(None,{'cover_spec':{'lines':['고정','문구']}},[{},{}],rows,forbidden,'사과')
    assert gap.issues[0]['scope']=='source_overlay' and gap.issues[0]['candidate_ids']==['0']
    assert gap.issues[0]['search_query']=='' and not gap.thumbnail_lines


def test_eligible_boolean_cannot_hide_unreadable_product_or_leaking_overlay():
    candidate={'score':10}
    assert eligible_frames([candidate],[verdict(overlays_acceptable=False)])==[]
    assert len(eligible_frames([candidate],[verdict()]))==1
