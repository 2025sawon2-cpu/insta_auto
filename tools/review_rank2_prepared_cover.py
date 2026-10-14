"""Review the fixed full canvases once and freeze the existing initial selection."""
import copy
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from hotpost.config import load_settings
from hotpost.cover_selection import select_cover
from hotpost.editing_adapter import _atomic_json
from hotpost.initial_prepared_render import POLICY, checked_cover, checked_plan, digest, sha
from hotpost.scene_requirements import input_signature
from hotpost.script_rewriter import _generate

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/rework-top-three-20261014'
OUT=BASE/'rank2-initial-cover-preparation-v1'
TASK='work-8013247e50624ae6'
PIXEL_PROOF_SHA='c62459ab3b495f5c96b190783f2777daf54b975cf376f6e614eba595632bd925'
CANDIDATES_SHA='d1041a2e9a9b76451635b36213f1040ebb0d9a345a60a3cbe593e4d0a191df03'


def main():
    global OUT
    parser=argparse.ArgumentParser();parser.add_argument('--copy-proposal',type=Path);args=parser.parse_args()
    copy_revision=None
    if args.copy_proposal:
        copy_revision=args.copy_proposal.resolve()
        OUT=BASE/'rank2-initial-cover-preparation-v2-copy'
    with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        state=json.loads(db.execute('select state from tasks where id=?',(TASK,)).fetchone()[0])
        assert not db.execute("select 1 from jobs where task_id=? and status in ('queued','running')",(TASK,)).fetchone()
    assert state['revision']==1722 and state['automation']['paused_by_user'] and not state['edits']
    pixel_path=BASE/'rank2-cover-pixels-v2/pixel-proof.json'
    candidates_path=pixel_path.parent/'candidates.json'
    assert sha(pixel_path)==PIXEL_PROOF_SHA and sha(candidates_path)==CANDIDATES_SHA
    pixel=json.loads(pixel_path.read_text('utf-8'));candidates=json.loads(candidates_path.read_text('utf-8'))
    selected_path=Path(pixel['selected_plan_path'])
    assert sha(selected_path)==pixel['selected_plan_sha256']
    plan=json.loads(selected_path.read_text('utf-8'))['plan']
    if copy_revision:
        proposal=json.loads(copy_revision.read_text('utf-8'))
        assert proposal['binding']['selected_sha256']==sha(selected_path)
        assert proposal['binding']['previous_lines']==plan['cover_spec']['lines']
        assert proposal['task_mutations']==0 and proposal['approved'] is False
        lines=proposal['thumbnail_lines']
        plan=copy.deepcopy(plan)
        plan['cover_spec'].update(lines=lines,copy_origin='actual-full-canvas-hook-revision')
        state=copy.deepcopy(state)
        state['daily_quality']['thumbnail_lines']=lines
    for candidate in candidates:checked_cover(plan,candidate,require_approval=False)
    independent_path=BASE/'rank2-cover-fullcanvas-v2-independent.json'
    independent=json.loads(independent_path.read_text('utf-8'))
    assert independent['status']=='PASS' and independent['task_id']==TASK
    assert independent['pixel_proof_sha256']==PIXEL_PROOF_SHA and independent['candidates_sha256']==CANDIDATES_SHA
    binding={'task_id':TASK,'run_id':state['run_id'],'script_id':state['script_id'],'voice_id':state['voice_id'],
        'input_signature':input_signature(state),'selected_plan_sha256':sha(selected_path),
        'pixel_proof_sha256':PIXEL_PROOF_SHA,'candidates_sha256':CANDIDATES_SHA,
        'independent_sha256':sha(independent_path)}
    if copy_revision:binding['copy_revision_sha256']=sha(copy_revision)
    OUT.mkdir(exist_ok=True)
    marker=OUT/'input-binding.json'
    if marker.exists():assert json.loads(marker.read_text('utf-8'))==binding
    else:_atomic_json(marker,binding)
    settings=load_settings()
    assert settings.data_dir.resolve()==ROOT/'data'

    def generate(call_settings,instruction,data,media=None):
        purpose=data.get('purpose')
        if purpose not in {'cover_selection','cover_single_frame_confirmation'}:
            raise RuntimeError('Frozen thumbnail copy requires new pixel evidence; do not generate another hook')
        payload={'instruction':instruction,'evidence':data,'media':media or []}
        raw=json.dumps(payload,ensure_ascii=False,sort_keys=True)
        jid='codex'+hashlib.sha256(('editorial\n\n'+raw).encode()).hexdigest()[:32]
        path=OUT/('official-'+purpose+'.json')
        if path.exists():
            completed=json.loads(path.read_text('utf-8'))
            assert completed['binding']==binding and completed['payload_sha256']==hashlib.sha256(raw.encode()).hexdigest()
            if completed['state']!='completed':raise RuntimeError('Prior cover submission is unconfirmed; preserve it')
            return completed['result']
        value={'state':'pending','binding':binding,'purpose':purpose,'writing_job_id':jid,
            'payload_sha256':hashlib.sha256(raw.encode()).hexdigest(),'at':time.time(),
            'frame_ids':data['frame_ids'],'candidate_id':data.get('candidate_id')}
        _atomic_json(path,value)
        result=_generate(call_settings,instruction,data,media=media)
        with sqlite3.connect((ROOT/'data/writing/jobs.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
            row=db.execute('select state,payload,result from jobs where id=?',(jid,)).fetchone()
            assert row[0]=='completed' and hashlib.sha256(row[1].encode()).hexdigest()==value['payload_sha256']
            recorded=json.loads(row[2]);assert recorded['value']==result
            calls=recorded['inference']['calls'];assert len(calls)==1 and calls[0]['status']=='completed'
        value.update(state='completed',result=result,actual_calls=1,call_id=calls[0]['call_id'],completed_at=time.time())
        job_result=ROOT/'data/writing'/jid/'result.json'
        value['writing_result']={'path':str(job_result.resolve()),'sha256':sha(job_result)}
        _atomic_json(path,value)
        return result

    prepared=select_cover(settings,copy.deepcopy(plan),copy.deepcopy(candidates),OUT,generate,
        search_context=state['product'],_allow_product_crop=False)
    candidate=prepared['cover_spec']['source'];material=checked_cover(prepared,candidate)
    from hotpost.initial_prepared_render import canonical_lines
    material['thumbnail_lines']=canonical_lines(prepared['cover_spec']['lines'])
    path=OUT/'prepared-plan.json'
    if path.exists():assert json.loads(path.read_text('utf-8'))==prepared
    else:_atomic_json(path,prepared)
    evidence={k:v for k,v in binding.items() if k!='selected_plan_sha256'}
    evidence.update(policy=POLICY,material=material,material_key=digest(material),
        accepted_cover_binding_sha256=candidate['cover_pixel_binding']['binding_sha256'],
        preparation_failure_identity=state['daily_quality']['preparation_failures'][-1]['identity'])
    for key,p in [('prepared_plan',path),('selected_result',selected_path),('cover_review',OUT/'cover-selection.json'),
            ('independent_review',independent_path),('pixel_candidates',candidates_path),('pixel_proof',pixel_path),
            ('batch_submission',OUT/'official-cover_selection.json'),('solo_submission',OUT/'official-cover_single_frame_confirmation.json')]:
        evidence[key]={'path':str(p.resolve()),'sha256':sha(p)}
    if copy_revision:evidence['copy_revision']={'path':str(copy_revision),'sha256':sha(copy_revision)}
    checked_plan(state,evidence)
    dest=OUT/'prepared-render-receipt.json'
    if dest.exists():assert json.loads(dest.read_text('utf-8'))==evidence
    else:_atomic_json(dest,evidence)
    print(json.dumps({'actual_calls':2,'source_id':candidate['source_id'],'native_frame':candidate['cover_pixel_binding']['native_frame'],
        'material_key':evidence['material_key'],'task_mutations':0,'renders':0},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
