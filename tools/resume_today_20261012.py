"""Preserve daily versions and resume through the existing Studio commands."""
import argparse,copy,json,re,time
from pathlib import Path
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.editing_adapter import _atomic_json
from hotpost.writing.contract import receipt
from hotpost.studio_workflow import current_run,init_run,snapshot
ROOT=Path('data/source-recovery-20261012-v1').resolve()

def cta():
    studio=Studio(load_settings(),workers=False);records=[]
    tasks=sorted([t for t in studio.store.list() if t.get('automation',{}).get('selection_date_kst')=='2026-10-12'],key=lambda t:t['automation'].get('rank',99))
    for state in tasks:
        script=next(s for s in state['scripts'] if s['id']==state['script_id']);text=script['text']
        match=re.search(r'댓글에\s*[‘’\'"“”]?([가-힣A-Za-z0-9]{1,20})[‘’\'"“”]?\s*남겨주세요[.!。]?\s*$',text)
        assert match,'Inspect unsupported ending manually before changing it'
        if match.group(1)=='나도':
            if script.get('origin')=='manual' and not state.get('approved_script_id') and not state.get('voice_id'):
                studio.action(state['id'],'approve-script',{'script_id':script['id']})
                print(state['shortcode'],'completed interrupted CTA update; voice generation queued',flush=True)
            continue
        target=text[:match.start()]+'댓글에 ‘나도’ 남겨주세요.'
        candidate=state.get('selected_candidate')
        if isinstance(candidate,int):
            candidates=state.get('script_candidates',[])
            candidate=candidates[candidate] if 0<=candidate<len(candidates) else {}
        selected=copy.deepcopy(candidate if isinstance(candidate,dict) else {})
        selected.update(text=target,writing_contract=receipt(),revision_reason='사용자 확정한 나도 키워드만 변경; 본문 보존')
        def revise_unfinished(s,db):
            assert not s.get('edits'),'Use normal reproduction for an already rendered task'
            live=db.execute("SELECT kind FROM jobs WHERE task_id=? AND status IN ('queued','running') AND kind NOT IN ('collect_sources','refresh_sources')",(s['id'],)).fetchall()
            assert not live,'Wait for the existing production step rather than replace its inputs'
            # Automatic intake allows script/voice generation before acquisition.
            # The Studio reproduction UI requires an existing selected source;
            # create the same version boundary for these unfinished zero-source tasks.
            old=snapshot(s);old['status']='superseded';s.pop('run_id',None)
            run=init_run(s);run.update(parent_id=old['id'],inputs={**copy.deepcopy(old['inputs']),'script_text':target})
            run['inputs'].pop('source_ids',None)
            studio._script(s,target,'user_fixed_cta_recovery')
            s['cta_recovery_candidate']=selected
            s['feedback']={};s.pop('pending_reproduction',None)
            s['automation'].update(active=True,needs_top_pick=False,selection_mode='manual_resume')
            studio.advance_workflow(s,db)
            studio.store.event(db,s['id'],'fixed_cta_recovery',{'previous_run_id':old['id'],'new_run_id':run['id'],'scope':'CTA only; original script and voice preserved'})
        reproduced=studio.store.change(state['id'],revise_unfinished)
        records.append({'shortcode':state['shortcode'],'previous_script_id':script['id'],'previous_voice_id':state['voice_id'],'new_script_id':reproduced.get('script_id'),'new_run_id':reproduced.get('run_id'),'pending':bool(reproduced.get('pending_reproduction')),'change':'CTA keyword only','at':time.time()})
        _atomic_json(ROOT/'cta-revisions.json',records)
        print(state['shortcode'],'whole-script voice generation queued for fixed 나도 ending',flush=True)
    _atomic_json(ROOT/'cta-revisions.json',records)

def resume(code):
    studio=Studio(load_settings(),workers=False);state=next(t for t in studio.store.list() if t['shortcode']==code)
    assert state.get('automation',{}).get('selection_date_kst')=='2026-10-12'
    result=studio.action(state['id'],'resume-auto',{})
    _atomic_json(ROOT/code/'resume-receipt.json',{'task_id':state['id'],'at':time.time(),'status':result['status'],'message':result.get('message'),'jobs':[j for j in result['jobs'] if j['status'] in ('running','queued')]})
    print(code,result['status'],result.get('message'),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['cta','resume']);p.add_argument('--code');a=p.parse_args()
    if a.action=='cta':cta()
    else:resume(a.code)
