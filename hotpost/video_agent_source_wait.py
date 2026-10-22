"""Continue an accepted claim after a resolved parser wait, never a failed retry.

All file reads are bounded and local. The worker still performs its normal media,
preparation, current session, scope and pacing checks before any source request.
"""
import copy
import hashlib
import json
import math
import re
import time
from pathlib import Path


class _Files:
    def __init__(self,root):self.root=Path(root).resolve();self.remaining=32*1024*1024;self.stamps={}
    @staticmethod
    def stamp(path):
        s=path.stat();return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
    def read(self,path,limit=4*1024*1024):
        path=Path(path)
        if not path.resolve().is_relative_to(self.root):raise ValueError('foreign evidence')
        for part in (path,*path.parents):
            if part.is_symlink() or part.is_junction():raise ValueError('linked evidence')
            if part==self.root:break
        stamp=self.stamp(path);size=stamp[2]
        if not 0<=size<=min(limit,self.remaining):raise ValueError('evidence budget')
        with path.open('rb') as stream:raw=stream.read(size+1)
        if len(raw)!=size or self.stamp(path)!=stamp or self.stamps.get(path,stamp)!=stamp:
            raise ValueError('evidence changed')
        self.stamps[path]=stamp
        self.remaining-=len(raw)
        return raw
    def value(self,path,limit=4*1024*1024):return json.loads(self.read(path,limit))
    def unchanged(self):return all(self.stamp(p)==s for p,s in self.stamps.items())


def _evidence_root(db):
    """The store's artifact location; isolated DB tests may bind preserved files."""
    return Path(next(r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main')).parent.parent


def _related(kind,detail,job_id):
    return kind=='source_collection_stopped' or (isinstance(detail,dict) and
        (detail.get('job_id')==job_id or job_id in (detail.get('job_ids') or [])))


def _events(db,row,cp,admission,recovery,receipt,saved):
    rows=list(reversed(db.execute('SELECT id,kind,detail,created FROM events WHERE task_id=? ORDER BY id DESC LIMIT 512',
        (row['task_id'],)).fetchall()))
    expected={'decision_id':admission['decision_id'],'kind':'retry_repaired',**receipt}
    accepted=next((r for r in reversed(rows) if r['kind']=='video_agent_action'
        and json.loads(r['detail'])==expected),None)
    if not accepted:return False
    times=(recovery['at'],saved['created'],accepted['created'],cp['_claim_started_at'],row['updated'],cp['not_before'])
    if not all(type(t) in (int,float) and math.isfinite(t) for t in times):return False
    if not (0<times[0]<=times[1]<=times[2]<times[3]<=times[4]<=times[5]<=time.time()):return False
    tail=[r for r in rows if r['id']>accepted['id'] and _related(r['kind'],json.loads(r['detail']),row['id'])]
    if not tail or len(tail)>64 or len(tail)%2:return False
    previous=accepted['created'];tokens=set()
    for i in range(0,len(tail),2):
        claimed,deferred=tail[i:i+2];a=json.loads(claimed['detail']);b=json.loads(deferred['detail'])
        if (claimed['kind']!='job_timing' or deferred['kind']!='job_timing'
                or a.get('outcome')!='claimed' or b.get('outcome')!='deferred'
                or b.get('wait_kind')!='source_wait'
                or any(a.get(k)!=b.get(k) for k in ('job_id','kind','claim_token','started_at'))
                or a.get('kind')!='collect_sources'):return False
        times=(a.get('started_at'),a.get('observed_at'),b.get('observed_at'),b.get('not_before'))
        if not all(type(t) in (int,float) and math.isfinite(t) for t in times):return False
        if not previous<times[0]<=times[1]<=times[2]<=times[3]:return False
        if not isinstance(a.get('claim_token'),str) or a['claim_token'] in tokens:return False
        tokens.add(a['claim_token']);previous=times[2]
    latest=json.loads(tail[-1]['detail'])
    return all(latest.get(k)==v for k,v in {'job_id':row['id'],'kind':'collect_sources',
        'claim_token':cp['_claim_token'],'started_at':cp['_claim_started_at'],
        'observed_at':row['updated'],'not_before':cp['not_before']}.items())


def _progress(files,state,baseline,row,cp):
    from .source_preparation import payload_key,query_policy,reusable_query_contract
    from .source_search.strategy import normalize_query,consumed_scope
    from .source_search.planner import TEXT_ROUTES,IMAGE_ROUTES
    from .source_query_identity import matches_identity
    from .source_visual_queries import digest
    from .video_agent_context import semantic_fingerprint
    acquisition=state.get('source_acquisition') or {};prior=baseline.get('source_acquisition') or {}
    if 'core_search_plan' in prior:return False
    before=prior.get('interrupted_attempts',[]);after=acquisition.get('interrupted_attempts',[])
    if not isinstance(after,list) or after[:len(before)]!=before or not 1<=len(after)-len(before)<=8:return False
    # The sole allowed additions are exact pre-submit execution receipts and the
    # independently verified finite plan. All other semantic inputs remain fixed.
    projected=copy.deepcopy(state);projected['source_acquisition'].pop('core_search_plan',None)
    if 'interrupted_attempts' in prior:projected['source_acquisition']['interrupted_attempts']=copy.deepcopy(before)
    else:projected['source_acquisition'].pop('interrupted_attempts',None)
    if semantic_fingerprint(projected)!=semantic_fingerprint(baseline):return False
    reference=Path(state['reference_video'])
    scope={'reference_sha256':hashlib.sha256(files.read(reference,16*1024*1024)).hexdigest(),
        'product':normalize_query(state.get('product') or ''),
        'reference_text_sha256':hashlib.sha256((state.get('reviewed_original_text') or state.get('original_text') or '').encode()).hexdigest()}
    selected=cp['planning_preparation'];wanted={'task_id':state['id'],'job_id':row['id'],
        'run_id':state['run_id'],'search_context':scope,'source_policy':state['source_policy']}
    if any(selected.get(k)!=v for k,v in wanted.items()):return False
    path=Path(selected['path'])
    if path.resolve().parent!=files.root/'source-preparations'/state['shortcode']:return False
    raw=files.read(path)
    if hashlib.sha256(raw).hexdigest()!=selected['sha256']:return False
    bundle=json.loads(raw);plan=bundle['query_plan']
    if (bundle['payload_sha256']!=payload_key(bundle) or bundle.get('query_policy')!=query_policy()
            or not reusable_query_contract(plan,state['source_policy'],state.get('product',''),wanted,verify_files=False)):
        return False
    registered={r['path']:r['sha256'] for r in bundle['files']}
    if (len(registered)>32 or len(registered)!=len(bundle['files'])
            or registered.get(bundle['reference'])!=scope['reference_sha256']):return False
    required={bundle['reference'],bundle['sheet'],*bundle['frames']}
    visual=plan['visual_query_evidence']['evidence']
    if (visual.get('reference_sha256')!=scope['reference_sha256']
            or registered.get(visual['reference_path'])!=visual['reference_sha256']
            or any(registered.get(r['path'])!=r['sha256'] for r in visual['frames'])):return False
    required.update([visual['reference_path'],*(r['path'] for r in visual['frames'])])
    if not required<=registered.keys():return False
    for name in required:
        if hashlib.sha256(files.read(name,16*1024*1024)).hexdigest()!=registered[name]:return False
    observations=cp['source_access_preflight']['observations']
    # Reconstruct finite_search_plan's metadata using real receipt validators
    # with files=False: every referenced byte was bounded and hashed above.
    if plan.get('text_query_evidence'):
        from .source_text_query_receipts import plan_text_queries
        rows=plan_text_queries(plan,owner={k:wanted[k] for k in ('task_id','job_id','run_id')},verify_files=False)
    else:
        from .source_visual_queries import plan_queries
        rows=plan_queries(plan,verify_files=False)
    words=list(dict.fromkeys(r['query'] for r in rows if matches_identity(r['query'],plan['search_identity'])))
    history=[r for r in acquisition.get('queries',[]) if isinstance(r,dict)
        and r.get('run_id')==state['run_id'] and r.get('search_context')==scope]
    executed={r.get('provider') for r in history if consumed_scope(r)}
    routes=[r['provider'] for r in observations if r.get('provider') in {*TEXT_ROUTES,*IMAGE_ROUTES}
        and (r.get('status')=='ready' or r.get('status')=='query_exhausted' and r['provider'] in executed)]
    if not words or not routes:return False
    material={'context':{'run_id':state['run_id'],**scope},'identity':plan['search_identity'],'queries':words,
        'frame_sha256':[registered[name] for name in bundle['frames']],'routes':sorted(set(routes))}
    finite={**material,'sha256':digest(material),'excluded_routes':[
        {k:r.get(k) for k in ('provider','status','reason')} for r in observations if r['provider'] not in routes]}
    if finite!=acquisition.get('core_search_plan'):return False
    for descriptor in after[len(before):]:
        manifest=Path(descriptor['manifest_path'])
        if (manifest.parent.parent!=files.root/'source_jobs' or manifest.name!='manifest.json'
                or not re.fullmatch(re.escape(state['shortcode'])+r'-\d+',manifest.parent.name)):
            return False
        receipt_path=manifest.parent/'interrupted-execution-receipt.json'
        if Path(descriptor['receipt_path'])!=receipt_path:return False
        receipt_raw=files.read(receipt_path);receipt=json.loads(receipt_raw)
        if hashlib.sha256(receipt_raw).hexdigest()!=descriptor['receipt_sha256']:return False
        if {k:v for k,v in descriptor.items() if k not in {'receipt_path','receipt_sha256'}}!=receipt:return False
        owner={'task_id':state['id'],'studio_job_id':row['id'],'run_id':state['run_id'],
            'shortcode':state['shortcode'],'source_request':json.loads(row['payload']).get('request',''),
            'reference_sha256':scope['reference_sha256'],'source_policy':state['source_policy'],'search_context':scope}
        if any(receipt.get(k)!=v for k,v in owner.items()):return False
        if any(receipt.get(k) for k in ('searches','candidates','worker_checkpoints')):return False
        if hashlib.sha256(files.read(manifest)).hexdigest()!=receipt['manifest_sha256']:return False
    return True


def resolved_claimed_wait(db,row,state,epoch):
    """Return an authenticated baseline for the existing queue's parent checks."""
    from .video_agent_planning_claim import repaired_child_receipt
    from .video_agent_context import semantic_fingerprint
    try:
        cp=json.loads(row['checkpoint'])
        if row['status'] not in {'queued','paused'} or row['error'] or cp.get('deferred_wait') is not True:return None
        if cp.get('not_before',float('inf'))>time.time() or not cp.get('_claim_token'):return None
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='supervision_jobs'").fetchone():
            if db.execute("SELECT 1 FROM supervision_jobs WHERE task_id=? AND phase='held'",(row['task_id'],)).fetchone():return None
        files=_Files(_evidence_root(db))
        admission=cp['video_agent_retry_admission']
        saved=db.execute('SELECT result,created FROM video_agent_action_receipts WHERE task_id=? AND decision_id=?',
            (row['task_id'],admission['decision_id'])).fetchone()
        if not saved:return None
        receipt=json.loads(saved['result'])
        recovery=next(r for r in cp['video_agent_recoveries'] if
            {k:r.get(k) for k in ('decision_id','method_key')}==admission)
        if not _events(db,row,cp,admission,recovery,receipt,saved):return None
        parser=cp['parser_repair_context'];observations=parser['observations']
        if (parser.get('task_id')!=state['id'] or parser.get('run_id')!=state['run_id']
                or len(observations)!=1 or observations[0].get('provider')!='tiktok'
                or observations[0].get('status')!='readiness_blocked'
                or observations[0].get('manual_gate_active') is not False):return None
        expected=observations[0]['readiness']
        if expected.get('reason')!='page_unresolved' or not expected.get('parser_revision'):return None
        current=files.value(files.root/'search_readiness/tiktok.json')
        recovered=current.get('recovery') or {}
        if (current.get('reason')!='search_response_observed' or current.get('previous_failure')!=expected
                or current.get('parser_revision')!=expected.get('parser_revision')
                or recovered.get('status')!='response_validated' or recovered.get('previous_readiness')!=expected
                or recovered.get('query_submitted') is not False or recovered.get('grants_media_approval') is not False):return None
        moments=(row['updated'],recovered.get('at'),current.get('at'))
        if not all(type(t) in (int,float) and math.isfinite(t) for t in moments):return None
        if not 0<moments[0]<=moments[1]<=moments[2]<=time.time():return None
        for evidence in receipt.get('evidence',[]):
            repair=evidence.get('repair') or {};repair_id=repair.get('repair_id','')
            if not re.fullmatch(r'repair-[a-f0-9]{32}',repair_id):continue
            folder=files.root/'studio/code-repairs'/repair_id
            record=files.value(folder/'repair.json',8*1024*1024)
            if (record.get('status')!='applied' or record.get('binding')!=repair.get('binding')
                    or (record.get('review') or {}).get('binding_sha256')!=repair.get('review_binding_sha256')):continue
            meta=record['incident_fixture']
            if meta.get('relative_path')!='.repair-evidence/incident.json':continue
            raw=files.read(folder/'stage/.repair-evidence/incident.json',16*1024*1024)
            if len(raw)!=meta['bytes'] or hashlib.sha256(raw).hexdigest()!=meta['sha256']:continue
            baseline=json.loads(raw)['task']
            # This complete task's digest must be the original durable host
            # acceptance. Merely editing the fixture/metadata cannot invent it.
            if semantic_fingerprint(baseline)!=(repair.get('binding') or {}).get('input_fingerprint'):continue
            if not repaired_child_receipt(db,row,baseline,epoch):continue
            if _progress(files,state,baseline,row,cp) and files.unchanged():return baseline
    except (OSError,ValueError,KeyError,TypeError,AttributeError,StopIteration,OverflowError):pass
    return None
