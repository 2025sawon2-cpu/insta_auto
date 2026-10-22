"""Completion outbox written in the video transaction, with no external effects."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time


def _digest(path):
    try:
        with Path(path).open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    except (OSError, TypeError):
        return None


def record_completion(db, state, previous_status):
    if previous_status == 'completed' or state.get('status') != 'completed':
        return
    if state.get('creation_mode') in {'photo_post', 'self_shot'}:
        return
    edit = next((e for e in state.get('edits', []) if e.get('id') == state.get('edit_id')), {})
    script = next((s for s in state.get('scripts', []) if s.get('id') == state.get('script_id')), {})
    if not edit.get('export_verified') or not script.get('text'):
        return
    payload = dict(task_id=state['id'], shortcode=state['shortcode'], edit_id=edit['id'],
        video_sha256=_digest(edit.get('export_path')), plan_sha256=_digest(edit.get('plan_path')),
        script_id=script['id'], script_sha256=hashlib.sha256(script['text'].strip().encode()).hexdigest())
    db.execute('INSERT OR IGNORE INTO postproduction_outbox VALUES(?,?,?,?,?,?)',
        (state['id'], edit['id'], json.dumps(payload, ensure_ascii=False), 'pending', '', time.time()))
