"""A separately reviewed cart edit using clean, observed loading/leg adjustment clips."""
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
from hotpost.source_presentation import POLICY, review_scope
from hotpost.source_quality import sha256_file
from hotpost.studio import Studio
from tools import build_tiktok_rework as build
from tools.recover_daily_materials import ROOT as DAILY
from tools.rework_tiktok_batch import save

ROOT = DAILY.parent / 'daily-cart-clean-20261011'
OLD = DAILY.parent / 'daily-cover-quality-20261011'
CODE = 'DeTJ6HbKCdF'
EDIT = 'daily-cart-clean-20261011-v3'
DEFINITIONS = [
    ('cart-loaded', 3.5, 6.6, '상판 위 수납 상자와 바퀴 잠금 부위를 손으로 보여줌. 보행 이동 장면은 아님.'),
    ('cart-loading', 2.5, 3.3, '작은 수납 상자를 카트 상판에 올리는 동작.'),
    ('cart-tilt', 6.6, 7.6, '상자를 실은 카트를 손잡이로 기울여 고정 상태를 보여줌. 차까지 걷는 장면은 아님.'),
    ('leg-adjust', 15.8, 18.4, '다리 끝 길이 조절 부위를 손으로 늘리고, 세운 테이블 다리 높이를 조정함.')]


def configure():
    build.root = lambda code: ROOT / code / 'final'
    original = build.boundary
    build.boundary = lambda c, action, **kw: original(c, action, quality_revision='clean-cart-source-v3-caption-v2', **kw)
    bins = next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']


def clips():
    r = build.root(CODE)
    r.mkdir(parents=True, exist_ok=True)
    data = json.loads((DAILY / CODE / 'discovery.json').read_text('utf-8'))
    row = next(x for x in data['candidates'] if x['url'].endswith('/7668652651189439764'))
    raw = Path(row['path'])
    items = []
    for name, start, end, observation in DEFINITIONS:
        path = r / 'clips' / (name + '.mp4')
        path.parent.mkdir(exist_ok=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-t', str(end - start),
            '-i', str(raw), '-an', '-vf', 'scale=720:1280,setsar=1,fps=30', '-c:v', 'libx264',
            '-preset', 'veryfast', '-crf', '18', str(path)], check=True)
        meta = probe_video(path)
        frames = []
        for i, ratio in enumerate((.05, .35, .65, .95)):
            second = (meta['duration'] - .05) * ratio
            frame = path.with_name(name + f'-{i}.jpg')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(second), '-i', str(path),
                            '-frames:v', '1', str(frame)], check=True)
            frames.append({'path': str(frame.resolve()), 'timestamp': second, 'sha256': sha256_file(frame)})
        items.append({'id': 'cart-clean-' + name, 'name': name, 'path': str(path.resolve()),
            'sha256': sha256_file(path), 'video_meta': meta, 'original_sha256': sha256_file(raw),
            'original_path': str(raw.resolve()), 'original_interval': {'start': start, 'end': end},
            'url': row['url'], 'provider': 'tiktok', 'rights': row['rights'], 'source_role': 'core',
            'proposed_observation': observation, 'evidence_frames': frames,
            'pending_visual_review': True, 'caption_softening_band': None, 'watermark_masks': []})
    save(r / 'proposed-sources.json', items)
    sheet = Image.new('RGB', (720, 1380), '#222')
    draw = ImageDraw.Draw(sheet)
    for i, source in enumerate(items):
        for k, frame in enumerate(source['evidence_frames']):
            with Image.open(frame['path']) as im:
                im.thumbnail((180, 320))
                sheet.paste(im, (180 * k, 345 * i + 25))
            draw.text((180 * k + 2, 345 * i + 2), f"{source['name']} {frame['timestamp']:.2f}s", fill='white')
    sheet.save(r / 'clip-review.jpg', quality=94)
    print('Four actual derivative clips await visual review.', flush=True)


def prepare():
    r = build.root(CODE)
    items = json.loads((r / 'proposed-sources.json').read_text('utf-8'))
    assert all(not x['pending_visual_review'] and x.get('editing_eligible') for x in items)
    p = json.loads((OLD / CODE / 'final/timeline.json').read_text('utf-8'))
    before = copy.deepcopy(p)
    for s in items:
        p['sources'].append(s)
        p['shots'].append({'id': 'shot-' + s['name'], 'source_id': s['id'], 'path': s['path'],
            'sha256': s['sha256'], 'start': 0, 'end': s['video_meta']['duration'],
            'frames': [f['path'] for f in s['evidence_frames']], 'observation': s['proposed_observation'],
            'source_role': 'core', 'context_usage_limits': ['정확한 SKU 미확정. 이동 거리·가격·하중 수치를 입증하지 않음.'],
            'evidence_status': 'actual-decoded-frame-review'})
    assignments = [(1, 3, 'cart-loaded', 'context'), (6, 6, 'cart-loading', 'direct'),
                   (7, 7, 'cart-tilt', 'context'), (8, 10, 'leg-adjust', 'direct')]
    for first, last, name, relation in assignments:
        shot = next(s for s in p['shots'] if s['id'] == 'shot-' + name)
        cursor = 0
        for beat in p['beats'][first - 1:last]:
            length = beat['end'] - beat['start']
            beat.update(options=[{'shot_id': shot['id'], 'relation': relation, 'reason': shot['observation'], 'reviewed': True}],
                selected_shot_id=shot['id'], source_start=cursor, source_end=cursor + length,
                relation=relation, reason=shot['observation'], needs_review=False)
            cursor += length
        assert cursor <= shot['end'] + .02
    # The remaining parasol cue uses a table context scene, not a witnessed fitting.
    for beat in p['beats'][12:14]:
        beat['relation'] = 'context'
        for option in beat['options']:
            option['relation'] = 'context'
    assert p['voice'] == before['voice'] and p['cues'] == before['cues']
    assert p['script_text'] == before['script_text'] and p['cover_spec'] == before['cover_spec']
    p['visual_claims'] = {'height_adjustment_witnessed': True, 'walking_to_car_witnessed': False,
                          'parasol_fitting_witnessed': False, 'new_raw_downloads': 1}
    for key in ('rendered_clips', 'cover_path', 'sfx_path', 'output_dir'):
        p.pop(key, None)
    save(r / 'prepared-plan.json', p)
    for name in ('script.json', 'voice.json', 'baseline-state.json'):
        shutil.copy2(OLD / CODE / 'final' / name, r / name)
    save(r / 'revision-origin.json', {'previous_video': str(OLD / CODE / 'final/preview.mp4'),
        'previous_plan': str(OLD / CODE / 'final/timeline.json'), 'tts_regenerated': False,
        'cover_preserved': True, 'changed_beats': [1, 2, 3, 6, 7, 8, 9, 10],
        'new_raw_source': items[0]['url'], 'source_files_added': 1})
    print('New clean cart body plan prepared; old edits and narration preserved.', flush=True)


def approve():
    r = build.root(CODE)
    items = json.loads((r / 'proposed-sources.json').read_text('utf-8'))
    for source in items:
        source.update(pending_visual_review=False, editing_eligible=True, blur_required=False,
            source_quality='reviewed-clean-portrait', presentation_review_required=False,
            relevance_review_required=False,
            functional_review={'reviewed': True, 'source_sha256': source['sha256'],
                'same_core_function': True, 'context_usable': True,
                'observed_actions': [source['proposed_observation']],
                'context_usage_limits': ['보행/이동 거리·파라솔 부착·가격·정확한 SKU를 이 장면이 입증하지 않음.'],
                'evidence_frames': [f['path'] for f in source['evidence_frames']],
                'reviewer': 'codex_session_visual_review'},
            visual_review={'reviewer': 'codex_session_visual_review', 'reviewed_at': time.time(),
                'scope': 'four actual decoded derivative frames plus original uniform/dense action frames',
                'observation': source['proposed_observation'], 'evidence_frames': source['evidence_frames']})
        source['presentation_review'] = {'policy': POLICY, 'reviewed': True,
            'source_sha256': source['sha256'], 'scope': review_scope(source),
            'usable': True, 'quality_usable': True, 'action_preserved': True,
            'observations': [source['proposed_observation']], 'evidence_frames': source['evidence_frames'],
            'reviewer': 'codex_session_visual_review'}
    save(r / 'proposed-sources.json', items)
    ledger = DAILY / CODE / 'discovery.json'
    data = json.loads(ledger.read_text('utf-8'))
    row = next(x for x in data['candidates'] if x['url'].endswith('/7668652651189439764'))
    row.update(visual_review_pending=False, usage_review={
        'status': 'reviewed_intervals_only', 'core_approved': True, 'editing_eligible': False,
        'whole_video_approved': False, 'source_sha256': items[0]['original_sha256'],
        'approved_derivative_clips': [s['path'] for s in items],
        'observed_core_actions': ['짐을 카트 상판에 올림', '다리 끝을 늘려 높이 조절'],
        'movement_limit': '기울여 고정 상태를 보여주는 장면이며 차까지 걷는 시연은 아님.',
        'exact_sku_confirmed': False, 'rights': row['rights'], 'checked_at': time.time()})
    save(ledger, data)
    save(DAILY / CODE / 'review/7668652651189439764/usage-review.json', row['usage_review'])
    print('Four derivative clips actually reviewed; precise cue relations retained.', flush=True)


def attach():
    r = build.root(CODE)
    qa = json.loads((r / 'verification.json').read_text('utf-8'))
    assert not qa['visual_review_pending']
    result = json.loads((r / 'render-result.json').read_text('utf-8'))
    baseline = json.loads((r / 'baseline-state.json').read_text('utf-8'))
    studio = Studio(load_settings(), workers=False)
    current = studio.store.get(baseline['id'])
    if any(e['id'] == EDIT for e in current['edits']):
        print('New cart edit already attached; no duplicate.', flush=True)
        return
    old = next(e for e in current['edits'] if e['id'] == current['edit_id'])
    assert old['id'] == 'daily-cart-cover-20261011-v2'
    save(r / 'state-before-attachment.json', current)
    plan = json.loads((r / 'timeline.json').read_text('utf-8'))
    edit = {k: v for k, v in result.items() if k != 'status'}
    edit.update(id=EDIT, script_id=old['script_id'], voice_id=old['voice_id'], status='completed',
        created=time.time(), export_path=result['preview_path'], export_verified=True, exported_at=time.time(),
        export_kind='web_render', registration_deferred=True, source_diversity=qa['metrics'],
        previous_edit_id=old['id'], revision_scope='clean source clips and witnessed leg adjustment')
    def change(state, db):
        assert state['edit_id'] == old['id']
        state['edits'].append(edit)
        for source in plan['sources']:
            if not any(s['id'] == source['id'] for s in state['sources']):
                state['sources'].append(source)
        state.update(edit_id=EDIT, status='completed', progress=100,
                     message='무자막 세로 소스와 실제 높이조절 동작으로 본문 보완', error='')
        state.setdefault('automation', {}).update(active=False, stage='completed')
        from hotpost.studio_workflow import snapshot
        state.pop('run_id', None)
        run = snapshot(state)
        run.update(status='completed', completed=time.time())
        state['latest_completed_run_id'] = run['id']
        studio.store.event(db, state['id'], 'cart_clean_sources_revised', {'edit_id': EDIT,
            'previous_edit_id': old['id'], 'tts_regenerated': False, 'new_source_files': 1})
    studio.store.change(baseline['id'], change)
    print('New reviewed cart source edit attached as separate version.', flush=True)


def repair_run():
    """Separate this manual revision from the prior run reused by snapshot()."""
    r = build.root(CODE)
    studio = Studio(load_settings(), workers=False)
    task = json.loads((r / 'baseline-state.json').read_text('utf-8'))['id']
    current = studio.store.get(task)
    correct = [run for run in current['runs'] if run.get('revision_origin') == EDIT]
    if correct:
        print('Separate clean-source run already recorded.', flush=True)
        return
    save(r / 'state-before-run-repair.json', current)
    old_plan = json.loads((OLD / CODE / 'final/timeline.json').read_text('utf-8'))
    new_plan = json.loads((r / 'timeline.json').read_text('utf-8'))
    old_edit = next(e for e in current['edits'] if e['id'] == 'daily-cart-cover-20261011-v2')
    def selected_sources(plan):
        used = {b['selected_shot_id'] for b in plan['beats']}
        ids = {s['source_id'] for s in plan['shots'] if s['id'] in used}
        return [copy.deepcopy(s) for s in plan['sources'] if s['id'] in ids]
    def change(state, db):
        assert state['edit_id'] == EDIT
        prior = next(run for run in state['runs'] if run['id'] == state['run_id'])
        assert prior['artifacts']['edit_id'] == EDIT
        # Existing old edit and exact old plan are authoritative; identify this
        # as a reconstructed snapshot, not an unchanged historical run receipt.
        prior['artifacts'].update(edit_id=old_edit['id'], sources=selected_sources(old_plan))
        prior['inputs']['source_ids'] = [s['id'] for s in prior['artifacts']['sources']]
        prior.update(status='completed', completed=old_edit['exported_at'],
            snapshot_reconstructed_from=old_edit['plan_path'],
            snapshot_repair_reason='manual revision helper reused current run; old edit/plan preserved')
        state.pop('run_id', None)
        from hotpost.studio_workflow import init_run, snapshot
        run = init_run(state)
        sources = selected_sources(new_plan)
        run['inputs']['source_ids'] = [s['id'] for s in sources]
        snapshot(state)
        run.update(status='completed', completed=time.time(), revision_origin=EDIT)
        state['latest_completed_run_id'] = run['id']
        studio.store.event(db, task, 'cart_manual_revision_run_separated', {
            'previous_run_id': prior['id'], 'new_run_id': run['id'], 'edit_id': EDIT,
            'prior_snapshot_reconstructed_from_existing_plan': True})
    saved = studio.store.change(task, change)
    assert any(run['artifacts']['edit_id'] == old_edit['id'] for run in saved['runs'])
    assert saved['latest_completed_run_id'] != current['latest_completed_run_id']
    print('Old cover run reconstructed from preserved artifacts; separate new run saved.', saved['latest_completed_run_id'], flush=True)


def share():
    from tools import share_daily_rework as public
    codes = ('DeTaESASnr_', CODE, 'DeSvpmAsWgZ')
    for code in codes:
        (ROOT / code / 'writing').mkdir(parents=True, exist_ok=True)
        revision = 'quality-v4.json' if code == 'DeSvpmAsWgZ' else 'quality-v3.json'
        shutil.copy2(DAILY / code / 'writing' / revision, ROOT / code / 'writing' / revision)
        if code != CODE:
            target = ROOT / code / 'final'
            target.mkdir(exist_ok=True)
            for name in ('cover.png', 'verification.json', 'timeline.json'):
                shutil.copy2(DAILY / code / 'final' / name, target / name)
    public.ROOT = ROOT
    public.main(codes=codes, port=8801, receipt_name='daily-cart-clean-20261011-three-share.json',
                writing_revisions={'DeSvpmAsWgZ': 'quality-v4.json'})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['clips', 'approve', 'prepare', 'render', 'attach', 'repair_run', 'share'])
    args = parser.parse_args()
    configure()
    if args.phase == 'render':
        build.render(CODE)
    else:
        globals()[args.phase]()


if __name__ == '__main__':
    main()
