"""Select every newly detected hot video and hand it off to the studio."""
from __future__ import annotations

from .studio_store import change_claimed

import hashlib
import json
import re
import subprocess
import sys
import time
from .daily_hot import daily_state, date_key
from .collection_window import in_collection_window


def selection_key(run_key, now=None):
    return f'{run_key}:daily-hot-24h-v3:{date_key(time.time() if now is None else now)}'


def all_today(report, settings, now=None):
    now = time.time() if now is None else now
    if report.get('is_sample') or now - report.get('generated_at', 0) > settings.metric_freshness_hours * 3600:
        return []
    rows = [p for p in report.get('posts', []) if p.get('kind') in ('reel', 'video')
            and daily_state(p, now)['hot_today']
            and in_collection_window(p.get('taken_at', 0), report.get('collection_started_at', report['generated_at']))]
    rows.sort(key=lambda p: (p.get('rank_score', 0), p.get('taken_at', 0)), reverse=True)
    result = []
    for rank, p in enumerate(rows, 1):
        observed = (p.get('assessment') or {}).get('last_observed_at') or 0
        eligible = (p.get('metric_status', {}).get('views') == 'observed'
                    and p.get('views') is not None
                    and 0 <= now - observed <= settings.metric_freshness_hours * 3600)
        result.append({'shortcode':p['shortcode'], 'rank':rank, 'rank_score':p.get('rank_score'),
                       'assessment':p.get('assessment', {}), 'eligible':True, 'reason':'',
                       'metric_warning':'' if eligible else '정확한 최신 조회수 미확인'})
    return result


def top_two(report, settings, now=None):
    """Compatibility entry point; the current policy selects all today's videos."""
    return all_today(report, settings, now)


def enqueue_top(settings, report, run_key):
    if not settings.studio_auto_top_enabled or report.get('is_sample'):
        return []
    if settings.studio_auto_start_date_kst and date_key(time.time()) < settings.studio_auto_start_date_kst:
        return []
    from .studio import Studio
    studio = Studio(settings, workers=False)
    daily_run_key = selection_key(run_key)
    limit = max(0, int(settings.studio_auto_top_limit))
    candidates = all_today(report, settings)
    if limit:
        candidates = candidates[:limit]
    selection = studio.store.freeze_selection(daily_run_key, candidates)
    # A saved wider selection is historical evidence, not permission to start
    # work outside the current limit. Never backfill a stopped/completed rank.
    if limit:
        selection = [row for row in selection if row['rank'] <= limit]
    results = []
    for row in selection:
        if not row['eligible']:
            results.append({**row, 'created':False, 'outcome':'skipped'})
            continue
        task, created = studio.create(row['shortcode'], automation={
            **row, 'active':True, 'protocol':2, 'run_key':str(run_key), 'selected_at':time.time(),
            'selection_date_kst':date_key(time.time()),
            'policy':'수집 시작 전 24시간 게시된 오늘 최초 감지 핫 영상 · 급상승순 제작', 'stage':'prepare',
            'selection_mode':'automatic', 'reviewed_by_user':False,
            'finish_selected_batch':True,
        }, with_created=True)
        from .studio_intake import task_status
        status = task_status(task)
        results.append({**row, 'task_id':task['id'], 'created':created,
                        'outcome':'created' if created else 'existing', **status})
    return results


def intake_log(rows):
    created = sum(bool(r.get('created')) for r in rows)
    existing = sum(r.get('outcome') == 'existing' for r in rows)
    skipped = sum(r.get('outcome') == 'skipped' for r in rows)
    blocked = sum(r.get('state') == 'blocked' for r in rows)
    return f'제작실 자동 선정 결과: 신규 등록 {created}개 · 기존 작업 {existing}개 · 선정 보류 {skipped}개 (연결된 작업 중 진행 불가 {blocked}개)'


def enqueue_latest(settings):
    from .storage import Storage
    store = Storage(settings.db_path)
    try:
        run = store.last_run()
        account_count = len(store.managed_accounts())
    finally:
        store.close()
    if not run or not run.get('finished_at') or not run.get('accounts_ok') or run.get('source') == 'demo':
        return []
    if run.get('stop_reason') or run.get('accounts_skipped'):
        return []
    # A manual --only run must not trigger selection from a partial report.
    if sum(run.get(k, 0) or 0 for k in ('accounts_ok', 'accounts_failed', 'accounts_skipped')) != account_count:
        return []
    report = json.loads(settings.report_path.read_text(encoding='utf-8'))
    if report.get('generated_at', 0) < run['finished_at']:
        return []
    return enqueue_top(settings, report, run['id'])


def ensure_worker(settings):
    """The studio worker lease makes a duplicate launcher harmless."""
    from .config import ROOT
    with (settings.data_dir / 'studio-worker.log').open('a', encoding='utf-8') as log:
        subprocess.Popen([sys.executable, '-X', 'utf8', '-u', '-m', 'hotpost.studio_automation'],
                         cwd=ROOT, stdout=log, stderr=log,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def rewrite(studio, state, job):
    job.setdefault('task_id', state['id'])
    from .studio_adapter import StudioAdapter
    from .editing_adapter import _atomic_json
    adapter = StudioAdapter(studio.settings)
    checkpoint = job['checkpoint']
    request_id = checkpoint.get('studio_job_id')
    if not request_id:
        from pathlib import Path
        from .reference_context import post_caption, reference_kind
        manifest_path = Path(state.get('source_search_manifest_path') or state.get('manifest_path', ''))
        manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.is_file() else {}
        # The preparation manifest may contain only the display title/CTA.
        # Subject resolution needs the full source caption, like the writer.
        manifest = _resolve_rewrite_manifest(studio, state, {**manifest, 'caption':post_caption(studio.settings,state) or manifest.get('caption','')})
        product = state.get('product_override') or identify_subject(manifest, state['original_text'], state.get('product') or state['title'])
        change_claimed(studio.store, job, lambda s, db: s.update(product=product))
        # Benchmark the original narration, never replace its topic with B-roll.
        rewrite_video = state['reference_video']
        remote = adapter.submit(state['id'], Path(rewrite_video), state.get('reviewed_original_text', state['original_text']),
                                {'product':product,
                                 'product_url':state.get('product_url_override',''),
                                 'evidence_mode':'benchmark',
                                 'reference_caption':post_caption(studio.settings,state),
                                 'reference_kind':reference_kind(state),
                                 'reference_visual_evidence':(state.get('reference_text_evidence') or {}).get('evidence'),
                                 'notes':'공통 대본 계약으로 자동 제작합니다. '
                                         + state.get('rewrite_instructions',''),
                                 'generation_key':checkpoint.get('generation_key',job['payload'].get('generation_key',''))})
        request_id = remote['id']
        checkpoint['studio_job_id'] = request_id
        studio.store.checkpoint(job, checkpoint)
        change_claimed(studio.store, job, lambda s, db: s.update(studio_job_id=request_id))
    from .operation_progress import ProgressWatch
    from .model_service import ModelServiceUnavailable
    watch=ProgressWatch(studio.settings.studio_timeout,'대본 작업 응답')
    seen=set()
    while True:
        remote = adapter.get(request_id)
        if checkpoint.get('retry_requested'):
            if remote['state'] in ('failed', 'cancelled', 'interrupted'):
                remote = adapter.retry(state['id'], request_id)
                request_id = remote['id']
                checkpoint['studio_job_id'] = request_id
                change_claimed(studio.store, job, lambda s, db: s.update(studio_job_id=request_id))
            checkpoint.pop('retry_requested', None)
            studio.store.checkpoint(job, checkpoint)
        if remote['state'] == 'completed':
            if job.get('claim_token'):
                studio.store.assert_owned(job)
            _atomic_json(studio.folder(state['id']) / 'script-candidates.json', remote['result'])
            change_claimed(studio.store, job, lambda s, db: s.update(
                script_candidates=remote['result']['scripts'],
                benchmark_analysis=remote['result'].get('benchmark',{}).get('analysis',{})))
            candidates = remote['result'].get('scripts', [])
            valid = []
            reference_hash = hashlib.sha256(state.get('reviewed_original_text', state['original_text']).encode()).hexdigest()
            for index, item in enumerate(candidates):
                text = item.get('text', '').strip()
                review = item.get('rewrite_review') or {}
                if (text and len(text) <= 3000
                        and review.get('script_sha256') == hashlib.sha256(item['text'].encode()).hexdigest()
                        and review.get('reference_sha256') == reference_hash):
                    valid.append((index, item))
            if not valid:
                reasons = list(dict.fromkeys(reason for item in candidates
                    for reason in (item.get('rewrite_review') or {}).get('reasons', [])))
                raise ValueError('사용 가능한 재가공 대본 또는 일치하는 버전 정보가 없습니다. '
                                 + ' / '.join(reasons)[:420])
            if state.get('automation', {}).get('protocol') == 2:
                from .studio_top_pick import choose
                index, evaluation = choose(studio.settings, {**state,
                    'writing_visual_payload':remote.get('payload',{}),
                    'benchmark_analysis': remote['result'].get('benchmark',{}).get('analysis',{})}, valid)
                item = next(item for i,item in valid if i == index)
            else:
                index, item = valid[0]
                evaluation = {'reason':'버전이 일치하는 첫 번째 후보 자동 선택 · 내용 판단은 완성 영상에서'}
            if job.get('claim_token'):
                studio.store.assert_owned(job)
            _atomic_json(studio.folder(state['id']) / 'script-candidates.json', remote['result'])
            return {'text':item['text'], 'script_candidates':candidates, 'studio_job_id':request_id,
                    'benchmark_analysis':remote['result'].get('benchmark',{}).get('analysis',{}),
                    'selected_candidate':index, 'rewrite_review':item['rewrite_review'],
                    'top_pick':evaluation, 'selection_reason':evaluation['reason']}
        if remote['state'] in ('failed', 'cancelled', 'interrupted'):
            failure=remote.get('result') or {}
            if failure.get('error_reason')=='model_capacity':
                raise ModelServiceUnavailable(str(remote.get('error')),failure.get('retry_at'),failure.get('attempted',True))
            raise ValueError('대본 재가공 실패: ' + str(remote.get('error') or remote.get('message') or request_id)[:500])
        identity=(remote['state'],remote.get('progress'))
        if identity not in seen:
            seen.add(identity);watch.observe('states',len(seen))
        if remote['state']=='queued':watch.reset()
        adapter.jobs.observe_progress(request_id,watch)
        watch.check()
        message = '대본 재가공 · ' + str(remote.get('message') or remote['state'])[:250]
        progress = round(float(remote.get('progress') or 0) * 100)
        if (message, progress) != checkpoint.get('_last_progress'):
            change_claimed(studio.store, job, lambda s, db: s.update(message=message, progress=progress))
            checkpoint['_last_progress'] = (message, progress)
        time.sleep(2)
    raise RuntimeError('대본 생성 대기 시간 초과. 재시도하면 기존 내장 Codex 작업을 조회합니다.')


def _normalize_screen_text(raw) -> str:
    if isinstance(raw, list):
        return ' '.join(str(row.get('text', '')) if isinstance(row, dict) else str(row) for row in raw).strip()
    return str(raw or '').strip()


def _resolve_rewrite_manifest(studio, state, manifest):
    from pathlib import Path
    result = dict(manifest)
    settings = getattr(studio, 'settings', None)
    if settings:
        try:
            from .reference_context import post_caption
            full_cap = post_caption(settings, state)
            if full_cap and len(full_cap) > len(result.get('caption') or ''):
                result['caption'] = full_cap
        except Exception:
            pass
    if not result.get('screen_text') and state.get('transcript_path'):
        tpath = Path(state['transcript_path'])
        if tpath.is_file():
            try:
                tdata = json.loads(tpath.read_text(encoding='utf-8'))
                result['screen_text'] = _normalize_screen_text(tdata.get('screen_text', ''))
            except (OSError, ValueError, TypeError):
                pass
    def valid_visual_plan(plan):
        if not plan.get('visual_query_evidence'):
            return True  # Historical textual manifests retain their contract.
        try:
            from .source_visual_queries import plan_queries
            from .source_quality import sha256_file
            plan_queries(plan)
            return (state.get('reference_video')
                    and sha256_file(Path(state['reference_video'])) == plan['query_reference_sha256']
                    and plan['query_evidence']['caption'] == result.get('caption','')
                    and plan['query_evidence']['speech'] == state.get('reference_speech_text',state.get('original_text',''))
                    and plan['query_evidence']['screen_text'] == _normalize_screen_text(result.get('screen_text','')))
        except (OSError, ValueError, KeyError, TypeError):
            return False
    if result.get('product_evidence') and valid_visual_plan(result['product_evidence']):
        return result
    result.pop('product_evidence',None)
    shortcode = state.get('shortcode', '')
    if settings and shortcode and getattr(settings, 'source_dir', None):
        for candidate in sorted(Path(settings.source_dir).glob(f'{shortcode}-*/manifest.json'),
                                key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                cdata = json.loads(candidate.read_text(encoding='utf-8'))
                if cdata.get('product_evidence') and valid_visual_plan(cdata['product_evidence']):
                    result['product_evidence'] = cdata['product_evidence']
                    return result
            except (OSError, ValueError, TypeError):
                continue
    speech = state.get('original_text', '')
    fallback = state.get('product') or state.get('title', '')
    if identify_subject(result, speech, fallback) != '원작 중심 대상 미확인':
        return result
    if settings and getattr(settings, 'data_dir', None):
        try:
            from .source_planning import QUERY_PLAN_POLICY, cached_enrich_plan
            from .source_queries import product_query_plan
            caption = result.get('caption', '')
            screen_text = _normalize_screen_text(result.get('screen_text', ''))
            speech_raw = state.get('reference_speech_text', speech)
            ref_video = Path(state.get('reference_video', '')) if state.get('reference_video') else None
            from .source_quality import sha256_file
            ref_sha = sha256_file(ref_video) if ref_video and ref_video.is_file() else None
            plans_dir = Path(settings.data_dir) / 'source-query-plans'
            for sp in (speech_raw, speech):
                value = {'policy': QUERY_PLAN_POLICY, 'caption': caption, 'speech': sp,
                         'screen_text': screen_text, 'reference_sha256': ref_sha}
                identity = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                plan_path = plans_dir / (identity + '.json')
                if plan_path.is_file():
                    saved = json.loads(plan_path.read_text('utf-8'))
                    if (saved.get('input_sha256') == identity and saved.get('policy') == QUERY_PLAN_POLICY
                            and isinstance(saved.get('plan'), dict) and valid_visual_plan(saved['plan'])):
                        result['product_evidence'] = saved['plan']
                        return result
            # Equal captions cannot authorize another reference's search plan.
            # The exact SHA-bound cache above is the only query-cache fallback.
            if getattr(studio, '_lease', None) is not None and getattr(settings, 'source_query_model_enabled', False) and caption:
                transcript_ev = {'speech': speech_raw, 'screen_text': screen_text}
                base_plan = product_query_plan(caption, [], [], transcript_ev, [])
                enriched = cached_enrich_plan(settings, base_plan, caption, transcript_ev, reference_sha256=ref_sha)
                if isinstance(enriched, dict):
                    result['product_evidence'] = enriched
                    return result
        except Exception:
            pass
    return result


def identify_subject(manifest, speech, fallback):
    from .source_queries import product_query_plan
    caption = manifest.get('caption', '')
    text = caption+'\n'+speech
    from .source_planning import primary_subject
    # The accepted source manifest stores reviewed frame text with its query
    # evidence; it does not duplicate screen_text at the top level.
    query_evidence = manifest.get('product_evidence',{}).get('query_evidence',{})
    screen_text = _normalize_screen_text(manifest.get('screen_text') or query_evidence.get('screen_text',''))
    evidence = {'caption':caption, 'speech':speech, 'screen_text':screen_text}
    subject = primary_subject(manifest.get('product_evidence',{}).get('primary_subject'), evidence)
    if subject:
        return subject['name']
    # A cabinet's contents are not the promoted product. Require storage
    # evidence before resolving an implicit cabinet name from the narration.
    if re.search(r'진열장|장식장|진열.{0,35}(?:문|닫)|(?:문|닫).{0,35}진열', text, re.S):
        return '원목 진열장' if re.search(r'원목|대나무', text) else '진열장'
    # Direct wording takes precedence over broad visual catalog guesses.
    direct = product_query_plan(caption, [], [], {'speech':speech, 'screen_text':screen_text}, [])['products']
    products = direct or [p for p in manifest.get('product_evidence', {}).get('products', [])
                          if set(p.get('sources', [])) & {'caption','speech','screen_text'}]
    if products:
        return (products[0].get('ko') or products[0].get('en') or fallback)[:300]
    # Keep observed context when no category matches; never invent a model name.
    # A story introduction is not an unknown product's name. The full source
    # evidence still reaches the writer, while unresolved metadata stays honest.
    noun = re.sub(r'^[^가-힣A-Za-z0-9]+', '', str(fallback)).strip()
    if 2 <= len(noun) <= 50 and len(noun.split()) <= 6 and not re.search(
            r'댓글|남겨|DM|프로필|팔로우|숨김|메시지|파트너스|[.!?]|거예요|전화|티타임',noun,re.I):
        return noun
    return '원작 중심 대상 미확인'


def refresh_resolved_subject(state, manifest):
    """Replace an early display fallback only with actual reference evidence."""
    if state.get('product_override'):return False
    product=identify_subject(manifest,state.get('original_text',''),'')
    if not product or product=='원작 중심 대상 미확인' or product==state.get('product'):
        return False
    # A separately reviewed product name is no longer an early title fallback.
    # Replacing it with another noun from the same reference invalidates search
    # and review receipts whose scope includes this exact label.
    plan=manifest.get('product_evidence') or {}
    try:
        from .source_coverage import search_scope_for_state
        from .source_visual_queries import plan_queries
        from .source_search.strategy import normalize_query
        scope=search_scope_for_state(state)
        if (state.get('run_id') and plan.get('run_id')==state['run_id']
                and plan.get('search_context')==scope
                and scope.get('reference_sha256')
                and plan.get('query_reference_sha256')==scope['reference_sha256']):
            plan_queries(plan)
            names=(plan.get('search_identity') or {}).get('product_terms',{}).get('ko',[])
            if normalize_query(state.get('product','')) in {normalize_query(n) for n in names}:
                return False
    except (ValueError,KeyError,TypeError,OSError):
        pass  # Unverified names never freeze a potentially incorrect fallback.
    state.setdefault('product_resolution_history',[]).append({
        'previous':state.get('product'),'resolved':product,'at':time.time(),
        'primary_subject':manifest.get('product_evidence',{}).get('primary_subject'),
        'basis':'actual_reference_without_title_fallback'})
    state['product']=product
    return True


def main():
    from .config import load_settings
    from .studio import Studio
    studio = Studio(load_settings())
    if studio._lease is None:
        return
    # Keep the durable consumer available even when the dashboard is closed.
    try:
        while not studio.stop.wait(1):
            if studio.video_agents and studio.video_agents.restart_requested.is_set():break
    except KeyboardInterrupt:
        pass
    finally:
        studio.close()
    if studio.video_agents and studio.video_agents.restart_requested.is_set():
        import os,sys
        os.execv(sys.executable,[sys.executable,'-X','utf8','-m','hotpost.studio_automation'])


if __name__ == '__main__':
    main()
