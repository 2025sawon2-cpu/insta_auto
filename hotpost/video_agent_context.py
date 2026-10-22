"""Bounded evidence and semantic identity for a persistent video owner."""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path

VOLATILE = {'updated','revision','progress','message','heartbeat','last_checked_at'}
PREPARATION_DIAGNOSTIC_MEDIA_BYTES = 128*1024*1024

def search_code(pipeline,repo,query):
    """Literal bounded search in source/test scopes; never a shell or data search."""
    query=str(query)
    if not 2<=len(query)<=200:raise ValueError('검색할 오류 문구나 심볼을 2~200자로 입력하세요.')
    root=pipeline.roots[repo]
    scopes=('hotpost','tests') if repo=='main' else ('auto_capcut/core','tests')
    matches=[]
    for scope in scopes:
        for path in sorted((root/scope).rglob('*.py')):
            if not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size>256000:continue
            raw=path.read_bytes();content=raw.decode('utf-8',errors='replace')
            chunks=content.splitlines(keepends=True);lines=[s.rstrip('\r\n') for s in chunks];offset=0
            for line,text in enumerate(lines,1):
                if query.casefold() in text.casefold():
                    matches.append({'path':path.relative_to(root).as_posix(),'line':line,'text':text[:300],
                        'offset':offset,'base_sha256':hashlib.sha256(raw).hexdigest(),
                        'context':'\n'.join(lines[max(0,line-4):line+3])[:1800]})
                    if len(matches)>=40:return {'status':'completed','matches':matches,'truncated':True}
                offset+=len(chunks[line-1])
    return {'status':'completed','matches':matches,'truncated':False}

def semantic_fingerprint(state):
    # Worker scheduling is not a change to the video's inputs. Keep the full
    # evidence in state/history, but do not invalidate a reviewed repair on a
    # fresh claim, repeated receipt wait, or another identical collection round.
    if isinstance(state,dict) and 'id' in state and 'automation' in state:
        state=dict(state)
        state.pop('status',None)
        state.pop('error',None)
        if isinstance(state.get('automation'),dict):
            state['automation']={k:v for k,v in state['automation'].items() if k!='stage'}
        for collection,fields in (('scripts',('script_id','approved_script_id')),('voices',('voice_id','approved_voice_id')),('edits',('edit_id',))):
            if collection in state:
                selected={state.get(field) for field in fields}-{None}
                state[collection]=[row for row in state[collection] if row.get('id') in selected]
        state.pop('source_search',None)  # UI projection; access gates use acquisition.
        acquisition=dict(state.get('source_acquisition') or {})
        for key in ('round','rounds','queued_at','started_at','execution_seconds',
                    'bounded_rounds','no_progress_rounds','next_attempt_at'):
            acquisition.pop(key,None)
        for key in ('receipt_wait','waiting'):
            if isinstance(acquisition.get(key),dict):
                acquisition[key]={k:v for k,v in acquisition[key].items() if k!='at'}
        if 'source_acquisition' in state:state['source_acquisition']=acquisition
    def clean(value):
        if isinstance(value, dict):
            return {k:clean(v) for k,v in value.items() if k not in VOLATILE}
        if isinstance(value, list):return [clean(v) for v in value]
        return value
    return hashlib.sha256(json.dumps(clean(state),sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def job_method_fingerprint(row):
    """Job inputs/evidence, without queue identity or retry/repair bookkeeping."""
    return _job_method_fingerprint(row,normalize_preflight=True)


def _job_method_fingerprint(row,*,normalize_preflight):
    """The false mode reproduces historical durable parent receipts only."""
    operational={'not_before','_claim_token','_claim_started_at','supervision',
                 'video_agent_input_fingerprint','auto_retries','retry_requested',
                 'service_retries','failure_trace','supervision_model_job_id',
                 'supervision_model_history','interval_recovery','deferred_wait',
                 'video_agent_job_fingerprint','video_agent_parked_repair','video_agent_park_receipt'}
    operational.add('video_agent_retry_admission')
    operational.add('no_progress_hold')
    cp=row['checkpoint'];checkpoint=json.loads(cp) if isinstance(cp,str) else cp
    material={k:v for k,v in checkpoint.items() if k not in operational}
    # The observation time is scheduling evidence, including ordinary scope
    # exhaustion. Keep status, reason, scope and retry deadlines in the method.
    import copy
    material=copy.deepcopy(material)
    for key in (('source_access_preflight','parser_repair_context')
            if normalize_preflight or checkpoint.get('parser_repair_context') else ()):
        value=material.get(key)
        if not isinstance(value,dict):continue
        value.pop('at',None)
        for observation in value.get('observations',[]):
            if isinstance(observation,dict):observation.pop('observed_at',None)
    value=dict(row).get('payload') or {};payload=json.loads(value) if isinstance(value,str) else dict(value)
    if row['kind'] in {'collect_sources','refresh_sources'}:payload.pop('round',None)
    return semantic_fingerprint({'kind':row['kind'],'payload':payload,'checkpoint':material})


def _progress_reviews(value):
    """Project repeated failure bookkeeping only; never alter stored evidence."""
    if isinstance(value,list):return [_progress_reviews(item) for item in value]
    if not isinstance(value,dict):return value
    result={key:_progress_reviews(item) for key,item in value.items()}
    outcome=result.get('review_outcome')
    if isinstance(outcome,dict):outcome.pop('checked_at',None)
    history=result.get('review_error_history')
    if isinstance(history,list):
        unique={}
        for item in history:
            if isinstance(item,dict):item={k:v for k,v in item.items() if k not in {'resolved_at','checked_at'}}
            unique[json.dumps(item,sort_keys=True,ensure_ascii=False,default=str)]=item
        result['review_error_history']=[unique[k] for k in sorted(unique)]
    return result


def queue_progress_fingerprint(state,rows):
    """Stable across queue replacement; changed media/reviews still invalidate it."""
    jobs=[job_method_fingerprint(row) for row in rows]
    fields=('id','automation','run_id','shortcode','reference_video','transcript_path','original_text',
            'script_id','approved_script_id','voice_id','approved_voice_id','edit_id','creation_mode','editorial_content_hold')
    progress_state={key:state[key] for key in fields if key in state}
    for collection,field in (('scripts','script_id'),('voices','voice_id'),('edits','edit_id')):
        selected={state.get(field),state.get('approved_'+field)}-{None}
        progress_state[collection]=[r for r in state.get(collection,[]) if r.get('id') in selected]
    if any(row['kind'] in {'edit','revision','quality_reedit','quality_review','export','register'} for row in rows):
        for key in ('sources','source_policy','source_goal','daily_quality'):
            if key in state:progress_state[key]=state[key]
    if rows and all(row['kind'] in {'collect_sources','refresh_sources'} for row in rows):
        # Unselected drafts/voices and unrelated edit results do not advance a
        # source search. Keep its selected dependencies, source receipts and goal.
        fields=('id','automation','run_id','shortcode','reference_video','transcript_path',
                'original_text','source_policy','source_goal','source_acquisition','sources',
                'source_search_manifest_path','script_id','approved_script_id','voice_id',
                'approved_voice_id','creation_mode','editorial_content_hold')
        progress_state={key:state[key] for key in fields if key in state}
        for collection,field in (('scripts','script_id'),('voices','voice_id')):
            selected={state.get(field),state.get('approved_'+field)}-{None}
            progress_state[collection]=[r for r in state.get(collection,[]) if r.get('id') in selected]
        quality=state.get('daily_quality') or {}
        progress_state['daily_quality']={k:quality[k] for k in ('feedback','narration_context_hold') if k in quality}
        if isinstance(progress_state.get('automation'),dict):
            progress_state['automation']={k:v for k,v in progress_state['automation'].items() if k!='stage'}
    return semantic_fingerprint({'input':semantic_fingerprint(_progress_reviews(progress_state)),
        'jobs':sorted(jobs,key=lambda v:json.dumps(v,sort_keys=True))})


def scope_repair_context(state,row,*,now=None):
    """Recognize an internal exhausted-scope wait, never grant search access."""
    import math
    if row['kind'] not in {'collect_sources','refresh_sources'}:return False
    value=dict(row)
    cp=value.get('checkpoint') or {};cp=json.loads(cp) if isinstance(cp,str) else cp
    payload=value.get('payload') or {};payload=json.loads(payload) if isinstance(payload,str) else payload
    if (not state.get('id') or value.get('task_id')!=state['id']
            or not state.get('run_id') or payload.get('run_id')!=state['run_id']):return False
    acquisition=state.get('source_acquisition') or {}
    if (acquisition.get('no_progress_rounds',0)<=0 or acquisition.get('waiting')
            or acquisition.get('receipt_wait') or acquisition.get('hold')):return False
    if cp.get('deferred_wait') is not True:return False
    if (cp.get('failure_classification') or {}).get('category')=='access_blocked':return False
    pre=cp.get('source_access_preflight') or {}
    at=pre.get('at');observations=pre.get('observations')
    now=time.time() if now is None else now
    if (type(at) not in (int,float) or not math.isfinite(at) or not 0<=at<=now
            or pre.get('ready_routes')!=[] or not isinstance(observations,list) or not observations):return False
    exhausted=False
    for observation in observations:
        if not isinstance(observation,dict) or observation.get('attempted') is not False:return False
        observed=observation.get('observed_at');retry=observation.get('retry_at',0)
        if (type(observed) not in (int,float) or not math.isfinite(observed) or not 0<=observed<=at
                or type(retry) not in (int,float) or not math.isfinite(retry) or retry>now):return False
        if observation.get('status') in {'ready','cooldown'}:return False
        if observation.get('status')=='query_exhausted':
            if observation.get('reason')!='no_unused_supported_scope':return False
            exhausted=True
    return exhausted


def recovery_target(state,rows,ages=None):
    """Bind a diagnostic reservation to the exact repeated, queued method."""
    from .video_agent_actions import _gate, ActionHeld, repair_has_available_route, parser_repair_context
    acquisition=state.get('source_acquisition') or {}
    candidates=[]
    now=time.time()
    for row in rows:
        if row['status']!='queued':continue
        try:_gate(state,'park_for_repair',row)
        except ActionHeld:continue
        checkpoint=json.loads(row['checkpoint'])
        cooldown=checkpoint.get('not_before',0)>now
        internal=bool(checkpoint.get('internal_evidence_wait'))
        parser=parser_repair_context(state,row)
        scope=scope_repair_context(state,row,now=now)
        pacing=(row['kind'] in {'collect_sources','refresh_sources'}
                and checkpoint.get('not_before')==acquisition.get('next_attempt_at')
                and not acquisition.get('waiting') and not checkpoint.get('deferred_wait'))
        if cooldown and not (parser or scope) and (checkpoint.get('deferred_wait') or not (internal or pacing)):continue
        if (checkpoint.get('failure_classification') or {}).get('category')=='access_blocked':continue
        if acquisition.get('hold'):continue
        if (acquisition.get('waiting') or {}).get('searches') and not repair_has_available_route(state,row):continue
        if internal or parser or (row['kind'] in {'collect_sources','refresh_sources'} and acquisition.get('no_progress_rounds',0)>0
                and not acquisition.get('waiting') and not acquisition.get('receipt_wait')):
            since=(ages or {}).get(row['id'],now)
            candidates.append((now-since < (30 if internal or parser else 300),since,row['id']))
    return min(candidates)[2] if candidates else None

def action_prerequisites(studio,task,action):
    """Host-owned prerequisites, distinct from media progress or planner wording."""
    job_id=action.get('job_id') or ((action.get('patch') or {}).get('binding') or {}).get('job_id')
    context={}
    if action.get('kind')=='propose_patch' and any(row.get('replacements') for row in (action.get('patch') or {}).get('files',[])):
        from .video_agent_repairs import SOURCE_REPLACEMENT_CONTRACT
        context['source_replacement_contract']=SOURCE_REPLACEMENT_CONTRACT
    if action.get('repair_id') and action.get('kind') not in {'inspect_repair'}:
        pipeline=getattr(studio,'video_repair_pipeline',None)
        if pipeline:
            record=pipeline._read(action['repair_id'])
            if record['binding'].get('task_id')!=task:raise ValueError('Repair task differs from caller')
            job_id=record['binding']['job_id']
            context['repair_status']=record['status']
            context['review_signature']=(record.get('review') or {}).get('signature')
    if job_id:
        with studio.store.connect() as db:
            row=db.execute('SELECT kind,payload,checkpoint,status FROM jobs WHERE id=? AND task_id=?',(job_id,task)).fetchone()
        if row:context['job']={'status':row['status'],'method':job_method_fingerprint(row)}
    return context


def compact_incident(incident,*,evidence_excerpt=False):
    """Project historical ledgers without erasing current failure prerequisites."""
    if not isinstance(incident,dict):return incident
    result=json.loads(json.dumps(incident,ensure_ascii=False))
    acquisition=(result.get('task') or {}).get('source_acquisition') or {}
    for key in ('rounds','interrupted_attempts','queries','urls','inspected_urls'):
        value=acquisition.get(key)
        if not isinstance(value,list):continue
        raw=json.dumps(value,ensure_ascii=False,sort_keys=True)
        if len(raw)<=10000:continue
        tail=json.dumps(value[-2:],ensure_ascii=False,sort_keys=True)
        acquisition[key]={'historical_ledger_summary':True,'count':len(value),
            'sha256':hashlib.sha256(raw.encode('utf8')).hexdigest(),
            **({'last_items':value[-2:]} if len(tail)<=6000 else {'last_items_excerpt':tail[:4000]})}
        result['projection_note']='Historical ledgers summarized; current job/checkpoint and expected binding remain complete. Original production history is preserved.'
    if evidence_excerpt:
        for artifact in result.get('artifacts') or []:
            if not isinstance(artifact,dict):continue
            contents=[artifact.pop(k,'') for k in ('content','content_head','content_tail')]
            excerpt='\n'.join(s for s in contents if isinstance(s,str) and s)
            if excerpt:artifact.update(content_excerpt=excerpt[:1200],excerpt_only=True)
    return result


def repair_incident(state,job):
    """Freeze the actual blocked inputs for independent repair review."""
    fields=('id','shortcode','run_id','status','error','script_id','voice_id','edit_id',
        'original_text','original_transcript','reference_video','analysis','product_identity',
        'source_policy','source_request','source_goal','source_acquisition','source_search','daily_quality')
    incident={'task':{k:state.get(k) for k in fields},'job':dict(job)}
    for key in ('checkpoint','payload'):
        if isinstance(incident['job'].get(key),str):incident['job'][key]=json.loads(incident['job'][key])
    incident['sources']=[]
    for source in state.get('sources',[]):
        item={k:source.get(k) for k in ('id','sha256','path','manual_usage_review','review_outcome',
            'presentation_review_required','overlay_review_required','relevance_review_required',
            'editing_eligible','source_role','product_source_kind')}
        for name,keys in [('functional_review',('reviewed','same_core_function','context_usable','source_sha256','policy','reason')),
            ('presentation_review',('reviewed','usable','quality_usable','action_preserved','source_sha256','policy','scope','interval_evaluation_required','reason'))]:
            review=source.get(name)
            if isinstance(review,dict):
                item[name]={k:review.get(k) for k in keys}
                item[name].update(projected=True,original_sha256=hashlib.sha256(json.dumps(review,ensure_ascii=False,sort_keys=True).encode()).hexdigest())
        incident['sources'].append(item)
    if job['kind']=='collect_sources':
        from .source_pause_receipts import binding
        try:incident['expected_source_attempt_binding']=binding(state,incident['job'])
        except (OSError,ValueError,KeyError,TypeError) as exc:incident['source_binding_error']=str(exc)
    return compact_incident(incident)


def incident_artifacts(studio,state,job,*,max_characters=220000,max_files=6):
    """Capture bounded, already-authorized original evidence for the reviewer."""
    import re
    cp=job['checkpoint'];cp=json.loads(cp) if isinstance(cp,str) else cp
    paths=[]
    # A captured recovery test needs the registered immutable interruption,
    # not only the manifest it authenticates. Put current receipts first so a
    # bounded diagnostic fixture cannot omit its own recovery entry evidence.
    for attempt in reversed(cp.get('source_attempts') or []):
        if not isinstance(attempt,dict) or not attempt.get('receipt_path'):continue
        try:
            from .source_pause_receipts import verified_receipt
            payload=dict(job).get('payload') or {}
            if isinstance(payload,str):payload=json.loads(payload)
            verified_receipt(studio.settings.source_dir,attempt,state,{**dict(job),'payload':payload})
            paths.append(str(Path(attempt['receipt_path']).resolve()))
        except (OSError,ValueError,TypeError,KeyError,AttributeError,RuntimeError):continue
    paths.extend(causal_readiness_artifacts(studio,state,job))
    message=str((cp.get('failure_trace') or {}).get('message') or dict(job).get('error') or '')
    paths.extend(m.strip() for m in re.findall(r'(?:proposal_path|review_path)=([^|\n]+)',message))
    rejection=(state.get('source_acquisition') or {}).get('visual_query_rejection')
    if isinstance(rejection,dict):
        binding=rejection.get('binding') or {}
        expected={'task_id':state.get('id'),'job_id':dict(job).get('id'),'run_id':state.get('run_id')}
        if isinstance(binding,dict) and all(v and binding.get(k)==v for k,v in expected.items()):
            # Include registered correction evidence, not only initial filenames
            # quoted by the outer exception. All reads still use the own-file guard.
            paths.extend(sorted(artifact_paths(rejection)))
    paths.extend(sorted(artifact_paths({k:v for k,v in cp.items() if k!='source_attempts'})))
    paths.extend(sorted(visual_query_artifact_paths(studio,state,job_id=dict(job).get('id')),
                        key=lambda name:(-len(Path(name).parts),name)))
    for attempt in cp.get('source_attempts') or []:
        if not isinstance(attempt,dict):continue
        if attempt.get('manifest_path'):paths.append(attempt['manifest_path'])
        workers=attempt.get('workers') or []
        if isinstance(workers,list):paths.extend(w['path'] for w in workers if isinstance(w,dict) and w.get('path'))
    if state.get('source_search_manifest_path'):paths.append(state['source_search_manifest_path'])
    paths.extend(sorted(preparation_artifact_paths(studio,state,paths)))
    result=[];seen=set();budget=min(4000000,max(1,int(max_characters)));max_files=min(24,max(1,int(max_files)))
    for name in paths:
        if not isinstance(name,str):continue
        if Path(name).suffix.lower() not in {'.json','.txt','.log','.md','.srt','.vtt'}:continue
        if name in seen or len(result)>=max_files or budget<=0:continue
        seen.add(name)
        try:
            proof=inspect_artifact(studio,state,{'path':name},_full_text=True)
            if 'content' not in proof:continue
            length=proof['total_characters']
            def read_part(start,count):return proof['content'][start:start+count]
            if length>budget:
                tail=min(24000,budget//2);head=budget-tail
                result.append({'path':proof['path'],'sha256':proof['sha256'],'bytes':proof['bytes'],
                    'content_head':read_part(0,head),'content_tail':read_part(length-tail,tail), 'truncated':True})
                budget=0
            else:
                result.append({'path':proof['path'],'sha256':proof['sha256'],'bytes':proof['bytes'],'content':read_part(0,length),'truncated':False})
                budget-=length
        except (OSError,ValueError,TypeError,RuntimeError):continue
    return result


def review_artifacts(artifacts):
    """Bound model review text while the isolated fixture retains full evidence."""
    result=[];budget=220000
    for original in artifacts[:6]:
        if budget<=0:break
        row=dict(original)
        content=row.pop('content',None)
        if content is None:
            head=row.pop('content_head','');tail=row.pop('content_tail','')
            if len(head)+len(tail)>budget:
                tail_size=min(len(tail),24000,budget//2)
                tail=tail[-tail_size:] if tail_size else ''
                head=head[:max(0,budget-len(tail))]
            row.update(content_head=head,content_tail=tail,truncated=True)
            budget-=len(head)+len(tail);result.append(row);continue
        if len(content)<=budget:
            row['content']=content;budget-=len(content)
        else:
            size=min(len(content),budget);tail=min(24000,size//2);head=size-tail
            row.update(content_head=content[:head],content_tail=content[-tail:] if tail else '',truncated=True)
            budget-=size
        result.append(row)
    return result


def causal_readiness_artifacts(studio,state,job):
    """Capture the prior execution behind a current readiness wait, read-only.

    A successor may have no source_attempts: the failing request belongs to an
    earlier job in this run. Locate its hashed evidence by the saved query,
    parser revision and request time, never by guessed paths or error prose.
    This supplies test evidence only and grants no recovery authorization.
    """
    import math
    def finite_time(value):
        try:return type(value) in (int,float) and math.isfinite(value)
        except OverflowError:return False
    try:
        cp=job['checkpoint'];cp=json.loads(cp) if isinstance(cp,str) else cp
        context=cp.get('parser_repair_context') or {}
        if (context.get('task_id')!=state['id'] or not state.get('run_id')
                or context.get('run_id')!=state['run_id']):return []
        observations=context.get('observations') or []
        if not isinstance(observations,list):return []
        targets=[]
        for observation in observations[:32]:
            if not isinstance(observation,dict):continue
            readiness=observation.get('readiness') or {}
            if not isinstance(readiness,dict):continue
            at=readiness.get('at')
            if (observation.get('provider') and readiness.get('query') and readiness.get('parser_revision')
                    and finite_time(at)):
                targets.append((observation['provider'],readiness['query'],readiness['parser_revision'],at))
        if not targets:return []
        allowed={Path(p).resolve() for p in job_artifact_paths(studio,state)}
        def read_registered(name,sha):
            if not isinstance(name,str) or not isinstance(sha,str) or len(sha)!=64:raise ValueError()
            path=Path(name).resolve()
            if path not in allowed:raise ValueError()
            with path.open('rb') as stream:raw=stream.read(4*1024*1024+1)
            if len(raw)>4*1024*1024 or hashlib.sha256(raw).hexdigest()!=sha:raise ValueError()
            return str(path),json.loads(raw)
        with studio.store.connect() as db:
            rows=db.execute("SELECT id,payload,checkpoint FROM jobs WHERE task_id=? AND kind='collect_sources' ORDER BY created DESC LIMIT 128",(state['id'],)).fetchall()
        result=[]
        for row in rows:
            try:
                if json.loads(row['payload']).get('run_id')!=state['run_id']:continue
                attempts=json.loads(row['checkpoint']).get('source_attempts') or []
                if not isinstance(attempts,list):continue
                for attempt in attempts[-32:]:
                    try:
                        expected={'task_id':state['id'],'studio_job_id':row['id'],'run_id':state['run_id'],'shortcode':state.get('shortcode')}
                        if not isinstance(attempt,dict) or any(attempt.get(k)!=v for k,v in expected.items()):continue
                        receipt_path,receipt=read_registered(attempt.get('receipt_path'),attempt.get('receipt_sha256'))
                        if not isinstance(receipt,dict) or any(receipt.get(k)!=v for k,v in expected.items()):continue
                        searches=receipt.get('searches')
                        if not isinstance(searches,list):continue
                        matched=False
                        for search in searches[:512]:
                            if not isinstance(search,dict):continue
                            requests=search.get('requests') or []
                            if not isinstance(requests,list):continue
                            for provider,query,revision,at in targets:
                                if (search.get('provider'),search.get('query'),search.get('parser_revision'))!=(provider,query,revision):continue
                                matched=matched or any(isinstance(r,dict) and finite_time(r.get('at'))
                                    and 0<=at-r['at']<=5 for r in requests[:128])
                        if not matched:continue
                        if receipt.get('manifest_path')!=attempt.get('manifest_path'):continue
                        manifest,_=read_registered(receipt.get('manifest_path'),receipt.get('manifest_sha256'))
                        workers=receipt.get('worker_checkpoints')
                        if not isinstance(workers,list) or not 1<=len(workers)<=16:continue
                        worker_paths=[read_registered(w['path'],w['sha256'])[0] for w in workers]
                        result.extend([receipt_path,*worker_paths,manifest])
                        if len(result)>=24:return list(dict.fromkeys(result))[:24]
                    except (OSError,ValueError,KeyError,TypeError,AttributeError,RuntimeError):continue
            except (ValueError,KeyError,TypeError,AttributeError):continue
        return list(dict.fromkeys(result))
    except (OSError,ValueError,KeyError,TypeError,AttributeError,RuntimeError):return []


def artifact_paths(state):
    paths=set()
    def visit(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if isinstance(item,str) and (key.endswith('_path') or key in {'path','reference_video','manifest'}):
                    paths.add(item)
                elif isinstance(item,(dict,list)):visit(item)
        elif isinstance(value,list):
            for item in value:visit(item)
    visit(state)
    return paths


def job_artifact_paths(studio,state):
    """Read-only evidence registered by this video's own source attempts."""
    source_dir=getattr(studio.settings,'source_dir',None)
    if source_dir is None:return set()
    source_root=Path(source_dir).resolve();allowed=set()
    with studio.store.connect() as db:
        rows=db.execute('SELECT id,checkpoint FROM jobs WHERE task_id=?',(state['id'],)).fetchall()
    for row in rows:
        try:checkpoint=json.loads(row['checkpoint'])
        except (ValueError,TypeError):continue
        if not isinstance(checkpoint,dict):continue
        attempts=checkpoint.get('source_attempts');roots=[]
        if not isinstance(attempts,list):continue
        for entry in attempts:
            if not isinstance(entry,dict):continue
            if (entry.get('task_id')!=state['id'] or entry.get('studio_job_id')!=row['id']
                    or entry.get('shortcode')!=state.get('shortcode') or not entry.get('manifest_path')):continue
            try:manifest=Path(entry['manifest_path']).resolve()
            except (OSError,RuntimeError,ValueError,TypeError):continue
            if (manifest.is_relative_to(source_root) and manifest.parent.name.startswith(str(state['shortcode'])+'-')):
                roots.append(manifest.parent)
        for candidate in artifact_paths(checkpoint):
            try:path=Path(candidate).resolve()
            except (OSError,RuntimeError,ValueError,TypeError):continue
            if any(path.is_relative_to(root) for root in roots):allowed.add(str(path))
    return allowed

def preparation_artifact_paths(studio,state,manifests):
    """Follow only hash-bound preparation bundles in already-owned manifests."""
    return set(_preparation_artifact_bindings(studio,state,manifests))


def _preparation_artifact_bindings(studio,state,manifests):
    """Return the registered expected SHA as well as its authorized path."""
    import re
    shortcode=state.get('shortcode')
    if not isinstance(shortcode,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',shortcode):return {}
    source_root=Path(studio.settings.source_dir).resolve()
    preparation_root=(Path(studio.settings.data_dir)/'source-preparations').resolve()
    own_root=(preparation_root/shortcode).resolve()
    if own_root.parent!=preparation_root or own_root.name!=shortcode:return {}
    registered={Path(p).resolve() for p in artifact_paths(state)|job_artifact_paths(studio,state)}
    result={}
    # Bound historical discovery independently of the text capture budget.
    candidates=dict.fromkeys(str(p) for p in manifests if isinstance(p,(str,Path)) and Path(p).name=='manifest.json')
    for name in list(candidates)[:64]:
        try:
            manifest=Path(name).resolve()
            if (manifest not in registered or manifest.name!='manifest.json'
                    or not manifest.is_relative_to(source_root)
                    or not manifest.parent.name.startswith(shortcode+'-')):continue
            with manifest.open('rb') as stream:raw=stream.read(4*1024*1024+1)
            if len(raw)>4*1024*1024:continue
            value=json.loads(raw)
            if not isinstance(value,dict) or value.get('shortcode')!=shortcode:continue
            target=Path(value['preparation_bundle_path']).resolve()
            if target.suffix!='.json' or not target.is_relative_to(own_root):continue
            expected=value.get('preparation_bundle_sha256')
            if not isinstance(expected,str) or not re.fullmatch(r'[a-f0-9]{64}',expected):continue
            with target.open('rb') as stream:raw=stream.read(4*1024*1024+1)
            if len(raw)>4*1024*1024 or hashlib.sha256(raw).hexdigest()!=expected:continue
            result[str(target)]=expected
        except (OSError,ValueError,TypeError,KeyError,RuntimeError):continue
    return result


def preparation_query_diagnostics(studio,state):
    """Read-only original-plan facts; never select, rebind or approve a plan.

    Relocating test media changes nested receipt hashes. Distinguish that from
    an invalid production plan before an owner invents a needless migration.
    """
    from .source_preparation import payload_key, query_policy, reusable_query_contract
    from .source_policy import run_policy
    from .source_diversity import acquisition_policy
    from .source_search.strategy import normalize_query
    settings=getattr(studio,'settings',None)
    if not getattr(settings,'source_dir',None) or not getattr(settings,'data_dir',None) or not state.get('run_id'):return []
    manifests=artifact_paths(state)|job_artifact_paths(studio,state)
    bindings=_preparation_artifact_bindings(studio,state,manifests)
    paths=sorted(bindings)[:4]
    roots=[Path(settings.source_dir).resolve(),(Path(settings.data_dir)/'transcripts').resolve()]
    shortcode=state.get('shortcode','')
    result=[];remaining=PREPARATION_DIAGNOSTIC_MEDIA_BYTES;checked={}
    def stamp(stat):
        return tuple(getattr(stat,k,None) for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns'))
    def media_digest(raw):
        nonlocal remaining
        path=Path(raw)
        if '..' in path.parts or not path.is_absolute():raise ValueError('Unsafe media path')
        for parent in (path,*path.parents):
            if parent in roots:break
            if parent.is_symlink() or getattr(parent,'is_junction',lambda:False)():
                raise ValueError('Linked media path')
        path=path.resolve()
        root=next((r for r in roots if path.is_relative_to(r)),None)
        if root is None:raise ValueError('Foreign source media')
        relative=path.relative_to(root)
        if len(relative.parts)<2 or not relative.parts[0].startswith(shortcode+'-'):
            raise ValueError('Foreign source media')
        before=path.stat();size=before.st_size
        if path in checked:
            sha,saved=checked[path]
            if stamp(before)!=saved:raise ValueError('Media changed during diagnostic')
            return sha
        if size>remaining:raise ValueError('Diagnostic media budget exceeded')
        remaining-=size
        h=hashlib.sha256()
        with path.open('rb') as stream:
            import os
            opened=os.fstat(stream.fileno())
            # On Windows path stat and descriptor stat can expose different
            # creation/change-time meanings. Compare ctime only within each API.
            if stamp(opened)[:4]!=stamp(before)[:4]:raise ValueError('Media changed during diagnostic')
            read=0
            while chunk:=stream.read(min(1024*1024,size-read+1)):
                read+=len(chunk)
                if read>size:raise ValueError('Media changed during diagnostic')
                h.update(chunk)
            if stamp(os.fstat(stream.fileno()))!=stamp(opened):raise ValueError('Media changed during diagnostic')
        if read!=size:raise ValueError('Media changed during diagnostic')
        if stamp(path.stat())!=stamp(before):raise ValueError('Media changed during diagnostic')
        checked[path]=(h.hexdigest(),stamp(before))
        return h.hexdigest()
    for name in paths:
        row={'path':name,'task_id':state['id'],'run_id':state['run_id'],
             'input_fingerprint':semantic_fingerprint(state),'status':'unverified',
             'scope':'registered original bundle; not selection, retry permission or production approval'}
        result.append(row)
        try:
            with Path(name).open('rb') as stream:raw=stream.read(4*1024*1024+1)
            if len(raw)>4*1024*1024:raise ValueError('Diagnostic bundle budget exceeded')
            row['bundle_sha256']=hashlib.sha256(raw).hexdigest()
            if row['bundle_sha256']!=bindings[name]:raise ValueError('Registered bundle SHA changed')
            value=json.loads(raw);plan=value['query_plan']
            if value.get('payload_sha256')!=payload_key(value):raise ValueError('Bundle payload changed')
            receipt=plan['visual_query_evidence'];evidence=receipt['evidence']
            frames=evidence['frames']
            if not isinstance(frames,list) or not 1<=len(frames)<=64:raise ValueError('Invalid frame list')
            declared={r['path']:r['sha256'] for r in value['files']}
            required=[(evidence['reference_path'],evidence['reference_sha256']),
                      *[(r['path'],r['sha256']) for r in frames]]
            for path,sha in required:
                if declared.get(path)!=sha or media_digest(path)!=sha:
                    raise ValueError('Original media binding changed')
            if media_digest(state['reference_video'])!=evidence['reference_sha256']:
                raise ValueError('Current reference differs from registered bundle')
            # Use unchanged semantic validation on the bounded bytes' hashes.
            # Never let the semantic pass reopen unbounded media. Production
            # callers retain verify_files=True; only this diagnostic opts out.
            policy=acquisition_policy(state,run_policy(state))
            context={'run_id':state['run_id'],'search_context':{
                    'reference_sha256':evidence['reference_sha256'],
                    'product':normalize_query(state.get('product') or ''),
                    'reference_text_sha256':hashlib.sha256((state.get('reviewed_original_text')
                        or state.get('original_text') or '').encode()).hexdigest()}}
            row['contract_kind']='text' if plan.get('text_query_evidence') else 'visual'
            if plan.get('text_query_evidence'):
                # Derive text ownership from the host's persisted selection,
                # never from the plan's self-declared query_owner alone.
                owners=[]
                with studio.store.connect() as db:
                    jobs=db.execute("SELECT id,payload,checkpoint FROM jobs WHERE task_id=? AND kind='collect_sources'",
                        (state['id'],)).fetchall()
                for job in jobs:
                    try:
                        payload=json.loads(job['payload']);cp=json.loads(job['checkpoint'])
                        selected=cp.get('planning_preparation') or {}
                        expected={**context,'task_id':state['id'],'job_id':job['id'],'source_policy':policy,
                            'path':name,'sha256':row['bundle_sha256']}
                        if (payload.get('run_id')==state['run_id'] and isinstance(selected,dict)
                                and all(selected.get(k)==v for k,v in expected.items())):
                            owners.append({**context,'task_id':state['id'],'job_id':job['id']})
                    except (ValueError,TypeError,AttributeError):continue
                if len(owners)!=1:raise ValueError('Text diagnostic needs one matching owned preparation selection')
                context=owners[0];row['contract_job_id']=context['job_id']
            valid=value.get('query_policy')==query_policy() and reusable_query_contract(
                plan,policy,state.get('product',''),context,verify_files=False)
            if any(stamp(path.stat())!=saved for path,(_,saved) in checked.items()):
                raise ValueError('Media changed during diagnostic')
            row.update(status='reusable' if valid else 'unusable',media_sha_checked=True,
                       current_query_contract=bool(valid))
            if valid:
                row['fixture_guidance']=('This registered original query contract passes with its original media. '
                    'Relocating immutable evidence in an isolated test requires consistent nested path/hash '
                    'rebinding, while preserving proposal contents, independent verdicts and the original '
                    'job/checkpoint. Relocation alone is not a new production plan or approval. '
                    'This diagnostic does not prove selection/preflight, grant retry, or excuse a missing causal branch.')
        except (OSError,ValueError,TypeError,KeyError,AttributeError,RuntimeError,OverflowError) as exc:
            row['reason']=str(exc)[:300]
    return result


def visual_query_artifact_paths(studio,state,*,job_id=None,target=None):
    """Diagnostic JSON only, rooted in this job's host-registered input digest."""
    import re
    from itertools import islice
    data_dir=getattr(getattr(studio,'settings',None),'data_dir',None)
    if data_dir is None or not state.get('run_id'):return set()
    data_root=Path(data_dir).resolve()
    cache=data_root/'source-visual-queries'
    names={'proposal.json','review.json','receipt.json',
           'identity-correction-proposal.json','identity-correction-review.json'}
    recovery=re.compile(r'(?:empty|validation)-recovery-[a-f0-9]{64}')
    def safe(path,base=cache):
        try:
            if '..' in path.parts or not path.is_relative_to(base):return False
            for part in (path,*path.parents):
                if part==data_root:break
                if part.is_symlink() or getattr(part,'is_junction',lambda:False)():return False
            return path.resolve().is_relative_to(base.resolve())
        except (OSError,RuntimeError,ValueError):return False
    allowed=set();seen_inputs=set();remaining=4*1024*1024;parent_reads=0
    def read_json(path,base):
        nonlocal remaining
        if not safe(path,base) or not path.is_file() or remaining<=0:return None
        limit=min(256*1024,remaining)
        with path.open('rb') as stream:raw=stream.read(limit+1)
        remaining-=len(raw)
        if len(raw)>limit:return None
        value=json.loads(raw)
        return value if isinstance(value,dict) else None
    with studio.store.connect() as db:
        rows=db.execute("SELECT id,payload,checkpoint,error FROM jobs WHERE task_id=? ORDER BY updated DESC",(state['id'],)).fetchall()
    for row in rows:
        if job_id is not None and row['id']!=job_id:continue
        try:
            cp=json.loads(row['checkpoint']);payload=json.loads(row['payload'])
            binding=cp.get('visual_query_input')
            if (not isinstance(binding,dict) or binding.get('task_id')!=state['id']
                    or binding.get('job_id')!=row['id'] or not state.get('run_id')
                    or binding.get('run_id')!=payload.get('run_id') or binding.get('run_id')!=state['run_id']
                    or not isinstance(binding.get('input_sha256'),str)
                    or not re.fullmatch('[a-f0-9]{64}',binding['input_sha256'])):continue
            key=binding['input_sha256'];root=cache/key
            # Topic caches include owner/evidence in their directory digest.
            # Follow only this job's exact host failure paths or an explicitly
            # requested receipt with full evidence/owner binding; never glob.
            topic=data_root/'source-topic-query-receipts'
            owner={k:binding[k] for k in ('task_id','job_id','run_id')}
            trace=cp.get('failure_trace')
            messages=(str(row['error'] or ''),str(trace.get('message') or '') if isinstance(trace,dict) else '')
            registered=[]
            for message in messages:
                registered.extend(Path(p.strip()) for p in re.findall(
                    r'(?:proposal_path|review_path)=([^|\n]+)',message))
            registered={p if p.is_absolute() else Path.cwd()/p for p in registered}
            requested=Path(target) if target is not None else None
            if requested is not None and not requested.is_absolute():requested=Path.cwd()/requested
            topic_targets=[requested] if requested is not None else sorted(registered)
            checked_topic=set()
            from .source_visual_queries import digest
            for item in topic_targets:
                if (not item.is_relative_to(topic) or len(item.relative_to(topic).parts)!=2
                        or item.name not in {'proposal.json','review.json','receipt.json'}
                        or not re.fullmatch('[a-f0-9]{64}',item.parent.name)
                        or item.parent in checked_topic or not safe(item,topic)):
                    continue
                checked_topic.add(item.parent)
                try:
                    receipt=read_json(item.parent/'receipt.json',topic)
                    receipt_owned=bool(receipt and receipt.get('input_sha256')==key
                        and receipt.get('owner')==owner and isinstance(receipt.get('evidence'),dict)
                        and receipt['evidence'].get('owner')==owner
                        and digest(receipt['evidence'])==key
                        and item.parent.name==digest({'evidence':receipt['evidence'],'owner':owner}))
                    proposal=read_json(item.parent/'proposal.json',topic)
                    review=read_json(item.parent/'review.json',topic)
                    pair_owned=bool(proposal and review and proposal.get('input_sha256')==key
                        and review.get('input_sha256')==key and isinstance(proposal.get('proposal'),dict)
                        and review.get('proposal_sha256')==digest(proposal['proposal']))
                    # Failed pairs need the producer-selected path saved by the
                    # host; a copied input label alone grants no directory read.
                    registered_here=any(p.parent==item.parent and p.name in {'proposal.json','review.json'}
                        and safe(p,topic) for p in registered)
                    if receipt is not None:
                        pair_owned=bool(pair_owned and receipt_owned
                            and receipt.get('proposal')==proposal.get('proposal')
                            and receipt.get('review')==review)
                    if pair_owned and (registered_here or receipt_owned):
                        for name in ('proposal.json','review.json'):
                            path=item.parent/name
                            if target is None or path==requested:allowed.add(str(path.resolve()))
                    if receipt_owned and (target is None or item.name=='receipt.json'):
                        allowed.add(str((item.parent/'receipt.json').resolve()))
                except (OSError,RuntimeError,ValueError,TypeError,KeyError,AttributeError,OverflowError):
                    continue
            if key in seen_inputs or not safe(root):continue
            seen_inputs.add(key)
            candidate=Path(target) if target is not None else None
            if candidate is not None and not candidate.is_absolute():candidate=Path.cwd()/candidate
            if candidate is not None and candidate.is_relative_to(root):
                parts=candidate.relative_to(root).parts
                if (1<=len(parts)<=3 and parts[-1] in names
                        and all(recovery.fullmatch(p) for p in parts[:-1])
                        and safe(candidate) and candidate.is_file()):
                    allowed.add(str(candidate.resolve()))
                    continue
            directories=[root];level=[root]
            for _ in range(2):
                next_level=[]
                for directory in level:
                    try:
                        if not directory.is_dir():continue
                        next_level.extend(p for p in islice(directory.iterdir(),64)
                            if recovery.fullmatch(p.name) and safe(p) and p.is_dir())
                    except (OSError,RuntimeError,ValueError):continue
                level=next_level[:32];directories.extend(level)
            if candidate is not None:
                candidates=[]
                if candidate.is_relative_to(root):
                    parts=candidate.relative_to(root).parts
                    if (1<=len(parts)<=3 and parts[-1] in names
                            and all(recovery.fullmatch(p) for p in parts[:-1])):candidates=[candidate]
            else:candidates=[directory/name for directory in directories for name in sorted(names)]
            for item in candidates:
                if safe(item) and item.is_file():allowed.add(str(item.resolve()))
            # A nested insufficient pool writes its new diagnostic cache outside
            # the legacy input directory. Derive that exact path from an already
            # owned receipt; never follow arbitrary paths inside its JSON.
            from .source_visual_queries import digest,verify,query_pool_report
            for directory in directories[1:]:
                if parent_reads>=16:break
                try:
                    parent_path=directory/'receipt.json'
                    if not safe(parent_path,cache) or not parent_path.is_file():continue
                    parent_reads+=1
                    receipt=read_json(parent_path,cache)
                    if not receipt or receipt.get('input_sha256')!=key:continue
                    evidence=receipt['evidence']
                    if digest(evidence)!=key or not evidence.get('search_minimums'):continue
                    rows=verify(receipt,verify_files=False)  # Metadata authority only, not media approval.
                    pool=query_pool_report(rows,evidence['search_minimums'],receipt.get('search_identity'))
                    if pool['ready']:continue
                    feedback={'evidence':evidence,'previous_proposal':receipt['proposal'],
                        'independent_review':receipt['review'],'accepted_query_pool':pool,
                        'contract_defects':[{'query_id':q.get('id'),
                            'missing_observation_links':not bool(q.get('observation_ids')),
                            'missing_frame_links':not bool(q.get('frame_ids'))}
                            for q in receipt['proposal'].get('queries',[])]}
                    flat=data_root/'source-visual-pool-recoveries'/digest(feedback)
                    for name in ('proposal.json','review.json','receipt.json'):
                        item=flat/name
                        if candidate is not None and candidate!=item:continue
                        document=read_json(item,flat)
                        if (document and document.get('input_sha256')==key
                                and (name!='receipt.json' or digest(document.get('evidence'))==key)):
                            allowed.add(str(item.resolve()))
                except (OSError,RuntimeError,ValueError,TypeError,KeyError,AttributeError,OverflowError):continue
        except (OSError,RuntimeError,ValueError,TypeError,KeyError,AttributeError):continue
    return allowed


def inspect_artifact(studio,state,action,*,_full_text=False):
    requested=Path(str(action.get('path','')))
    path=requested.resolve()
    allowed={Path(p).resolve() for p in artifact_paths(state)|job_artifact_paths(studio,state)}
    root=studio.folder(state['id']).resolve()
    if path not in allowed and not path.is_relative_to(root):
        allowed.update(Path(p) for p in preparation_artifact_paths(studio,state,allowed))
        allowed.update(Path(p) for p in visual_query_artifact_paths(studio,state,target=requested))
        if path.suffix.lower() in {'.jpg','.jpeg','.png'}:
            from .video_agent_preparation_evidence import preparation_frames
            frames=[frame for group in preparation_frames(studio,state) if group['status']=='captured'
                    for frame in group['frames'] if Path(frame['path'])==path]
            if frames:
                return {'status':'completed',**frames[0],
                    'scope':'registered original frame; diagnostic evidence, not product approval'}
    if path not in allowed and not path.is_relative_to(root):raise ValueError('해당 영상의 증거 파일만 읽을 수 있습니다.')
    if path.is_file() and path in allowed and path.suffix.lower() in {'.mp4','.mov','.wav','.mp3','.png','.jpg','.jpeg'}:
        with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        return {'status':'completed','path':str(path),'sha256':sha,'bytes':path.stat().st_size}
    if not path.is_file() or path.suffix.lower() not in {'.json','.txt','.log','.md','.srt','.vtt'}:
        raise ValueError('텍스트 증거 파일을 지정하세요.')
    if path.stat().st_size>4*1024*1024:raise ValueError('증거 파일이 너무 큽니다. 구체적인 영수증을 선택하세요.')
    with path.open('rb') as stream:raw=stream.read(4*1024*1024+1)
    if len(raw)>4*1024*1024:raise ValueError('증거 파일이 너무 큽니다. 구체적인 영수증을 선택하세요.')
    start=max(0,int(action.get('offset',0)));limit=min(24000,max(1,int(action.get('limit',12000))))
    text=raw.decode('utf-8',errors='replace')
    if _full_text:start=0;limit=len(text)
    return {'status':'completed','path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'total_characters':len(text),
            'content':text[start:start+limit],'next_offset':start+limit if len(text)>start+limit else None}

def completion(state):
    from .daily_quality import verified_quality_export
    edit=next((e for e in state.get('edits',[]) if e.get('id')==state.get('edit_id')),None)
    if not edit or state.get('daily_quality',{}).get('status')!='passed':return None
    if not (edit.get('script_id') and edit.get('script_id')==state.get('script_id')==state.get('approved_script_id')
            and edit.get('voice_id') and edit.get('voice_id')==state.get('voice_id')==state.get('approved_voice_id')):return None
    voice=next((v for v in state.get('voices',[]) if v.get('id')==state.get('voice_id')),None)
    if not voice or voice.get('script_id')!=edit['script_id']:return None
    if not verified_quality_export(state,edit):return None
    path=Path(edit.get('export_path') or '')
    if not path.is_file():return None
    return {'edit_id':edit['id'],'path':str(path),'completion_verified':True,
            'render_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'input_fingerprint':semantic_fingerprint(state)}

def parser_failure_evidence(state, jobs):
    """Keep the causal saved search receipt visible ahead of old query history."""
    from .video_agent_actions import parser_repair_context
    contexts=[observation for job in jobs if parser_repair_context(state,job)
              for observation in job['checkpoint']['parser_repair_context']['observations']]
    result=[]
    fields=('provider','query','status','parser_revision','run_id','stage','error','error_detail',
            'reason','execution','requests','visible_search_controls','visible_search_inputs')
    for row in reversed((state.get('source_acquisition') or {}).get('queries',[])):
        if not isinstance(row,dict) or row.get('run_id')!=state.get('run_id'):continue
        if row.get('status')!='page_unresolved':continue
        if not any(row.get('provider')==context.get('provider')
                   and row.get('query')==(context.get('readiness') or {}).get('query')
                   and row.get('parser_revision')==(context.get('readiness') or {}).get('parser_revision')
                   for context in contexts):continue
        result.append({key:row[key] for key in fields if key in row})
        if len(result)>=8:break
    return result


def source_lane_observation(studio,db,task_id):
    """Saved queue plus live owned-thread facts, never a claim/retry permit."""
    import math
    def timestamp(value):
        return value if type(value) in (int,float) and math.isfinite(value) and value>=0 else None
    workers=[thread for thread in getattr(studio,'_threads',())
             if thread.name=='studio-sources' and thread.is_alive()]
    rows=[dict(row) for row in db.execute("""SELECT id,task_id,kind,updated,
        CASE WHEN json_valid(checkpoint) THEN CASE
          WHEN json_type(checkpoint,'$._claim_started_at') IN ('integer','real')
          THEN json_extract(checkpoint,'$._claim_started_at') END END AS claim_started_at
        FROM jobs WHERE status='running' AND kind IN ('collect_sources','refresh_sources')
        ORDER BY updated DESC LIMIT 8""")]
    count=db.execute("SELECT count(*) FROM jobs WHERE status='running' AND kind IN ('collect_sources','refresh_sources')").fetchone()[0]
    queued=[dict(row) for row in db.execute("""SELECT id,kind,
        CASE WHEN json_valid(checkpoint) THEN CASE
          WHEN json_type(checkpoint,'$.not_before') IN ('integer','real')
          THEN json_extract(checkpoint,'$.not_before') END END AS not_before
        FROM jobs WHERE task_id=? AND status='queued' AND kind IN ('collect_sources','refresh_sources')
        ORDER BY created LIMIT 12""",(task_id,))]
    for row in rows:
        row['claim_started_at']=timestamp(row['claim_started_at']);row['updated']=timestamp(row['updated'])
    for row in queued:row['not_before']=timestamp(row['not_before'])
    # A worker may be transitioning between persisted states. Report facts;
    # absence of an active row cannot establish a fault or a start guarantee.
    return {'observed_at':time.time(),'live_source_worker_count':len(workers),
        'running_source_job_count':count,'running_source_jobs':rows,
        'running_source_jobs_truncated':count>len(rows),'this_task_queued_source_jobs':queued,
        'scope':'Serial source worker scheduling observation only. A running source job can occupy the lane while another task is queued. No access, failure, retry or start-time verdict.'}


def snapshot(studio,task_id):
    state=studio.store.get(task_id)
    fields=('id','title','status','error','run_id','automation','source_goal','source_acquisition',
            'source_search','daily_quality','production_blockers','script_id','voice_id','edit_id')
    result={k:state.get(k) for k in fields}
    result['fingerprint']=semantic_fingerprint(state)
    result['artifacts']=sorted(artifact_paths(state)|job_artifact_paths(studio,state)|visual_query_artifact_paths(studio,state))[-100:]
    result['inventory']={k:len(state.get(k,[])) for k in ('sources','scripts','voices','edits')}
    result['superseded_repairs']=[r for r in getattr(studio,'superseded_code_receipts',[])
        if (r.get('binding') or {}).get('task_id')==task_id]
    proofs=[r for r in (getattr(studio,'loaded_code_receipts',{}) or {}).values()
        if (r.get('binding') or {}).get('task_id')==task_id]
    loaded=max(proofs,key=lambda r:r.get('applied_at',0)) if proofs else getattr(studio,'loaded_code_receipt',None)
    if isinstance(loaded,dict) and (loaded.get('binding') or {}).get('task_id')==task_id:
        result['loaded_repair']={k:loaded.get(k) for k in ('repair_id','binding','files','process_id','loaded_at')}
    result['code_map']={'quality_routing':'hotpost/daily_quality_routing.py','preparation':'hotpost/studio_runtime/generation.py',
        'source_review':'hotpost/studio_sources.py','overlay_review':'hotpost/source_overlay_review.py',
        'source_admission':'hotpost/editing_adapter.py','workflow':'hotpost/studio_workflow.py',
        'editing':'hotpost/studio_runtime/editing.py','failure_dispatch':'hotpost/studio_runtime/lifecycle.py',
        'tool_contracts':'hotpost/video_agent_actions.py','repair_contracts':'hotpost/video_agent_repairs.py'}
    result['assets']={k:[{a:r.get(a) for a in ('id','path','sha256','script_id','voice_id','plan_path','export_path') if r.get(a)} for r in state.get(k,[])][-30:] for k in ('sources','scripts','voices','edits')}
    with studio.store.connect() as db:
        result['source_lane_observation']=source_lane_observation(studio,db,task_id)
        owner=db.execute('SELECT record FROM video_agents WHERE task_id=?',(task_id,)).fetchone()
        reserved=(json.loads(owner['record']).get('recovery_job_id') if owner else None)
        result['recovery_job_id']=reserved
        result['jobs']=[dict(r) for r in db.execute(
            'SELECT id,task_id,kind,status,error,checkpoint,payload FROM jobs WHERE task_id=? ORDER BY created DESC LIMIT 12',(task_id,))]
        if reserved and not any(row['id']==reserved for row in result['jobs']):
            row=db.execute('SELECT id,task_id,kind,status,error,checkpoint,payload FROM jobs WHERE task_id=? AND id=?',(task_id,reserved)).fetchone()
            if row:result['jobs'].insert(0,dict(row))
        from .video_agent_planning_claim import internal_wait_parking_proof
        result['internal_wait_repair_parking']=[proof for row in db.execute(
            "SELECT * FROM jobs WHERE task_id=? AND status='paused' ORDER BY updated DESC LIMIT 12",(task_id,))
            if (proof:=internal_wait_parking_proof(db,state,row))]
    for job in result['jobs']:
        job['checkpoint']=json.loads(job['checkpoint'])
        job['payload']=json.loads(job['payload'])
    result['parser_failure_evidence']=parser_failure_evidence(state,result['jobs'])
    from .video_agent_page_evidence import current_parser_page
    result['current_parser_page_observation']=current_parser_page(studio,state,result['jobs'])
    result['original_preparation_query_diagnostics']=preparation_query_diagnostics(studio,state)
    from .video_agent_preparation_evidence import preparation_frames
    result['preparation_frame_evidence']=preparation_frames(studio,state,
        diagnostics=result['original_preparation_query_diagnostics'])
    supervisor=getattr(studio,'supervisor',None)
    if supervisor:result['supervision']=supervisor.summary(task_id)
    # An oversized source manifest is inspected explicitly, never copied wholesale.
    for key in ('source_search','source_acquisition','daily_quality'):
        raw=json.dumps(result[key],ensure_ascii=False,default=str)
        if len(raw)>16000:result[key]={'summary':raw[:16000],'truncated':True}
    return result
