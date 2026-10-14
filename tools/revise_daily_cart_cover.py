"""Review a clearer cart cover in a separate render, preserving every old edit."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import time

from hotpost.config import load_settings
from hotpost.source_quality import sha256_file
from hotpost.studio import Studio
from tools import build_tiktok_rework as build
from tools.recover_daily_materials import ROOT as OLD_ROOT
from tools.rework_tiktok_batch import save

ROOT = OLD_ROOT.parent / 'daily-cover-quality-20261011'
CODE = 'DeTJ6HbKCdF'
EDIT_ID = 'daily-cart-cover-20261011-v2'


def configure():
    build.root = lambda code: ROOT / code / 'final'
    original = build.boundary
    build.boundary = lambda c, action, **kw: original(
        c, action, quality_revision='cart-recognizable-cover-v2-caption-v2', **kw)
    bins = next(Path(os.environ['LOCALAPPDATA']).glob(
        'Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']


def prepare():
    old = OLD_ROOT / CODE / 'final'
    target = build.root(CODE)
    target.mkdir(parents=True, exist_ok=True)
    plan = json.loads((old / 'timeline.json').read_text('utf-8'))
    preview = json.loads((OLD_ROOT / CODE / 'cover-quality-v2/expand/cover-preview-result.json').read_text('utf-8'))
    plan['cover_spec'] = preview['cover_spec']
    plan['cover_spec']['source']['review_reason'] = (
        'Actual full-size preview reviewed: recognizable table and extension action, '
        'no old-caption softening band; earlier leg-closeup did not identify the product.')
    # All body windows and the selected narration are deliberately reused.
    assert plan['beats'] == json.loads((old / 'timeline.json').read_text('utf-8'))['beats']
    save(target / 'prepared-plan.json', plan)
    for name in ('script.json', 'voice.json', 'baseline-state.json'):
        shutil.copy2(old / name, target / name)
    save(target / 'revision-origin.json', {
        'previous_plan': str(old / 'timeline.json'),
        'previous_plan_sha256': sha256_file(old / 'timeline.json'),
        'previous_video': str(old / 'preview.mp4'),
        'changed': ['first-frame cover background'],
        'new_source_downloads': 0, 'tts_regenerated': False})


def attach():
    target = build.root(CODE)
    verification = json.loads((target / 'verification.json').read_text('utf-8'))
    assert not verification['visual_review_pending']
    result = json.loads((target / 'render-result.json').read_text('utf-8'))
    baseline = json.loads((target / 'baseline-state.json').read_text('utf-8'))
    studio = Studio(load_settings(), workers=False)
    current = studio.store.get(baseline['id'])
    if any(e['id'] == EDIT_ID for e in current['edits']):
        print(CODE, 'cover revision already attached; no duplicate run', flush=True)
        return
    old_edit = next(e for e in current['edits'] if e['id'] == current['edit_id'])
    save(target / 'state-before-attachment.json', current)
    old_result = json.loads((OLD_ROOT / CODE / 'final/render-result.json').read_text('utf-8'))
    assert Path(old_edit['preview_path']).resolve() == Path(old_result['preview_path']).resolve()
    edit = {k: v for k, v in result.items() if k != 'status'}
    edit.update(id=EDIT_ID, script_id=old_edit['script_id'], voice_id=old_edit['voice_id'],
                status='completed', created=time.time(), export_path=result['preview_path'],
                export_verified=True, exported_at=time.time(), export_kind='web_render',
                registration_deferred=True, source_diversity=verification['metrics'],
                previous_edit_id=old_edit['id'], revision_scope='cover background only')

    def change(state, db):
        if any(e['id'] == EDIT_ID for e in state['edits']):
            return
        assert state['edit_id'] == old_edit['id'], 'Current edit changed; preserve it.'
        state['edits'].append(edit)
        state.update(edit_id=EDIT_ID, status='completed', progress=100,
                     message='제품 전체가 보이는 썸네일로 보완', error='')
        state.setdefault('automation', {}).update(active=False, stage='completed')
        from hotpost.studio_workflow import snapshot
        state.pop('run_id', None)
        run = snapshot(state)
        run.update(status='completed', completed=time.time())
        state['latest_completed_run_id'] = run['id']
        studio.store.event(db, state['id'], 'cart_cover_revised', {
            'edit_id': EDIT_ID, 'previous_edit_id': old_edit['id'],
            'tts_regenerated': False, 'body_windows_preserved': True})

    studio.store.change(baseline['id'], change)
    print(CODE, 'new cover revision attached; old edit preserved', flush=True)


def share():
    from tools import share_daily_rework as public
    codes = ('DeTaESASnr_', CODE, 'DeSvpmAsWgZ')
    for code in codes:
        (ROOT / code / 'writing').mkdir(parents=True, exist_ok=True)
        revision = 'quality-v4.json' if code == 'DeSvpmAsWgZ' else 'quality-v3.json'
        shutil.copy2(OLD_ROOT / code / 'writing' / revision, ROOT / code / 'writing' / revision)
        if code != CODE:
            target = ROOT / code / 'final'
            target.mkdir(exist_ok=True)
            for name in ('cover.png', 'verification.json', 'timeline.json'):
                shutil.copy2(OLD_ROOT / code / 'final' / name, target / name)
    public.ROOT = ROOT
    public.main(codes=codes, port=8800,
                receipt_name='daily-cover-quality-20261011-three-share.json',
                writing_revisions={'DeSvpmAsWgZ': 'quality-v4.json'})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['prepare', 'render', 'attach', 'share'])
    phase = parser.parse_args().phase
    configure()
    if phase == 'render':
        build.render(CODE)
    else:
        globals()[phase]()


if __name__ == '__main__':
    main()
