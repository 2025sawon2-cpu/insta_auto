import hashlib
import pytest
from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.studio_sources import source_goal
from hotpost.studio_workflow import snapshot


@pytest.mark.parametrize('verified,voice_id,script_id,completed',[
    (True,'voice','script',True),(False,'voice','script',False),
    (True,'other','script',False),(True,'voice','other',False)])
def test_photo_story_completion_requires_verified_matching_edit(tmp_path,verified,voice_id,script_id,completed):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('photo','photo',{'protocol':2,'active':True})
    final=tmp_path/'final.mp4';final.write_bytes(b'fixture')
    photo=tmp_path/'photo.jpg';photo.write_bytes(b'actual-photo-fixture')
    asset={'id':'photo','path':str(photo),'kind':'still_image','sha256':hashlib.sha256(photo.read_bytes()).hexdigest()}
    state.update(creation_mode='photo_post',original_text='caption',sources=[],
        scripts=[{'id':'script'}],script_id='script',voices=[{'id':'voice'}],voice_id='voice',
        edits=[{'id':'edit','voice_id':voice_id,'script_id':script_id,'export_kind':'photo_story',
                'export_path':str(final),'export_verified':verified,'photo_assets':[asset]}],edit_id='edit')
    snapshot(state)['inputs']['photo_story']=True
    with studio.store.transaction() as db:studio.advance_workflow(state,db)
    assert (state['status']=='completed') is completed
    if completed:
        goal=source_goal(state)
        assert goal['ready'] and not goal['core_ready']
        assert goal['asset_kind']=='still_image' and 'usable_seconds' not in goal
        photo.write_bytes(b'changed')
        assert not source_goal(state)['ready']
