"""Transactional outbox for per-video Markdown search and production evidence."""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta

LOG = logging.getLogger(__name__)


def ensure(db):
    db.execute('''CREATE TABLE IF NOT EXISTS production_record_outbox (
        task_id TEXT NOT NULL, run_key TEXT NOT NULL, snapshot TEXT NOT NULL,
        digest TEXT NOT NULL, pending INTEGER NOT NULL,
        PRIMARY KEY(task_id,run_key))''')


def queue(db, state):
    """Keep evidence in the same commit as its accepted production state."""
    acquisition = state.get('source_acquisition') or {}
    if not acquisition and not state.get('edits'):
        return
    material = {key: state.get(key) for key in (
        'id', 'run_id', 'status', 'script_id', 'approved_script_id', 'voice_id',
        'approved_voice_id', 'edit_id', 'source_policy', 'runs', 'scripts', 'voices',
        'edits', 'daily_quality', 'source_search_manifest_path') if key in state}
    material['sources'] = [{k: s.get(k) for k in ('id','url','original_url','sha256','path',
        'editing_eligible','usage_review','manual_usage_review')} for s in state.get('sources',[])]
    material['source_acquisition'] = {key: acquisition.get(key) for key in
        ('queries','rounds','core_search_plan','hold','waiting','receipt_wait')}
    from .production_control import owner_record
    owner=owner_record(db,state['id'])
    material['attempt_holds']=[*owner.get('hold_history',[]),
        *([owner['no_progress_hold']] if owner.get('no_progress_hold') else [])]
    snapshot = json.dumps(material, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(snapshot.encode()).hexdigest()
    db.execute('''INSERT INTO production_record_outbox VALUES(?,?,?,?,1)
        ON CONFLICT(task_id,run_key) DO UPDATE SET snapshot=excluded.snapshot,
        digest=excluded.digest,pending=1 WHERE digest<>excluded.digest''',
        (state['id'], state.get('run_id') or 'unassigned', snapshot, digest))


def _cell(value):
    return str('' if value is None else value).replace('|','\\|').replace('\r',' ').replace('\n','<br>')


def _time(value):
    if type(value) not in (int,float):
        return '미확인'
    try:
        return datetime.fromtimestamp(value, timezone(timedelta(hours=9))).isoformat()
    except (ValueError, OverflowError, OSError):
        return '미확인'


def render(state):
    from .source_attempts import search_execution
    a = state.get('source_acquisition') or {}
    run = state.get('run_id')
    rounds = [r for r in a.get('rounds') or [] if r.get('run_id')==run]
    attempts = [(r.get('job_id'), i, row) for r in rounds
                for i,row in enumerate(r.get('searches') or [])]
    historical = False
    if not attempts:
        # A merged old receipt cannot reconstruct the number/order of retries.
        historical = True
        attempts = [('historical',i,row) for i,row in enumerate(a.get('queries') or [])
                    if row.get('run_id')==run]
    manifest = state.get('source_search_manifest_path')
    plans = [];generated=[];candidates=[]
    if manifest and Path(manifest).is_file():
        saved = json.loads(Path(manifest).read_text('utf-8'))
        plan = saved.get('query_plan') or {**(saved.get('product_evidence') or {}),
                                         'query_details':saved.get('query_details') or []}
        owner = plan.get('query_owner') or (plan.get('visual_query_evidence') or {}).get('owner') or {}
        if owner.get('task_id')==state['id'] and owner.get('run_id')==run:
            plans = plan.get('query_details') or []
            generated=((plan.get('visual_query_evidence') or {}).get('proposal') or {}).get('queries') or []
            candidates=saved.get('candidates') or []
    lines = ['# 영상별 소스 검색어·활용 기록', '',
             f"- task: {state['id']} / run: {run or '미지정'} / 상태: {state.get('status')}",
             f'- 기존 검색 증거: {_cell(manifest)}',
             '- 시각은 Asia/Seoul(+09:00). 미확인 시각은 저장 시각으로 대체하지 않음.', '']
    lines += ['## 생성·선정 검색어', '', '| ID | 언어 | 원문 | 목적·핵심/보조 | 상태 |',
              '| --- | --- | --- | --- | --- |']
    for i,row in enumerate(plans):
        lines.append('| '+' | '.join(map(_cell, (i,row.get('language'),row.get('query'),
            row.get('search_purpose') or row.get('viewpoint'), '선정·실제 제출은 아래 증거 참조')))+' |')
    selected={(r.get('language'),r.get('query')) for r in plans}
    for i,row in enumerate(generated):
        if (row.get('language'),row.get('query')) not in selected:
            lines.append('| '+' | '.join(map(_cell,('proposal:'+str(row.get('id',i)),
                row.get('language'),row.get('query'),row.get('viewpoint'),
                '생성·미선정: 원본 proposal/review 및 현 계약 검증 결과 참조')))+' |')
    if not plans:
        lines += ['', '생성·선정 원본 계약 미확인. 실제 제출 문자열에서 계획을 역으로 만들지 않음.']
    lines += ['', '## 실제 검색 시도', '',
        '| 시도 ID | 언어 | 실제 제출 문자열 | 플랫폼 | 실제 제출 시각 | 결과·중단 사유 | 후보 수 | 증거 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']
    unique=set();submitted=0
    for job_id,i,row in attempts:
        receipt=search_execution(row);execution=row.get('execution') or {}
        sent=receipt['query_submitted']
        actual=execution.get('actual_input_value',execution.get('input_value',row.get('query')))
        if sent:
            unique.add((row.get('language'),actual));submitted+=1
        evidence=row.get('receipt_path') or row.get('debug_path') or manifest
        lines.append('| '+' | '.join(map(_cell, (f'{job_id}:{i}',row.get('language'),
            actual if sent else '미제출: '+str(row.get('query') or ''),row.get('provider'),
            _time(execution.get('submitted_at')) if sent else '',
            str(row.get('status'))+' / '+str(row.get('reason') or row.get('error') or receipt['basis']),
            row.get('candidates'),evidence)))+' |')
    lines += ['', f'- 실제 제출 고유 검색어 수: {len(unique)} / 확인된 제출 시도 수: {submitted}',
              '- 핵심/보조 목적은 원래 검색 행의 증거를 따름. 후보 발견·다운로드·채택·사용은 별개.']
    if historical:
        lines += ['- 과거 병합 이력만 존재: 재시도 총수·순서는 복원 불가. 위 수치는 확인된 이력 범위.']
    lines += ['', '## 발견 후보·다운로드·검토 결과', '',
        '| URL | 발견 검색어 | 플랫폼 | 다운로드 파일(채택과 별개) | 선택·제외 증거 |',
        '| --- | --- | --- | --- | --- |']
    for candidate in candidates:
        lines.append('| '+' | '.join(map(_cell,(candidate.get('url'),candidate.get('query'),
            candidate.get('platform') or candidate.get('provider'),candidate.get('downloaded_file'),
            json.dumps({'selected_for_zip':candidate.get('selected_for_zip'),
                        'rejection_reasons':candidate.get('rejection_reasons')},ensure_ascii=False))))+' |')
    lines += ['', '## 후보·현재 소스와 편집 사용 연결', '',
              '| 소스 ID | 원본 URL | 파일 | 채택 근거 | 계획 사용 구간 | 최종 QA 완료 |',
              '| --- | --- | --- | --- | --- | --- |']
    edit=next((e for e in state.get('edits') or [] if e.get('id')==state.get('edit_id')), {})
    plan={}
    if edit.get('plan_path') and Path(edit['plan_path']).is_file():
        plan=json.loads(Path(edit['plan_path']).read_text('utf-8'))
    shots={s['id']:s for s in plan.get('shots',[]) if s.get('id')}
    used={}
    for cut in plan.get('visual_cuts') or plan.get('beats') or []:
        sid=shots.get(cut.get('selected_shot_id'),{}).get('source_id')
        if sid:used.setdefault(sid,[]).append({k:cut.get(k) for k in ('start','end','source_start','source_end')})
    from .video_agent_context import completion
    done=completion(state)
    for source in state.get('sources') or []:
        lines.append('| '+' | '.join(map(_cell,(source['id'],source.get('original_url') or source.get('url'),
            source.get('path'),json.dumps(source.get('manual_usage_review') or source.get('usage_review'),ensure_ascii=False),
            json.dumps(used.get(source['id'],[]),ensure_ascii=False),
            bool(done and used.get(source['id'])))))+' |')
    lines += ['', '소스 행만으로 과거 모든 발견 후보·다운로드 시도 수를 추정하지 않음. '
              '기존 manifest와 검색 시도 증거에서 확인하며 미확인 연결은 미확인으로 유지.',
              '문제 근거와 해결/재개 기록: 같은 작업 폴더의 hold-*.md 및 DB production_attempt_* event.', '']
    for incident in state.get('attempt_holds',[]):
        lines += [f"- 보류 {incident['id']}: {incident.get('resolution_status')} / "
                  f"재개 결정 {incident.get('resume_decision_id','미확인')} / 영상 최종 QA {bool(done)}"]
    return '\n'.join(lines)


def flush(store):
    with store.connect() as db:
        rows=db.execute('SELECT * FROM production_record_outbox WHERE pending=1').fetchall()
    for row in rows:
        temporary=None
        try:
            state=json.loads(row['snapshot'])
            # IDs are data: derive the filename instead of interpolating run paths.
            run_key=hashlib.sha256(row['run_key'].encode()).hexdigest()[:24]
            task_key=hashlib.sha256(row['task_id'].encode()).hexdigest()[:24]
            folder=store.root/'production-records'/task_key;folder.mkdir(parents=True,exist_ok=True)
            target=folder/('source-search-'+run_key+'.md')
            temporary=target.with_suffix('.'+uuid.uuid4().hex+'.tmp')
            temporary.write_text(render(state),encoding='utf-8')
            with store.transaction() as db:
                current=db.execute('SELECT digest FROM production_record_outbox WHERE task_id=? AND run_key=?',
                                   (row['task_id'],row['run_key'])).fetchone()
                if not current or current['digest']!=row['digest']:continue
                temporary.replace(target)
                db.execute('UPDATE production_record_outbox SET pending=0 WHERE task_id=? AND run_key=? AND digest=?',
                           (row['task_id'],row['run_key'],row['digest']))
        except (OSError,ValueError,TypeError,KeyError,AttributeError):
            LOG.exception('Production Markdown projection pending: %s',row['task_id'])
        finally:
            if temporary and temporary.exists():temporary.unlink(missing_ok=True)


def write_attempt(settings, manifest_path):
    """Project a saved search checkpoint, including a not-yet-accepted attempt.

    No new search and no approval: the manifest/owner binding is the evidence.
    Accepted task state is projected separately by the transactional outbox.
    """
    temporary=None
    try:
        path=Path(manifest_path);saved=json.loads(path.read_text('utf-8'))
        plan=saved.get('query_plan') or saved.get('product_evidence') or {}
        owner=plan.get('query_owner') or (plan.get('visual_query_evidence') or {}).get('owner') or {}
        if not all(owner.get(k) for k in ('task_id','run_id','job_id')):return
        if any(saved.get(k) is not None and saved[k]!=owner[k] for k in ('task_id','run_id','job_id')):return
        state={'id':owner['task_id'],'run_id':owner['run_id'],
            'status':str(saved.get('status') or saved.get('audit_checkpoint') or 'attempt_record'),
            'source_search_manifest_path':str(path),'source_acquisition':{'rounds':[
                {'run_id':owner['run_id'],'job_id':owner['job_id'],'searches':saved.get('search_audit') or []}]}}
        task_key=hashlib.sha256(owner['task_id'].encode()).hexdigest()[:24]
        job_key=hashlib.sha256(owner['job_id'].encode()).hexdigest()[:24]
        folder=settings.data_dir/'studio'/'production-records'/task_key
        folder.mkdir(parents=True,exist_ok=True)
        target=folder/('source-attempt-'+job_key+'.md')
        temporary=target.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(render(state),encoding='utf-8');temporary.replace(target)
    except (OSError,ValueError,TypeError,KeyError,AttributeError):
        LOG.exception('Saved source attempt Markdown pending: %s',manifest_path)
    finally:
        if temporary and temporary.exists():temporary.unlink(missing_ok=True)


def write_proposal(settings, owner, proposal_path, review_path=None):
    """Record generation even when subsequent independent validation rejects it."""
    temporary=None
    try:
        proposal_path=Path(proposal_path)
        saved=json.loads(proposal_path.read_text('utf-8'))
        proposal=saved.get('proposal') or {}
        review=json.loads(Path(review_path).read_text('utf-8')) if review_path and Path(review_path).is_file() else None
        task_key=hashlib.sha256(owner['task_id'].encode()).hexdigest()[:24]
        key=hashlib.sha256((str(proposal_path)+str(owner['run_id'])).encode()).hexdigest()[:24]
        folder=settings.data_dir/'studio'/'production-records'/task_key;folder.mkdir(parents=True,exist_ok=True)
        target=folder/('query-proposal-'+key+'.md')
        lines=['# 생성 검색어 원본 기록','',
            f"- task/run/job: {owner['task_id']} / {owner['run_id']} / {owner['job_id']}",
            f'- 원본 제안: {proposal_path}',f'- 원본 검토: {review_path or "미실행"}',
            '- 상태: 생성 기록. 선정·실제 제출·후보 채택 승인과 구분.', '',
            '| ID | 언어 | 생성 원문 | 탐색 관점 |','| --- | --- | --- | --- |']
        for row in proposal.get('queries') or []:
            lines.append('| '+' | '.join(map(_cell,(row.get('id'),row.get('language'),
                row.get('query'),row.get('viewpoint'))))+' |')
        if review is not None:
            lines += ['', '## 저장된 독립 검토 결과 — 호스트 검증 통과와 별개', '',
                      '```json',json.dumps(review,ensure_ascii=False,indent=2),'```']
        temporary=target.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text('\n'.join(lines)+'\n',encoding='utf-8');temporary.replace(target)
    except (OSError,ValueError,TypeError,KeyError,AttributeError):
        LOG.exception('Generated query Markdown pending: %s',proposal_path)
    finally:
        if temporary and temporary.exists():temporary.unlink(missing_ok=True)
