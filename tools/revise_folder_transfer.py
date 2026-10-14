"""Actual USB connection/file copy at storage cues, keeping prior draft versions."""
import argparse
import copy
import json
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
from tools import revise_cart_youtube_actions as environment
from tools.rework_tiktok_batch import save

CODE = 'DeSoiZvyyqj'
WORK = 'work-df891c7f6d48490e'
ROOT = Path('data/folder-transfer-quality-20261011-v7')
OLD = Path('data/folder-quality-20261011-v6')
DAILY = Path('data/daily-rework-20261011') / CODE
EDIT = 'folder-transfer-quality-20261011-v7'
PREVIOUS = 'folder-quality-20261011-v6'


def read(path):
    return json.loads(Path(path).read_text('utf-8'))


def configure():
    environment.ROOT = ROOT
    environment.EDIT = EDIT
    environment.configure()


def clips():
    raw = (DAILY / 'videos/7636068417656589600.mp4').resolve()
    reviewed = read(DAILY / 'review/7636068417656589600/visual-review.json')
    assert reviewed['actual_visual_review'] and sha256_file(raw) == reviewed['source_sha256']
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(raw), '-f', 'null', '-'],
                   check=True, capture_output=True)
    final = build.root(CODE)
    final.mkdir(parents=True, exist_ok=True)
    rows = []
    sheet = Image.new('RGB', (960, 904), '#222')
    draw = ImageDraw.Draw(sheet)
    definitions = [('phone-usb', 8.12, 9.98, '노란 폴더형 케이스와 휴대폰을 USB-C 케이블로 연결한 모습'),
                   ('pc-copy', 12.70, 14.12, 'PC 파일 복사 진행 창의 용량과 진행 막대가 움직이는 모습')]
    for j, (name, start, end, observation) in enumerate(definitions):
        target = final / 'clips' / (name + '-v2.mp4')
        target.parent.mkdir(exist_ok=True)
        if target.exists():
            raise RuntimeError('Existing derivative retained; use a new version')
        # Remove numeric promotion captions only. Preserve the folder/cable and
        # actual PC progress window; these clips do not verify advertised speed.
        vf = 'scale=720:1280,setsar=1,fps=30'
        band = [100, 800, 540, 145] if name == 'phone-usb' else [110, 810, 570, 155]
        x, y, w, h = band
        vf += f',split[base][txt];[txt]crop={w}:{h}:{x}:{y},boxblur=24:2[blur];[base][blur]overlay={x}:{y}'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-t', str(end-start),
            '-i', str(raw), '-an', '-vf', vf, '-c:v', 'libx264', '-preset', 'veryfast',
            '-crf', '18', str(target)], check=True, capture_output=True)
        meta = probe_video(target)
        frames = []
        for k, fraction in enumerate((.02, .35, .65, .98)):
            t = (meta['duration'] - .04) * fraction
            frame = target.with_name(name + f'-v2-{k}.jpg')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(t), '-i', str(target),
                            '-frames:v', '1', str(frame)], check=True, capture_output=True)
            frames.append({'path': str(frame), 'timestamp': t, 'sha256': sha256_file(frame)})
            with Image.open(frame) as im:
                im.thumbnail((240, 426)); sheet.paste(im, (k*240, j*452+25))
            draw.text((k*240+2, j*452+2), f'{name} {t:.2f}s', fill='white')
        rows.append({'id': EDIT + '-' + name, 'name': name, 'path': str(target),
            'sha256': sha256_file(target), 'video_meta': meta, 'original_path': str(raw),
            'original_sha256': reviewed['source_sha256'], 'original_interval': {'start': start, 'end': end},
            'url': 'https://www.tiktok.com/@nunoagonia/video/7636068417656589600',
            'provider': 'tiktok', 'rights': 'unknown-check-before-reuse', 'source_role': 'context',
            'proposed_observation': observation, 'evidence_frames': frames,
            'pending_visual_review': True, 'editing_eligible': False,
            'preprocessed_blur_regions_px': [band]})
    sheet.save(final / 'clip-review-v2.jpg', quality=95)
    save(final / 'proposed-sources-v2.json', rows)
    print('Two bounded portrait clips await actual review', flush=True)


def prepare():
    final = build.root(CODE)
    if (final / 'prepared-plan.json').exists():
        raise RuntimeError('Existing prepared version retained')
    reviewed = read(final / 'clips-reviewed.json')
    sources = read(final / 'proposed-sources-v2.json')
    sources.append(read(final / 'phone-files-proposed.json'))
    assert reviewed['reviewed_source_sha256'] == {s['id']: s['sha256'] for s in sources}
    quality = read(DAILY / 'writing/quality-v7.json')
    assert not quality['human_review_pending']
    selected = next(s for s in quality['scripts'] if s['number'] == 2)
    plan = read(OLD / CODE / 'final/timeline.json')
    assert selected['text'] == read(OLD / CODE / 'final/script.json')['text']
    for source in sources:
        assert sha256_file(Path(source['path'])) == source['sha256']
        for frame in source['evidence_frames']:
            assert sha256_file(Path(frame['path'])) == frame['sha256']
        limits = ['폰 뒤 부착·휴대폰 사진 이동의 직접 증거가 아님.',
                  'PC 복사 창의 파일은 사진으로 확인되지 않음. 속도·용량·같은 SKU를 보증하지 않음.']
        source.update(pending_visual_review=False, editing_eligible=True, blur_required=False,
            source_quality='reviewed-portrait-context', presentation_review_required=False,
            relevance_review_required=False)
        source['functional_review'] = {'reviewed': True, 'source_sha256': source['sha256'],
            'same_core_function': False, 'context_usable': True, 'context_usage_limits': limits,
            'observed_actions': [source['proposed_observation']],
            'evidence_frames': [f['path'] for f in source['evidence_frames']],
            'reviewer': 'codex_session_visual_review'}
        source['presentation_review'] = {'policy': POLICY, 'reviewed': True,
            'source_sha256': source['sha256'], 'scope': review_scope(source), 'usable': True,
            'quality_usable': True, 'action_preserved': True,
            'observations': [source['proposed_observation']], 'evidence_frames': source['evidence_frames'],
            'reviewer': 'codex_session_visual_review'}
        plan['sources'].append(source)
        plan['shots'].append({'id': 'shot-' + source['name'], 'source_id': source['id'],
            'path': source['path'], 'sha256': source['sha256'], 'start': 0,
            'end': source['video_meta']['duration'], 'frames': [f['path'] for f in source['evidence_frames']],
            'observation': source['proposed_observation'], 'source_role': 'context',
            'context_usage_limits': limits, 'evidence_status': 'actual-bounded-portrait-review'})
    for number, name in [(11, 'phone-usb'), (12, 'pc-copy'), (13, 'phone-files')]:
        shot = next(s for s in plan['shots'] if s['id'] == 'shot-' + name)
        beat = plan['beats'][number-1]
        reason = shot['observation'] + ' · 저장과 연결을 보여주는 맥락이며 사진 파일 복사로 단정하지 않음'
        beat.update(selected_shot_id=shot['id'], relation='context', reason=reason,
            options=[{'shot_id': shot['id'], 'relation': 'context', 'reason': reason, 'reviewed': True}])
    for key in ('layout', 'background_path'):
        plan['cover_spec'].pop(key, None)
    plan['cover_spec'].update(lines=selected['thumbnail_lines'],
        copy_review={'reviewer': 'codex_session_editorial_review',
                     'hook_review': selected['thumbnail_mechanism'],
                     'source_review': 'Previously inspected closed physical yellow folder in hands'})
    plan['thumbnail_lines'] = selected['thumbnail_lines']
    for key in ('rendered_clips', 'cover_path', 'sfx_path', 'output_dir'):
        plan.pop(key, None)
    save(final / 'prepared-plan.json', plan)
    for name in ('script.json', 'voice.json'):
        shutil.copy2(OLD / CODE / 'final' / name, final / name)
    writing = ROOT / CODE / 'writing'; writing.mkdir(exist_ok=True)
    shutil.copy2(DAILY / 'writing/quality-v7.json', writing / 'quality-v7.json')
    current = Studio(load_settings(), workers=False).store.get(WORK)
    assert current['edit_id'] == PREVIOUS
    save(final / 'baseline-state.json', current)
    save(final / 'revision-origin.json', {'changed_beats': [11, 12, 13],
        'script_and_voice_preserved': True, 'tts_regenerated': False,
        'original_phone_interval': [8.12, 9.98], 'original_pc_copy_interval': [12.70, 14.12],
        'original_phone_files_interval': [25.83, 26.85],
        'thumbnail_revision': str(DAILY / 'writing/quality-v7.json'),
        'photo_copy_and_back_mount_not_claimed_verified': True})


def attach():
    final = build.root(CODE)
    qa = read(final / 'verification.json')
    assert qa['actual_visual_review'] and not qa['visual_review_pending']
    result, plan = read(final / 'render-result.json'), read(final / 'timeline.json')
    studio = Studio(load_settings(), workers=False)
    current = studio.store.get(WORK)
    if any(e['id'] == EDIT for e in current['edits']):
        return
    assert current['edit_id'] == PREVIOUS
    old = next(e for e in current['edits'] if e['id'] == PREVIOUS)
    edit = {k: v for k, v in result.items() if k != 'status'}
    edit.update(id=EDIT, script_id=old['script_id'], voice_id=old['voice_id'], status='completed',
        created=time.time(), export_path=result['preview_path'], export_verified=True,
        export_kind='web_render', registration_deferred=True, source_diversity=qa['metrics'],
        previous_edit_id=PREVIOUS, review_draft=True, source_coverage_complete=False,
        source_limit='휴대폰 사진 복사·폰 뒤 부착 장면 보완 필요')
    def change(state, db):
        assert state['edit_id'] == PREVIOUS
        state['edits'].append(edit)
        state['sources'].extend(copy.deepcopy(s) for s in plan['sources']
                               if not any(x['id'] == s['id'] for x in state['sources']))
        state.update(edit_id=EDIT, status='draft_review', progress=100, error='',
                     message='저장 대사에 실제 휴대폰 연결과 PC 파일 복사 장면을 배치한 검토본')
        state.setdefault('automation', {}).update(active=False, stage='source_wait')
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
        run.update(status='review', quality_draft=True, source_coverage_complete=False)
        state['quality_revision_path'] = str((DAILY / 'writing/quality-v7.json').resolve())
        studio.store.event(db, state['id'], 'folder_transfer_revision',
                           {'edit_id': EDIT, 'previous_edit_id': PREVIOUS})
    saved = studio.store.change(WORK, change)
    assert all(next(r for r in saved['runs'] if r['id'] == p['id']) == p for p in current['runs'])
    assert saved['script_id'] == current['script_id'] and saved['voice_id'] == current['voice_id']
    save(final / 'attachment.json', {'task_id': WORK, 'edit_id': EDIT, 'run_id': saved['run_id'],
        'prior_runs_unchanged': True, 'script_and_voice_ids_preserved': True})
    print('Folder transfer draft attached; prior runs retained', saved['run_id'], flush=True)


def share():
    from tools import share_daily_rework as public
    public.ROOT = ROOT
    public.TITLES[CODE] = '실물 폴더 저장 케이스 · 연결·복사 장면 보완'
    public.main(codes=(CODE,), port=8813, receipt_name='folder-transfer-quality-20261011-v7-share.json',
                writing_revisions={CODE: 'quality-v7.json'}, review_codes=(CODE,))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['clips', 'prepare', 'render', 'attach', 'share'])
    args = parser.parse_args()
    configure()
    if args.phase == 'render':
        if (build.root(CODE) / 'render-result.json').exists():
            raise RuntimeError('Existing render retained; use a new version')
        build.render(CODE)
    else:
        globals()[args.phase]()
