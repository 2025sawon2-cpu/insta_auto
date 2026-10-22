import copy
import json
import sqlite3
from types import SimpleNamespace
import pytest
from hotpost import studio_sources as sources
from hotpost import source_interval_recovery as recovery
from hotpost.source_quality import sha256_file
from hotpost.source_preparation import PreparationEvidenceWaiting

@pytest.mark.parametrize('tampered',[False,True])
def test_db_restore_and_real_cache(tmp_path,monkeypatch,tampered):
    reference=tmp_path/'r.mp4'; reference.write_bytes(b'reference')
    media=tmp_path/'s.mp4'; media.write_bytes(b'source')
    source={'id':'s','path':str(media),'sha256':sha256_file(media),
            'video_meta':{'duration':6},'overlay_review_error':'needs review'}
    state={'id':'t','run_id':'run','reference_video':str(reference),
           'product':'soup','original_text':'original','sources':[source]}
    binding={'policy':recovery.POLICY,'task_id':'t','reference_sha256':sha256_file(reference),
             'product':'soup','original_text':'original'}
    context_key=recovery.key(binding)
    root=tmp_path/'c'; root.mkdir()
    evidence_path=root/'overview-evidence.json'
    evidence_path.write_text(json.dumps({'source_sha256':source['sha256'],
        'source_path':str(media),'frames':[]}),encoding='utf8')
    proposal_binding={'policy':recovery.POLICY,'source_sha256':source['sha256'],
        'reference_sha256':binding['reference_sha256'],'product':'soup',
        'context_key':context_key,'evidence_sha256':sha256_file(evidence_path)}
    identity=recovery.key(proposal_binding)
    cache=root/('proposal-'+identity[:20]+'.json')
    windows=[{'start':1.,'end':2.}]
    cache.write_text(json.dumps({'binding':proposal_binding,'windows':windows}),encoding='utf8')
    digest=sha256_file(cache)
    prior={**binding,'context_key':context_key,'proposals':{identity:digest},
           'receipts':{'historical':{'status':'accepted'}}}
    db=sqlite3.connect(':memory:')
    db.execute('CREATE TABLE jobs (id TEXT, task_id TEXT, status TEXT, checkpoint TEXT)')
    def insert(job_id,task,status,context):
        db.execute('INSERT INTO jobs VALUES (?,?,?,?)',(job_id,task,status,
            json.dumps({'interval_recovery':{context_key:context}})))
    insert('completed','t','done',prior)
    poison={**prior,'proposals':{identity:'f'*64}}
    insert('other-task','other','done',poison)
    insert('running','t','running',poison)
    insert('current','t','done',poison)
    db.commit()
    job={'id':'current','task_id':'t','payload':{},'checkpoint':{}}
    snapshots=[]
    def checkpoint(current,value):
        snapshots.append(json.loads(json.dumps(value)))
    store=SimpleNamespace(connect=lambda:db,get=lambda task:copy.deepcopy(state),checkpoint=checkpoint)
    reviews=[]
    def normal_review(state_arg,job_arg,candidates,progress):
        reviews.extend(copy.deepcopy(candidates))
        return candidates,{}
    owner=SimpleNamespace(store=store,settings=SimpleNamespace(source_min_usable=5),
        folder=lambda task:tmp_path,_review_source_records=normal_review)
    monkeypatch.setattr(sources,'source_goal',lambda *a,**k:{'ready':False,
        'policy_version':6,'core_ready':False,'source_diversity_ready':False})
    import hotpost.studio_pause as pause
    monkeypatch.setattr(pause,'check_paused',lambda *a:None)
    # Synthetic decoding boundary only; source, evidence and cache SHA checks run.
    monkeypatch.setattr(recovery,'_check_evidence',lambda evidence:None)
    calls=[]
    def resume(settings,candidate,folder,runtime,review,**kwargs):
        assert folder==tmp_path/'source-mask-checks'/source['sha256'][:20]/'local-interval-recovery'/context_key[:20]
        kwargs['check']()
        assert runtime['receipts']=={}
        assert runtime['proposals']=={identity:digest}
        actual,_=recovery.propose(settings,candidate,root,runtime,
            generate=lambda *a,**k:pytest.fail('must reuse cache'))
        calls.append(actual)
        return review(copy.deepcopy(candidate))
    monkeypatch.setattr(recovery,'recover',resume)
    method=next(value._recover_local_source_intervals for value in vars(sources).values()
        if isinstance(value,type) and '_recover_local_source_intervals' in value.__dict__)
    try:
        if tampered:
            cache.write_text(cache.read_text(encoding='utf8')+' ',encoding='utf8')
            with pytest.raises(PreparationEvidenceWaiting,match='SHA'):
                method(owner,state,job,lambda *a:None)
            assert reviews==[] and calls==[]
        else:
            assert method(owner,state,job,lambda *a:None) is None
            assert calls==[windows]
            assert reviews==[source]
        assert snapshots
        saved=snapshots[0]['interval_recovery'][context_key]
        assert saved['proposals']=={identity:digest}
        assert saved['receipts']=={}
        assert state['sources']==[source]
        assert 'manual_usage_review' not in state['sources'][0]
    finally:
        db.close()

def test_conflict_atomic_and_binding_isolated():
    binding={'policy':recovery.POLICY,'task_id':'task','reference_sha256':'a'*64,
             'product':'soup','original_text':'original'}
    context_key=recovery.key(binding)
    prior={**binding,'context_key':context_key,'proposals':{'b'*64:'c'*64}}
    context={'proposals':{'b'*64:'d'*64},'receipts':{}}
    before=copy.deepcopy(context)
    with pytest.raises(ValueError,match='Conflicting'):
        recovery.restore_proposal_ledger(context,binding,context_key,
            [{'interval_recovery':{context_key:prior}}])
    assert context==before
    for field in [*binding,'context_key']:
        empty={'proposals':{},'receipts':{}}
        recovery.restore_proposal_ledger(empty,binding,context_key,
            [{'interval_recovery':{context_key:{**prior,field:'different'}}}])
        assert empty=={'proposals':{},'receipts':{}}
