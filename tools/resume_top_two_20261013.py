"""Continue today's existing top two; keep scripts, voices, caps and attempt history."""
import argparse
import json
import time
from pathlib import Path

from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json
from hotpost.source_quality import sha256_file
from hotpost.source_queries import grounded_tiktok_noun_phrase
from hotpost.studio import Studio
from hotpost.studio_automation import all_today


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('stage',choices=('prepare','queue','status'))
    args=parser.parse_args();settings=load_settings();studio=Studio(settings,workers=False)
    root=settings.data_dir/'top-two-production-20261013';root.mkdir(exist_ok=True)
    path=root/'receipt.json'
    if args.stage=='prepare':
        if path.exists():raise ValueError('Existing request receipt; do not duplicate')
        report=json.loads(settings.report_path.read_text('utf-8'));top=all_today(report,settings)[:2]
        assert [r['shortcode'] for r in top]==['DeXvBHjT5U_','DeXut7fTAxb']
        tasks={t['shortcode']:t for t in studio.store.list()};posts={p['shortcode']:p for p in report['posts']}
        records=[]
        for rank,query in zip(top,['얼룩 제거제','아디다스 폴로 니트']):
            state=tasks[rank['shortcode']];quote=state['original_text']+' '+posts[state['shortcode']]['caption']
            assert grounded_tiktok_noun_phrase(query,quote)==query
            _atomic_json(root/(state['shortcode']+'-before.json'),state)
            records.append({'task_id':state['id'],'shortcode':state['shortcode'],'rank':rank['rank'],'rank_score':rank['rank_score'],
                'query':query,'query_evidence':quote,'script_id':state['script_id'],'voice_id':state['voice_id'],
                'original_source_round':state['source_acquisition']['round'],
                'original_bounded_rounds':state['source_acquisition']['bounded_rounds'],
                'original_no_progress_rounds':state['source_acquisition']['no_progress_rounds'],
                'repair_round':state['daily_quality']['repair_round'],'max_repairs':state['daily_quality']['max_repairs'],
                'preserved_files':{r['path']:sha256_file(Path(r['path'])) for r in state['voices']},
                'queued':False})
        _atomic_json(path,{'authorized':'User requested top two production after rule calibration on 2026-10-13',
            'created':time.time(),'collection_already_completed':True,'collection_run_id':6,
            'collection_accounts_ok':39,'collection_accounts_failed':0,'collection_posts_processed':52,
            'report_generated_at_kst':report['generated_at_kst'],'tasks':records})
        print(json.dumps({'prepared':True,'targets':[r['shortcode'] for r in records]},ensure_ascii=False));return
    receipt=json.loads(path.read_text('utf-8'))
    if args.stage=='queue':
        for record in receipt['tasks']:
            if record['queued']:continue
            def bind(state,db):
                if state['script_id']!=record['script_id'] or state['voice_id']!=record['voice_id']:
                    raise ValueError('Selected narration changed; re-evaluate rather than overwrite')
                for p,sha in record['preserved_files'].items():
                    if sha256_file(Path(p))!=sha:raise ValueError('Existing personal voice changed')
                state['source_search_brief']=record['query']
                change={'at':time.time(),'reason':'Reviewed noun dictionary expanded for actual current product; new supported search condition',
                    'query':record['query'],'evidence':record['query_evidence'],'previous_source_round':state['source_acquisition']['round'],
                    'previous_no_progress_rounds':state['source_acquisition']['no_progress_rounds']}
                state.setdefault('source_search_condition_changes',[]).append(change)
                studio.store.event(db,state['id'],'user_top_two_condition_changed',change)
            studio.store.change(record['task_id'],bind)
            result=studio.action(record['task_id'],'resume-auto',{})
            record.update(queued=True,queued_at=time.time())
            _atomic_json(path,receipt)
            print(json.dumps({'task_id':record['task_id'],'code':record['shortcode'],'status':result['status'],
                'message':result['message'],'query':record['query'],'previous_no_progress_preserved':result['source_acquisition']['no_progress_rounds']},ensure_ascii=False),flush=True)
        return
    status=[]
    for record in receipt['tasks']:
        state=studio.store.get(record['task_id'])
        row={'task_id':state['id'],'code':state['shortcode'],'rank':record['rank'],'status':state['status'],
            'message':state.get('message'),'error':state.get('error'),'source_search':state.get('source_search'),
            'sources':len(state['sources']),'source_goal':state.get('source_goal'),
            'scripts':len(state['scripts']),'voices':len(state['voices']),'edits':len(state['edits']),
            'script_id':state['script_id'],'voice_id':state['voice_id'],'edit_id':state['edit_id'],
            'daily_quality':state.get('daily_quality'),'source_acquisition':{k:state.get('source_acquisition',{}).get(k)
                for k in ('round','bounded_rounds','no_progress_rounds','hold')},
            'jobs':[{k:j.get(k) for k in ('id','kind','status','error','updated')} for j in studio.store.jobs(state['id'])[:5]]}
        status.append(row)
    _atomic_json(root/'status.json',{'checked_at':time.time(),'tasks':status})
    print(json.dumps(status,ensure_ascii=False))


if __name__=='__main__':main()
