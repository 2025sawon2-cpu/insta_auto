"""Review explicitly named saved clips through the normal source gates only."""
import argparse,copy,json,time
from pathlib import Path
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.source_quality import editing_ready,sha256_file
from hotpost.editing_adapter import _atomic_json

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--code',required=True)
    parser.add_argument('--source',required=True,nargs='+');args=parser.parse_args()
    studio=Studio(load_settings(),workers=False)
    state=next(t for t in studio.store.list() if t['shortcode']==args.code)
    assert state.get('automation',{}).get('selection_date_kst')=='2026-10-12'
    assert not any(j['status'] in ('running','queued') for j in studio.store.jobs(state['id']))
    selected=[copy.deepcopy(s) for s in state['sources'] if s['id'] in args.source]
    assert {s['id'] for s in selected}==set(args.source)
    for source in selected:
        assert source['id'].startswith('focused-') and not editing_ready(source)
        assert sha256_file(Path(source['path']))==source['sha256']
        assert not (source.get('manual_usage_review') or {}).get('editing_eligible') is False
    job={'id':'explicit-local-review-'+str(time.time_ns()),'kind':'refresh_sources'}
    reviewed,completion=studio._review_source_records(state,job,selected,
        lambda message,pct:print(message,pct,flush=True))
    assert completion is None
    path=Path('data/source-recovery-20261012-v1')/args.code/(job['id']+'.json')
    _atomic_json(path,{'at':time.time(),'sources':reviewed,'network_requests_for_sources':False,
        'normal_visual_gates':True,'automatic_editing_resumed':False})
    def accept(current,db):
        assert not db.execute("select 1 from jobs where task_id=? and status in ('running','queued')",(current['id'],)).fetchone()
        by_id={s['id']:s for s in reviewed}
        for index,source in enumerate(current['sources']):
            if source['id'] not in by_id:continue
            assert source['sha256']==by_id[source['id']]['sha256']
            assert not (source.get('manual_usage_review') or {}).get('editing_eligible') is False
            current['sources'][index]=by_id[source['id']]
        studio.store.event(db,current['id'],'explicit_saved_scene_review',{'receipt':str(path.resolve()),
            'sources':[{ 'id':s['id'],'ready':editing_ready(s)} for s in reviewed],
            'no_platform_navigation':True,'automatic_editing_resumed':False})
    studio.store.change(state['id'],accept)
    print(json.dumps({'receipt':str(path.resolve()),'sources':[{ 'id':s['id'],'ready':editing_ready(s)} for s in reviewed]},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
