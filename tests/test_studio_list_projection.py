import copy
import json
from pathlib import Path

from hotpost.config import Settings
from hotpost.studio import Studio


def test_board_summary_omits_old_plan_and_large_receipts_but_keeps_status(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('summary','완성 영상',prepare=False)
    state.update(status='completed',run_id='r',latest_completed_run_id='r',edit_id='e',
        automation={'protocol':2,'stage':'completed'},original_text='Reference',
        daily_quality={'reviews':[{'large':'x'*100000}]},
        edits=[{'id':'e','plan_path':str(tmp_path/'missing-historical-plan.json'),
            'cover_path':str(tmp_path/'cover.png'),'export_verified':True,'portable_draft_path':'draft'}],
        runs=[{'id':'r','number':1,'status':'completed','artifacts':{'edit_id':'e','sources':[{'id':'source'}],
            'original_text':'Reference','script_id':'s','voice_id':'v'}}])
    original=copy.deepcopy(state)
    result=studio.brief(state)
    assert result['_summary'] and result['status']=='completed'
    assert result['thumbnail_url'].endswith('cover.png')
    assert all(s['status']=='completed' for s in result['pipeline'][0]['steps'])
    assert 'daily_quality' not in result and 'edits' not in result
    assert len(json.dumps(result))<5000 and state==original


def test_unfinished_summary_never_invents_a_completed_export(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('waiting','제작 중',prepare=False)
    state.update(creation_mode='self_shot',status='quality_review',
        self_shot={'started':True},automation={'protocol':2,'stage':'quality_review'},
        edits=[{'id':'e','export_verified':True}],
        runs=[{'id':'r','number':1,'status':'running','artifacts':{'edit_id':'e'}}])
    result=studio.brief(state)
    assert result['self_shot']['started'] and result['collection_date_basis']=='self_shot'
    assert result['pipeline'][0]['steps'][-1]['status']=='pending'
    assert not any('download_url' in s for s in result['pipeline'][0]['steps'])
