"""One normal hook proposal after the full-canvas cover's actual rejection."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from hotpost.cover_selection import cover_gap
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json
from hotpost.initial_prepared_render import sha
from hotpost.script_rewriter import _generate

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/rework-top-three-20261014'
OUT=BASE/'rank2-cover-copy-v1'
TASK='work-8013247e50624ae6'

def main():
    assert not OUT.exists(),'Preserve the existing proposal; no blind copy replay'
    with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        state=json.loads(db.execute('select state from tasks where id=?',(TASK,)).fetchone()[0])
        assert not db.execute("select 1 from jobs where task_id=? and status in ('queued','running')",(TASK,)).fetchone()
    assert state['revision']==1722 and state['automation']['paused_by_user'] and not state['edits']
    pixels=BASE/'rank2-cover-pixels-v2/candidates.json'
    pixel_proof=BASE/'rank2-cover-pixels-v2/pixel-proof.json'
    proof=json.loads(pixel_proof.read_text('utf-8'))
    selected=Path(proof['selected_plan_path']);plan=json.loads(selected.read_text('utf-8'))['plan']
    review=BASE/'rank2-initial-cover-preparation-v1/cover-selection.json'
    reviews=json.loads(review.read_text('utf-8'))['reviews']
    assert len(reviews)==3 and all(r['hook_unresolved'] is False and r['faces_present'] is False
        and all(r[k] is True for k in ('overlays_acceptable','mask_coverage_valid','product_view_preserved')) for r in reviews)
    OUT.mkdir()
    binding={'task_id':TASK,'run_id':state['run_id'],'script_id':state['script_id'],'voice_id':state['voice_id'],
        'selected_path':str(selected.resolve()),'selected_sha256':sha(selected),'candidates_path':str(pixels.resolve()),
        'candidates_sha256':sha(pixels),'failed_fullcanvas_review_path':str(review.resolve()),
        'failed_fullcanvas_review_sha256':sha(review),'previous_lines':plan['cover_spec']['lines']}
    _atomic_json(OUT/'input-binding.json',binding)
    def generate(settings,instruction,data,media=None):
        assert data['purpose']=='cover_hook_repair'
        marker=OUT/'official-hook-proposal.json'
        assert not marker.exists()
        payload={'instruction':instruction,'evidence':data,'media':media or []}
        raw=json.dumps(payload,ensure_ascii=False,sort_keys=True)
        jid='codex'+hashlib.sha256(('editorial\n\n'+raw).encode()).hexdigest()[:32]
        item={'state':'pending','binding':binding,'writing_job_id':jid,'payload_sha256':hashlib.sha256(raw.encode()).hexdigest(),'at':time.time()}
        _atomic_json(marker,item)
        result=_generate(settings,instruction,data,media=media)
        writing=ROOT/'data/writing'/jid/'result.json';recorded=json.loads(writing.read_text('utf-8'))
        calls=recorded['inference']['calls'];assert recorded['value']==result and len(calls)==1 and calls[0]['status']=='completed'
        item.update(state='completed',result=result,actual_calls=1,call_id=calls[0]['call_id'],
            writing_result={'path':str(writing.resolve()),'sha256':sha(writing)})
        _atomic_json(marker,item)
        return result
    gap=cover_gap(load_settings(),plan,json.loads(pixels.read_text('utf-8')),reviews,generate,'사과요리')
    assert gap.thumbnail_lines and gap.thumbnail_lines!=plan['cover_spec']['lines']
    _atomic_json(OUT/'proposal.json',{'binding':binding,'thumbnail_lines':gap.thumbnail_lines,
        'official_proposal_path':str((OUT/'official-hook-proposal.json').resolve()),
        'official_proposal_sha256':sha(OUT/'official-hook-proposal.json'),'actual_calls':1,
        'approved':False,'task_mutations':0,'voice_regenerations':0})
    print(json.dumps({'actual_calls':1,'thumbnail_lines':gap.thumbnail_lines,'approved':False},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
