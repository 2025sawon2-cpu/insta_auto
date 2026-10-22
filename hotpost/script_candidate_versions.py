"""Append corrective scripts without changing a production's selected artifacts."""
import copy
import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing

from .studio_store import Conflict


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def completed_writing_candidate(store, data):
    """Read a completed internal job; importing never starts a writer/model."""
    job_id, number = data.get('writing_job_id'), data.get('variant_number')
    if not isinstance(job_id, str) or not re.fullmatch(r'codex[0-9a-f]{32}', job_id):
        raise ValueError('완료된 내부 집필 작업 ID가 필요합니다.')
    if type(number) is not int or number not in (1, 2, 3):
        raise ValueError('집필 후보 번호는 1~3입니다.')
    root = store.root.parent / 'writing'
    with closing(sqlite3.connect((root/'jobs.sqlite3').resolve().as_uri()+'?mode=ro', uri=True)) as db:
        row = db.execute('SELECT kind,state,result FROM jobs WHERE id=?', (job_id,)).fetchone()
    if not row or row[0] != 'script' or row[1] != 'completed':
        raise ValueError('완료된 대본 작업만 후보로 가져올 수 있습니다.')
    result = json.loads(row[2])
    payload = json.loads((root/job_id/'payload.json').read_text('utf-8'))
    from .writing.contract import snapshot, receipt
    contract = receipt(snapshot())
    if (result.get('flow') != 'three-variants-v1' or result.get('writing_contract') != contract
            or receipt(payload.get('writing_contract', {})) != contract):
        raise Conflict('현재 집필 계약과 완료 작업의 계약이 다릅니다.')
    rows = [c for c in result.get('scripts', []) if c.get('variant_number') == number]
    if len(rows) != 1:
        raise ValueError('집필 작업의 후보 번호가 일치하지 않습니다.')
    candidate = copy.deepcopy(rows[0])
    text = candidate.get('text', '')
    if (not isinstance(text, str) or not text.strip() or len(text) > 3000
            or candidate.get('writing_contract') != contract
            or (candidate.get('quality_summary') or {}).get('script_sha256') != digest(text)):
        raise Conflict('완료 집필 후보의 본문·계약 SHA가 일치하지 않습니다.')
    lines = candidate.get('thumbnail_lines')
    if not isinstance(lines, list) or len(lines) != 2 or any(not isinstance(x, str) or not x.strip() for x in lines):
        raise ValueError('완료 후보의 두 줄 썸네일 문구가 없습니다.')
    return candidate, payload


def add_candidate(store, task_id, data):
    imported = payload = None
    if data.get('writing_job_id'):
        imported, payload = completed_writing_candidate(store, data)
        if data.get('text') is not None and data['text'] != imported['text']:
            raise Conflict('완료 집필 원고와 다른 본문을 가져올 수 없습니다.')
        data = {**data, 'text': imported['text'], 'writing_contract': imported['writing_contract'],
                'reference_sha256': digest(payload['reference_script'])}
    text = str(data.get('text', '')).strip()
    if not text or len(text) > 3000:
        raise ValueError('대본은 1~3000자로 입력하세요.')
    reference_hash = str(data.get('reference_sha256', ''))
    contract = data.get('writing_contract', {})
    if (not isinstance(contract, dict) or not contract.get('version') or
            len(str(contract.get('sha256', ''))) != 64):
        raise ValueError('작성 기준의 버전과 해시가 필요합니다.')
    notes = data.get('review_notes', [])
    if not isinstance(notes, list) or len(notes) > 30 or any(not isinstance(n, str) or len(n) > 1000 for n in notes):
        raise ValueError('대본 검토 기록을 확인하세요.')
    identity_input = reference_hash + '\n' + contract['sha256'] + '\n' + text
    legacy_identity = None
    if imported:
        identity_input += '\n' + data['writing_job_id']
        legacy_identity = digest(identity_input)
        identity_input += '\nvariant:' + str(data['variant_number'])
    identity = digest(identity_input)

    def same_revision(candidate):
        if candidate.get('revision_id') == identity:
            return True
        # Preserve imports saved before variant identity was included. A
        # different variant with identical narration still owns its metadata.
        return bool(imported and candidate.get('revision_id') == legacy_identity
                    and candidate.get('writing_job_id') == data['writing_job_id']
                    and candidate.get('writing_variant_number') == data['variant_number'])
    with store.transaction() as db:
        state = store.get(task_id, db)
        reference = state.get('reviewed_original_text', state.get('original_text', ''))
        if not reference or reference_hash != digest(reference):
            raise Conflict('원본 발화가 변경되었습니다. 새 원본과 대조한 뒤 후보를 저장하세요.')
        if imported:
            from .source_quality import sha256_file
            from pathlib import Path
            source = Path(state.get('reference_video') or '__missing__')
            if not source.is_file() or sha256_file(source) != payload.get('reference_video_sha256'):
                raise Conflict('집필에 사용한 원본 영상과 현재 제작 원본 SHA가 다릅니다.')
        candidates = state.get('script_candidates', [])
        if any(same_revision(c) for c in candidates):
            return copy.deepcopy(state)
        if data.get('revision') is not None and data['revision'] != state['revision']:
            raise Conflict('제작 정보가 변경되었습니다. 최신 상태에서 다시 저장하세요.')
        if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind='rewrite' AND status IN ('queued','running')", (task_id,)).fetchone():
            raise Conflict('대본 생성이 진행 중입니다. 현재 생성 결과가 저장된 뒤 후보를 추가하세요.')
        archived = next((c for c in state.get('script_candidate_revisions', [])
                         if same_revision(c)), None)
        candidate = copy.deepcopy(archived) if archived else {
            'text': text, 'title': '원본 대조 수정안', 'origin': 'agent_corrective_revision',
            'revision_id': identity, 'created': time.time(),
            'reference_sha256': reference_hash, 'script_sha256': digest(text),
            'writing_contract': copy.deepcopy(contract),
            'review_notes': list(notes), 'user_approved': False,
            'editorial_review': {'status': 'not_evaluated', 'advisory_only': True},
        }
        if imported and archived is None:
            candidate = {**copy.deepcopy(imported), **{
                'revision_id': identity, 'created': time.time(), 'origin': 'codex_internal_import',
                'reference_sha256': reference_hash, 'script_sha256': digest(text),
                'writing_job_id': data['writing_job_id'], 'writing_variant_number': data['variant_number'],
                'review_notes': list(notes), 'user_approved': False}}
        state.setdefault('script_candidates', []).append(candidate)
        # An immutable archive survives subsequent regeneration of the main list.
        if archived is None:
            state.setdefault('script_candidate_revisions', []).append(copy.deepcopy(candidate))
        store.event(db, task_id, 'add-script-candidate', {'revision_id': candidate['revision_id'], 'selected': False})
        store.save(db, state)
        return copy.deepcopy(state)
