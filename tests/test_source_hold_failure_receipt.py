"""Exercise the real acquisition exception boundary, without media approval.
The external-work sub-entry is interrupted after publishing a deep copy of the
captured manifest. Task/run, candidate fields and failure stage are retained.
This local regression covers classification only; it does not grant retry or
replace the required incident recovery integration and host retry tests.
"""
import copy
import json
import os
from pathlib import Path
import pytest
from hotpost import source_finder
from hotpost.config import Settings
from hotpost.editing_adapter import _atomic_json
from hotpost.studio_pause import StudioPaused
from hotpost.studio_supervision import SupervisionHold


@pytest.mark.parametrize('exception,reason',[(SupervisionHold,'supervision_hold'),(StudioPaused,'user_stopped')])
def test_real_entry_preserves_hold_and_partial_receipt(tmp_path,monkeypatch,exception,reason):
    fixture=json.loads(Path(os.environ['HOTPOST_REPAIR_INCIDENT']).read_text('utf8'))
    state=copy.deepcopy(fixture['task']);job=copy.deepcopy(fixture['job'])
    assert job['id']=='job-3fc62c0446b44f1d'
    assert job['task_id']==state['id'] and job['payload']['run_id']==state['run_id']
    descriptor=job['checkpoint']['source_attempts'][-1]
    captured=next(json.loads(a['content']) for a in fixture['artifacts']
        if a.get('path')==descriptor['manifest_path'] and 'content' in a)
    assert captured['failure']=={'stage':'candidate_verification','type':'SupervisionHold','reason':'user_stopped'}
    assert captured['status']=='paused'
    assert sum(bool(c.get('downloaded_file')) for c in captured['candidates'])==3
    settings=Settings(data_dir=tmp_path)
    stopped=exception('isolated interruption')
    published=[]
    def interrupted(settings,shortcode,progress,**kwargs):
        root=kwargs['root']
        assert root.resolve().is_relative_to(tmp_path.resolve())
        saved=copy.deepcopy(captured)
        saved['job_id']=root.name
        _atomic_json(root/'manifest.json',saved)
        published.append(root/'manifest.json')
        progress('isolated candidate verification',56)
        raise stopped
    monkeypatch.setattr(source_finder,'_find_sources',interrupted)
    with pytest.raises(exception) as caught:
        source_finder.find_sources(settings,state['shortcode'],lambda *args:None)
    assert caught.value is stopped
    assert len(published)==1
    saved=json.loads(published[0].read_text('utf8'))
    assert saved['status']=='paused'
    assert saved['failure']=={'stage':'candidate_verification','type':exception.__name__,'reason':reason}
    assert saved['candidates']==captured['candidates']
    assert saved['search_audit']==captured['search_audit']
    assert saved['run_id']==state['run_id']
    assert fixture['job']==job and fixture['task']==state
