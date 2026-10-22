"""Image-first CAPTCHA decisions and durable evidence; no platform requests."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from hotpost.captcha_review import review_page,saved_review,digest,POLICY
from hotpost.config import Settings
from hotpost.browser_search import BrowserSearcher
from hotpost.search_access import access_record,observe_saved_captcha,manual_required,indexed_gate
from hotpost.source_access_preflight import observe_routes
from hotpost.source_coverage import actual_search_coverage
from hotpost.source_search.strategy import merge_history


class Page:
    url='https://www.tiktok.com/search?q=wallet&secret=never-save'
    viewport_size={'width':320,'height':480}
    def __init__(self,body='Drag the slider to fit the puzzle',capture_error=False):
        self.body=body;self.capture_error=capture_error;self.captures=0
    def locator(self,selector):
        return SimpleNamespace(inner_text=lambda **kw:self.body,count=lambda:0)
    def screenshot(self,*,path,**kwargs):
        self.captures+=1
        if self.capture_error:raise RuntimeError('capture unavailable')
        Image.new('RGB',(320,480),'white').save(path)


def verdict(positive):
    return {'verdict':'captcha' if positive else 'not_captcha','visible_challenge':positive,
            'observations':['Visible challenge box' if positive else 'Product search cards, no challenge'],
            'reason':'Independent screenshot assessment'}


def install_reviewer(monkeypatch,settings,answer,calls):
    def review(self,instruction,evidence,media):
        captures=list((settings.data_dir/'captcha_reviews').rglob('screen.png'))
        assert captures and any(digest(p)==evidence['screenshot_sha256'] for p in captures)
        assert list((settings.data_dir/'captcha_reviews').rglob('evidence.json'))
        assert media and media[0]['inlineData']['mimeType']=='image/jpeg'
        assert 'secret=' not in evidence['detector']['url']
        calls.append(copy.deepcopy(evidence))
        if isinstance(answer,Exception):raise answer
        return copy.deepcopy(answer)
    monkeypatch.setattr('hotpost.studio_adapter.StudioAdapter.editorial',review)


@pytest.mark.parametrize('positive',[True,False])
def test_capture_is_saved_before_independent_review_and_bound_to_receipt(tmp_path,monkeypatch,positive):
    settings=Settings(data_dir=tmp_path);page=Page();calls=[]
    install_reviewer(monkeypatch,settings,verdict(positive),calls)
    pointer=review_page(settings,'tiktok',page,query='wallet')
    assert pointer['status']==('captcha' if positive else 'clear')
    record=saved_review(pointer)
    assert record['review']==verdict(positive)
    assert record['detector']['matched_text'][0]['token']=='drag the slider'
    assert record['screenshot_sha256']==digest(record['screenshot_path'])
    assert record['navigation_performed'] is False and record['challenge_solved_by_agent'] is False
    again=review_page(settings,'tiktok',page,query='wallet')
    assert again==pointer and page.captures==1 and len(calls)==1


def test_product_caption_with_challenge_words_is_not_a_captcha_gate(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path);calls=[];page=Page('Video title: fit the puzzle toy')
    install_reviewer(monkeypatch,settings,verdict(False),calls)
    worker=BrowserSearcher(settings,tmp_path/'debug');audit={'query':'wallet'}
    assert worker._check_block(page,'tiktok',audit) is False
    assert audit['captcha_review']['status']=='clear' and saved_review(audit['captcha_review'])
    assert not access_record(tmp_path,'tiktok')


def test_false_captcha_does_not_ignore_a_real_login_wall(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path);calls=[]
    install_reviewer(monkeypatch,settings,verdict(False),calls)
    audit={'query':'wallet'}
    assert BrowserSearcher(settings,tmp_path/'debug')._check_block(
        Page('Log in to search. Video title: fit the puzzle toy'),'tiktok',audit)
    assert audit['status']=='login_required' and saved_review(audit['captcha_review'])


def test_verified_challenge_gate_and_persisted_query_history_reference_real_image(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path);calls=[]
    install_reviewer(monkeypatch,settings,verdict(True),calls)
    audit={'provider':'tiktok','query':'wallet','requests':[{'operation':'search_input'}]}
    assert BrowserSearcher(settings,tmp_path/'debug')._check_block(Page(),'tiktok',audit)
    gate=access_record(tmp_path,'tiktok')
    assert gate['reason']=='captcha' and saved_review(gate['captcha_review'])
    restored=json.loads(json.dumps(merge_history([audit])))
    assert restored[0]['captcha_review']==audit['captcha_review']
    assert actual_search_coverage(restored,{'en':5})['en']['count']==0


@pytest.mark.parametrize('failure',['capture','model','uncertain','invalid'])
def test_unconfirmed_capture_or_review_never_becomes_confirmed_captcha(tmp_path,monkeypatch,failure):
    settings=Settings(data_dir=tmp_path);calls=[]
    answer=(RuntimeError('model unavailable') if failure=='model' else
            {'verdict':'uncertain','visible_challenge':False,'observations':['image incomplete'],'reason':'cannot confirm'}
            if failure=='uncertain' else {} if failure=='invalid' else verdict(True))
    install_reviewer(monkeypatch,settings,answer,calls)
    audit={'query':'wallet'}
    assert BrowserSearcher(settings,tmp_path/'debug')._check_block(Page(capture_error=failure=='capture'),'tiktok',audit)
    assert audit['status']=='captcha_review_pending'
    gate=access_record(tmp_path,'tiktok')
    assert gate['reason']=='captcha_review_pending' and manual_required(gate)
    record=saved_review(audit['captcha_review']);assert record['status']=='captcha_review_pending'
    assert len(calls)==(0 if failure=='capture' else 1)


def test_tampered_image_is_not_reused_or_accepted_as_gate_proof(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path);page=Page();calls=[]
    install_reviewer(monkeypatch,settings,verdict(True),calls)
    old=review_page(settings,'tiktok',page)
    Path(old['screenshot_path']).write_bytes(b'changed bytes')
    assert saved_review(old) is None
    worker=BrowserSearcher(settings,tmp_path/'debug');audit={'captcha_review':old}
    worker._block('tiktok',audit,'captcha')
    assert audit['status']=='captcha_review_pending'
    new=review_page(settings,'tiktok',page)
    assert new['receipt_path']!=old['receipt_path'] and saved_review(new)
    assert page.captures==2 and len(calls)==2


def test_saved_legacy_gate_is_rechecked_from_image_and_old_event_preserved(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path);calls=[]
    folder=tmp_path/'search_cooldowns';folder.mkdir()
    (folder/'tiktok.json').write_text(json.dumps({'reason':'captcha','requires_verification':True,'strikes':4}))
    install_reviewer(monkeypatch,settings,verdict(False),calls)
    result=observe_saved_captcha(settings,'tiktok',Page('Normal search results'))
    assert result['status']=='clear' and saved_review(result['captcha_review'])
    gate=access_record(tmp_path,'tiktok')
    assert gate['strikes']==4 and gate['reason']=='captcha' and not manual_required(gate)
    assert gate['last_captcha_check']['captcha_review']==result['captcha_review']


@pytest.mark.parametrize('positive',[True,False])
def test_preflight_uses_reviewed_image_not_text_suspicion(tmp_path,monkeypatch,positive):
    settings=Settings(data_dir=tmp_path);calls=[];page=Page()
    install_reviewer(monkeypatch,settings,verdict(positive),calls)
    monkeypatch.setattr('hotpost.source_browser_runtime.existing_page',lambda *a:page)
    row=observe_routes(settings,['tiktok'],context=object())[0]
    assert row['status']==('captcha' if positive else 'ready')
    assert saved_review(row['captcha_review'])


def test_indexed_response_without_browser_image_remains_unconfirmed(tmp_path):
    settings=Settings(data_dir=tmp_path)
    result=indexed_gate('tiktok',SimpleNamespace(url='https://tiktok.com/captcha',
        text='verify you are human',status_code=200),settings)
    assert result['status']=='captcha_review_pending'
    assert access_record(tmp_path,'tiktok')['reason']=='captcha_review_pending'


def test_actual_writing_transport_receives_image_file_before_model_call(tmp_path,monkeypatch):
    from hotpost.writing.jobs import Jobs
    settings=Settings(data_dir=tmp_path);received=[]
    monkeypatch.setattr(Jobs,'start',lambda self:self.work())
    def chat(*args,images,**kwargs):
        assert len(images)==1 and Path(images[0]).is_file()
        with Image.open(images[0]) as image:assert image.size==(320,480)
        received.append(str(images[0]))
        return verdict(False)
    monkeypatch.setattr('hotpost.writing.codex_writer.chat',chat)
    pointer=review_page(settings,'tiktok',Page())
    assert pointer['status']=='clear' and len(received)==1
    job_payload=json.loads((Path(received[0]).parent/'payload.json').read_text('utf8'))
    assert job_payload['media'][0]['inlineData']['_external_file']==Path(received[0]).name


def test_page_changing_during_review_cannot_apply_old_positive_image(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path);page=Page()
    def reviewer(*args):
        page.body='Normal product search results'
        return verdict(True)
    pointer=review_page(settings,'tiktok',page,reviewer=reviewer)
    record=saved_review(pointer)
    assert pointer['status']=='captcha_review_pending'
    assert record['review']['verdict']=='captcha' and record['reason']=='page_changed_during_screenshot_review'


def test_explicit_recheck_can_retry_uncertain_image_without_deleting_old_evidence(tmp_path):
    from hotpost.search_access import request_manual_recheck
    settings=Settings(data_dir=tmp_path);page=Page();calls=[]
    def uncertain(*args):
        calls.append(1)
        return {'verdict':'uncertain','visible_challenge':False,'observations':['cannot tell'],'reason':'unclear'}
    old=review_page(settings,'tiktok',page,reviewer=uncertain)
    assert review_page(settings,'tiktok',page,reviewer=uncertain)==old and len(calls)==1
    assert request_manual_recheck(tmp_path,'tiktok')
    new=review_page(settings,'tiktok',page,reviewer=lambda *args:verdict(False))
    assert new['status']=='clear' and saved_review(old)['status']=='captcha_review_pending'
