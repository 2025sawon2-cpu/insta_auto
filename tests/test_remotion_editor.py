import copy
import math
import pytest
from hotpost.remotion_editor import validate_document
from hotpost.studio_store import Conflict
from test_studio_workflow import prepared, complete, small_inventory_contract


def document():
    return {'version': 1, 'elements': [dict(id='arrow-1', kind='arrow', text='', start=0, end=2,
        x=540, y=800, size=220, rotation=-20, color='#ffdf00', background=False, shape='curved')]}


@pytest.mark.parametrize('field,value', [('x', -1), ('y', 1921), ('size', 900), ('rotation', math.nan),
    ('start', True), ('end', math.inf), ('end', .001), ('kind', 'html'), ('color', 'url(http://evil)'),
    ('shape', '<svg>'), ('background', 'yes'), ('id', '../foo')])
def test_document_rejects_invalid_values(field, value):
    doc = document();doc['elements'][0][field] = value
    with pytest.raises(ValueError):validate_document(doc, 3)


def test_document_allows_empty_and_overlapping_layers_without_mutation():
    doc = document();doc['elements'].append({**doc['elements'][0], 'id': 'arrow-2'})
    result = validate_document(doc, 3)
    result['elements'][0]['size'] = 250
    assert doc['elements'][0]['size'] == 220
    assert validate_document({'version':1, 'elements':[]}, 3)['elements'] == []


def test_document_rejects_duplicates_external_props_and_arbitrary_emoji():
    doc = document();doc['elements'].append(copy.deepcopy(doc['elements'][0]))
    with pytest.raises(ValueError):validate_document(doc, 3)
    doc = document();doc['elements'][0]['src'] = 'http://external/'
    with pytest.raises(ValueError):validate_document(doc, 3)
    doc = document();doc['elements'][0].update(kind='emoji', text='<script>')
    with pytest.raises(ValueError):validate_document(doc, 3)


def test_overlay_export_creates_revision_preserving_script_voice_and_completed_version(prepared, monkeypatch):
    monkeypatch.setattr('hotpost.remotion_editor.available', lambda: True)
    studio, task = prepared;complete(studio, task)
    before = studio.store.get(task)
    result = studio.action(task, 'export-overlays', {'edit_id':before['edit_id'],
        'feedback_revision':before.get('feedback_revision', 0), 'document':document()})
    assert result['script_id'] == before['script_id'] and result['voice_id'] == before['voice_id']
    assert result['edit_id'] == before['edit_id']
    assert len(result['pipeline']) == 2
    assert result['pipeline'][0]['status'] == 'completed'
    assert result['pipeline'][0]['video_url'] == studio.media_url(task, before['edits'][-1]['export_path'])
    job = studio.store.claim()
    assert job['kind'] == 'revision' and job['payload']['remotion_only'] is True
    assert job['payload']['overlay_document'] == document()
    assert len(studio.store.get(task)['voices']) == len(before['voices'])
    # An overlay revision must finish without any collection, writing or TTS work,
    # including when the preserved voice was a legacy named voice.
    monkeypatch.setattr(studio, 'ensure_source_collection', lambda *_: pytest.fail('overlay revision recollected sources'))
    target = studio.folder(task)/'overlay-result.mp4';target.write_bytes(b'new-mp4')
    edited = {**before['edits'][-1], 'id':job['id'], 'parent_id':before['edit_id'],
              'export_path':str(target), 'preview_path':str(target), 'export_kind':'remotion'}
    studio.store.finish(job, edited, lambda s,db,r:studio._accept(s,job,r,db))
    after = studio.store.get(task)
    assert after['status'] == 'completed' and after['latest_completed_run_id'] != before['latest_completed_run_id']
    assert not studio.store.claim('media')
    assert after['voices'] == before['voices']


def test_overlay_save_handles_empty_document_revision_conflict_and_mixed_changes(prepared, monkeypatch):
    monkeypatch.setattr('hotpost.remotion_editor.available', lambda: True)
    studio, task = prepared;complete(studio, task)
    state = studio.store.get(task)
    body = {'edit_id':state['edit_id'], 'feedback_revision':0, 'document':{'version':1,'elements':[]}}
    result = studio.action(task, 'save-overlays', body)
    assert result['feedback']['overlay_document']['elements'] == []
    assert len(result['pipeline']) == 1 and not studio.store.claim()
    with pytest.raises(Conflict):studio.action(task, 'export-overlays', body)
    with pytest.raises(Conflict):studio.action(task, 'make-video', {'text':'새 대본'})
    state = studio.store.get(task)
    assert 'script_text' not in state['feedback']
    with pytest.raises(Conflict):studio.action(task, 'save-overlays', {**body,'edit_id':'old'})
