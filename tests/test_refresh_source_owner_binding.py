"""Actual public refresh -> actual caller -> actual topic receipt contract."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.studio_store import Conflict
from hotpost.source_policy import montage_policy


@pytest.fixture
def staged(monkeypatch, tmp_path):
    studio = Studio(Settings(data_dir=tmp_path), workers=False)
    state, _ = studio.store.create('new-search', '원문 기반 추가 검색')
    def setup(s, db):
        db.execute("UPDATE jobs SET status='failed',error='retained old failure' WHERE task_id=?", (s['id'],))
        s.update(run_id='current-run', source_policy=montage_policy(),
                 runs=[{'id':'current-run','number':1,'status':'active','artifacts':{},'source_policy':montage_policy()}],
                 automation={'active':False,'paused_by_user':True,'paused_at':123.0},
                 source_acquisition={'queries':[], 'rounds':[]},
                 sources=[{'id':'retained-source','sha256':'a'*64,'path':str(tmp_path/'old.mp4')}])
    studio.store.change(state['id'], setup)
    return studio, state['id']


def full_jobs(studio,task):
    with studio.store.connect() as db:
        rows=[dict(r) for r in db.execute('SELECT * FROM jobs WHERE task_id=?',(task,))]
    for row in rows:
        for key in ('payload','checkpoint'):row[key]=json.loads(row[key])
    return rows


def request(studio, task, **options):
    studio.action(task, 'refresh-sources', {'request':'', **options})
    return next(j for j in full_jobs(studio,task) if j['kind']=='refresh_sources')


def test_public_command_binds_current_run_and_preserves_paused_owner_history(staged):
    studio, task = staged
    original = studio.store.get(task)
    old_jobs = copy.deepcopy(studio.store.jobs(task))
    job = request(studio, task, search_before_saved_reviews=True, run_id='model-spoof')
    assert job['payload']['run_id']=='current-run'
    assert job['payload']['search_before_saved_reviews'] is True
    assert job['payload']['manual_source_request'] is True
    assert job['payload']['pause_token']==123.0
    current = studio.store.get(task)
    assert current['automation']==original['automation']
    assert current['sources']==original['sources'] and current['runs']==original['runs']
    assert current['run_id']==original['run_id']
    assert all(next(j for j in studio.store.jobs(task) if j['id']==old['id'])==old for old in old_jobs)
    with pytest.raises(Conflict):
        request(studio, task, search_before_saved_reviews=True)


@pytest.mark.parametrize('comparison_complete',[True,False])
def test_public_refresh_actual_finder_and_topic_receipt_keep_task_job_run(staged, tmp_path, monkeypatch, comparison_complete):
    from test_source_preparation_reuse import finder_fixture
    from hotpost import source_finder as finder, source_topic_queries as topic
    from hotpost.source_visual_queries import plan_queries
    from hotpost.source_preparation import reusable_query_contract
    studio, task = staged
    settings, media_calls = finder_fixture(tmp_path, monkeypatch)
    settings.source_query_model_enabled = True
    studio.settings = settings
    reference = tmp_path/'retained-reference.mp4'
    reference.write_bytes(b'actual fixed reference')
    studio.store.change(task, lambda s, db: s.update(reference_video=str(reference), product='은색 거울'))
    from hotpost.source_coverage import search_scope_for_state
    def retain_history(s,db):
        s['source_acquisition'].update(strategy_version=2,search_context_ledger_version=1,
            search_identity_ledger_version=1,urls=['https://retained/original'],queries=[{
                'provider':'tiktok','query':'old mirror','status':'results','candidates':1,
                'execution':{'query_submitted':True,'query_url_matched':True},
                'run_id':s['run_id'],'search_context':search_scope_for_state(s)}])
    studio.store.change(task,retain_history)
    job = request(studio, task, search_before_saved_reviews=True)
    claimed = studio.store.claim('sources', task_id=task, job_id=job['id'])
    assert claimed and claimed['id']==job['id']
    before = studio.store.get(task)
    old_reference_bytes = reference.read_bytes()
    monkeypatch.setattr(studio, '_review_deferred_downloads', lambda *a: pytest.fail('old deferred review before explicit search'))
    monkeypatch.setattr(studio, '_review_pending_local_sources', lambda *a: pytest.fail('old local review before explicit search'))
    reviews=[]
    monkeypatch.setattr(studio, '_review_source_records', lambda *a: reviews.append(True) or ([], None))
    monkeypatch.setattr('hotpost.source_planning.cached_enrich_plan', lambda settings, plan, *a, **kw: plan)
    original_topic = topic.cached_topic_queries
    receipt_calls=[]
    def cached(settings, reference, frames, caption, transcript, **kwargs):
        proposal={'subject_identity':{'version':'core-product-identity-v2','kind':'category',
            'product_terms':{'en':['mirror'],'zh':['镜子'],'ko':['거울']},'required_terms':[]},
            'queries':[{'id':lang,'query':q,'language':lang,'viewpoint':'product','semantic_key':'product',
                'text_quotes':[{'source':'caption','quote':caption}],'frame_ids':[]}
                for lang,q in [('en','silver mirror'),('zh','银色 镜子')]]}
        def generate(settings,instruction,data,**options):
            if 'proposal_sha256' not in data:return proposal
            return {'input_sha256':data['input_sha256'],'proposal_sha256':data['proposal_sha256'],
                'search_only':True,'subject_identity_supported':True,'core_identity_complete':comparison_complete,
                'known_subject_identity_complete':comparison_complete,
                'checks':[{'query_id':q['id'],**dict.fromkeys(topic.FLAGS,True)} for q in proposal['queries']]}
        receipt=original_topic(settings,reference,frames,caption,transcript,generate,**kwargs)
        receipt_calls.append(receipt)
        return receipt
    monkeypatch.setattr(topic,'cached_topic_queries',cached)
    actual_finder=finder.find_sources
    observed=[];previous=[]
    def execute(*args,**kwargs):
        observed.append(copy.deepcopy(kwargs['search_context']))
        previous.append(copy.deepcopy(kwargs['previous_searches']))
        assert 'https://retained/original' in kwargs['exclude_urls']
        return actual_finder(*args,**kwargs)
    monkeypatch.setattr(finder,'find_sources',execute)
    result=studio._refresh_sources(before,claimed)
    context=observed[0]
    assert {k:context[k] for k in ('task_id','job_id','run_id')}=={
        'task_id':task,'job_id':claimed['id'],'run_id':'current-run'}
    assert len(receipt_calls)==1 and receipt_calls[0]['owner']=={k:context[k] for k in ('task_id','job_id','run_id')}
    assert previous[0]==before['source_acquisition']['queries']
    capture=next(j for j in full_jobs(studio,task) if j['id']==claimed['id'])
    assert capture['checkpoint']['visual_query_input']['task_id']==task
    assert capture['checkpoint']['visual_query_input']['job_id']==claimed['id']
    assert capture['checkpoint']['visual_query_input']['run_id']=='current-run'
    manifest=json.loads(Path(result['source_search_manifest_path']).read_text('utf8'))
    plan=manifest['product_evidence']
    assert len(plan_queries(plan))==2 and not plan['minimum_query_plan_ready']
    assert reusable_query_contract(plan,context['source_policy'],'은색 거울',context)
    assert reviews==[True]  # New discovery still passes the normal received-media review.
    assert media_calls['download']==media_calls['frames']==1
    current=studio.store.get(task)
    assert current['sources']==before['sources'] and current['automation']==before['automation']
    assert current['run_id']==before['run_id'] and reference.read_bytes()==old_reference_bytes
    assert current['source_acquisition']['queries']==before['source_acquisition']['queries']


def test_default_refresh_still_reviews_saved_local_media_first(staged, monkeypatch):
    studio,task=staged
    job=request(studio,task)
    claimed=studio.store.claim('sources',task_id=task,job_id=job['id'])
    pending={'sources':[],'searches':[],'visual_review_only':True}
    called=[]
    monkeypatch.setattr(studio,'_review_pending_local_sources',lambda *a:called.append(True) or copy.deepcopy(pending))
    monkeypatch.setattr('hotpost.source_finder.find_sources',lambda *a,**k:pytest.fail('default must retain local review priority'))
    assert studio._refresh_sources(studio.store.get(task),claimed)['visual_review_only']
    assert called==[True]


def test_new_user_pause_still_revokes_explicit_refresh(staged):
    from hotpost.studio_pause import StudioPaused
    studio,task=staged
    job=request(studio,task,search_before_saved_reviews=True)
    claimed=studio.store.claim('sources',task_id=task,job_id=job['id'])
    studio.store.change(task,lambda s,db:s['automation'].update(paused_at=456.0))
    with pytest.raises(StudioPaused):studio._refresh_sources(studio.store.get(task),claimed)


def test_explicit_refresh_still_waits_at_real_access_gate(staged, monkeypatch):
    from hotpost.source_access_preflight import SourceAccessWaiting
    studio,task=staged
    studio.settings.source_browser_search=True
    studio.store.change(task,lambda s,db:s['source_acquisition'].update(waiting=True))
    job=request(studio,task,search_before_saved_reviews=True)
    claimed=studio.store.claim('sources',task_id=task,job_id=job['id'])
    before=studio.store.get(task)
    monkeypatch.setattr('hotpost.source_preparation.preflight_preparation',lambda *a:(None,[]))
    monkeypatch.setattr('hotpost.source_access_preflight.current_routes',lambda settings,providers:[
        {'provider':p,'status':'login_required','reason':'saved_manual_gate'} for p in providers])
    monkeypatch.setattr('hotpost.source_finder.find_sources',lambda *a,**k:pytest.fail('access denial cannot start discovery'))
    with pytest.raises(SourceAccessWaiting):
        studio._refresh_sources(before,claimed)
    assert claimed['checkpoint']['source_access_preflight']['ready_routes']==[]
    current=studio.store.get(task)
    assert current['sources']==before['sources'] and current['automation']==before['automation']
    assert current['run_id']==before['run_id']
