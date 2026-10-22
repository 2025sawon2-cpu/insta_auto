import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hotpost.studio_thumbnail import validate_thumbnail, render_thumbnail
from hotpost.studio_store import Conflict
from test_studio_workflow import prepared, complete, small_inventory_contract


def document():
    return {'version':1,'frame':0,'elements':[dict(id='title',kind='text',text='썸네일 테스트',start=0,end=1/30,
        x=540,y=520,size=110,rotation=-8,color='#ffdf40',background=False,shape='straight')]}


@pytest.mark.parametrize('mutation', [dict(frame=90),dict(frame=1.2),dict(frame=True),dict(url='http://evil')])
def test_thumbnail_rejects_invalid_frames_and_external_assets(mutation):
    with pytest.raises(ValueError):validate_thumbnail({**document(),**mutation},3)


def test_thumbnail_has_exactly_one_frame_and_independent_document():
    doc=document();validated=validate_thumbnail(doc,3)
    validated['elements'][0]['text']='별도 문구'
    assert doc['elements'][0]['text']=='썸네일 테스트'
    doc['elements'][0]['end']=2/30
    with pytest.raises(ValueError):validate_thumbnail(doc,3)


def test_thumbnail_rejects_known_unsupported_font_glyph():
    doc=document();doc['elements'][0]['text']='흰 몸판·검은 어깨'
    with pytest.raises(ValueError,match='U\\+00B7'):validate_thumbnail(doc,3)


def test_thumbnail_save_and_export_preserve_version_voice_and_script(prepared,monkeypatch):
    monkeypatch.setattr('hotpost.remotion_editor.available',lambda:True)
    studio,task=prepared;complete(studio,task)
    before=studio.store.get(task)
    body=dict(edit_id=before['edit_id'],feedback_revision=before.get('feedback_revision',0),document=document())
    saved=studio.action(task,'save-thumbnail',body)
    assert saved['status']=='completed' and saved['feedback']['thumbnail_document']==document()
    assert not studio.store.claim('media')
    with pytest.raises(Conflict):studio.action(task,'export-thumbnail',body)
    result=studio.action(task,'export-thumbnail',{**body,'feedback_revision':saved['feedback_revision']})
    assert result['status']=='editing'
    assert result['pipeline'][0]['status']=='completed' and len(result['pipeline'])==2
    queued=studio.store.get(task)
    assert queued['scripts']==before['scripts'] and queued['voices']==before['voices']
    job=studio.store.claim('media');assert job['payload']['thumbnail_only']
    monkeypatch.setattr(studio,'ensure_source_collection',lambda *_:pytest.fail('thumbnail recollected sources'))
    target=studio.folder(task)/'new.mp4';target.write_bytes(b'new video')
    edited={**before['edits'][-1],'id':job['id'],'parent_id':before['edit_id'],'export_path':str(target),'export_verified':True}
    studio.store.finish(job,edited,lambda s,db,r:studio._accept(s,job,r,db))
    after=studio.store.get(task)
    assert after['status']=='completed' and len(after['edits'])==len(before['edits'])+1
    assert after['voices']==before['voices'] and after['scripts']==before['scripts']
    assert not studio.store.claim('media')


def test_thumbnail_conflicts_with_other_edits_or_old_base(prepared,monkeypatch):
    monkeypatch.setattr('hotpost.remotion_editor.available',lambda:True)
    studio,task=prepared;complete(studio,task);state=studio.store.get(task)
    with pytest.raises(Conflict):studio.action(task,'save-thumbnail',dict(edit_id='old',document=document()))
    studio.store.change(task,lambda s,db:s.update(feedback={'script_text':'수정 대본'}))
    with pytest.raises(Conflict):studio.action(task,'save-thumbnail',dict(edit_id=state['edit_id'],document=document()))


def test_discard_edit_feedback_clears_thumbnail_together_and_keeps_voice(prepared,monkeypatch):
    monkeypatch.setattr('hotpost.remotion_editor.available',lambda:True)
    studio,task=prepared;complete(studio,task)
    state=studio.store.get(task)
    studio.action(task,'save-thumbnail',{'edit_id':state['edit_id'],'document':document()})
    studio.action(task,'save-feedback',{'speed':1.05})
    with pytest.raises(Conflict):studio.action(task,'reproduce',{})
    result=studio.action(task,'discard-edit-feedback',{})
    assert result['feedback']=={'speed':1.05}
    assert studio.store.get(task)['edit_id']==state['edit_id']


@pytest.mark.parametrize('changed',['voice','script','sources','already_preserved'])
def test_voice_change_preserves_manual_cover_but_new_content_does_not(prepared,changed):
    from hotpost.studio_thumbnail import queue_preserved_thumbnail
    studio,task=prepared;complete(studio,task)
    def check(state,db):
        old=state['edits'][-1]
        Path(old['plan_path']).write_text(json.dumps({'thumbnail_document':document()}),'utf8')
        old_run=state['runs'][-1]
        old_run['artifacts']['edit_id']=old['id'];old_run['inputs']['source_ids']=['source']
        current={**old,'id':'new-body','voice_id':'new-voice'}
        run={'id':'voice-change','parent_id':old_run['id'],'inputs':{'source_ids':['source']}}
        if changed=='script':
            state['scripts'].append({'id':'different-script','text':'다른 제품 설명'})
            current['script_id']='different-script'
        if changed=='sources':run['inputs']['source_ids']=['different-source']
        if changed=='already_preserved':current['preserved_thumbnail_from']=old['id']
        queued=queue_preserved_thumbnail(studio,state,db,run,current)
        assert queued is (changed=='voice')
    studio.store.change(task,check)
    jobs=[j for j in studio.store.jobs(task) if j['kind']=='revision']
    if changed=='voice':
        assert len(jobs)==1
        job=studio.store.claim('media')
        assert job['payload']['thumbnail_document']=={**document(),'frame':-1}
        assert job['payload']['preserved_thumbnail_from']
        assert job['payload']['voice_id']=='new-voice'
    else:assert not jobs


@pytest.mark.parametrize('b_frames', [0, 2])
def test_real_render_changes_only_first_decoded_frame_and_copies_audio(tmp_path, b_frames):
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:pytest.skip('FFmpeg unavailable')
    from hotpost.config import Settings
    from hotpost.studio import Studio
    studio=Studio(Settings(data_dir=tmp_path,auto_capcut_timeout=180),workers=False)
    state,_=studio.store.create('thumbnail-real','썸네일 렌더 검증',prepare=False)
    folder=studio.folder(state['id']);base=folder/'original.mp4'
    subprocess.run([ffmpeg,'-y','-v','error','-f','lavfi','-i','testsrc2=s=1080x1920:r=30:d=2',
        '-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','libx264','-crf','23',
        '-bf',str(b_frames),'-pix_fmt','yuv420p','-c:a','aac','-shortest',str(base)],check=True)
    edit={'id':'original','duration':2,'export_path':str(base),'clean_preview_path':str(base)}
    job={'id':'thumbnail-real','payload':{'thumbnail_document':document()}}
    result=render_thumbnail(studio,state,job,edit,{'duration':2,'beats':[]})
    def frames(path):
        rows=subprocess.run([ffmpeg,'-v','error','-i',str(path),'-map','0:v','-f','framemd5','-'],check=True,capture_output=True,encoding='utf-8').stdout
        return [r for r in rows.splitlines() if r and not r.startswith('#')]
    before,after=frames(base),frames(result['export_path'])
    assert len(before)==len(after)==60
    assert before[0]!=after[0]
    assert before[1:]==after[1:]
    assert Path(result['export_path']).stat().st_size < base.stat().st_size*1.2
    assert Path(result['cover_path']).is_file() and result['export_verified']
    assert json.loads(Path(result['plan_path']).read_text(encoding='utf-8'))['thumbnail_document']==document()
    revised=json.loads(Path(result['plan_path']).read_text(encoding='utf-8'))
    assert revised['cover_spec']['lines']==['썸네일 테스트']
    assert revised['cover_spec']['source']['rendered_cover_sha256']
    assert 'single_frame_confirmation' not in revised['cover_spec']['source']
    from hotpost.studio_thumbnail import verify_manual_thumbnail
    state['edits']=[edit]
    manual={**edit,**result,'id':job['id'],'parent_id':edit['id']}
    verify_manual_thumbnail(state,manual,revised,Path(result['export_path']))
    altered=json.loads(json.dumps(revised));altered['thumbnail_document']['elements'][0]['text']='다른 문구'
    with pytest.raises(ValueError,match='문구·폰트'):
        verify_manual_thumbnail(state,manual,altered,Path(result['export_path']))
    if b_frames == 2:
        # A second edit must unwrap the compact parent's hidden decoder frame.
        parent={**edit,**result,'id':'first-thumbnail','parent_id':edit['id']}
        # Normal QA reclassifies the finished revision as a web render.
        # Actual copy receipts must still identify its hidden decoder preroll.
        parent['export_kind']='web_render'
        original_preview={**edit,'preview_path':edit['export_path']}
        original_preview.pop('export_path')
        state['edits']=[original_preview,parent]
        second_doc=document();second_doc['elements'][0]['text']='두 번째 썸네일'
        second=render_thumbnail(studio,state,{'id':'thumbnail-second','payload':{'thumbnail_document':second_doc}},
                                parent,{'duration':2,'beats':[]})
        again=frames(second['export_path'])
        assert len(again)==60 and again[1:]==before[1:]
        assert again[0]!=after[0]
        assert Path(second['export_path']).stat().st_size < base.stat().st_size*1.2
        assert Path(parent['export_path']).is_file()


def test_thumbnail_rejects_missing_original_in_version_chain(tmp_path):
    if not shutil.which('ffmpeg'):pytest.skip('FFmpeg unavailable')
    from hotpost.config import Settings
    from hotpost.studio import Studio
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('missing-parent','원본 연결 검증',prepare=False)
    base=studio.folder(state['id'])/'exists.mp4';base.write_bytes(b'file')
    edit={'id':'thumb','duration':1,'export_kind':'thumbnail','parent_id':'missing','export_path':str(base)}
    with pytest.raises(ValueError,match='원본 완성본'):
        render_thumbnail(studio,state,{'id':'job','payload':{'thumbnail_document':document()}},edit,{})
