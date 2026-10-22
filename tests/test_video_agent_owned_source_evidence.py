import hashlib
import json
import pytest
from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.video_agent_context import inspect_artifact,job_artifact_paths


@pytest.mark.parametrize('damage',[None,'context_task','context_run','job_run','attempt_task','receipt_run','receipt_sha','worker_sha','manifest_sha','query','revision','time','nan','huge_request','huge_observation','foreign_worker','malformed'])
def test_readiness_successor_captures_exact_prior_causal_evidence(tmp_path,damage):
    from hotpost.video_agent_context import incident_artifacts,causal_readiness_artifacts
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('cause','Cause',{'active':True},prepare=False)
    state=studio.store.change(state['id'],lambda s,db:s.update(run_id='current-run'))
    root=studio.settings.source_dir/'cause-123';root.mkdir(parents=True)
    manifest=root/'manifest.json';manifest.write_text('{}')
    worker=root/'checkpoint.json';worker.write_text('{"failure":"original"}')
    receipt=root/'interrupted-execution-receipt.json'
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    readiness={'query':'actual query','parser_revision':'revision','at':100.2}
    context={'task_id':state['id'],'run_id':state['run_id'],'observations':[{'provider':'tiktok','readiness':readiness}]}
    context['observations'].insert(0,{'provider':'tiktok','readiness':{**readiness,'at':10**400}})
    with studio.store.transaction() as db:
        old=studio.store.enqueue(db,state['id'],'collect_sources',{'run_id':state['run_id']},'old')
        child=studio.store.enqueue(db,state['id'],'collect_sources',{'run_id':state['run_id']},'child')
        binding={'task_id':state['id'],'studio_job_id':old,'run_id':state['run_id'],'shortcode':state['shortcode']}
        search={'provider':'tiktok','query':'actual query','parser_revision':'revision','requests':[{'at':100.0}]}
        value={**binding,'manifest_path':str(manifest),'manifest_sha256':sha(manifest),
               'worker_checkpoints':[{'path':str(worker),'sha256':sha(worker)}],'searches':[search]}
        if damage=='receipt_run':value['run_id']='other'
        if damage=='worker_sha':value['worker_checkpoints'][0]['sha256']='0'*64
        if damage=='manifest_sha':value['manifest_sha256']='0'*64
        if damage=='foreign_worker':
            other=tmp_path/'private.json';other.write_text('{}')
            value['worker_checkpoints']=[{'path':str(other),'sha256':sha(other)}]
        if damage=='query':search['query']='other'
        if damage=='revision':search['parser_revision']='other'
        if damage=='time':search['requests'][0]['at']=90
        if damage=='nan':search['requests'][0]['at']=float('nan')
        if damage=='huge_request':search['requests'][0]['at']=10**400
        if damage=='huge_observation':readiness['at']=10**400
        search['requests'].insert(0,{'at':10**400})
        receipt.write_text(json.dumps(value))
        attempt={**binding,'manifest_path':str(manifest),'receipt_path':str(receipt),'receipt_sha256':sha(receipt),
                 'workers':[{'path':str(worker)}]}
        if damage=='attempt_task':attempt['task_id']='other'
        if damage=='receipt_sha':attempt['receipt_sha256']='0'*64
        oldcp={'source_attempts':[attempt]}
        if damage=='malformed':oldcp=[]
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(oldcp),old))
        if damage=='job_run':db.execute('update jobs set payload=? where id=?',(json.dumps({'run_id':'other'}),old))
        if damage=='context_task':context['task_id']='other'
        if damage=='context_run':context['run_id']='other'
        cp={'parser_repair_context':context}
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),child))
        # More recent malformed records cannot hide the earlier valid cause.
        for index,malformed in enumerate([None,[],{'source_attempts':[None]}]):
            bad=studio.store.enqueue(db,state['id'],'collect_sources',{'run_id':state['run_id']},'bad-'+str(index))
            db.execute('update jobs set checkpoint=? where id=?',(json.dumps(malformed),bad))
    before=studio.store.get(state['id'])
    job={'id':child,'checkpoint':cp}
    paths=causal_readiness_artifacts(studio,state,job)
    if damage:assert paths==[]
    else:
        assert paths==[str(p.resolve()) for p in (receipt,worker,manifest)]
        captured=incident_artifacts(studio,state,job)
        assert [p['path'] for p in captured]==paths
        for p in captured:
            assert hashlib.sha256(p['content'].encode()).hexdigest()==p['sha256']
    assert studio.store.get(state['id'])==before
    with studio.store.connect() as db:
        assert {r['status'] for r in db.execute('select status from jobs where task_id=?',(state['id'],))}=={'queued'}


@pytest.mark.parametrize('damage',[None,'task','job','run','payload_run','digest','foreign_cache','arbitrary_file','unbound_directory','too_deep','outside'])
def test_registered_visual_query_input_owns_only_fixed_nested_diagnostics(tmp_path,damage):
    from hotpost.video_agent_context import incident_artifacts
    import os
    from pathlib import Path
    if os.name=='nt':tmp_path=Path('\\\\?\\'+str(tmp_path))
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('visual','Visual',{'active':True},prepare=False)
    state=studio.store.change(state['id'],lambda s,db:s.update(run_id='run-visual'))
    digest='a'*64
    target=tmp_path/'source-visual-queries'/digest/('empty-recovery-'+'b'*64)/'identity-correction-proposal.json'
    if damage=='foreign_cache':target=tmp_path/'source-visual-queries'/('c'*64)/'proposal.json'
    if damage=='arbitrary_file':target=target.with_name('private.json')
    if damage=='unbound_directory':target=target.parent/'unregistered'/'proposal.json'
    if damage=='too_deep':target=target.parent/('validation-recovery-'+'c'*64)/('validation-recovery-'+'d'*64)/'proposal.json'
    if damage=='outside':target=tmp_path/'private.json'
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'{"failed_proposal":"preserved","private_path":"do-not-follow"}')
    with studio.store.transaction() as db:
        jid=studio.store.enqueue(db,state['id'],'collect_sources',{'run_id':state['run_id']},'visual-input')
        binding={'task_id':state['id'],'job_id':jid,'run_id':state['run_id'],'input_sha256':digest}
        if damage in {'task','job','run'}:binding[damage+'_id']='foreign'
        if damage=='digest':binding['input_sha256']='../private'
        cp={'visual_query_input':binding}
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),jid))
        if damage=='payload_run':db.execute('update jobs set payload=? where id=?',(json.dumps({'run_id':'foreign'}),jid))
    before=studio.store.get(state['id'])
    if damage:
        with pytest.raises(ValueError,match='증거 파일'):inspect_artifact(studio,state,{'path':str(target)})
        assert str(target.resolve()) not in {x['path'] for x in incident_artifacts(studio,state,{'id':jid,'checkpoint':cp})}
    else:
        proof=inspect_artifact(studio,state,{'path':str(target)})
        assert proof['sha256']==hashlib.sha256(target.read_bytes()).hexdigest()
        artifacts=incident_artifacts(studio,state,{'id':jid,'checkpoint':cp},max_files=24)
        assert next(x for x in artifacts if x['path']==str(target.resolve()))['content']==proof['content']
    assert studio.store.get(state['id'])==before


def test_visual_query_diagnostic_link_cannot_escape_registered_cache(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('visual','Visual',{'active':True},prepare=False)
    state=studio.store.change(state['id'],lambda s,db:s.update(run_id='run-visual'))
    root=tmp_path/'source-visual-queries'/('a'*64);root.mkdir(parents=True)
    private=tmp_path/'private.json';private.write_text('private')
    target=root/'proposal.json'
    try:target.symlink_to(private)
    except OSError as exc:pytest.skip('Host does not permit links: '+str(exc))
    with studio.store.transaction() as db:
        jid=studio.store.enqueue(db,state['id'],'collect_sources',{'run_id':state['run_id']},'input')
        cp={'visual_query_input':{'task_id':state['id'],'job_id':jid,'run_id':state['run_id'],'input_sha256':'a'*64}}
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),jid))
    with pytest.raises(ValueError,match='증거 파일'):inspect_artifact(studio,state,{'path':str(target)})


@pytest.mark.parametrize('alias',['file','directory','traversal'])
def test_visual_query_alias_to_otherwise_owned_json_is_rejected_before_resolve(tmp_path,alias):
    import os
    from pathlib import Path
    if os.name=='nt':tmp_path=Path('\\\\?\\'+str(tmp_path))
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('visual','Visual',{'active':True},prepare=False)
    state=studio.store.change(state['id'],lambda s,db:s.update(run_id='run-visual'))
    root=tmp_path/'source-visual-queries'/('a'*64);root.mkdir(parents=True)
    actual=root/'review.json';actual.write_text('{}')
    nested=root/('empty-recovery-'+'b'*64)
    if alias=='traversal':
        nested.mkdir();target=nested/'..'/'review.json'
    else:
        try:
            if alias=='file':target=root/'proposal.json';target.symlink_to(actual)
            else:nested.symlink_to(root,target_is_directory=True);target=nested/'review.json'
        except OSError as exc:pytest.skip('Host does not permit links: '+str(exc))
    with studio.store.transaction() as db:
        jid=studio.store.enqueue(db,state['id'],'collect_sources',{'run_id':state['run_id']},'input')
        cp={'visual_query_input':{'task_id':state['id'],'job_id':jid,'run_id':state['run_id'],'input_sha256':'a'*64}}
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),jid))
    assert inspect_artifact(studio,state,{'path':str(actual)})['content']=='{}'
    with pytest.raises(ValueError,match='증거 파일'):inspect_artifact(studio,state,{'path':str(target)})


@pytest.mark.parametrize('damage',[None,'hash','manifest_shortcode','foreign_bundle','outside_bundle','unregistered_manifest','missing_hash'])
def test_owned_manifest_preparation_bundle_is_hash_bound_and_captured(tmp_path,damage):
    from hotpost.video_agent_context import incident_artifacts
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('evidence','Evidence',{'active':True},prepare=False)
    root=studio.settings.source_dir/'evidence-123';root.mkdir(parents=True)
    manifest=root/'manifest.json'
    bundle=tmp_path/'source-preparations'/'evidence'/'bundle.json'
    if damage=='foreign_bundle':bundle=tmp_path/'source-preparations'/'foreign'/'bundle.json'
    if damage=='outside_bundle':bundle=tmp_path/'private.json'
    bundle.parent.mkdir(parents=True,exist_ok=True)
    private=tmp_path/'secret.json';private.write_text('private')
    bundle.write_text(json.dumps({'reference':'preserved','private_path':str(private)}))
    value={'shortcode':'foreign' if damage=='manifest_shortcode' else 'evidence',
        'preparation_bundle_path':str(bundle),'preparation_bundle_sha256':hashlib.sha256(bundle.read_bytes()).hexdigest()}
    if damage=='hash':value['preparation_bundle_sha256']='0'*64
    if damage=='missing_hash':value.pop('preparation_bundle_sha256')
    manifest.write_text(json.dumps(value))
    with studio.store.transaction() as db:
        jid=studio.store.enqueue(db,state['id'],'collect_sources',{},'collect')
        cp={'source_attempts':[] if damage=='unregistered_manifest' else
            [{'task_id':state['id'],'studio_job_id':jid,'shortcode':'evidence','manifest_path':str(manifest)}]}
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),jid))
    # Malformed historical JSON cannot block the valid manifest's bundle.
    for index,value_bad in enumerate([None,[]]):
        bad=studio.settings.source_dir/('evidence-bad-'+str(index))/'manifest.json'
        bad.parent.mkdir(parents=True);bad.write_text(json.dumps(value_bad))
        state['bad_'+str(index)+'_path']=str(bad)
    before=studio.store.get(state['id'])
    if damage:
        with pytest.raises(ValueError,match='증거 파일'):inspect_artifact(studio,state,{'path':str(bundle)})
    else:
        proof=inspect_artifact(studio,state,{'path':str(bundle)})
        assert proof['sha256']==value['preparation_bundle_sha256']
        captured=incident_artifacts(studio,state,{'id':jid,'checkpoint':cp})
        saved=next(a for a in captured if a['path']==str(bundle.resolve()))
        assert saved['content']==bundle.read_text() and saved['sha256']==proof['sha256']
    with pytest.raises(ValueError,match='증거 파일'):inspect_artifact(studio,state,{'path':str(private)})
    assert studio.store.get(state['id'])==before


@pytest.mark.parametrize('damage',[None,'other_task','other_job','other_shortcode','outside_source_root','unregistered_sibling'])
def test_owner_reads_only_registered_evidence_of_its_own_source_attempt(tmp_path,damage):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('evidence','Evidence',{'active':True},prepare=False)
    root=studio.settings.source_dir/'evidence-123';root.mkdir(parents=True)
    manifest=root/'manifest.json';manifest.write_text('{"original_receipt":true}')
    review=root/'source-review.json';review.write_text('{"approved":false}')
    with studio.store.transaction() as db:
        job=studio.store.enqueue(db,state['id'],'collect_sources',{},'collect')
        entry={'task_id':state['id'],'studio_job_id':job,'shortcode':'evidence','manifest_path':str(manifest)}
        if damage=='other_task':entry['task_id']='other'
        if damage=='other_job':entry['studio_job_id']='other'
        if damage=='other_shortcode':entry['shortcode']='other'
        if damage=='outside_source_root':
            manifest=tmp_path/'elsewhere'/'evidence-123'/'manifest.json';manifest.parent.mkdir(parents=True);manifest.write_text('{}');entry['manifest_path']=str(manifest)
        cp={'source_attempts':[entry],'source_batch_review':{'path':str(review),'manifest':str(manifest)}}
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),job))
    target=manifest
    if damage=='unregistered_sibling':target=root/'unregistered.json';target.write_text('{}')
    before=studio.store.get(state['id'])
    if damage:
        with pytest.raises(ValueError,match='증거 파일'):inspect_artifact(studio,state,{'path':str(target)})
    else:
        assert str(review.resolve()) in job_artifact_paths(studio,state)
        result=inspect_artifact(studio,state,{'path':str(target)})
        assert result['content']=='{"original_receipt":true}'
        assert result['sha256']==hashlib.sha256(target.read_bytes()).hexdigest()
        assert inspect_artifact(studio,state,{'path':str(review)})['content']=='{"approved":false}'
    assert studio.store.get(state['id'])==before


@pytest.mark.parametrize('bad_checkpoint',[None,[],{'source_attempts':None},{'source_attempts':[None,12,{}, {'manifest_path':42}]}])
def test_bad_history_does_not_block_valid_owned_evidence(tmp_path,bad_checkpoint):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('evidence','Evidence',{'active':True},prepare=False)
    root=studio.settings.source_dir/'evidence-valid';root.mkdir(parents=True)
    manifest=root/'manifest.json';manifest.write_text('{}')
    with studio.store.transaction() as db:
        good=studio.store.enqueue(db,state['id'],'collect_sources',{},'good')
        bad=studio.store.enqueue(db,state['id'],'collect_sources',{},'bad')
        cp={'source_attempts':[{'task_id':state['id'],'studio_job_id':good,'shortcode':'evidence','manifest_path':str(manifest)}]}
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),good))
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(bad_checkpoint),bad))
    assert inspect_artifact(studio,state,{'path':str(manifest)})['content']=='{}'


@pytest.mark.parametrize('link_kind',['file','directory','cycle'])
def test_owned_evidence_resolves_links_without_granting_external_access(tmp_path,link_kind):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('evidence','Evidence',{'active':True},prepare=False)
    root=studio.settings.source_dir/'evidence-valid';root.mkdir(parents=True)
    manifest=root/'manifest.json';manifest.write_text('{}')
    outside=tmp_path/'external';outside.mkdir();(outside/'private.json').write_text('private')
    link=root/('linked.json' if link_kind!='directory' else 'linked')
    try:
        if link_kind=='file':link.symlink_to(outside/'private.json')
        elif link_kind=='directory':link.symlink_to(outside,target_is_directory=True)
        else:link.symlink_to(link)
    except OSError as exc:pytest.skip('Host does not permit symlink creation: '+str(exc))
    candidate=link/'private.json' if link_kind=='directory' else link
    with studio.store.transaction() as db:
        job=studio.store.enqueue(db,state['id'],'collect_sources',{},'good')
        cp={'source_attempts':[{'task_id':state['id'],'studio_job_id':job,'shortcode':'evidence','manifest_path':str(manifest)}], 'review_path':str(candidate)}
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),job))
    assert job_artifact_paths(studio,state)=={str(manifest.resolve())}
    assert inspect_artifact(studio,state,{'path':str(manifest)})['content']=='{}'
    with pytest.raises((ValueError,RuntimeError,OSError)):inspect_artifact(studio,state,{'path':str(candidate)})



def test_incident_artifacts_are_owned_original_bytes_and_bounded(tmp_path):
    from hotpost.video_agent_context import incident_artifacts,compact_incident
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('evidence','Evidence',{'active':True},prepare=False)
    root=studio.settings.source_dir/'evidence-123';root.mkdir(parents=True)
    files=[root/name for name in ['manifest.json','worker-1.json','worker-2.json']]
    for i,p in enumerate(files):p.write_bytes((str(i)*100000).encode())
    foreign=tmp_path/'foreign.json';foreign.write_text('PRIVATE')
    with studio.store.transaction() as db:
        job=studio.store.enqueue(db,state['id'],'collect_sources',{},'source')
        cp={'source_attempts':[{'task_id':state['id'],'studio_job_id':job,'shortcode':'evidence','manifest_path':str(files[0]),'workers':[{'path':str(p),'settled':True} for p in files[1:]]}],'failure_trace':{'message':'proposal_path='+str(foreign)}}
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),job))
        row=dict(db.execute('select * from jobs where id=?',(job,)).fetchone())
    before=studio.store.get(state['id']);evidence=incident_artifacts(studio,state,row)
    assert len(evidence)==3 and all(r['path']!=str(foreign) for r in evidence)
    assert evidence[0]['content']==files[0].read_text() and evidence[0]['sha256']==hashlib.sha256(files[0].read_bytes()).hexdigest()
    assert sum(len(r.get('content',''))+len(r.get('content_head',''))+len(r.get('content_tail','')) for r in evidence)<=220000
    assert evidence[-1]['truncated'] is True
    incident={'artifacts':evidence};summary=compact_incident(incident,evidence_excerpt=True)
    assert len(json.dumps(summary))<6000 and 'content' in incident['artifacts'][0]
    assert studio.store.get(state['id'])==before


@pytest.mark.parametrize('denied',[False,True])
def test_incident_capture_reads_once_through_guard(monkeypatch,denied):
    import hotpost.video_agent_context as context
    from types import SimpleNamespace
    from pathlib import Path
    content='x'*50000;calls=[]
    def guarded(studio,state,action,*,_full_text=False):
        calls.append(dict(action));assert _full_text
        if denied:raise ValueError('not owned')
        return {'path':'owned.json','content':content,'sha256':hashlib.sha256(content.encode()).hexdigest(),'bytes':len(content),'total_characters':len(content)}
    monkeypatch.setattr(context,'inspect_artifact',guarded)
    monkeypatch.setattr(Path,'read_bytes',lambda path:pytest.fail('unguarded read'))
    result=context.incident_artifacts(SimpleNamespace(),{'id':'task'},{'checkpoint':{'source_attempts':[{'manifest_path':'owned.json'}]}})
    assert len(calls)==1
    if denied:assert result==[]
    else:assert result[0]['content']==content


def test_guarded_text_read_rejects_growth_after_stat(tmp_path,monkeypatch):
    from pathlib import Path
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('growth','Growth',{'active':True},prepare=False)
    file=studio.folder(state['id'])/'growing.json';file.write_text('{}')
    original=Path.open
    def growing(path,mode='r',*args,**kwargs):
        if path==file.resolve() and mode=='rb':
            with original(path,'wb') as writer:writer.write(b'x'*(5*1024*1024))
        return original(path,mode,*args,**kwargs)
    monkeypatch.setattr(Path,'open',growing)
    with pytest.raises(ValueError,match='너무 큽니다'):inspect_artifact(studio,state,{'path':str(file)})


def test_full_capture_uses_one_coherent_read_and_planner_cannot_request_unbounded_text(tmp_path,monkeypatch):
    from pathlib import Path
    from hotpost.video_agent_context import incident_artifacts
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('snapshot','Snapshot',{'active':True},prepare=False)
    file=studio.folder(state['id'])/'review.json';content='x'*50000;file.write_text(content)
    real_open=Path.open;reads=[]
    def counted(path,mode='r',*args,**kwargs):
        if path==file.resolve() and mode=='rb':reads.append(str(path))
        return real_open(path,mode,*args,**kwargs)
    monkeypatch.setattr(Path,'open',counted)
    result=incident_artifacts(studio,state,{'checkpoint':{'review_path':str(file)}})
    assert len(reads)==1 and result[0]['content']==content
    assert result[0]['sha256']==hashlib.sha256(content.encode()).hexdigest()
    proof=inspect_artifact(studio,state,{'path':str(file),'_full_text':True,'limit':1000000})
    assert len(proof['content'])==24000 and proof['next_offset']==24000


@pytest.mark.parametrize('binding_error',[None,'task_id','job_id','run_id'])
def test_incident_captures_registered_correction_evidence_for_exact_failed_job(tmp_path,binding_error):
    from pathlib import Path
    from hotpost.video_agent_context import incident_artifacts
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('correction','Correction',{'active':True},prepare=False)
    state['run_id']='same-run'
    folder=tmp_path/'source-visual-queries'/'input-hash';folder.mkdir(parents=True)
    files=[]
    for name in ('proposal.json','review.json','identity-correction-proposal.json','identity-correction-review.json'):
        path=folder/name;path.write_text(json.dumps({'original_name':name}),'utf8');files.append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    with studio.store.transaction() as db:
        jid=studio.store.enqueue(db,state['id'],'collect_sources',{},'collect')
        row=dict(db.execute('select * from jobs where id=?',(jid,)).fetchone())
    binding={'task_id':state['id'],'job_id':jid,'run_id':state['run_id']}
    if binding_error:binding[binding_error]='different'
    state['source_acquisition']={'visual_query_rejection':{'binding':binding,'files':files[:2],'correction_diagnostics':files[2:]}}
    before=json.dumps(state,sort_keys=True)
    captured=incident_artifacts(studio,state,row)
    assert json.dumps(state,sort_keys=True)==before
    if binding_error:assert captured==[]
    else:
        assert {r['path'] for r in captured}=={str(Path(f['path']).resolve()) for f in files}
        assert all(r['content']==Path(r['path']).read_text('utf8') for r in captured)


def test_checkpoint_review_files_reach_full_fixture_but_model_projection_stays_bounded(tmp_path):
    from hotpost.video_agent_context import incident_artifacts,review_artifacts
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('bound-review','Review',{'active':True},prepare=False)
    folder=studio.folder(state['id'])
    proof=folder/'current-review.json';proof.write_text('x'*350000,'utf8')
    foreign=tmp_path/'private.json';foreign.write_text('private','utf8')
    with studio.store.transaction() as db:
        jid=studio.store.enqueue(db,state['id'],'collect_sources',{},'source')
        cp={'deferred_source_review':{'path':str(proof)},'foreign_path':str(foreign)}
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),jid))
        row=dict(db.execute('select * from jobs where id=?',(jid,)).fetchone())
    full=incident_artifacts(studio,state,row,max_characters=4000000,max_files=24)
    assert len(full)==1 and full[0]['content']==proof.read_text('utf8') and full[0]['truncated'] is False
    projected=review_artifacts(full)
    assert projected[0]['sha256']==full[0]['sha256'] and projected[0]['truncated'] is True
    assert len(projected[0]['content_head'])+len(projected[0]['content_tail'])==220000
    assert 'content' in full[0] and 'content_head' not in full[0]
    partial=review_artifacts([{'content_head':'prefix','content_tail':'suffix','truncated':True,'sha256':'original'}])
    assert partial[0]['content_head']=='prefix' and partial[0]['content_tail']=='suffix'
    one_left=review_artifacts([{'content':'x'*219999,'truncated':False},
        {'content_head':'HEAD','content_tail':'TAIL','truncated':True}])
    assert one_left[1]['content_head']=='H' and one_left[1]['content_tail']==''
    assert sum(len(r.get('content',''))+len(r.get('content_head',''))+len(r.get('content_tail','')) for r in one_left)==220000
