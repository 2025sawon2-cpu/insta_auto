import pytest

from hotpost.studio_pause import StudioPaused,pause_scope
from hotpost.script_rewriter import _generate


def test_pause_after_one_model_call_prevents_following_cover_or_scene_calls(monkeypatch):
    calls=[];stopped=[False]
    def editorial(self,*args):
        calls.append(args);stopped[0]=True
        return {'saved_current_stage':True}
    monkeypatch.setattr('hotpost.studio_adapter.StudioAdapter.editorial',editorial)
    def boundary(*args):pass
    def check():
        if stopped[0]:raise StudioPaused('진행 중지')
    boundary.check_cancel=check
    with pause_scope(boundary):
        assert _generate(None,'first',{})=={'saved_current_stage':True}
        with pytest.raises(StudioPaused):_generate(None,'next cover',{})
    assert len(calls)==1
    # Other independent work must not inherit this task's stop callback.
    assert _generate(None,'unrelated',{})=={'saved_current_stage':True}
    assert len(calls)==2
