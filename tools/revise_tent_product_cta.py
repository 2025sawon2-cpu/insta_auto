"""Replace construction close-ups in the CTA, preserving narration and prior runs."""
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
from hotpost.studio_workflow import init_run, snapshot
from tools import build_tiktok_rework as build
from tools.rework_tiktok_batch import save

CODE = 'DeRIBMYzn0x'
ROOT = Path('data/tent-product-cta-20261011-v4')
OLD = Path('data/tiktok-quality-20261011-v2')
EDIT = 'tent-product-cta-20261011-v4'
PREVIOUS = 'tiktok-quality-20261011-v2-' + CODE


def read(path):
    return json.loads(path.read_text('utf-8'))


def configure():
    build.root = lambda code: (ROOT / code / 'final').resolve()
    original = build.boundary
    build.boundary = lambda code, action, **kw: original(code, action, quality_revision=EDIT, **kw)
    bins = next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']


def prepare():
    final = build.root(CODE)
    final.mkdir(parents=True, exist_ok=True)
    if (final / 'prepared-plan.json').exists():
        raise RuntimeError('Existing version retained; do not overwrite.')
    plan = read(OLD / CODE / 'final/timeline.json')
    shot = next(s for s in plan['shots'] if s['id'] == 'shot-sleep')
    # The renderer reallocates beat offsets. Constrain the actual reviewed shot
    # window, rather than supplying offsets which selection would discard.
    shot['start'] = 2.0
    assert sha256_file(Path(shot['path'])) == shot['sha256']
    source = next(s for s in plan['sources'] if s['id'] == shot['source_id'])
    for frame in source['evidence_frames']:
        assert sha256_file(Path(frame['path'])) == frame['sha256']
    # Start after the original sleeping/room crossfade: show the product whole.
    cursor = 2.0
    for beat in plan['beats'][14:17]:
        length = beat['end'] - beat['start']
        reason = '침대 텐트 전체와 아래 책상 조명이 함께 보이고, 마지막에는 텐트 안에 눕는 사용 모습. 숙면 효과 입증이 아닌 사용 상황.'
        beat.update(selected_shot_id=shot['id'], source_start=cursor, source_end=cursor + length,
                    relation='context', reason=reason, needs_review=False,
                    options=[{'shot_id': shot['id'], 'relation': 'context', 'reason': reason, 'reviewed': True}])
        cursor += length
    assert cursor <= shot['end']
    plan['cover_spec']['source']['reviewed'] = True
    for key in ('rendered_clips', 'cover_path', 'sfx_path', 'output_dir'):
        plan.pop(key, None)
    save(final / 'prepared-plan.json', plan)
    for name in ('script.json', 'voice.json'):
        shutil.copy2(OLD / CODE / 'final' / name, final / name)
    current = Studio(load_settings(), workers=False).store.get('work-e876a432d6354bf7')
    assert current['edit_id'] == PREVIOUS
    save(final / 'baseline-state.json', current)
    save(final / 'revision-origin.json', {'previous_edit_id': PREVIOUS, 'changed_beats': [15, 16, 17],
        'script_and_voice_preserved': True, 'tts_regenerated': False, 'new_downloads': 0,
        'review_scope': 'Four actual derivative frames and prior rendered cover/12 samples viewed',
        'selected_original_interval': [source['original_interval']['start'] + 2, source['original_interval']['start'] + cursor],
        'remaining': ['Actual hearing incomplete', 'Hook response unmeasured', 'Other products remain under review']})


def attach():
    final = build.root(CODE)
    qa = read(final / 'verification.json')
    assert qa.get('actual_visual_review') and not qa['visual_review_pending']
    result, plan = read(final / 'render-result.json'), read(final / 'timeline.json')
    studio = Studio(load_settings(), workers=False)
    current = studio.store.get('work-e876a432d6354bf7')
    if any(e['id'] == EDIT for e in current['edits']):
        return
    assert current['edit_id'] == PREVIOUS
    old = next(e for e in current['edits'] if e['id'] == PREVIOUS)
    edit = {k: v for k, v in result.items() if k != 'status'}
    edit.update(id=EDIT, script_id=old['script_id'], voice_id=old['voice_id'], status='completed', created=time.time(),
        export_path=result['preview_path'], export_verified=True, exported_at=time.time(), export_kind='web_render',
        registration_deferred=True, source_diversity=qa['metrics'], previous_edit_id=PREVIOUS,
        review_draft=True, final_quality_passed=False, revision_scope='Product usage rather than construction detail at CTA')
    def change(state, db):
        assert state['edit_id'] == PREVIOUS
        state['edits'].append(edit)
        state.update(edit_id=EDIT, status='completed', progress=100, message='마지막 댓글 요청에 침대 텐트 전체 사용 모습을 배치', error='')
        state.setdefault('automation', {}).update(active=False, stage='completed')
        parent = state.pop('run_id', None)
        run = init_run(state)
        if parent:
            run['parent_id'] = parent
        used = {b['selected_shot_id'] for b in plan['beats']}
        ids = {s['source_id'] for s in plan['shots'] if s['id'] in used}
        sources = [copy.deepcopy(s) for s in plan['sources'] if s['id'] in ids]
        run['inputs']['source_ids'] = [s['id'] for s in sources]
        snapshot(state)
        run['artifacts']['sources'] = sources
        run.update(status='completed', completed=time.time(), revision_origin=EDIT)
        state['latest_completed_run_id'] = run['id']
        studio.store.event(db, state['id'], 'tent_product_cta_revised', {'edit_id': EDIT, 'previous_edit_id': PREVIOUS})
    saved = studio.store.change(current['id'], change)
    assert all(next(r for r in saved['runs'] if r['id'] == prior['id']) == prior for prior in current['runs'])
    save(final / 'attachment.json', {'edit_id': EDIT, 'run_id': saved['run_id'], 'prior_runs_unchanged': True})
    print('Tent CTA attached; prior runs preserved:', saved['run_id'], flush=True)


def share():
    from tools import share_daily_rework as public
    writing = ROOT / CODE / 'writing'
    writing.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OLD / CODE / 'writing/quality.json', writing / 'quality.json')
    public.ROOT = ROOT
    public.TITLES[CODE] = '침대 암막 텐트 · 마지막 제품 장면 보완'
    public.main(codes=(CODE,), port=8810, receipt_name='tent-product-cta-20261011-v4-share.json',
                writing_revisions={CODE: 'quality.json'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['prepare', 'render', 'attach', 'share'])
    phase = parser.parse_args().phase
    configure()
    if phase == 'render':
        build.render(CODE)
        rendered = read(build.root(CODE) / 'timeline.json')
        assert rendered['beats'][14]['source_start'] == 2.0
        assert rendered['beats'][16]['source_end'] <= 5.0
        assert not rendered['footage_diversity']['frozen_beats']
    else:
        globals()[phase]()
