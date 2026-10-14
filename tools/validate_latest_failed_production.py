"""One explicitly requested production; preserve automatic repair caps and old outputs.

Run as a module with --stage preflight|review-sources|collect|render|review|commit.
Each stage has a durable receipt. It never starts an automatic repair loop.
"""
import argparse
import copy
from dataclasses import replace
import json
import sqlite3
import time
from pathlib import Path

from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json
from hotpost.model_service import ModelServiceUnavailable
from hotpost.scene_requirements import assess, coverage_current, input_signature, merge_sources
from hotpost.source_quality import sha256_file
from hotpost.studio import Studio
from hotpost.studio_store import uid
from hotpost.source_browser_runtime import BrowserBusy


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--stage',required=True,choices=('preflight','revalidate-policy','review-sources','review-focused','collect','collect-precision','render','review','commit','account-attempts','persist-source-status'))
    args=parser.parse_args();settings=load_settings();studio=Studio(settings,workers=False)
    root=settings.data_dir/'reliability-validation-20261013-mat';root.mkdir(exist_ok=True)
    receipt_path=root/'receipt.json';state_path=root/'state-input.json'
    if not receipt_path.is_file():
        with studio.store.connect() as db:
            row=db.execute("SELECT task_id,id,error,updated FROM jobs WHERE status='failed' ORDER BY updated DESC LIMIT 1").fetchone()
        if not row:raise ValueError('No failed production exists')
        state=studio.store.get(row['task_id'])
        if state['shortcode']!='DeWWWOeDhGk':raise ValueError('Latest failed target changed; reassess selection')
        if any(j['status']=='running' for j in studio.store.jobs(state['id'])):raise ValueError('Target already running')
        _atomic_json(root/'state-before.json',state)
        hashes={}
        for record in [*state['sources'],*state['voices'],*state['scripts'],*state['edits']]:
            for key in ('path','preview_path','plan_path','export_path'):
                path=Path(record.get(key) or '__missing__')
                if path.is_file():hashes[str(path.resolve())]=sha256_file(path)
        _atomic_json(root/'preserved-hashes.json',hashes)
        state=copy.deepcopy(state)
        state.pop('reviewed_scene_rules',None)
        receipt={'id':uid('validation-'),'task_id':state['id'],'shortcode':state['shortcode'],
            'selected_failed_job':row['id'],'authorization':'User explicitly requested latest failed hot-post production with a guard agent on 2026-10-13',
            'manual_render_limit':1,'manual_render_count':0,'source_no_progress':0,'source_attempts':0,
            'original_repair_round':state.get('daily_quality',{}).get('repair_round',0),
            'original_max_repairs':state.get('daily_quality',{}).get('max_repairs'),
            'script_id':state['script_id'],'voice_id':state['voice_id'],'stage_history':[],
            'input_change':'Remove failed manually pinned scene choices in execution copy; narration and originals preserved',
            'created':time.time(),'status':'prepared'}
        _atomic_json(state_path,state);_atomic_json(receipt_path,receipt)
    receipt=json.loads(receipt_path.read_text('utf-8'));state=json.loads(state_path.read_text('utf-8'))
    if state['script_id']!=receipt['script_id'] or state['voice_id']!=receipt['voice_id']:raise ValueError('Narration changed')
    stage=args.stage
    if stage=='persist-source-status':
        if receipt['status']=='running':raise ValueError('Healthy active stage has not finished')
        hashes=json.loads((root/'preserved-hashes.json').read_text('utf-8'))
        if any(not Path(p).is_file() or sha256_file(Path(p))!=sha for p,sha in hashes.items()):raise ValueError('An old artifact changed')
        def persist_sources(current,db):
            if current['script_id']!=receipt['script_id'] or current['voice_id']!=receipt['voice_id']:raise ValueError('Narration selection changed')
            q=current['daily_quality']
            if q['repair_round']!=receipt['original_repair_round'] or q['max_repairs']!=receipt['original_max_repairs']:raise ValueError('Automatic cap changed')
            current['sources']=merge_sources(current['sources'],state['sources'])
            current['automation']['active']=False
            current['source_search']={'status':'done','progress':100,'scene_wait':not coverage_current(state),
                'message':'실제 소스 검토 완료 · 필요한 삽입·틈새 차단 장면 미확보' if not coverage_current(state) else '실제 소스 검토 완료 · 필요한 장면 확보'}
            entry={'id':receipt['id'],'receipt_path':str(receipt_path.resolve()),'render_count':receipt['manual_render_count'],
                   'source_no_progress':receipt['source_no_progress'],'scenes_ready':coverage_current(state),
                   'coverage_path':str((root/'scene-coverage.json').resolve())}
            entries=q.setdefault('manual_validations',[])
            old=next((r for r in entries if r['id']==receipt['id']),None)
            if old:old.update(entry)
            else:entries.append(entry)
            current.update(status='attention',message=current['source_search']['message'],error='')
            studio.store.event(db,current['id'],'manual_validation_source_review_completed',entry)
        studio.store.change(state['id'],persist_sources)
        print(json.dumps({'status':'saved','source_count':len(state['sources']),'render_count':receipt['manual_render_count']},ensure_ascii=False));return
    if stage=='account-attempts':
        if receipt['status']=='running':raise ValueError('Healthy active stage must finish before reconciliation')
        ledger_path=root/'attempt-ledger.json'
        ledger=json.loads(ledger_path.read_text('utf-8')) if ledger_path.is_file() else {'attempts':[]}
        known={r['id'] for r in ledger['attempts']}
        for r in receipt['stage_history']:
            if r['stage'] not in ('preflight','revalidate-policy','collect','collect-precision','review-sources','review-focused') or r['status']!='completed':continue
            if r['identity'] in known:continue
            improved=bool(r.get('scenes_ready')) or bool(r.get('scene_gain'))
            ledger['attempts'].append({'id':r['identity'],'stage':r['stage'],'completed':r['finished'],'improved':improved})
            known.add(r['identity'])
        local_path=root/'local-candidate/reviewed-source.json'
        if local_path.is_file():state['sources']=merge_sources(state['sources'],[json.loads(local_path.read_text('utf-8'))])
        counter=0
        ledger['attempts'].sort(key=lambda r:r['completed'])
        for r in ledger['attempts']:counter=0 if r['improved'] else counter+1
        ledger.update(no_progress_completed_attempts=counter,counted_sources_individually=False,updated=time.time())
        receipt['source_no_progress']=counter
        _atomic_json(ledger_path,ledger);_atomic_json(receipt_path,receipt);_atomic_json(state_path,state)
        print(json.dumps({'completed_attempts':len(ledger['attempts']),'no_progress':counter,
                          'scenes_ready':coverage_current(state)},ensure_ascii=False));return
    if receipt['status']=='running':raise ValueError('Another healthy validation stage is still running')
    if stage in ('collect','review-sources'):
        if receipt['source_no_progress']>=settings.source_no_progress_rounds:raise ValueError('No progress limit reached; new evidence required')
    if stage=='collect-precision':
        from hotpost.source_queries import grounded_tiktok_noun_phrase
        query='L자주방매트';quote=state['original_text']
        if grounded_tiktok_noun_phrase(query,quote)!=query:raise ValueError('Necessary shape modifier is not grounded in original reference')
        change=receipt.get('condition_changed_once')
        if not change:
            change={'query':query,'evidence_quote':quote,'previous_completed_no_progress':receipt['source_no_progress'],
                    'reason':'Original L-shape modifier was omitted by noun grammar and operator query propagation; actual policy correction',
                    'guard_review':'production_guard approved one changed-condition attempt, preserving prior history',
                    'max_candidates':6,'created':time.time(),'used':False}
            receipt['condition_changed_once']=change;_atomic_json(receipt_path,receipt)
        if change['used']:raise ValueError('Changed-condition one-off attempt already completed; no automatic replay')
        settings=replace(settings,source_max_candidates=6,source_max_downloads=6,source_max_probe_downloads=6,
                         source_max_attempts=6,source_candidates_per_platform=6,source_queries_per_platform=1,
                         source_refine_max_candidates=0)
        studio.settings=settings
        acquisition=state.setdefault('source_acquisition',{})
        acquisition['urls']=list(dict.fromkeys([*acquisition.get('urls',[]),
            *(s.get('origin_url') for s in state['sources'] if s.get('origin_url'))]))
    if stage=='review-focused':
        evidence_path=settings.data_dir/'reliability-guard-20261013/precision-window-4-to-7-1791828202/diagnostic-evidence.json'
        evidence=json.loads(evidence_path.read_text('utf-8'))
        parent=Path(evidence['source_path'])
        if sha256_file(parent)!=evidence['source_sha256']:raise ValueError('Actual source diagnostic changed')
        if any(sha256_file(Path(f['path']))!=f['sha256'] for f in evidence['frames']):raise ValueError('Diagnostic frames changed')
        focused=receipt.get('focused_window_once')
        if not focused:
            focused={'parent_path':str(parent),'parent_sha256':evidence['source_sha256'],
                     'original_interval':{'start':4.,'end':7.3},'diagnostic_path':str(evidence_path.resolve()),
                     'diagnostic_sha256':sha256_file(evidence_path),'previous_no_progress':receipt['source_no_progress'],
                     'reason':'New actual installation evidence lies outside previously reviewed windows',
                     'guard_review':'production_guard approved one new local interval review; no external search',
                     'created':time.time(),'used':False}
            receipt['focused_window_once']=focused;_atomic_json(receipt_path,receipt)
        if focused['used']:raise ValueError('Focused new interval already reviewed; same-input replay forbidden')
    if stage=='revalidate-policy':
        from hotpost.scene_requirements import POLICY
        live_before=studio.store.get(state['id'])
        validation_binding={key:live_before.get(key) for key in ('script_id','voice_id','edit_id')}
        if any(validation_binding[key]!=state.get(key) for key in validation_binding):
            raise ValueError('Current narration/draft differs from the validation input')
        validation_feedback=copy.deepcopy(live_before.get('daily_quality',{}).get('feedback'))
        if validation_feedback!=state.get('daily_quality',{}).get('feedback'):
            raise ValueError('Current quality feedback differs from the validation input')
        if live_before.get('automation',{}).get('active'):
            raise ValueError('Automatic production became active; do not overwrite its state')
        if receipt['manual_render_count']!=1 or receipt.get('quality_passed') is not False:
            raise ValueError('Actual failed quality review must exist before changed-policy validation')
        before=json.loads((root/'scene-coverage-before-manual-qa.json').read_text('utf-8'))
        if before.get('policy')==POLICY:raise ValueError('No meaningful coverage policy change to validate')
        receipt.setdefault('changed_policy_recheck',{'previous_policy':before.get('policy'),'policy':POLICY,
            'reason':'Actual narration/product-part relationship and decisive selected-frame evidence added after observed quality failure',
            'external_searches_allowed':False,'additional_renders_allowed':False,'used':False,'created':time.time()})
        if receipt['changed_policy_recheck']['used']:raise ValueError('Changed-policy recheck already completed')
        _atomic_json(receipt_path,receipt)
    identity=stage if stage not in ('collect','review-sources') else stage+':'+str(receipt['source_attempts'])
    previous=next((r for r in reversed(receipt['stage_history']) if r['identity']==identity),None)
    if previous and previous['status']=='completed':
        print(json.dumps({'stage':stage,'status':'already_completed','root':str(root.resolve())}));return
    signature=input_signature(state)
    if previous and previous['status']=='failed' and previous.get('input_signature')==signature:
        raise ValueError('Confirmed same-input stage failure must not be repeated')
    if previous and previous['status']=='model_wait':
        if time.time()<previous['retry_at']:raise ValueError('Shared model recovery wait not finished')
        if previous.get('service_failures',0)>=3:raise ValueError('Actual service retry limit reached')
    if previous and previous['status']=='browser_wait' and time.time()<previous['retry_at']:
        raise ValueError('Existing collector browser wait not finished')
    run={'identity':identity,'stage':stage,'status':'running','input_signature':signature,'started':time.time(),
         'service_failures':previous.get('service_failures',0) if previous else 0}
    receipt['stage_history'].append(run);receipt.update(status='running',stage=stage)
    _atomic_json(receipt_path,receipt)
    checkpoint_path=root/(identity.replace(':','-')+'-checkpoint.json')
    checkpoint=json.loads(checkpoint_path.read_text('utf-8')) if checkpoint_path.is_file() else {}
    original_checkpoint=studio.store.checkpoint
    def checkpoint_write(job_id,value):
        if job_id==receipt['id']:_atomic_json(checkpoint_path,value)
        else:original_checkpoint(job_id,value)
    studio.store.checkpoint=checkpoint_write
    job={'id':receipt['id'],'kind':'manual_validation','checkpoint':checkpoint,
         'payload':{'script_id':state['script_id'],'voice_id':state['voice_id'],'edit_id':state['edit_id']}}
    print(json.dumps({'stage':stage,'status':'started','root':str(root.resolve()),'job_id':receipt['id']}),flush=True)
    try:
        if stage=='preflight':
            coverage=assess(settings,state)
            state['daily_quality']['scene_requirements']=coverage
            _atomic_json(root/'scene-coverage.json',coverage)
            run['scenes_ready']=coverage_current(state)
            if not run['scenes_ready']:receipt['source_no_progress']+=1
        elif stage=='revalidate-policy':
            prior=sum(r.get('covered') is True for r in state['daily_quality'].get('scene_requirements',{}).get('requirements',[]))
            coverage=assess(settings,state);state['daily_quality']['scene_requirements']=coverage
            _atomic_json(root/'scene-coverage-new-policy.json',coverage)
            run['scenes_ready']=coverage_current(state)
            current=sum(r.get('covered') is True for r in coverage.get('requirements',[]))
            run['scene_gain']=current>prior
            receipt['source_no_progress']=0 if coverage['ready'] or run['scene_gain'] else receipt['source_no_progress']+1
            receipt['changed_policy_recheck'].update(used=True,completed=time.time(),scenes_ready=run['scenes_ready'],
                coverage_path=str((root/'scene-coverage-new-policy.json').resolve()))
            def save_new_policy(current,db):
                if any(current.get(key)!=value for key,value in validation_binding.items()):
                    raise ValueError('Current narration/draft changed during policy validation')
                q=current['daily_quality']
                if q.get('feedback')!=validation_feedback or current.get('automation',{}).get('active'):
                    raise ValueError('Feedback/automation changed during policy validation')
                if q.get('repair_round')!=receipt['original_repair_round'] or q.get('max_repairs')!=receipt['original_max_repairs']:
                    raise ValueError('Automatic repair limits changed during policy validation')
                current['daily_quality']['scene_requirements']=coverage
                entry=next(r for r in current['daily_quality']['manual_validations'] if r['id']==receipt['id'])
                entry.update(scenes_ready=run['scenes_ready'],source_no_progress=receipt['source_no_progress'],
                    new_policy_coverage_path=str((root/'scene-coverage-new-policy.json').resolve()))
                current['source_search']={'status':'done','progress':100,'scene_wait':not run['scenes_ready'],
                    'message':'새 규칙 검토 완료 · 대사·제품 관계에 맞는 증거 미확보' if not run['scenes_ready'] else '새 규칙 검토 완료 · 장면 근거 확보, 완성본 품질 보완 대기'}
                current['automation']['active']=False
                studio.store.event(db,current['id'],'manual_validation_changed_policy_checked',
                    {'id':receipt['id'],'scenes_ready':run['scenes_ready'],'policy':coverage['policy'],'render_count':1})
            studio.store.change(state['id'],save_new_policy)
        elif stage=='review-sources':
            reviewed,_=studio._review_source_records(state,job,copy.deepcopy(state['sources']),
                lambda message,pct:print(json.dumps({'message':message,'progress':pct},ensure_ascii=False),flush=True))
            state['sources']=merge_sources(state['sources'],reviewed)
            coverage=assess(settings,state);state['daily_quality']['scene_requirements']=coverage
            receipt['source_attempts']+=1
            prior=sum(r.get('covered') is True for r in json.loads(state_path.read_text('utf-8')).get('daily_quality',{}).get('scene_requirements',{}).get('requirements',[]))
            current=sum(r.get('covered') is True for r in coverage.get('requirements',[]))
            receipt['source_no_progress']=0 if coverage['ready'] or current>prior else receipt['source_no_progress']+1
            _atomic_json(root/'scene-coverage.json',coverage);run['scenes_ready']=coverage_current(state)
        elif stage=='review-focused':
            from hotpost.operation_progress import run_progress_command
            from hotpost.source_finder import probe_video, _executable
            output=root/'focused-installation';output.mkdir(exist_ok=True)
            candidate_path=output/'candidate.json'
            if candidate_path.is_file():
                candidate=json.loads(candidate_path.read_text('utf-8'))
                if sha256_file(Path(candidate['path']))!=candidate['sha256']:raise ValueError('Focused derivative changed')
            else:
                path=output/'installation-4-to-7-3.mp4'
                if path.exists():raise ValueError('Unreceipted derivative exists; do not overwrite diagnostic artifact')
                result=run_progress_command([str(_executable('ffmpeg')),'-nostdin','-v','error','-progress','pipe:1','-nostats',
                    '-ss','4','-i',focused['parent_path'],'-t','3.3','-map','0:v:0','-an',
                    '-c:v','libx264','-crf','18','-preset','fast','-movflags','+faststart',str(path)],
                    idle_seconds=60)
                if result.returncode:raise RuntimeError(result.stderr[-1200:])
                parent_record=next(s for s in state['sources'] if s['sha256']==focused['parent_sha256'])
                candidate=studio._source_records([path],state['source_search_manifest_path'])[0]
                candidate.update(id='focused-real-installation-4-to-7-3',original_sha256=focused['parent_sha256'],
                    original_interval=focused['original_interval'],origin_url=parent_record.get('origin_url'),
                    rights=parent_record.get('rights'),source_quality='unknown',blur_required=False,
                    relevance_review_required=True,presentation_review_required=True,editing_eligible=False,
                    video_meta=probe_video(path),local_candidate_reason=focused['reason'])
                _atomic_json(candidate_path,candidate)
                focused.update(derivative_path=str(path.resolve()),derivative_sha256=candidate['sha256'])
                _atomic_json(receipt_path,receipt)
            reviewed_path=output/'reviewed-source.json'
            if reviewed_path.is_file():
                saved_source=json.loads(reviewed_path.read_text('utf-8'))
                if saved_source['sha256']!=candidate['sha256'] or sha256_file(Path(saved_source['path']))!=candidate['sha256']:
                    raise ValueError('Completed focused review belongs to a different derivative')
                candidate=saved_source
            def focused_progress(message,pct):
                print(json.dumps({'message':message,'progress':pct},ensure_ascii=False),flush=True)
                studio.store.change(state['id'],lambda s,db:s.update(source_search={
                    'status':'running','progress':pct,'message':'새 설치 구간 검토 · '+message,
                    'scene_wait':True,'manual_validation_id':receipt['id']}))
            reviewed,_=studio._review_source_records(state,job,[candidate],focused_progress)
            _atomic_json(reviewed_path,reviewed[0])
            prior=sum(r.get('covered') is True for r in state['daily_quality'].get('scene_requirements',{}).get('requirements',[]))
            # Preserve the parent and its approved windows before prioritizing
            # the new derivative; URL deduplication is intentionally directional.
            merged=merge_sources(state['sources'],reviewed)
            new_hashes={s['sha256'] for s in reviewed}
            state['sources']=sorted(merged,key=lambda s:s['sha256'] not in new_hashes)
            coverage=assess(settings,state);state['daily_quality']['scene_requirements']=coverage
            current=sum(r.get('covered') is True for r in coverage.get('requirements',[]))
            run['scene_gain']=current>prior;run['scenes_ready']=coverage_current(state)
            receipt['source_no_progress']=0 if coverage['ready'] or run['scene_gain'] else receipt['source_no_progress']+1
            focused.update(used=True,completed=time.time(),scenes_ready=run['scenes_ready'])
            _atomic_json(root/'scene-coverage.json',coverage)
        elif stage in ('collect','collect-precision'):
            job['payload'].update(request=receipt['condition_changed_once']['query'] if stage=='collect-precision' else '주방 매트, L자 주방 매트',daily_quality_repair=True)
            result=studio._refresh_sources(state,job)
            _atomic_json(root/('collection-'+str(receipt['source_attempts'])+'.json'),result)
            prior=sum(r.get('covered') is True for r in state['daily_quality'].get('scene_requirements',{}).get('requirements',[]))
            state['sources']=merge_sources(state['sources'],result['sources'])
            coverage=result['scene_requirements'];state['daily_quality']['scene_requirements']=coverage
            state['source_search_manifest_path']=result['source_search_manifest_path']
            ac=state.setdefault('source_acquisition',{});ac.setdefault('queries',[]).extend(result.get('searches',[]))
            ac.setdefault('urls',[]).extend(result.get('attempted_urls',[]))
            ac['round']=ac.get('round',0)+1
            receipt['source_attempts']+=1
            current=sum(r.get('covered') is True for r in coverage.get('requirements',[]))
            run['scene_gain']=current>prior
            receipt['source_no_progress']=0 if coverage['ready'] or current>prior else receipt['source_no_progress']+1
            _atomic_json(root/'scene-coverage.json',coverage);run['scenes_ready']=coverage_current(state)
            if stage=='collect-precision':
                receipt['condition_changed_once'].update(used=True,completed=time.time(),searches=result.get('searches',[]),scene_gain=run['scene_gain'])
        elif stage=='render':
            if receipt['manual_render_count']>=1:raise ValueError('Explicit one-off render already consumed')
            if not coverage_current(state):raise ValueError('Required actual scenes not yet proven; rendering forbidden')
            edit=studio._edit(state,job)
            edit.update(manual_validation_id=receipt['id'],parent_id=state['edit_id'])
            _atomic_json(root/'manual-edit.json',edit)
            receipt['manual_render_count']=1
            state['edits'].append(edit);state['edit_id']=edit['id']
        elif stage=='review':
            if receipt['manual_render_count']!=1:raise ValueError('No new one-off render to review')
            job['id']=receipt['id']+'-review';job['payload']['edit_id']=state['edit_id']
            review=studio._quality_review(state,job)
            _atomic_json(root/'manual-quality-review.json',review)
            run['passed']=review['passed'];receipt['quality_passed']=review['passed']
        elif stage=='commit':
            if receipt['manual_render_count']!=1 or not (root/'manual-quality-review.json').is_file():raise ValueError('Render and review must finish first')
            hashes=json.loads((root/'preserved-hashes.json').read_text('utf-8'))
            if any(not Path(p).is_file() or sha256_file(Path(p))!=sha for p,sha in hashes.items()):raise ValueError('An old artifact changed')
            edit=json.loads((root/'manual-edit.json').read_text('utf-8'));review=json.loads((root/'manual-quality-review.json').read_text('utf-8'))
            prior_coverage=state.get('daily_quality',{}).get('scene_requirements',{})
            archive=root/'scene-coverage-before-manual-qa.json'
            if prior_coverage and not archive.is_file():_atomic_json(archive,prior_coverage)
            edit.update(quality_verified=review['passed'],quality_review_path=review['review_path'])
            if not review['passed']:edit['export_verified']=False
            _atomic_json(root/'manual-edit.json',edit)
            def commit(current,db):
                if current['script_id']!=receipt['script_id'] or current['voice_id']!=receipt['voice_id']:raise ValueError('Narration selection changed during validation')
                q=current['daily_quality']
                if q['repair_round']!=receipt['original_repair_round'] or q['max_repairs']!=receipt['original_max_repairs']:raise ValueError('Automatic repair history changed')
                current['sources']=merge_sources(current['sources'],state['sources'])
                if not any(e['id']==edit['id'] for e in current['edits']):current['edits'].append(edit)
                current['edit_id']=edit['id'];current['automation']['active']=False
                entry={'id':receipt['id'],'receipt_path':str(receipt_path.resolve()),'render_count':receipt['manual_render_count'],
                    'edit_id':edit['id'],'review_path':str((root/'manual-quality-review.json').resolve()),
                    'passed':review['passed'],'quality_passed':review['passed'],'scenes_ready':review['passed'],
                    'before_render_scenes_ready':prior_coverage.get('ready') is True,'coverage_path':str(archive.resolve())}
                entries=q.setdefault('manual_validations',[])
                existing=next((r for r in entries if r['id']==receipt['id']),None)
                if existing:existing.update(entry)
                else:entries.append(entry)
                reviews=q.setdefault('reviews',[])
                if not any(r.get('edit_id')==edit['id'] and r.get('render_sha256')==review['render_sha256'] for r in reviews):reviews.append(review)
                q.update(reviewed_edit_id=edit['id'],feedback=review.get('issues',[]))
                if review['passed']:
                    edit.update(quality_verified=True,quality_review_path=review['review_path'],export_verified=True,
                                export_path=edit['preview_path'],export_kind='web_render')
                    q.update(status='passed',reviewed_edit_id=edit['id']);q.pop('pending',None)
                    current.update(status='completed',message='사용자 요청 1회 재제작·실제품질 검토 완료',error='')
                else:
                    if q.get('scene_requirements'):q.setdefault('scene_requirement_history',[]).append(q['scene_requirements'])
                    q['scene_requirements']={'ready':False,'reason':'Actual manual quality feedback changed; prior scene approval is historical',
                        'previous_coverage_path':str(archive.resolve())}
                    q.update(status='manual_review_failed',manual_validation_hold='actual_quality_failed')
                    current['source_search']={'status':'done','progress':100,'scene_wait':True,
                        'message':'완성본 검토 미통과 · 새 대사·제품 구조에 맞는 장면 검토 필요'}
                    current.update(status='attention',message='사용자 요청 1회 재제작 완료 · 추가 품질 문제 기록',error='')
                studio.store.event(db,current['id'],'manual_validation_completed',{'id':receipt['id'],'passed':review['passed'],'automatic_cap_preserved':True})
            studio.store.change(state['id'],commit)
            state['daily_quality'].update(reviewed_edit_id=edit['id'],feedback=review.get('issues',[]))
            state['daily_quality'].setdefault('reviews',[]).append(review)
            if not review['passed']:
                state['daily_quality']['scene_requirements']={'ready':False,'reason':'Actual manual quality feedback changed',
                    'previous_coverage_path':str(archive.resolve())}
        run.update(status='completed',finished=time.time());receipt['status']='completed'
        _atomic_json(state_path,state);_atomic_json(receipt_path,receipt)
        print(json.dumps({'stage':stage,'status':'completed','scenes_ready':run.get('scenes_ready'),
                          'quality_passed':receipt.get('quality_passed'),'render_count':receipt['manual_render_count']},ensure_ascii=False),flush=True)
    except Exception as exc:
        run.update(status='failed',error=str(exc)[:1500],error_type=type(exc).__name__,finished=time.time())
        if isinstance(exc,ModelServiceUnavailable):
            run.update(status='model_wait',retry_at=exc.retry_at,
                       service_failures=run['service_failures']+int(exc.attempted))
        elif isinstance(exc,BrowserBusy):
            run.update(status='browser_wait',retry_at=time.time()+30)
        receipt['status']=run['status'];_atomic_json(receipt_path,receipt)
        raise


if __name__=='__main__':main()
