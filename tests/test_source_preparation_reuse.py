import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from hotpost.config import Settings
from hotpost import source_finder as finder
from hotpost import source_preparation as preparation


def finder_fixture(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path,source_query_model_enabled=False,source_use_openclip=False,
                      source_browser_search=False,source_match_mode='appearance')
    calls={'download':0,'frames':0,'sheet':0,'visual_queries':0,'plan':0}
    monkeypatch.setattr(finder,'_post',lambda *a:SimpleNamespace(is_video=True,kind='reel',caption='은색 거울',url='https://reference'))
    monkeypatch.setattr(finder,'_transcript_evidence',lambda *a:{'speech':'거울을 엽니다','screen_text':'거울','reference_kind':'screen_text'})
    def download(s,p,path):
        calls['download']+=1;path.write_bytes(b'actual fixed reference');return path
    def frames(ref,folder):
        calls['frames']+=1;folder.mkdir();path=folder/'frame_001.jpg';Image.new('RGB',(12,12),'silver').save(path);return [path]
    def sheet(frames,path):
        calls['sheet']+=1;path.write_bytes(frames[0].read_bytes())
    class Verifier:
        error='';product_evidence=[];subject_reference_indices=[];available=False
        def __init__(self,*a):pass
        def discover_product_queries(self):calls['visual_queries']+=1;return []
    def plan(*args):
        calls['plan']+=1;return {'products':[],
            'query_evidence':{'caption':'은색 거울','speech':'거울을 엽니다','screen_text':'거울'},
            'query_details':[{'query':'silver mirror','language':'en','intent':'subject'}]}
    from hotpost.source_visual_queries import cached_visual_queries, binding, digest
    def visual(settings,reference,frames,caption,transcript):
        evidence=binding(reference,frames,caption,transcript)
        proposal={'observations':[],'queries':[]}
        review={'input_sha256':digest(evidence),'proposal_sha256':digest(proposal),'checks':[]}
        return cached_visual_queries(settings,reference,frames,caption,transcript,
            lambda s,instruction,data,**kw: review if 'proposal_sha256' in data else proposal)
    monkeypatch.setattr('hotpost.source_visual_queries.cached_visual_queries',visual)
    monkeypatch.setattr(finder,'_download_reference',download);monkeypatch.setattr(finder,'extract_frames',frames)
    monkeypatch.setattr(finder,'create_contact_sheet',sheet);monkeypatch.setattr(finder,'OpenClipVerifier',Verifier)
    monkeypatch.setattr(finder,'search_google_vision',lambda *a:([],[]));monkeypatch.setattr(finder,'product_query_plan',plan)
    monkeypatch.setattr('hotpost.text_overlay.TextOverlayDetector',lambda *a:SimpleNamespace(note=''))
    monkeypatch.setattr('hotpost.source_search.discovery.discover',lambda s,c,f,q,p,v,r,*a,**kw:([],q,{'notes':[]},[],0))
    monkeypatch.setattr('hotpost.source_planning.QUERY_PLAN_POLICY','prepared-policy-one',raising=False)
    return settings,calls


def test_full_finder_reuses_actual_media_and_plan_and_zip_external_sheet(tmp_path,monkeypatch):
    settings,calls=finder_fixture(tmp_path,monkeypatch)
    first=finder.find_sources(settings,'reused-reference')
    original=dict(calls)
    second=finder.find_sources(settings,'reused-reference',search_round=1,
        search_context={'rounds':[{'manifest_path':str(Path(first['zip_path']).parent/'manifest.json')}]})
    assert calls==original=={'download':1,'frames':1,'sheet':1,'visual_queries':1,'plan':1}
    root=Path(second['zip_path']).parent
    for relative in second['reference_frames']:assert (root/relative).is_file()
    assert (root/second['reference_contact_sheet']).is_file()
    assert not (root/'reference.mp4').exists()
    with zipfile.ZipFile(second['zip_path']) as z:
        assert z.read('reference_contact_sheet.jpg')==(root/second['reference_contact_sheet']).read_bytes()
        assert 'reference.mp4' not in z.namelist()


def test_changed_bundle_media_holds_without_reference_rebuild(tmp_path,monkeypatch):
    settings,calls=finder_fixture(tmp_path,monkeypatch);first=finder.find_sources(settings,'reused-reference')
    value=json.loads(Path(first['preparation_bundle_path']).read_text(encoding='utf-8'))
    Path(value['frames'][0]).write_bytes(b'changed pixels');before=dict(calls)
    with pytest.raises(ValueError,match='SHA'):finder.find_sources(settings,'reused-reference')
    assert calls==before


def test_query_policy_upgrade_reuses_media_but_evaluates_new_plan_once(tmp_path,monkeypatch):
    settings,calls=finder_fixture(tmp_path,monkeypatch);first=finder.find_sources(settings,'reused-reference')
    oldpath=Path(first['preparation_bundle_path']);old=oldpath.read_bytes()
    monkeypatch.setattr('hotpost.source_planning.QUERY_PLAN_POLICY','prepared-policy-two')
    # The previous manifest supplies media without inheriting the old query policy.
    second=finder.find_sources(settings,'reused-reference',search_context={'rounds':[
        {'manifest_path':str(Path(first['zip_path']).parent/'manifest.json')}]})
    third=finder.find_sources(settings,'reused-reference')
    assert calls=={'download':1,'frames':1,'sheet':1,'visual_queries':1,'plan':2}
    assert oldpath.read_bytes()==old and second['preparation_bundle_path']==third['preparation_bundle_path']


def test_legacy_media_adoption_rejects_authoritative_reference_mismatch(tmp_path,monkeypatch):
    settings,calls=finder_fixture(tmp_path,monkeypatch);first=finder.find_sources(settings,'reused-reference')
    manifest=Path(first['zip_path']).parent/'manifest.json'
    # A legacy receipt has no preparation bundle and its files have current hashes only.
    value=json.loads(manifest.read_text(encoding='utf-8'))
    for p in (tmp_path/'source-preparations').rglob('*.json'):p.unlink()
    with pytest.raises(ValueError,match='기준 영상'):
        preparation.prior_bundle(settings,'reused-reference','은색 거울',
            {'speech':'거울을 엽니다','screen_text':'거울','reference_kind':'screen_text'},
            {'rounds':[{'manifest_path':str(manifest)}],'expected_reference_sha256':'different-current-task-source'})
    assert calls['download']==1


def test_preflight_checks_accepted_bundle_receipt_before_any_new_preparation(tmp_path,monkeypatch):
    settings,calls=finder_fixture(tmp_path,monkeypatch);first=finder.find_sources(settings,'reused-reference')
    path=Path(first['preparation_bundle_path']);value=json.loads(path.read_text(encoding='utf-8'))
    value['query_plan']['query_details']=[{'query':'unrelated vegetable slicer','language':'en'}]
    # Recomputing the local envelope cannot overwrite a prior accepted receipt.
    value['payload_sha256']=preparation.payload_key(value)
    path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    before=dict(calls);folder_count=len(list(settings.source_dir.iterdir()))
    state={'shortcode':'reused-reference','reference_video':value['reference'],
           'source_acquisition':{'rounds':[{'manifest_path':str(Path(first['zip_path']).parent/'manifest.json')}]}}
    with pytest.raises(preparation.PreparationEvidenceWaiting,match='수용 영수증'):
        preparation.preflight_preparation(settings,state)
    assert calls==before and len(list(settings.source_dir.iterdir()))==folder_count


def test_query_capacity_wait_keeps_completed_reference_and_frames(tmp_path,monkeypatch):
    from hotpost.model_service import ModelServiceUnavailable
    settings,calls=finder_fixture(tmp_path,monkeypatch);settings.source_query_model_enabled=True
    attempted=[]
    def query(s,p,*a,**kw):
        attempted.append(True)
        if len(attempted)==1:raise ModelServiceUnavailable('capacity wait',attempted=False)
        return p
    monkeypatch.setattr('hotpost.source_planning.cached_enrich_plan',query)
    with pytest.raises(ModelServiceUnavailable):finder.find_sources(settings,'reused-reference')
    finder.find_sources(settings,'reused-reference')
    assert calls['download']==calls['frames']==calls['sheet']==calls['visual_queries']==1
    assert len(attempted)==2
