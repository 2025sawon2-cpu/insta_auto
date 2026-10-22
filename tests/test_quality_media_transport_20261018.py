"""QA transport regression using the preserved tent failure's actual images.

No model, worker, renderer or live-state mutation occurs. The actual QA method
assembles requests; subprocess extraction is an isolated copy port and the
generator captures requests instead of contacting Codex. JPEG re-encoding is
lossy transport compression at the original resolution, never evidence edits.
"""
import base64
import copy
import hashlib
import io
import json
import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from hotpost.config import Settings
from hotpost.daily_quality import DailyQualityMixin, POLICY
from hotpost.quality_boundaries import boundary_indices
from hotpost.visual_media import review_frame_data


ROOT=Path(__file__).resolve().parents[1]
TASK='work-17bb4524ce3a4217'
EDIT='job-558f0a1bf2084148'
QA='job-3670ecae905e4be8'
BYTE_CAP=1024*1024
PIXEL_CAP=4_000_000


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def tent_evidence():
    task=ROOT/'data/studio'/TASK
    qa=task/QA
    receipt=qa/'boundary-evidence.json'
    if not receipt.is_file():pytest.skip('Preserved local tent QA evidence is unavailable')
    value=json.loads(receipt.read_text('utf-8'))
    sheets=[qa/'boundaries/boundary-sheet-1.jpg',qa/'boundaries/boundary-sheet-3.jpg']
    assert all(p.is_file() for p in sheets)
    return SimpleNamespace(task=task,qa=qa,receipt=receipt,boundaries=value,sheets=sheets)


@pytest.mark.parametrize('index,expected_bytes',[(0,1_244_452),(1,1_096_485)])
def test_actual_oversize_boundary_sheet_fits_same_resolution_without_evidence_changes(tent_evidence,tmp_path,monkeypatch,index,expected_bytes):
    source=tent_evidence.sheets[index]
    before=digest(source)
    assert source.stat().st_size==expected_bytes>BYTE_CAP
    copy_path=tmp_path/source.name
    shutil.copy2(source,copy_path)
    assert digest(copy_path)==before
    def forbidden(*args,**kwargs):pytest.fail('Transport must not resize, crop or thumbnail evidence')
    for name in ('resize','crop','thumbnail'):monkeypatch.setattr(Image.Image,name,forbidden)
    encoded=review_frame_data(copy_path)
    raw=base64.b64decode(encoded['data'],validate=True)
    assert encoded['mimeType']=='image/jpeg' and len(raw)<=BYTE_CAP
    with Image.open(io.BytesIO(raw)) as image:
        assert image.format=='JPEG' and image.size==(1440,2010)
        assert image.width*image.height<=PIXEL_CAP
        image.verify()
    assert digest(source)==digest(copy_path)==before


class Reviewer(DailyQualityMixin):
    def folder(self,task):
        root=self.root/task
        root.mkdir(parents=True,exist_ok=True)
        return root


def test_actual_quality_review_uses_bounded_transport_for_every_image_and_keeps_originals(tent_evidence,tmp_path,monkeypatch):
    fixture=tent_evidence
    db_path=ROOT/'data/studio/studio.sqlite3'
    if not db_path.is_file():pytest.skip('Local completed tent state is unavailable')
    with sqlite3.connect('file:'+str(db_path)+'?mode=ro',uri=True) as db:
        stored=json.loads(db.execute('select state from tasks where id=?',(TASK,)).fetchone()[0])
    original_edit=next(e for e in stored['edits'] if e['id']==EDIT)
    original_plan=Path(original_edit['plan_path'])
    original_raw=original_plan.read_bytes()
    plan=json.loads(original_raw)
    isolated_plan=tmp_path/'plan.json';isolated_plan.write_bytes(original_raw)
    edit=copy.deepcopy(original_edit)
    edit['plan_path']=str(isolated_plan)
    # Only the in-memory review history is empty, so the real method assembles
    # each request rather than returning the live task's cached QA result.
    state=copy.deepcopy(stored)
    state.update(id='isolated-transport-task',edits=[edit],edit_id=EDIT,
        daily_quality=dict(policy=POLICY,reviews=[],status='pending',repair_round=0,max_repairs=3))
    reviewer=Reviewer();reviewer.root=tmp_path/'review'
    reviewer.settings=Settings(data_dir=tmp_path/'unused-data')
    job=dict(id='isolated-quality-job',kind='quality_review',task_id=state['id'],payload=dict(edit_id=EDIT))

    protected={original_plan,isolated_plan,Path(edit.get('export_path') or edit['preview_path']),
        Path(plan['voice']['path']),Path(plan['voice_source']['path']),fixture.receipt,
        *[Path(p) for p in fixture.boundaries['sheets']],
        *[Path(f['path']) for f in fixture.boundaries['frames']]}
    protected.update(Path(s['path']) for s in stored['scripts'] if s['id']==edit['script_id'])
    hashes={p:digest(p) for p in protected}
    original_indices=[f['index'] for f in fixture.boundaries['frames']]
    assert original_indices==boundary_indices(plan)
    captured=[];extractions=[]

    def fake_extract(args,**kwargs):
        # Only derived test outputs are synthesized by copying already decoded
        # actual tent images. Never call ffmpeg or write a production path.
        assert args[0]=='ffmpeg'
        if args[-1]=='-':return SimpleNamespace(returncode=0,stdout=b'',stderr=b'')
        destination=Path(args[-1])
        assert destination.resolve().is_relative_to(tmp_path.resolve())
        origin=fixture.qa/destination.name
        if not origin.is_file():origin=fixture.qa/'actual-first-frame.jpg'
        assert origin.is_file()
        shutil.copy2(origin,destination)
        extractions.append(destination)
        return SimpleNamespace(returncode=0,stdout=b'',stderr=b'')

    def same_boundaries(video,current_plan,output):
        assert Path(video)==Path(edit.get('export_path') or edit['preview_path'])
        assert current_plan==plan
        return copy.deepcopy(fixture.boundaries)

    def generate(settings,instruction,evidence,*,media):
        images=[]
        for part in media:
            if 'inlineData' not in part:continue
            encoded=part['inlineData'];raw=base64.b64decode(encoded['data'],validate=True)
            # Match writing/jobs.py's actual pre-model limits, including pixels.
            assert len(raw)<=BYTE_CAP
            with Image.open(io.BytesIO(raw)) as image:
                dimensions=image.size
                assert image.width*image.height<=PIXEL_CAP
                assert encoded['mimeType']=='image/jpeg' and image.format=='JPEG'
                image.verify()
            images.append(dict(bytes=len(raw),dimensions=dimensions,sha256=hashlib.sha256(raw).hexdigest()))
        assert images
        captured.append(dict(purpose=evidence['purpose'],beat_ids=list(evidence['detailed_beat_ids']),images=images))
        return dict(passed=True,issues=[],advisories=[],thumbnail_lines=None)

    monkeypatch.setattr('hotpost.daily_quality.subprocess.run',fake_extract)
    monkeypatch.setattr('hotpost.source_finder.probe_video',lambda path:{'duration':plan['duration']})
    monkeypatch.setattr('hotpost.quality_boundaries.extract_boundaries',same_boundaries)
    monkeypatch.setattr('hotpost.render_audio.audit',lambda *args:{'passed':True,'issues':[]})
    monkeypatch.setattr('hotpost.script_rewriter._generate',generate)
    result=reviewer._quality_review(state,job)
    assert result['passed'] is True
    assert len(captured)==3 and all(c['purpose']=='daily_video_quality' for c in captured)
    assert set(b for c in captured for b in c['beat_ids'])=={b['id'] for b in plan['beats']}
    # Actual oversize sheets must appear in QA calls at precisely their original
    # 1440x2010 geometry, encoded through the existing adaptive JPEG helper.
    transmitted={i['sha256']:i for c in captured for i in c['images']}
    for sheet in fixture.sheets:
        bounded=review_frame_data(sheet)
        key=hashlib.sha256(base64.b64decode(bounded['data'],validate=True)).hexdigest()
        assert transmitted[key]['dimensions']==(1440,2010)
    assert all(digest(path)==before for path,before in hashes.items())
    assert original_plan.read_bytes()==isolated_plan.read_bytes()==original_raw
    assert [f['index'] for f in result['boundary_evidence']['frames']]==original_indices
    assert result['boundary_evidence']['frames']==fixture.boundaries['frames']
    assert extractions and all(p.is_relative_to(tmp_path) for p in extractions)
