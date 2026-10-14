"""Settled unusable candidates must not starve fresh grounded acquisition."""
import copy
import hashlib
from pathlib import Path

import pytest

from hotpost.source_functional import REVIEW_POLICY
from hotpost import source_presentation as sp
from test_source_pause_history import Harness, MemoryStore


def rejected(tmp_path, name='game'):
    path = tmp_path / (name + '.mp4')
    path.write_bytes(name.encode())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'id':name, 'path':str(path), 'sha256':digest,
            'source_quality':'clean', 'editing_eligible':False,
            'presentation_review_required':True,
            'functional_review':{'reviewed':True, 'policy':REVIEW_POLICY,
                'source_sha256':digest, 'same_core_function':False,
                'context_usable':False, 'observed_actions':['digital game menu'],
                'evidence_frames':['actual-sampled-game-frame.png']}}


def test_verified_rejection_only_changes_scheduling(tmp_path):
    source = rejected(tmp_path)
    before = copy.deepcopy(source)
    assert sp.needs_presentation_review(source)
    for _ in range(3):
        assert not sp.needs_pending_presentation_review(source)
    assert source == before
    assert source['editing_eligible'] is False


@pytest.mark.parametrize('field,value', [
    ('reviewed',False), ('reviewed',1), ('source_sha256','other'),
    ('policy','old-policy'), ('same_core_function',None),
    ('same_core_function',0), ('context_usable',''),
    ('same_core_function',True), ('context_usable',True),
    ('observed_actions',[]), ('evidence_frames',[])])
def test_unverified_false_and_new_positive_remain_pending(tmp_path,field,value):
    source = rejected(tmp_path)
    source['functional_review'][field] = value
    before = copy.deepcopy(source)
    assert sp.needs_pending_presentation_review(source)
    assert source == before


@pytest.mark.parametrize('change',['no_review','file_changed','file_missing','metadata_changed','manual_positive'])
def test_changed_or_missing_evidence_cannot_be_skipped(tmp_path,change):
    source = rejected(tmp_path)
    if change == 'no_review': source.pop('functional_review')
    if change == 'file_changed': Path(source['path']).write_bytes(b'new actual footage')
    if change == 'file_missing': Path(source['path']).unlink()
    if change == 'metadata_changed': source['sha256'] = 'new'
    if change == 'manual_positive': source['manual_usage_review'] = {'editing_eligible':True}
    before = copy.deepcopy(source)
    assert sp.needs_pending_presentation_review(source)
    assert source == before


def harness(tmp_path, sources):
    from hotpost.config import Settings
    h = Harness()
    h.settings = Settings(data_dir=tmp_path)
    state = {'id':'task','shortcode':'apple','sources':sources,'reference_duration':21,
             'source_acquisition':{'queries':[{'query':'old', 'status':'results'}]},
             'manifest_path':str(tmp_path/'immutable-manifest.json'),
             'automation':{'active':False}}
    h.store = MemoryStore(state)
    job = {'id':'new','task_id':'task','kind':'collect_sources',
           'payload':{'round':9},'checkpoint':{}}
    return h, state, job


def test_collect_two_rejected_sources_reaches_fresh_route_without_local_loop(tmp_path,monkeypatch):
    from hotpost import source_finder
    sources = [rejected(tmp_path,'game1'), rejected(tmp_path,'game2')]
    h, state, job = harness(tmp_path,sources)
    h._restore_source_attempt_history = lambda state,job: state
    h._bind_source_attempt_progress = lambda *args: None
    h._review_deferred_downloads = lambda *args: None
    h._review_source_records = lambda *args: pytest.fail('settled rejections were requeued')
    seen=[]
    class FreshRouteReached(Exception): pass
    def find(*args,**kwargs):
        seen.append(kwargs)
        raise FreshRouteReached
    monkeypatch.setattr(source_finder,'find_sources',find)
    before = copy.deepcopy(state)
    with pytest.raises(FreshRouteReached): h._collect_source_attempt(state,job)
    assert len(seen) == 1 and seen[0]['previous_searches'] == before['source_acquisition']['queries']
    assert h.store.state['sources'] == before['sources']
    assert h.store.state['source_acquisition']['queries'] == before['source_acquisition']['queries']
    assert 'bounded_rounds' not in h.store.state['source_acquisition']


def test_refresh_local_gate_skips_completed_rejections_without_mutation(tmp_path):
    h, state, job = harness(tmp_path,[rejected(tmp_path,'game1'),rejected(tmp_path,'game2')])
    h._review_source_records = lambda *args: pytest.fail('settled rejections were requeued')
    before = copy.deepcopy(state)
    assert h._review_pending_local_sources(state,job,lambda *args:None) is None
    assert state == before


def test_refresh_same_failed_overlay_does_not_starve_fresh_query(tmp_path):
    from hotpost.source_overlay_review import POLICY
    source = rejected(tmp_path)
    source.pop('functional_review')
    source.update(source_quality='unknown',blur_required=True,
                  overlay_review_error='An independent visual reviewer and exact intervals are required',
                  overlay_review_attempted_policy=POLICY,
                  overlay_review_attempted_sha256=source['sha256'])
    h, state, job = harness(tmp_path,[source])
    h._review_source_records = lambda *args: pytest.fail('same failed overlay was requeued')
    before = copy.deepcopy(state)
    assert h._review_pending_local_sources(state,job,lambda *args:None) is None
    assert state == before
    # Actual changed input is allowed; the failed same-input gate cannot veto it.
    source['overlay_review_attempted_sha256'] = 'old-file'
    h._review_source_records = lambda state,job,pending,progress: (pending,None)
    assert h._review_pending_local_sources(state,job,lambda *args:None)['visual_review_only']


@pytest.mark.parametrize('kind',['unreviewed','positive','overlay'])
def test_local_gate_preserves_real_unfinished_work(tmp_path,kind):
    source = rejected(tmp_path)
    if kind == 'unreviewed': source.pop('functional_review')
    if kind == 'positive': source['functional_review']['context_usable'] = True
    if kind == 'overlay': source.update(source_quality='unknown',blur_required=True)
    h, state, job = harness(tmp_path,[source]); calls=[]
    def review(state,job,pending,progress):
        calls.append(copy.deepcopy(pending));return pending,None
    h._review_source_records = review
    before = copy.deepcopy(state)
    result = h._review_pending_local_sources(state,job,lambda *args:None)
    assert len(calls) == 1 and result['visual_review_only']
    assert state == before
