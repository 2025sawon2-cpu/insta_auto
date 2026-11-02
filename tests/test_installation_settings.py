import json
import sqlite3

import pytest

from hotpost.installation_settings import read, save, SetupConflict
from hotpost.collection_products import CollectionProducts
from hotpost.monetization_store import MonetizationStore
from hotpost.post_preparation import PostPreparation
from test_publication_accounts import dashboard


VALUES = dict(publication_accounts=['@alice','alice.second'],discovery_account='alice.collects',
              storefront_url='https://influencers.coupang.com/s/alice',collection='My picks')
LOCAL = {'Host':'localhost','Origin':'http://localhost'}


def test_fresh_install_is_empty_redirects_to_setup_and_exposes_no_personal_defaults(dashboard):
    request, settings = dashboard
    status, data = request('GET','/api/installation')
    assert status == 200 and data['can_save'] and not data['configured']
    assert data['values']['publication_accounts'] == [] and data['values']['storefront_url'] == ''
    assert request('GET','/')[0] == 302
    assert request('GET','/api/report')[1]['posts'] == []
    status, display = request('GET','/api/display-settings')
    assert status == 200 and display['values'] == display['defaults']


def test_save_roundtrip_drives_publication_and_discovery_without_starting_workers(dashboard):
    request, settings = dashboard
    status, data = request('PUT','/api/installation',dict(revision=0,values=VALUES),LOCAL)
    assert status == 200 and data['configured'] and data['revision']==1 and not data['login_verified']
    assert request('GET','/api/installation')[1]['values']['publication_accounts']==['alice','alice.second']
    assert request('GET','/api/post-preparations/post')[1]['accounts']==['alice','alice.second']
    products=CollectionProducts(settings.data_dir)
    assert products.config()['account']=='alice.collects'
    assert products.config()['storefront_url']==VALUES['storefront_url']
    assert products.config()['enabled'] is False
    legacy=MonetizationStore(settings.data_dir/'monetization')
    assert legacy.automation()==dict(enabled=False,account='alice',discovery_account='alice.collects')
    with legacy.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM effects').fetchone()[0]==0


@pytest.mark.parametrize('change',[
    {'publication_accounts':[]},{'publication_accounts':['bad/account']},
    {'storefront_url':'https://example.com/s/alice'},{'collection':''},
    {'access_key':'unexpected-secret'}, {'discovery_account':123},
])
def test_invalid_setup_rejected_without_persisting_partial_values(dashboard,change):
    request, settings=dashboard
    status,_=request('PUT','/api/installation',dict(revision=0,values={**VALUES,**change}),LOCAL)
    assert status==400
    assert read(settings.data_dir)['configured'] is False


@pytest.mark.parametrize('headers',[
    {}, {'Host':'localhost','Origin':'https://other.example'},
    {**LOCAL,'CF-Connecting-IP':'198.51.100.1'},
    {'Host':'public.example','Origin':'https://public.example'},
])
def test_setup_writes_require_same_origin_installed_machine(dashboard,headers):
    request,settings=dashboard
    assert request('PUT','/api/installation',dict(revision=0,values=VALUES),headers)[0]==403
    assert not read(settings.data_dir)['configured']


def test_stale_revision_and_active_work_never_overwrite_setup(dashboard):
    request,settings=dashboard
    assert request('PUT','/api/installation',dict(revision=0,values=VALUES),LOCAL)[0]==200
    assert request('PUT','/api/installation',dict(revision=0,values=VALUES),LOCAL)[0]==409
    ledger=MonetizationStore(settings.data_dir/'monetization')
    with ledger.connect() as db:
        db.execute('INSERT INTO effects VALUES(?,?,?,?,?,?,?,?)',('alice.collects','post','product_discovery','id','dispatching','{}',1,1))
    changed={**VALUES,'collection':'Another collection'}
    assert request('PUT','/api/installation',dict(revision=1,values=changed),LOCAL)[0]==409
    assert read(settings.data_dir)['values']['collection']=='My picks'


@pytest.mark.parametrize('effect_status',['dispatching','unknown'])
def test_login_hints_save_during_active_work_without_changing_identity_or_effects(dashboard,effect_status):
    request,settings=dashboard
    assert request('PUT','/api/installation',dict(revision=0,values=VALUES),LOCAL)[0]==200
    ledger=MonetizationStore(settings.data_dir/'monetization')
    with ledger.connect() as db:
        db.execute('INSERT INTO effects VALUES(?,?,?,?,?,?,?,?)',
                   ('alice.collects','post','product_discovery','id',effect_status,'{}',1,1))
    drafts=PostPreparation(settings)
    with drafts.connect() as db:
        db.execute('INSERT INTO coupang_link_jobs VALUES(?,?,?,?,?,?,?,?,?)',
                   ('link','post','running','{}','{}','pending',1,0,0))
    routes={'alice':{'provider':'google','account_hint':'saved@example.test'}}
    status,saved=request('PUT','/api/installation',dict(revision=1,values={**VALUES,'littly_logins':routes}),LOCAL)
    assert status==200 and saved['values']['littly_logins']==routes
    with ledger.connect() as db:
        assert db.execute('SELECT status FROM effects WHERE id=?',('id',)).fetchone()[0]==effect_status
    with drafts.connect() as db:
        assert db.execute('SELECT status FROM coupang_link_jobs WHERE id=?',('link',)).fetchone()[0]=='running'
    changed={**saved['values'],'publication_accounts':['alice','another.brand']}
    assert request('PUT','/api/installation',dict(revision=2,values=changed),LOCAL)[0]==409


def test_legacy_settings_prefill_without_replacing_configuration_or_draft(tmp_path):
    root=tmp_path/'data';root.mkdir()
    products=CollectionProducts(root)
    products.configure('existing.collector','https://influencers.coupang.com/s/existing','Existing','browser')
    before=products.config()
    draft_db=root/'post-preparation.sqlite3'
    with sqlite3.connect(draft_db) as db:
        db.execute('CREATE TABLE keep_me(value TEXT)');db.execute('INSERT INTO keep_me VALUES(?)',('untouched',))
        db.execute('CREATE TABLE drafts(shortcode TEXT, value TEXT, updated REAL)')
        db.execute('INSERT INTO drafts VALUES(?,?,?)',('post',json.dumps({'selected_accounts':['existing.brand']}),1))
    draft_bytes=draft_db.read_bytes()
    data=read(root)
    assert data['configured'] and data['values']['discovery_account']=='existing.collector'
    assert data['values']['publication_accounts']==['existing.brand']
    save(root,dict(revision=0,values=data['values']))
    assert products.config()==before
    assert draft_bytes==draft_db.read_bytes()


def test_same_instagram_account_can_be_used_for_both_roles(tmp_path):
    data=save(tmp_path,dict(revision=0,values={**VALUES,'discovery_account':''}))
    assert data['values']['discovery_account']=='alice'


@pytest.mark.parametrize('active',['queue','link'])
def test_pending_collection_and_running_link_keep_existing_identity(tmp_path,active):
    save(tmp_path,dict(revision=0,values=VALUES))
    if active=='queue':
        service=CollectionProducts(tmp_path)
        with service.store.connect() as db:
            db.execute('INSERT INTO collection_product_queue VALUES(?,?)',('post',json.dumps({'status':'pending'})))
    else:
        with sqlite3.connect(tmp_path/'post-preparation.sqlite3') as db:
            db.execute('CREATE TABLE coupang_link_jobs(status TEXT)')
            db.execute("INSERT INTO coupang_link_jobs VALUES('running')")
    with pytest.raises(SetupConflict):
        save(tmp_path,dict(revision=1,values={**VALUES,'discovery_account':'another'}))
    assert read(tmp_path)['revision']==1


def test_collector_configuration_does_not_invent_personal_publication_accounts(tmp_path):
    CollectionProducts(tmp_path).configure('collector','https://influencers.coupang.com/s/store','Collection','browser')
    data=read(tmp_path)
    assert data['values']['publication_accounts']==[]
    assert not data['configured']


def test_publication_choices_can_change_without_changing_pending_product_identity(tmp_path):
    save(tmp_path, dict(revision=0, values=VALUES))
    products = CollectionProducts(tmp_path)
    before = products.config()
    pending = json.dumps({'status': 'pending', 'account': 'alice.collects'})
    with products.store.connect() as db:
        db.execute('INSERT INTO collection_product_queue VALUES(?,?)', ('post', pending))
    result = save(tmp_path, dict(revision=1, values={**VALUES,
        'publication_accounts': ['alice', 'alice.collects']}))
    assert result['values']['publication_accounts'] == ['alice', 'alice.collects']
    assert products.config() == before
    with products.store.connect() as db:
        assert db.execute('SELECT state FROM collection_product_queue').fetchone()[0] == pending


@pytest.mark.parametrize('change', [
    {'discovery_account': 'another'}, {'collection': 'Another collection'},
    {'storefront_url': 'https://influencers.coupang.com/s/another'},
    {'publication_accounts': ['another', 'alice']},
])
def test_pending_product_identity_changes_still_conflict(tmp_path, change):
    save(tmp_path, dict(revision=0, values=VALUES))
    products = CollectionProducts(tmp_path)
    with products.store.connect() as db:
        db.execute('INSERT INTO collection_product_queue VALUES(?,?)',
                   ('post', json.dumps({'status': 'pending'})))
    with pytest.raises(SetupConflict):
        save(tmp_path, dict(revision=1, values={**VALUES, **change}))
    assert read(tmp_path)['revision'] == 1


@pytest.mark.parametrize('provider', ['google', 'chrome'])
def test_login_routes_survive_legacy_saves_and_keep_account_registration_optional(tmp_path, provider):
    from hotpost.installation_settings import littly_login_routes, require_littly_login
    routes={'alice':{'provider':provider,'account_hint':'first@example.test'},
            'alice.second':{'provider':'kakao','account_hint':'saved Kakao account'}}
    state=save(tmp_path,dict(revision=0,values={**VALUES,'littly_logins':routes}))
    assert not state['login_verified']
    assert require_littly_login(tmp_path,'@alice')['provider']==provider
    assert not require_littly_login(tmp_path,'alice.second')['login_verified']
    changed=save(tmp_path,dict(revision=1,values={**VALUES,
        'publication_accounts':['alice','new.brand']}))
    assert changed['values']['littly_logins']=={'alice':routes['alice']}
    by_account={r['account']:r for r in littly_login_routes(changed['values'])}
    assert by_account['alice']['configured'] and not by_account['new.brand']['configured']
    with pytest.raises(ValueError,match='new.brand.*리틀리 로그인 방식'):
        require_littly_login(tmp_path,'new.brand')
    # Partial hints can be saved without claiming that login is ready.
    partial=save(tmp_path,dict(revision=2,values={**changed['values'],
        'littly_logins':{'new.brand':{'provider':'kakao','account_hint':''}}}))
    assert not any(r['configured'] for r in littly_login_routes(partial['values']))


@pytest.mark.parametrize('routes',[
    [], {'unknown':{'provider':'google','account_hint':'account'}},
    {'alice':{'provider':'other','account_hint':'account'}},
    {'alice':{'provider':'google','account_hint':123}},
    {'alice':{'provider':'kakao','account_hint':'line\nbreak'}},
    {'alice':{'provider':'google','account_hint':'x'*161}},
    {'alice':{'provider':'google','account_hint':'account','password':'do-not-store'}},
    {'alice':{'provider':'google','account_hint':'a'},'@alice':{'provider':'kakao','account_hint':'b'}},
])
def test_invalid_or_credential_login_fields_are_rejected(tmp_path,routes):
    with pytest.raises(ValueError):
        save(tmp_path,dict(revision=0,values={**VALUES,'littly_logins':routes}))
    assert not read(tmp_path)['configured']


def test_login_identifiers_are_visible_only_on_local_setup(dashboard):
    request,settings=dashboard
    values={**VALUES,'littly_logins':{'alice':{'provider':'google','account_hint':'private@example.test'}}}
    assert request('PUT','/api/installation',dict(revision=0,values=values),LOCAL)[0]==200
    local=request('GET','/api/installation',headers={'Host':'localhost'})[1]
    assert local['values']['littly_logins']==values['littly_logins']
    for headers in [{'Host':'public.example'},
                    {'Host':'localhost','CF-Connecting-IP':'198.51.100.1'}]:
        public=request('GET','/api/installation',headers=headers)[1]
        assert not public['can_save'] and 'littly_logins' not in public['values']
        assert 'private@example.test' not in json.dumps(public)
    assert read(settings.data_dir)['values']['littly_logins']==values['littly_logins']
