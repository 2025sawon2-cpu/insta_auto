"""Durable evidence navigation; bounded context must not erase recoverable memory."""
import json

READ_TOOLS = {'inspect_code', 'inspect_artifact', 'inspect_repair', 'recall'}
REPAIR_TOOLS = {'propose_patch','test_patch','review_patch','park_for_repair','apply_patch','retry_repaired','recover_preparation','continue_repaired'}
REPAIR_EVIDENCE_TOOLS = {'inspect_code','inspect_artifact','inspect_repair','recall'}


def model_context_id(result, binding):
    """Use host CLI receipts, never the model's action, to scope delivered code."""
    import uuid
    from .writing.owner_session import value_digest
    if not isinstance(result,dict) or 'value' not in result:return None
    inference=result.get('inference')
    calls=inference.get('calls') if isinstance(inference,dict) else None
    if not isinstance(calls,list):return None
    ids=set();digest=value_digest(result['value'])
    for call in calls:
        if not isinstance(call,dict):continue
        context=call.get('owner_conversation')
        if (call.get('status')!='completed' or call.get('exit_code')!=0
                or call.get('decoded_value_sha256')!=digest or not isinstance(context,dict)
                or context.get('binding')!=binding):continue
        thread=context.get('thread_id')
        try:
            if isinstance(thread,str) and str(uuid.UUID(thread))==thread:ids.add(thread)
        except ValueError:pass
    return next(iter(ids)) if len(ids)==1 else None


def novel_code_contract(store, task_id, epoch, result, context_id=None):
    """An exhausted diagnosis budget must not hide previously unread source.

    Compare canonical paths and delivered ranges of the exact source SHA against
    durable host receipts. New wording, aliases and overlapping page sizes cannot
    purchase another read. This is information progress, never repair progress.
    """
    from pathlib import PurePosixPath
    content=result.get('content');sha=result.get('base_sha256')
    start=result.get('offset');total=result.get('total_characters')
    if (not isinstance(content,str) or not content or not isinstance(sha,str)
            or type(start) is not int or type(total) is not int):return False
    end=start+len(content)
    if start<0 or end>total or (len(content)<1024 and end!=total):return False
    path=str(PurePosixPath(result['path'].replace('\\','/'))).casefold()
    ranges=[]
    with store.connect() as db:
        rows=db.execute("""SELECT
            coalesce(json_extract(observation,'$.result.repo'),json_extract(observation,'$.action.repo')) repo,
            coalesce(json_extract(observation,'$.result.path'),json_extract(observation,'$.action.path')) path,
            coalesce(json_extract(observation,'$.result.offset'),0) start,
            length(json_extract(observation,'$.result.content')) size
            FROM video_agent_steps WHERE task_id=? AND epoch=?
            AND json_extract(observation,'$.action.kind')='inspect_code'
            AND json_extract(observation,'$.result.status')='completed'
            AND json_extract(observation,'$.result.base_sha256')=?
            AND (? IS NULL OR json_extract(observation,'$.model_context_id')=?)""",
            (task_id,epoch,sha,context_id,context_id)).fetchall()
    for row in rows:
        if row['repo']!=result.get('repo') or not isinstance(row['path'],str):continue
        if str(PurePosixPath(row['path'].replace('\\','/'))).casefold()!=path:continue
        if type(row['start']) is not int or type(row['size']) is not int:continue
        lo=max(start,row['start']);hi=min(end,row['start']+row['size'])
        if hi>lo:ranges.append((lo,hi))
    cursor=start;unread=0
    for lo,hi in sorted(ranges):
        unread+=max(0,lo-cursor);cursor=max(cursor,hi)
    unread+=max(0,end-cursor)
    return unread>=min(1024,len(content))


def repair_stage_progress(observations):
    """A new draft/test cycle is activity, not a new recovery milestone."""
    tracks={};repairs={};active=None
    phases={'propose_patch':1,'test_patch':2,'review_patch':3,'apply_patch':4,
            'retry_repaired':5,'continue_repaired':5}
    for obs in observations:
        action=obs.get('action') or {};result=obs.get('result') or {}
        if not isinstance(action,dict) or not isinstance(result,dict):continue
        kind=action.get('kind');status=result.get('status') or obs.get('status')
        if not isinstance(kind,str):continue
        repair_id=result.get('repair_id') or action.get('repair_id')
        if not isinstance(repair_id,str):repair_id=None
        fingerprint=obs.get('fingerprint')
        epoch=action.get('_agent_epoch')
        if kind=='propose_patch' and status=='completed' and repair_id:
            patch=action.get('patch') if isinstance(action.get('patch'),dict) else {}
            binding=patch.get('binding') if isinstance(patch.get('binding'),dict) else {}
            job_id=binding.get('job_id') or action.get('job_id')
            if isinstance(job_id,str) and job_id and isinstance(fingerprint,str) and fingerprint and type(epoch) is int:
                active=(job_id,fingerprint,epoch);repairs[repair_id]=active
                tracks.setdefault(active,{'job_id':job_id,'input_fingerprint':fingerprint,
                    'agent_epoch':epoch,'phase':0,'stagnant_decisions':0,'repair_ids':[]})
                if repair_id not in tracks[active]['repair_ids']:tracks[active]['repair_ids'].append(repair_id)
        elif repair_id in repairs:
            active=repairs[repair_id]
        if active is None or fingerprint!=active[1] or epoch!=active[2]:continue
        # A host-confirmed dependency hold is not failed repair work. A
        # planner's unverified wait claim alone must not evade this counter.
        if status=='waiting' and (result.get('retry_same_decision') or obs.get('dependency_wait')):continue
        track=tracks[active];track['stagnant_decisions']+=1
        passed=(kind=='propose_patch' and status=='completed' and result.get('code_changed') is not False
                or kind=='test_patch' and status=='tests_passed'
                or kind=='review_patch' and status=='completed' and bool(result.get('review_id'))
                or kind=='apply_patch' and status in {'applied','loaded'}
                or kind in {'retry_repaired','continue_repaired'} and status=='queued')
        phase=phases.get(kind,0) if passed else 0
        if phase>track['phase']:
            track.update(phase=phase,stagnant_decisions=0)
    return list(tracks.values())


def working_evidence(rows, observations):
    """Keep complete recent read ranges; an excerpt must not erase its tail."""
    result=[];seen=set();versions={};budget=144000
    for row,obs in reversed(list(zip(rows,observations))):
        action=obs.get('action');value=obs.get('result')
        if not isinstance(action,dict) or not isinstance(value,dict):continue
        if action.get('kind') not in ('inspect_code','inspect_artifact','inspect_repair','recall'):continue
        content=value.get('content')
        if not isinstance(content,str):continue
        identity=json.dumps([action.get(k) for k in ('kind','repo','path','decision_id','repair_id','incident_path')],sort_keys=True)
        sha=value.get('sha256') or value.get('base_sha256')
        if identity not in versions:versions[identity]=sha
        if versions[identity]!=sha:continue
        if not content:continue
        key=json.dumps([identity,value.get('offset',action.get('offset',0)),action.get('line'),len(content)],sort_keys=True)
        if key in seen:continue
        seen.add(key)
        if len(content)>budget:continue
        result.append({'decision_id':row['decision_id'],'historical_evidence':True,
            'action':{k:action[k] for k in ('kind','repo','path','decision_id','repair_id','incident_path','offset','line','limit') if k in action},
            'result':{k:value[k] for k in ('content','offset','next_offset','base_sha256','sha256','total_characters') if k in value}})
        budget-=len(content)
        if len(result)>=10 or budget<=0:break
    return list(reversed(result))


def staged_packet(pipeline,evidence,*,target_ids=None):
    """Carry the current draft, not an older live version of its changed files."""
    if not callable(getattr(pipeline,'repair_material',None)):return []
    ids=list(dict.fromkeys(row.get('repair_id') for row in reversed(evidence.get('memory_index',[]))
                          if row.get('kind')=='propose_patch' and isinstance(row.get('repair_id'),str)
                          and row['repair_id']))
    jobs={row['id'] for row in evidence.get('jobs',[])}
    if target_ids is not None:jobs.intersection_update(target_ids)
    for repair_id in ids[:8]:
        try:material=pipeline.repair_material(repair_id,evidence['id'])
        except (ValueError,KeyError,OSError):continue
        if material.get('status') not in {'staged','tests_passed','tests_failed','review_rejected','reviewed','apply_failed'}:continue
        binding=material['binding']
        if binding.get('agent_epoch')!=evidence.get('owner_epoch') or binding.get('job_id') not in jobs:continue
        result=[];budget=180000
        for file in material['files']:
            offset=None
            for prior in reversed(evidence.get('memory_index',[])):
                if (prior.get('kind')=='inspect_repair' and prior.get('repo')==file['repo']
                        and prior.get('path')==file['path'] and prior.get('staged_sha256')==file['sha256']):
                    if type(prior.get('offset')) is int and prior['offset']>=0:offset=prior['offset']
                    break
            if budget<=0:break
            try:
                row=pipeline.inspect_staged_file(repair_id,evidence['id'],file['repo'],file['path'],
                                                offset=0,limit=min(48000,budget))
                # If the remaining packet cannot hold this file, sending its
                # header can hide every changed function. Prefer the verified
                # last read, otherwise the first changed hunk with context.
                capacity=min(96000,budget)
                if row['total_characters']>capacity:
                    hint=file.get('change_offset',0)
                    if type(hint) is not int or hint<0:hint=0
                    start=offset if offset is not None else max(0,hint-min(4000,capacity//4))
                    start=min(start,max(0,row['total_characters']-capacity))
                    row=pipeline.inspect_staged_file(repair_id,evidence['id'],file['repo'],file['path'],
                                                    offset=start,limit=min(48000,budget))
                if row.get('next_offset') is not None and budget>len(row['content']):
                    tail=pipeline.inspect_staged_file(repair_id,evidence['id'],file['repo'],file['path'],
                        offset=row['next_offset'],limit=min(48000,budget-len(row['content'])))
                    if tail['sha256']!=row['sha256']:continue
                    row={**row,'content':row['content']+tail['content'],'next_offset':tail['next_offset']}
            except (ValueError,KeyError,OSError):continue
            if not row.get('content'):continue
            result.append({**row,'historical_evidence':True});budget-=len(row['content'])
            if len(result)>=8:break
        return result
    return []


def repair_packet(studio,evidence,*,target_ids=None):
    """Supply code directly when the read-only diagnosis budget is exhausted."""
    pipeline=getattr(studio,'video_repair_pipeline',None)
    if not pipeline:return []
    packet=staged_packet(pipeline,evidence,target_ids=target_ids)
    targets=[];locations={};read_locations={}
    if not packet and evidence.get('quality_recovery'):
        targets.append(('main','hotpost/daily_quality_routing.py'))
    if not packet and evidence.get('source_recovery'):
        targets.extend([('main','hotpost/studio_sources.py'),('main','hotpost/studio_automation.py')])
    for job in ([] if packet else evidence.get('jobs',[])):
        if target_ids is not None and job['id'] not in target_ids:continue
        for frame in (job.get('checkpoint',{}).get('failure_trace') or {}).get('frames',[]):
            from pathlib import Path
            for repo,root in pipeline.roots.items():
                try:
                    target=(repo,Path(frame['path']).resolve().relative_to(root.resolve()).as_posix())
                    targets.append(target);locations[target]=max(1,int(frame.get('line',1)))
                except (ValueError,KeyError):pass
    for row in reversed(evidence.get('memory_index',[])):
        if row.get('kind')=='inspect_code' and row.get('path') and row.get('repo'):
            target=(row['repo'],row['path']);targets.append(target)
            if target not in read_locations and row.get('sha256'):
                read_locations[target]=row
    targets.extend(('main',p) for p in evidence.get('code_map',{}).values())
    seen={(row['repo'],row['path']) for row in packet}
    budget=180000-sum(len(row['content']) for row in packet)
    for repo,path in targets:
        if len(packet)>=8:break
        if (repo,path) in seen:continue
        seen.add((repo,path))
        try:row=pipeline.inspect_code(repo,path)
        except (ValueError,KeyError,OSError):continue
        text=row.get('content','')
        if budget<=0:break
        start=0
        if (repo,path) in locations:
            start=sum(len(line) for line in text.splitlines(keepends=True)[:max(0,locations[(repo,path)]-80)])
        elif (repo,path) in read_locations:
            previous=read_locations[(repo,path)]
            if previous['sha256']==row.get('base_sha256'):
                if type(previous.get('line')) is int and previous['line']>=1:
                    start=sum(len(line) for line in text.splitlines(keepends=True)[:max(0,previous['line']-1)])
                elif type(previous.get('offset')) is int and previous['offset']>=0:
                    start=previous['offset']
                if start>=len(text):start=0
        count=min(48000,budget);excerpt=text[start:start+count]
        packet.append({'repo':repo,'path':path,**row,'content':excerpt,'offset':start,'total_characters':len(text),
            'next_offset':start+count if start+count<len(text) else None});budget-=len(excerpt)
        if len(packet)>=8:break
    return packet


REPAIR_EXECUTION_INSTRUCTION = '''The read-only diagnosis budget is exhausted.
You are now the repair executor. The host has attached current source files with exact
base hashes in repair_packet, plus durable evidence and failure receipts. Rows marked
source=staged_repair contain the current draft for prior_repair_id replacements; they
are not applied code or approval. Other rows are live code. Restaging identical file
contents is not code progress and does not renew the diagnosis budget. Select only
one of the supplied allowed_actions. Do not repeat an inspection or wait.
Produce a concrete minimal patch plus a regression test for the evidenced failure, or
continue an existing patch through test/review/apply. For the exact audited legacy
preparation incident use recover_preparation. All mutations remain independently gated.
If essential code/evidence is absent, inspect_code, inspect_artifact or recall may fetch up to six distinct
missing references. Include needed_for_repair explaining the exact missing dependency.
Do not reread the same request. The evidence budget is shown in repair_evidence_used.
After those six references, inspect_code with an exact repo/path remains available
for an essential unread source contract (include needed_for_repair). No query searches,
recall or artifact reads receive this exception. The host returns 4096–48000 characters
and requires at least 1024 previously unread characters of the exact file SHA (or its
short final tail). Aliases, overlapping ranges and changed wording do not renew access.
Use line/offset to read the missing contract, then implement the known missing recovery
connection. Do not add unrelated negative tests merely because old references are spent.
Delivery is scoped to the current host-attested owner conversation: a read in an old
ephemeral/lost conversation may be restored once to this conversation. Its historical
existence alone does not prove you received it here. New source information never resets
the repair-stage watchdog or grants approval.
Do not modify protected quality, authentication, ownership or approval controls.
'''


def history(store, task_id):
    with store.connect() as db:
        rows = db.execute('SELECT decision_id,observation FROM video_agent_steps WHERE task_id=? ORDER BY id', (task_id,)).fetchall()
    observations = [json.loads(r['observation']) for r in rows]
    index = []
    for row, obs in zip(rows, observations):
        action = obs.get('action') if isinstance(obs.get('action'),dict) else {}
        result = obs.get('result') if isinstance(obs.get('result'),dict) else {}
        patch=action.get('patch') if isinstance(action.get('patch'),dict) else {}
        binding=patch.get('binding') if isinstance(patch.get('binding'),dict) else {}
        is_repair=isinstance(action.get('kind'),str) and action['kind'] in REPAIR_TOOLS
        index.append({'decision_id':row['decision_id'], 'kind':action.get('kind'),
            'path':action.get('path'), 'query':action.get('query'), 'repo':action.get('repo'),
            'offset':result.get('offset',action.get('offset')), 'line':action.get('line'), 'limit':action.get('limit'),
            'incident_path':action.get('incident_path'),
            'status':result.get('status') or obs.get('status'),
            'reason':str(result.get('error') or result.get('reason') or obs.get('error') or '')[:600],
            'sha256':result.get('base_sha256') or result.get('sha256'),
            'staged_sha256':result.get('sha256') if result.get('source')=='staged_repair' else None,
            'repair_id':result.get('repair_id') or action.get('repair_id'),
            'job_id':action.get('job_id') or binding.get('job_id'),
            'input_fingerprint':(obs.get('fingerprint') or binding.get('input_fingerprint')) if is_repair else None,
            'hypothesis':str(action.get('hypothesis') or '')[:500] if is_repair else '',
            'historical_evidence':True})
    recent = []
    for position,obs in enumerate(observations[-12:]):
        item = dict(obs)
        if isinstance(item.get('result'), dict):
            item['result'] = dict(item['result'])
            if isinstance(item['result'].get('diagnostics'),dict):
                from .video_agent_context import compact_incident
                diagnostics=dict(item['result']['diagnostics'])
                if 'incident' in diagnostics:diagnostics['incident']=compact_incident(diagnostics['incident'],evidence_excerpt=True)
                item['result']['diagnostics']=diagnostics
            # The next decision must receive the complete last tool response.
            # Trimming it while retaining next_offset silently skips unread code.
            if position<len(observations[-12:])-1 and len(item['result'].get('content','')) > 5000:
                item['result']['content'] = item['result']['content'][:5000]
                item['result']['context_excerpt_only'] = True
        recent.append(item)
    # Keep the latest entry for each actual reference/method, not only recent turns.
    unique = {}
    for item in index:
        key = json.dumps([item['kind'],item['repo'],item['path'],item['query'],item['repair_id'],item['job_id'],item['incident_path']],sort_keys=True)
        # Reassignment alone preserves the FIRST insertion position in dict.
        # Move refreshed references to the end before applying the recency cap.
        unique.pop(key,None)
        unique[key] = item
    return {'previous_steps':recent, 'memory_index':list(unique.values())[-160:],
            'working_evidence':working_evidence(rows,observations),
            'repair_stage_progress':repair_stage_progress(observations),
            'total_decisions':len(observations)}


def recall(store, task_id, action):
    if not action.get('decision_id'):
        offset=max(0,int(action.get('offset',0)));limit=min(40,max(1,int(action.get('limit',20))))
        query=str(action.get('query',''))[:200]
        with store.connect() as db:
            rows=db.execute('SELECT decision_id,observation FROM video_agent_steps WHERE task_id=? AND instr(observation,?)>0 ORDER BY id LIMIT ? OFFSET ?',
                            (task_id,query,limit+1,offset)).fetchall()
        entries=[]
        for row in rows[:limit]:
            obs=json.loads(row['observation']);act=obs.get('action');result=obs.get('result') or {}
            entries.append({'decision_id':row['decision_id'],'action':act,
                'status':result.get('status') or obs.get('status'),
                'reason':str(result.get('error') or result.get('reason') or '')[:600]})
        return {'status':'completed','entries':entries,'next_offset':offset+limit if len(rows)>limit else None}
    with store.connect() as db:
        row = db.execute('SELECT observation FROM video_agent_steps WHERE task_id=? AND decision_id=?',
                         (task_id, action.get('decision_id'))).fetchone()
    if row is None:
        raise ValueError('Choose a decision_id from this video memory_index.')
    text = row[0]
    offset = max(0,int(action.get('offset',0)))
    limit = min(24000,max(1,int(action.get('limit',12000))))
    return {'status':'completed','content':text[offset:offset+limit],
            'next_offset':offset+limit if len(text)>offset+limit else None,
            'historical_evidence':True}


RECOVERY_INSTRUCTION = '''You are an independent recovery engineer taking responsibility for this video.
The ordinary planner has stalled. Reconstruct the cause from the durable memory_index,
exact job failure_trace and previous outcomes. Successful reads can ALWAYS be repeated;
recall(decision_id,offset?,limit?) retrieves earlier observations. Without decision_id,
recall(query?,offset?,limit?) searches/pages ALL historical decisions, including repeated
observations of one file and those outside memory_index. Do not invent file paths.
Use inspect_code(repo,query) then inspect_code(repo,path,offset?,limit?) for exact code.
Your objective is a verified repair and resumed production, not more unbounded diagnosis.
If the evidence identifies a concrete repair, propose_patch with a regression test now.
For a failed prepare that ran the obsolete manual selection path, recover_preparation(job_id)
is available only when the host proves the current protocol and exact failure contract.
Never approve media yourself or relax quality/authentication guards. A failed METHOD is
abandoned, never ownership of the video. wait requires a named service/access dependency.
Return the same single-action JSON contract; the host executes and verifies your choice.
'''
