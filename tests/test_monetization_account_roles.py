import pytest

from hotpost.monetization_store import MonetizationStore, MonetizationConflict
from test_monetization import followup_fixture


def test_split_accounts_are_bound_to_their_own_ui_and_receipts(tmp_path):
    service, calls, _, _ = followup_fixture(tmp_path)
    observed = []
    original_factory = service.browser_factory
    def factory(settings):
        browser = original_factory(settings)
        original_discover = browser.discover_product
        original_littly = browser.register_littly
        browser.preflight = lambda account, providers: observed.append((account, providers))
        def discover(state, *args):
            observed.append(('comment',state['account']))
            return original_discover(state,*args)
        def littly(state,*args):
            observed.append(('littly',state['account']))
            return original_littly(state,*args)
        browser.discover_product = discover
        browser.register_littly = littly
        return browser
    service.browser_factory = factory
    service.store.configure_automation(False, 'mr.salrim', 'ggul_dol2')
    service.run_saved('work-1'); service.close()
    state = service.get('work-1')
    assert state['stage'] == 'awaiting_post'
    assert state['account'] == state['package']['account'] == state['littly']['account'] == 'mr.salrim'
    assert state['discovery_account'] == state['product']['account'] == 'ggul_dol2'
    assert ('comment','ggul_dol2') in observed and ('littly','mr.salrim') in observed
    assert ('ggul_dol2',('instagram','coupang')) in observed
    assert ('mr.salrim',('littly',)) in observed
    with service.store.connect() as db:
        assert db.execute("SELECT account FROM effects WHERE kind='product_discovery'").fetchone()[0] == 'ggul_dol2'
        assert db.execute("SELECT account FROM effects WHERE kind='littly_create'").fetchone()[0] == 'mr.salrim'
        assert db.execute('SELECT account FROM next_post_slots').fetchone()[0] == 'mr.salrim'
    assert len(state['effects']) == 3
    assert service.preview('work-1')['verified'] is True
    assert ('comment','나도') in calls


def test_changed_destination_cannot_repeat_same_discovery_account_and_reference(tmp_path):
    store = MonetizationStore(tmp_path)
    a = store.prepare('a','publish_a','Reference',{},'ggul_dol2')
    b = store.prepare('b','publish_b','Reference',{},'ggul_dol2')
    store.reserve_effect(a,'product_discovery',{'keyword':'나도'})
    with pytest.raises(MonetizationConflict):
        store.reserve_effect(b,'product_discovery',{'keyword':'나도'})
    assert not store.next_post_busy('publish_b')
    assert len(store.effects(b)) == 1


def test_split_account_interruption_recovers_owner_and_preserves_one_attempt(tmp_path):
    store = MonetizationStore(tmp_path)
    state = store.prepare('a','mr.salrim','Reference',{},'ggul_dol2')
    store.reserve_effect(state,'product_discovery',{'keyword':'나도'})
    MonetizationStore(tmp_path).recover_abandoned()
    current = store.get('a')
    assert current['status'] == 'error'
    assert store.effects(current)[0]['status'] == 'unknown'
    assert not store.next_post_busy('mr.salrim')
    with pytest.raises(MonetizationConflict):
        store.reserve_effect(current,'product_discovery',{})


def test_role_correction_is_explicit_and_only_before_attempts(tmp_path):
    service, _, _, _ = followup_fixture(tmp_path)
    initial = service.prepare('work-1','ggul_dol2')
    service.store.configure_automation(False,'mr.salrim','ggul_dol2')
    with pytest.raises(MonetizationConflict): service.run_saved('work-1')
    fixed = service.rebind_account('work-1',initial['revision'])
    assert fixed['account'] == 'mr.salrim' and fixed['discovery_account'] == 'ggul_dol2'
    assert fixed['binding'] == initial['binding']
    service.store.reserve_effect(fixed,'product_discovery',{})
    with pytest.raises(ValueError): service.store.change('work-1',{'discovery_account':'someone_else'})
    with pytest.raises(MonetizationConflict):
        service.store.rebind_unstarted_account('work-1','other',expected=service.store.get('work-1')['revision'],discovery_account='ggul_dol2')
