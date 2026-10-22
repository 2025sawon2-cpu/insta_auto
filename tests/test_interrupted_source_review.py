import copy
import pytest

from hotpost.source_review_status import failed_outcome, is_transient, ReviewResponseInvalid
from hotpost.studio_pause import StudioPaused, PAUSE_MESSAGE, check_paused
from hotpost.scene_requirements import clear_cached_review_errors
from hotpost.source_overlay_review import needs_overlay_review, POLICY
from hotpost.studio_store import StudioStore


@pytest.mark.parametrize('legacy',[False,True])
@pytest.mark.parametrize('stage',['overlay','presentation'])
def test_interrupted_review_can_be_reexamined_but_never_approved_or_unpause_task(tmp_path,stage,legacy):
    source={'sha256':'actual-source','source_quality':'unknown','blur_required':True,'editing_eligible':False,
        stage+'_review_error':PAUSE_MESSAGE,'overlay_review_attempted_policy':POLICY,
        'overlay_review_attempted_sha256':'actual-source'}
    source['review_outcome']=failed_outcome(stage,StudioPaused(PAUSE_MESSAGE),source)
    if legacy:source['review_outcome'].update(status='unconfirmed',code='review_evidence_unconfirmed')
    saved=copy.deepcopy(source['review_outcome'])
    assert is_transient(source,stage)
    assert clear_cached_review_errors(source)
    assert source['editing_eligible'] is False and stage+'_review_error' not in source
    assert source['review_error_history'][-1]['outcome']==saved
    assert needs_overlay_review(source)
    store=StudioStore(tmp_path/'studio');state,_=store.create('interrupted','Test',
        {'active':False,'paused_by_user':True},prepare=False)
    with pytest.raises(StudioPaused):check_paused(store,{'task_id':state['id'],'kind':'collect_sources'})


@pytest.mark.parametrize('error',[ReviewResponseInvalid('missing actual frame'),ValueError('Not a cancellation')])
def test_real_invalid_or_unknown_review_is_not_unbounded_transient_retry(error):
    source={'sha256':'source','source_quality':'unknown','blur_required':True,'editing_eligible':False,
        'overlay_review_error':str(error),'overlay_review_attempted_policy':POLICY,
        'overlay_review_attempted_sha256':'source'}
    source['review_outcome']=failed_outcome('overlay',error,source);before=copy.deepcopy(source)
    assert not is_transient(source,'overlay') and not clear_cached_review_errors(source)
    assert not needs_overlay_review(source) and source==before
