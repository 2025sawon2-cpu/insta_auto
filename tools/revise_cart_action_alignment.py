"""Versioned cart correction after dense action-direction review; no queue restart."""
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
from hotpost.source_quality import sha256_file
from hotpost.source_presentation import POLICY, review_scope
from hotpost.source_finder import probe_video
from hotpost.studio import Studio
from hotpost.studio_workflow import init_run, snapshot
from tools import build_tiktok_rework as build
from tools.recover_daily_materials import ROOT as DAILY
from tools.rework_tiktok_batch import save

ROOT = DAILY.parent / 'daily-cart-actions-20261011'
OLD = DAILY.parent / 'daily-cart-clean-20261011'
CODE = 'DeTJ6HbKCdF'
EDIT = 'daily-cart-actions-20261011-v4'
DEFINITIONS = [
    ('folded-cart', '7633755703873817877', 37.2, 40.0, [.13, .481, .74, .044],
     '접이식 다리가 이미 수납된 상판 아래쪽을 보여준 뒤 뒤집어 바퀴로 굴리는 낮은 카트가 됨. 다리를 접는 순간 자체는 보이지 않음.'),
    ('parasol-fit', '7633755703873817877', 34.45, 36.45, [.13, .481, .74, .044],
     '상판 구멍에 파라솔을 꽂고 펼쳐 테이블 위를 가리는 동작.'),
    ('outdoor-use', '7619137069176130832', 12.85, 16.0, [.02, .745, .96, .11],
     '야외 테이블 위에 컵과 음식을 놓고 과일을 손질하는 사용 모습.')]


def configure():
    build.root = lambda code: ROOT / code / 'final'
    original = build.boundary
    build.boundary = lambda c, action, **kw: original(c, action, quality_revision='cart-action-direction-v4-caption-v2', **kw)
    bins = next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']


def clips():
    r = build.root(CODE)
    r.mkdir(parents=True, exist_ok=True)
    rows = json.loads((DAILY / CODE / 'discovery.json').read_text('utf-8'))['candidates']
    items = []
    for name, video, start, end, band, observation in DEFINITIONS:
        row = next(x for x in rows if x['url'].endswith('/' + video))
        raw = Path(row['path'])
        target = r / 'clips' / (name + '.mp4')
        target.parent.mkdir(exist_ok=True)
        vf = 'scale=720:1280,setsar=1,fps=30'
        x, y, w, h = [int(n * k) // 2 * 2 for n, k in zip(band, [720, 1280, 720, 1280])]
        vf += f',split[base][txt];[txt]crop={w}:{h}:{x}:{y},boxblur=12:2[blur];[base][blur]overlay={x}:{y}'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-t', str(end - start),
            '-i', str(raw), '-an', '-vf', vf, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', str(target)], check=True)
        meta = probe_video(target)
        frames = []
        for i, ratio in enumerate((.05, .35, .65, .95)):
            second = (meta['duration'] - .05) * ratio
            frame = target.with_name(name + f'-{i}.jpg')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(second), '-i', str(target),
                            '-frames:v', '1', str(frame)], check=True)
            frames.append({'path': str(frame.resolve()), 'timestamp': second, 'sha256': sha256_file(frame)})
        items.append({'id': 'cart-action-v4-' + name, 'name': name, 'path': str(target.resolve()),
            'sha256': sha256_file(target), 'video_meta': meta, 'original_sha256': sha256_file(raw),
            'original_path': str(raw.resolve()), 'original_interval': {'start': start, 'end': end},
            'url': row['url'], 'provider': 'tiktok', 'rights': row['rights'], 'source_role': 'core',
            'proposed_observation': observation, 'evidence_frames': frames,
            'pending_visual_review': True, 'caption_softening_band': band, 'watermark_masks': []})
    save(r / 'proposed-sources.json', items)
    sheet = Image.new('RGB', (720, 1035), '#222')
    draw = ImageDraw.Draw(sheet)
    for i, s in enumerate(items):
        for k, f in enumerate(s['evidence_frames']):
            with Image.open(f['path']) as im:
                im.thumbnail((180, 320)); sheet.paste(im, (180 * k, 345 * i + 25))
            draw.text((180 * k + 2, 345 * i + 2), f"{s['name']} {f['timestamp']:.2f}s", fill='white')
    sheet.save(r / 'clip-review.jpg', quality=94)
    print('Three bounded clips await actual visual review.', flush=True)


def approve():
    r = build.root(CODE)
    items = json.loads((r / 'proposed-sources.json').read_text('utf-8'))
    for s in items:
        s.update(pending_visual_review=False, editing_eligible=True, blur_required=False,
            source_quality='reviewed-portrait-action-v4', presentation_review_required=False,
            relevance_review_required=False,
            functional_review={'reviewed': True, 'source_sha256': s['sha256'], 'same_core_function': True,
                'context_usable': True, 'observed_actions': [s['proposed_observation']],
                'context_usage_limits': ['같은 기능의 제품. 정확한 SKU·다리 접기 순간·차까지 이동을 입증하지 않음.'],
                'evidence_frames': [f['path'] for f in s['evidence_frames']], 'reviewer': 'codex_session_visual_review'},
            visual_review={'reviewer': 'codex_session_visual_review', 'reviewed_at': time.time(),
                'scope': 'dense original frames and four decoded derivative frames',
                'observation': s['proposed_observation'], 'evidence_frames': s['evidence_frames']})
        s['presentation_review'] = {'policy': POLICY, 'reviewed': True,
            'source_sha256': s['sha256'], 'scope': review_scope(s), 'usable': True,
            'quality_usable': True, 'action_preserved': True,
            'observations': [s['proposed_observation']], 'evidence_frames': s['evidence_frames'],
            'reviewer': 'codex_session_visual_review'}
    save(r / 'proposed-sources.json', items)


def prepare():
    r = build.root(CODE)
    items = json.loads((r / 'proposed-sources.json').read_text('utf-8'))
    assert all(not s['pending_visual_review'] and s['editing_eligible'] for s in items)
    p = json.loads((OLD / CODE / 'final/timeline.json').read_text('utf-8'))
    # Keep the old immutable plan; this new plan corrects the observation.
    wrong = next(s for s in p['shots'] if s['id'] == 'shot-fold-legs')
    wrong.update(observation='이 구간은 휴대 후 다리를 펼쳐 테이블을 설치하는 동작. 접는 동작이 아님.',
                 action_review_correction='dense frame review contradicted earlier sparse observation')
    bad_source = next(s for s in p['sources'] if s['id'] == wrong['source_id'])
    bad_source['prior_action_review'] = copy.deepcopy(bad_source.get('functional_review'))
    bad_source['proposed_observation'] = wrong['observation']
    bad_source['functional_review']['observed_actions'] = [wrong['observation']]
    bad_source['visual_review']['observation'] = wrong['observation']
    bad_source['action_review_correction'] = {'status': 'supersedes_prior_observation',
        'reason': '0.2초 간격 실제 프레임에서 수납 상태→다리 밖으로 펼침 확인. 다리 접기 대사와 반대 동작.',
        'evidence': str((DAILY / CODE / 'cart-motion-review/7619137069176130832-1.3-0.2/sampling.json').resolve()),
        'checked_at': time.time()}
    bad_source['presentation_review']['scope'] = review_scope(bad_source)
    bad_source['presentation_review']['observations'] = [wrong['observation']]
    for s in items:
        p['sources'].append(s)
        p['shots'].append({'id': 'shot-v4-' + s['name'], 'source_id': s['id'], 'path': s['path'],
            'sha256': s['sha256'], 'start': 0, 'end': s['video_meta']['duration'],
            'frames': [f['path'] for f in s['evidence_frames']], 'observation': s['proposed_observation'],
            'source_role': 'core', 'context_usage_limits': s['functional_review']['context_usage_limits'],
            'evidence_status': 'dense-decoded-frame-action-review'})
    for first, last, name, relation in [(4, 5, 'folded-cart', 'context'),
            (13, 14, 'parasol-fit', 'direct'), (17, 19, 'outdoor-use', 'context')]:
        shot = next(s for s in p['shots'] if s['id'] == 'shot-v4-' + name)
        cursor = 0
        for beat in p['beats'][first - 1:last]:
            length = beat['end'] - beat['start']
            beat.update(options=[{'shot_id': shot['id'], 'relation': relation, 'reason': shot['observation'], 'reviewed': True}],
                selected_shot_id=shot['id'], source_start=cursor, source_end=cursor + length,
                relation=relation, reason=shot['observation'], needs_review=False)
            cursor += length
        assert cursor <= shot['end'] + .01
    p['visual_claims'].update(parasol_fitting_witnessed=True, leg_folding_moment_witnessed=False,
        folded_cart_conversion_witnessed=True, opposite_action_removed=True, new_raw_downloads=0)
    for key in ('rendered_clips', 'cover_path', 'sfx_path', 'output_dir'): p.pop(key, None)
    save(r / 'prepared-plan.json', p)
    for name in ('script.json', 'voice.json'): shutil.copy2(OLD / CODE / 'final' / name, r / name)
    studio = Studio(load_settings(), workers=False)
    save(r / 'baseline-state.json', studio.store.get('work-385b11cdea3040cb'))
    save(r / 'revision-origin.json', {'previous_video': str(OLD / CODE / 'final/preview.mp4'),
        'previous_plan': str(OLD / CODE / 'final/timeline.json'), 'tts_regenerated': False,
        'cover_preserved': True, 'changed_beats': [4, 5, 13, 14, 17, 18, 19],
        'new_raw_source_files_used': 0, 'old_sparse_observation_corrected': True})


def attach():
    r = build.root(CODE)
    qa = json.loads((r / 'verification.json').read_text('utf-8'))
    assert not qa['visual_review_pending']
    result = json.loads((r / 'render-result.json').read_text('utf-8'))
    plan = json.loads((r / 'timeline.json').read_text('utf-8'))
    studio = Studio(load_settings(), workers=False)
    current = studio.store.get('work-385b11cdea3040cb')
    if any(e['id'] == EDIT for e in current['edits']): return
    old = next(e for e in current['edits'] if e['id'] == current['edit_id'])
    assert old['id'] == 'daily-cart-clean-20261011-v3'
    save(r / 'state-before-attachment.json', current)
    edit = {k: v for k, v in result.items() if k != 'status'}
    edit.update(id=EDIT, script_id=old['script_id'], voice_id=old['voice_id'], status='completed',
        created=time.time(), export_path=result['preview_path'], export_verified=True, exported_at=time.time(),
        export_kind='web_render', registration_deferred=True, source_diversity=qa['metrics'],
        previous_edit_id=old['id'], revision_scope='action direction, parasol fitting, outdoor usage')
    def change(state, db):
        assert state['edit_id'] == old['id']
        state['edits'].append(edit)
        state['sources'].extend(copy.deepcopy(s) for s in plan['sources'] if not any(x['id'] == s['id'] for x in state['sources']))
        corrected = next(s for s in plan['sources'] if s['id'] == 'daily-DeTJ6HbKCdF-fold-legs')
        for i, source in enumerate(state['sources']):
            if source['id'] == corrected['id']: state['sources'][i] = copy.deepcopy(corrected)
        state.update(edit_id=EDIT, status='completed', progress=100,
            message='반대 동작 제거·실제 파라솔 시연·야외 사용 장면으로 보완', error='')
        state.setdefault('automation', {}).update(active=False, stage='completed')
        state.pop('run_id', None)
        run = init_run(state)
        used = {b['selected_shot_id'] for b in plan['beats']}
        ids = {s['source_id'] for s in plan['shots'] if s['id'] in used}
        sources = [copy.deepcopy(s) for s in plan['sources'] if s['id'] in ids]
        run['inputs']['source_ids'] = [s['id'] for s in sources]
        snapshot(state)
        run['artifacts']['sources'] = sources
        run.update(status='completed', completed=time.time(), revision_origin=EDIT)
        state['latest_completed_run_id'] = run['id']
        studio.store.event(db, state['id'], 'cart_action_alignment_revised', {'edit_id': EDIT,
            'previous_edit_id': old['id'], 'old_run_preserved': current['run_id']})
    saved = studio.store.change(current['id'], change)
    assert next(x for x in saved['runs'] if x['id'] == current['run_id']) == next(x for x in current['runs'] if x['id'] == current['run_id'])
    print('New cart action version attached; prior run unchanged.', saved['run_id'], flush=True)


def share():
    from tools import share_daily_rework as public
    codes = ('DeTaESASnr_', CODE, 'DeSvpmAsWgZ')
    for c in codes:
        rev = 'quality-v4.json' if c == 'DeSvpmAsWgZ' else 'quality-v3.json'
        (ROOT / c / 'writing').mkdir(parents=True, exist_ok=True)
        shutil.copy2(DAILY / c / 'writing' / rev, ROOT / c / 'writing' / rev)
        if c != CODE:
            target = ROOT / c / 'final'; target.mkdir(exist_ok=True)
            for name in ('cover.png', 'verification.json', 'timeline.json'): shutil.copy2(DAILY / c / 'final' / name, target / name)
    public.ROOT = ROOT
    public.main(codes=codes, port=8802, receipt_name='daily-cart-actions-20261011-three-share.json',
                writing_revisions={'DeSvpmAsWgZ': 'quality-v4.json'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['clips', 'approve', 'prepare', 'render', 'attach', 'share'])
    args = parser.parse_args()
    configure()
    if args.phase == 'render': build.render(CODE)
    else: globals()[args.phase]()
