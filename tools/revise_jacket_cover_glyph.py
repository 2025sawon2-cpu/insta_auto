"""Version only cover punctuation; retain approved speech, audio and all runs."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import time

from hotpost.config import load_settings
from hotpost.source_quality import sha256_file
from hotpost.studio import Studio
from hotpost.studio_workflow import init_run, snapshot
from tools import build_tiktok_rework as build
from tools import revise_cart_youtube_actions as environment
from tools.rework_tiktok_batch import save

CODE = 'DeSvpmAsWgZ'
ROOT = Path('data/daily-jacket-cover-20261011-v5')
OLD = Path('data/daily-rework-20261011')
EDIT = 'daily-jacket-cover-glyph-20261011-v5'
WORK = 'work-ea4d11c896714ac1'


def configure():
    environment.ROOT = ROOT
    environment.EDIT = EDIT
    environment.configure()


def prepare():
    final = build.root(CODE)
    if (final/'prepared-plan.json').exists():
        raise RuntimeError('Keep the existing revision; do not overwrite it')
    final.mkdir(parents=True, exist_ok=True)
    old = OLD/CODE/'final'
    plan = json.loads((old/'timeline.json').read_text('utf-8'))
    assert plan['cover_spec']['lines'][0] == '흰 몸판·검은 어깨'
    plan['cover_spec']['lines'][0] = '흰 몸판에 검은 어깨'
    plan['cover_spec']['copy_review']['display_correction'] = (
        '도현이 지원하지 않는 중간점을 연결 조사로 바꿈. 제품·갈등·편향·대본은 동일.')
    for key in ('rendered_clips', 'cover_path', 'sfx_path', 'output_dir'):
        plan.pop(key, None)
    save(final/'prepared-plan.json', plan)
    for name in ('script.json', 'voice.json'):
        shutil.copy2(old/name, final/name)
    save(final/'baseline-state.json', Studio(load_settings(),workers=False).store.get(WORK))
    save(final/'revision-origin.json', {
        'previous_video': str((old/'preview.mp4').resolve()),
        'scope': 'thumbnail unsupported punctuation only', 'new_downloads': 0,
        'script_changed': False, 'tts_regenerated': False, 'story_or_bias_changed': False,
        'old_lines': ['흰 몸판·검은 어깨', '다른 걸로 바꾸라고?'],
        'new_lines': plan['cover_spec']['lines']})


def attach():
    final = build.root(CODE)
    qa = json.loads((final/'verification.json').read_text('utf-8'))
    assert not qa['visual_review_pending']
    assert qa['unchanged_body_and_audio_verified']
    result = json.loads((final/'render-result.json').read_text('utf-8'))
    studio = Studio(load_settings(), workers=False)
    current = studio.store.get(WORK)
    if any(edit['id'] == EDIT for edit in current['edits']):
        print('Version already attached; no duplicate run', flush=True)
        return
    baseline = json.loads((final/'baseline-state.json').read_text('utf-8'))
    assert current['edit_id'] == baseline['edit_id']
    old = next(e for e in current['edits'] if e['id'] == current['edit_id'])
    edit = {k:v for k,v in result.items() if k != 'status'}
    edit.update(id=EDIT, script_id=old['script_id'], voice_id=old['voice_id'],
        status='completed', created=time.time(), export_path=result['preview_path'],
        export_verified=True, export_kind='web_render', registration_deferred=True,
        source_diversity=qa['metrics'], previous_edit_id=old['id'],
        revision_scope='DoHyeon missing punctuation corrected; speech and body identical')
    def change(state, db):
        assert state['edit_id'] == old['id']
        state['edits'].append(edit)
        state.update(edit_id=EDIT,status='completed',progress=100,error='',
            message='썸네일 네모 글자 수정 · 기존 대본·음성·편집 보존')
        state.setdefault('automation',{}).update(active=False,stage='completed')
        parent = state.pop('run_id', None)
        run = init_run(state)
        if parent: run['parent_id'] = parent
        snapshot(state)
        previous_run = next((r for r in current['runs'] if r['id'] == parent), None)
        if previous_run:
            run['artifacts']['sources'] = copy.deepcopy(previous_run['artifacts'].get('sources', []))
        run.update(status='completed', completed=time.time(), revision_origin=EDIT)
        state['latest_completed_run_id'] = run['id']
        studio.store.event(db,WORK,'thumbnail_glyph_correction',{'edit_id':EDIT,'previous_edit_id':old['id']})
    saved = studio.store.change(WORK,change)
    assert all(next(r for r in saved['runs'] if r['id']==prior['id']) == prior for prior in current['runs'])
    assert saved['scripts'] == current['scripts'] and saved['voices'] == current['voices']
    save(final/'attachment-verification.json',{'edit_id':EDIT,'run_id':saved['run_id'],
        'prior_runs_unchanged':True,'scripts_unchanged':True,'voices_unchanged':True,
        'preview_sha256':sha256_file(Path(result['preview_path']))})
    print('Cover-only version attached; prior runs/scripts/voices unchanged',saved['run_id'],flush=True)


def share():
    from tools import share_daily_rework as public
    codes = ('DeTaESASnr_', 'DeTJ6HbKCdF', CODE)
    for code in codes:
        origin = Path('data/daily-cart-youtube-20261011-v6') if code=='DeTJ6HbKCdF' else OLD
        revision = 'quality-v4.json' if code==CODE else 'quality-v3.json'
        writing = ROOT/code/'writing'; writing.mkdir(parents=True,exist_ok=True)
        shutil.copy2(origin/code/'writing'/revision,writing/revision)
        if code != CODE:
            final = ROOT/code/'final';final.mkdir(exist_ok=True)
            for name in ('cover.png','verification.json','timeline.json'):
                shutil.copy2(origin/code/'final'/name,final/name)
    public.ROOT=ROOT
    public.TITLES[CODE] = '노스페이스 패딩 · 썸네일 표시 보완'
    public.main(codes=codes,port=8808,receipt_name='daily-jacket-cover-20261011-v5-three-share.json',
        writing_revisions={CODE:'quality-v4.json'})


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['prepare','render','attach','share'])
    args=parser.parse_args();configure()
    if args.phase=='render':build.render(CODE)
    else:globals()[args.phase]()
