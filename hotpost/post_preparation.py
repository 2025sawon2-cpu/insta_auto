"""Independent publication drafts; historical production files are read-only inputs."""
from __future__ import annotations
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
import time
from .post_preparation_content import build_copy
from .post_media_rules import without_opening_interjection

ACCOUNTS = ('mr.salrim', '__ariddaum__')
CHOICES = ('recommended', 'hook', 'curiosity', 'benefit')


class DraftConflict(ValueError):
    pass


def shortcode(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise ValueError('올바른 게시물을 선택하세요.')
    return value


class PostPreparation:
    def __init__(self, settings):
        self.root = settings.data_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'post-preparation.sqlite3'
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS drafts (
                shortcode TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                value TEXT NOT NULL, updated REAL NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS thumbnail_jobs (
                id TEXT PRIMARY KEY, shortcode TEXT NOT NULL, status TEXT NOT NULL,
                message TEXT NOT NULL, text TEXT NOT NULL, created REAL NOT NULL,
                updated REAL NOT NULL, owner_pid INTEGER NOT NULL, owner_birth REAL NOT NULL)''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _file(self, value):
        if not value:
            return None
        try:
            path = Path(value).resolve(strict=True)
            return path if path.is_file() and path.is_relative_to(self.root) else None
        except (OSError, ValueError, RuntimeError):
            return None

    def source(self, code):
        code = shortcode(code)
        historical = self.root / 'studio' / 'studio.sqlite3'
        state = {}
        if historical.is_file():
            with sqlite3.connect(historical.as_uri() + '?mode=ro', uri=True) as db:
                row = db.execute('SELECT state FROM tasks WHERE shortcode=?', (code,)).fetchone()
                if row:
                    state = json.loads(row[0])
        runs = {r['id']: r for r in state.get('runs', [])}
        completed = []
        for edit in state.get('edits', []):
            run = next((r for r in runs.values() if r.get('artifacts', {}).get('edit_id') == edit.get('id')
                        and r.get('status') == 'completed'), None)
            if edit.get('export_verified') and run and self._file(edit.get('export_path') or edit.get('preview_path')):
                completed.append((edit, run))
        chosen = next((pair for pair in completed if pair[1]['id'] == state.get('latest_completed_run_id')), None)
        if chosen is None and completed:
            chosen = max(completed, key=lambda pair: pair[1].get('completed') or pair[1].get('created') or 0)
        edit, run = chosen or ({}, {})
        plan = {}
        plan_path = self._file(edit.get('plan_path'))
        if plan_path and plan_path.stat().st_size <= 8 * 1024 * 1024:
            try:
                plan = json.loads(plan_path.read_text('utf-8'))
            except (OSError, ValueError):
                pass
        script_id = edit.get('script_id') or state.get('script_id')
        script = next((s.get('text', '') for s in state.get('scripts', []) if s.get('id') == script_id), '')
        spoken_text = plan.get('voice', {}).get('spoken_text') or script
        document = plan.get('thumbnail_document') or {}
        lines = plan.get('cover_spec', {}).get('lines')
        cover = '\n'.join(str(x) for x in lines) if isinstance(lines, list) else plan.get('cover_text', '')
        if not cover and isinstance(document.get('lines'), list):
            cover = '\n'.join(str(x) for x in document['lines'])
        media = {'reference': self._file(state.get('reference_video')),
                 'final': self._file(edit.get('export_path') or edit.get('preview_path')),
                 'cover': self._file(edit.get('cover_path'))}
        background = self._file(plan.get('cover_spec', {}).get('background_path'))
        font = (plan.get('cover_font_style') or plan.get('cover_spec', {}).get('font') or {}).get('font_path')
        font = Path(font) if font else None
        base_final = media['final']
        from .post_thumbnail import active_assets
        active = active_assets(self, code, edit.get('id'))
        rules = {}
        if active:
            media.update(final=self._file(active['final']), cover=self._file(active['cover']))
            cover = active['text']
            base_final = self._file(active.get('body_final')) or base_final
            spoken_text = active.get('spoken_text', spoken_text)
            rules = active.get('rules', {})
        # Copy drafts are normalized separately; this alone never certifies old audio.
        script = without_opening_interjection(spoken_text)
        return {'run_id': run.get('id'), 'edit_id': edit.get('id'), 'script': script,
                'cover_text': cover, 'media': media, 'media_version': active['version'] if active else None,
                'base_final': base_final, 'thumbnail_background': background, 'thumbnail_font': font,
                'spoken_text': spoken_text, 'publication_rules': rules,
                'thumbnail_style': plan.get('cover_spec', {}).get('style', {}),
                'thumbnail_ready': bool(base_final and background and font and font.is_file())}

    def defaults(self, code, source):
        options = dict.fromkeys(CHOICES, '')
        options['recommended'] = source['cover_text']
        for seeds in (Path(__file__).with_name('post_preparation_copy.json'), self.root / 'post-preparation-copy.json'):
            if not seeds.is_file():
                continue
            try:
                entry = json.loads(seeds.read_text('utf-8')).get(code, {})
                for key in CHOICES[1:]:
                    if isinstance(entry.get(key), str):
                        options[key] = entry[key][:120]
            except (OSError, ValueError, AttributeError):
                pass
        copy = build_copy(code, source['script'], options['benefit'])
        return {'selected_accounts': [], 'thumbnail_options': options, 'selected_thumbnail': 'recommended',
                **copy,
                'product_link': ''}

    def get(self, code):
        code = shortcode(code)
        source = self.source(code)
        with self.connect() as db:
            row = db.execute('SELECT * FROM drafts WHERE shortcode=?', (code,)).fetchone()
        draft = json.loads(row['value']) if row else self.defaults(code, source)
        from .post_thumbnail import job_status
        thumbnail = {**job_status(self, code), 'ready': source['thumbnail_ready'], 'applied_text': source['cover_text']}
        suffix = '?v=' + source['media_version'] if source['media_version'] else ''
        return {'shortcode': code, 'accounts': list(ACCOUNTS), 'draft': draft,
                'revision': row['revision'] if row else 0, 'updated': row['updated'] if row else None,
                'source_run_id': source['run_id'], 'source_edit_id': source['edit_id'],
                'thumbnail': thumbnail,
                'media': {key: f'/api/post-preparations/{code}/media/{key}' + (suffix if key in ('final','cover') else '') if value else None
                          for key, value in source['media'].items()}}

    def save(self, code, payload):
        code = shortcode(code)
        if not isinstance(payload, dict) or set(payload) != {'revision', 'draft'}:
            raise ValueError('올바른 초안이 필요합니다.')
        revision, value = payload['revision'], payload['draft']
        if type(revision) is not int or revision < 0 or not isinstance(value, dict):
            raise ValueError('올바른 초안 버전이 필요합니다.')
        fields = {'selected_accounts', 'thumbnail_options', 'selected_thumbnail', 'caption', 'pinned_comment', 'product_link'}
        if set(value) != fields:
            raise ValueError('초안의 입력 항목을 확인하세요.')
        accounts = value['selected_accounts']
        if not isinstance(accounts, list) or any(not isinstance(a, str) or a not in ACCOUNTS for a in accounts):
            raise ValueError('등록된 업로드 계정을 선택하세요.')
        options = value['thumbnail_options']
        if not isinstance(options, dict) or set(options) != set(CHOICES):
            raise ValueError('썸네일 문구 네 개를 확인하세요.')
        if any(not isinstance(x, str) or len(x) > 120 for x in options.values()):
            raise ValueError('썸네일 문구는 120자 이내로 입력하세요.')
        if value['selected_thumbnail'] not in CHOICES:
            raise ValueError('사용할 썸네일 문구를 선택하세요.')
        for key, limit in (('caption', 2200), ('pinned_comment', 2200), ('product_link', 2048)):
            if not isinstance(value[key], str) or len(value[key]) > limit:
                raise ValueError(f'{key} 입력 길이를 확인하세요.')
        value = {**value, 'selected_accounts': [a for a in ACCOUNTS if a in accounts]}
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM drafts WHERE shortcode=?', (code,)).fetchone()
            if (row['revision'] if row else 0) != revision:
                raise DraftConflict('다른 화면에서 초안이 변경됐어요. 입력을 복사한 뒤 다시 열어 주세요.')
            now = time.time()
            db.execute('INSERT OR REPLACE INTO drafts VALUES (?,?,?,?)',
                       (code, revision + 1, json.dumps(value, ensure_ascii=False), now))
        return {'revision': revision + 1, 'updated': now}

    def start_thumbnail(self, code, payload):
        from .post_thumbnail import start
        return start(self, shortcode(code), payload)

    def media(self, code, kind, version=None):
        code = shortcode(code)
        if kind not in ('reference', 'final', 'cover'):
            raise FileNotFoundError('영상을 찾을 수 없습니다.')
        if version and kind in ('final','cover'):
            if not re.fullmatch('[a-f0-9]{32}', version):
                raise FileNotFoundError('영상을 찾을 수 없습니다.')
            with self.connect() as db:
                found = db.execute("SELECT 1 FROM thumbnail_jobs WHERE id=? AND shortcode=? AND status='completed'", (version, code)).fetchone()
            path = self._file(self.root/'post-preparations'/code/version/('final.mp4' if kind=='final' else 'cover.png'))
            if not found or not path:
                raise FileNotFoundError('영상을 찾을 수 없습니다.')
            return path
        path = self.source(code)['media'][kind]
        if path is None:
            raise FileNotFoundError('영상 파일이 아직 없습니다.')
        return path
