import numpy as np
from hotpost.render_audio import compare

def test_missing_internal_audio_rejected_despite_metadata_duration():
    rate=2000;v=np.random.default_rng(13).normal(0,.08,rate*12)
    r=np.concatenate([v[:rate],v[rate*3:]])
    result=compare(r,v,rate)
    assert not result['passed'] and result['duration_delta_seconds']==-2

def test_effect_at_opening_does_not_displace_later_speech():
    rate=2000;v=np.random.default_rng(13).normal(0,.08,rate*12);r=v.copy()
    r[:rate]+=np.sin(np.arange(rate)*.2)*.05
    result=compare(r,v,rate)
    assert result['passed'] and all(a['offset_seconds']==0 for a in result['anchors'])
