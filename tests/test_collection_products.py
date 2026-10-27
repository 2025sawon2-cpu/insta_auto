import json
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from hotpost.collection_products import CollectionProducts, read_result, keyword_from_caption
from hotpost.post_preparation import PostPreparation


STORE = 'https://influencers.coupang.com/s/own'
PRODUCT = 'https://www.coupang.com/vp/products/123?itemId=456&vendorItemId=789'
LINK = 'https://link.coupang.com/re/AFFSDP?lptag=own&portal=CREATOR&pageKey=123&itemId=456&vendorItemId=789'


def report(*codes):
    return dict(is_sample=False, ranking_mode='views_per_follower_72h', collection_started_at=100,
                posts=[dict(shortcode=c,username='author',caption='댓글에 ‘텐트’ 남겨주세요',eligible=True,kind='reel') for c in codes])


@pytest.fixture
def service(tmp_path):
    root=tmp_path/'data';root.mkdir()
    ledger=CollectionProducts(root)
    ledger.configure('collector',STORE,'살림템','existing-extension')
    (root/'report.json').write_text(json.dumps(report('new','other')),'utf8')
    return ledger


def evidence(service, name, **fields):
    path=service.root/(name+'.json')
    path.write_text(json.dumps(dict(observed_at=time.time(),**fields)),'utf8')
    return path


def begin(service, code='new'):
    service.enqueue(report(code))
    proof=evidence(service,'preflight',account='collector',author='author',shortcode=code,
                   browser_extension='existing-extension',storefront_url=STORE,
                   keyword='텐트',caption='댓글에 ‘텐트’ 남겨주세요',dm_baseline=['old-message'])
    return service.begin(code,proof)


def test_only_truly_new_qualified_posts_queue_and_no_backfill_on_configure(tmp_path):
    root=tmp_path/'data';root.mkdir()
    (root/'report.json').write_text(json.dumps(report('old')),'utf8')
    ledger=CollectionProducts(root)
    ledger.configure('collector',STORE,'살림템','existing-extension')
    r=report('old','new','low','image','daiso')
    r['posts'][2]['eligible']=False;r['posts'][3]['kind']='image'
    r['posts'][4]['caption']='다이소 제품'
    assert ledger.enqueue(r)==['new']
    assert ledger.enqueue(r)==[]
    r['posts'][2]['eligible']=True
    assert ledger.enqueue(r)==[]  # previously observed ineligible is not newly collected
    assert [s['shortcode'] for s in ledger.items()]==['new']


def test_durable_outbox_survives_later_upsert_and_repeated_publish(service):
    assert service.enqueue(report('new'))==['new']
    assert service.enqueue(report('new'),known=['new'])==[]
    assert service.get('new')['status']=='pending'
    current=report('new');current['collection_started_at']=101
    (service.root/'report.json').write_text(json.dumps(current),'utf8')
    assert begin(service)['status']=='comment_reserved'


def test_legacy_attempt_blocks_new_comment_and_our_reservation_blocks_legacy(service):
    with service.store.connect() as db:
        db.execute('INSERT INTO effects VALUES(?,?,?,?,?,?,?,?)',('collector','new','product_discovery','old','error','{}',1,1))
    with pytest.raises(ValueError,match='기존 상품 확인'):
        begin(service)
    assert service.get('new')['status']=='pending'


def test_duplicate_begin_and_parallel_second_post_refused(service):
    state=begin(service)
    with pytest.raises(ValueError,match='이미 시작'):
        begin(service)
    with pytest.raises(ValueError,match='앞선 상품'):
        begin(service,'other')
    with service.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM effects WHERE kind='product_discovery'").fetchone()[0]==1
    service.fail('new',state['token'],'DM timeout, no retry')
    with pytest.raises(ValueError,match='이미 시작'):
        begin(service)


def advance_to_link(service):
    state=begin(service);token=state['token']
    service.advance('new',token,'comment_confirmed',evidence(service,'comment',account='collector',comment_id='new-comment',keyword='텐트'))
    with pytest.raises(ValueError,match='새 DM'):
        service.advance('new',token,'dm_received',evidence(service,'old-dm',sender='author',incoming=True,message_id='old-message'))
    service.advance('new',token,'dm_received',evidence(service,'dm',sender='author',incoming=True,message_id='new-message'))
    service.reserve_action('new',token,'product_button')
    with pytest.raises(ValueError,match='이미 예약'):
        service.reserve_action('new',token,'product_button')
    service.advance('new',token,'product_verified',evidence(service,'product',product_url=PRODUCT,product_name='exact tent',dm_button_url='https://example.test/button',message_id='new-message'))
    service.advance('new',token,'link_reserved',evidence(service,'store',storefront_url=STORE,collection='살림템'))
    return token


def completion(service, **changes):
    value=dict(one_link=LINK,product_name='exact tent',product_url=PRODUCT,storefront_url=STORE,
               landing_verified=True,final_url=PRODUCT,store_record_evidence=dict(one_link=LINK,storefront_url=STORE,
               product_id='123',item_id='456',vendor_item_id='789'))
    value.update(changes)
    return evidence(service,'completion',**value)


def test_exact_landing_and_own_store_required_then_read_reuses_without_draft_write(service):
    token=advance_to_link(service)
    with pytest.raises(ValueError,match='상품 또는 옵션'):
        service.advance('new',token,'completed',completion(service,final_url=PRODUCT.replace('456','999')))
    with pytest.raises(ValueError,match='내 스토어'):
        service.advance('new',token,'completed',completion(service,storefront_url=STORE+'wrong'))
    service.advance('new',token,'completed',completion(service))
    assert read_result(service.root,'new')['one_link']==LINK
    prep=PostPreparation(SimpleNamespace(data_dir=service.root))
    assert prep.get('new')['draft']['product_link']==LINK
    with prep.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM drafts').fetchone()[0]==0
    current=prep.get('new');current['draft']['product_link']='https://example.test/user-choice'
    prep.save('new',dict(revision=0,draft=current['draft']))
    assert prep.get('new')['draft']['product_link']=='https://example.test/user-choice'


def test_prior_evidence_mutation_blocks_completion(service):
    token=advance_to_link(service)
    (service.root/'comment.json').write_text('{}','utf8')
    with pytest.raises(ValueError,match='근거 파일'):
        service.advance('new',token,'completed',completion(service))
    assert service.get('new')['status']=='link_reserved'


def test_keyword_comes_from_post_body_not_global_nado():
    assert keyword_from_caption("📌댓글에 ‘오프너’ 남겨주세요")['keyword']=='오프너'
    assert keyword_from_caption("궁금하신분들 '원목' 남겨주세요")['keyword']=='원목'
    assert keyword_from_caption('아무 댓글이나 남겨주세요')['keyword']=='나도'
    with pytest.raises(ValueError):
        keyword_from_caption('제품 소개입니다')


def test_unpublished_snapshot_cannot_start_comment(service):
    r=report('future');r['collection_started_at']=999
    service.enqueue(r)
    proof=evidence(service,'future',account='collector',author='author',shortcode='future',
                   browser_extension='existing-extension',storefront_url=STORE,
                   keyword='텐트',caption='댓글에 ‘텐트’ 남겨주세요',dm_baseline=[])
    with pytest.raises(ValueError,match='현재 리포트'):
        service.begin('future',proof)


def test_prior_ui_link_attempt_blocks_collection_and_completed_collection_blocks_ui(service):
    prep=PostPreparation(SimpleNamespace(data_dir=service.root))
    with prep.connect() as db:
        db.execute('INSERT INTO coupang_link_jobs VALUES(?,?,?,?,?,?,?,?,?)',('prior','new','failed','{}','{}','failed',1,1,1))
    with pytest.raises(ValueError,match='원링크 시도'):
        begin(service)


def test_read_absent_result_creates_no_ledger(tmp_path):
    assert read_result(tmp_path,'new') is None
    assert not (tmp_path/'monetization').exists()


def test_legacy_recovery_does_not_reclassify_live_collection_and_unknown_not_overwritten(service):
    token=advance_to_link(service)
    service.store.recover_abandoned()
    with service.store.connect() as db:
        assert db.execute("SELECT status FROM effects WHERE kind='product_discovery'").fetchone()[0]=='dispatching'
        db.execute("UPDATE effects SET status='unknown' WHERE kind='product_discovery'")
    with pytest.raises(ValueError,match='불명확'):
        service.advance('new',token,'completed',completion(service))
    with service.store.connect() as db:
        assert db.execute("SELECT status FROM effects WHERE kind='product_discovery'").fetchone()[0]=='unknown'


def test_verified_own_prior_success_reused_without_new_comment(service):
    prep=PostPreparation(SimpleNamespace(data_dir=service.root))
    result=dict(status='one_link_ready',one_link=LINK,landing_verified=True,final_url=PRODUCT,
                product_name='exact tent',storefront_url=STORE)
    with prep.connect() as db:
        db.execute('INSERT INTO coupang_link_jobs VALUES(?,?,?,?,?,?,?,?,?)',
                   ('prior','new','completed','{}',json.dumps(result),'done',1,1,1))
    assert begin(service)['reused_link_job_id']=='prior'
    assert read_result(service.root,'new')['one_link']==LINK
    with service.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM effects').fetchone()[0]==0


def test_shared_admission_prevents_concurrent_ui_and_collection_start(service):
    from hotpost.collection_products import admission
    from hotpost.post_coupang_link import start
    prep=PostPreparation(SimpleNamespace(data_dir=service.root))
    with admission(service.root):
        with pytest.raises(ValueError,match='busy'):
            start(prep,'new',{})
        with pytest.raises(ValueError,match='busy'):
            begin(service)


def test_follow_gate_then_new_product_dm_provenance(service):
    state=begin(service);token=state['token']
    service.advance('new',token,'comment_confirmed',evidence(service,'comment',account='collector',comment_id='new-comment',keyword='텐트'))
    service.advance('new',token,'dm_received',evidence(service,'gate',sender='author',incoming=True,message_id='gate-message'))
    service.reserve_action('new',token,'follow')
    service.reserve_action('new',token,'follow_check')
    service.advance('new',token,'dm_received',evidence(service,'followup',sender='author',incoming=True,message_id='product-message'))
    assert service.get('new')['steps']['dm_received']['value']['message_id']=='gate-message'
    assert service.get('new')['steps']['dm_received_followup']['value']['message_id']=='product-message'
    with pytest.raises(ValueError,match='DM 버튼'):
        service.advance('new',token,'product_verified',evidence(service,'wrong-message',product_url=PRODUCT,product_name='tent',dm_button_url='https://example.test/button',message_id='gate-message'))
    service.advance('new',token,'product_verified',evidence(service,'product',product_url=PRODUCT,product_name='tent',dm_button_url='https://example.test/button',message_id='product-message'))
