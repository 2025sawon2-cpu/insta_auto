"""Run with python -m tools.apply_reliability_update [--apply]."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json
from hotpost.studio_store import StudioStore

VERSION='stage-liveness-20261013-v1'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    settings=load_settings();path=settings.data_dir/'studio/studio.sqlite3'
    plans=[]
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        for tid,raw in db.execute('SELECT id,state FROM tasks'):
            state=json.loads(raw)
            if (state.get('status')=='completed' or state.get('daily_quality',{}).get('status')=='passed'
                    or state.get('reliability_policy')==VERSION):continue
            q=state.get('daily_quality',{});ac=state.get('source_acquisition',{})
            expired=q and q.get('pending')=='exhausted'  # preserve former stop; usage is not a limit
            transport=any(s.get('overlay_review_error')=='분석 프레임을 같은 해상도로 전달할 수 없습니다.'
                          and s.get('overlay_review_attempted_policy')=='codex-bounded-overlay-review-v2'
                          for s in state.get('sources',[]))
            plans.append({'id':tid,'quality_exhausted':bool(expired),'transport_recheck':transport,
                          'obsolete_hold':(ac.get('hold') or {}).get('reason') in {'time_limit','round_limit'}})
    if not args.apply:
        print(json.dumps({'apply':False,'tasks':plans},ensure_ascii=False));return
    root=settings.data_dir/('reliability-applied-'+datetime.now().strftime('%Y%m%d-%H%M%S'));root.mkdir()
    with sqlite3.connect(path) as source,sqlite3.connect(root/'studio-before.sqlite3') as target:source.backup(target)
    store=StudioStore(settings.data_dir/'studio')
    for plan in plans:
        def apply(state,db):
            state['reliability_policy']=VERSION
            q=state.get('daily_quality',{});ac=state.setdefault('source_acquisition',{})
            if q:
                from hotpost.quality_progress import ensure
                ensure(state)
            if plan['quality_exhausted']:
                q.update(status='needs_attention',pending='exhausted')
                state.update(status='attention',message='자동 품질 보완 누적 한도 소진 · 결과와 검토 기록 보존')
                state.get('automation',{}).update(active=False)
                db.execute("UPDATE jobs SET status='paused' WHERE task_id=? AND status IN ('queued','running') AND kind IN ('quality_review','quality_reedit','refresh_sources','rewrite','edit','collect_sources')",(state['id'],))
            elif plan['transport_recheck'] or plan['obsolete_hold']:
                if ac.get('hold'):ac.setdefault('hold_history',[]).append(ac.pop('hold'))
                if plan['transport_recheck']:
                    # The new transport policy is a real new review input; retain lifetime rounds/time.
                    ac['no_progress_rounds']=0
                    state['source_search']={'status':'queued','message':'전송 정책 수정 후 기존 파일 검토 재개','progress':0}
                db.execute("UPDATE jobs SET status='queued' WHERE task_id=? AND kind='collect_sources' AND status='paused'",(state['id'],))
            store.event(db,state['id'],'reliability_policy_applied',plan)
        store.change(plan['id'],apply)
    _atomic_json(root/'application.json',{'policy':VERSION,'tasks':plans,'preserved_outputs':True})
    print(json.dumps({'root':str(root.resolve()),'updated':len(plans),
        'quality_exhausted':sum(p['quality_exhausted'] for p in plans),'transport_rechecks':sum(p['transport_recheck'] for p in plans)},ensure_ascii=False))


if __name__=='__main__':main()
