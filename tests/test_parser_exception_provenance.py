import copy
import json

from hotpost.config import Settings
from hotpost import source_parser_recovery as recovery
from test_parser_owner_recovery import blocked_job


def test_generic_failure_reaches_bound_receipt_without_exposing_exception_text(tmp_path,monkeypatch):
    state,job=blocked_job(tmp_path,monkeypatch)
    job['task_id']=state['id']
    settings=Settings(data_dir=tmp_path,source_browser_search=True)
    before=(tmp_path/'search_readiness/tiktok.json').read_bytes()
    original=copy.deepcopy(state)
    writes=[]
    class Store:
        def get(self,task):
            assert task==state['id']
            return copy.deepcopy(state)
        def checkpoint(self,current,checkpoint):
            assert current['id']==job['id']
            writes.append(copy.deepcopy(checkpoint))
    def unavailable(*args,**kwargs):
        raise RuntimeError('secret cookie and private service URL must not be persisted')
    monkeypatch.setattr(recovery,'read_response',unavailable)
    assert recovery.recover_response(settings,Store(),state,job) is False
    receipt=writes[-1]['parser_response_recovery']
    assert receipt['task_id']==state['id'] and receipt['job_id']==job['id']
    assert receipt['run_id']==state['run_id']
    assert receipt['status']=='unavailable' and receipt['error_type']=='RuntimeError'
    assert receipt['query_submitted'] is False and receipt['grants_media_approval'] is False
    assert 1<=len(receipt['error_frames'])<=8
    assert receipt['error_frames'][-1]['function']=='unavailable'
    assert all(set(row)=={'module','function','line'} for row in receipt['error_frames'])
    assert 'secret cookie' not in json.dumps(receipt)
    assert (tmp_path/'search_readiness/tiktok.json').read_bytes()==before
    assert state==original
