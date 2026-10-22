import copy
import pytest

from hotpost.studio_pause import check_paused, StudioPaused
from hotpost.studio_store import StudioStore


def test_manual_source_permission_is_bound_to_exact_pause_generation():
    class Store:
        state={'automation':{'paused_by_user':True,'paused_at':123.}}
        def get(self,task):return copy.deepcopy(self.state)
    store=Store()
    job={'task_id':'x','kind':'refresh_sources','payload':{'manual_source_request':True,'pause_token':123.}}
    check_paused(store,job)
    store.state['automation']['paused_at']=124.
    with pytest.raises(StudioPaused):check_paused(store,job)
    for kind in ['collect_sources','edit','voice']:
        wrong={**job,'kind':kind,'payload':{**job['payload'],'pause_token':124.}}
        with pytest.raises(StudioPaused):check_paused(store,wrong)


def test_cancelled_claim_becomes_paused_once_without_immediate_reclaim(tmp_path):
    store=StudioStore(tmp_path)
    state,_=store.create('fixture','제품',{'protocol':2,'active':False})
    store.change(state['id'],lambda s,db:db.execute("update jobs set kind='refresh_sources'"))
    job=store.claim('sources')
    assert job is not None
    store.change(state['id'],lambda s,db:s['automation'].update(paused_by_user=True,paused_at=123.))
    with pytest.raises(StudioPaused):check_paused(store,job)
    assert store.pause_claimed(job,'사용자 중지')
    revision=store.get(state['id'])['revision']
    assert store.claim('sources') is None
    assert not store.pause_claimed(job,'stale')
    assert store.get(state['id'])['revision']==revision
    assert store.jobs(state['id'])[0]['status']=='paused'
