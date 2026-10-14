"""Replace two opening beats with reviewed loaded walking, preserving prior runs."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from PIL import Image, ImageDraw
from hotpost.config import load_settings
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file
from hotpost.source_presentation import POLICY, review_scope
from hotpost.studio import Studio
from hotpost.studio_workflow import init_run, snapshot
from tools import build_tiktok_rework as build
from tools.rework_tiktok_batch import save

CODE = 'DeTJ6HbKCdF'
TASK = 'work-385b11cdea3040cb'
ROOT = Path('data/daily-cart-opening-20261011-v7')
OLD = Path('data/daily-cart-youtube-20261011-v6')
RAWROOT = Path('data/daily-rework-20261011') / CODE / 'youtube-observed-kVz3rckivWQ'
EDIT = 'daily-cart-opening-motion-20261011-v7'
PREVIOUS = 'daily-cart-youtube-actions-20261011-v6'


def read(path):
    return json.loads(path.read_text('utf-8'))


def configure():
    build.root = lambda code: (ROOT / code / 'final').resolve()
    original = build.boundary
    build.boundary = lambda code, action, **kw: original(code, action, quality_revision=EDIT, **kw)
    bins = next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']


def clips():
    receipt = read(RAWROOT / 'source-reception.json')
    assert receipt['completed'] and receipt['browser_reception']['full_decode_passed']
    raw = Path(receipt['path'])
    assert sha256_file(raw) == receipt['sha256']
    final = build.root(CODE)
    target = final / 'clips/loaded-walk-v7b.mp4'
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise RuntimeError('Existing version retained; do not overwrite')
    start, end = 26.70, 29.10
    # Visible Chinese subtitle only, above the loaded boxes. No logo removal.
    vf = 'scale=1080:1920,setsar=1,fps=30,split[base][txt];[txt]crop=720:174:180:810,boxblur=18:2[blur];[base][blur]overlay=180:810'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-t', str(end-start),
                    '-i', str(raw), '-an', '-vf', vf, '-c:v', 'libx264', '-preset',
                    'veryfast', '-crf', '18', str(target)], check=True)
    sheet = Image.new('RGB', (1080, 984), '#222')
    draw = ImageDraw.Draw(sheet)
    frames = []
    for i, timestamp in enumerate((.03, .5, 1, 1.45, 1.9, 2.3)):
        frame = target.with_name(f'loaded-walk-v7b-{i}.jpg')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(timestamp), '-i', str(target),
                        '-frames:v', '1', str(frame)], check=True, capture_output=True)
        frames.append({'path': str(frame.resolve()), 'timestamp': timestamp, 'sha256': sha256_file(frame)})
        with Image.open(frame) as im:
            im.thumbnail((270, 480))
            sheet.paste(im, (i % 4 * 270, i // 4 * 492 + 12))
        draw.text((i % 4 * 270 + 3, i // 4 * 492), f'{timestamp:.2f}s', fill='white')
    source = {'id': 'cart-opening-v7-loaded-walk', 'name': 'loaded-walk-v7',
        'path': str(target.resolve()), 'sha256': sha256_file(target), 'video_meta': probe_video(target),
        'original_path': str(raw.resolve()), 'original_sha256': receipt['sha256'],
        'original_interval': {'start': start, 'end': end}, 'url': receipt['url'], 'provider': 'youtube',
        'rights': receipt['rights'], 'source_role': 'core', 'evidence_frames': frames,
        'proposed_observation': '상자 두 개가 놓인 낮은 테이블 카트를 남성이 손잡이로 끌며 야외에서 걸어가는 동작',
        'pending_visual_review': True, 'editing_eligible': False,
        'caption_softening_band': [180/1080, 810/1920, 720/1080, 174/1920],
        'watermark_masks': [], 'independent_filming_origin_unverified': True}
    save(final / 'proposed-source.json', source)
    sheet.save(final / 'clip-review.jpg', quality=94)


def prepare():
    final = build.root(CODE)
    review = read(final / 'clip-reviewed.json')
    assert review['reviewed'] and review['quality_usable'] and review['loaded_walking_witnessed']
    source = read(final / 'proposed-source.json')
    source.update(pending_visual_review=False, editing_eligible=True, blur_required=False,
        source_quality='reviewed-portrait-action', presentation_review_required=False, relevance_review_required=False)
    limits = ['동일 기능의 유사 테이블 카트. 정확한 SKU 및 이동 목적지가 차인지는 미확인.',
              '원본 360×640 확대 영상. 독립 촬영자와 상업 이용 허가는 미확인.']
    source['functional_review'] = {'reviewed': True, 'source_sha256': source['sha256'],
        'same_core_function': True, 'context_usable': True, 'observed_actions': [source['proposed_observation']],
        'context_usage_limits': limits, 'evidence_frames': [f['path'] for f in source['evidence_frames']],
        'reviewer': 'codex_session_visual_review'}
    source['visual_review'] = {'reviewed_at': time.time(), 'reviewer': 'codex_session_visual_review',
        'scope': '16 uniform raw frames, 32 dense action frames and 6 full-size portrait derivative frames',
        'observation': source['proposed_observation'], 'evidence_frames': source['evidence_frames']}
    source['presentation_review'] = {'policy': POLICY, 'reviewed': True, 'source_sha256': source['sha256'],
        'scope': review_scope(source), 'usable': True, 'quality_usable': True, 'action_preserved': True,
        'observations': [source['proposed_observation']], 'evidence_frames': source['evidence_frames'],
        'reviewer': 'codex_session_visual_review'}
    plan = read(OLD / CODE / 'final/timeline.json')
    plan['sources'].append(source)
    shot = {'id': 'shot-v7-loaded-walk', 'source_id': source['id'], 'path': source['path'],
        'sha256': source['sha256'], 'start': 0, 'end': source['video_meta']['duration'],
        'frames': [f['path'] for f in source['evidence_frames']], 'observation': source['proposed_observation'],
        'source_role': 'core', 'context_usage_limits': limits, 'evidence_status': 'dense-decoded-frame-action-review'}
    plan['shots'].append(shot)
    cursor = 0
    for beat in plan['beats'][1:3]:
        length = beat['end'] - beat['start']
        beat.update(selected_shot_id=shot['id'], source_start=cursor, source_end=cursor + length,
            relation='direct', reason=shot['observation'], needs_review=False,
            options=[{'shot_id': shot['id'], 'relation': 'direct', 'reason': shot['observation'], 'reviewed': True}])
        cursor += length
    assert cursor <= shot['end']
    for key in ('rendered_clips', 'cover_path', 'sfx_path', 'output_dir'):
        plan.pop(key, None)
    plan['visual_claims'].update(opening_loaded_walking_witnessed=True, walking_to_car_witnessed=False)
    save(final / 'prepared-plan.json', plan)
    for name in ('script.json', 'voice.json'):
        shutil.copy2(OLD / CODE / 'final' / name, final / name)
    save(final / 'baseline-state.json', Studio(load_settings(), workers=False).store.get(TASK))
    save(final / 'revision-origin.json', {'previous_edit_id': PREVIOUS, 'changed_beats': [2, 3],
        'tts_regenerated': False, 'cover_preserved': True, 'new_completed_downloads': 1,
        'source_receipt': str((RAWROOT / 'source-reception.json').resolve()),
        'independent_filming_origin_unverified': True, 'opening_change': 'loaded static state to actual walking'})


def attach():
    final = build.root(CODE)
    qa, plan, result = read(final/'verification.json'), read(final/'timeline.json'), read(final/'render-result.json')
    assert qa.get('actual_visual_review') and not qa['visual_review_pending']
    studio = Studio(load_settings(), workers=False)
    current = studio.store.get(TASK)
    if any(e['id'] == EDIT for e in current['edits']):
        return
    assert current['edit_id'] == PREVIOUS
    old = next(e for e in current['edits'] if e['id'] == PREVIOUS)
    save(final/'state-before-attachment.json', current)
    edit = {k:v for k,v in result.items() if k != 'status'}
    edit.update(id=EDIT, script_id=old['script_id'], voice_id=old['voice_id'], status='completed',
        created=time.time(), export_path=result['preview_path'], export_verified=True, exported_at=time.time(),
        export_kind='web_render', registration_deferred=True, source_diversity=qa['metrics'],
        previous_edit_id=PREVIOUS, review_draft=True, final_quality_passed=False,
        revision_scope='Two opening beats show real loaded walking; script, voice and cover preserved')
    def change(state, db):
        assert state['edit_id'] == PREVIOUS
        state['edits'].append(edit)
        state['sources'].extend(copy.deepcopy(s) for s in plan['sources'] if not any(x['id']==s['id'] for x in state['sources']))
        state.update(edit_id=EDIT, status='completed', progress=100, message='도입부에 실제 적재 후 걷는 장면을 배치', error='')
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
        studio.store.event(db, TASK, 'cart_opening_motion_revised', {'edit_id': EDIT, 'previous_edit_id': PREVIOUS})
    saved = studio.store.change(TASK, change)
    assert all(next(r for r in saved['runs'] if r['id']==prior['id'])==prior for prior in current['runs'])
    save(final/'attachment.json', {'edit_id': EDIT, 'run_id': saved['run_id'], 'prior_runs_unchanged': True})
    print('New opening attached; prior runs preserved:', saved['run_id'], flush=True)


def share():
    from tools import share_daily_rework as public
    writing = ROOT / CODE / 'writing'
    writing.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OLD / CODE / 'writing/quality-v3.json', writing/'quality-v3.json')
    public.ROOT = ROOT
    public.main(codes=(CODE,), port=8811, receipt_name='daily-cart-opening-20261011-v7-share.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['clips', 'prepare', 'render', 'attach', 'share'])
    args = parser.parse_args()
    configure()
    if args.phase == 'render':
        build.render(CODE)
    else:
        globals()[args.phase]()
