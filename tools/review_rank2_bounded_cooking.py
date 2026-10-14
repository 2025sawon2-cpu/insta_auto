"""Run the single frozen cooking scope through normal visual reviewers."""
import copy
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import patch

from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json
from hotpost.source_functional import review_function, apply_function_review
from hotpost.source_mask_review import explicit_review_scope, _check_evidence
from hotpost.source_overlay_review import review_source_overlays, accepted_interval_frames, POLICY
from hotpost.source_presentation import review_presentation, apply_presentation_review
from hotpost.source_quality import sha256_file as _file_sha256
from hotpost.studio_sources import source_goal

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/rework-top-three-20261014/rank2-bounded-cooking-v1'
TASK='work-8013247e50624ae6'
SOURCE='source-a56be5436e7f48e1'


def sha256_file(path):
    return _file_sha256(Path(path))


def canonical(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--recover-function-service',action='store_true')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    pending=ROOT/'data/rework-top-three-20261014/rank2-LyV-bounded-official-pending-input.json'
    request=json.loads(pending.read_text('utf-8'))
    with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        state=json.loads(db.execute('select state from tasks where id=?',(TASK,)).fetchone()[0])
        assert not db.execute("select 1 from jobs where task_id=? and status in ('queued','running')",(TASK,)).fetchone()
    assert state['automation']['paused_by_user'] and len(state['sources'])==35
    source=next(s for s in state['sources'] if s['id']==SOURCE)
    assert canonical(source)==request['accepted_input_binding']['source_state_sha256']
    assert sha256_file(source['path'])==request['source_sha256']==source['sha256']
    assert sha256_file(state['reference_video'])==request['reference_sha256']
    task_folder=ROOT/'data/studio'/TASK
    reference_frames=[task_folder/'source-reference'/f'frame_{i:03d}.jpg' for i in range(1,5)]
    overview=task_folder/('source-reference-overview-'+request['reference_sha256'][:16]+'.jpg')
    assert all(p.is_file() for p in [*reference_frames,overview])
    reference_info={'original_product_text':state.get('reviewed_original_text') or state.get('original_text',''),
        'product':state.get('product',''),'overview_path':str(overview),
        'overview_sha256':sha256_file(overview),'reference_sha256':request['reference_sha256']}
    before=copy.deepcopy(source)
    binding={'task_id':TASK,'source_id':SOURCE,'source_state_sha256':canonical(source),
        'request_sha256':sha256_file(pending),'reference_sha256':request['reference_sha256'],
        'source_sha256':source['sha256'],'intervals':request['requested_intervals'],
        'reference_frames_sha256':{str(p):sha256_file(p) for p in [*reference_frames,overview]}}
    marker=OUT/'input-binding.json'
    if marker.exists():assert json.loads(marker.read_text('utf-8'))==binding
    else:_atomic_json(marker,binding)
    scope=explicit_review_scope(source['sha256'],request['requested_intervals'],source['video_meta']['duration'],
        samples_per_interval=5,policy=POLICY)
    folder=OUT/'mask'
    folder.mkdir(exist_ok=True)
    if not (folder/'overlay-scope.json').exists():
        evidence=json.loads(Path(request['candidate_evidence_path']).read_text('utf-8'))
        assert sha256_file(request['candidate_evidence_path'])==request['candidate_evidence_sha256']
        _check_evidence(evidence)
        assert len(evidence['frames'])==5
        _atomic_json(folder/'overlay-scope.json',scope)
        _atomic_json(folder/'overlay-evidence.json',evidence)
    settings=load_settings()
    assert settings.data_dir.resolve()==ROOT/'data'
    from hotpost.script_rewriter import _generate

    def traced_generate(*args,**kwargs):
        purpose=args[2].get('purpose','bounded-review')
        record=OUT/('model-'+purpose+'.json')
        if record.exists():raise RuntimeError('Preserve prior submission; no blind replay: '+purpose)
        _atomic_json(record,{'state':'submission_pending','at':time.time(),'binding':binding,'purpose':purpose})
        result=_generate(*args,**kwargs)
        _atomic_json(record,{'state':'completed','at':time.time(),'binding':binding,'purpose':purpose,'result':result})
        return result

    result=review_source_overlays(settings,copy.deepcopy(source),folder,
        generate=traced_generate,intervals=request['requested_intervals'])
    accepted=accepted_interval_frames(result)
    assert result['reviewed_intervals']==[{'source_start':22.0,'source_end':26.0}]
    function_path=OUT/'function.json'
    function_gate=OUT/'function-submission.json'
    if function_path.exists():
        completed=json.loads(function_gate.read_text('utf-8')) if function_gate.exists() else {}
        assert completed.get('state')=='completed' and completed.get('binding')==binding
        assert completed.get('result_sha256')==sha256_file(function_path)
        function=json.loads(function_path.read_text('utf-8'))
    else:
        # Stage functions use their normal generator; an operator marker prevents
        # unconfirmed submissions from being silently replayed by this tool.
        gate=OUT/'function-submission.json'
        recovery_attempt=None
        if gate.exists():
            if not args.recover_function_service:
                raise RuntimeError('Prior function submission needs explicit result recovery')
            held=json.loads((OUT/'function-service-hold.json').read_text('utf-8'))
            recovery=json.loads((OUT/'function-service-recovery-registration.json').read_text('utf-8'))
            assert json.loads(gate.read_text('utf-8'))==held['function_original_submission']
            assert recovery['state']=='registered' and recovery['binding']==binding
            assert recovery['hold_sha256']==sha256_file(OUT/'function-service-hold.json')
            assert time.time()>=recovery['retry_at'],'Preserve the actual service waiting time'
            for p,digest in held['raw_files'].items():assert sha256_file(p)==digest
            for p,digest in recovery['code_sha256'].items():assert sha256_file(p)==digest
            with sqlite3.connect((ROOT/'data/writing/jobs.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
                row=db.execute('select state,payload,result from jobs where id=?',(held['writing_job_id'],)).fetchone()
                assert row[0]=='failed' and hashlib.sha256(row[1].encode()).hexdigest()==held['payload_sha256']
                assert json.loads(row[2])==held['original_job_result']
            recovery_attempt=OUT/'function-service-single-probe.json'
            if recovery_attempt.exists():raise RuntimeError('The bounded recovery probe was already claimed; preserve its outcome')
            _atomic_json(recovery_attempt,{'state':'pending','binding':binding,'at':time.time(),
                'registration_sha256':sha256_file(OUT/'function-service-recovery-registration.json')})
        else:
            if args.recover_function_service:raise RuntimeError('No preserved function service failure exists')
            _atomic_json(gate,{'state':'pending','binding':binding,'at':time.time()})
        try:
            def checked_recovery_generate(call_settings,instruction,data,media=None):
                payload={'instruction':instruction,'evidence':data,'media':media or []}
                fingerprint=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                if fingerprint!=held['payload_sha256']:raise RuntimeError('Recovered function payload differs from the actual failed request')
                with sqlite3.connect((ROOT/'data/writing/jobs.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
                    assert not db.execute("select 1 from jobs where state in ('queued','running')").fetchone()
                from hotpost.writing.jobs import Jobs
                assert not Jobs(ROOT/'data/writing').active_children(held['writing_job_id'])
                return _generate(call_settings,instruction,data,media=media)
            if recovery_attempt:
                with patch('hotpost.script_rewriter._generate',checked_recovery_generate):
                    function=review_function(settings,SimpleNamespace(file_sha256=source['sha256']),reference_frames,
                        accepted,reference_info)
            else:
                function=review_function(settings,SimpleNamespace(file_sha256=source['sha256']),reference_frames,
                    accepted,reference_info)
        except Exception as exc:
            if recovery_attempt:
                _atomic_json(recovery_attempt,{'state':'failed','binding':binding,'at':time.time(),
                    'error_type':type(exc).__name__,'retry_at':getattr(exc,'retry_at',None),
                    'attempted':getattr(exc,'attempted',None),'automatic_second_probe':False})
            raise
        _atomic_json(function_path,function)
        _atomic_json(gate,{'state':'completed','binding':binding,'at':time.time(),
            'result_sha256':sha256_file(function_path)})
        if recovery_attempt:
            _atomic_json(recovery_attempt,{'state':'completed','binding':binding,'at':time.time(),
                'result_sha256':sha256_file(function_path),'actual_probes':1})
    assert function['source_sha256']==source['sha256']
    expected_function_frames=[str(overview),*[str(p) for p in reference_frames],*[f['path'] for f in accepted]]
    assert function['evidence_frames']==expected_function_frames
    apply_function_review(result,function)
    if result.get('editing_eligible'):
        portrait_path=OUT/'portrait.json'
        portrait_gate=OUT/'portrait-submission.json'
        if portrait_path.exists():
            completed=json.loads(portrait_gate.read_text('utf-8')) if portrait_gate.exists() else {}
            assert completed.get('state')=='completed' and completed.get('binding')==binding
            assert completed.get('result_sha256')==sha256_file(portrait_path)
            portrait=json.loads(portrait_path.read_text('utf-8'))
        else:
            gate=OUT/'portrait-submission.json'
            if gate.exists():raise RuntimeError('Prior portrait submission needs explicit result recovery')
            _atomic_json(gate,{'state':'pending','binding':binding,'at':time.time()})
            portrait=review_presentation(settings,result,OUT/'portrait-frames')
            _atomic_json(portrait_path,portrait)
            _atomic_json(gate,{'state':'completed','binding':binding,'at':time.time(),
                'result_sha256':sha256_file(portrait_path)})
        apply_presentation_review(result,portrait)
    assert source==before
    assert binding['reference_frames_sha256']=={str(p):sha256_file(p) for p in [*reference_frames,overview]}
    trial=copy.deepcopy(state)
    trial['sources']=[result if s['id']==SOURCE else s for s in trial['sources']]
    goal=source_goal(trial,settings.source_min_usable)
    _atomic_json(OUT/'official-result.json',{'binding':binding,'source':result,'goal':goal,
        'task_mutations':0,'downloads':0,'browser_requests':0,'created_at':time.time()})
    print(json.dumps({'source_role':result.get('source_role'),'editing_eligible':result.get('editing_eligible'),
        'intervals':result['reviewed_intervals'],'goal':goal},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
