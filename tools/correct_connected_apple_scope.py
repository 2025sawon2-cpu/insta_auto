"""Append one evidence-bound non-submission correction, without rewriting receipts."""
import argparse
import copy
import hashlib
import json
import sqlite3
import time
from pathlib import Path

from hotpost.source_attempts import search_execution
from hotpost.source_search.strategy import search_key
from hotpost.studio_store import StudioStore, Conflict

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/rework-top-three-20261014'
TASK='work-8013247e50624ae6'


def sha(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        before=json.loads(db.execute('select state from tasks where id=?',(TASK,)).fetchone()[0])
        if db.execute("select 1 from jobs where status in ('queued','running')").fetchone():
            raise Conflict('Queue must be idle')
    if not before.get('automation',{}).get('paused_by_user'):raise Conflict('Target must be paused')
    acquisition=before['source_acquisition'];proof=[]
    for row in acquisition.get('rounds',[]):
        path=Path(row['manifest_path']);data=json.loads(path.read_text('utf-8'))
        for index,audit in enumerate(data.get('search_audit',[])):
            if (data.get('shortcode')=='Deb2jkPxQ43' and audit.get('provider')=='tiktok'
                    and audit.get('query')=='사과' and audit.get('stage')=='locate_search_input'
                    and not audit.get('requests') and audit.get('visible_search_controls')==3
                    and audit.get('status')=='error' and audit.get('error')=='TimeoutError'):
                proof.append((path,index,audit))
    if len(proof)!=1:raise Conflict('Exactly one immutable non-submission receipt required')
    path,index,audit=proof[0];file_sha=hashlib.sha256(path.read_bytes()).hexdigest();identity=search_key(audit)
    matches=[r for r in acquisition.get('queries',[]) if search_key(r)==identity]
    if len(matches)!=1:raise Conflict('Exactly one affected historical query scope required')
    original=copy.deepcopy(matches[0]);already=original.get('execution',{}).get('resolution')=='confirmed_not_submitted'
    detail={'at':time.time(),'task_id':TASK,'scope':list(identity),'manifest_path':str(path),
            'manifest_sha256':file_sha,'audit_index':index,'audit':audit,'original_history_row':original,
            'original_history_row_sha256':sha(original),'resolution':'confirmed_not_submitted'}
    corrected={**original,'stage':audit['stage'],'execution':{'query_submitted':False,'query_url_matched':False,
        'resolution':'confirmed_not_submitted','correction_manifest_sha256':file_sha,'correction_audit_index':index}}
    if not already and args.apply:
        store=StudioStore(ROOT/'data/studio')
        def change(state,db):
            if state!=before or db.execute("select 1 from jobs where status in ('queued','running')").fetchone():
                raise Conflict('State or queue changed')
            rows=state['source_acquisition']['queries']
            for position,row in enumerate(rows):
                if search_key(row)==identity:
                    if row!=original:raise Conflict('Affected scope changed')
                    rows[position]=corrected
            state.setdefault('source_execution_corrections',[]).append(detail)
            store.event(db,TASK,'confirmed_search_non_submission_correction',detail)
        after=store.change(TASK,change,before['revision'])
        retained=copy.deepcopy(after);retained['source_acquisition']['queries']=copy.deepcopy(before['source_acquisition']['queries'])
        for field in ('source_execution_corrections','revision','updated'):retained.pop(field,None)
        saved=copy.deepcopy(before)
        for field in ('source_execution_corrections','revision','updated'):saved.pop(field,None)
        if retained!=saved:raise AssertionError('Unrelated production state changed')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=file_sha:raise AssertionError('Original manifest changed')
    result={'applied':args.apply,'already_corrected':already,'detail':detail,
            'corrected_execution':search_execution(corrected),'original_receipt_preserved':True}
    if args.apply:(OUT/'apple-scope-correction.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='detail'},ensure_ascii=False))


if __name__=='__main__':main()
