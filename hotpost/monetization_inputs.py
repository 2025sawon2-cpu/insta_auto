"""Read-only, bounded discovery of finished videos with the user's fixed comment."""
from contextlib import closing
import sqlite3

from .post_publish import COMMENT_KEYWORD


def task_inputs(settings, store, requested=''):
    """Return summaries only; visiting this page never prepares a workflow."""
    account = store.automation()['account']
    with store.connect() as db:
        slot = db.execute('SELECT task_id FROM next_post_slots WHERE account=?', (account,)).fetchone()
        active = db.execute("SELECT task_id FROM records WHERE account=? AND json_extract(state,'$.stage')!='completed' ORDER BY updated DESC LIMIT 1", (account,)).fetchone()
    preferred = requested or (slot[0] if slot else active[0] if active else '')
    path = settings.data_dir / 'studio/studio.sqlite3'
    if not path.is_file():
        return {'tasks': [], 'selected_task_id': '', 'account': account, 'selection_error': '완성된 영상이 아직 없습니다.'}
    projection = """SELECT id,shortcode,json_extract(state,'$.title') AS title,updated
        FROM tasks WHERE json_extract(state,'$.status')='completed'
        AND COALESCE(json_extract(state,'$.automation.paused_by_user'),0)=0
        AND COALESCE(json_extract(state,'$.creation_mode'),'')!='photo_post'"""
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = list(db.execute(projection + ' ORDER BY updated DESC,id LIMIT 50'))
        if preferred and not any(row['id'] == preferred for row in rows):
            row = db.execute(projection + ' AND id=?', (preferred,)).fetchone()
            if row: rows.insert(0, row)
    tasks = []
    for row in rows:
        item = dict(row)
        item['title'] = item['title'] or item['shortcode']
        item.update(keyword=COMMENT_KEYWORD, comment_mode='fixed', keyword_error='')
        tasks.append(item)
    ids = {item['id'] for item in tasks}
    selected = preferred if preferred in ids else '' if requested else tasks[0]['id'] if tasks else ''
    return {'tasks': tasks, 'selected_task_id': selected, 'account': account,
            'discovery_account':store.automation().get('discovery_account',account),
            'selection_error': '지정한 완성 영상을 찾을 수 없습니다.' if requested and not selected else ''}
