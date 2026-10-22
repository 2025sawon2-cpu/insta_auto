import copy,hashlib,json,os
from pathlib import Path
import pytest
from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost import source_visual_queries as visual
from hotpost.video_agent_context import inspect_artifact,incident_artifacts,visual_query_artifact_paths


def setup(tmp_path):
    if os.name=='nt':tmp_path=Path('\\\\?\\'+str(tmp_path))
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('pool','Pool',{'active':True},prepare=False)
    state=studio.store.change(state['id'],lambda s,db:s.update(run_id='run-current'))
    evidence={'policy':visual.LEGACY_MINIMUM_POLICY,'frames':[],'text':{'caption':'original'},
        'search_minimums':{'en':5,'zh':5},'reference_path':str(tmp_path/'unread-media'),
        'reference_sha256':'1'*64}
    key=visual.digest(evidence);proposal={'queries':[],'observations':[]}
    review={'input_sha256':key,'proposal_sha256':visual.digest(proposal),'checks':[]}
    pool=visual.query_pool_report([],evidence['search_minimums'])
    receipt={'policy':evidence['policy'],'input_sha256':key,'evidence':evidence,'proposal':proposal,
        'review':review,'queries':[],'approved_query_pool':pool}
    assert visual.verify(receipt,verify_files=False)==[]
    parent=tmp_path/'source-visual-queries'/key/('empty-recovery-'+'b'*64)/'receipt.json'
    parent.parent.mkdir(parents=True);parent.write_text(json.dumps(receipt),'utf8')
    feedback={'evidence':evidence,'previous_proposal':proposal,'independent_review':review,
        'accepted_query_pool':pool,'contract_defects':[]}
    flat=tmp_path/'source-visual-pool-recoveries'/visual.digest(feedback);flat.mkdir(parents=True)
    documents={'proposal.json':{'input_sha256':key,'proposal':{'queries':[]}},
        'review.json':{'input_sha256':key,'query_set_reason':'product absent in pixels; text search remains possible'},
        'receipt.json':receipt}
    for name,value in documents.items():(flat/name).write_text(json.dumps(value),'utf8')
    with studio.store.transaction() as db:
        jid=studio.store.enqueue(db,state['id'],'collect_sources',{'run_id':state['run_id']},'pool-input')
        cp={'visual_query_input':{'task_id':state['id'],'job_id':jid,'run_id':state['run_id'],'input_sha256':key}}
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),jid))
    return studio,state,jid,cp,parent,flat


def test_flat_pool_diagnostics_follow_exact_owned_parent_and_are_captured(tmp_path):
    studio,state,jid,cp,parent,flat=setup(tmp_path)
    before=studio.store.get(state['id']);raw={p:p.read_bytes() for p in [parent,*flat.iterdir()]}
    allowed=visual_query_artifact_paths(studio,state,job_id=jid)
    captured={x['path']:x for x in incident_artifacts(studio,state,{'id':jid,'checkpoint':cp},max_files=24)}
    for name in ('proposal.json','review.json','receipt.json'):
        path=flat/name;result=inspect_artifact(studio,state,{'path':str(path)})
        assert str(path.resolve()) in allowed and captured[str(path.resolve())]['content']==result['content']
        assert result['sha256']==hashlib.sha256(raw[path]).hexdigest()
    assert not (tmp_path/'unread-media').exists()  # Diagnostic scope never reads referenced media.
    assert studio.store.get(state['id'])==before
    assert all(p.read_bytes()==data for p,data in raw.items())
    with studio.store.connect() as db:assert db.execute('select status from jobs where id=?',(jid,)).fetchone()[0]=='queued'


@pytest.mark.parametrize('damage',['task','job','run','payload_run','input','parent_digest','parent_review',
    'parent_queries','missing_parent','parent_oversize','foreign_flat','foreign_document','private_name','traversal','target_oversize'])
def test_flat_pool_diagnostic_authority_is_bounded_and_not_transferable(tmp_path,damage):
    studio,state,jid,cp,parent,flat=setup(tmp_path);target=flat/'review.json'
    if damage in {'task','job','run','input','payload_run'}:
        with studio.store.transaction() as db:
            if damage=='payload_run':db.execute('update jobs set payload=? where id=?',(json.dumps({'run_id':'other'}),jid))
            else:
                key='input_sha256' if damage=='input' else damage+'_id';cp['visual_query_input'][key]='a'*64 if damage=='input' else 'other'
                db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),jid))
    elif damage.startswith('parent_'):
        doc=json.loads(parent.read_text('utf8'))
        if damage=='parent_digest':doc['evidence']['text']['caption']='changed'
        elif damage=='parent_review':doc['review']['proposal_sha256']='0'*64
        elif damage=='parent_queries':doc['queries']=[{'query':'invented'}]
        if damage=='parent_oversize':parent.write_text(' '*300000,'utf8')
        else:parent.write_text(json.dumps(doc),'utf8')
    elif damage=='missing_parent':parent.unlink()
    elif damage=='foreign_flat':
        target=flat.parent/('d'*64)/'review.json';target.parent.mkdir();target.write_text((flat/'review.json').read_text('utf8'),'utf8')
    elif damage=='foreign_document':target.write_text(json.dumps({'input_sha256':'e'*64}),'utf8')
    elif damage=='private_name':target=flat/'private.json';target.write_text('private','utf8')
    elif damage=='traversal':target=flat/'alias'/'..'/'review.json'
    elif damage=='target_oversize':target.write_text(json.dumps({'input_sha256':cp['visual_query_input']['input_sha256'],'padding':'x'*300000}),'utf8')
    with pytest.raises(ValueError,match='증거 파일'):inspect_artifact(studio,state,{'path':str(target)})
    assert str(target) not in visual_query_artifact_paths(studio,state,target=target)


def test_empty_directories_do_not_consume_parent_read_budget(tmp_path,monkeypatch):
    studio,state,jid,cp,parent,flat=setup(tmp_path)
    root=parent.parent.parent
    empty=[]
    for n in range(16):
        path=root/('empty-recovery-'+format(n,'064x'));path.mkdir();empty.append(path)
    original=Path.iterdir
    def ordered(path):
        if path.resolve()==root.resolve():return iter([*empty,parent.parent])
        return original(path)
    monkeypatch.setattr(Path,'iterdir',ordered)
    captured={x['path'] for x in incident_artifacts(studio,state,{'id':jid,'checkpoint':cp},max_files=24)}
    for name in ('proposal.json','review.json','receipt.json'):
        path=flat/name
        assert inspect_artifact(studio,state,{'path':str(path)})['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
        assert str(path.resolve()) in captured


def test_unrelated_directory_error_preserves_direct_and_flat_diagnostics(tmp_path,monkeypatch):
    studio,state,jid,cp,parent,flat=setup(tmp_path)
    root=parent.parent.parent
    legacy=root/'proposal.json';legacy.write_text('{"existing":true}','utf8')
    inaccessible=root/('empty-recovery-'+'c'*64);inaccessible.mkdir()
    original=Path.iterdir
    def fail_one(path):
        if path.resolve()==inaccessible.resolve():raise PermissionError('unrelated directory')
        return original(path)
    monkeypatch.setattr(Path,'iterdir',fail_one)
    assert inspect_artifact(studio,state,{'path':str(legacy)})['sha256']==hashlib.sha256(legacy.read_bytes()).hexdigest()
    assert str((flat/'review.json').resolve()) in visual_query_artifact_paths(studio,state)


def test_pool_diagnostic_does_not_follow_symlink(tmp_path):
    studio,state,jid,cp,parent,flat=setup(tmp_path);target=flat/'review.json';target.unlink()
    private=tmp_path/'private.json';private.write_text('private','utf8')
    try:target.symlink_to(private)
    except OSError as exc:pytest.skip('Host link permission: '+str(exc))
    with pytest.raises(ValueError,match='증거 파일'):inspect_artifact(studio,state,{'path':str(target)})
